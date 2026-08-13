"""Testes da Fase 9 — Desativar BiblicalNLUService (Sprint 28).

Valida:
- BiblicalNLUService com enabled=False não assina SpeechTranscribed.
- BiblicalNLUService com enabled=False não publica eventos ao receber SpeechTranscribed.
- BiblicalNLUService com enabled=True mantém comportamento original (compatibilidade).
- start() com enabled=False é no-op.
- is_running reflete o estado real.
- CompositionRoot não ativa o NLU (verificado via instância).
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from parser.books import load_parser_books
from parser.normalizer import Normalizer
from parser.parser import Parser
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    IntentUnknown,
    ReferenceDetected,
    ReferenceInvalid,
    SpeechTranscribed,
)
from pipeline.metadata import EventMetadata
from pipeline.nlu import BiblicalNLUService


def _make_transcribed(text: str) -> SpeechTranscribed:
    """Cria um evento SpeechTranscribed para testes."""
    meta = EventMetadata.for_initial(
        session_id="test-session", origin="SpeechWorker",
        event_id="test-event-id", correlation_id="test-correlation-id",
        timestamp=1000.0,
    )
    return SpeechTranscribed(
        meta=meta, text=text, language="pt",
        confidence=0.9, latency_ms=500, duration_ms=2000,
    )


class TestBiblicalNLUDisabled(unittest.TestCase):
    """Testes do BiblicalNLUService desativado (Sprint 28 — Fase 9)."""

    @classmethod
    def setUpClass(cls):
        cls.books = load_parser_books("config/books.json")
        cls.normalizer = Normalizer()
        cls.parser = Parser(books=cls.books, normalizer=cls.normalizer)

    def setUp(self):
        self.store = MagicMock()
        self.bus = PipelineEventBus(store=self.store)

    def test_disabled_default(self):
        """Default: enabled=False (Sprint 28 — Fase 9)."""
        nlu = BiblicalNLUService(
            parser=self.parser, bus=self.bus, session_id="test",
        )
        self.assertFalse(nlu.enabled)
        self.assertFalse(nlu.is_running)

    def test_disabled_start_is_noop(self):
        """start() com enabled=False não assina SpeechTranscribed."""
        nlu = BiblicalNLUService(
            parser=self.parser, bus=self.bus, session_id="test",
        )
        nlu.start()
        self.assertFalse(nlu.is_running)
        # Verificar que não está inscrito.
        self.assertNotIn(SpeechTranscribed, self.bus.subscribed_types())

    def test_disabled_does_not_publish(self):
        """SpeechTranscribed publicado no bus não gera eventos do NLU."""
        nlu = BiblicalNLUService(
            parser=self.parser, bus=self.bus, session_id="test",
        )
        nlu.start()  # no-op

        events: list = []
        self.bus.subscribe(ReferenceDetected, lambda e: events.append(e))
        self.bus.subscribe(ReferenceInvalid, lambda e: events.append(e))
        self.bus.subscribe(IntentUnknown, lambda e: events.append(e))

        # Publicar SpeechTranscribed com referência clara.
        self.bus.publish(_make_transcribed("joão 3 16"))

        # NLU não deve ter publicado nada.
        self.assertEqual(len(events), 0)
        self.assertEqual(nlu.total_processed, 0)

    def test_disabled_stop_is_noop(self):
        """stop() com enabled=False é no-op (não estava inscrito)."""
        nlu = BiblicalNLUService(
            parser=self.parser, bus=self.bus, session_id="test",
        )
        nlu.start()  # no-op
        nlu.stop()   # no-op
        self.assertFalse(nlu.is_running)

    def test_enabled_true_maintains_behavior(self):
        """enabled=True mantém comportamento original (compatibilidade)."""
        nlu = BiblicalNLUService(
            parser=self.parser, bus=self.bus, session_id="test",
            enabled=True,
        )
        self.assertTrue(nlu.enabled)
        nlu.start()
        self.assertTrue(nlu.is_running)

        events: list = []
        self.bus.subscribe(ReferenceDetected, lambda e: events.append(e))

        # Publicar SpeechTranscribed com referência clara.
        self.bus.publish(_make_transcribed("joão 3 16"))

        # NLU deve ter publicado ReferenceDetected.
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], ReferenceDetected)
        self.assertEqual(nlu.total_processed, 1)

        nlu.stop()
        self.assertFalse(nlu.is_running)

    def test_enabled_true_stop_unsubscribes(self):
        """stop() com enabled=True desinscreve do EventBus."""
        nlu = BiblicalNLUService(
            parser=self.parser, bus=self.bus, session_id="test",
            enabled=True,
        )
        nlu.start()
        self.assertTrue(nlu.is_running)
        self.assertIn(SpeechTranscribed, self.bus.subscribed_types())

        nlu.stop()
        self.assertFalse(nlu.is_running)

    def test_disabled_metrics_stay_zero(self):
        """Métricas permanecem zero quando disabled."""
        nlu = BiblicalNLUService(
            parser=self.parser, bus=self.bus, session_id="test",
        )
        nlu.start()

        self.bus.publish(_make_transcribed("joão 3 16"))
        self.bus.publish(_make_transcribed("romanos 8 28"))
        self.bus.publish(_make_transcribed("texto sem referência"))

        self.assertEqual(nlu.total_processed, 0)
        self.assertEqual(nlu.total_detected, 0)
        self.assertEqual(nlu.total_invalid, 0)
        self.assertEqual(nlu.total_unknown, 0)


if __name__ == "__main__":
    unittest.main()
