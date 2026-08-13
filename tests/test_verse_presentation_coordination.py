"""Testes de coordenação VersePresentationService ↔ StateOrchestrator.

Sprint 28 — Fase 6.

Valida:
- VersePresentationService consulta StateOrchestrator.current_state == PRESENT.
- Dedup por (book_id, chapter, verse) via last_presented_reference.
- Apresentação rejeitada quando estado != PRESENT.
- Apresentação rejeitada quando referência já apresentada (dedup).
- Fallback: sem StateOrchestrator, apresenta sempre.
- Correção de antecipada coordenada.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    ReferenceAntecipada,
    ReferenceDetected,
    VersePresented,
    VersePresentationFailed,
    VerseResolved,
    VerseResolving,
)
from pipeline.metadata import EventMetadata
from pipeline.state_orchestrator import State, StateOrchestrator
from presentation.verse_presentation_service import VersePresentationService


def _make_meta(correlation_id: str = "corr-1") -> EventMetadata:
    return EventMetadata.for_initial(
        session_id="test-session",
        origin="test",
        correlation_id=correlation_id,
    )


def _make_search_result(
    book: str = "João", book_id: int = 43, chapter: int = 3,
    verse: int = 16, reference: str = "João 3:16",
) -> MagicMock:
    """Cria um mock de SearchResult."""
    r = MagicMock()
    r.book = book
    r.book_id = book_id
    r.chapter = chapter
    r.verse = verse
    r.reference = reference
    r.version = "ACF"
    r.text = "Porque Deus amou o mundo..."
    return r


def _make_detected(
    book: str = "João", book_id: int = 43, chapter: int = 3,
    verse: int = 16, confidence: float = 0.95,
    correlation_id: str = "corr-1",
) -> ReferenceDetected:
    return ReferenceDetected(
        meta=_make_meta(correlation_id),
        book=book, book_id=book_id, chapter=chapter,
        verse_start=verse, verse_end=0,
        confidence=confidence,
        raw_text="joão 3 16", normalized_text=f"{book} {chapter}:{verse}",
    )


def _make_antecipada(
    book: str = "Salmos", book_id: int = 19, chapter: int = 23,
    verse: int = 0, confidence: float = 0.75,
    correlation_id: str = "corr-2",
) -> ReferenceAntecipada:
    return ReferenceAntecipada(
        meta=_make_meta(correlation_id),
        book=book, book_id=book_id, chapter=chapter,
        verse_start=verse, verse_end=0,
        confidence=confidence, completeness="chapter",
        normalized_text=f"{book} {chapter}",
    )


@pytest.fixture
def setup():
    """Cria bus, StateOrchestrator, VersePresentationService com mocks."""
    bus = PipelineEventBus()
    orch = StateOrchestrator(bus=bus, session_id="test")
    orch.start()

    searcher = MagicMock()
    holyrics = MagicMock()
    holyrics.show_verse_references.return_value = {"status": "ok"}

    vps = VersePresentationService(
        searcher=searcher,
        holyrics=holyrics,
        bus=bus,
        session_id="test",
        version="ACF",
    )
    vps.start()
    vps.set_state_orchestrator(orch)

    # Coletar eventos.
    presented: list[VersePresented] = []
    failed: list[VersePresentationFailed] = []
    bus.subscribe(VersePresented, lambda e: presented.append(e))
    bus.subscribe(VersePresentationFailed, lambda e: failed.append(e))

    return bus, orch, vps, searcher, holyrics, presented, failed


class TestVersePresentationCoordination:
    """Testes de coordenação com StateOrchestrator."""

    def test_presents_when_state_present(self, setup):
        """Apresenta quando StateOrchestrator.current_state == PRESENT."""
        bus, orch, vps, searcher, holyrics, presented, failed = setup
        searcher.search_by_reference.return_value = _make_search_result()
        # Disparar ReferenceDetected — StateOrchestrator transita para PRESENT.
        bus.publish(_make_detected())
        # StateOrchestrator processa primeiro (PRESENT), depois VPS apresenta.
        assert orch.current_state == State.PRESENT
        assert len(presented) == 1
        assert holyrics.show_verse_references.called

    def test_rejects_when_state_wait(self, setup):
        """Rejeita apresentação quando estado == WAIT (sem ReferenceDetected)."""
        bus, orch, vps, searcher, holyrics, presented, failed = setup
        searcher.search_by_reference.return_value = _make_search_result()
        # Publicar ReferenceDetected com correlation_id diferente —
        # StateOrchestrator transita para PRESENT.
        # Mas para testar rejeição, precisamos que o VPS receba o evento
        # ANTES do StateOrchestrator. Como o EventBus é síncrono e a ordem
        # de inscrição importa, o StateOrchestrator foi inscrito primeiro.
        # Vamos simular: forçar estado WAIT e publicar diretamente no VPS.
        orch._ctx.current_state = State.WAIT
        with orch._lock:
            orch._ctx.current_state = State.WAIT
        # Chamar VPS diretamente (não via bus, para não acionar StateOrchestrator).
        vps._on_reference_detected(_make_detected())
        # Não deve apresentar.
        assert len(presented) == 0
        assert holyrics.show_verse_references.called is False

    def test_dedup_rejects_same_reference(self, setup):
        """Dedup: mesma referência (book_id, chapter, verse) é rejeitada.

        Sprint 28 (Fase 6) — o VPS mantém _last_presented_key interno
        (não consulta last_presented_reference do StateOrchestrator,
        que é atualizado antes do VPS processar o evento). O dedup
        interno é atualizado apenas após apresentação bem-sucedida.
        """
        bus, orch, vps, searcher, holyrics, presented, failed = setup
        searcher.search_by_reference.return_value = _make_search_result()
        # Primeira apresentação — transita para PRESENT, VPS apresenta.
        bus.publish(_make_detected())
        assert len(presented) == 1
        # Segunda vez — mesma referência.
        # StateOrchestrator processa primeiro (marca "repeat", mantém PRESENT).
        # VPS processa depois: current_state == PRESENT (OK), mas
        # _last_presented_key == (43, 3, 16) → rejeita por dedup interno.
        bus.publish(_make_detected())
        # A segunda não deve apresentar no Holyrics.
        assert holyrics.show_verse_references.call_count == 1
        assert vps._total_dedup_rejected >= 1

    def test_presents_different_reference(self, setup):
        """Referência diferente é apresentada (não dedup)."""
        bus, orch, vps, searcher, holyrics, presented, failed = setup
        # Primeira referência.
        searcher.search_by_reference.return_value = _make_search_result(
            book="João", book_id=43, chapter=3, verse=16,
        )
        bus.publish(_make_detected(book="João", book_id=43, chapter=3, verse=16))
        assert len(presented) == 1
        # Segunda referência — diferente.
        searcher.search_by_reference.return_value = _make_search_result(
            book="Romanos", book_id=45, chapter=8, verse=28,
            reference="Romanos 8:28",
        )
        bus.publish(_make_detected(
            book="Romanos", book_id=45, chapter=8, verse=28,
        ))
        # Deve apresentar a nova referência.
        assert len(presented) == 2

    def test_fallback_without_state_orchestrator(self):
        """Sem StateOrchestrator, apresenta sempre (fallback)."""
        bus = PipelineEventBus()
        searcher = MagicMock()
        holyrics = MagicMock()
        holyrics.show_verse_references.return_value = {"status": "ok"}
        searcher.search_by_reference.return_value = _make_search_result()

        vps = VersePresentationService(
            searcher=searcher, holyrics=holyrics, bus=bus,
            session_id="test", version="ACF",
        )
        vps.start()
        # NÃO injetar StateOrchestrator.
        presented: list[VersePresented] = []
        bus.subscribe(VersePresented, lambda e: presented.append(e))
        bus.publish(_make_detected())
        assert len(presented) == 1
        assert holyrics.show_verse_references.called

    def test_correction_presented_when_state_present(self, setup):
        """Correção de antecipada é apresentada quando estado == PRESENT."""
        bus, orch, vps, searcher, holyrics, presented, failed = setup
        # Antecipada: Salmos 23 (verse=0).
        searcher.search_by_reference.return_value = _make_search_result(
            book="Salmos", book_id=19, chapter=23, verse=0,
            reference="Salmos 23",
        )
        bus.publish(_make_antecipada(
            book="Salmos", book_id=19, chapter=23, verse=0,
            correlation_id="corr-2",
        ))
        assert len(presented) == 1
        # Detected: Salmos 23:4 (verse=4) — correção.
        searcher.search_by_reference.return_value = _make_search_result(
            book="Salmos", book_id=19, chapter=23, verse=4,
            reference="Salmos 23:4",
        )
        bus.publish(_make_detected(
            book="Salmos", book_id=19, chapter=23, verse=4,
            correlation_id="corr-2",
        ))
        # Deve apresentar a correção.
        assert len(presented) == 2

    def test_state_rejected_metric_incremented(self, setup):
        """Métrica _total_state_rejected é incrementada quando rejeitado."""
        bus, orch, vps, searcher, holyrics, presented, failed = setup
        searcher.search_by_reference.return_value = _make_search_result()
        # Forçar estado WAIT.
        with orch._lock:
            orch._ctx.current_state = State.WAIT
        # Chamar VPS diretamente.
        vps._on_reference_detected(_make_detected())
        assert vps._total_state_rejected >= 1
