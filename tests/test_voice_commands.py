"""Testes de Voice Commands (Sprint 28 — Fase 8).

Valida:
- VersionCommandDetector detecta "verso anterior" em committed words → back.
- "volta" / "voltar" → back.
- "próximo verso" / "pula" → forward.
- "capítulo N" → goto_chapter.
- "versículo N" → goto_verse.
- Leitura normal não dispara comando (threshold 0.90).
- ReadingFollowService executa retrocesso/avanço via NavigationCommandDetected.
- NavigationCommandDetected publicado corretamente.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    NavigationCommandDetected,
    ReadingFollowAdvanced,
    ReadingFollowStarted,
    ReferenceDetected,
    SpeechCommittedWords,
)
from pipeline.metadata import EventMetadata
from presentation.reading_follow_service import ReadingFollowService
from presentation.version_command_detector import VersionCommandDetector


def _make_meta(correlation_id: str = "corr-1") -> EventMetadata:
    return EventMetadata.for_initial(
        session_id="test-session", origin="test", correlation_id=correlation_id)


def _make_committed(text: str, correlation_id: str = "corr-1") -> SpeechCommittedWords:
    return SpeechCommittedWords(
        meta=_make_meta(correlation_id),
        committed_text=text, full_committed_text=text,
        words=tuple(), language="pt",
        confidence=0.9, latency_ms=100, audio_duration_ms=6000,
    )


def _make_detected(
    book: str = "João", book_id: int = 43, chapter: int = 3,
    verse_start: int = 16, verse_end: int = 18,
) -> ReferenceDetected:
    return ReferenceDetected(
        meta=_make_meta(),
        book=book, book_id=book_id, chapter=chapter,
        verse_start=verse_start, verse_end=verse_end,
        confidence=0.95,
        raw_text="joão 3 16-18", normalized_text="João 3:16-18",
    )


@pytest.fixture
def setup():
    """Cria bus, VersionCommandDetector, ReadingFollowService com mocks."""
    bus = PipelineEventBus()

    # VersionCommandDetector.
    vcd = VersionCommandDetector(bus=bus, session_id="test")
    vcd.start()

    # ReadingFollowService.
    searcher = MagicMock()
    holyrics = MagicMock()

    verse_texts = {
        16: "Porque Deus amou o mundo de tal maneira que deu o seu Filho unigenito",
        17: "Para que todo aquele que nele crê não pereça mas tenha a vida eterna",
        18: "Quem crê nele não é condenado mas quem não crê já está condenado",
    }

    def search_side_effect(book, chapter, verse, *, version=None):
        r = MagicMock()
        r.text = verse_texts.get(verse, "")
        r.book = book
        r.book_id = 43
        r.chapter = chapter
        r.verse = verse
        r.reference = f"{book} {chapter}:{verse}"
        r.version = version or "ACF"
        return r

    searcher.search_by_reference.side_effect = search_side_effect

    rfs = ReadingFollowService(
        searcher=searcher, holyrics=holyrics, bus=bus,
        session_id="test", version="ACF",
        debounce_ms=100, min_words=5,
    )
    rfs.start()

    nav_commands: list[NavigationCommandDetected] = []
    advanced: list[ReadingFollowAdvanced] = []
    started: list[ReadingFollowStarted] = []
    bus.subscribe(NavigationCommandDetected, lambda e: nav_commands.append(e))
    bus.subscribe(ReadingFollowAdvanced, lambda e: advanced.append(e))
    bus.subscribe(ReadingFollowStarted, lambda e: started.append(e))

    return bus, vcd, rfs, searcher, holyrics, nav_commands, advanced, started, verse_texts


class TestVersionCommandDetectorNavigation:
    """Testes do VersionCommandDetector para comandos de navegação."""

    def test_detects_verso_anterior(self, setup):
        """'verso anterior' → NavigationCommandDetected(command=back)."""
        bus, vcd, _, _, _, nav, _, _, _ = setup
        bus.publish(_make_committed("verso anterior"))
        assert len(nav) == 1
        assert nav[0].command == "back"
        assert nav[0].confidence >= 0.90

    def test_detects_volta(self, setup):
        """'volta' → NavigationCommandDetected(command=back)."""
        bus, vcd, _, _, _, nav, _, _, _ = setup
        bus.publish(_make_committed("volta"))
        assert len(nav) == 1
        assert nav[0].command == "back"

    def test_detects_voltar(self, setup):
        """'voltar' → back."""
        bus, vcd, _, _, _, nav, _, _, _ = setup
        bus.publish(_make_committed("voltar"))
        assert len(nav) == 1
        assert nav[0].command == "back"

    def test_detects_proximo_verso(self, setup):
        """'próximo verso' → forward."""
        bus, vcd, _, _, _, nav, _, _, _ = setup
        bus.publish(_make_committed("próximo verso"))
        assert len(nav) == 1
        assert nav[0].command == "forward"

    def test_detects_pula(self, setup):
        """'pula' → forward."""
        bus, vcd, _, _, _, nav, _, _, _ = setup
        bus.publish(_make_committed("pula"))
        assert len(nav) == 1
        assert nav[0].command == "forward"

    def test_detects_pular(self, setup):
        """'pular' → forward."""
        bus, vcd, _, _, _, nav, _, _, _ = setup
        bus.publish(_make_committed("pular"))
        assert len(nav) == 1
        assert nav[0].command == "forward"

    def test_detects_capitulo_n(self, setup):
        """'capítulo 5' → goto_chapter(5)."""
        bus, vcd, _, _, _, nav, _, _, _ = setup
        bus.publish(_make_committed("capítulo 5"))
        assert len(nav) == 1
        assert nav[0].command == "goto_chapter"
        assert nav[0].target_value == 5

    def test_detects_versiculo_n(self, setup):
        """'versículo 17' → goto_verse(17)."""
        bus, vcd, _, _, _, nav, _, _, _ = setup
        bus.publish(_make_committed("versículo 17"))
        assert len(nav) == 1
        assert nav[0].command == "goto_verse"
        assert nav[0].target_value == 17

    def test_normal_reading_does_not_trigger(self, setup):
        """Leitura normal não dispara comando (threshold 0.90)."""
        bus, vcd, _, _, _, nav, _, _, _ = setup
        bus.publish(_make_committed(
            "porque Deus amou o mundo de tal maneira que deu o seu Filho"
        ))
        assert len(nav) == 0

    def test_empty_text_does_not_trigger(self, setup):
        """Texto vazio não dispara."""
        bus, vcd, _, _, _, nav, _, _, _ = setup
        bus.publish(_make_committed(""))
        assert len(nav) == 0


class TestReadingFollowNavigation:
    """Testes do ReadingFollowService com NavigationCommandDetected."""

    def test_back_retreats_verse(self, setup):
        """NavigationCommandDetected(back) retrocede versículo."""
        bus, vcd, rfs, _, holyrics, _, advanced, started, _ = setup
        # Ativar reading follow.
        bus.publish(_make_detected(verse_start=16, verse_end=18))
        assert rfs.get_state()["current_verse"] == 16
        # Avançar para 17 via committed words.
        bus.publish(_make_committed(
            "porque Deus amou o mundo de tal maneira que deu o seu Filho"
        ))
        time.sleep(0.3)
        assert rfs.get_state()["current_verse"] == 17
        # Comando "verso anterior" → retrocede para 16.
        bus.publish(_make_committed("verso anterior"))
        assert rfs.get_state()["current_verse"] == 16
        # Verificar que publicou ReadingFollowAdvanced com reason.
        back_events = [a for a in advanced if a.reason == "voice_command_back"]
        assert len(back_events) >= 1
        assert back_events[-1].previous_verse == 17
        assert back_events[-1].current_verse == 16

    def test_forward_advances_verse(self, setup):
        """NavigationCommandDetected(forward) avança versículo."""
        bus, vcd, rfs, _, _, _, advanced, started, _ = setup
        bus.publish(_make_detected(verse_start=16, verse_end=18))
        assert rfs.get_state()["current_verse"] == 16
        # Comando "pula" → avança para 17.
        bus.publish(_make_committed("pula"))
        assert rfs.get_state()["current_verse"] == 17
        forward_events = [a for a in advanced if a.reason == "voice_command_forward"]
        assert len(forward_events) >= 1
        assert forward_events[-1].previous_verse == 16
        assert forward_events[-1].current_verse == 17

    def test_back_at_start_does_nothing(self, setup):
        """Retrocesso no versículo inicial não faz nada."""
        bus, vcd, rfs, _, _, _, advanced, _, _ = setup
        bus.publish(_make_detected(verse_start=16, verse_end=18))
        assert rfs.get_state()["current_verse"] == 16
        # Comando "volta" → já no inicial, não faz nada.
        bus.publish(_make_committed("volta"))
        assert rfs.get_state()["current_verse"] == 16

    def test_forward_at_end_deactivates(self, setup):
        """Avanço no último versículo desativa (completed)."""
        bus, vcd, rfs, _, _, _, _, _, _ = setup
        bus.publish(_make_detected(verse_start=16, verse_end=17))
        # Avançar 16 → 17 via fuzzy.
        bus.publish(_make_committed(
            "porque Deus amou o mundo de tal maneira que deu o seu Filho"
        ))
        time.sleep(0.3)
        assert rfs.get_state()["current_verse"] == 17
        # Comando "pula" → no último, desativa.
        bus.publish(_make_committed("pula"))
        assert rfs.get_state()["active"] is False

    def test_goto_verse_jumps(self, setup):
        """NavigationCommandDetected(goto_verse) pula para versículo N."""
        bus, vcd, rfs, _, _, _, advanced, _, _ = setup
        bus.publish(_make_detected(verse_start=16, verse_end=18))
        assert rfs.get_state()["current_verse"] == 16
        # Comando "versículo 18" → pula para 18.
        bus.publish(_make_committed("versículo 18"))
        assert rfs.get_state()["current_verse"] == 18
        goto_events = [a for a in advanced if a.reason == "voice_command_goto"]
        assert len(goto_events) >= 1

    def test_navigation_ignored_when_inactive(self, setup):
        """Comando de navegação ignorado quando ReadingFollow inativo."""
        bus, vcd, rfs, _, _, _, advanced, _, _ = setup
        # Não ativar reading follow.
        bus.publish(_make_committed("verso anterior"))
        assert rfs.get_state()["active"] is False
        assert len(advanced) == 0
