"""Testes do IncrementalBiblicalParser com SpeechCommittedWords (Sprint 28).

Valida que o parser:
- Processa SpeechCommittedWords (não SpeechPartial/Updated).
- Detecta referências em committed words.
- Reseta em SpeechTranscribed.
- Não processa partials.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from parser.books import ParserBookTable, load_parser_books
from parser.normalizer import Normalizer
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    ReferenceCandidate,
    ReferenceDetected,
    SpeechCommittedWords,
    SpeechPartial,
    SpeechPartialUpdated,
    SpeechTranscribed,
)
from pipeline.incremental_parser import IncrementalBiblicalParser
from pipeline.metadata import EventMetadata


def _make_meta(correlation_id: str = "corr-1") -> EventMetadata:
    return EventMetadata.for_initial(
        session_id="test-session",
        origin="StreamingSTTService",
        correlation_id=correlation_id,
    )


def _make_committed(
    committed_text: str,
    full_committed_text: str = "",
    correlation_id: str = "corr-1",
) -> SpeechCommittedWords:
    return SpeechCommittedWords(
        meta=_make_meta(correlation_id),
        committed_text=committed_text,
        full_committed_text=full_committed_text or committed_text,
        words=tuple(),
        language="pt",
        confidence=0.9,
        latency_ms=100,
        audio_duration_ms=6000,
    )


def _make_partial(text: str, correlation_id: str = "corr-1") -> SpeechPartial:
    return SpeechPartial(
        meta=_make_meta(correlation_id),
        text=text,
        language="pt",
        confidence=0.9,
        latency_ms=100,
        audio_duration_ms=6000,
        is_stable=False,
    )


def _make_transcribed(text: str, correlation_id: str = "corr-1") -> SpeechTranscribed:
    return SpeechTranscribed(
        meta=_make_meta(correlation_id),
        text=text,
        language="pt",
        confidence=0.9,
        latency_ms=100,
        duration_ms=6000,
    )


@pytest.fixture
def parser():
    """Cria um IncrementalBiblicalParser com books real."""
    try:
        books = load_parser_books("config/books.json")
    except Exception:
        pytest.skip("config/books.json não disponível")
    bus = PipelineEventBus()
    p = IncrementalBiblicalParser(
        books=books,
        bus=bus,
        session_id="test-session",
    )
    p.start()
    return p, bus


class TestParserCommittedWords:
    """Testes do parser com SpeechCommittedWords."""

    def test_processes_committed_words(self, parser):
        """Parser processa SpeechCommittedWords e detecta referência."""
        p, bus = parser

        events = []
        bus.subscribe(ReferenceCandidate, lambda e: events.append(e))
        bus.subscribe(ReferenceDetected, lambda e: events.append(e))

        # Commit "joão" → deve detectar book.
        bus.publish(_make_committed("joão", "joão"))
        assert p._current_book is not None
        assert p._current_book.book.canonical.lower() == "joão"

    def test_detects_full_reference_in_committed(self, parser):
        """Referência completa é detectada em committed words incrementais."""
        p, bus = parser

        detected = []
        bus.subscribe(ReferenceDetected, lambda e: detected.append(e))

        # Commit incremental: "joão" → "capítulo três" → "versículo dezesseis"
        bus.publish(_make_committed("joão", "joão"))
        bus.publish(_make_committed("capítulo três", "joão capítulo três"))
        bus.publish(_make_committed("versículo dezesseis", "joão capítulo três versículo dezesseis"))

        assert len(detected) == 1
        event = detected[0]
        assert event.book.lower() == "joão"
        assert event.chapter == 3
        assert event.verse_start == 16

    def test_resets_on_speech_transcribed(self, parser):
        """SpeechTranscribed reseta o estado do parser."""
        p, bus = parser

        # Processar algumas committed words.
        bus.publish(_make_committed("joão", "joão"))
        assert p._current_book is not None

        # SpeechTranscribed deve resetar.
        bus.publish(_make_transcribed("joão capítulo três versículo dezesseis"))
        assert p._current_book is None
        assert p._expecting == "book"

    def test_ignores_speech_partial(self, parser):
        """Parser NÃO processa SpeechPartial (apenas committed words)."""
        p, bus = parser

        events = []
        bus.subscribe(ReferenceCandidate, lambda e: events.append(e))

        # Publicar SpeechPartial — não deve ser processado.
        bus.publish(_make_partial("joão capítulo três versículo dezesseis"))

        assert len(events) == 0
        assert p._current_book is None

    def test_new_correlation_id_resets(self, parser):
        """Novo correlation_id em committed words reseta o parser."""
        p, bus = parser

        # Fluxo 1: detectar joão.
        bus.publish(_make_committed("joão", "joão", correlation_id="corr-1"))
        assert p._current_book is not None

        # Fluxo 2: novo correlation_id deve resetar.
        bus.publish(_make_committed("salmos", "salmos", correlation_id="corr-2"))
        assert p._current_book is not None
        assert p._current_book.book.canonical.lower() == "salmos"
