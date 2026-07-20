"""Testes do SpeechPipelineService (Sprint 16).

Cobre:
  - Início/fim do pipeline.
  - Callback on_audio_data enfileira chunks.
  - VAD thread processa chunks e emite eventos.
  - Eventos SpeechStarted/Ended/SegmentCreated publicados no EventBus.
  - Segmentos enfileirados na SpeechQueue.
  - stop() faz flush final.
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

import numpy as np

from config.models import AudioConfig
from microfone.capture import SpeechSegment, VadSegmenter
from microfone.speech_pipeline import SpeechPipelineService
from microfone.speech_queue import SpeechQueue
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    SpeechEnded,
    SpeechSegmentCreated,
    SpeechStarted,
)


class _FakeCapture:
    """AudioCaptureService fake para testes."""

    def __init__(self):
        self._on_audio_data = None

    def set_on_audio_data(self, callback):
        self._on_audio_data = callback


class _ControllableVad:
    """VAD mockado que detecta fala baseado em amplitude do chunk.

    Retorna True se o RMS do chunk > threshold.
    """

    def __init__(self, threshold: float = 100.0):
        self._threshold = threshold

    def is_speech(self, pcm: bytes, sample_rate: int) -> bool:
        import numpy as np
        if len(pcm) == 0:
            return False
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
        rms = np.sqrt(np.mean(samples ** 2)) if len(samples) > 0 else 0.0
        return bool(rms > self._threshold)


class _FakeVad(VadSegmenter):
    """VadSegmenter com VAD mockado controlável."""

    def __init__(self):
        super().__init__(
            sample_rate=16000,
            chunk_ms=30,
            min_speech_ms=100,
            max_silence_ms=90,  # 3 chunks de silêncio
            vad_mode=3,
            vad=_ControllableVad(threshold=100.0),
        )


def _make_audio_config():
    return AudioConfig(
        input_device="test",
        sample_rate=16000,
        channels=1,
        chunk_ms=30,
        vad_enabled=True,
        min_speech_ms=100,
        max_silence_ms=90,
        vad_mode=3,
        max_segment_ms=30000,
    )


def _make_chunk(duration_ms: int = 30, amplitude: float = 0.5):
    """Cria um chunk de áudio float32 (30ms @ 16kHz = 480 samples).

    Usa ruído aleatório (não DC) para que o VAD Silero detecte como fala.
    """
    samples = int(16000 * duration_ms / 1000)
    if amplitude > 0:
        # Ruído aleatório normalizado para amplitude desejada.
        rng = np.random.default_rng(42)
        return (rng.standard_normal(samples) * amplitude).astype(np.float32)
    return np.zeros(samples, dtype=np.float32)


class TestSpeechPipelineService(unittest.TestCase):

    def setUp(self):
        self.capture = _FakeCapture()
        self.config = _make_audio_config()
        self.store = MagicMock()
        self.bus = PipelineEventBus(store=self.store)
        self.queue = SpeechQueue(maxsize=10)
        self.segmenter = _FakeVad()
        self.pipeline = SpeechPipelineService(
            capture_service=self.capture,
            audio_config=self.config,
            bus=self.bus,
            speech_queue=self.queue,
            session_id="test-session",
            segmenter=self.segmenter,
        )

    def tearDown(self):
        if self.pipeline.is_running:
            self.pipeline.stop()

    def test_initial_state(self):
        """Pipeline começa parado."""
        self.assertFalse(self.pipeline.is_running)
        self.assertFalse(self.pipeline.in_speech)

    def test_start_connects_callback(self):
        """start() conecta o callback ao AudioCaptureService."""
        self.pipeline.start()
        self.assertTrue(self.pipeline.is_running)
        self.assertIsNotNone(self.capture._on_audio_data)
        self.pipeline.stop()

    def test_stop_disconnects_callback(self):
        """stop() desconecta o callback."""
        self.pipeline.start()
        self.pipeline.stop()
        self.assertFalse(self.pipeline.is_running)
        self.assertIsNone(self.capture._on_audio_data)

    def test_speech_started_event(self):
        """Processar chunk de fala emite SpeechStarted."""
        events = []
        self.bus.subscribe(SpeechStarted, lambda e: events.append(e))

        self.pipeline.start()
        # Simular chunk de fala.
        chunk = _make_chunk(amplitude=0.8)
        self.capture._on_audio_data(chunk, time.time())
        # Aguardar VAD thread processar.
        time.sleep(0.3)

        self.assertTrue(self.pipeline.in_speech)
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], SpeechStarted)
        self.pipeline.stop()

    def test_speech_ended_and_segment_created(self):
        """Fala seguida de silêncio emite SpeechEnded e SpeechSegmentCreated."""
        started = []
        ended = []
        created = []
        self.bus.subscribe(SpeechStarted, lambda e: started.append(e))
        self.bus.subscribe(SpeechEnded, lambda e: ended.append(e))
        self.bus.subscribe(SpeechSegmentCreated, lambda e: created.append(e))

        self.pipeline.start()
        # Enviar 5 chunks de fala (150ms > min_speech_ms=100).
        for _ in range(5):
            self.capture._on_audio_data(_make_chunk(amplitude=0.8), time.time())
            time.sleep(0.05)
        # Enviar 5 chunks de silêncio (150ms > max_silence_ms=90).
        for _ in range(5):
            self.capture._on_audio_data(_make_chunk(amplitude=0.0), time.time())
            time.sleep(0.05)
        # Aguardar processamento.
        time.sleep(0.5)

        self.assertGreaterEqual(len(started), 1)
        self.assertGreaterEqual(len(ended), 1)
        self.assertGreaterEqual(len(created), 1)
        # Segmento deve estar na fila.
        self.assertGreater(self.queue.qsize(), 0)
        self.pipeline.stop()

    def test_segment_enqueued(self):
        """Segmento completo é enfileirado na SpeechQueue."""
        self.pipeline.start()
        # Fala.
        for _ in range(5):
            self.capture._on_audio_data(_make_chunk(amplitude=0.8), time.time())
            time.sleep(0.03)
        # Silêncio.
        for _ in range(5):
            self.capture._on_audio_data(_make_chunk(amplitude=0.0), time.time())
            time.sleep(0.03)
        time.sleep(0.3)

        segment = self.queue.get(timeout=1.0)
        self.assertIsNotNone(segment)
        self.assertIsInstance(segment, SpeechSegment)
        self.assertGreater(segment.duration_ms, 0)
        self.pipeline.stop()


if __name__ == "__main__":
    unittest.main()
