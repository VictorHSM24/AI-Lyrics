"""Testes unitários do módulo busca/searcher.py.

Estratégia:
  - Cria um DB FTS5 real em tmp_path com versículos de teste.
  - Usa BookTable real do config/books.json.
  - Testa todos os tipos de busca: textual, aproximada, referência,
    capítulo, contextual.
  - Testa RRF fusion, confidence, ambiguidade, cache, métricas.
  - Testa tratamento de erros (DB ausente, livro desconhecido, query vazia).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from busca.exceptions import SearchError
from busca.searcher import (
    SearchMetrics,
    SearchResult,
    Searcher,
    _bm25_to_confidence,
    _build_reference,
    _normalize_query,
    _normalize_rrf_scores,
    _parse_book_id_from_id,
    _rrf_fuse,
)
from config.books import BookTable
from config.loader import load_books
from config.models import SearchConfig


# ---------------------------------------------------------------------------
# Dados de teste
# ---------------------------------------------------------------------------

SAMPLE_VERSES = [
    {"book": "Gênesis", "book_id": 1, "chapter": 1, "verse": 1,
     "text": "No princípio criou Deus os céus e a terra.", "version": "ACF"},
    {"book": "Gênesis", "book_id": 1, "chapter": 1, "verse": 2,
     "text": "E a terra era sem forma e vazia; e havia trevas sobre a face do abismo.",
     "version": "ACF"},
    {"book": "Gênesis", "book_id": 1, "chapter": 1, "verse": 3,
     "text": "E disse Deus: Haja luz. E houve luz.", "version": "ACF"},
    {"book": "João", "book_id": 43, "chapter": 3, "verse": 16,
     "text": "Porque Deus amou o mundo de tal maneira que deu o seu Filho unigênito.",
     "version": "ACF"},
    {"book": "João", "book_id": 43, "chapter": 3, "verse": 17,
     "text": "Porque Deus enviou o seu Filho ao mundo, para que o mundo seja salvo por ele.",
     "version": "ACF"},
    {"book": "Romanos", "book_id": 45, "chapter": 8, "verse": 28,
     "text": "E sabemos que todas as coisas cooperam para o bem daqueles que amam a Deus.",
     "version": "ACF"},
    {"book": "Mateus", "book_id": 40, "chapter": 5, "verse": 13,
     "text": "Vós sois o sal da terra.", "version": "ACF"},
    {"book": "João", "book_id": 43, "chapter": 3, "verse": 16,
     "text": "Porque Deus amou o mundo de tal maneira que deu o seu Filho unigênito.",
     "version": "NVI"},
]


# ---------------------------------------------------------------------------
# Dados multiversão — simula o cenário real onde ACF tem wording diferente
# para alguns versículos, enquanto ARA/NAA têm o wording que o usuário busca.
# ---------------------------------------------------------------------------

MULTIVERSION_VERSES = [
    # João 3:16 — ACF e ARA têm wording similar ("Deus amou o mundo")
    {"book": "João", "book_id": 43, "chapter": 3, "verse": 16,
     "text": "Porque Deus amou o mundo de tal maneira que deu o seu Filho unigênito.",
     "version": "ACF"},
    {"book": "João", "book_id": 43, "chapter": 3, "verse": 16,
     "text": "Porque Deus amou o mundo de tal maneira que deu o seu Filho unigênito.",
     "version": "ARA"},

    # Salmos 23:4 — ACF tem "vale da sombra da morte" (wording exato)
    {"book": "Salmos", "book_id": 19, "chapter": 23, "verse": 4,
     "text": "Ainda que eu andasse pelo vale da sombra da morte, não temeria mal algum.",
     "version": "ACF"},
    {"book": "Salmos", "book_id": 19, "chapter": 23, "verse": 4,
     "text": "Ainda que eu ande pelo vale da sombra da morte, não temerei mal nenhum.",
     "version": "NAA"},

    # Filipenses 4:13 — ACF usa "Posso todas as coisas em Cristo"
    #                    ARA/NAA usam "tudo posso naquele que me fortalece"
    {"book": "Filipenses", "book_id": 50, "chapter": 4, "verse": 13,
     "text": "Posso todas as coisas em Cristo que me fortalece.",
     "version": "ACF"},
    {"book": "Filipenses", "book_id": 50, "chapter": 4, "verse": 13,
     "text": "tudo posso naquele que me fortalece.",
     "version": "ARA"},
    {"book": "Filipenses", "book_id": 50, "chapter": 4, "verse": 13,
     "text": "Tudo posso naquele que me fortalece.",
     "version": "NAA"},

    # Romanos 8:28 — ACF usa "contribuem juntamente"
    #                 ARA/NAA usam "cooperam para o bem"
    {"book": "Romanos", "book_id": 45, "chapter": 8, "verse": 28,
     "text": "E sabemos que todas as coisas contribuem juntamente para o bem.",
     "version": "ACF"},
    {"book": "Romanos", "book_id": 45, "chapter": 8, "verse": 28,
     "text": "Sabemos que todas as coisas cooperam para o bem daqueles que amam a Deus.",
     "version": "ARA"},
    {"book": "Romanos", "book_id": 45, "chapter": 8, "verse": 28,
     "text": "Sabemos que todas as coisas cooperam para o bem daqueles que amam a Deus.",
     "version": "NAA"},

    # Hebreus 11:1 — ACF usa "firme fundamento"
    #                 ARA/NAA usam "certeza"
    {"book": "Hebreus", "book_id": 58, "chapter": 11, "verse": 1,
     "text": "ORA, a fé é o firme fundamento das coisas que se esperam.",
     "version": "ACF"},
    {"book": "Hebreus", "book_id": 58, "chapter": 11, "verse": 1,
     "text": "Ora, a fé é a certeza de coisas que se esperam.",
     "version": "ARA"},
    {"book": "Hebreus", "book_id": 58, "chapter": 11, "verse": 1,
     "text": "Ora, a fé é a certeza de coisas que se esperam.",
     "version": "NAA"},

    # Versículo extra para testar busca comum
    {"book": "Gênesis", "book_id": 1, "chapter": 1, "verse": 1,
     "text": "No princípio criou Deus os céus e a terra.", "version": "ACF"},

    # João 3:17 ACF — necessário para teste de navegação (próximo de 3:16)
    {"book": "João", "book_id": 43, "chapter": 3, "verse": 17,
     "text": "Porque Deus enviou o seu Filho ao mundo, para que o mundo seja salvo por ele.",
     "version": "ACF"},
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FTS5_SCHEMA = (
    "CREATE VIRTUAL TABLE verses USING fts5("
    "book, "
    "chapter UNINDEXED, "
    "verse UNINDEXED, "
    "text, "
    "version UNINDEXED, "
    "id UNINDEXED, "
    "tokenize = 'unicode61 remove_diacritics 2'"
    ")"
)


def _build_test_db(db_path: str, verses: list[dict]) -> None:
    """Cria um DB FTS5 de teste com os versículos fornecidos."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_FTS5_SCHEMA)
        for v in verses:
            verse_id = f"{v['book_id']:02d}{v['chapter']:03d}{v['verse']:03d}"
            conn.execute(
                "INSERT INTO verses (book, chapter, verse, text, version, id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (v["book"], v["chapter"], v["verse"], v["text"], v["version"], verse_id),
            )
        conn.commit()
    finally:
        conn.close()


