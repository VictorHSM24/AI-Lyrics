"""Testes de infraestrutura do StateOrchestrator (CAP-01, Passo 1).

Cobre apenas a infraestrutura:
  - Instanciação correta
  - Estado inicial = WAIT
  - Contexto inicial correto
  - start() registra handlers no EventBus
  - stop() remove handlers do EventBus
  - Properties retornam snapshots imutáveis
  - Componente inicializa sem exceções

Nenhum teste de transição ou máquina de estados.
"""

from __future__ import annotations

import unittest

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    IntentCandidate,
    IntentUnknown,
    ReferenceCandidate,
    ReferenceDetected,
    SpeechTranscribed,
)
from pipeline.metadata import EventMetadata
from pipeline.state_orchestrator import (
    OrchestratorContext,
    State,
    StateOrchestrator,
)


def _make_meta(origin: str = "test") -> EventMetadata:
    """Cria EventMetadata para testes."""
    return EventMetadata.for_initial(
        session_id="test-session",
        origin=origin,
        event_id="test-event-id",
        correlation_id="test-correlation-id",
        timestamp=1000.0,
    )


class TestStateOrchestratorInfra(unittest.TestCase):
    """Testes de infraestrutura do StateOrchestrator."""

    def setUp(self) -> None:
        self.bus = PipelineEventBus()
        self.orch = StateOrchestrator(
            bus=self.bus,
            session_id="test-session",
        )

    # ------------------------------------------------------------------
    # Instanciação
    # ------------------------------------------------------------------

    def test_instantiates_without_exceptions(self):
        """StateOrchestrator instancia sem exceções."""
        orch = StateOrchestrator(bus=self.bus, session_id="s1")
        self.assertIsNotNone(orch)

    def test_instantiates_with_book_names(self):
        """StateOrchestrator aceita book_names opcional."""
        orch = StateOrchestrator(
            bus=self.bus,
            session_id="s1",
            book_names={"João", "Gênesis"},
        )
        self.assertIsNotNone(orch)

    # ------------------------------------------------------------------
    # Estado inicial
    # ------------------------------------------------------------------

    def test_initial_state_is_wait(self):
        """Estado inicial deve ser WAIT."""
        self.assertEqual(self.orch.current_state, State.WAIT)

    def test_initial_state_is_wait_string_compatible(self):
        """State.WAIT é compatível com string 'WAIT'."""
        self.assertEqual(self.orch.current_state, "WAIT")

    # ------------------------------------------------------------------
    # Contexto inicial
    # ------------------------------------------------------------------

    def test_initial_context_current_state(self):
        """Contexto inicial tem current_state = WAIT."""
        ctx = self.orch.context
        self.assertEqual(ctx.current_state, State.WAIT)

    def test_initial_context_active_book_is_none(self):
        """Contexto inicial tem active_book = None."""
        ctx = self.orch.context
        self.assertIsNone(ctx.active_book)

    def test_initial_context_active_book_id_is_zero(self):
        """Contexto inicial tem active_book_id = 0."""
        ctx = self.orch.context
        self.assertEqual(ctx.active_book_id, 0)

    def test_initial_context_active_chapter_is_none(self):
        """Contexto inicial tem active_chapter = None."""
        ctx = self.orch.context
        self.assertIsNone(ctx.active_chapter)

    def test_initial_context_pending_reference_is_none(self):
        """Contexto inicial tem pending_reference = None."""
        ctx = self.orch.context
        self.assertIsNone(ctx.pending_reference)

    def test_initial_context_last_presented_is_none(self):
        """Contexto inicial tem last_presented_reference = None."""
        ctx = self.orch.context
        self.assertIsNone(ctx.last_presented_reference)

    def test_initial_context_segment_count_is_zero(self):
        """Contexto inicial tem segment_count = 0."""
        ctx = self.orch.context
        self.assertEqual(ctx.segment_count_since_last_state_change, 0)

    def test_initial_context_has_biblical_content_is_false(self):
        """Contexto inicial tem has_biblical_content = False."""
        ctx = self.orch.context
        self.assertFalse(ctx.has_biblical_content)

    # ------------------------------------------------------------------
    # Snapshot imutável
    # ------------------------------------------------------------------

    def test_context_returns_copy(self):
        """context property retorna cópia defensiva."""
        ctx1 = self.orch.context
        ctx2 = self.orch.context
        self.assertIsNot(ctx1, ctx2)
        self.assertEqual(ctx1.current_state, ctx2.current_state)

    def test_context_mutation_does_not_affect_orchestrator(self):
        """Mutação do snapshot retornado não afeta o orquestrador."""
        ctx = self.orch.context
        ctx.current_state = State.PRESENT
        ctx.active_book = "João"
        # Orquestrador não foi afetado.
        self.assertEqual(self.orch.current_state, State.WAIT)
        self.assertIsNone(self.orch.context.active_book)

    # ------------------------------------------------------------------
    # start() / stop()
    # ------------------------------------------------------------------

    def test_start_subscribes_to_reference_candidate(self):
        """start() inscreve handler para ReferenceCandidate."""
        self.orch.start()
        self.assertTrue(self.bus.has_subscribers(ReferenceCandidate))

    def test_start_subscribes_to_reference_detected(self):
        """start() inscreve handler para ReferenceDetected."""
        self.orch.start()
        self.assertTrue(self.bus.has_subscribers(ReferenceDetected))

    def test_start_subscribes_to_intent_unknown(self):
        """start() inscreve handler para IntentUnknown."""
        self.orch.start()
        self.assertTrue(self.bus.has_subscribers(IntentUnknown))

    def test_start_subscribes_to_speech_transcribed(self):
        """start() inscreve handler para SpeechTranscribed."""
        self.orch.start()
        self.assertTrue(self.bus.has_subscribers(SpeechTranscribed))

    def test_start_subscribes_to_intent_candidate(self):
        """start() inscreve handler para IntentCandidate."""
        self.orch.start()
        self.assertTrue(self.bus.has_subscribers(IntentCandidate))

    def test_start_registers_five_handlers(self):
        """start() registra exatamente 5 handlers."""
        self.orch.start()
        total = sum(
            1 for et in self.bus.subscribed_types()
            for _ in self.bus.handlers(et)
        )
        self.assertEqual(total, 5)

    def test_start_is_idempotent(self):
        """start() chamado duas vezes não duplica inscrições."""
        self.orch.start()
        self.orch.start()
        total = sum(
            1 for et in self.bus.subscribed_types()
            for _ in self.bus.handlers(et)
        )
        self.assertEqual(total, 5)

    def test_stop_unsubscribes_all(self):
        """stop() remove todas as inscrições."""
        self.orch.start()
        self.orch.stop()
        self.assertFalse(self.bus.has_subscribers(ReferenceCandidate))
        self.assertFalse(self.bus.has_subscribers(ReferenceDetected))
        self.assertFalse(self.bus.has_subscribers(IntentUnknown))
        self.assertFalse(self.bus.has_subscribers(SpeechTranscribed))
        self.assertFalse(self.bus.has_subscribers(IntentCandidate))

    def test_stop_is_idempotent(self):
        """stop() chamado duas vezes não levanta exceção."""
        self.orch.start()
        self.orch.stop()
        self.orch.stop()  # não deve levantar

    def test_stop_without_start(self):
        """stop() sem start() não levanta exceção."""
        self.orch.stop()  # não deve levantar

    # ------------------------------------------------------------------
    # Handlers não publicam eventos (Passo 1 = esqueleto)
    # ------------------------------------------------------------------

    def test_reference_candidate_does_not_publish(self):
        """Handler de ReferenceCandidate não publica StateChanged."""
        self.orch.start()
        meta = _make_meta("IncrementalBiblicalParser")
        self.bus.publish(ReferenceCandidate(
            meta=meta,
            book="João",
            book_id=43,
            chapter=0,
            confidence=0.40,
            completeness="book",
            normalized_text="joão",
        ))
        # Nenhum StateChanged deve estar no EventStore.
        from pipeline.events import StateChanged
        events = [e for e in self.bus.history() if isinstance(e, StateChanged)]
        self.assertEqual(len(events), 0)

    def test_reference_detected_does_not_publish(self):
        """Handler de ReferenceDetected não publica StateChanged."""
        self.orch.start()
        meta = _make_meta("IncrementalBiblicalParser")
        self.bus.publish(ReferenceDetected(
            meta=meta,
            book="João",
            book_id=43,
            chapter=3,
            verse_start=16,
            confidence=0.98,
            normalized_text="joao 3:16",
        ))
        from pipeline.events import StateChanged
        events = [e for e in self.bus.history() if isinstance(e, StateChanged)]
        self.assertEqual(len(events), 0)

    def test_intent_unknown_does_not_publish(self):
        """Handler de IntentUnknown não publica StateChanged."""
        self.orch.start()
        meta = _make_meta("BiblicalNLUService")
        self.bus.publish(IntentUnknown(
            meta=meta,
            raw_text="olá boa noite",
            reason="no_pattern",
        ))
        from pipeline.events import StateChanged
        events = [e for e in self.bus.history() if isinstance(e, StateChanged)]
        self.assertEqual(len(events), 0)

    def test_speech_transcribed_does_not_publish(self):
        """Handler de SpeechTranscribed não publica StateChanged."""
        self.orch.start()
        meta = _make_meta("STT")
        self.bus.publish(SpeechTranscribed(
            meta=meta,
            text="Glória a Deus, bom dia",
            language="pt",
            confidence=0.95,
        ))
        from pipeline.events import StateChanged
        events = [e for e in self.bus.history() if isinstance(e, StateChanged)]
        self.assertEqual(len(events), 0)

    def test_intent_candidate_does_not_publish(self):
        """Handler de IntentCandidate não publica StateChanged."""
        self.orch.start()
        meta = _make_meta("SemanticEngine")
        self.bus.publish(IntentCandidate(
            meta=meta,
            intent="show_reference",
            candidates_json="[]",
            inference_ms=100,
            provider="stub",
            model="stub",
        ))
        from pipeline.events import StateChanged
        events = [e for e in self.bus.history() if isinstance(e, StateChanged)]
        self.assertEqual(len(events), 0)

    # ------------------------------------------------------------------
    # State enum
    # ------------------------------------------------------------------

    def test_state_values_are_strings(self):
        """State enum values são strings compatíveis com benchmark."""
        self.assertEqual(State.WAIT.value, "WAIT")
        self.assertEqual(State.PREPARE.value, "PREPARE")
        self.assertEqual(State.PRESENT.value, "PRESENT")
        self.assertEqual(State.IGNORE.value, "IGNORE")

    def test_state_is_str_subclass(self):
        """State herda de str para compatibilidade com serialização."""
        self.assertIsInstance(State.WAIT, str)
        self.assertIsInstance(State.PREPARE, str)
        self.assertIsInstance(State.PRESENT, str)
        self.assertIsInstance(State.IGNORE, str)


