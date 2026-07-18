"""Testes unitários do reconhecedor de livros bíblicos (parser/books.py).

Cobre:
- exemplos do enunciado (joao, jo, 1 corintios, primeira corintios, etc.)
- longest-match (1 João vs João)
- ordinais e romanos (via Normalizer)
- ambiguidades e prioridade (jo, ez, hb)
- confiança (1.0 única, 0.5 ambígua)
- abreviações
- variações PT-BR
- casos extremos (vazio, não-encontrado, case-insensitive)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parser.books import BookResolveResult, ParserBookTable, load_parser_books
from parser.normalizer import Normalizer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def table() -> ParserBookTable:
    """Carrega a tabela real do config/books.json."""
    return load_parser_books("config/books.json")


# ---------------------------------------------------------------------------
# Exemplos do enunciado
# ---------------------------------------------------------------------------

class TestEnunciadoExamples:
    def test_joao(self, table: ParserBookTable) -> None:
        r = table.resolve("joao")
        assert r is not None
        assert r.book.canonical == "João"
        assert r.book.id == 43

    def test_jo(self, table: ParserBookTable) -> None:
        r = table.resolve("jo")
        assert r is not None
        assert r.book.canonical == "João"
        assert r.book.id == 43

    def test_1_corintios(self, table: ParserBookTable) -> None:
        r = table.resolve("1 corintios")
        assert r is not None
        assert r.book.canonical == "1 Coríntios"
        assert r.book.id == 46

    def test_primeira_corintios(self, table: ParserBookTable) -> None:
        r = table.resolve("primeira corintios")
        assert r is not None
        assert r.book.canonical == "1 Coríntios"
        assert r.book.id == 46

    def test_i_corintios(self, table: ParserBookTable) -> None:
        r = table.resolve("i corintios")
        assert r is not None
        assert r.book.canonical == "1 Coríntios"
        assert r.book.id == 46

    def test_ii_corintios(self, table: ParserBookTable) -> None:
        r = table.resolve("ii corintios")
        assert r is not None
        assert r.book.canonical == "2 Coríntios"
        assert r.book.id == 47

    def test_primeira_carta_aos_corintios(self, table: ParserBookTable) -> None:
        r = table.resolve("primeira carta aos corintios")
        assert r is not None
        assert r.book.canonical == "1 Coríntios"
        assert r.book.id == 46

    def test_canticos(self, table: ParserBookTable) -> None:
        r = table.resolve("canticos")
        assert r is not None
        assert r.book.canonical == "Cânticos"
        assert r.book.id == 22

    def test_apocalipse(self, table: ParserBookTable) -> None:
        r = table.resolve("apocalipse")
        assert r is not None
        assert r.book.canonical == "Apocalipse"
        assert r.book.id == 66


# ---------------------------------------------------------------------------
# Longest-match
# ---------------------------------------------------------------------------

class TestLongestMatch:
    def test_1_joao_not_joao(self, table: ParserBookTable) -> None:
        """"1 joao" deve resolver para 1 João (id=62), não João (id=43)."""
        r = table.resolve("1 joao")
        assert r is not None
        assert r.book.id == 62
        assert r.book.canonical == "1 João"

    def test_primeiro_joao_not_joao(self, table: ParserBookTable) -> None:
        """"primeiro joao" deve resolver para 1 João, não João."""
        r = table.resolve("primeiro joao")
        assert r is not None
        assert r.book.id == 62

    def test_segunda_joao(self, table: ParserBookTable) -> None:
        r = table.resolve("segunda joao")
        assert r is not None
        assert r.book.id == 63
        assert r.book.canonical == "2 João"

    def test_terceiro_joao(self, table: ParserBookTable) -> None:
        r = table.resolve("terceiro joao")
        assert r is not None
        assert r.book.id == 64
        assert r.book.canonical == "3 João"

    def test_joao_in_phrase(self, table: ParserBookTable) -> None:
        """"joao capitulo 3 versiculo 16" deve encontrar João (não 1 João)."""
        r = table.resolve("joao capitulo 3 versiculo 16")
        assert r is not None
        assert r.book.id == 43

    def test_1_joao_in_phrase(self, table: ParserBookTable) -> None:
        """"1 joao capitulo 4" deve encontrar 1 João."""
        r = table.resolve("1 joao capitulo 4")
        assert r is not None
        assert r.book.id == 62


# ---------------------------------------------------------------------------
# Ambiguidades e prioridade
# ---------------------------------------------------------------------------

class TestAmbiguityPriority:
    def test_jo_resolves_to_joao(self, table: ParserBookTable) -> None:
        """'jo' é ambíguo (Josué, Jó, João); prioridade → João (priority=100)."""
        r = table.resolve("jo")
        assert r is not None
        assert r.book.id == 43
        assert r.ambiguous is True
        assert r.confidence == 0.5

    def test_hb_resolves_to_hebreus(self, table: ParserBookTable) -> None:
        """'hb' é ambíguo (Habacuque, Hebreus); prioridade → Hebreus (priority=80)."""
        r = table.resolve("hb")
        assert r is not None
        assert r.book.id == 58
        assert r.ambiguous is True
        assert r.confidence == 0.5

    def test_ez_ambiguous(self, table: ParserBookTable) -> None:
        """'ez' é ambíguo (Esdras, Ezequiel); mesma prioridade → menor ID (Esdras)."""
        r = table.resolve("ez")
        assert r is not None
        assert r.ambiguous is True
        assert r.confidence == 0.5
        # Empate de prioridade (50=50) → menor ID vence (Esdras=15).
        assert r.book.id == 15

    def test_ambiguous_aliases_set(self, table: ParserBookTable) -> None:
        """Verifica que exatamente 3 aliases são ambíguas."""
        amb = table.ambiguous_aliases()
        assert "jo" in amb
        assert "hb" in amb
        assert "ez" in amb
        assert len(amb) == 3


# ---------------------------------------------------------------------------
# Confiança
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_unique_alias_confidence_1(self, table: ParserBookTable) -> None:
        r = table.resolve("romanos")
        assert r is not None
        assert r.confidence == 1.0
        assert r.ambiguous is False

    def test_ambiguous_alias_confidence_05(self, table: ParserBookTable) -> None:
        r = table.resolve("jo")
        assert r is not None
        assert r.confidence == 0.5
        assert r.ambiguous is True

    def test_unique_long_alias_confidence_1(self, table: ParserBookTable) -> None:
        r = table.resolve("primeira carta aos corintios")
        assert r is not None
        assert r.confidence == 1.0
        assert r.ambiguous is False


# ---------------------------------------------------------------------------
# Abreviações
# ---------------------------------------------------------------------------

class TestAbbreviations:
    def test_gn(self, table: ParserBookTable) -> None:
        r = table.resolve("gn")
        assert r is not None
        assert r.book.canonical == "Gênesis"

    def test_sl(self, table: ParserBookTable) -> None:
        r = table.resolve("sl")
        assert r is not None
        assert r.book.canonical == "Salmos"

    def test_mt(self, table: ParserBookTable) -> None:
        r = table.resolve("mt")
        assert r is not None
        assert r.book.canonical == "Mateus"

    def test_ap(self, table: ParserBookTable) -> None:
        r = table.resolve("ap")
        assert r is not None
        assert r.book.canonical == "Apocalipse"

    def test_1co(self, table: ParserBookTable) -> None:
        r = table.resolve("1co")
        assert r is not None
        assert r.book.canonical == "1 Coríntios"

    def test_2co(self, table: ParserBookTable) -> None:
        r = table.resolve("2co")
        assert r is not None
        assert r.book.canonical == "2 Coríntios"


# ---------------------------------------------------------------------------
# Variações PT-BR e diacritics
# ---------------------------------------------------------------------------

class TestVariations:
    def test_with_diacritics(self, table: ParserBookTable) -> None:
        r = table.resolve("João")
        assert r is not None
        assert r.book.id == 43

    def test_without_diacritics(self, table: ParserBookTable) -> None:
        r = table.resolve("joao")
        assert r is not None
        assert r.book.id == 43

    def test_uppercase(self, table: ParserBookTable) -> None:
        r = table.resolve("JOÃO")
        assert r is not None
        assert r.book.id == 43

    def test_mixed_case(self, table: ParserBookTable) -> None:
        r = table.resolve("RoMaNoS")
        assert r is not None
        assert r.book.id == 45

    def test_sao_joao(self, table: ParserBookTable) -> None:
        r = table.resolve("sao joao")
        assert r is not None
        assert r.book.id == 43

    def test_evangelho_de_joao(self, table: ParserBookTable) -> None:
        r = table.resolve("evangelho de joao")
        assert r is not None
        assert r.book.id == 43

    def test_1_corinto(self, table: ParserBookTable) -> None:
        r = table.resolve("1 corinto")
        assert r is not None
        assert r.book.canonical == "1 Coríntios"


# ---------------------------------------------------------------------------
# Casos extremos
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty(self, table: ParserBookTable) -> None:
        assert table.resolve("") is None

    def test_whitespace_only(self, table: ParserBookTable) -> None:
        assert table.resolve("   ") is None

    def test_not_found(self, table: ParserBookTable) -> None:
        assert table.resolve("xyzwxyz") is None

    def test_punctuation(self, table: ParserBookTable) -> None:
        """Pontuação é removida pelo Normalizer."""
        r = table.resolve("João, 3:16")
        assert r is not None
        assert r.book.id == 43

    def test_by_id_valid(self, table: ParserBookTable) -> None:
        book = table.by_id(43)
        assert book.canonical == "João"

    def test_by_id_invalid(self, table: ParserBookTable) -> None:
        with pytest.raises(KeyError, match="not found"):
            table.by_id(99)

    def test_all_books_count(self, table: ParserBookTable) -> None:
        assert len(table.all_books()) == 66

    def test_all_books_sorted(self, table: ParserBookTable) -> None:
        books = table.all_books()
        ids = [b.id for b in books]
        assert ids == sorted(ids)
        assert ids[0] == 1
        assert ids[-1] == 66


# ---------------------------------------------------------------------------
# Romanos e ordinais integrados com Normalizer
# ---------------------------------------------------------------------------

class TestNormalizerIntegration:
    def test_roman_i_corintios(self, table: ParserBookTable) -> None:
        r = table.resolve("I Coríntios")
        assert r is not None
        assert r.book.id == 46

    def test_roman_ii_pedro(self, table: ParserBookTable) -> None:
        r = table.resolve("II Pedro")
        assert r is not None
        assert r.book.id == 61

    def test_roman_iii_joao(self, table: ParserBookTable) -> None:
        r = table.resolve("III João")
        assert r is not None
        assert r.book.id == 64

    def test_ordinal_primeira_pedro(self, table: ParserBookTable) -> None:
        r = table.resolve("primeira pedro")
        assert r is not None
        assert r.book.id == 60

    def test_ordinal_segundo_reis(self, table: ParserBookTable) -> None:
        r = table.resolve("segundo reis")
        assert r is not None
        assert r.book.id == 12

    def test_ordinal_terceiro_joao(self, table: ParserBookTable) -> None:
        r = table.resolve("terceiro joao")
        assert r is not None
        assert r.book.id == 64


# ---------------------------------------------------------------------------
# Posição (start/end) na string
# ---------------------------------------------------------------------------

class TestPosition:
    def test_start_end_joao_in_phrase(self, table: ParserBookTable) -> None:
        r = table.resolve("mostrar joao 3 16")
        assert r is not None
        assert r.start >= 0
        assert r.end > r.start
        # "joao" começa após "mostrar "
        assert r.start == 8

    def test_start_end_at_beginning(self, table: ParserBookTable) -> None:
        r = table.resolve("joao 3 16")
        assert r is not None
        assert r.start == 0


# ---------------------------------------------------------------------------
# load_parser_books
# ---------------------------------------------------------------------------

class TestLoadParserBooks:
    def test_load_default(self) -> None:
        t = load_parser_books("config/books.json")
        assert len(t.all_books()) == 66

    def test_load_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            load_parser_books(str(tmp_path / "nonexistent.json"))

    def test_load_with_custom_normalizer(self) -> None:
        norm = Normalizer()
        t = load_parser_books("config/books.json", normalizer=norm)
        assert t.resolve("joao") is not None