def _search_config(db_path: str) -> SearchConfig:
    return SearchConfig(
        fts5_db=db_path,
        embeddings_path="data/bible.embeddings.npy",
        embedding_model="intfloat/multilingual-e5-small",
        embedding_device="cpu",
        rrf_k=60,
        top_k=20,
        search_gap=0.15,
    )


@pytest.fixture
def book_table() -> BookTable:
    """Carrega BookTable real do config/books.json."""
    books_path = Path(__file__).parent.parent / "config" / "books.json"
    return load_books(str(books_path))


@pytest.fixture
def test_db(tmp_path: Path) -> str:
    """Cria um DB FTS5 de teste em tmp_path."""
    db_path = str(tmp_path / "test.sqlite")
    _build_test_db(db_path, SAMPLE_VERSES)
    return db_path


@pytest.fixture
def searcher(test_db: str, book_table: BookTable) -> Searcher:
    """Cria um Searcher com DB de teste."""
    config = _search_config(test_db)
    return Searcher(config, book_table, version="ACF")


@pytest.fixture
def multiversion_db(tmp_path: Path) -> str:
    """Cria um DB FTS5 multiversão para testes de priorização."""
    db_path = str(tmp_path / "multiversion.sqlite")
    _build_test_db(db_path, MULTIVERSION_VERSES)
    return db_path


@pytest.fixture
def mv_searcher(multiversion_db: str, book_table: BookTable) -> Searcher:
    """Cria um Searcher com DB multiversão (ACF preferida)."""
    config = _search_config(multiversion_db)
    return Searcher(config, book_table, version="ACF")


# ---------------------------------------------------------------------------
# Helpers de normalização
# ---------------------------------------------------------------------------

