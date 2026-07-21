"""STTExecutor — serializa acesso ao Whisper (Sprint 19).

Responsabilidade:
  - Único ponto de acesso ao STT (Whisper).
  - Serializa chamadas de múltiplas threads (SpeechWorker +
    StreamingSTTService) em uma fila interna.
  - Mantém uma única instância do modelo em RAM (~2GB).
  - Futuramente: prioridade (parciais > finais).

Sprint 19 — Streaming Speech Pipeline:
  O SpeechWorker e o StreamingSTTService precisam ambos chamar o
  Whisper. Sem o STTExecutor, ambos acessariam self._model.transcribe()
  concorrentemente, o que pode causar:
    - Contenção de GPU/CPU.
    - Resultados inconsistentes (faster-whisper não é totalmente
      thread-safe em todas as configurações).
    - OOM se duas transcrições rodarem em paralelo.

  O STTExecutor resolve isso com um Lock interno: apenas uma
  transcrição roda por vez. As outras esperam na fila.

  Trade-off: transcrições parciais podem esperar as finais terminar.
  Em hardware típico (CPU), uma transcrição de 6s leva ~3s, então
  o pior caso de espera é ~3s — aceitável para parciais.
  Em GPU, uma transcrição de 6s leva ~0.5s, então a espera é
  desprezível.

  Futuro: adicionar PriorityQueue para dar prioridade às parciais.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import numpy as np

from transcricao.stt import STT, STTResult

logger = logging.getLogger(__name__)

__all__ = ["STTExecutor", "STTJobResult"]


@dataclass
class STTJobResult:
    """Resultado de um job de transcrição do STTExecutor.

    Attributes:
        result: STTResult com texto, language, confidence, timing.
        queue_wait_ms: tempo esperando na fila antes de executar.
        total_ms: tempo total (queue + execução).
    """
    result: STTResult
    queue_wait_ms: int
    total_ms: int


class STTExecutor:
    """Serializa acesso ao STT (Whisper) entre múltiplas threads.

    Args:
        stt: instância de STT (faster-whisper) já inicializada.

    Uso:
        executor = STTExecutor(stt=stt_instance)

        # Thread 1 (SpeechWorker) — transcrição final de segmento.
        result = executor.transcribe_segment(segment)

        # Thread 2 (StreamingSTT) — transcrição parcial de janela.
        result = executor.transcribe_audio(audio_float32, duration_ms=6000)
    """

    def __init__(self, stt: STT) -> None:
        self._stt = stt
        self._lock = threading.Lock()

        # Métricas.
        self._total_jobs = 0
        self._total_segment_jobs = 0
        self._total_audio_jobs = 0
        self._total_wait_ms = 0
        self._total_exec_ms = 0

        logger.info("STTExecutor initialized — single STT instance shared.")

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def transcribe_segment(self, segment) -> STTJobResult:
        """Transcreve um SpeechSegment (fluxo existente do SpeechWorker).

        Args:
            segment: SpeechSegment com PCM bytes.

        Returns:
            STTJobResult com resultado + métricas de espera.
        """
        t_enqueue = time.monotonic()
        with self._lock:
            t_start = time.monotonic()
            queue_wait_ms = int((t_start - t_enqueue) * 1000)
            result = self._stt.transcribe(segment)
            t_end = time.monotonic()

        exec_ms = int((t_end - t_start) * 1000)
        total_ms = int((t_end - t_enqueue) * 1000)

        with self._lock_metrics():
            self._total_jobs += 1
            self._total_segment_jobs += 1
            self._total_wait_ms += queue_wait_ms
            self._total_exec_ms += exec_ms

        logger.debug(
            "STTExecutor segment job: wait=%dms exec=%dms total=%dms",
            queue_wait_ms, exec_ms, total_ms,
        )
        return STTJobResult(
            result=result,
            queue_wait_ms=queue_wait_ms,
            total_ms=total_ms,
        )

    def transcribe_audio(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> STTJobResult:
        """Transcreve áudio float32 diretamente (fluxo StreamingSTT).

        Diferente de transcribe_segment, este método recebe um
        ndarray float32 [-1.0, 1.0] (formato do RingBuffer/SlidingWindow)
        e converte para PCM bytes internamente antes de chamar o STT.

        Args:
            audio: ndarray float32 [-1.0, 1.0]. Shape (N,) para mono.
            sample_rate: taxa de amostragem (default 16000).

        Returns:
            STTJobResult com resultado + métricas de espera.
        """
        if audio is None or audio.size == 0:
            return STTJobResult(
                result=STTResult(
                    text="",
                    language="pt",
                    confidence=0.0,
                    processing_ms=0,
                    audio_duration_ms=0,
                ),
                queue_wait_ms=0,
                total_ms=0,
            )

        # Converter float32 → PCM int16 bytes (formato esperado pelo STT).
        pcm_int16 = (audio * 32767.0).astype(np.int16)
        pcm_bytes = pcm_int16.tobytes()
        duration_ms = int(len(pcm_bytes) / (2 * sample_rate) * 1000)

        # Criar SpeechSegment mínimo para reusar self._stt.transcribe().
        from microfone.capture import SpeechSegment
        now = time.time()
        segment = SpeechSegment(
            audio=pcm_bytes,
            start_time=now - duration_ms / 1000.0,
            end_time=now,
            duration_ms=duration_ms,
            chunk_count=0,
        )

        t_enqueue = time.monotonic()
        with self._lock:
            t_start = time.monotonic()
            result = self._stt.transcribe(segment)
            t_end = time.monotonic()

        queue_wait_ms = int((t_start - t_enqueue) * 1000)
        exec_ms = int((t_end - t_start) * 1000)
        total_ms = int((t_end - t_enqueue) * 1000)

        with self._lock_metrics():
            self._total_jobs += 1
            self._total_audio_jobs += 1
            self._total_wait_ms += queue_wait_ms
            self._total_exec_ms += exec_ms

        logger.debug(
            "STTExecutor audio job: wait=%dms exec=%dms total=%dms "
            "audio=%dms text=%r",
            queue_wait_ms, exec_ms, total_ms, duration_ms,
            result.text[:60],
        )
        return STTJobResult(
            result=result,
            queue_wait_ms=queue_wait_ms,
            total_ms=total_ms,
        )

    # ------------------------------------------------------------------
    # Métricas
    # ------------------------------------------------------------------

    def _lock_metrics(self) -> threading.Lock:
        """Lock separado para métricas (não bloqueia transcrições)."""
        if not hasattr(self, "_metrics_lock"):
            self._metrics_lock = threading.Lock()
        return self._metrics_lock

    @property
    def total_jobs(self) -> int:
        return self._total_jobs

    @property
    def total_segment_jobs(self) -> int:
        return self._total_segment_jobs

    @property
    def total_audio_jobs(self) -> int:
        return self._total_audio_jobs

    @property
    def avg_wait_ms(self) -> float:
        if self._total_jobs == 0:
            return 0.0
        return self._total_wait_ms / self._total_jobs

    @property
    def avg_exec_ms(self) -> float:
        if self._total_jobs == 0:
            return 0.0
        return self._total_exec_ms / self._total_jobs
