"""Testes do BiblicalNLUService (Sprint 17).

Cobre todos os casos exigidos pela sprint:
  - João 3:16
  - João capítulo três
  - João três dezesseis
  - 1 Coríntios 13
  - Primeiro Coríntios treze
  - Efésios dois oito e nove
  - Salmo 23
  - Livro inexistente
  - Capítulo inválido
  - Texto comum sem referência
  - Romanos oito vinte e oito
  - Gênesis capítulo um

Cobre também:
  - Eventos publicados (ReferenceDetected, ReferenceInvalid, IntentUnknown).
  - Confiança calculada (não fixa).
  - Performance < 50ms.
  - Stateless (nenhum estado entre chamadas).
  - Casos inválidos não geram exceções.
"""

from __future__ import annotations

import time
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
        session_id="test-session",
        origin="SpeechWorker",
        event_id="test-event-id",
        correlation_id="test-correlation-id",
        timestamp=1000.0,
    )
    return SpeechTranscribed(
        meta=meta,
        text=text,
        language="pt",
        confidence=0.9,
        latency_ms=500,
        duration_ms=2000,
    )


class TestBiblicalNLUService(unittest.TestCase):
    """Testes do BiblicalNLUService com o Parser determinístico."""

    @classmethod
    def setUpClass(cls):
        """Carrega o Parser uma vez para todos os testes (stateless)."""
        cls.books = load_parser_books("config/books.json")
        cls.normalizer = Normalizer()
        cls.parser = Parser(books=cls.books, normalizer=cls.normalizer)

    def setUp(self):
        self.store = MagicMock()
        self.bus = PipelineEventBus(store=self.store)
        self.nlu = BiblicalNLUService(
            parser=self.parser,
            bus=self.bus,
            session_id="test-session",
        )
        self.nlu.start()

        # Capturar eventos publicados.
        self.events: list = []
        self.bus.subscribe(ReferenceDetected, self.events.append)
        self.bus.subscribe(ReferenceInvalid, self.events.append)
        self.bus.subscribe(IntentUnknown, self.events.append)

    def tearDown(self):
        self.nlu.stop()

    def _process(self, text: str):
        """Processa um texto e retorna os eventos publicados."""
        self.events.clear()
        self.nlu._on_transcribed(_make_transcribed(text))
        return list(self.events)

    # ------------------------------------------------------------------
    # Casos exigidos pela sprint — referências válidas
    # ------------------------------------------------------------------

    def test_joao_3_16(self):
        """'Abra em João 3:16' → ReferenceDetected."""
        events = self._process("abre em joao 3 16")
        detected = [e for e in events if isinstance(e, ReferenceDetected)]
        self.assertEqual(len(detected), 1)
        ev = detected[0]
        self.assertEqual(ev.book, "João")
        self.assertEqual(ev.chapter, 3)
        self.assertEqual(ev.verse_start, 16)
        self.assertGreater(ev.confidence, 0.9)

    def test_joao_capitulo_tres(self):
        """'João capítulo três' → ReferenceDetected (capítulo only)."""
        events = self._process("joao capitulo tres")
        detected = [e for e in events if isinstance(e, ReferenceDetected)]
        self.assertEqual(len(detected), 1)
        ev = detected[0]
        self.assertEqual(ev.book, "João")
        self.assertEqual(ev.chapter, 3)

    def test_joao_tres_dezesseis(self):
        """'João três dezesseis' → ReferenceDetected."""
        events = self._process("joao tres dezesseis")
        detected = [e for e in events if isinstance(e, ReferenceDetected)]
        self.assertEqual(len(detected), 1)
        ev = detected[0]
        self.assertEqual(ev.book, "João")
        self.assertEqual(ev.chapter, 3)
        self.assertEqual(ev.verse_start, 16)

    def test_1_corintios_13(self):
        """'1 Coríntios 13' → ReferenceDetected."""
        events = self._process("1 corintios 13")
        detected = [e for e in events if isinstance(e, ReferenceDetected)]
        self.assertEqual(len(detected), 1)
        ev = detected[0]
        self.assertIn("Coríntios", ev.book)
        self.assertEqual(ev.chapter, 13)

    def test_primeiro_corintios_treze(self):
        """'Primeiro Coríntios treze' → ReferenceDetected."""
        events = self._process("primeiro corintios treze")
        detected = [e for e in events if isinstance(e, ReferenceDetected)]
        self.assertEqual(len(detected), 1)
        ev = detected[0]
        self.assertIn("Coríntios", ev.book)
        self.assertEqual(ev.chapter, 13)

    def test_efesios_dois_oito_e_nove(self):
        """'Efésios dois oito e nove' → ReferenceDetected (versículo range)."""
        events = self._process("efesios dois oito e nove")
        detected = [e for e in events if isinstance(e, ReferenceDetected)]
        self.assertEqual(len(detected), 1)
        ev = detected[0]
        self.assertIn("Efésios", ev.book)
        self.assertEqual(ev.chapter, 2)

    def test_salmo_23(self):
        """'Salmo 23' → ReferenceDetected."""
        events = self._process("salmo 23")
        detected = [e for e in events if isinstance(e, ReferenceDetected)]
        self.assertEqual(len(detected), 1)
        ev = detected[0]
        self.assertIn("Salmos", ev.book)
        self.assertEqual(ev.chapter, 23)

    def test_romanos_oito_vinte_e_oito(self):
        """'Romanos oito vinte e oito' → ReferenceDetected."""
        events = self._process("romanos oito vinte e oito")
        detected = [e for e in events if isinstance(e, ReferenceDetected)]
        self.assertEqual(len(detected), 1)
        ev = detected[0]
        self.assertEqual(ev.book, "Romanos")
        self.assertEqual(ev.chapter, 8)

    def test_genesis_capitulo_um(self):
        """'Gênesis capítulo um' → ReferenceDetected."""
        events = self._process("genesis capitulo um")
        detected = [e for e in events if isinstance(e, ReferenceDetected)]
        self.assertEqual(len(detected), 1)
        ev = detected[0]
        self.assertIn("Gênesis", ev.book)
        self.assertEqual(ev.chapter, 1)

    # ------------------------------------------------------------------
    # Casos inválidos
    # ------------------------------------------------------------------

    def test_livro_inexistente(self):
        """'Livro inexistente' → IntentUnknown (nenhum livro encontrado)."""
        events = self._process("abracadabra 3 16")
        unknown = [e for e in events if isinstance(e, IntentUnknown)]
        self.assertGreaterEqual(len(unknown), 1)

    def test_capitulo_invalido(self):
        """'João capítulo 300' → ReferenceInvalid."""
        events = self._process("joao capitulo 300")
        invalid = [e for e in events if isinstance(e, ReferenceInvalid)]
        self.assertEqual(len(invalid), 1)
        self.assertEqual(invalid[0].reason, "invalid_chapter")

    def test_texto_sem_referencia(self):
        """'Boa noite a todos' → IntentUnknown."""
        events = self._process("boa noite a todos")
        unknown = [e for e in events if isinstance(e, IntentUnknown)]
        self.assertGreaterEqual(len(unknown), 1)

    def test_texto_vazio(self):
        """Texto vazio → IntentUnknown com reason='empty_text'."""
        events = self._process("")
        unknown = [e for e in events if isinstance(e, IntentUnknown)]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0].reason, "empty_text")

    # ------------------------------------------------------------------
    # Propriedades do serviço
    # ------------------------------------------------------------------

    def test_confidence_not_fixed(self):
        """Confiança varia entre padrões (marcadores vs compacto)."""
        # Com marcadores (cap/vers) → 0.98 * 1.0 = 0.98
        events1 = self._process("joao capitulo 3 versiculo 16")
        ev1 = [e for e in events1 if isinstance(e, ReferenceDetected)][0]

        # Compacto (sem marcadores) → 0.95 * 1.0 = 0.95
        events2 = self._process("joao 3 16")
        ev2 = [e for e in events2 if isinstance(e, ReferenceDetected)][0]

        self.assertNotEqual(ev1.confidence, ev2.confidence)
        self.assertGreater(ev1.confidence, ev2.confidence)

    def test_no_exceptions_on_invalid(self):
        """Casos inválidos não geram exceções."""
        for text in ["", "   ", "!!!", "joao capitulo 0", "mateus versiculo",
                      "livro inexistente 999:999", None]:
            try:
                if text is None:
                    self._process("")
                else:
                    self._process(text)
            except Exception as e:
                self.fail(f"Exception raised for {text!r}: {e}")

    def test_stateless(self):
        """Processar o mesmo texto duas vezes produz o mesmo resultado."""
        events1 = self._process("joao 3 16")
        events2 = self._process("joao 3 16")
        self.assertEqual(len(events1), len(events2))
        ev1 = [e for e in events1 if isinstance(e, ReferenceDetected)]
        ev2 = [e for e in events2 if isinstance(e, ReferenceDetected)]
        self.assertEqual(len(ev1), len(ev2))
        if ev1 and ev2:
            self.assertEqual(ev1[0].book, ev2[0].book)
            self.assertEqual(ev1[0].chapter, ev2[0].chapter)

    def test_performance_under_50ms(self):
        """Cada interpretação deve levar < 50ms."""
        texts = [
            "abre em joao capitulo 3 versiculo 16",
            "romanos 8 28",
            "primeiro corintios treze",
            "salmo 23",
            "genesis capitulo um",
            "efesios dois oito e nove",
            "boa noite a todos",
            "joao capitulo 300",
        ]
        for text in texts:
            t0 = time.monotonic()
            self._process(text)
            elapsed_ms = (time.monotonic() - t0) * 1000
            self.assertLess(
                elapsed_ms,
                50.0,
                f"Processing {text!r} took {elapsed_ms:.1f}ms (>50ms)",
            )

    def test_metrics(self):
        """Métricas são atualizadas corretamente."""
        self._process("joao 3 16")
        self._process("joao capitulo 300")
        self._process("boa noite")
        self.assertEqual(self.nlu.total_processed, 3)
        self.assertEqual(self.nlu.total_detected, 1)
        self.assertEqual(self.nlu.total_invalid, 1)
        self.assertGreaterEqual(self.nlu.total_unknown, 1)

    def test_normalized_text(self):
        """normalized_text é gerada corretamente."""
        events = self._process("joao 3 16")
        ev = [e for e in events if isinstance(e, ReferenceDetected)][0]
        self.assertEqual(ev.normalized_text, "joao 3:16")

    def test_start_stop(self):
        """start/stop controlam subscrição."""
        nlu2 = BiblicalNLUService(
            parser=self.parser,
            bus=self.bus,
            session_id="test",
        )
        self.assertFalse(nlu2.is_running)
        nlu2.start()
        self.assertTrue(nlu2.is_running)
        nlu2.stop()
        self.assertFalse(nlu2.is_running)


if __name__ == "__main__":
    unittest.main()