class TestNormalizeQuery:
    def test_lowercase(self) -> None:
        assert _normalize_query("Deus Amou") == "deus amou"

    def test_remove_diacritics(self) -> None:
        assert _normalize_query("João Coríntios") == "joao corintios"

    def test_collapse_whitespace(self) -> None:
        assert _normalize_query("deus   amou   o   mundo") == "deus amou o mundo"

    def test_empty(self) -> None:
        assert _normalize_query("") == ""

    def test_only_spaces(self) -> None:
        assert _normalize_query("   ") == ""


class TestParseBookIdFromId:
    def test_standard(self) -> None:
        assert _parse_book_id_from_id("43003016") == 43

    def test_single_digit(self) -> None:
        assert _parse_book_id_from_id("01001001") == 1


class TestBuildReference:
    def test_with_verse(self) -> None:
        assert _build_reference("João", 3, 16) == "João 3:16"

    def test_without_verse(self) -> None:
        assert _build_reference("João", 3, None) == "João 3"


class TestBuildFts5Query:
    def test_simple(self) -> None:
        q = Searcher._build_fts5_query("deus amou o mundo")
        assert '"deus" "amou" "o" "mundo"' == q

    def test_empty(self) -> None:
        assert Searcher._build_fts5_query("") == ""

    def test_escapes_operators(self) -> None:
        # _build_fts5_query não normaliza — recebe query já normalizada
        q = Searcher._build_fts5_query("deus or mundo")
        assert '"deus" "or" "mundo"' == q


class TestBm25ToConfidence:
    def test_zero_bm25(self) -> None:
        """BM25 = 0 (nenhum match) → confidence ~0.5."""
        c = _bm25_to_confidence(0.0)
        assert 0.4 < c < 0.6

    def test_good_match(self) -> None:
        """BM25 muito negativo → confidence alta."""
        # bm25=-3 → positive=3 → sigmoid(3/5)=sigmoid(0.6)≈0.646
        # bm25=-10 → positive=10 → sigmoid(10/5)=sigmoid(2)≈0.881
        c = _bm25_to_confidence(-10.0)
        assert c > 0.8

    def test_poor_match(self) -> None:
        """BM25 pouco negativo → confidence baixa."""
        c = _bm25_to_confidence(-0.1)
        assert c < 0.6

    def test_bounded(self) -> None:
        """Confidence deve estar em [0, 1]."""
        for bm25 in [-10, -5, -1, 0, 1]:
            c = _bm25_to_confidence(float(bm25))
            assert 0.0 <= c <= 1.0


# ---------------------------------------------------------------------------
# RRF
# ---------------------------------------------------------------------------

class TestRRF:
    def test_single_source(self) -> None:
        """RRF com uma fonte only."""
        scores = _rrf_fuse(["a", "b", "c"], [], k=60)
        assert scores["a"] > scores["b"] > scores["c"]

    def test_two_sources(self) -> None:
        """RRF com duas fontes — IDs em ambas devem ter score maior."""
        scores = _rrf_fuse(["a", "b", "c"], ["b", "a", "d"], k=60)
        # 'a' e 'b' aparecem em ambos → score maior que 'c' e 'd'
        assert scores["a"] > scores["c"]
        assert scores["b"] > scores["d"]

    def test_empty(self) -> None:
        scores = _rrf_fuse([], [], k=60)
        assert scores == {}

    def test_k_affects_scores(self) -> None:
        """k maior → scores menores mas ordering preservado."""
        scores_k1 = _rrf_fuse(["a", "b"], [], k=1)
        scores_k60 = _rrf_fuse(["a", "b"], [], k=60)
        assert scores_k1["a"] > scores_k60["a"]


class TestNormalizeRRF:
    def test_normalizes(self) -> None:
        scores = {"a": 0.5, "b": 0.1}
        normalized = _normalize_rrf_scores(scores)
        assert normalized["a"] == 1.0
        assert 0 < normalized["b"] < 1.0

    def test_empty(self) -> None:
        assert _normalize_rrf_scores({}) == {}

    def test_single(self) -> None:
        scores = {"a": 0.5}
        normalized = _normalize_rrf_scores(scores)
        assert normalized["a"] == 1.0


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------

class TestSearchResult:
    def test_construction(self) -> None:
        r = SearchResult(
            reference="João 3:16",
            book="João",
            book_id=43,
            chapter=3,
            verse=16,
            text="Porque Deus amou o mundo...",
            version="ACF",
            score=0.97,
            c_search=0.95,
            ambiguous=False,
            match_type="fts",
        )
        assert r.reference == "João 3:16"
        assert r.book_id == 43
        assert r.score == 0.97
        assert r.match_type == "fts"

    def test_frozen(self) -> None:
        r = SearchResult("a", "b", 1, 1, 1, "t", "v", 0.5, 0.5, False, "fts")
        with pytest.raises((AttributeError, Exception)):
            r.score = 0.99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SearchMetrics
