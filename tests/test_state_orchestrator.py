"""Testes do StateOrchestrator (Sprint 28 — Fase 5).

Valida:
- Transições WAIT/PREPARE/PRESENT/IGNORE.
- StateChanged publicado em todas as transições.
- Dedup por last_presented_reference (repeat = noop).
- Correção de antecipada.
- Inscrição em ReferenceAntecipada + SpeechCommittedWords.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    IntentUnknown,
    ReferenceAntecipada,
    ReferenceCandidate,
    ReferenceDetected,
    SpeechCommittedWords,
    SpeechTranscribed,
    StateChanged,
)
from pipeline.metadata import EventMetadata
from pipeline.state_orchestrator import State, StateOrchestrator


def _make_meta(correlation_id: str = "corr-1") -> EventMetadata:
    return EventMetadata.for_initial(
        session_id="test-session",
        origin="test",
        correlation_id=correlation_id,
    )


def _make_candidate(
    book: str = "João", book_id: int = 43, chapter: int = 0,
    completeness: str = "book", confidence: float = 0.40,
) -> ReferenceCandidate:
    return ReferenceCandidate(
        meta=_make_meta(),
        book=book, book_id=book_id, chapter=chapter,
        verse_start=0, verse_end=0,
        confidence=confidence, completeness=completeness,
        normalized_text="",
    )


def _make_detected(
    book: str = "João", book_id: int = 43, chapter: int = 3,
    verse: int = 16, confidence: float = 0.95,
) -> ReferenceDetected:
    return ReferenceDetected(
        meta=_make_meta(),
        book=book, book_id=book_id, chapter=chapter,
        verse_start=verse, verse_end=0,
        confidence=confidence,
        raw_text="joão 3 16", normalized_text="João 3:16",
    )


def _make_antecipada(
    book: str = "Salmos", book_id: int = 19, chapter: int = 23,
    verse: int = 0, confidence: float = 0.75,
) -> ReferenceAntecipada:
    return ReferenceAntecipada(
        meta=_make_meta(),
        book=book, book_id=book_id, chapter=chapter,
        verse_start=verse, verse_end=0,
        confidence=confidence, completeness="chapter",
        normalized_text="Salmos 23",
    )


def _make_transcribed(text: str = "texto sem referencia") -> SpeechTranscribed:
    return SpeechTranscribed(
        meta=_make_meta(),
        text=text, language="pt",
        confidence=0.9, latency_ms=100,
        duration_ms=6000,
    )


def _make_committed(text: str = "texto") -> SpeechCommittedWords:
    return SpeechCommittedWords(
        meta=_make_meta(),
        committed_text=text, full_committed_text=text,
        words=tuple(), language="pt",
        confidence=0.9, latency_ms=100, audio_duration_ms=6000,
    )


@pytest.fixture
def orchestrator():
    """Cria StateOrchestrator com EventBus e coletor de StateChanged."""
    bus = PipelineEventBus()
    orch = StateOrchestrator(bus=bus, session_id="test-session")
    orch.start()
    changes: list[StateChanged] = []
    bus.subscribe(StateChanged, lambda e: changes.append(e))
    return orch, bus, changes


class TestStateOrchestratorTransitions:
    """Testes das transições de estado."""

    def test_initial_state_is_wait(self, orchestrator):
        """Estado inicial é WAIT."""
        orch, _, _ = orchestrator
        assert orch.current_state == State.WAIT

    def test_wait_to_prepare_on_candidate(self, orchestrator):
        """WAIT → PREPARE ao receber ReferenceCandidate."""
        orch, bus, changes = orchestrator
        bus.publish(_make_candidate(book="João", completeness="book"))
        assert orch.current_state == State.PREPARE
        assert len(changes) == 1
        assert changes[0].from_state == "WAIT"
        assert changes[0].to_state == "PREPARE"
        assert changes[0].reason == "book_detected"

    def test_prepare_to_present_on_detected(self, orchestrator):
        """PREPARE → PRESENT ao receber ReferenceDetected."""
        orch, bus, changes = orchestrator
        bus.publish(_make_candidate(book="João", completeness="book"))
        bus.publish(_make_detected(book="João", chapter=3, verse=16))
        assert orch.current_state == State.PRESENT
        # 2 transições: WAIT→PREPARE, PREPARE→PRESENT.
        assert len(changes) == 2
        assert changes[1].to_state == "PRESENT"

    def test_present_to_wait_on_intent_unknown(self, orchestrator):
        """PRESENT → WAIT ao receber IntentUnknown."""
        orch, bus, changes = orchestrator
        bus.publish(_make_detected())
        bus.publish(IntentUnknown(meta=_make_meta(), raw_text="texto", reason="none"))
        assert orch.current_state == State.WAIT
        assert changes[-1].to_state == "WAIT"

    def test_wait_to_ignore_on_transcribed_no_biblical(self, orchestrator):
        """WAIT → IGNORE ao receber SpeechTranscribed sem pista bíblica."""
        orch, bus, changes = orchestrator
        bus.publish(_make_transcribed("olá como estão vocês"))
        assert orch.current_state == State.IGNORE
        assert changes[-1].to_state == "IGNORE"
        assert changes[-1].reason == "segment_ignored"

    def test_ignore_to_prepare_on_candidate(self, orchestrator):
        """IGNORE → PREPARE ao receber nova ReferenceCandidate."""
        orch, bus, changes = orchestrator
        bus.publish(_make_transcribed("olá pessoal"))
        assert orch.current_state == State.IGNORE
        bus.publish(_make_candidate(book="João"))
        assert orch.current_state == State.PREPARE
        assert changes[-1].from_state == "IGNORE"

    def test_present_to_wait_on_transcribed_no_biblical(self, orchestrator):
        """PRESENT → WAIT ao receber SpeechTranscribed sem pista bíblica."""
        orch, bus, changes = orchestrator
        bus.publish(_make_detected())
        assert orch.current_state == State.PRESENT
        bus.publish(_make_transcribed("obrigado amém"))
        assert orch.current_state == State.WAIT


class TestStateOrchestratorDedup:
    """Testes de dedup por last_presented_reference."""

    def test_same_reference_is_repeat(self, orchestrator):
        """Mesma referência detectada 2x → segunda é repeat (noop)."""
        orch, bus, changes = orchestrator
        bus.publish(_make_detected(book="João", chapter=3, verse=16))
        bus.publish(_make_detected(book="João", chapter=3, verse=16))
        # Segunda deve ser repeat.
        assert changes[-1].reason == "repeat"
        assert changes[-1].repeat is True

    def test_different_reference_is_new(self, orchestrator):
        """Referência diferente → new_reference (não repeat)."""
        orch, bus, changes = orchestrator
        bus.publish(_make_detected(book="João", chapter=3, verse=16))
        bus.publish(_make_detected(book="Romanos", book_id=45, chapter=8, verse=28))
        assert changes[-1].reason == "new_reference"
        assert changes[-1].repeat is False


class TestStateOrchestratorAntecipada:
    """Testes de ReferenceAntecipada."""

    def test_antecipada_transitions_to_present(self, orchestrator):
        """ReferenceAntecipada → PRESENT."""
        orch, bus, changes = orchestrator
        bus.publish(_make_antecipada(book="Salmos", chapter=23, verse=0))
        assert orch.current_state == State.PRESENT
        assert changes[-1].reason == "anticipation"

    def test_antecipada_then_detected_correction(self, orchestrator):
        """Antecipada (Salmos 23) → Detected (Salmos 23:4) = correção.

        §13.5: StateOrchestrator detecta (book, chapter) igual mas verse difere.
        Publica StateChanged com detail="corrected".
        """
        orch, bus, changes = orchestrator
        # Antecipada: Salmos 23 (verse=0).
        bus.publish(_make_antecipada(book="Salmos", book_id=19, chapter=23, verse=0))
        assert orch.current_state == State.PRESENT
        # Detected: Salmos 23:4 (verse=4) — referência diferente (verse mudou).
        bus.publish(_make_detected(book="Salmos", book_id=19, chapter=23, verse=4))
        # Deve ser new_reference (não repeat, pois verse difere).
        assert changes[-1].reason == "new_reference"
        # §13.5: detail deve ser "corrected".
        assert changes[-1].detail == "corrected"

    def test_antecipada_then_same_detected_confirmed(self, orchestrator):
        """Antecipada (Salmos 23) → Detected (Salmos 23, mesma ref) = confirmed.

        §13.5: se antecipada e detected têm mesma referência, marcar
        detail="confirmed" (não reapresentar).
        """
        orch, bus, changes = orchestrator
        # Antecipada: Salmos 23 (verse=0).
        bus.publish(_make_antecipada(book="Salmos", book_id=19, chapter=23, verse=0))
        # Detected: Salmos 23 (mesma ref — verse=0).
        bus.publish(_make_detected(book="Salmos", book_id=19, chapter=23, verse=0))
        # Deve ser repeat (mesma referência).
        assert changes[-1].reason == "repeat"
        # §13.5: detail deve ser "confirmed" (foi antecipada e confirmada).
        assert changes[-1].detail == "confirmed"


class TestStateOrchestratorCommittedWords:
    """Testes de SpeechCommittedWords."""

    def test_committed_updates_has_biblical_content(self, orchestrator):
        """SpeechCommittedWords atualiza has_biblical_content."""
        orch, bus, changes = orchestrator
        bus.publish(_make_committed("vamos abrir em joão capitulo 3"))
        with orch._lock:
            assert orch._ctx.has_biblical_content is True

    def test_committed_no_biblical_content(self, orchestrator):
        """SpeechCommittedWords sem pista bíblica."""
        orch, bus, changes = orchestrator
        bus.publish(_make_committed("olá pessoal tudo bem"))
        with orch._lock:
            assert orch._ctx.has_biblical_content is False

    def test_committed_does_not_publish_state_changed(self, orchestrator):
        """SpeechCommittedWords não publica StateChanged diretamente."""
        orch, bus, changes = orchestrator
        bus.publish(_make_committed("joão capitulo 3"))
        assert len(changes) == 0
