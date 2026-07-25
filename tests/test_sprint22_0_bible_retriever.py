"""Sprint 22.0 — Testes do BibleRetriever (RAG Local).

Valida:
- Descoberta automática de versões em data/sources/.
- Warm-up carrega todas as versões e cria índice FTS5 em memória.
- retrieve() retorna candidatos agregados por versículo.
- Agregação: múltiplas versões do mesmo versículo colapsam em um candidato.
- Ranking: candidatos melhor pontuados aparecem primeiro.
- Performance: retrieve < 100ms.
- Casos de borda: texto vazio, retriever não aquecido, fallback.
- Estruturas BibleCandidate e BibleVersionMatch.
"""
from __future__ import annotations

import os
import time

import pytest

from knowledge import (
    BibleCandidate,
    BibleVersionMatch,
    BibleRetriever,
    BibleRetrieverError,
    discover_versions,
    warmup_bible_retriever,
)
from knowledge.bible_retriever import _normalize_text, _bm25_to_score
from config.loader import load_books


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def book_table():
    """BookTable carregado de config/books.json (uma vez por módulo)."""
    return load_books("config/books.json")


@pytest.fixture(scope="module")
def retriever(book_table):
    """BibleRetriever aquecido com as bases reais (uma vez por módulo).

    Usa scope="module" para evitar reaquecer o índice em cada teste,
    pois o warm-up leva ~1.5s.
    """
    r, _stats = warmup_bible_retriever(
        sources_dir="data/sources",
        book_table=book_table,
        top_k_default=20,
    )
    yield r
    r.close()


# ---------------------------------------------------------------------------
# Testes de descoberta
# ---------------------------------------------------------------------------


class TestDiscoverVersions:
    """Testa a descoberta automática de bases SQLite."""

    def test_discover_finds_sqlite_files(self):
        """discover_versions encontra arquivos .sqlite em data/sources/."""
        files = discover_versions("data/sources")
        assert len(files) >= 1
        for f in files:
            assert f.suffix == ".sqlite"
            assert f.exists()

    def test_discover_raises_on_missing_dir(self):
        """discover_versions levanta erro se diretório não existe."""
        with pytest.raises(BibleRetrieverError, match="sources directory not found"):
            discover_versions("/nonexistent/path/xyz")

    def test_discover_raises_on_empty_dir(self, tmp_path):
        """discover_versions levanta erro se não há .sqlite."""
        with pytest.raises(BibleRetrieverError, match="no .sqlite files"):
            discover_versions(str(tmp_path))


# ---------------------------------------------------------------------------
# Testes de warm-up
# ---------------------------------------------------------------------------


class TestWarmup:
    """Testa o warm-up do BibleRetriever."""

    def test_warmup_loads_all_versions(self, retriever):
        """Warm-up carrega todas as 7 versões esperadas."""
        stats = retriever.stats
        assert stats.total_versions >= 1
        # As 7 versões conhecidas devem estar presentes.
        expected = {"ACF", "ARA", "ARC", "JFAA", "NAA", "NTLH", "NVT"}
        found = set(stats.versions_discovered)
        assert expected.issubset(found), f"missing versions: {expected - found}"

    def test_warmup_indexes_verses(self, retriever):
        """Warm-up indexa mais de 200k versículos (7 versões × ~31102)."""
        stats = retriever.stats
        assert stats.total_verses > 200000
        assert stats.unique_verses > 30000  # versículos únicos

    def test_warmup_records_init_time(self, retriever):
        """Warm-up registra tempo de inicialização > 0."""
        assert retriever.stats.init_time_ms > 0

    def test_is_ready_after_warmup(self, retriever):
        """is_ready retorna True após warm-up."""
        assert retriever.is_ready is True

    def test_versions_property(self, retriever):
        """versions retorna lista de códigos de versão."""
        versions = retriever.versions
        assert "ACF" in versions
        assert len(versions) >= 1


# ---------------------------------------------------------------------------
# Testes de retrieve
# ---------------------------------------------------------------------------