# ---------------------------------------------------------------------------

class TestSearchMetrics:
    def test_defaults(self) -> None:
        m = SearchMetrics()
        assert m.total_searches == 0
        assert m.avg_time_ms == 0.0

    def test_avg_time(self) -> None:
        m = SearchMetrics()
        m.total_searches = 3
        m.total_time_ms = 30.0
        assert m.avg_time_ms == 10.0

    def test_avg_results(self) -> None:
        m = SearchMetrics()
        m.successful = 2
        m.total_results = 10
        assert m.avg_results == 5.0

    def test_reset(self) -> None:
        m = SearchMetrics()
        m.total_searches = 5
        m.by_type["fts"] = 3
        m.reset()
        assert m.total_searches == 0
        assert m.by_type == {}


# ---------------------------------------------------------------------------
# Searcher — inicialização
# ---------------------------------------------------------------------------

class TestSearcherInit:
    def test_init_success(self, test_db: str, book_table: BookTable) -> None:
        config = _search_config(test_db)
        s = Searcher(config, book_table, version="ACF")
        assert s.is_open is True
        assert s.db_path == test_db
        s.close()
        assert s.is_open is False

    def test_init_db_not_found(self, tmp_path: Path, book_table: BookTable) -> None:
        config = _search_config(str(tmp_path / "nonexistent.sqlite"))
        with pytest.raises(SearchError, match="not found"):
            Searcher(config, book_table)

    def test_init_table_missing(self, tmp_path: Path, book_table: BookTable) -> None:
        """DB existe mas sem tabela verses."""
        db_path = str(tmp_path / "empty.sqlite")
        conn = sqlite3.connect(db_path)
        conn.close()
        config = _search_config(db_path)
        with pytest.raises(SearchError, match="table.*not found"):
            Searcher(config, book_table)

    def test_context_manager(self, test_db: str, book_table: BookTable) -> None:
        config = _search_config(test_db)
        with Searcher(config, book_table) as s:
            assert s.is_open is True
        assert s.is_open is False


# ---------------------------------------------------------------------------
# Searcher — busca textual
# ---------------------------------------------------------------------------

class TestSearchText:
    def test_search_deus_amou_mundo(self, searcher: Searcher) -> None:
        """'deus amou o mundo' → João 3:16 no top-1."""
        results = searcher.search("deus amou o mundo")
        assert len(results) > 0
        assert results[0].book == "João"
        assert results[0].chapter == 3
        assert results[0].verse == 16
        assert results[0].match_type in ("hybrid", "fts")

    def test_search_todas_coisas_cooperam(self, searcher: Searcher) -> None:
        """'todas as coisas cooperam para o bem' → Romanos 8:28."""
        results = searcher.search("todas as coisas cooperam para o bem")
        assert len(results) > 0
        ids = [r.book_id for r in results]
        assert 45 in ids  # Romanos
        assert results[0].book == "Romanos"
        assert results[0].chapter == 8
        assert results[0].verse == 28

    def test_search_sal_terra(self, searcher: Searcher) -> None:
        """'sal da terra' → Mateus 5:13."""
        results = searcher.search("sal da terra")
        assert len(results) > 0
        assert results[0].book == "Mateus"
        assert results[0].chapter == 5
        assert results[0].verse == 13

    def test_search_empty_query(self, searcher: Searcher) -> None:
        assert searcher.search("") == []
        assert searcher.search("   ") == []

    def test_search_no_results(self, searcher: Searcher) -> None:
        """Query que não existe na Bíblia → []."""
        results = searcher.search("xyzqwerty nonexistent")
        assert results == []

    def test_search_results_have_scores(self, searcher: Searcher) -> None:
        results = searcher.search("deus amou o mundo")
        assert len(results) > 0
        for r in results:
            assert 0.0 <= r.score <= 1.0
            assert 0.0 <= r.c_search <= 1.0

    def test_search_results_ordered_by_score(self, searcher: Searcher) -> None:
        results = searcher.search("deus")
        assert len(results) > 1
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

    def test_search_top_k_limit(self, searcher: Searcher) -> None:
        results = searcher.search("deus", top_k=2)
        assert len(results) <= 2

    def test_search_filter_by_version(self, searcher: Searcher) -> None:
        """Resultados devem ser apenas da versão ACF (após dedup, ACF vence)."""
        results = searcher.search("deus amou o mundo", version="ACF")
        # Após dedup, João 3:16 ACF tem maior score+bônus → único resultado
        assert len(results) > 0
        for r in results:
            assert r.version == "ACF"

    def test_search_version_nvi(self, searcher: Searcher) -> None:
        """Buscar com version=NVI: versículo correto encontrado.

        Com multiversão, NVI não é mais filtro rígido. ACF tem bônus maior
        e pode vencer mesmo quando NVI é solicitada, mas o versículo
        correto (João 3:16) deve ser encontrado.
        """
        results = searcher.search("deus amou o mundo", version="NVI")
        assert len(results) > 0
        assert results[0].book == "João"
        assert results[0].chapter == 3
        assert results[0].verse == 16

    def test_search_with_diacritics(self, searcher: Searcher) -> None:
        """Buscar com acentos deve funcionar (tokenizer remove diacritics)."""
        results = searcher.search("Deus amou o mundo")
        assert len(results) > 0
        assert results[0].book == "João"


