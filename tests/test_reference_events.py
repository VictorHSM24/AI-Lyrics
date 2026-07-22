"""Testes dos eventos do Sprint 17 — Biblical Intent & Reference Extraction.

Cobre:
  - ReferenceDetected, ReferenceInvalid, IntentUnknown.
  - Serialização to_dict().
  - Imutabilidade (frozen dataclass).
  - Registry inclui novos eventos.
"""

from __future__ import annotations

import unittest

from pipeline.events import (
    IntentUnknown,
    ReferenceDetected,
    ReferenceInvalid,
    all_event_types,
    all_event_type_names,
    is_pipeline_event,
)
from pipeline.metadata import EventMetadata


def _make_meta(origin: str = "BiblicalNLUService") -> EventMetadata:
    return EventMetadata.for_initial(
        session_id="test-session",
        origin=origin,
        event_id="test-event-id",
        correlation_id="test-correlation-id",
        timestamp=1000.0,
    )


class TestReferenceEvents(unittest.TestCase):

    def test_reference_detected(self):
        """ReferenceDetected carrega todos os campos da referência."""
        meta = _make_meta()
        ev = ReferenceDetected(
            meta=meta,
            intent="OPEN_REFERENCE",
            book="João",
            book_id=43,
            chapter=3,
            verse_start=16,
            verse_end=16,
            confidence=0.98,
            raw_text="Abra em João capítulo três versículo dezesseis",
            normalized_text="joao 3:16",
        )
        self.assertEqual(ev.event_type, "ReferenceDetected")
        self.assertEqual(ev.intent, "OPEN_REFERENCE")
        self.assertEqual(ev.book, "João")
        self.assertEqual(ev.book_id, 43)
        self.assertEqual(ev.chapter, 3)
        self.assertEqual(ev.verse_start, 16)
        self.assertEqual(ev.verse_end, 16)
        self.assertEqual(ev.confidence, 0.98)
        self.assertEqual(ev.normalized_text, "joao 3:16")

    def test_reference_invalid(self):
        """ReferenceInvalid carrega motivo da invalidade."""
        meta = _make_meta()
        ev = ReferenceInvalid(
            meta=meta,
            book="João",
            book_id=43,
            chapter=300,
            verse_start=0,
            reason="invalid_chapter",
            raw_text="João capítulo 300",
        )
        self.assertEqual(ev.event_type, "ReferenceInvalid")
        self.assertEqual(ev.book, "João")
        self.assertEqual(ev.chapter, 300)
        self.assertEqual(ev.reason, "invalid_chapter")

    def test_intent_unknown(self):
        """IntentUnknown carrega texto e motivo."""
        meta = _make_meta()
        ev = IntentUnknown(
            meta=meta,
            raw_text="olá boa noite",
            reason="no_pattern",
        )
        self.assertEqual(ev.event_type, "IntentUnknown")
        self.assertEqual(ev.raw_text, "olá boa noite")
        self.assertEqual(ev.reason, "no_pattern")

    def test_events_are_frozen(self):
        """Todos os novos eventos são imutáveis."""
        meta = _make_meta()
        ev = ReferenceDetected(meta=meta, book="João", book_id=43, chapter=3)
        with self.assertRaises(AttributeError):
            ev.book = "Romanos"  # type: ignore[misc]

    def test_to_dict(self):
        """to_dict inclui event_type, meta e campos específicos."""
        meta = _make_meta()
        ev = ReferenceDetected(
            meta=meta,
            intent="OPEN_REFERENCE",
            book="João",
            book_id=43,
            chapter=3,
            verse_start=16,
            verse_end=16,
            confidence=0.98,
            raw_text="joao 3 16",
            normalized_text="joao 3:16",
        )
        d = ev.to_dict()
        self.assertEqual(d["event_type"], "ReferenceDetected")
        self.assertIn("meta", d)
        self.assertEqual(d["book"], "João")
        self.assertEqual(d["chapter"], 3)
        self.assertEqual(d["confidence"], 0.98)

    def test_is_pipeline_event(self):
        """Todos os novos eventos são PipelineEvent."""
        meta = _make_meta()
        for ev in [
            ReferenceDetected(meta=meta),
            ReferenceInvalid(meta=meta),
            IntentUnknown(meta=meta),
        ]:
            self.assertTrue(is_pipeline_event(ev), f"{ev.event_type} should be PipelineEvent")

    def test_registry_includes_new_events(self):
        """all_event_types inclui os 3 novos eventos."""
        names = all_event_type_names()
        for name in ["ReferenceDetected", "ReferenceInvalid", "IntentUnknown"]:
            self.assertIn(name, names)
        # 15 originais + 5 Sprint 16 + 3 Sprint 17 + 4 Sprint 18 = 27
        # Sprint 19: +3 (SpeechPartial, SpeechPartialUpdated, ReferenceCandidate)
        # Sprint 20: +3 (IntentCandidate, SemanticInferenceCompleted, SemanticResolutionCompleted)
        # Sprint 21: +4 (SermonContextUpdated, SermonBookChanged, SermonChapterChanged, SermonTopicChanged)
        # Sprint 21.1: +1 (SemanticProviderUnavailable)
        # Sprint 21.4: +1 (ReferenceAntecipada)
        self.assertEqual(len(all_event_types()), 39)
        # Sprint 21.4 — Streaming First.
        self.assertIn("ReferenceAntecipada", names)


if __name__ == "__main__":
    unittest.main()
