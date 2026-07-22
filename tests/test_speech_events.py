"""Testes dos eventos do Sprint 16 — Continuous Speech Pipeline.

Cobre:
  - SpeechStarted, SpeechEnded, SpeechSegmentCreated, SpeechTranscribing, SpeechTranscribed.
  - Serialização to_dict().
  - Imutabilidade (frozen dataclass).
  - Registry inclui novos eventos.
"""

from __future__ import annotations

import unittest

from pipeline.events import (
    SpeechEnded,
    SpeechSegmentCreated,
    SpeechStarted,
    SpeechTranscribed,
    SpeechTranscribing,
    all_event_types,
    all_event_type_names,
    is_pipeline_event,
)
from pipeline.metadata import EventMetadata


def _make_meta(origin: str = "TestOrigin") -> EventMetadata:
    return EventMetadata.for_initial(
        session_id="test-session",
        origin=origin,
        event_id="test-event-id",
        correlation_id="test-correlation-id",
        timestamp=1000.0,
    )


class TestSpeechEvents(unittest.TestCase):
    """Testes dos novos eventos de speech."""

    def test_speech_started(self):
        """SpeechStarted carrega timestamp_start."""
        meta = _make_meta("SpeechPipelineService")
        ev = SpeechStarted(meta=meta, timestamp_start=1234.5)
        self.assertEqual(ev.event_type, "SpeechStarted")
        self.assertEqual(ev.timestamp_start, 1234.5)
        self.assertEqual(ev.origin, "SpeechPipelineService")

    def test_speech_ended(self):
        """SpeechEnded carrega timestamp_end e duration_ms."""
        meta = _make_meta("SpeechPipelineService")
        ev = SpeechEnded(meta=meta, timestamp_end=5678.9, duration_ms=1500)
        self.assertEqual(ev.event_type, "SpeechEnded")
        self.assertEqual(ev.timestamp_end, 5678.9)
        self.assertEqual(ev.duration_ms, 1500)

    def test_speech_segment_created(self):
        """SpeechSegmentCreated carrega metadados do segmento."""
        meta = _make_meta("SpeechPipelineService")
        ev = SpeechSegmentCreated(
            meta=meta,
            duration_ms=2000,
            chunk_count=50,
            sample_rate=16000,
            channels=1,
        )
        self.assertEqual(ev.event_type, "SpeechSegmentCreated")
        self.assertEqual(ev.duration_ms, 2000)
        self.assertEqual(ev.chunk_count, 50)
        self.assertEqual(ev.sample_rate, 16000)
        self.assertEqual(ev.channels, 1)

    def test_speech_transcribing(self):
        """SpeechTranscribing carrega duration_ms."""
        meta = _make_meta("SpeechWorker")
        ev = SpeechTranscribing(meta=meta, duration_ms=3000)
        self.assertEqual(ev.event_type, "SpeechTranscribing")
        self.assertEqual(ev.duration_ms, 3000)

    def test_speech_transcribed(self):
        """SpeechTranscribed carrega texto, language, confidence, latency."""
        meta = _make_meta("SpeechWorker")
        ev = SpeechTranscribed(
            meta=meta,
            text="vamos abrir em joao tres dezesseis",
            language="pt",
            confidence=0.85,
            latency_ms=1200,
            duration_ms=3000,
        )
        self.assertEqual(ev.event_type, "SpeechTranscribed")
        self.assertEqual(ev.text, "vamos abrir em joao tres dezesseis")
        self.assertEqual(ev.language, "pt")
        self.assertEqual(ev.confidence, 0.85)
        self.assertEqual(ev.latency_ms, 1200)
        self.assertEqual(ev.duration_ms, 3000)

    def test_events_are_frozen(self):
        """Todos os novos eventos são imutáveis (frozen dataclass)."""
        meta = _make_meta()
        ev = SpeechStarted(meta=meta, timestamp_start=100.0)
        with self.assertRaises(AttributeError):
            ev.timestamp_start = 200.0  # type: ignore[misc]

    def test_to_dict(self):
        """to_dict inclui event_type, meta e campos específicos."""
        meta = _make_meta("SpeechWorker")
        ev = SpeechTranscribed(
            meta=meta,
            text="teste",
            language="pt",
            confidence=0.9,
            latency_ms=500,
            duration_ms=1000,
        )
        d = ev.to_dict()
        self.assertEqual(d["event_type"], "SpeechTranscribed")
        self.assertIn("meta", d)
        self.assertEqual(d["text"], "teste")
        self.assertEqual(d["language"], "pt")
        self.assertEqual(d["confidence"], 0.9)
        self.assertEqual(d["latency_ms"], 500)

    def test_is_pipeline_event(self):
        """Todos os novos eventos são PipelineEvent."""
        meta = _make_meta()
        for ev in [
            SpeechStarted(meta=meta),
            SpeechEnded(meta=meta),
            SpeechSegmentCreated(meta=meta),
            SpeechTranscribing(meta=meta),
            SpeechTranscribed(meta=meta),
        ]:
            self.assertTrue(is_pipeline_event(ev), f"{ev.event_type} should be PipelineEvent")

    def test_registry_includes_new_events(self):
        """all_event_types inclui os 5 novos eventos do Sprint 16."""
        types = all_event_types()
        names = all_event_type_names()
        for name in ["SpeechStarted", "SpeechEnded", "SpeechSegmentCreated",
                      "SpeechTranscribing", "SpeechTranscribed"]:
            self.assertIn(name, names)
        # 15 originais + 5 Sprint 16 + 3 Sprint 17 + 4 Sprint 18 = 27
        # Sprint 19: +3, Sprint 20: +3, Sprint 21: +4, Sprint 21.1: +1, Sprint 21.4: +1
        self.assertEqual(len(types), 39)


if __name__ == "__main__":
    unittest.main()