class TestRetrieve:
    """Testa a recuperação de candidatos."""

    def test_retrieve_joao_3_16(self, retriever):
        """retrieve('Porque Deus amou o mundo') encontra João 3:16."""
        candidates = retriever.retrieve("Porque Deus amou o mundo de tal maneira", top_k=5)
        assert len(candidates) >= 1
        top = candidates[0]
        assert top.book == "João"
        assert top.chapter == 3
        assert top.verse == 16
        assert top.aggregated_score > 0.9

    def test_retrieve_salmos_23(self, retriever):
        """retrieve('O Senhor é meu pastor') encontra Salmos 23:1."""
        candidates = retriever.retrieve("O Senhor é meu pastor nada me faltará", top_k=5)
        assert len(candidates) >= 1
        top = candidates[0]
        assert top.book == "Salmos"
        assert top.chapter == 23
        assert top.verse == 1

    def test_retrieve_numeros_6_24(self, retriever):
        """retrieve('O Senhor te abençoe') encontra Números 6:24.

        Este é o caso de referência menos frequente que motivou a Sprint 22.0.
        """
        candidates = retriever.retrieve("O Senhor te abençoe e te guarde", top_k=10)
        assert len(candidates) >= 1
        # Números 6:24 deve estar no top 5.
        numeros = [c for c in candidates if c.book_reference_id == 4 and c.chapter == 6 and c.verse == 24]
        assert len(numeros) >= 1, "Números 6:24 não encontrado no top 10"
        assert numeros[0].aggregated_score > 0.9

    def test_retrieve_aggregates_versions(self, retriever):
        """Candidatos agregam múltiplas versões do mesmo versículo."""
        candidates = retriever.retrieve("Porque Deus amou o mundo de tal maneira", top_k=5)
        top = candidates[0]
        # João 3:16 deve ter múltiplas versões (pelo menos 5 das 7).
        assert top.num_versions >= 5
        assert len(top.versions) == top.num_versions
        # Cada version match tem version, text, score.
        for v in top.versions:
            assert isinstance(v, BibleVersionMatch)
            assert v.version in {"ACF", "ARA", "ARC", "JFAA", "NAA", "NTLH", "NVT"}
            assert v.text
            assert 0.0 <= v.score <= 1.0

    def test_retrieve_orders_by_aggregated_score(self, retriever):
        """Candidatos são ordenados por aggregated_score (desc)."""
        candidates = retriever.retrieve("O Senhor é meu pastor nada me faltará", top_k=10)
        if len(candidates) >= 2:
            assert candidates[0].aggregated_score >= candidates[1].aggregated_score

    def test_retrieve_empty_text_returns_empty(self, retriever):
        """retrieve('') retorna lista vazia."""
        assert retriever.retrieve("") == []
        assert retriever.retrieve("   ") == []

    def test_retrieve_top_k_limits_results(self, retriever):
        """top_k limita o número de candidatos retornados."""
        candidates = retriever.retrieve("Deus", top_k=3)
        assert len(candidates) <= 3

    def test_retrieve_default_top_k(self, retriever):
        """Sem top_k, usa top_k_default (20)."""
        candidates = retriever.retrieve("Deus amou o mundo", top_k=None)
        assert len(candidates) <= 20

    def test_retrieve_performance_under_100ms(self, retriever):
        """retrieve() executa em <100ms (objetivo da Sprint 22.0)."""
        queries = [
            "O Senhor te abençoe e te guarde",
            "Porque Deus amou o mundo de tal maneira",
            "O Senhor é meu pastor nada me faltará",
            "Tudo posso naquele que me fortalece",
            "No princípio criou Deus os céus e a terra",
        ]
        for q in queries:
            t0 = time.monotonic()
            retriever.retrieve(q, top_k=20)
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            assert elapsed_ms < 100.0, f"retrieve({q!r}) took {elapsed_ms:.1f}ms (>100ms)"

    def test_retrieve_not_warmed_up_raises(self):
        """retrieve() sem warm-up levanta BibleRetrieverError."""
        r = BibleRetriever(sources_dir="data/sources")
        with pytest.raises(BibleRetrieverError, match="not warmed up"):
            r.retrieve("teste", top_k=5)

    def test_retrieve_canonical_reference_format(self, retriever):
        """canonical_reference tem formato 'Livro Cap:Vers'."""
        candidates = retriever.retrieve("Porque Deus amou o mundo", top_k=5)
        if candidates:
            ref = candidates[0].canonical_reference
            assert ":" in ref
            assert " " in ref


