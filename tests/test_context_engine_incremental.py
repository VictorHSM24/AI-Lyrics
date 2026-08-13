"""Testes do ContextEngine incremental (Sprint 28 — Fase 4).

Valida:
- ContextEngine mantém cache próprio via inscrição em SpeechCommittedWords.
- ContextEngine mantém último ReferenceDetected via inscrição.
- build() NÃO chama bus.history() quando inscrito.
- Buffer circular limita número de committed words.
- Janela temporal filtra eventos antigos.
- Fallback para history_fn quando bus não disponível.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    ReferenceDetected,
    SpeechCommittedWords,
    SpeechPartial,
)
from pipeline.metadata import EventMetadata
from semantic.context_engine import ContextEngine


def _make_meta(correlation_id: str = "corr-1") -> EventMetadata:
    return EventMetadata.for_initial(
        session_id="test-session",
        origin="StreamingSTTService",
        correlation_id=correlation_id,
    )


def _make_committed(
    text: str,
    correlation_id: str = "corr-1",
    timestamp: float | None = None,
) -> SpeechCommittedWords:
    meta = _make_meta(correlation_id)
    if timestamp is not None:
        meta = EventMetadata(
            event_id=meta.event_id,
            correlation_id=meta.correlation_id,
            causation_id=meta.causation_id,
            session_id=meta.session_id,
            timestamp=timestamp,
            origin=meta.origin,
        )
    return SpeechCommittedWords(
        meta=meta, committed_text=text, full_committed_text=text,
        words=tuple(), language="pt",
        confidence=0.9, latency_ms=100, audio_duration_ms=2000,
    )


def _make_ref_detected(
    book: str = "João",
    chapter: int = 3,
    verse: int = 16,
) -> ReferenceDetected:
    return ReferenceDetected(
        meta=_make_meta(),
        book=book, chapter=chapter, verse_start=verse,
        confidence=0.95,
        raw_text="joão 3 16",
        normalized_text="João 3:16",
    )


class TestContextEngineIncremental:
    """Testes do cache incremental do ContextEngine."""

    def test_subscribes_to_committed_and_reference(self):
        """ContextEngine inscreve em SpeechCommittedWords + ReferenceDetected."""
        bus = PipelineEventBus()
        ce = ContextEngine(bus=bus)
        assert ce._subscribed is True

    def test_committed_words_added_to_buffer(self):
        """SpeechCommittedWords é adicionado ao buffer interno."""
        bus = PipelineEventBus()
        ce = ContextEngine(bus=bus)
        bus.publish(_make_committed("o senhor é meu pastor"))
        with ce._lock:
            assert len(ce._committed_buffer) == 1
            assert ce._committed_buffer[0][1] == "o senhor é meu pastor"

    def test_reference_detected_stored(self):
        """ReferenceDetected é armazenado internamente."""
        bus = PipelineEventBus()
        ce = ContextEngine(bus=bus)
        bus.publish(_make_ref_detected("Salmos", 23, 1))
        with ce._lock:
            assert ce._last_reference is not None
            assert ce._last_reference.book == "Salmos"
            assert ce._last_reference.chapter == 23

    def test_build_uses_cache_not_history(self):
        """build() usa cache interno, não bus.history()."""
        history_called = []
        bus = PipelineEventBus()

        def history_fn():
            history_called.append(True)
            return []

        ce = ContextEngine(history_fn=history_fn, bus=bus)
        bus.publish(_make_committed("texto anterior do pregador"))
        ctx = ce.build(current_text="atual")
        # history_fn NÃO deve ter sido chamada (cache incremental usado).
        assert len(history_called) == 0
        assert "texto anterior" in ctx.recent_text

    def test_build_excludes_current_text(self):
        """build() não inclui current_text no recent_text."""
        bus = PipelineEventBus()
        ce = ContextEngine(bus=bus)
        bus.publish(_make_committed("texto atual"))
        ctx = ce.build(current_text="texto atual")
        assert ctx.recent_text == ""

    def test_window_filters_old_events(self):
        """Eventos antigos (fora da janela) são filtrados."""
        bus = PipelineEventBus()
        ce = ContextEngine(bus=bus, window_seconds=1.0)
        # Evento antigo (timestamp baixo).
        old = _make_committed("texto muito antigo", timestamp=time.time() - 100)
        bus.publish(old)
        # Evento recente.
        bus.publish(_make_committed("texto recente"))
        ctx = ce.build(current_text="atual")
        assert "antigo" not in ctx.recent_text
        assert "recente" in ctx.recent_text

    def test_buffer_circular_limits_size(self):
        """Buffer circular limita número de committed words."""
        bus = PipelineEventBus()
        ce = ContextEngine(bus=bus, max_committed=3)
        for i in range(5):
            bus.publish(_make_committed(f"texto {i}"))
        with ce._lock:
            assert len(ce._committed_buffer) == 3
            # Os 3 mais recentes (texto 2, 3, 4).
            texts = [t for _, t in ce._committed_buffer]
            assert "texto 2" in texts
            assert "texto 4" in texts
            assert "texto 0" not in texts

    def test_last_reference_in_context(self):
        """build() inclui última referência detectada no contexto."""
        bus = PipelineEventBus()
        ce = ContextEngine(bus=bus)
        bus.publish(_make_ref_detected("João", 3, 16))
        ctx = ce.build(current_text="como vimos antes")
        assert ctx.last_book == "João"
        assert ctx.last_chapter == 3
        assert "João 3:16" in ctx.last_reference

    def test_fallback_to_history_fn_without_bus(self):
        """Sem bus, build() usa history_fn (compatibilidade)."""
        bus = PipelineEventBus()
        bus.publish(SpeechPartial(
            meta=_make_meta(), text="texto via history",
            language="pt", confidence=0.9, latency_ms=100,
            audio_duration_ms=2000, is_stable=False,
        ))
        ce = ContextEngine(history_fn=bus.history)
        ctx = ce.build(current_text="atual")
        assert "texto via history" in ctx.recent_text

    def test_multiple_committed_accumulate(self):
        """Múltiplos committed words: recent_text contém apenas o último
        full_committed_text (que já é acumulado — não há redundância)."""
        bus = PipelineEventBus()
        ce = ContextEngine(bus=bus)
        # Cada evento carrega full_committed_text (texto acumulado).
        bus.publish(_make_committed("primeira parte"))
        bus.publish(_make_committed("primeira parte segunda parte"))
        ctx = ce.build(current_text="atual")
        # recent_text deve conter apenas o último (mais completo).
        assert "segunda parte" in ctx.recent_text
        # Não deve duplicar "primeira parte".
        assert ctx.recent_text.count("primeira parte") == 1
