"""SpeechWorker — thread dedicada para transcrição com Whisper (Sprint 16).

Responsabilidades:
  - Consumir SpeechSegments da SpeechQueue.
  - Chamar STT.transcribe(segment) → STTResult.
  - Publicar eventos: SpeechTranscribing, SpeechTranscribed.
  - Nunca bloquear a thread do PortAudio ou do VAD.

Thread Safety:
  - SpeechQueue: thread-safe (queue.Queue).
  - STT.transcribe: chamado apenas por esta thread (sequencial).
  - EventBus.publish: thread-safe (Lock interno).

Performance:
  - Latência fim da fala → texto: objetivo < 1500 ms.
  - Whisper roda em thread própria — não bloqueia captura nem VAD.
  - Se a fila encher, segmentos antigos são descartados (SpeechQueue bounded).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from microfone.capture import SpeechSegment
from microfone.speech_queue import SpeechQueue
from pipeline.bus import PipelineEventBus
from pipeline.events import SpeechTranscribed, SpeechTranscribing
from pipeline.metadata import EventMetadata

logger = logging.getLogger(__name__)


class SpeechWorker:
    """Worker dedicado que transcreve SpeechSegments com Whisper.

    Consome segmentos da SpeechQueue em uma thread própria e publica
    eventos de transcrição no EventBus.

    Args:
        stt: instância de STT (faster-whisper) já inicializada.
        bus: PipelineEventBus para publicar eventos.
        speech_queue: SpeechQueue de onde consumir segmentos.
        session_id: ID da sessão atual (para EventMetadata).
    """

    def __init__(
        self,
        stt: Any,
        bus: PipelineEventBus,
        speech_queue: SpeechQueue,
        session_id: str,
    ) -> None:
        self._stt = stt
        self._bus = bus
        self._queue = speech_queue
        self._session_id = session_id

        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Métricas.
        self._total_transcribed = 0
        self._total_errors = 0
        self._total_latency_ms = 0

        logger.info("SpeechWorker initialized.")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inicia a thread do worker."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._worker_loop,
            name="SpeechWorker-Whisper",
            daemon=True,
        )
        self._thread.start()
        logger.info("SpeechWorker started — Whisper thread running.")

    def stop(self) -> None:
        """Para a thread do worker."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._thread = None
        logger.info("SpeechWorker stopped.")

    # ------------------------------------------------------------------
    # Worker Thread — consome segmentos e transcreve
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """Loop principal da thread do worker."""
        logger.info("SpeechWorker thread started.")
        while not self._stop_event.is_set():
            segment = self._queue.get(timeout=0.2)
            if segment is None:
                continue
            self._transcribe_segment(segment)

        logger.info("SpeechWorker thread exiting.")

    def _transcribe_segment(self, segment: SpeechSegment) -> None:
        """Transcreve um segmento e publica eventos."""
        t0 = time.monotonic()

        # Sprint 17.3 — Tempo de espera na fila (segment.end_time → agora).
        queue_wait_ms = 0
        try:
            queue_wait_ms = int((t0 - segment.end_time) * 1000)
            if queue_wait_ms < 0:
                queue_wait_ms = 0
        except Exception:
            pass

        # Publicar evento SpeechTranscribing.
        meta_transcribing = EventMetadata.for_initial(
            session_id=self._session_id,
            origin="SpeechWorker",
        )
        transcribing_event = SpeechTranscribing(
            meta=meta_transcribing,
            duration_ms=segment.duration_ms,
        )
        self._bus.publish(transcribing_event)
        logger.info(
            "Transcribing segment (duration=%d ms, queue_wait=%d ms)...",
            segment.duration_ms, queue_wait_ms,
        )

        # Transcrever com Whisper.
        try:
            result = self._stt.transcribe(segment)
        except Exception as e:
            self._total_errors += 1
            logger.error("Whisper transcription failed: %s", e)
            # Publicar evento com erro.
            meta_done = EventMetadata.for_next(
                previous=meta_transcribing,
                origin="SpeechWorker",
            )
            event = SpeechTranscribed(
                meta=meta_done,
                text="",
                language="",
                confidence=0.0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                duration_ms=segment.duration_ms,
            )
            self._bus.publish(event)
            return

        latency_ms = int((time.monotonic() - t0) * 1000)
        self._total_transcribed += 1
        self._total_latency_ms += latency_ms

        # Publicar evento SpeechTranscribed.
        meta_done = EventMetadata.for_next(
            previous=meta_transcribing,
            origin="SpeechWorker",
        )
        event = SpeechTranscribed(
            meta=meta_done,
            text=result.text,
            language=result.language,
            confidence=result.confidence,
            latency_ms=latency_ms,
            duration_ms=segment.duration_ms,
        )
        self._bus.publish(event)

        # Sprint 17.3 — Log detalhado com métricas de pipeline.
        stt_ms = getattr(result, "processing_ms", 0)
        audio_ms = getattr(result, "duration_ms", segment.duration_ms)
        rtf = stt_ms / audio_ms if audio_ms > 0 else 0.0
        logger.info(
            "Transcribed: total=%d ms, stt=%d ms, queue_wait=%d ms, "
            "audio=%d ms, rtf=%.2f, confidence=%.2f, text=%r",
            latency_ms,
            stt_ms,
            queue_wait_ms,
            audio_ms,
            rtf,
            result.confidence,
            result.text[:80] if result.text else "",
        )

    # ------------------------------------------------------------------
    # Estado e métricas
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def total_transcribed(self) -> int:
        return self._total_transcribed

    @property
    def total_errors(self) -> int:
        return self._total_errors

    @property
    def avg_latency_ms(self) -> float:
        if self._total_transcribed == 0:
            return 0.0
        return self._total_latency_ms / self._total_transcribed
