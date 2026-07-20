"""AudioEventPublisher — transmite frames de áudio via WebSocket (Sprint 15.1).

Bridge entre AudioCaptureService (callback síncrono na thread do
PortAudio) e ConnectionManager (assíncrono, WebSocket).

Fluxo:
  AudioCaptureService callback (thread PortAudio)
      ↓ AudioFrame
  AudioEventPublisher._on_frame (thread PortAudio)
      ↓ enfileira AudioEventDTO
  AudioEventPublisher._drain_loop (asyncio)
      ↓ broadcast_event
  ConnectionManager
      ↓ WebSocket
  Frontend

Eventos emitidos:
  - audio.started    — quando a captura inicia
  - audio.stopped    — quando a captura para
  - audio.device.changed — quando o dispositivo é trocado
  - audio.level      — enviado continuamente com RMS/Peak

Throttling:
  - audio.level é limitado a ~25 FPS (40ms entre eventos) para
    evitar sobrecarregar o WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from presentation.dtos import EventDTO, EventMetadataDTO

logger = logging.getLogger("api.audio_events")


# ---------------------------------------------------------------------------
# Helpers — construir EventDTO para eventos de áudio.
# ---------------------------------------------------------------------------


def _make_audio_event(
    event_type: str,
    payload: dict,
    session_id: str = "audio",
    correlation_id: str | None = None,
    category: str = "operational",
) -> EventDTO:
    """Constrói um EventDTO para um evento de áudio.

    Sprint 17.2 — category distingue operational de telemetry:
      - audio.started, audio.stopped, audio.device.changed → "operational"
      - audio.level → "telemetry"
    """
    now = time.time()
    return EventDTO(
        event_type=event_type,
        meta=EventMetadataDTO(
            event_id=str(uuid.uuid4()),
            correlation_id=correlation_id or str(uuid.uuid4()),
            causation_id=None,
            session_id=session_id,
            timestamp=now,
            origin="audio",
            metadata=(),
        ),
        payload=payload,
        category=category,
    )


# ---------------------------------------------------------------------------
# AudioEventPublisher
# ---------------------------------------------------------------------------


class AudioEventPublisher:
    """Publica eventos de áudio via WebSocket.

    Recebe frames do AudioCaptureService (thread PortAudio) e os
    enfileira para drenagem assíncrona via ConnectionManager.

    Throttling: audio.level é limitado a max_fps eventos por segundo.
    """

    def __init__(self, manager: Any, max_fps: float = 25.0) -> None:
        self._manager = manager
        self._max_fps = max_fps
        self._min_interval = 1.0 / max_fps if max_fps > 0 else 0.0
        self._pending: list[EventDTO] = []
        self._drain_task: asyncio.Task | None = None
        self._last_level_time: float = 0.0
        self._started = False

    def start(self) -> None:
        """Inicia o publisher — começa a drenar eventos."""
        if self._started:
            return
        self._started = True
        try:
            loop = asyncio.get_event_loop()
            self._drain_task = loop.create_task(self._drain_loop())
        except RuntimeError:
            # Sem loop rodando (testes síncronos) — drenagem manual.
            pass
        logger.info("AudioEventPublisher started (max_fps=%.1f)", self._max_fps)

    def stop(self) -> None:
        """Para o publisher."""
        if self._drain_task is not None:
            self._drain_task.cancel()
            self._drain_task = None
        self._started = False
        logger.info("AudioEventPublisher stopped.")

    # ------------------------------------------------------------------
    # Callbacks — chamados pelo AudioCaptureService.
    # ------------------------------------------------------------------

    def on_frame(self, frame: Any) -> None:
        """Callback chamado a cada frame capturado.

        Aplica throttling para limitar a taxa de eventos audio.level.
        Executado na thread do PortAudio — deve ser rápido.
        """
        now = frame.timestamp
        if (now - self._last_level_time) < self._min_interval:
            return
        self._last_level_time = now

        event = _make_audio_event(
            "audio.level",
            {
                "rms": frame.rms,
                "peak": frame.peak,
                "timestamp": frame.timestamp,
                "sample_rate": frame.sample_rate,
                "channels": frame.channels,
                "frame_count": frame.frame_count,
            },
            category="telemetry",
        )
        self._pending.append(event)

    def emit_started(self, device_index: int | None, sample_rate: int, channels: int) -> None:
        """Emite evento audio.started."""
        event = _make_audio_event(
            "audio.started",
            {
                "device_index": device_index,
                "sample_rate": sample_rate,
                "channels": channels,
            },
        )
        self._pending.append(event)
        logger.info("audio.started emitted: device=%s", device_index)

    def emit_stopped(self) -> None:
        """Emite evento audio.stopped."""
        event = _make_audio_event("audio.stopped", {})
        self._pending.append(event)
        logger.info("audio.stopped emitted.")

    def emit_device_changed(self, device_index: int, restarted: bool) -> None:
        """Emite evento audio.device.changed."""
        event = _make_audio_event(
            "audio.device.changed",
            {
                "device_index": device_index,
                "restarted": restarted,
            },
        )
        self._pending.append(event)
        logger.info("audio.device.changed emitted: device=%d restarted=%s", device_index, restarted)

    # ------------------------------------------------------------------
    # Drenagem — envia eventos pendentes via WebSocket.
    # ------------------------------------------------------------------

    async def _drain_loop(self) -> None:
        """Drena eventos pendentes e broadcasta via WebSocket."""
        while True:
            try:
                await asyncio.sleep(0.02)  # 20ms
                if not self._pending:
                    continue
                pending = self._pending[:]
                self._pending.clear()
                for event in pending:
                    await self._manager.broadcast_event(event)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("AudioEventPublisher drain error: %s", exc)

    def drain_now(self) -> None:
        """Drenagem síncrona — útil para testes sem event loop."""
        if not self._pending:
            return
        pending = self._pending[:]
        self._pending.clear()
        for q in list(self._manager._queues.values()):
            for event in pending:
                try:
                    if q.full():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass


# ---------------------------------------------------------------------------
# Singleton — uma instância por processo.
# ---------------------------------------------------------------------------


_audio_publisher: AudioEventPublisher | None = None


def get_audio_event_publisher() -> AudioEventPublisher:
    """Retorna o singleton AudioEventPublisher."""
    global _audio_publisher
    if _audio_publisher is None:
        from api.websocket.events import get_ws_manager
        _audio_publisher = AudioEventPublisher(get_ws_manager())
    return _audio_publisher


def reset_audio_event_publisher() -> None:
    """Reseta o singleton (útil para testes)."""
    global _audio_publisher
    if _audio_publisher is not None:
        _audio_publisher.stop()
    _audio_publisher = None


def connect_audio_capture_to_publisher(capture_service: Any) -> None:
    """Conecta AudioCaptureService ao AudioEventPublisher.

    Faz o publisher receber frames do callback do capture service.
    Deve ser chamado após ambos estarem inicializados.
    """
    publisher = get_audio_event_publisher()
    capture_service.set_on_frame(publisher.on_frame)
    publisher.start()
    logger.info("AudioCaptureService connected to AudioEventPublisher.")
