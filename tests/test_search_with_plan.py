"""Testes de search_with_plan (múltiplas estratégias + ranking composto).

Cobre:
  - search_with_plan com QueryPlan simples (sem enrichment)
  - search_with_plan com QueryPlan enriquecido (keywords + books + sinônimos)
  - Múltiplas estratégias (OR, AND, book_filter, fuzzy)
  - Ranking composto (phrase match, keyword hits, book bonus)
  - Casos que antes falhavam com search() tradicional
  - Compatibilidade: search() tradicional não alterado
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from busca.query_planner import QueryPlan, QueryPlanner
from busca.searcher import Searcher
from config import load_books, load_config
from core.types import Intent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def searcher():
    """Searcher real conectado ao banco SQLite."""
    config_path = "config/config.yaml"
    if not os.path.isfile(config_path):
        pytest.skip("config.yaml not found")
    cfg = load_config(config_path)
    if not os.path.isfile(cfg.search.fts5_db):
        pytest.skip(f"FTS5 database not found: {cfg.search.fts5_db}")
    book_table = load_books()
    s = Searcher(cfg.search, book_table, cfg.state.default_version)
    yield s
    s.close()


@pytest.fixture
def planner():
    return QueryPlanner()


# ---------------------------------------------------------------------------
# Testes de search_with_plan
# ---------------------------------------------------------------------------


class TestSearchWithPlan:
    """Testes de Searcher.search_with_plan()."""

    def test_empty_plan_returns_empty(self, searcher: Searcher) -> None:
        plan = QueryPlan(original_query="", normalized_query="")
        results = searcher.search_with_plan(plan)
        assert results == []

    def test_simple_plan_returns_results(self, searcher: Searcher) -> None:
        plan = QueryPlan(
            original_query="vale da sombra da morte",
            normalized_query="vale da sombra da morte",
            keywords=("vale", "sombra", "morte"),
        )
        results = searcher.search_with_plan(plan)
        assert len(results) > 0
        assert results[0].book == "Salmos"
        assert results[0].chapter == 23

    def test_plan_with_book_filter(self, searcher: Searcher) -> None:
        """Book filter deve restringir busca aos livros sugeridos."""
        plan = QueryPlan(
            original_query="tudo posso naquele que me fortalece",
            normalized_query="tudo posso naquele que me fortalece",
            keywords=("posso", "fortalece"),
            suggested_books=("Filipenses",),
            search_modes=("or", "keyword_subset", "book_filter", "fuzzy"),
            filters={"suggested_book_names": ["Filipenses"]},
        )
        results = searcher.search_with_plan(plan)
        assert len(results) > 0
        assert results[0].book == "Filipenses"
        assert results[0].chapter == 4
        assert results[0].verse == 13

    def test_plan_with_synonyms_as_boost(self, searcher: Searcher) -> None:
        """Sinônimos (boost_terms) devem ajudar a encontrar resultados."""
        plan = QueryPlan(
            original_query="Jesus manda lançar a rede à direita",
            normalized_query="jesus manda lancar a rede a direita",
            keywords=("rede", "direita", "barco"),
            suggested_books=("João",),
            search_modes=("or", "keyword_subset", "book_filter", "fuzzy"),
            boost_terms=("lancar", "jogar"),
            filters={"suggested_book_names": ["João"]},
        )
        results = searcher.search_with_plan(plan)
        assert len(results) > 0
        assert results[0].book == "João"
        assert results[0].chapter == 21

    def test_plan_faith_certainity(self, searcher: Searcher) -> None:
        """Caso que falhava com search() tradicional: 'fé é a certeza'."""
        plan = QueryPlan(
            original_query="a fé é a certeza das coisas que se esperam",
            normalized_query="a fe e a certeza das coisas que se esperam",
            keywords=("fe", "certeza", "coisas", "esperam"),
            suggested_books=("Hebreus",),
            search_modes=("or", "keyword_subset", "book_filter", "fuzzy"),
            filters={"suggested_book_names": ["Hebreus"]},
        )
        results = searcher.search_with_plan(plan)
        assert len(results) > 0
        assert results[0].book == "Hebreus"
        assert results[0].chapter == 11
        assert results[0].verse == 1

    def test_plan_who_without_sin(
        self, searcher: Searcher, planner: QueryPlanner,
    ) -> None:
        """Caso que falhava com search() tradicional: 'quem não tiver pecado'."""
        intent = Intent(
            action="search",
            query="quem não tiver pecado",
            confidence=0.9,
            source="llm",
            raw="quem não tiver pecado",
            enrichment={
                "keywords": ["pecado"],
                "livros_sugeridos": ["João"],
                "sinonimos": ["sem pecado", "inocente", "pedra"],
            },
        )
        plan = planner.plan(intent)
        results = searcher.search_with_plan(plan)
        assert len(results) > 0
        # João 8:7 deve estar no top 3
        top_refs = [r.reference for r in results[:3]]
        assert any("João 8:7" in ref for ref in top_refs)

    def test_search_traditional_still_works(self, searcher: Searcher) -> None:
        """search() tradicional não deve ser afetado por search_with_plan()."""
        results = searcher.search("tudo posso naquele que me fortalece")
        assert len(results) > 0
        assert results[0].book == "Filipenses"
        assert results[0].chapter == 4
        assert results[0].verse == 13

    def test_search_traditional_reference_still_works(self, searcher: Searcher) -> None:
        """Busca por referência não deve ser afetada."""
        results = searcher.search("João 3:16")
        assert len(results) > 0
        assert results[0].book == "João"
        assert results[0].chapter == 3
        assert results[0].verse == 16

    def test_plan_preserves_search_result_fields(self, searcher: Searcher) -> None:
        """SearchResult deve ter todos os campos preenchidos corretamente."""
        plan = QueryPlan(
            original_query="vale da sombra da morte",
            normalized_query="vale da sombra da morte",
            keywords=("vale", "sombra", "morte"),
        )
        results = searcher.search_with_plan(plan)
        assert len(results) > 0
        r = results[0]
        assert r.reference is not None and len(r.reference) > 0
        assert r.book is not None
        assert r.book_id > 0
        assert r.chapter > 0
        assert r.text is not None and len(r.text) > 0
        assert r.version is not None
        assert 0.0 <= r.score <= 1.0
        assert 0.0 <= r.c_search <= 1.0
        assert r.match_type == "hybrid"

    def test_plan_dedup_by_book_chapter_verse(self, searcher: Searcher) -> None:
        """Resultados não devem ter duplicatas (mesmo book:chapter:verse)."""
        plan = QueryPlan(
            original_query="amarás o teu próximo",
            normalized_query="amaras o teu proximo",
            keywords=("amaras", "proximo"),
        )
        results = searcher.search_with_plan(plan)
        refs = [(r.book, r.chapter, r.verse) for r in results]
        assert len(refs) == len(set(refs))  # sem duplicatas


# ---------------------------------------------------------------------------
# Testes de integração: Intent → QueryPlanner → search_with_plan
# ---------------------------------------------------------------------------


class TestIntegrationPlanSearch:
    """Testes de integração: Intent → QueryPlanner → search_with_plan."""

    def test_full_flow_with_enrichment(
        self, searcher: Searcher, planner: QueryPlanner,
    ) -> None:
        """Fluxo completo: Intent com enrichment → plan → search."""
        intent = Intent(
            action="search",
            query="tudo posso naquele que me fortalece",
            confidence=0.9,
            source="llm",
            raw="tudo posso naquele que me fortalece",
            enrichment={
                "keywords": ["posso", "fortalece"],
                "livros_sugeridos": ["Filipenses"],
            },
        )
        plan = planner.plan(intent)
        results = searcher.search_with_plan(plan)
        assert len(results) > 0
        assert results[0].book == "Filipenses"
        assert results[0].chapter == 4
        assert results[0].verse == 13

    def test_full_flow_without_enrichment(
        self, searcher: Searcher, planner: QueryPlanner,
    ) -> None:
        """Fluxo completo: Intent sem enrichment → plan → search."""
        intent = Intent(
            action="search",
            query="vale da sombra da morte",
            confidence=0.8,
            source="parser",
            raw="vale da sombra da morte",
        )
        plan = planner.plan(intent)
        results = searcher.search_with_plan(plan)
        assert len(results) > 0
        assert results[0].book == "Salmos"
