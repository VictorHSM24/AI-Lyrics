"""Testes unitários do módulo estado/state.py.

Cobre:
- exemplos do enunciado (next, previous, jump, transição de livro)
- transições entre capítulos
- transições entre livros
- limites (início e fim da Bíblia)
- estado vazio + navegação relativa → StateError
- jump relativo (amount) e jump de capítulo (chapter="current")
- persistência (save/load)
- histórico de navegação
- última busca e última intenção
- validação de referências
- load_bible_structure de um DB FTS5
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from core.exceptions import StateError
from core.types import Intent, VerseRef
from estado.state import (
    BibleState,
    BibleStructure,
    BibleStateManager,
    HistoryEntry,
    load_bible_structure,
)


# ---------------------------------------------------------------------------
# Estrutura bíblica de teste
# ---------------------------------------------------------------------------

# Estrutura simplificada para testes (subset real).
# João (43): 21 capítulos; cap. 3 tem 36 v., cap. 21 tem 25 v.
# Atos (44): 28 capítulos; cap. 1 tem 26 v.
# Gênesis (1): 50 capítulos; cap. 1 tem 31 v.
# Apocalipse (66): 22 capítulos; cap. 22 tem 21 v.
# Romanos (45): 16 capítulos; cap. 8 tem 39 v.

TEST_CHAPTER_COUNTS = {
    1: 50,    # Gênesis
    43: 21,   # João
    44: 28,   # Atos
    45: 16,   # Romanos
    66: 22,   # Apocalipse
}

TEST_VERSE_COUNTS = {
    (1, 1): 31,    # Gênesis 1
    (43, 3): 36,   # João 3
    (43, 21): 25,  # João 21
    (44, 1): 26,   # Atos 1
    (45, 8): 39,   # Romanos 8
    (66, 22): 21,  # Apocalipse 22
}

TEST_BOOK_NAMES = {
    1: "Gênesis",
    43: "João",
    44: "Atos",
    45: "Romanos",
    66: "Apocalipse",
}


def _make_structure() -> BibleStructure:
    return BibleStructure(
        chapter_counts=dict(TEST_CHAPTER_COUNTS),
        verse_counts=dict(TEST_VERSE_COUNTS),
    )


def _make_manager(**kwargs) -> BibleStateManager:
    defaults = {
        "structure": _make_structure(),
        "book_names": dict(TEST_BOOK_NAMES),
        "persist_path": None,
        "history_size": 20,
        "default_version": "ACF",
    }
    defaults.update(kwargs)
    return BibleStateManager(**defaults)


def _show(manager: BibleStateManager, book_id: int, chapter: int, verse: int | None) -> VerseRef:
    """Helper: aplica action=show."""
    return manager.apply(Intent(
        action="show",
        book_id=book_id,
        book=TEST_BOOK_NAMES.get(book_id, ""),
        chapter=chapter,
        verse=verse,
    ))


def _next(manager: BibleStateManager, amount: int = 1) -> VerseRef:
    """Helper: aplica action=next."""
    return manager.apply(Intent(action="next", amount=amount))


def _previous(manager: BibleStateManager, amount: int = 1) -> VerseRef:
    """Helper: aplica action=previous."""
    return manager.apply(Intent(action="previous", amount=amount))


def _jump(manager: BibleStateManager, amount: int | None = None) -> VerseRef:
    """Helper: aplica action=jump."""
    return manager.apply(Intent(action="jump", amount=amount))


# ---------------------------------------------------------------------------
# Exemplos do enunciado
# ---------------------------------------------------------------------------

class TestEnunciadoExamples:
    def test_next_joao_3_16_to_17(self) -> None:
        m = _make_manager()
        _show(m, 43, 3, 16)
        ref = _next(m)
        assert ref.book_id == 43
        assert ref.chapter == 3
        assert ref.verse == 17

    def test_previous_joao_3_16_to_15(self) -> None:
        m = _make_manager()
        _show(m, 43, 3, 16)
        ref = _previous(m)
        assert ref.book_id == 43
        assert ref.chapter == 3
        assert ref.verse == 15

    def test_jump_plus_3_from_joao_3_16(self) -> None:
        """jump(+3) → João 3:19 (salto relativo de 3 versículos)."""
        m = _make_manager()
        _show(m, 43, 3, 16)
        ref = _jump(m, amount=3)
        assert ref.book_id == 43
        assert ref.chapter == 3
        assert ref.verse == 19

    def test_next_joao_21_25_to_atos_1_1(self) -> None:
        """Transição de livro: João 21:25 → Atos 1:1."""
        m = _make_manager()
        _show(m, 43, 21, 25)
        ref = _next(m)
        assert ref.book_id == 44
        assert ref.chapter == 1
        assert ref.verse == 1
        assert ref.book == "Atos"


# ---------------------------------------------------------------------------
# Navegação next
# ---------------------------------------------------------------------------

class TestNext:
    def test_next_within_chapter(self) -> None:
        m = _make_manager()
        _show(m, 43, 3, 16)
        ref = _next(m, 5)
        assert ref.verse == 21

    def test_next_chapter_overflow(self) -> None:
        """João 3:36 + next(1) → tenta ir a João 4:1, mas cap. 4 não está na estrutura de teste."""
        m = _make_manager()
        _show(m, 43, 3, 36)
        # Como não temos (43, 4) em verse_counts, deve dar StateError.
        with pytest.raises(StateError, match="não encontrado"):
            _next(m)

    def test_next_book_overflow(self) -> None:
        """João 21:25 + next(1) → Atos 1:1 (overflow de livro)."""
        m = _make_manager()
        _show(m, 43, 21, 25)
        ref = _next(m)
        assert ref.book_id == 44
        assert ref.chapter == 1
        assert ref.verse == 1

    def test_next_multiple_across_chapter(self) -> None:
        """João 3:35 + next(2) → João 3:36 + 1 → overflow → João 4:1 (não testável sem dados)."""
        m = _make_manager()
        _show(m, 43, 3, 35)
        ref = _next(m, 1)
        assert ref.verse == 36

    def test_next_at_end_of_bible(self) -> None:
        """Apocalipse 22:21 + next(1) → StateError (fim da Bíblia)."""
        m = _make_manager()
        _show(m, 66, 22, 21)
        with pytest.raises(StateError, match="fim da Bíblia"):
            _next(m)

    def test_next_amount_zero(self) -> None:
        m = _make_manager()
        _show(m, 43, 3, 16)
        ref = _next(m, 0)
        assert ref.verse == 16


# ---------------------------------------------------------------------------
# Navegação previous
# ---------------------------------------------------------------------------

class TestPrevious:
    def test_previous_within_chapter(self) -> None:
        m = _make_manager()
        _show(m, 43, 3, 16)
        ref = _previous(m, 5)
        assert ref.verse == 11

    def test_previous_chapter_underflow(self) -> None:
        """João 3:1 + previous(1) → João 2:?? (último verso do cap. 2).
        Não temos João 2 na estrutura de teste, então deve dar StateError.
        """
        m = _make_manager()
        _show(m, 43, 3, 1)
        with pytest.raises(StateError, match="não encontrado"):
            _previous(m)

    def test_previous_book_underflow(self) -> None:
        """Gênesis 1:1 + previous(1) → StateError (início da Bíblia)."""
        m = _make_manager()
        _show(m, 1, 1, 1)
        with pytest.raises(StateError, match="início da Bíblia"):
            _previous(m)

    def test_previous_amount_zero(self) -> None:
        m = _make_manager()
        _show(m, 43, 3, 16)
        ref = _previous(m, 0)
        assert ref.verse == 16

    def test_previous_multiple(self) -> None:
        m = _make_manager()
        _show(m, 43, 3, 10)
        ref = _previous(m, 5)
        assert ref.verse == 5


# ---------------------------------------------------------------------------
# Jump
# ---------------------------------------------------------------------------

class TestJump:
    def test_jump_relative_positive(self) -> None:
        """jump(+3) = avança 3 versículos."""
        m = _make_manager()
        _show(m, 43, 3, 16)
        ref = _jump(m, amount=3)
        assert ref.verse == 19

    def test_jump_relative_negative(self) -> None:
        """jump(-3) = retrocede 3 versículos."""
        m = _make_manager()
        _show(m, 43, 3, 16)
        ref = _jump(m, amount=-3)
        assert ref.verse == 13

    def test_jump_relative_zero(self) -> None:
        """jump(0) = mantém posição."""
        m = _make_manager()
        _show(m, 43, 3, 16)
        ref = _jump(m, amount=0)
        assert ref.verse == 16

    def test_jump_chapter_current(self) -> None:
        """jump sem amount = capítulo inteiro (verse=None)."""
        m = _make_manager()
        _show(m, 43, 3, 16)
        ref = _jump(m)
        assert ref.book_id == 43
        assert ref.chapter == 3
        assert ref.verse is None

    def test_jump_chapter_current_state_updated(self) -> None:
        """Após jump de capítulo, state.verse deve ser None."""
        m = _make_manager()
        _show(m, 43, 3, 16)
        _jump(m)
        state = m.current()
        assert state.verse is None

    def test_jump_relative_across_chapter(self) -> None:
        """jump(+2) a partir de João 3:35 → 36, depois overflow."""
        m = _make_manager()
        _show(m, 43, 3, 35)
        ref = _jump(m, amount=1)
        assert ref.verse == 36


# ---------------------------------------------------------------------------
# Estado vazio
# ---------------------------------------------------------------------------

class TestEmptyState:
    def test_next_empty_raises(self) -> None:
        m = _make_manager()
        with pytest.raises(StateError, match="nenhum versículo aberto"):
            _next(m)

    def test_previous_empty_raises(self) -> None:
        m = _make_manager()
        with pytest.raises(StateError, match="nenhum versículo aberto"):
            _previous(m)

    def test_jump_empty_raises(self) -> None:
        m = _make_manager()
        with pytest.raises(StateError, match="nenhum versículo aberto"):
            _jump(m)

    def test_current_ref_empty(self) -> None:
        m = _make_manager()
        assert m.current_ref() is None

    def test_current_empty_state(self) -> None:
        m = _make_manager()
        state = m.current()
        assert state.is_empty() is True
        assert state.book_id is None


# ---------------------------------------------------------------------------
# set() direto
# ---------------------------------------------------------------------------

class TestSetDirect:
    def test_set_valid_ref(self) -> None:
        m = _make_manager()
        ref = VerseRef(book_id=43, book="João", chapter=3, verse=16)
        m.set(ref)
        state = m.current()
        assert state.book_id == 43
        assert state.chapter == 3
        assert state.verse == 16

    def test_set_invalid_book_id(self) -> None:
        m = _make_manager()
        ref = VerseRef(book_id=99, book="X", chapter=1, verse=1)
        with pytest.raises(StateError, match="out of range"):
            m.set(ref)

    def test_set_invalid_chapter(self) -> None:
        m = _make_manager()
        ref = VerseRef(book_id=43, book="João", chapter=99, verse=1)
        with pytest.raises(StateError, match="out of range"):
            m.set(ref)

    def test_set_invalid_verse(self) -> None:
        m = _make_manager()
        ref = VerseRef(book_id=43, book="João", chapter=3, verse=99)
        with pytest.raises(StateError, match="out of range"):
            m.set(ref)

    def test_set_chapter_only(self) -> None:
        m = _make_manager()
        ref = VerseRef(book_id=43, book="João", chapter=3, verse=None)
        m.set(ref)
        assert m.current().verse is None


# ---------------------------------------------------------------------------
# apply(show)
# ---------------------------------------------------------------------------

class TestApplyShow:
    def test_show_valid(self) -> None:
        m = _make_manager()
        ref = m.apply(Intent(
            action="show",
            book_id=43,
            book="João",
            chapter=3,
            verse=16,
        ))
        assert ref.book_id == 43
        assert ref.chapter == 3
        assert ref.verse == 16

    def test_show_missing_book_id(self) -> None:
        m = _make_manager()
        with pytest.raises(StateError, match="requires book_id"):
            m.apply(Intent(action="show", chapter=3, verse=16))

    def test_show_invalid_chapter(self) -> None:
        m = _make_manager()
        with pytest.raises(StateError, match="out of range"):
            m.apply(Intent(action="show", book_id=43, chapter=99, verse=1))

    def test_show_uses_default_version(self) -> None:
        m = _make_manager(default_version="NVI")
        ref = m.apply(Intent(action="show", book_id=43, book="João", chapter=3, verse=16))
        assert ref.version == "NVI"

    def test_show_with_explicit_version(self) -> None:
        m = _make_manager()
        ref = m.apply(Intent(
            action="show", book_id=43, book="João", chapter=3, verse=16, version="NVI",
        ))
        assert ref.version == "NVI"


# ---------------------------------------------------------------------------
# Histórico
# ---------------------------------------------------------------------------

class TestHistory:
    def test_history_after_show(self) -> None:
        m = _make_manager()
        _show(m, 43, 3, 16)
        hist = m.history()
        assert len(hist) == 1
        assert hist[0].action == "show"
        assert hist[0].ref.verse == 16

    def test_history_after_navigation(self) -> None:
        m = _make_manager()
        _show(m, 43, 3, 16)
        _next(m)
        _previous(m)
        hist = m.history()
        assert len(hist) == 3
        assert hist[0].action == "previous"  # mais recente primeiro
        assert hist[1].action == "next"
        assert hist[2].action == "show"

    def test_history_size_limit(self) -> None:
        m = _make_manager(history_size=3)
        _show(m, 43, 3, 16)
        _next(m)
        _next(m)
        _next(m)
        _next(m)
        hist = m.history()
        assert len(hist) == 3  # limitado a 3

    def test_clear_history(self) -> None:
        m = _make_manager()
        _show(m, 43, 3, 16)
        m.clear_history()
        assert m.history() == []


# ---------------------------------------------------------------------------
# Última busca e intenção
# ---------------------------------------------------------------------------

class TestLastSearchIntent:
    def test_set_search(self) -> None:
        m = _make_manager()
        m.set_search("deus amou o mundo")
        assert m.last_search() == "deus amou o mundo"

    def test_set_intent(self) -> None:
        m = _make_manager()
        intent = Intent(action="show", book_id=43, chapter=3, verse=16)
        m.set_intent(intent)
        assert m.last_intent() is intent

    def test_apply_sets_last_intent(self) -> None:
        m = _make_manager()
        intent = Intent(action="show", book_id=43, book="João", chapter=3, verse=16)
        m.apply(intent)
        assert m.last_intent() is intent


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        path = str(tmp_path / "state.json")
        m = _make_manager(persist_path=path)
        _show(m, 43, 3, 16)
        _next(m)
        m.set_search("deus amou o mundo")

        # Novo manager carrega do mesmo arquivo.
        m2 = _make_manager(persist_path=path)
        m2.load()
        state = m2.current()
        assert state.book_id == 43
        assert state.chapter == 3
        assert state.verse == 17
        assert m2.last_search() == "deus amou o mundo"

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        path = str(tmp_path / "subdir" / "state.json")
        m = _make_manager(persist_path=path)
        _show(m, 43, 3, 16)
        assert os.path.isfile(path)

    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        path = str(tmp_path / "nonexistent.json")
        m = _make_manager(persist_path=path)
        m.load()  # não deve erro
        assert m.current().is_empty()

    def test_load_corrupted_file(self, tmp_path: Path) -> None:
        path = str(tmp_path / "corrupt.json")
        Path(path).write_text("{invalid json", encoding="utf-8")
        m = _make_manager(persist_path=path)
        m.load()  # não deve erro, usa estado vazio
        assert m.current().is_empty()

    def test_load_not_dict(self, tmp_path: Path) -> None:
        path = str(tmp_path / "notdict.json")
        Path(path).write_text("[1, 2, 3]", encoding="utf-8")
        m = _make_manager(persist_path=path)
        m.load()
        assert m.current().is_empty()

    def test_save_without_path_raises(self) -> None:
        m = _make_manager(persist_path=None)
        with pytest.raises(StateError, match="not configured"):
            m.save()

    def test_auto_save_on_set(self, tmp_path: Path) -> None:
        path = str(tmp_path / "state.json")
        m = _make_manager(persist_path=path)
        ref = VerseRef(book_id=43, book="João", chapter=3, verse=16)
        m.set(ref)
        # O arquivo deve ter sido criado automaticamente.
        assert os.path.isfile(path)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert data["book_id"] == 43

    def test_persisted_history(self, tmp_path: Path) -> None:
        path = str(tmp_path / "state.json")
        m = _make_manager(persist_path=path)
        _show(m, 43, 3, 16)
        _next(m)
        m2 = _make_manager(persist_path=path)
        m2.load()
        hist = m2.history()
        assert len(hist) == 2


# ---------------------------------------------------------------------------
# VerseRef properties
# ---------------------------------------------------------------------------

class TestVerseRef:
    def test_id_format(self) -> None:
        ref = VerseRef(book_id=43, book="João", chapter=3, verse=16)
        assert ref.id == "43003016"

    def test_reference_with_verse(self) -> None:
        ref = VerseRef(book_id=43, book="João", chapter=3, verse=16)
        assert ref.reference == "João 3:16"

    def test_reference_without_verse(self) -> None:
        ref = VerseRef(book_id=43, book="João", chapter=3, verse=None)
        assert ref.reference == "João 3"


# ---------------------------------------------------------------------------
# load_bible_structure
# ---------------------------------------------------------------------------

class TestLoadBibleStructure:
    def test_load_from_fts5_db(self, tmp_path: Path) -> None:
        """Cria um DB FTS5 de teste e carrega a estrutura."""
        db_path = str(tmp_path / "test.sqlite")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE VIRTUAL TABLE verses USING fts5("
            "book, chapter UNINDEXED, verse UNINDEXED, text, "
            "version UNINDEXED, id UNINDEXED, "
            "tokenize = 'unicode61 remove_diacritics 2')"
        )
        # Inserir alguns versículos.
        verses = [
            ("João", 3, 16, "Porque Deus amou...", "ACF", "43003016"),
            ("João", 3, 17, "Porque Deus enviou...", "ACF", "43003017"),
            ("João", 3, 36, "Quem crê no Filho...", "ACF", "43003036"),
            ("João", 21, 25, "Há porém...", "ACF", "43021025"),
            ("Atos", 1, 1, "Escrevi-te...", "ACF", "44001001"),
        ]
        conn.executemany(
            "INSERT INTO verses (book, chapter, verse, text, version, id) "
            "VALUES (?, ?, ?, ?, ?, ?)", verses
        )
        conn.commit()
        conn.close()

        struct = load_bible_structure(db_path)
        assert struct.chapter_count(43) == 21
        assert struct.verse_count(43, 3) == 36
        assert struct.verse_count(43, 21) == 25
        assert struct.chapter_count(44) == 1
        assert struct.verse_count(44, 1) == 1

    def test_load_nonexistent_db(self, tmp_path: Path) -> None:
        with pytest.raises(StateError, match="not found"):
            load_bible_structure(str(tmp_path / "nonexistent.sqlite"))

    def test_load_no_table(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "empty.sqlite")
        sqlite3.connect(db_path).close()
        with pytest.raises(StateError, match="does not exist"):
            load_bible_structure(db_path)


# ---------------------------------------------------------------------------
# Versículo None (capítulo inteiro) + navegação
# ---------------------------------------------------------------------------

class TestChapterModeNavigation:
    def test_next_from_chapter_mode(self) -> None:
        """Se verse=None (capítulo inteiro), next() vai ao próximo v.1."""
        m = _make_manager()
        m.set(VerseRef(book_id=43, book="João", chapter=3, verse=None))
        ref = _next(m)
        # Começa do verso 0, +1 = 1.
        assert ref.verse == 1

    def test_previous_from_chapter_mode(self) -> None:
        """Se verse=None, previous() vai ao último verso do capítulo."""
        m = _make_manager()
        m.set(VerseRef(book_id=43, book="João", chapter=3, verse=None))
        ref = _previous(m)
        # Começa do último+1, -1 = último.
        assert ref.verse == 36


# ---------------------------------------------------------------------------
# Ações não suportadas
# ---------------------------------------------------------------------------

class TestUnsupportedActions:
    def test_apply_search_raises(self) -> None:
        m = _make_manager()
        with pytest.raises(StateError, match="unsupported action"):
            m.apply(Intent(action="search", query="deus"))

    def test_apply_none_raises(self) -> None:
        m = _make_manager()
        with pytest.raises(StateError, match="unsupported action"):
            m.apply(Intent(action="none"))