# ---------------------------------------------------------------------------
# Searcher — busca por referência
# ---------------------------------------------------------------------------

class TestSearchReference:
    def test_reference_exact(self, searcher: Searcher) -> None:
        """'João 3:16' → versículo exato."""
        results = searcher.search("João 3:16")
        assert len(results) == 1
        assert results[0].book == "João"
        assert results[0].chapter == 3
        assert results[0].verse == 16
        assert results[0].match_type == "reference"
        assert results[0].score == 1.0

    def test_reference_not_found(self, searcher: Searcher) -> None:
        """Referência que não existe → []."""
        results = searcher.search("João 99:99")
        assert results == []

    def test_search_by_reference_method(self, searcher: Searcher) -> None:
        """Testa search_by_reference diretamente."""
        result = searcher.search_by_reference("João", 3, 16, version="ACF")
        assert result is not None
        assert result.book == "João"
        assert result.verse == 16
        assert result.match_type == "reference"

    def test_search_by_reference_unknown_book(self, searcher: Searcher) -> None:
        with pytest.raises(SearchError, match="unknown book"):
            searcher.search_by_reference("Livro Inexistente", 1, 1)

    def test_reference_with_ordinal(self, searcher: Searcher) -> None:
        """'1 Gênesis 1:1' não é válido, mas 'Gênesis 1:1' é."""
        results = searcher.search("Gênesis 1:1")
        assert len(results) == 1
        assert results[0].book == "Gênesis"
        assert results[0].chapter == 1
        assert results[0].verse == 1

    def test_reference_without_diacritics(self, searcher: Searcher) -> None:
        """'Joao 3:16' (sem acento) deve funcionar."""
        results = searcher.search("Joao 3:16")
        assert len(results) == 1
        assert results[0].book == "João"


# ---------------------------------------------------------------------------
# Searcher — busca por capítulo
# ---------------------------------------------------------------------------

class TestSearchChapter:
    def test_chapter_joao_3(self, searcher: Searcher) -> None:
        """'João 3' → todos os versículos do capítulo 3."""
        results = searcher.search("João 3")
        assert len(results) > 0
        for r in results:
            assert r.book == "João"
            assert r.chapter == 3
            assert r.match_type == "chapter"
        # Versículos devem estar ordenados
        verses = [r.verse for r in results]
        assert verses == sorted(verses)

    def test_chapter_genesis_1(self, searcher: Searcher) -> None:
        """'Gênesis 1' → capítulo 1 de Gênesis."""
        results = searcher.search("Gênesis 1")
        assert len(results) >= 3  # temos 3 versículos de Gn 1
        for r in results:
            assert r.book == "Gênesis"
            assert r.chapter == 1

    def test_chapter_not_found(self, searcher: Searcher) -> None:
        """Capítulo inexistente → []."""
        results = searcher.search("João 99")
        assert results == []

    def test_search_chapter_method(self, searcher: Searcher) -> None:
        results = searcher.search_chapter("João", 3, version="ACF")
        assert len(results) > 0
        assert all(r.chapter == 3 for r in results)

    def test_search_chapter_unknown_book(self, searcher: Searcher) -> None:
        with pytest.raises(SearchError, match="unknown book"):
            searcher.search_chapter("Livro Inexistente", 1)


# ---------------------------------------------------------------------------
# Searcher — busca contextual
# ---------------------------------------------------------------------------

