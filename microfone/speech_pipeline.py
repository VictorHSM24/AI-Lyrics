"""SpeechPipelineService — pipeline de VAD em thread dedicada (Sprint 16).

Responsabilidades:
  - Receber chunks de áudio do AudioCaptureService (thread PortAudio).
  - Converter float32 → int16 PCM.
  - Alimentar o VadSegmenter (thread própria).
  - Publicar eventos: SpeechStarted, SpeechEnded, SpeechSegmentCreated.
  - Enfileirar SpeechSegments na SpeechQueue para o SpeechWorker.

Thread Safety:
  - AudioChunkQueue: fila entre PortAudio thread e VAD thread.
  - VadSegmenter: acessado apenas pela VAD thread.
  - EventBus.publish: thread-safe (Lock interno).
  - SpeechQueue: thread-safe (queue.Queue).

Fluxo:
  AudioCaptureService (PortAudio thread)
    → on_audio_data(float32, timestamp)
    → AudioChunkQueue.put(chunk)

  VAD Thread (este serviço)
    → AudioChunkQueue.get() → float32→int16 → VadSegmenter.process_chunk()
    → SpeechStarted quando VAD detecta início
    → SpeechEnded quando VAD detecta fim
    → SpeechSegmentCreated quando segmento é criado
    → SpeechQueue.put(segment)
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable

import numpy as np

from config.models import AudioConfig
from microfone.capture import SpeechSegment, VadSegmenter
from microfone.speech_queue import SpeechQueue
from pipeline.bus import PipelineEventBus
from pipeline.events import SpeechEnded, SpeechSegmentCreated, SpeechStarted
from pipeline.metadata import EventMetadata

logger = logging.getLogger(__name__)


class SpeechPipelineService:
    """Pipeline de VAD que transforma áudio contínuo em SpeechSegments.

    Roda uma thread dedicada que consome chunks de áudio, processa VAD,
    e enfileira segmentos completos para transcrição.

    Args:
        capture_service: AudioCaptureService (já configurado).
        audio_config: AudioConfig com parâmetros de VAD.
        bus: PipelineEventBus para publicar eventos.
        speech_queue: SpeechQueue para enfileirar segmentos.
        session_id: ID da sessão atual (para EventMetadata).
        segmenter: VadSegmenter (criado internamente se omitido).
    """

    def __init__(
        self,
        capture_service: Any,
        audio_config: AudioConfig,
        bus: PipelineEventBus,
        speech_queue: SpeechQueue,
        session_id: str,
        segmenter: VadSegmenter | None = None,
    ) -> None:
        self._capture = capture_service
        self._config = audio_config
        self._bus = bus
        self._queue = speech_queue
        self._session_id = session_id

        # VadSegmenter — criado a partir da config se não fornecido.
        self._segmenter = segmenter or VadSegmenter(
            sample_rate=audio_config.sample_rate,
            chunk_ms=audio_config.chunk_ms,
            min_speech_ms=audio_config.min_speech_ms,
            max_silence_ms=audio_config.max_silence_ms,
            vad_mode=audio_config.vad_mode,
            max_segment_ms=audio_config.max_segment_ms,
        )

        # Fila entre PortAudio thread e VAD thread.
        self._chunk_queue: queue.Queue[tuple[np.ndarray, float]] = queue.Queue(maxsize=200)
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Rastreabilidade: correlation_id do segmento atual.
        self._current_correlation_id: str | None = None
        self._current_causation_id: str | None = None

        logger.info(
            "SpeechPipelineService initialized: sr=%d chunk_ms=%d min_speech=%d max_silence=%d",
            audio_config.sample_rate,
            audio_config.chunk_ms,
            audio_config.min_speech_ms,
            audio_config.max_silence_ms,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inicia a thread de VAD e conecta ao AudioCaptureService."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()

        # Conectar callback do AudioCaptureService.
        self._capture.set_on_audio_data(self._on_audio_data)

        # Iniciar thread de VAD.
        self._thread = threading.Thread(
            target=self._vad_loop,
            name="SpeechPipeline-VAD",
            daemon=True,
        )
        self._thread.start()
        logger.info("SpeechPipelineService started — VAD thread running.")

    def stop(self) -> None:
        """Para a thread de VAD e desconecta do AudioCaptureService."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()

        # Desconectar callback.
        self._capture.set_on_audio_data(None)

        # Flush final (forçar segmentação do que estiver no buffer).
        final_segment = self._segmenter.force_flush(time.time())
        if final_segment is not None:
            self._emit_segment(final_segment)

        # Aguardar thread terminar.
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

        logger.info("SpeechPipelineService stopped.")

    # ------------------------------------------------------------------
    # Callback do AudioCaptureService (thread PortAudio)
    # ------------------------------------------------------------------

    def _on_audio_data(self, audio_data: np.ndarray, timestamp: float) -> None:
        """Recebe chunk de áudio do PortAudio e coloca na fila.

        Chamado na thread do PortAudio — deve ser rápido.
        Apenas coloca na fila, sem processamento.
        """
        try:
            self._chunk_queue.put_nowait((audio_data, timestamp))
        except queue.Full:
            # Fila cheia — descartar chunk antigo para não bloquear PortAudio.
            try:
                self._chunk_queue.get_nowait()
                self._chunk_queue.put_nowait((audio_data, timestamp))
            except queue.Empty:
                pass

    # ------------------------------------------------------------------
    # VAD Thread — consome chunks e produz SpeechSegments
    # ------------------------------------------------------------------

    def _vad_loop(self) -> None:
        """Loop principal da thread de VAD."""
        logger.info("VAD thread started.")
        while not self._stop_event.is_set():
            try:
                item = self._chunk_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                continue
            audio_data, timestamp = item
            self._process_chunk(audio_data, timestamp)

        logger.info("VAD thread exiting.")

    def _process_chunk(self, audio_data: np.ndarray, timestamp: float) -> None:
        """Processa um chunk de áudio: float32 → int16 → VAD."""
        # Converter float32 [-1.0, 1.0] → int16 [-32768, 32767]
        pcm_int16 = (audio_data * 32767.0).astype(np.int16)
        pcm_bytes = pcm_int16.tobytes()

        # Detectar transição de estado antes de processar.
        was_in_speech = self._segmenter.in_speech

        # Processar chunk no VAD.
        segment = self._segmenter.process_chunk(pcm_bytes, timestamp)

        # Detectar início de fala (transição False → True).
        if not was_in_speech and self._segmenter.in_speech:
            self._emit_speech_started(timestamp)

        # Se VAD produziu um segmento, emitir eventos.
        if segment is not None:
            self._emit_speech_ended(segment)
            self._emit_segment(segment)

    # ------------------------------------------------------------------
    # Emissão de eventos
    # ------------------------------------------------------------------

    def _emit_speech_started(self, timestamp: float) -> None:
        """Publica evento SpeechStarted."""
        meta = EventMetadata.for_initial(
            session_id=self._session_id,
            origin="SpeechPipelineService",
        )
        self._current_correlation_id = meta.correlation_id
        self._current_causation_id = meta.event_id

        event = SpeechStarted(meta=meta, timestamp_start=timestamp)
        self._bus.publish(event)
        logger.info("Speech started at %.3f", timestamp)

    def _emit_speech_ended(self, segment: SpeechSegment) -> None:
        """Publica evento SpeechEnded."""
        if self._current_correlation_id is None or self._current_causation_id is None:
            return

        meta = EventMetadata.for_next(
            previous=EventMetadata(
                event_id=self._current_causation_id,
                correlation_id=self._current_correlation_id,
                causation_id=None,
                session_id=self._session_id,
                timestamp=segment.start_time,
                origin="SpeechPipelineService",
            ),
            origin="SpeechPipelineService",
        )

        event = SpeechEnded(
            meta=meta,
            timestamp_end=segment.end_time,
            duration_ms=segment.duration_ms,
        )
        self._bus.publish(event)
        self._current_causation_id = meta.event_id
        logger.info("Speech ended (duration=%d ms)", segment.duration_ms)

    def _emit_segment(self, segment: SpeechSegment) -> None:
        """Publica evento SpeechSegmentCreated e enfileira na SpeechQueue."""
        if self._current_correlation_id is None or self._current_causation_id is None:
            return

        meta = EventMetadata.for_next(
            previous=EventMetadata(
                event_id=self._current_causation_id,
                correlation_id=self._current_correlation_id,
                causation_id=None,
                session_id=self._session_id,
                timestamp=segment.end_time,
                origin="SpeechPipelineService",
            ),
            origin="SpeechPipelineService",
        )

        event = SpeechSegmentCreated(
            meta=meta,
            duration_ms=segment.duration_ms,
            chunk_count=segment.chunk_count,
            sample_rate=self._config.sample_rate,
            channels=self._config.channels if hasattr(self._config, 'channels') else 1,
        )
        self._bus.publish(event)
        self._current_causation_id = meta.event_id

        # Enfileirar segmento para o SpeechWorker.
        self._queue.put(segment)
        logger.info(
            "Segment created (duration=%d ms, chunks=%d) — queued",
            segment.duration_ms,
            segment.chunk_count,
        )

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """True se o pipeline está ativo."""
        return self._running

    @property
    def in_speech(self) -> bool:
        """True se o VAD está atualmente detectando fala."""
        return self._segmenter.in_speech