# ---------------------------------------------------------------------------
# Testes de estruturas de dados
# ---------------------------------------------------------------------------


class TestBibleCandidate:
    """Testa BibleCandidate e BibleVersionMatch."""

    def test_bible_version_match_to_dict(self):
        """BibleVersionMatch.to_dict() retorna dict correto."""
        v = BibleVersionMatch(version="ACF", text="teste", score=0.95)
        d = v.to_dict()
        assert d["version"] == "ACF"
        assert d["text"] == "teste"
        assert d["score"] == 0.95

    def test_bible_candidate_to_dict(self):
        """BibleCandidate.to_dict() retorna dict correto."""
        v = BibleVersionMatch(version="ACF", text="teste", score=0.95)
        c = BibleCandidate(
            book="João", book_reference_id=43, chapter=3, verse=16,
            canonical_reference="João 3:16", aggregated_score=0.95,
            versions=(v,), best_score=0.95, mean_score=0.95,
            num_versions=1, search_rank=1,
        )
        d = c.to_dict()
        assert d["book"] == "João"
        assert d["chapter"] == 3
        assert d["verse"] == 16
        assert d["canonical_reference"] == "João 3:16"
        assert d["aggregated_score"] == 0.95
        assert len(d["versions"]) == 1
        assert d["num_versions"] == 1

    def test_bible_candidate_primary_text(self):
        """primary_text retorna texto da versão com maior score."""
        v1 = BibleVersionMatch(version="ACF", text="texto A", score=0.8)
        v2 = BibleVersionMatch(version="NVT", text="texto B", score=0.95)
        c = BibleCandidate(
            book="João", book_reference_id=43, chapter=3, verse=16,
            canonical_reference="João 3:16", aggregated_score=0.9,
            versions=(v1, v2), best_score=0.95, mean_score=0.875,
            num_versions=2, search_rank=1,
        )
        assert c.primary_text == "texto B"  # v2 tem score maior

    def test_bible_candidate_is_frozen(self):
        """BibleCandidate é imutável."""
        v = BibleVersionMatch(version="ACF", text="t", score=0.9)
        c = BibleCandidate(
            book="João", book_reference_id=43, chapter=3, verse=16,
            canonical_reference="João 3:16", aggregated_score=0.9,
            versions=(v,), best_score=0.9, mean_score=0.9,
            num_versions=1, search_rank=1,
        )
        with pytest.raises(AttributeError):
            c.book = "Gênesis"  # type: ignore


# ---------------------------------------------------------------------------
# Testes de helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    """Testa funções helper de normalização e scoring."""

    def test_normalize_text_removes_diacritics(self):
        """_normalize_text remove acentos e lowercase."""
        assert _normalize_text("João") == "joao"
        assert _normalize_text("NÚMEROS") == "numeros"
        assert _normalize_text("  Espaços  ") == "espacos"

    def test_normalize_text_empty(self):
        """_normalize_text('') retorna ''."""
        assert _normalize_text("") == ""

    def test_bm25_to_score_range(self):
        """_bm25_to_score retorna valor em [0, 1]."""
        assert 0.0 <= _bm25_to_score(-0.5) <= 1.0
        assert 0.0 <= _bm25_to_score(-1.0) <= 1.0
        assert 0.0 <= _bm25_to_score(-5.0) <= 1.0
        # BM25 = 0 (sem match) deve dar score baixo.
        assert _bm25_to_score(0.0) == 0.0

    def test_bm25_to_score_better_match_higher_score(self):
        """BM25 mais negativo (melhor match) → score mais alto."""
        score_weak = _bm25_to_score(-0.5)
        score_strong = _bm25_to_score(-3.0)
        assert score_strong > score_weak