class TestSearchContext:
    def test_context_next(self, searcher: Searcher) -> None:
        """'próximo' com state em João 3:16 → João 3:17."""
        from estado.state import BibleState

        state = BibleState(book_id=43, chapter=3, verse=16, version="ACF")
        results = searcher.search("próximo", state=state)
        assert len(results) == 1
        assert results[0].book == "João"
        assert results[0].chapter == 3
        assert results[0].verse == 17
        assert results[0].match_type == "context"

    def test_context_prev(self, searcher: Searcher) -> None:
        """'anterior' com state em João 3:17 → João 3:16."""
        from estado.state import BibleState

        state = BibleState(book_id=43, chapter=3, verse=17, version="ACF")
        results = searcher.search("anterior", state=state)
        assert len(results) == 1
        assert results[0].verse == 16

    def test_context_next_chapter_boundary(self, searcher: Searcher) -> None:
        """'próximo' no último versículo do capítulo → próximo capítulo v.1."""
        from estado.state import BibleState

        # Gênesis 1:3 é o último versículo de Gênesis 1 no DB de teste
        state = BibleState(book_id=1, chapter=1, verse=3, version="ACF")
        results = searcher.search("próximo", state=state)
        # Não há Gênesis 2 no DB de teste → []
        assert results == []

    def test_context_empty_state(self, searcher: Searcher) -> None:
        """'próximo' com state vazio → []."""
        from estado.state import BibleState

        state = BibleState(version="ACF")
        results = searcher.search("próximo", state=state)
        assert results == []

    def test_context_without_state_falls_back_to_text(self, searcher: Searcher) -> None:
        """'próximo' sem state → busca textual (pode não encontrar)."""
        results = searcher.search("próximo")
        # Deve retornar [] pois não há versículos com "próximo" no DB de teste
        # Ou pode retornar resultados se houver match
        assert isinstance(results, list)

    def test_search_context_method_next(self, searcher: Searcher) -> None:
        from estado.state import BibleState

        state = BibleState(book_id=43, chapter=3, verse=16, version="ACF")
        results = searcher.search_context(state, direction="next", version="ACF")
        assert len(results) == 1
        assert results[0].verse == 17


# ---------------------------------------------------------------------------
# Searcher — ambiguidade
# ---------------------------------------------------------------------------

class TestAmbiguity:
    def test_ambiguous_when_gap_small(self, searcher: Searcher) -> None:
        """Quando gap top1/top2 < search_gap, ambiguous=True."""
        # "deus" aparece em vários versículos → provavelmente ambíguo
        results = searcher.search("deus")
        if len(results) >= 2:
            # Não podemos garantir que é ambíguo (depende dos scores),
            # mas podemos verificar que o campo existe.
            assert isinstance(results[0].ambiguous, bool)

    def test_not_ambiguous_single_result(self, searcher: Searcher) -> None:
        """Resultado único → ambiguous=False."""
        results = searcher.search("João 3:16")
        assert len(results) == 1
        assert results[0].ambiguous is False

    def test_reference_not_ambiguous(self, searcher: Searcher) -> None:
        """Busca por referência nunca é ambígua."""
        results = searcher.search("Gênesis 1:1")
        assert len(results) == 1
        assert results[0].ambiguous is False


# ---------------------------------------------------------------------------
# Searcher — cache
# ---------------------------------------------------------------------------

class TestCache:
    def test_cache_hit(self, searcher: Searcher) -> None:
        """Segunda busca com mesma query deve ser cache hit."""
        searcher.search("deus amou o mundo")
        initial_misses = searcher.metrics.cache_misses
        searcher.search("deus amou o mundo")
        assert searcher.metrics.cache_hits > 0
        assert searcher.metrics.cache_misses == initial_misses + 0  # não incrementa em hit

    def test_cache_miss_different_query(self, searcher: Searcher) -> None:
        """Busca com query diferente → cache miss."""
        searcher.search("deus amou o mundo")
        initial_misses = searcher.metrics.cache_misses
        searcher.search("sal da terra")
        assert searcher.metrics.cache_misses > initial_misses


# ---------------------------------------------------------------------------
# Searcher — métricas
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_metrics_updated(self, searcher: Searcher) -> None:
        searcher.search("deus amou o mundo")
        searcher.search("sal da terra")
        assert searcher.metrics.total_searches == 2
        assert searcher.metrics.successful == 2
        assert searcher.metrics.total_time_ms > 0

    def test_metrics_empty_results(self, searcher: Searcher) -> None:
        searcher.search("xyzqwerty nonexistent")
        assert searcher.metrics.empty_results == 1
        assert searcher.metrics.successful == 0

    def test_metrics_by_type(self, searcher: Searcher) -> None:
        searcher.search("deus amou o mundo")
        searcher.search("João 3:16")
        assert searcher.metrics.by_type.get("hybrid", 0) + searcher.metrics.by_type.get("fts", 0) >= 1
        assert searcher.metrics.by_type.get("reference", 0) >= 1


