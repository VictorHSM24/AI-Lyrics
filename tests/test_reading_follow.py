"""Testes para o Reading Follow Mode (Sprint 23.2).

Cobre:
- Parser de intervalo de versículos (determinístico e incremental)
- ReadingFollowService: ativação, avanço, parada, mudança de versão
- VersionCommandDetector: detecção de comandos de voz
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from core.types import Intent
from estado.state import BibleState
from parser.books import ParserBookTable, load_parser_books
from parser.normalizer import Normalizer
from parser.parser import Parser


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def books() -> ParserBookTable:
    return load_parser_books("config/books.json")


@pytest.fixture(scope="module")
def parser(books: ParserBookTable) -> Parser:
    return Parser(books=books)


@pytest.fixture(scope="module")
def normalizer() -> Normalizer:
    return Normalizer()


# ---------------------------------------------------------------------------
# Parser — intervalo de versículos
# ---------------------------------------------------------------------------

class TestVerseRangeParsing:
    """Testa detecção de intervalo (verse_end) no parser determinístico."""

    def test_range_with_ao(self, parser: Parser) -> None:
        r = parser.parse("mateus 7 do 1 ao 3")
        assert r.action == "show"
        assert r.verse == 1
        assert r.verse_end == 3

    def test_range_with_ate(self, parser: Parser) -> None:
        r = parser.parse("mateus 7 do 1 ate 5")
        assert r.action == "show"
        assert r.verse == 1
        assert r.verse_end == 5

    def test_range_with_a(self, parser: Parser) -> None:
        r = parser.parse("joao 3 do 16 a 18")
        assert r.action == "show"
        assert r.verse == 16
        assert r.verse_end == 18

    def test_single_verse_no_range(self, parser: Parser) -> None:
        r = parser.parse("mateus 7 1")
        assert r.action == "show"
        assert r.verse == 1
        assert r.verse_end is None

    def test_range_verse_end_greater_than_start(self, parser: Parser) -> None:
        r = parser.parse("genesis 1 do 1 ao 10")
        assert r.action == "show"
        assert r.verse_end > r.verse

    def test_range_normalizer_integration(self, parser: Parser, normalizer: Normalizer) -> None:
        text = normalizer.normalize("mateus sete do um ao três")
        r = parser.parse(text)
        assert r.action == "show"
        assert r.verse == 1
        assert r.verse_end == 3


# ---------------------------------------------------------------------------
# ReadingFollowService
# ---------------------------------------------------------------------------

class TestReadingFollowService:
    """Testa o ReadingFollowService com mocks."""

    @pytest.fixture
    def mock_searcher(self):
        mock = MagicMock()
        mock.search_by_reference.return_value = MagicMock(
            book="Mateus",
            book_id=40,
            chapter=7,
            verse=1,
            text="Não julgueis, para que não sejais julgados.",
            version="ACF",
        )
        return mock

    @pytest.fixture
    def mock_holyrics(self):
        mock = MagicMock()
        mock.show_verse.return_value = MagicMock(ok=True)
        mock.list_versions.return_value = ["ACF", "NVI", "ARA"]
        return mock

    @pytest.fixture
    def mock_bus(self):
        bus = MagicMock()
        bus.subscribe = MagicMock()
        bus.publish = MagicMock()
        return bus

    @pytest.fixture
    def service(self, mock_searcher, mock_holyrics, mock_bus):
        from presentation.reading_follow_service import ReadingFollowService
        svc = ReadingFollowService(
            searcher=mock_searcher,
            holyrics=mock_holyrics,
            bus=mock_bus,
            session_id="test-session",
            version="ACF",
            fuzzy_threshold=0.70,
        )
        yield svc
        svc.stop()

    def test_activate_manual(self, service, mock_bus):
        service.activate(
            book_id=40,
            book_name="Mateus",
            chapter=7,
            verse_start=1,
            verse_end=3,
        )
        assert service._state.active
        assert service._state.book == "Mateus"
        assert service._state.chapter == 7
        assert service._state.verse_start == 1
        assert service._state.verse_end == 3
        assert service._state.current_verse == 1
        mock_bus.publish.assert_called()

    def test_deactivate(self, service, mock_bus):
        service.activate(
            book_id=40,
            book_name="Mateus",
            chapter=7,
            verse_start=1,
            verse_end=3,
        )
        service.deactivate()
        assert not service._state.active

    def test_advance(self, service, mock_holyrics):
        service.activate(
            book_id=40,
            book_name="Mateus",
            chapter=7,
            verse_start=1,
            verse_end=3,
        )
        initial = service._state.current_verse
        service.advance()
        assert service._state.current_verse == initial + 1

    def test_advance_at_end_deactivates(self, service):
        service.activate(
            book_id=40,
            book_name="Mateus",
            chapter=7,
            verse_start=1,
            verse_end=2,
        )
        service.advance()  # 1 -> 2
        assert service._state.active
        service.advance()  # 2 -> end
        assert not service._state.active

    def test_set_version(self, service, mock_searcher):
        service.activate(
            book_id=40,
            book_name="Mateus",
            chapter=7,
            verse_start=1,
            verse_end=3,
        )
        result = service.set_version("NVI")
        assert result
        assert service._state.version == "NVI"

    def test_get_state_inactive(self, service):
        state = service.get_state()
        assert not state["active"]

    def test_get_state_active(self, service):
        service.activate(
            book_id=40,
            book_name="Mateus",
            chapter=7,
            verse_start=1,
            verse_end=3,
        )
        state = service.get_state()
        assert state["active"]
        assert state["book"] == "Mateus"
        assert state["total_verses"] == 3


# ---------------------------------------------------------------------------
# VersionCommandDetector
# ---------------------------------------------------------------------------

class TestVersionCommandDetector:
    """Testa o VersionCommandDetector."""

    @pytest.fixture
    def mock_holyrics(self):
        mock = MagicMock()
        mock.list_versions.return_value = ["ACF", "NVI", "ARA"]
        return mock

    @pytest.fixture
    def mock_bus(self):
        bus = MagicMock()
        bus.subscribe = MagicMock()
        bus.publish = MagicMock()
        return bus

    @pytest.fixture
    def detector(self, mock_holyrics, mock_bus):
        from presentation.version_command_detector import VersionCommandDetector
        det = VersionCommandDetector(
            bus=mock_bus,
            session_id="test-session",
            holyrics=mock_holyrics,
            auto_enabled=True,
            current_version="ACF",
        )
        yield det
        det.stop()

    def test_detect_version_command_nvi(self, detector, mock_bus):
        from pipeline.events import SpeechTranscribed, VersionChanged
        from pipeline.metadata import EventMetadata

        meta = EventMetadata.for_session_event(
            session_id="test", origin="test",
        )
        event = SpeechTranscribed(
            meta=meta,
            text="muda para versão NVI",
            confidence=0.9,
        )
        detector._on_speech_transcribed(event)
        published = [c for c in mock_bus.publish.call_args_list
                     if c.args and isinstance(c.args[0], VersionChanged)]
        assert len(published) >= 1

    def test_detect_version_command_acf(self, detector, mock_bus):
        from pipeline.events import SpeechTranscribed, VersionChanged
        from pipeline.metadata import EventMetadata

        meta = EventMetadata.for_session_event(
            session_id="test", origin="test",
        )
        event = SpeechTranscribed(
            meta=meta,
            text="trocar para ARA",
            confidence=0.9,
        )
        detector._on_speech_transcribed(event)
        published = [c for c in mock_bus.publish.call_args_list
                     if c.args and isinstance(c.args[0], VersionChanged)]
        assert len(published) >= 1

    def test_no_version_command_in_normal_speech(self, detector, mock_bus):
        from pipeline.events import SpeechTranscribed
        from pipeline.metadata import EventMetadata

        meta = EventMetadata.for_session_event(
            session_id="test", origin="test",
        )
        event = SpeechTranscribed(
            meta=meta,
            text="e então Jesus disse aos discípulos",
            confidence=0.9,
        )
        detector._on_speech_transcribed(event)
        from pipeline.events import VersionChanged
        published = [c for c in mock_bus.publish.call_args_list
                     if c.args and isinstance(c.args[0], VersionChanged)]
        assert len(published) == 0

    def test_auto_disabled_blocks_detection(self, detector, mock_bus):
        from pipeline.events import SpeechTranscribed, VersionChanged
        from pipeline.metadata import EventMetadata

        detector.set_auto_enabled(False)

        meta = EventMetadata.for_session_event(
            session_id="test", origin="test",
        )
        event = SpeechTranscribed(
            meta=meta,
            text="muda para versão NVI",
            confidence=0.9,
        )
        detector._on_speech_transcribed(event)
        published = [c for c in mock_bus.publish.call_args_list
                     if c.args and isinstance(c.args[0], VersionChanged)]
        assert len(published) == 0

    def test_set_current_version(self, detector):
        detector.set_current_version("NVI")
        assert detector._current_version == "NVI"

    def test_set_auto_enabled(self, detector):
        detector.set_auto_enabled(False)
        assert not detector._auto_enabled
        detector.set_auto_enabled(True)
        assert detector._auto_enabled