class TestStateChangedEvent(unittest.TestCase):
    """Testes do evento StateChanged (infraestrutura do tipo)."""

    def test_state_changed_is_operational(self):
        """StateChanged é um OperationalEvent."""
        from pipeline.events import (
            StateChanged,
            is_operational_event,
            is_pipeline_event,
        )
        meta = _make_meta("StateOrchestrator")
        ev = StateChanged(
            meta=meta,
            from_state="WAIT",
            to_state="PREPARE",
            reason="book_detected",
        )
        self.assertTrue(is_pipeline_event(ev))
        self.assertTrue(is_operational_event(ev))

    def test_state_changed_is_frozen(self):
        """StateChanged é imutável (frozen dataclass)."""
        from pipeline.events import StateChanged
        meta = _make_meta("StateOrchestrator")
        ev = StateChanged(meta=meta, from_state="WAIT", to_state="PREPARE", reason="book_detected")
        with self.assertRaises(AttributeError):
            ev.from_state = "PRESENT"  # type: ignore[misc]

    def test_state_changed_to_dict(self):
        """StateChanged.to_dict inclui campos específicos."""
        from pipeline.events import StateChanged
        meta = _make_meta("StateOrchestrator")
        ev = StateChanged(
            meta=meta,
            from_state="WAIT",
            to_state="PREPARE",
            reason="book_detected",
            active_book="João",
            active_chapter=0,
            pending_reference="João",
        )
        d = ev.to_dict()
        self.assertEqual(d["event_type"], "StateChanged")
        self.assertEqual(d["from_state"], "WAIT")
        self.assertEqual(d["to_state"], "PREPARE")
        self.assertEqual(d["reason"], "book_detected")
        self.assertEqual(d["active_book"], "João")

    def test_state_changed_in_registry(self):
        """StateChanged está no registry de tipos de evento."""
        from pipeline.events import all_event_type_names
        names = all_event_type_names()
        self.assertIn("StateChanged", names)

    def test_intent_classified_in_registry(self):
        """IntentClassified está no registry de tipos de evento."""
        from pipeline.events import all_event_type_names
        names = all_event_type_names()
        self.assertIn("IntentClassified", names)


if __name__ == "__main__":
    unittest.main()