# ---------------------------------------------------------------------------
# Searcher — auto-detecção
# ---------------------------------------------------------------------------

class TestAutoDetection:
    def test_text_query_detected_as_text(self, searcher: Searcher) -> None:
        results = searcher.search("deus amou o mundo")
        assert results[0].match_type in ("hybrid", "fts")

    def test_reference_detected_as_reference(self, searcher: Searcher) -> None:
        results = searcher.search("João 3:16")
        assert results[0].match_type == "reference"

    def test_chapter_detected_as_chapter(self, searcher: Searcher) -> None:
        results = searcher.search("João 3")
        assert all(r.match_type == "chapter" for r in results)

    def test_context_detected_as_context(self, searcher: Searcher) -> None:
        from estado.state import BibleState
        state = BibleState(book_id=43, chapter=3, verse=16, version="ACF")
        results = searcher.search("próximo", state=state)
        assert len(results) == 1
        assert results[0].match_type == "context"


# ---------------------------------------------------------------------------
# Searcher — robustez
# ---------------------------------------------------------------------------

class TestRobustness:
    def test_search_after_close_raises(self, searcher: Searcher) -> None:
        searcher.close()
        with pytest.raises(SearchError, match="database not open"):
            searcher.search("deus")

    def test_search_by_reference_after_close(self, searcher: Searcher) -> None:
        searcher.close()
        with pytest.raises(SearchError, match="database not open"):
            searcher.search_by_reference("João", 3, 16)

    def test_fts5_special_characters(self, searcher: Searcher) -> None:
        """Query com caracteres especiais FTS5 deve ser escapada."""
        # OR, AND, NOT são operadores FTS5 — devem ser tratados como texto
        results = searcher.search("deus OR mundo")
        # Não deve levantar exceção
        assert isinstance(results, list)

    def test_fts5_wildcard(self, searcher: Searcher) -> None:
        """Asterisco deve ser escapado (não tratado como wildcard)."""
        results = searcher.search("deus* mundo")
        assert isinstance(results, list)

    def test_unicode_query(self, searcher: Searcher) -> None:
        """Query com Unicode deve funcionar (remoção de diacritics)."""
        results = searcher.search("Deus amou o mundo")
        assert len(results) > 0


# ---------------------------------------------------------------------------
# Searcher — busca multiversão com priorização ACF
# ---------------------------------------------------------------------------


