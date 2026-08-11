"""Teste de integração — reproduz o bug real de isolamento de subscriber.

Reproduz a cadeia de produção:

  SpeechPartial
      ↓
  IncrementalBiblicalParser._on_partial  (handler 1)
      ↓
  SermonMemoryEngine._on_partial          (handler 2)
      ↓
  SemanticEngine._on_partial              (handler 3)

Cenário 1: SermonMemoryEngine lança exceção → SemanticEngine deve
           ainda receber o SpeechPartial.

Cenário 2: IncrementalBiblicalParser lança exceção → SemanticEngine
           deve ainda receber o SpeechPartial.

Cenário 3: Ambos (Incremental + Sermon) lançam exceção → SemanticEngine
           deve ainda receber o SpeechPartial.

Cenário 4: Nenhum falha → fluxo normal preservado.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from pipeline.bus import PipelineEventBus
from pipeline.events import SpeechPartial, SpeechPartialUpdated
from pipeline.metadata import EventMetadata


def _make_speech_partial(text: str = "As minhas ovelhas ouvem a minha voz") -> SpeechPartial:
    meta = EventMetadata.for_initial(session_id="s1", origin="StreamingSTTService")
    return SpeechPartial(
        meta=meta, text=text, language="pt", confidence=0.85,
        latency_ms=500, audio_duration_ms=6000, is_stable=False,
    )


class TestSubscriberIsolationIntegration(unittest.TestCase):
    """Testa isolamento na cadeia real de SpeechPartial."""

    def setUp(self) -> None:
        self.bus = PipelineEventBus()
        self.received: dict[str, list[str]] = {
            "incremental": [],
            "sermon": [],
            "semantic": [],
        }

    def _make_incremental_handler(self, should_fail: bool = False) -> Any:
        def handler(event: SpeechPartial) -> None:
            self.received["incremental"].append(event.text)
            if should_fail:
                raise ValueError("IncrementalParser simulated failure")
        return handler

    def _make_sermon_handler(self, should_fail: bool = False) -> Any:
        def handler(event: SpeechPartial) -> None:
            self.received["sermon"].append(event.text)
            if should_fail:
                raise RuntimeError("SermonMemoryEngine simulated failure")
        return handler

    def _make_semantic_handler(self) -> Any:
        def handler(event: SpeechPartial) -> None:
            self.received["semantic"].append(event.text)
        return handler

    # ------------------------------------------------------------------
    # Cenário 1 — SermonMemoryEngine falha, SemanticEngine recebe
    # ------------------------------------------------------------------

    def test_sermon_fails_semantic_still_receives(self) -> None:
        """SermonMemoryEngine lança exceção; SemanticEngine ainda recebe."""
        self.bus.subscribe(SpeechPartial, self._make_incremental_handler())
        self.bus.subscribe(SpeechPartial, self._make_sermon_handler(should_fail=True))
        self.bus.subscribe(SpeechPartial, self._make_semantic_handler())

        event = _make_speech_partial("As minhas ovelhas ouvem a minha voz")
        self.bus.publish(event)

        self.assertEqual(len(self.received["incremental"]), 1)
        self.assertEqual(len(self.received["sermon"]), 1)
        self.assertEqual(len(self.received["semantic"]), 1,
                         "SemanticEngine não recebeu SpeechPartial após falha de SermonMemoryEngine")
        self.assertEqual(self.received["semantic"][0], "As minhas ovelhas ouvem a minha voz")

    # ------------------------------------------------------------------
    # Cenário 2 — IncrementalBiblicalParser falha, SemanticEngine recebe
    # ------------------------------------------------------------------

    def test_incremental_fails_semantic_still_receives(self) -> None:
        """IncrementalParser lança exceção; SemanticEngine ainda recebe."""
        self.bus.subscribe(SpeechPartial, self._make_incremental_handler(should_fail=True))
        self.bus.subscribe(SpeechPartial, self._make_sermon_handler())
        self.bus.subscribe(SpeechPartial, self._make_semantic_handler())

        event = _make_speech_partial("Quando Jesus fala sobre as suas ovelhas")
        self.bus.publish(event)

        self.assertEqual(len(self.received["incremental"]), 1)
        self.assertEqual(len(self.received["sermon"]), 1)
        self.assertEqual(len(self.received["semantic"]), 1,
                         "SemanticEngine não recebeu SpeechPartial após falha de IncrementalParser")
        self.assertEqual(self.received["semantic"][0], "Quando Jesus fala sobre as suas ovelhas")

    # ------------------------------------------------------------------
    # Cenário 3 — Ambos falham, SemanticEngine ainda recebe
    # ------------------------------------------------------------------

    def test_both_fail_semantic_still_receives(self) -> None:
        """Incremental + Sermon falham; SemanticEngine ainda recebe."""
        self.bus.subscribe(SpeechPartial, self._make_incremental_handler(should_fail=True))
        self.bus.subscribe(SpeechPartial, self._make_sermon_handler(should_fail=True))
        self.bus.subscribe(SpeechPartial, self._make_semantic_handler())

        event = _make_speech_partial("Há tantas espécies de vozes no mundo")
        self.bus.publish(event)

        self.assertEqual(len(self.received["incremental"]), 1)
        self.assertEqual(len(self.received["sermon"]), 1)
        self.assertEqual(len(self.received["semantic"]), 1,
                         "SemanticEngine não recebeu SpeechPartial quando ambos anteriores falharam")
        self.assertEqual(self.received["semantic"][0], "Há tantas espécies de vozes no mundo")

    # ------------------------------------------------------------------
    # Cenário 4 — Nenhum falha, fluxo normal preservado
    # ------------------------------------------------------------------

    def test_no_failures_all_receive(self) -> None:
        """Nenhum handler falha; todos recebem o evento normalmente."""
        self.bus.subscribe(SpeechPartial, self._make_incremental_handler())
        self.bus.subscribe(SpeechPartial, self._make_sermon_handler())
        self.bus.subscribe(SpeechPartial, self._make_semantic_handler())

        event = _make_speech_partial("João 10:27")
        self.bus.publish(event)

        self.assertEqual(len(self.received["incremental"]), 1)
        self.assertEqual(len(self.received["sermon"]), 1)
        self.assertEqual(len(self.received["semantic"]), 1)
        self.assertEqual(self.received["semantic"][0], "João 10:27")

    # ------------------------------------------------------------------
    # Cenário 5 — SpeechPartialUpdated também é isolado
    # ------------------------------------------------------------------

    def test_partial_updated_isolation(self) -> None:
        """Isolamento também funciona para SpeechPartialUpdated."""
        received: list[str] = []

        def failing(_e: Any) -> None:
            raise RuntimeError("fail on updated")

        def receiver(event: SpeechPartialUpdated) -> None:
            received.append(event.text)

        self.bus.subscribe(SpeechPartialUpdated, failing)
        self.bus.subscribe(SpeechPartialUpdated, receiver)

        meta = EventMetadata.for_initial(session_id="s1", origin="test")
        event = SpeechPartialUpdated(
            meta=meta, text="João 10:27", appended_text="27",
            language="pt", confidence=0.9, latency_ms=100,
            audio_duration_ms=6000, is_stable=False,
        )
        self.bus.publish(event)
        self.assertEqual(received, ["João 10:27"])

    # ------------------------------------------------------------------
    # Cenário 6 — Ordem real de inscrição preservada
    # ------------------------------------------------------------------

    def test_real_subscription_order_preserved(self) -> None:
        """Ordem Incremental → Sermon → Semantic é preservada."""
        order: list[str] = []

        def inc(_e: Any) -> None:
            order.append("incremental")

        def ser(_e: Any) -> None:
            order.append("sermon")
            raise RuntimeError("sermon fail")

        def sem(_e: Any) -> None:
            order.append("semantic")

        self.bus.subscribe(SpeechPartial, inc)
        self.bus.subscribe(SpeechPartial, ser)
        self.bus.subscribe(SpeechPartial, sem)

        self.bus.publish(_make_speech_partial())
        self.assertEqual(order, ["incremental", "sermon", "semantic"])


if __name__ == "__main__":
    unittest.main()
