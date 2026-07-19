"""Testes do AudioEventPublisher — Sprint 15.1.

Cobertura:
  - Construção de EventDTO para eventos de áudio
  - Throttling de audio.level
  - emit_started / emit_stopped / emit_device_changed
  - drain_now (drenagem síncrona)
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock

from api.websocket.audio_events import (
    AudioEventPublisher,
    _make_audio_event,
)
from microfone.audio_capture_service import AudioFrame


class TestMakeAudioEvent(unittest.TestCase):
    """Testes do helper _make_audio_event."""

    def test_create_event(self):
        event = _make_audio_event(
            "audio.level",
            {"rms": 0.5, "peak": 0.8, "timestamp": 1.0},
        )
        self.assertEqual(event.event_type, "audio.level")
        self.assertEqual(event.payload["rms"], 0.5)
        self.assertEqual(event.payload["peak"], 0.8)
        self.assertEqual(event.meta.origin, "audio")
        self.assertEqual(event.meta.session_id, "audio")
        self.assertGreater(event.meta.timestamp, 0)
        self.assertTrue(event.meta.event_id)

    def test_create_event_with_correlation_id(self):
        event = _make_audio_event(
            "audio.started",
            {"device_index": 0},
            correlation_id="corr-123",
        )
        self.assertEqual(event.meta.correlation_id, "corr-123")


class TestAudioEventPublisher(unittest.TestCase):
    """Testes do AudioEventPublisher."""

    def setUp(self):
        # Mock do ConnectionManager.
        self.manager = MagicMock()
        self.manager._queues = {}
        self.publisher = AudioEventPublisher(self.manager, max_fps=25.0)

    def tearDown(self):
        self.publisher.stop()

    def test_on_frame_throttling(self):
        """Frames muito próximos devem ser throttled."""
        frame1 = AudioFrame(
            timestamp=100.0, sample_rate=16000, channels=1,
            frame_count=480, rms=0.5, peak=0.8,
        )
        frame2 = AudioFrame(
            timestamp=100.01, sample_rate=16000, channels=1,
            frame_count=480, rms=0.6, peak=0.9,
        )
        # Intervalo mínimo = 1/25 = 0.04s. frame2 está a 0.01s — throttled.
        self.publisher.on_frame(frame1)
        self.publisher.on_frame(frame2)
        # Apenas 1 evento enfileirado.
        self.assertEqual(len(self.publisher._pending), 1)

    def test_on_frame_passes_after_interval(self):
        """Frame após intervalo mínimo deve passar."""
        frame1 = AudioFrame(
            timestamp=100.0, sample_rate=16000, channels=1,
            frame_count=480, rms=0.5, peak=0.8,
        )
        frame2 = AudioFrame(
            timestamp=100.05, sample_rate=16000, channels=1,
            frame_count=480, rms=0.6, peak=0.9,
        )
        # Intervalo mínimo = 0.04s. frame2 está a 0.05s — passa.
        self.publisher.on_frame(frame1)
        self.publisher.on_frame(frame2)
        self.assertEqual(len(self.publisher._pending), 2)

    def test_emit_started(self):
        self.publisher.emit_started(device_index=0, sample_rate=16000, channels=1)
        self.assertEqual(len(self.publisher._pending), 1)
        event = self.publisher._pending[0]
        self.assertEqual(event.event_type, "audio.started")
        self.assertEqual(event.payload["device_index"], 0)
        self.assertEqual(event.payload["sample_rate"], 16000)

    def test_emit_stopped(self):
        self.publisher.emit_stopped()
        self.assertEqual(len(self.publisher._pending), 1)
        event = self.publisher._pending[0]
        self.assertEqual(event.event_type, "audio.stopped")

    def test_emit_device_changed(self):
        self.publisher.emit_device_changed(device_index=2, restarted=True)
        self.assertEqual(len(self.publisher._pending), 1)
        event = self.publisher._pending[0]
        self.assertEqual(event.event_type, "audio.device.changed")
        self.assertEqual(event.payload["device_index"], 2)
        self.assertTrue(event.payload["restarted"])

    def test_drain_now_with_queues(self):
        """drain_now deve colocar eventos nas filas do ConnectionManager."""
        queue = asyncio.Queue(maxsize=10)
        self.manager._queues = {MagicMock(): queue}

        self.publisher.emit_stopped()
        self.publisher.drain_now()

        # Evento deve estar na fila.
        self.assertEqual(queue.qsize(), 1)
        # Pending deve estar vazio.
        self.assertEqual(len(self.publisher._pending), 0)

    def test_drain_now_empty(self):
        """drain_now sem eventos não faz nada."""
        self.publisher.drain_now()
        self.assertEqual(len(self.publisher._pending), 0)

    def test_drain_now_drops_old_when_full(self):
        """drain_now descarta evento antigo se a fila estiver cheia."""
        queue = asyncio.Queue(maxsize=1)
        # Pré-preencher a fila.
        queue.put_nowait("old")
        self.manager._queues = {MagicMock(): queue}

        self.publisher.emit_stopped()
        self.publisher.drain_now()

        # Fila deve ter 1 item (o novo, antigo descartado).
        self.assertEqual(queue.qsize(), 1)
        event = queue.get_nowait()
        self.assertEqual(event.event_type, "audio.stopped")

    def test_on_frame_payload_has_required_fields(self):
        """audio.level deve ter rms, peak, timestamp no payload."""
        frame = AudioFrame(
            timestamp=100.0, sample_rate=16000, channels=1,
            frame_count=480, rms=0.5, peak=0.8,
        )
        self.publisher.on_frame(frame)
        event = self.publisher._pending[0]
        self.assertEqual(event.event_type, "audio.level")
        self.assertEqual(event.payload["rms"], 0.5)
        self.assertEqual(event.payload["peak"], 0.8)
        self.assertEqual(event.payload["timestamp"], 100.0)
        self.assertEqual(event.payload["sample_rate"], 16000)
        self.assertEqual(event.payload["channels"], 1)
        self.assertEqual(event.payload["frame_count"], 480)


if __name__ == "__main__":
    unittest.main()