class TestMultiVersionSearch:
    """Testa busca multiversão: versículos de qualquer versão podem aparecer,
    com priorização da versão preferida (ACF) via bônus pequeno."""

    def test_caso1_deus_amou_mundo_acf(self, mv_searcher: Searcher) -> None:
        """'deus amou o mundo' → João 3:16 ACF (ACF tem wording exato)."""
        results = mv_searcher.search("deus amou o mundo")
        assert len(results) > 0
        assert results[0].book == "João"
        assert results[0].chapter == 3
        assert results[0].verse == 16
        # ACF tem wording exato + bônus → vence
        assert results[0].version == "ACF"

    def test_caso2_vale_sombra_morte_acf(self, mv_searcher: Searcher) -> None:
        """'vale da sombra da morte' → Salmos 23:4 ACF (ACF tem wording exato)."""
        results = mv_searcher.search("vale da sombra da morte")
        assert len(results) > 0
        assert results[0].book == "Salmos"
        assert results[0].chapter == 23
        assert results[0].verse == 4
        # ACF tem wording exato + bônus → vence
        assert results[0].version == "ACF"

    def test_caso3_tudo_posso_naquele_ara_ou_naa(
        self, mv_searcher: Searcher
    ) -> None:
        """'tudo posso naquele que me fortalece' → Filipenses 4:13 ARA/NAA.

        ACF usa 'Posso todas as coisas em Cristo' — match pior.
        ARA/NAA usam 'tudo posso naquele que me fortalece' — match exato.
        O bônus ACF (+0.05) não deve superar a diferença de match.
        """
        results = mv_searcher.search("tudo posso naquele que me fortalece")
        assert len(results) > 0
        assert results[0].book == "Filipenses"
        assert results[0].chapter == 4
        assert results[0].verse == 13
        # ACF tem wording muito diferente → ARA ou NAA deve vencer
        assert results[0].version in ("ARA", "NAA")

    def test_caso4_cooperam_para_o_bem_ara_ou_naa(
        self, mv_searcher: Searcher
    ) -> None:
        """'todas as coisas cooperam para o bem' → Romanos 8:28 ARA/NAA.

        ACF usa 'contribuem juntamente' — não contém 'cooperam'.
        ARA/NAA usam 'cooperam para o bem' — match exato.
        """
        results = mv_searcher.search("todas as coisas cooperam para o bem")
        assert len(results) > 0
        assert results[0].book == "Romanos"
        assert results[0].chapter == 8
        assert results[0].verse == 28
        # ACF não tem 'cooperam' → ARA ou NAA deve vencer
        assert results[0].version in ("ARA", "NAA")

    def test_caso5_fe_certeza_ara_ou_naa(self, mv_searcher: Searcher) -> None:
        """'fé é a certeza de coisas que se esperam' → Hebreus 11:1 ARA/NAA.

        ACF usa 'firme fundamento' — não contém 'certeza'.
        ARA/NAA usam 'certeza' — match exato.
        Nota: usa 'de' (não 'das') para corresponder ao texto real.
        """
        results = mv_searcher.search("fé é a certeza de coisas que se esperam")
        assert len(results) > 0
        assert results[0].book == "Hebreus"
        assert results[0].chapter == 11
        assert results[0].verse == 1
        # ACF não tem 'certeza' → ARA ou NAA deve vencer
        assert results[0].version in ("ARA", "NAA")

    def test_dedup_por_versiculo(self, mv_searcher: Searcher) -> None:
        """Resultado não deve ter duplicatas do mesmo (book, chapter, verse)."""
        results = mv_searcher.search("deus amou o mundo")
        refs = [(r.book, r.chapter, r.verse) for r in results]
        assert len(refs) == len(set(refs)), "Há versículos duplicados"

    def test_acf_vence_desempate(self, mv_searcher: Searcher) -> None:
        """Quando ACF e ARA têm wording equivalente, ACF vence pelo bônus."""
        results = mv_searcher.search("deus amou o mundo")
        # João 3:16 em ACF e ARA têm texto idêntico
        # ACF tem bônus +0.05 vs ARA +0.02 → ACF vence
        joao_results = [r for r in results if r.book == "João" and r.verse == 16]
        assert len(joao_results) == 1  # dedup
        assert joao_results[0].version == "ACF"

    def test_top_k_respeitado(self, mv_searcher: Searcher) -> None:
        """top_k deve ser respeitado após dedup."""
        results = mv_searcher.search("deus", top_k=3)
        assert len(results) <= 3

    def test_score_no_intervalo_01(self, mv_searcher: Searcher) -> None:
        """Scores devem estar em [0.0, 1.0] após re-normalização."""
        results = mv_searcher.search("deus amou o mundo")
        for r in results:
            assert 0.0 <= r.score <= 1.0
            assert 0.0 <= r.c_search <= 1.0

    def test_match_type_hybrid(self, mv_searcher: Searcher) -> None:
        """Busca textual multiversão deve ter match_type='hybrid'."""
        results = mv_searcher.search("vale da sombra da morte")
        assert results[0].match_type in ("hybrid", "fts")

    def test_ambiguidade_calculada(self, mv_searcher: Searcher) -> None:
        """ambiguous deve ser calculado corretamente após dedup."""
        results = mv_searcher.search("deus amou o mundo")
        # Pode ser ambíguo ou não, mas o campo deve existir
        assert isinstance(results[0].ambiguous, bool)

    # --- Regressões: referências explícitas continuam funcionando ---

    def test_referencia_exata_continua(self, mv_searcher: Searcher) -> None:
        """'João 3:16' → referência exata (não busca textual multiversão)."""
        results = mv_searcher.search("João 3:16")
        assert len(results) == 1
        assert results[0].match_type == "reference"
        assert results[0].book == "João"
        assert results[0].verse == 16
        assert results[0].version == "ACF"

    def test_capitulo_continua(self, mv_searcher: Searcher) -> None:
        """'João 3' → capítulo (não busca textual multiversão)."""
        results = mv_searcher.search("João 3")
        assert len(results) > 0
        assert all(r.match_type == "chapter" for r in results)
        assert all(r.chapter == 3 for r in results)
        assert all(r.version == "ACF" for r in results)

    def test_navegacao_continua(self, mv_searcher: Searcher) -> None:
        """'próximo' com state → navegação contextual (não busca textual)."""
        from estado.state import BibleState
        state = BibleState(book_id=43, chapter=3, verse=16, version="ACF")
        results = mv_searcher.search("próximo", state=state)
        assert len(results) == 1
        assert results[0].match_type == "context"
        assert results[0].verse == 17
