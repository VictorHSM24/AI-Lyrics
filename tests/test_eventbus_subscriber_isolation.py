"""Testes de isolamento de exceções no PipelineEventBus (Sprint 23.0).

Valida que uma exceção em um subscriber não impede os demais
subscribers do mesmo evento de serem executados.

Cobre:
  1. Todos os handlers funcionam.
  2. Primeiro handler falha.
  3. Handler intermediário falha.
  4. Último handler falha.
  5. Múltiplos handlers falham.
  6. Tipos diferentes de exceção (ValueError, RuntimeError, TypeError).
  7. Ordem de execução preservada mesmo com falhas.
  8. Unsubscribe continua funcionando.
  9. Subscribe/unsubscribe durante publish.
  10. BaseException (KeyboardInterrupt/SystemExit) não é engolido.
"""

from __future__ import annotations

import logging
import unittest
from typing import Any

from pipeline.bus import PipelineEventBus
from pipeline.events import SpeechRecognized
from pipeline.metadata import EventMetadata


def _make_event(text: str = "hello") -> SpeechRecognized:
    meta = EventMetadata.for_initial(session_id="s1", origin="test")
    return SpeechRecognized(meta=meta, text=text)


class TestSubscriberIsolation(unittest.TestCase):
    """Testes de isolamento de exceções por subscriber no EventBus."""

    def setUp(self) -> None:
        self.bus = PipelineEventBus()

    # ------------------------------------------------------------------
    # TESTE 1 — todos os handlers funcionam
    # ------------------------------------------------------------------

    def test_all_handlers_succeed(self) -> None:
        """A → B → C: todos executam."""
        order: list[str] = []
        self.bus.subscribe(SpeechRecognized, lambda e: order.append("A"))
        self.bus.subscribe(SpeechRecognized, lambda e: order.append("B"))
        self.bus.subscribe(SpeechRecognized, lambda e: order.append("C"))
        self.bus.publish(_make_event())
        self.assertEqual(order, ["A", "B", "C"])

    # ------------------------------------------------------------------
    # TESTE 2 — primeiro handler falha
    # ------------------------------------------------------------------

    def test_first_handler_fails(self) -> None:
        """A falha → B executa → C executa."""
        order: list[str] = []

        def handler_a(_e: Any) -> None:
            order.append("A")
            raise ValueError("A failed")

        self.bus.subscribe(SpeechRecognized, handler_a)
        self.bus.subscribe(SpeechRecognized, lambda e: order.append("B"))
        self.bus.subscribe(SpeechRecognized, lambda e: order.append("C"))
        self.bus.publish(_make_event())
        self.assertEqual(order, ["A", "B", "C"])

    # ------------------------------------------------------------------
    # TESTE 3 — handler intermediário falha
    # ------------------------------------------------------------------

    def test_middle_handler_fails(self) -> None:
        """A executa → B falha → C executa."""
        order: list[str] = []

        def handler_b(_e: Any) -> None:
            order.append("B")
            raise RuntimeError("B failed")

        self.bus.subscribe(SpeechRecognized, lambda e: order.append("A"))
        self.bus.subscribe(SpeechRecognized, handler_b)
        self.bus.subscribe(SpeechRecognized, lambda e: order.append("C"))
        self.bus.publish(_make_event())
        self.assertEqual(order, ["A", "B", "C"])

    # ------------------------------------------------------------------
    # TESTE 4 — último handler falha
    # ------------------------------------------------------------------

    def test_last_handler_fails(self) -> None:
        """A executa → B executa → C falha → publish() retorna normalmente."""
        order: list[str] = []

        def handler_c(_e: Any) -> None:
            order.append("C")
            raise TypeError("C failed")

        self.bus.subscribe(SpeechRecognized, lambda e: order.append("A"))
        self.bus.subscribe(SpeechRecognized, lambda e: order.append("B"))
        self.bus.subscribe(SpeechRecognized, handler_c)
        # Não deve propagar exceção.
        self.bus.publish(_make_event())
        self.assertEqual(order, ["A", "B", "C"])

    # ------------------------------------------------------------------
    # TESTE 5 — múltiplos handlers falham
    # ------------------------------------------------------------------

    def test_multiple_handlers_fail(self) -> None:
        """A falha → B falha → C executa. Ambas exceções registradas."""
        order: list[str] = []

        def handler_a(_e: Any) -> None:
            order.append("A")
            raise ValueError("A failed")

        def handler_b(_e: Any) -> None:
            order.append("B")
            raise RuntimeError("B failed")

        self.bus.subscribe(SpeechRecognized, handler_a)
        self.bus.subscribe(SpeechRecognized, handler_b)
        self.bus.subscribe(SpeechRecognized, lambda e: order.append("C"))
        self.bus.publish(_make_event())
        self.assertEqual(order, ["A", "B", "C"])

    # ------------------------------------------------------------------
    # TESTE 6 — tipos diferentes de exceção
    # ------------------------------------------------------------------

    def test_different_exception_types(self) -> None:
        """ValueError, RuntimeError e TypeError são isoladas igualmente."""
        for exc_type in (ValueError, RuntimeError, TypeError):
            bus = PipelineEventBus()
            order: list[str] = []

            def failing(_e: Any, et=exc_type) -> None:
                order.append("fail")
                raise et("boom")

            bus.subscribe(SpeechRecognized, failing)
            bus.subscribe(SpeechRecognized, lambda e: order.append("ok"))
            bus.publish(_make_event())
            self.assertEqual(order, ["fail", "ok"],
                             f"{exc_type.__name__} não foi isolada")

    # ------------------------------------------------------------------
    # TESTE 7 — ordem preservada com falhas
    # ------------------------------------------------------------------

    def test_order_preserved_with_failures(self) -> None:
        """[A, B, C, D] executam nessa ordem mesmo que B falhe."""
        order: list[str] = []

        def handler_b(_e: Any) -> None:
            order.append("B")
            raise ValueError("B failed")

        self.bus.subscribe(SpeechRecognized, lambda e: order.append("A"))
        self.bus.subscribe(SpeechRecognized, handler_b)
        self.bus.subscribe(SpeechRecognized, lambda e: order.append("C"))
        self.bus.subscribe(SpeechRecognized, lambda e: order.append("D"))
        self.bus.publish(_make_event())
        self.assertEqual(order, ["A", "B", "C", "D"])

    # ------------------------------------------------------------------
    # TESTE 8 — unsubscribe continua funcionando
    # ------------------------------------------------------------------

    def test_unsubscribe_still_works(self) -> None:
        """Handler removido não recebe evento após correção."""
        received: list[str] = []

        def handler(_e: Any) -> None:
            received.append("called")

        self.bus.subscribe(SpeechRecognized, handler)
        self.bus.unsubscribe(SpeechRecognized, handler)
        self.bus.publish(_make_event())
        self.assertEqual(received, [])

    # ------------------------------------------------------------------
    # TESTE 9 — snapshot da lista durante publish
    # ------------------------------------------------------------------

    def test_snapshot_during_publish(self) -> None:
        """Handler que desinscreve outro durante publish não quebra iteração."""
        received: list[str] = []

        def handler_b(e: Any) -> None:
            received.append("B")

        def handler_a(e: Any) -> None:
            received.append("A")
            # Desinscrever B durante publish — não deve afetar iteração atual.
            self.bus.unsubscribe(SpeechRecognized, handler_b)

        self.bus.subscribe(SpeechRecognized, handler_a)
        self.bus.subscribe(SpeechRecognized, handler_b)
        self.bus.subscribe(SpeechRecognized, lambda e: received.append("C"))
        self.bus.publish(_make_event())
        # B já estava no snapshot, então ainda executa neste publish.
        self.assertEqual(received, ["A", "B", "C"])
        # No próximo publish, B não deve estar mais inscrito.
        received.clear()
        self.bus.publish(_make_event())
        self.assertEqual(received, ["A", "C"])

    # ------------------------------------------------------------------
    # TESTE 10 — BaseException não é engolido
    # ------------------------------------------------------------------

    def test_baseexception_not_swallowed(self) -> None:
        """KeyboardInterrupt e SystemExit não devem ser capturados pelo bus."""
        for exc_type in (KeyboardInterrupt, SystemExit):
            bus = PipelineEventBus()

            def failing(_e: Any, et=exc_type) -> None:
                raise et("critical")

            bus.subscribe(SpeechRecognized, failing)
            bus.subscribe(SpeechRecognized, lambda e: None)
            with self.assertRaises(exc_type):
                bus.publish(_make_event())


class TestSubscriberIsolationLogging(unittest.TestCase):
    """Verifica que exceções são logadas com contexto suficiente."""

    def test_exception_logged_with_context(self) -> None:
        """O log deve conter: nome do evento, handler, correlation_id."""
        bus = PipelineEventBus()
        meta = EventMetadata.for_initial(session_id="s1", origin="test")
        event = SpeechRecognized(meta=meta, text="test")

        def failing_handler(_e: Any) -> None:
            raise ValueError("test failure")

        bus.subscribe(SpeechRecognized, failing_handler)

        with self.assertLogs("pipeline.bus", level="ERROR") as cm:
            bus.publish(event)

        log_output = "\n".join(cm.output)
        self.assertIn("SpeechRecognized", log_output)
        self.assertIn("failing_handler", log_output)
        self.assertIn("test failure", log_output)
        self.assertIn(meta.correlation_id, log_output)


if __name__ == "__main__":
    unittest.main()
