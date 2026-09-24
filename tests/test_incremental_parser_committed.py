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


class TestSpeechFalsePositives:
    """Sprint 29 — prevenção de falsos positivos em fala.

    Incidente real: o pregador leu Atos 1:8 ("como em toda a Judéia e
    Samaria"). O Whisper commitou "judé" → casou com a alias inglesa
    "jude" (Judas). ~40s depois, "para dar um testemunho" — o artigo
    "um" virava dígito 1 → Judas 1 → apresentação antecipada de
    Judas 1:1 no telão.
    """

    def test_english_alias_jude_ignored(self, parser):
        """"jude"/"judé" (Judéia) não resolve como livro Judas na fala."""
        p, bus = parser
        events = []
        bus.subscribe(ReferenceCandidate, lambda e: events.append(e))

        bus.publish(_make_committed(
            "tanto em jerusalém como em toda a judé",
            "tanto em jerusalém como em toda a judé",
        ))
        assert p._current_book is None
        assert len(events) == 0

    def test_article_um_not_chapter(self, parser):
        """Artigo "um" não completa capítulo de livro pendente."""
        p, bus = parser

        bus.publish(_make_committed("abre em atos", "abre em atos"))
        assert p._current_book is not None

        bus.publish(_make_committed(
            "e foi um testemunho para todos",
            "abre em atos e foi um testemunho para todos",
        ))
        assert p._current_chapter is None

    def test_distant_number_expires_book(self, parser):
        """Número distante do livro (>10 palavras) expira o pendente."""
        p, bus = parser

        bus.publish(_make_committed("li o livro de jonas", "li o livro de jonas"))
        assert p._current_book is not None

        bus.publish(_make_committed(
            "e depois de muito tempo falando sobre outras coisas capitulo tres",
            "li o livro de jonas e depois de muito tempo falando sobre outras coisas capitulo tres",
        ))
        assert p._current_book is None
        assert p._expecting == "book"

    def test_unmarked_number_must_be_adjacent(self, parser):
        """Número sem marcador só completa se adjacente ao livro (≤3 palavras)."""
        p, bus = parser

        bus.publish(_make_committed(
            "o traidor judas foi um dos doze apostolos e depois morreu",
            "o traidor judas foi um dos doze apostolos e depois morreu",
        ))
        # "doze"→12 está a 4+ palavras de "judas" — narrativa, não citação.
        assert p._current_chapter is None

    def test_single_chapter_book_verse_unmarked(self, parser):
        """"Judas 9" = versículo 9 (capítulo 1 implícito), não capítulo 9."""
        p, bus = parser
        detected = []
        bus.subscribe(ReferenceDetected, lambda e: detected.append(e))

        bus.publish(_make_committed("abre em judas nove", "abre em judas nove"))
        assert len(detected) == 1
        assert detected[0].book == "Judas"
        assert detected[0].chapter == 1
        assert detected[0].verse_start == 9

    def test_single_chapter_book_verse_marked(self, parser):
        """"Judas versículo 9" = capítulo 1 implícito + versículo 9."""
        p, bus = parser
        detected = []
        bus.subscribe(ReferenceDetected, lambda e: detected.append(e))

        bus.publish(_make_committed(
            "epistola de judas versiculo nove",
            "epistola de judas versiculo nove",
        ))
        assert len(detected) == 1
        assert detected[0].book == "Judas"
        assert detected[0].chapter == 1
        assert detected[0].verse_start == 9

    def test_marked_chapter_um_still_works(self, parser):
        """"capítulo um"/"versículo primeiro" continuam válidos (marcador)."""
        p, bus = parser
        detected = []
        bus.subscribe(ReferenceDetected, lambda e: detected.append(e))

        bus.publish(_make_committed(
            "joão capítulo um versículo primeiro",
            "joão capítulo um versículo primeiro",
        ))
        assert len(detected) == 1
        assert detected[0].book.lower() == "joão"
        assert detected[0].chapter == 1
        assert detected[0].verse_start == 1

    def test_verb_amo_not_amos(self, parser):
        """Sprint 30 — "eu amo você" (verbo amar) não resolve como Amós."""
        p, bus = parser
        candidates = []
        bus.subscribe(ReferenceCandidate, lambda e: candidates.append(e))

        bus.publish(_make_committed(
            "eu abraço meu irmão, eu digo, eu amo você",
            "eu abraço meu irmão, eu digo, eu amo você",
        ))
        assert all(c.book != "Amós" for c in candidates)
        assert p._current_book is None or p._current_book.canonical != "Amós"

    def test_revelacao_not_apocalipse(self, parser):
        """Sprint 30 — "uma revelação diferente" não resolve Apocalipse."""
        p, bus = parser
        candidates = []
        bus.subscribe(ReferenceCandidate, lambda e: candidates.append(e))

        bus.publish(_make_committed(
            "achamos que toda vez que chegar aqui será uma revelação diferente",
            "achamos que toda vez que chegar aqui será uma revelação diferente",
        ))
        assert all(c.book != "Apocalipse" for c in candidates)

    def test_mal_not_malaquias(self, parser):
        """Sprint 30 — "o mal" / "tão mal" não resolve como Malaquias."""
        p, bus = parser
        candidates = []
        bus.subscribe(ReferenceCandidate, lambda e: candidates.append(e))

        bus.publish(_make_committed(
            "não tem como eu dizer que estou cheio de cristo mas com mal",
            "não tem como eu dizer que estou cheio de cristo mas com mal",
        ))
        assert all(c.book != "Malaquias" for c in candidates)

    def test_canonical_amos_still_works(self, parser):
        """O canônico "Amós 9:13" continua detectando após o blocklist."""
        p, bus = parser
        detected = []
        bus.subscribe(ReferenceDetected, lambda e: detected.append(e))

        bus.publish(_make_committed(
            "vamos ler amós nove treze",
            "vamos ler amós nove treze",
        ))
        assert len(detected) == 1
        assert detected[0].book == "Amós"
        assert detected[0].chapter == 9
        assert detected[0].verse_start == 13
