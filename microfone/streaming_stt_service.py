"""StreamingSTTService — transcrição parcial contínua (Sprint 19).

Responsabilidade:
  - Consumir janelas de áudio da SlidingWindow.
  - Transcrever via STTExecutor (serializa acesso ao Whisper).
  - Comparar nova transcrição com a anterior (diff por prefixo).
  - Publicar SpeechPartial (primeira vez) ou SpeechPartialUpdated
    (apenas se o texto evoluiu).
  - NUNCA chama parser, NUNCA chama Holyrics, NUNCA publica
    ReferenceDetected.

Sprint 19 — Streaming Speech Pipeline:
  Este serviço permite que referências sejam detectadas ANTES do
  fim da fala. Ele transcreve continuamente a janela deslizante
  e publica o texto parcial para o IncrementalBiblicalParser
  consumir.

Janela incremental com sobreposição (Etapa 4 — decisão do usuário):
  A cada 400ms, a SlidingWindow extrai os últimos 6s de áudio.
  O StreamingSTTService transcreve essa janela e compara com a
  transcrição anterior. Se o prefixo for igual, apenas o sufixo
  novo é publicado em SpeechPartialUpdated.appended_text.

  Exemplo:
    Janela 1 (0-6s):  "Irmãos vamos abrir nossas Bíblias no evangelho de João"
    Janela 2 (0.4-6.4s): "Irmãos vamos abrir nossas Bíblias no evangelho de João capítulo três"
    Diff: "capítulo três" (novo)
    → SpeechPartialUpdated(text=completo, appended_text="capítulo três")

Thread Safety:
  - Roda na thread da SlidingWindow (callback on_window).
  - STTExecutor serializa acesso ao Whisper.
  - EventBus.publish é thread-safe.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from microfone.stt_executor import STTExecutor
from pipeline.bus import PipelineEventBus
from pipeline.events import SpeechPartial, SpeechPartialUpdated
from pipeline.metadata import EventMetadata

logger = logging.getLogger(__name__)

__all__ = ["StreamingSTTService"]


class StreamingSTTService:
    """Serviço de transcrição parcial contínua.

    Args:
        executor: STTExecutor que serializa acesso ao Whisper.
        bus: PipelineEventBus para publicar eventos.
        session_id: ID da sessão atual.
        sample_rate: taxa de amostragem do áudio (default 16000).
        min_text_change: tamanho mínimo de mudança para publicar
            SpeechPartialUpdated. Evita publicar por mudanças
            triviais (1-2 caracteres). Default 3.

    Lifecycle:
        start() — marca como ativo, reseta estado.
        stop()  — marca como inativo, publica partial final vazio.
        on_window(audio, timestamp) — callback da SlidingWindow.
    """

    def __init__(
        self,
        executor: STTExecutor,
        bus: PipelineEventBus,
        session_id: str,
        sample_rate: int = 16000,
        min_text_change: int = 3,
        min_rms: float = 0.005,
        min_confidence: float = 0.30,
    ) -> None:
        self._executor = executor
        self._bus = bus
        self._session_id = session_id
        self._sample_rate = sample_rate
        self._min_text_change = min_text_change
        # Sprint 21.3.2 — anti-alucinação.
        # Causa raiz das transcrições fantasmas: o StreamingSTT envia
        # janelas de 6s do RingBuffer que podem ser puro silêncio. O
        # Whisper (especialmente via DirectML/ONNX, que não suporta
        # no_speech_threshold nem vad_filter) alucina frases do seu
        # corpus de treinamento (legendas de TV): "Legenda por Sônia
        # Ruberti", "Abertura", "A CIDADE NO BRASIL", etc.
        #
        # Duas camadas de proteção, ambas atacando a causa raiz:
        # 1. min_rms: energia mínima do áudio (RMS). Silêncio tem RMS ≈ 0;
        #    fala tem RMS > 0.01. Se RMS < min_rms, o áudio é silêncio e
        #    não é enviado ao Whisper — evita alucinação na origem.
        # 2. min_confidence: confiança mínima do STT. Alucinações têm
        #    confiança ~0.12-0.20; transcrições legítimas > 0.50. Se
        #    confidence < min_confidence, o texto é descartado — camada
        #    extra para alucinações que passam pelo RMS (ex.: ruído de
        #    fundo com energia suficiente para não ser silêncio, mas
        #    sem fala real).
        self._min_rms = min_rms
        self._min_confidence = min_confidence

        # Estado do fluxo parcial atual.
        self._active = False
        self._current_text: str = ""
        self._current_correlation_id: str | None = None
        self._current_causation_id: str | None = None
        self._current_language: str = "pt"

        # Métricas.
        self._total_windows = 0
        self._total_transcriptions = 0
        self._total_partials_published = 0
        self._total_updates_published = 0
        self._total_skipped_no_change = 0
        self._total_skipped_empty = 0
        self._total_latency_ms = 0
        # Sprint 21.3.2 — métricas de anti-alucinação.
        self._total_skipped_silence = 0
        self._total_skipped_low_confidence = 0

        logger.info(
            "StreamingSTTService initialized (min_rms=%.4f, min_confidence=%.2f).",
            min_rms, min_confidence,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inicia o serviço — reseta estado do fluxo parcial."""
        self._active = True
        self._current_text = ""
        self._current_correlation_id = None
        self._current_causation_id = None
        logger.info("StreamingSTTService started.")

    def stop(self) -> None:
        """Para o serviço."""
        self._active = False
        logger.info(
            "StreamingSTTService stopped — windows=%d partials=%d updates=%d",
            self._total_windows,
            self._total_partials_published,
            self._total_updates_published,
        )

    # ------------------------------------------------------------------
    # Callback da SlidingWindow
    # ------------------------------------------------------------------

    def on_window(self, audio: np.ndarray, timestamp: float) -> None:
        """Recebe janela de áudio da SlidingWindow e transcreve.

        Chamado na thread SlidingWindow-Extractor a cada 400ms.
        """
        if not self._active:
            return

        self._total_windows += 1

        # Áudio vazio — não transcrever.
        if audio is None or audio.size == 0:
            return

        # Áudio muito curto (< 1s) — ignorar (ruído / warmup).
        duration_ms = int(audio.size / self._sample_rate * 1000)
        if duration_ms < 1000:
            return

        # Sprint 21.3.2 — filtro de energia (RMS) anti-alucinação.
        # Causa raiz: o StreamingSTT recebe janelas de 6s do RingBuffer
        # que podem ser puro silêncio. O Whisper (especialmente via
        # DirectML/ONNX) alucina frases em silêncio. Calcular RMS do
        # áudio e pular transcrição se for muito baixo (silêncio).
        # Fala humana tem RMS tipicamente > 0.01; silêncio ≈ 0.
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < self._min_rms:
            self._total_skipped_silence += 1
            logger.debug(
                "StreamingSTT: skipping silence (rms=%.6f < %.6f).",
                rms, self._min_rms,
            )
            return

        t0 = time.monotonic()

        try:
            job = self._executor.transcribe_audio(
                audio, sample_rate=self._sample_rate,
            )
        except Exception as e:
            logger.error("StreamingSTT transcription error: %s", e)
            return

        result = job.result
        self._total_transcriptions += 1
        latency_ms = int((time.monotonic() - t0) * 1000)
        self._total_latency_ms += latency_ms

        new_text = (result.text or "").strip()
        self._current_language = result.language or "pt"

        # Texto vazio — não publicar.
        if not new_text:
            self._total_skipped_empty += 1
            return

        # Sprint 21.3.2 — filtro de confiança anti-alucinação.
        # Alucinações do Whisper em silêncio/ruído têm confiança baixa
        # (~0.12-0.20). Transcrições legítimas têm confiança > 0.50.
        # Se a confiança for muito baixa, o texto provavelmente é
        # alucinação e não deve ser publicado.
        if result.confidence < self._min_confidence:
            self._total_skipped_low_confidence += 1
            logger.debug(
                "StreamingSTT: skipping low-confidence text (conf=%.3f < %.3f, text=%r).",
                result.confidence, self._min_confidence, new_text[:60],
            )
            return

        # Primeira transcrição do fluxo — publicar SpeechPartial.
        if self._current_correlation_id is None or not self._current_text:
            self._publish_partial(
                new_text,
                result.confidence,
                latency_ms,
                duration_ms,
                timestamp,
            )
            self._current_text = new_text
            return

        # Transcrição subsequente — comparar com texto anterior.
        appended = self._compute_diff(self._current_text, new_text)

        # Se não há mudança significativa, não publicar.
        if len(appended.strip()) < self._min_text_change:
            self._total_skipped_no_change += 1
            return

        # Publicar SpeechPartialUpdated.
        self._publish_partial_updated(
            full_text=new_text,
            appended_text=appended,
            confidence=result.confidence,
            latency_ms=latency_ms,
            audio_duration_ms=duration_ms,
            timestamp=timestamp,
        )
        self._current_text = new_text

    # ------------------------------------------------------------------
    # Diff por alinhamento de prefixo
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_diff(old: str, new: str) -> str:
        """Computa o trecho novo em ``new`` relativo a ``old``.

        Estratégia: alinhamento por prefixo.
        - Encontra o maior prefixo comum entre old e new.
        - Retorna o sufixo de new após o prefixo comum.

        Se new não começa com o prefixo de old (ex.: Whisper
        reescreveu o início), retorna new inteiro — nesse caso
        não há como alinhar, e o parser deve reprocessar.

        Exemplos:
          old="joão capítulo", new="joão capítulo três"
            → "três"
          old="irmãos vamos", new="irmãos vamos abrir"
            → "abrir"
          old="joão três", new="joão capítulo três"
            → "capítulo três" (prefixo comum = "joão ")
        """
        if not old:
            return new

        # Normalizar para comparação (lowercase, espaços).
        old_words = old.lower().split()
        new_words = new.lower().split()

        # Encontrar quantas palavras do início são iguais.
        # Usar palavras (não caracteres) para robustez.
        common = 0
        for i in range(min(len(old_words), len(new_words))):
            if old_words[i] == new_words[i]:
                common += 1
            else:
                break

        if common == 0:
            # Não há prefixo comum — Whisper reescreveu.
            # Retornar new inteiro.
            return new

        # Retornar sufixo de new após as `common` palavras comuns.
        # Usar o texto original (não lowercase) para preservar casing.
        new_words_orig = new.split()
        appended = " ".join(new_words_orig[common:])
        return appended

    # ------------------------------------------------------------------
    # Publicação de eventos
    # ------------------------------------------------------------------

    def _publish_partial(
        self,
        text: str,
        confidence: float,
        latency_ms: int,
        audio_duration_ms: int,
        timestamp: float,
    ) -> None:
        """Publica SpeechPartial (primeira transcrição do fluxo)."""
        meta = EventMetadata.for_initial(
            session_id=self._session_id,
            origin="StreamingSTTService",
        )
        self._current_correlation_id = meta.correlation_id
        self._current_causation_id = meta.event_id

        event = SpeechPartial(
            meta=meta,
            text=text,
            language=self._current_language,
            confidence=confidence,
            latency_ms=latency_ms,
            audio_duration_ms=audio_duration_ms,
            is_stable=False,
        )
        self._bus.publish(event)
        self._total_partials_published += 1
        logger.info(
            "SpeechPartial: %r (confidence=%.2f, latency=%dms, corr=%s)",
            text[:80], confidence, latency_ms, meta.correlation_id,
        )

    def _publish_partial_updated(
        self,
        full_text: str,
        appended_text: str,
        confidence: float,
        latency_ms: int,
        audio_duration_ms: int,
        timestamp: float,
    ) -> None:
        """Publica SpeechPartialUpdated (evolução da transcrição)."""
        if self._current_correlation_id is None:
            # Não há fluxo ativo — não deveria acontecer, mas defender.
            return

        meta = EventMetadata.for_next(
            previous=EventMetadata(
                event_id=self._current_causation_id,
                correlation_id=self._current_correlation_id,
                causation_id=None,
                session_id=self._session_id,
                timestamp=timestamp,
                origin="StreamingSTTService",
            ),
            origin="StreamingSTTService",
        )
        self._current_causation_id = meta.event_id

        event = SpeechPartialUpdated(
            meta=meta,
            text=full_text,
            appended_text=appended_text,
            language=self._current_language,
            confidence=confidence,
            latency_ms=latency_ms,
            audio_duration_ms=audio_duration_ms,
            is_stable=False,
        )
        self._bus.publish(event)
        self._total_updates_published += 1
        logger.info(
            "SpeechPartialUpdated: appended=%r (full=%r, confidence=%.2f, "
            "latency=%dms, corr=%s)",
            appended_text[:60], full_text[:80], confidence,
            latency_ms, meta.correlation_id,
        )

    # ------------------------------------------------------------------
    # Reset de fluxo (chamado quando VAD fecha segmento)
    # ------------------------------------------------------------------

    def reset_flow(self) -> None:
        """Reseta o fluxo parcial atual.

        Chamado quando o VAD fecha um segmento (SpeechEnded) —
        indica que o fluxo parcial atual terminou e o próximo
        SpeechPartial iniciará um novo correlation_id.
        """
        self._current_text = ""
        self._current_correlation_id = None
        self._current_causation_id = None
        logger.debug("StreamingSTT flow reset.")

    # ------------------------------------------------------------------
    # Propriedades
    # ------------------------------------------------------------------

    @property
    def current_text(self) -> str:
        return self._current_text

    @property
    def total_windows(self) -> int:
        return self._total_windows

    @property
    def total_partials_published(self) -> int:
        return self._total_partials_published

    @property
    def total_updates_published(self) -> int:
        return self._total_updates_published

    @property
    def total_skipped_no_change(self) -> int:
        return self._total_skipped_no_change

    # Sprint 21.3.2 — métricas de anti-alucinação.
    @property
    def total_skipped_silence(self) -> int:
        return self._total_skipped_silence

    @property
    def total_skipped_low_confidence(self) -> int:
        return self._total_skipped_low_confidence

    @property
    def avg_latency_ms(self) -> float:
        if self._total_transcriptions == 0:
            return 0.0
        return self._total_latency_ms / self._total_transcriptions
