"""Testes do SpeechWorker (Sprint 16).

Cobre:
  - Consumo de segmentos da SpeechQueue.
  - Chamada a STT.transcribe().
  - Publicação de eventos SpeechTranscribing e SpeechTranscribed.
  - Tratamento de erro do STT.
  - Métricas (total_transcribed, total_errors).
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

from microfone.capture import SpeechSegment
from microfone.speech_queue import SpeechQueue
from microfone.speech_worker import SpeechWorker
from pipeline.bus import PipelineEventBus
from pipeline.events import SpeechTranscribed, SpeechTranscribing
from transcricao.stt import STTResult


def _make_segment(duration_ms: int = 500) -> SpeechSegment:
    return SpeechSegment(
        audio=b"\x00" * 3200,
        start_time=time.time(),
        end_time=time.time(),
        duration_ms=duration_ms,
        chunk_count=10,
    )


class _FakeSTT:
    """STT fake para testes."""

    def __init__(self, text: str = "teste reconhecido", fail: bool = False, delay: float = 0.01):
        self._text = text
        self._fail = fail
        self._delay = delay
        self.transcribed_segments = []

    def transcribe(self, segment: SpeechSegment) -> STTResult:
        self.transcribed_segments.append(segment)
        if self._delay > 0:
            time.sleep(self._delay)
        if self._fail:
            raise RuntimeError("STT error")
        return STTResult(
            text=self._text,
            language="pt",
            confidence=0.9,
            processing_ms=100,
            audio_duration_ms=segment.duration_ms,
        )


class TestSpeechWorker(unittest.TestCase):

    def setUp(self):
        self.store = MagicMock()
        self.bus = PipelineEventBus(store=self.store)
        self.queue = SpeechQueue(maxsize=10)

    def _make_worker(self, stt):
        return SpeechWorker(
            stt=stt,
            bus=self.bus,
            speech_queue=self.queue,
            session_id="test-session",
        )

    def test_initial_state(self):
        """Worker começa parado."""
        worker = self._make_worker(_FakeSTT())
        self.assertFalse(worker.is_running)
        self.assertEqual(worker.total_transcribed, 0)

    def test_transcribes_segment(self):
        """Worker transcreve segmento da fila e publica eventos."""
        transcribing_events = []
        transcribed_events = []
        self.bus.subscribe(SpeechTranscribing, lambda e: transcribing_events.append(e))
        self.bus.subscribe(SpeechTranscribed, lambda e: transcribed_events.append(e))

        stt = _FakeSTT(text="vamos abrir em joao tres dezesseis")
        worker = self._make_worker(stt)
        worker.start()

        # Enfileirar segmento.
        self.queue.put(_make_segment(500))
        # Aguardar processamento.
        time.sleep(0.5)
        worker.stop()

        self.assertEqual(len(stt.transcribed_segments), 1)
        self.assertEqual(len(transcribing_events), 1)
        self.assertEqual(len(transcribed_events), 1)
        self.assertEqual(transcribed_events[0].text, "vamos abrir em joao tres dezesseis")
        self.assertEqual(transcribed_events[0].language, "pt")
        self.assertGreater(transcribed_events[0].latency_ms, 0)
        self.assertEqual(worker.total_transcribed, 1)
        self.assertEqual(worker.total_errors, 0)

    def test_handles_stt_error(self):
        """Worker lida com erro do STT sem parar."""
        transcribed_events = []
        self.bus.subscribe(SpeechTranscribed, lambda e: transcribed_events.append(e))

        stt = _FakeSTT(fail=True)
        worker = self._make_worker(stt)
        worker.start()

        self.queue.put(_make_segment(500))
        time.sleep(0.5)
        worker.stop()

        # Evento transcribed com texto vazio é publicado mesmo em erro.
        self.assertEqual(len(transcribed_events), 1)
        self.assertEqual(transcribed_events[0].text, "")
        self.assertEqual(worker.total_transcribed, 0)
        self.assertEqual(worker.total_errors, 1)

    def test_stop_is_idempotent(self):
        """stop() pode ser chamado múltiplas vezes sem erro."""
        worker = self._make_worker(_FakeSTT())
        worker.start()
        worker.stop()
        worker.stop()  # não deve levantar exceção

    def test_avg_latency(self):
        """avg_latency_ms retorna média das latências."""
        stt = _FakeSTT()
        worker = self._make_worker(stt)
        worker.start()

        self.queue.put(_make_segment(500))
        self.queue.put(_make_segment(300))
        time.sleep(1.0)
        worker.stop()

        self.assertEqual(worker.total_transcribed, 2)
        self.assertGreater(worker.avg_latency_ms, 0)


if __name__ == "__main__":
    unittest.main()
