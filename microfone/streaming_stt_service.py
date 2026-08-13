"""StreamingSTTService — transcrição parcial contínua (Sprint 19 + Sprint 28).

Responsabilidade:
  - Consumir janelas de áudio da SlidingWindow.
  - Transcrever via STTExecutor (serializa acesso ao Whisper).
  - **Sprint 28 — LocalAgreement-2**: comparar palavras da transcrição
    atual com a anterior; palavras que aparecem em ambas = COMMITTED.
  - Publicar SpeechCommittedWords (palavras confirmed — fluxo primário).
  - Publicar SpeechPartial/Updated (texto completo — fluxo de UI).
  - NUNCA chama parser, NUNCA chama Holyrics, NUNCA publica
    ReferenceDetected.

Sprint 28 — LocalAgreement-2 + Committed Words:
  O algoritmo LocalAgreement-2 (ufal/whisper_streaming, IWSLT 2022)
  resolve o problema de estabilidade sem depender de silêncio:

  1. Transcreve o áudio com word_timestamps=True.
  2. Compara as palavras da transcrição atual com a anterior.
  3. Palavras que aparecem em AMBAS (prefixo comum) = COMMITTED.
  4. Publica SpeechCommittedWords com as palavras newly committed.
  5. Continua publicando SpeechPartial/Updated para UI.

  Exemplo:
    Transcrição T1: "irmãos vamos abrir no evangelho de joão capítulo"
    Transcrição T2: "irmãos vamos abrir no evangelho de joão capítulo três"
    Prefixo comum: 8 palavras → COMMITTED "irmãos vamos abrir no evangelho de joão capítulo"
    "três" é PARTIAL (só em T2, não confirmada ainda)
    → SpeechCommittedWords(committed_text="irmãos vamos abrir no evangelho de joão capítulo")
    → SpeechPartialUpdated(text="irmãos vamos abrir no evangelho de joão capítulo três")

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
from pipeline.events import SpeechCommittedWords, SpeechPartial, SpeechPartialUpdated
from pipeline.metadata import EventMetadata
# Sprint 21.9 — Telemetria de observabilidade (não altera comportamento).
from telemetry import hooks as telemetry_hooks

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
        # Sprint 28 — LocalAgreement-2: proteções de buffer.
        max_context_seconds: float = 12.0,
        trim_margin_seconds: float = 0.2,
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
        # Sprint 28 — proteções de buffer para LocalAgreement-2.
        # max_context_seconds: se o texto committed crescer além deste
        # limite de tempo (em segundos de áudio), algo está errado
        # (ex.: Whisper alucinando, buffer crescer indefinidamente).
        # Nesse caso, logar warning e forçar reset de prev_words.
        self._max_context_seconds = max_context_seconds
        # trim_margin_seconds: margem de áudio mantida antes da última
        # palavra committed ao fazer trim. Reservado para futura
        # implementação de buffer trimming real (buffer acumulado vs
        # janela fixa do SlidingWindow).
        self._trim_margin_seconds = trim_margin_seconds

        # Estado do fluxo parcial atual.
        self._active = False
        self._current_text: str = ""
        self._current_correlation_id: str | None = None
        self._current_causation_id: str | None = None
        self._current_language: str = "pt"

        # Sprint 28 — LocalAgreement-2 state.
        # _prev_words: palavras da transcrição anterior (lowercase, start, end).
        # Usado para comparar com a transcrição atual e commitar palavras
        # que aparecem em ambas (prefixo comum).
        self._prev_words: list[tuple[str, float, float]] = []
        # _committed_text: texto committed acumulado do fluxo atual.
        # Cresce conforme LocalAgreement-2 confirma palavras.
        self._committed_text: str = ""
        # _committed_word_count: número de palavras já committed.
        # Usado para saber quantas palavras do prefixo já foram publicadas.
        self._committed_word_count: int = 0
        # Métricas de LocalAgreement-2.
        self._total_committed_published: int = 0
        self._total_committed_words: int = 0

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
        # Sprint 28 — resetar estado de LocalAgreement-2.
        self._prev_words = []
        self._committed_text = ""
        self._committed_word_count = 0
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
            # Sprint 28 — resetar prev_words em silêncio (buffer trimming implícito).
            self._prev_words = []
            # Sprint 21.9 — telemetria.
            telemetry_hooks.stt_window(
                correlation_id=self._current_correlation_id,
                audio_duration_ms=duration_ms,
                rms=rms,
                skipped_silence=True,
            )
            return

        t0 = time.monotonic()

        try:
            # Sprint 28 — word_timestamps=True para LocalAgreement-2.
            job = self._executor.transcribe_audio(
                audio, sample_rate=self._sample_rate,
                word_timestamps=True,
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
            # Sprint 28 — resetar prev_words em silêncio (buffer trimming implícito).
            self._prev_words = []
            # Sprint 21.9 — telemetria.
            telemetry_hooks.stt_window(
                correlation_id=self._current_correlation_id,
                audio_duration_ms=duration_ms,
                rms=rms,
                skipped_empty=True,
                transcribed=True,
                confidence=result.confidence,
                latency_ms=latency_ms,
                language=self._current_language,
            )
            return

        # Sprint 21.3.2 — filtro de confiança anti-alucinação.
        if result.confidence < self._min_confidence:
            self._total_skipped_low_confidence += 1
            logger.debug(
                "StreamingSTT: skipping low-confidence text (conf=%.3f < %.3f, text=%r).",
                result.confidence, self._min_confidence, new_text[:60],
            )
            # Sprint 28 — resetar prev_words (não confiar em alucinação).
            self._prev_words = []
            # Sprint 21.9 — telemetria.
            telemetry_hooks.stt_window(
                correlation_id=self._current_correlation_id,
                audio_duration_ms=duration_ms,
                rms=rms,
                skipped_low_confidence=True,
                transcribed=True,
                text=new_text,
                confidence=result.confidence,
                latency_ms=latency_ms,
                language=self._current_language,
            )
            return

        # Sprint 28 — extrair palavras com timestamps do resultado.
        current_words = self._extract_words_list(result.words, result.text)

        # Sprint 28 — LocalAgreement-2: commitar palavras que aparecem
        # em ambas as transcrições (atual e anterior).
        new_committed = self._local_agreement(current_words)

        # Publicar SpeechCommittedWords se há novas palavras committed.
        if new_committed:
            self._publish_committed_words(
                new_committed_words=new_committed,
                full_committed_text=self._committed_text,
                confidence=result.confidence,
                latency_ms=latency_ms,
                audio_duration_ms=duration_ms,
                timestamp=timestamp,
            )

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
            # Sprint 28 — guardar palavras para próxima comparação.
            self._prev_words = current_words
            # Sprint 21.9 — telemetria.
            telemetry_hooks.stt_window(
                correlation_id=self._current_correlation_id,
                audio_duration_ms=duration_ms,
                rms=rms,
                transcribed=True,
                text=new_text,
                confidence=result.confidence,
                latency_ms=latency_ms,
                language=self._current_language,
            )
            return

        # Transcrição subsequente — comparar com texto anterior para partial.
        appended = self._compute_diff(self._current_text, new_text)

        # Se não há mudança significativa no partial, não publicar partial.
        if len(appended.strip()) >= self._min_text_change:
            # Publicar SpeechPartialUpdated.
            self._publish_partial_updated(
                full_text=new_text,
                appended_text=appended,
                confidence=result.confidence,
                latency_ms=latency_ms,
                audio_duration_ms=duration_ms,
                timestamp=timestamp,
            )
        else:
            self._total_skipped_no_change += 1

        self._current_text = new_text
        # Sprint 28 — guardar palavras para próxima comparação.
        self._prev_words = current_words

        # Sprint 21.9 — telemetria.
        telemetry_hooks.stt_window(
            correlation_id=self._current_correlation_id,
            audio_duration_ms=duration_ms,
            rms=rms,
            transcribed=True,
            text=new_text,
            confidence=result.confidence,
            latency_ms=latency_ms,
            language=self._current_language,
        )

    # ------------------------------------------------------------------
    # Sprint 28 — LocalAgreement-2
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_words_list(
        words_tuple: tuple[tuple[str, float, float], ...],
        full_text: str,
    ) -> list[tuple[str, float, float]]:
        """Extrai lista de palavras (lowercase, start, end) do STTResult.

        Se word_timestamps retornou palavras, usa elas. Caso contrário
        (ex.: backend não suporta), faz fallback splitting do texto.
        """
        if words_tuple:
            return [(w.lower().strip(), s, e) for w, s, e in words_tuple if w.strip()]
        # Fallback: sem timestamps, usar texto splitado com timestamps 0.
        return [(w.lower().strip(), 0.0, 0.0) for w in full_text.split() if w.strip()]

    def _local_agreement(
        self,
        current_words: list[tuple[str, float, float]],
    ) -> list[tuple[str, float, float]]:
        """LocalAgreement-2: commita palavras que aparecem em 2 transcrições consecutivas.

        Compara ``current_words`` com ``self._prev_words`` (transcrição
        anterior). Palavras que formam um prefixo comum entre ambas são
        "committed" — consideradas estáveis.

        Retorna apenas as palavras **novamente** committed (as que não
        estavam committed antes). Atualiza ``self._committed_text`` e
        ``self._committed_word_count``.
        """
        if not self._prev_words or not current_words:
            return []

        # Sprint 28 — proteção max_context_seconds: se a última palavra
        # committed tem timestamp > max_context_seconds, o buffer cresceu
        # demais. Resetar prev_words para forçar re-alinhamento.
        if self._committed_word_count > 0:
            last_committed_end = 0.0
            if self._prev_words and len(self._prev_words) >= self._committed_word_count:
                last_committed_end = self._prev_words[self._committed_word_count - 1][2]
            if last_committed_end > self._max_context_seconds:
                logger.warning(
                    "StreamingSTT: committed buffer exceeded max_context_seconds "
                    "(%.1fs > %.1fs) — resetting prev_words for re-alignment.",
                    last_committed_end, self._max_context_seconds,
                )
                self._prev_words = []
                return []

        # Contar prefixo comum entre prev e current.
        common_count = 0
        for i in range(min(len(self._prev_words), len(current_words))):
            if self._prev_words[i][0] == current_words[i][0]:
                common_count += 1
            else:
                break

        # Se o prefixo comum cresceu além do já committed, há novas palavras.
        if common_count <= self._committed_word_count:
            return []

        # Extrair novas palavras committed.
        new_committed = current_words[self._committed_word_count:common_count]

        # Atualizar estado committed.
        new_committed_text = " ".join(w[0] for w in new_committed)
        if self._committed_text:
            self._committed_text = self._committed_text + " " + new_committed_text
        else:
            self._committed_text = new_committed_text
        self._committed_word_count = common_count

        return new_committed

    def _publish_committed_words(
        self,
        new_committed_words: list[tuple[str, float, float]],
        full_committed_text: str,
        confidence: float,
        latency_ms: int,
        audio_duration_ms: int,
        timestamp: float,
    ) -> None:
        """Publica SpeechCommittedWords (palavras confirmed por LocalAgreement-2)."""
        if self._current_correlation_id is None:
            return

        # Se é o primeiro evento do fluxo, criar correlation_id.
        if self._current_causation_id is None:
            meta = EventMetadata.for_initial(
                session_id=self._session_id,
                origin="StreamingSTTService",
            )
            self._current_correlation_id = meta.correlation_id
            self._current_causation_id = meta.event_id
        else:
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

        committed_text = " ".join(w[0] for w in new_committed_words)
        words_tuple = tuple(new_committed_words)

        event = SpeechCommittedWords(
            meta=meta,
            committed_text=committed_text,
            full_committed_text=full_committed_text,
            words=words_tuple,
            language=self._current_language,
            confidence=confidence,
            latency_ms=latency_ms,
            audio_duration_ms=audio_duration_ms,
        )
        self._bus.publish(event)
        self._total_committed_published += 1
        self._total_committed_words += len(new_committed_words)
        logger.info(
            "SpeechCommittedWords: %r (total_committed=%d words, corr=%s)",
            committed_text[:80], self._committed_word_count, meta.correlation_id,
        )

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
        # Sprint 21.9 — telemetria.
        telemetry_hooks.stt_partial_published(
            correlation_id=meta.correlation_id,
            text=text,
            confidence=confidence,
            latency_ms=latency_ms,
            audio_duration_ms=audio_duration_ms,
            language=self._current_language,
            is_update=False,
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
        # Sprint 21.9 — telemetria.
        telemetry_hooks.stt_partial_published(
            correlation_id=meta.correlation_id,
            text=full_text,
            confidence=confidence,
            latency_ms=latency_ms,
            audio_duration_ms=audio_duration_ms,
            language=self._current_language,
            is_update=True,
            appended_text=appended_text,
            full_text=full_text,
            growth_chars=len(appended_text),
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
        # Sprint 28 — resetar estado de LocalAgreement-2.
        self._prev_words = []
        self._committed_text = ""
        self._committed_word_count = 0
        logger.debug("StreamingSTT flow reset.")

    # ------------------------------------------------------------------
    # Propriedades
    # ------------------------------------------------------------------

    @property
    def current_text(self) -> str:
        return self._current_text

    # Sprint 28 (Fase 10) — expor correlation_id ativo para propagação.
    @property
    def current_correlation_id(self) -> str | None:
        """Correlation_id do fluxo streaming ativo, ou None se inativo."""
        return self._current_correlation_id

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

    # Sprint 28 — métricas de LocalAgreement-2.
    @property
    def total_committed_published(self) -> int:
        return self._total_committed_published

    @property
    def total_committed_words(self) -> int:
        return self._total_committed_words

    @property
    def committed_text(self) -> str:
        return self._committed_text

    @property
    def avg_latency_ms(self) -> float:
        if self._total_transcriptions == 0:
            return 0.0
        return self._total_latency_ms / self._total_transcriptions
