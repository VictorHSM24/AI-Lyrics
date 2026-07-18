"""Testes do QueryPlanner e QueryPlan DTO.

Cobre:
  - QueryPlan: imutabilidade, campos opcionais, defaults
  - QueryPlanner: extração de keywords, stopwords, enrichment do LLM
  - Integração: plan a partir de Intent com/sem enrichment
"""

from __future__ import annotations

import pytest

from busca.query_planner import QueryPlan, QueryPlanner, _normalize, _extract_keywords
from core.types import Intent


# ---------------------------------------------------------------------------
# Testes de QueryPlan (DTO)
# ---------------------------------------------------------------------------


class TestQueryPlanDTO:
    """Testes do DTO QueryPlan."""

    def test_plan_is_frozen(self) -> None:
        plan = QueryPlan(
            original_query="teste",
            normalized_query="teste",
        )
        with pytest.raises(AttributeError):
            plan.original_query = "outro"  # type: ignore[misc]

    def test_defaults(self) -> None:
        plan = QueryPlan(
            original_query="teste",
            normalized_query="teste",
        )
        assert plan.original_query == "teste"
        assert plan.normalized_query == "teste"
        assert plan.keywords == ()
        assert plan.negative_keywords == ()
        assert plan.people == ()
        assert plan.places == ()
        assert plan.events == ()
        assert plan.themes == ()
        assert plan.suggested_books == ()
        assert plan.preferred_versions == ()
        assert plan.search_modes == ("or", "keyword_subset", "fuzzy")
        assert plan.boost_terms == ()
        assert plan.confidence == 0.5

    def test_with_all_fields(self) -> None:
        plan = QueryPlan(
            original_query="Jesus manda lançar a rede",
            normalized_query="jesus manda lancar a rede",
            keywords=("jesus", "rede", "direita"),
            people=("Jesus", "Pedro"),
            events=("pesca milagrosa",),
            suggested_books=("João",),
            search_modes=("or", "keyword_subset", "book_filter", "fuzzy"),
            boost_terms=("lançar", "jogar"),
            confidence=0.9,
        )
        assert plan.keywords == ("jesus", "rede", "direita")
        assert plan.people == ("Jesus", "Pedro")
        assert plan.events == ("pesca milagrosa",)
        assert plan.suggested_books == ("João",)
        assert "book_filter" in plan.search_modes
        assert plan.boost_terms == ("lançar", "jogar")
        assert plan.confidence == 0.9


# ---------------------------------------------------------------------------
# Testes de helpers de normalização
# ---------------------------------------------------------------------------


class TestNormalize:
    """Testes de _normalize e _extract_keywords."""

    def test_normalize_lowercase(self) -> None:
        assert _normalize("TESTE") == "teste"

    def test_normalize_diacritics(self) -> None:
        assert _normalize("João") == "joao"
        assert _normalize("coração") == "coracao"

    def test_normalize_whitespace(self) -> None:
        assert _normalize("a  b   c") == "a b c"

    def test_normalize_empty(self) -> None:
        assert _normalize("") == ""

    def test_extract_keywords_removes_stopwords(self) -> None:
        kws = _extract_keywords("a fé é a certeza das coisas")
        assert "a" not in kws
        assert "e" not in kws  # é → e after normalization
        assert "das" not in kws
        assert "fe" in kws
        assert "certeza" in kws
        assert "coisas" in kws

    def test_extract_keywords_removes_quem(self) -> None:
        kws = _extract_keywords("quem não tiver pecado")
        assert "quem" not in kws
        assert "nao" not in kws
        assert "pecado" in kws

    def test_extract_keywords_empty(self) -> None:
        assert _extract_keywords("") == []
        assert _extract_keywords("a e de") == []


# ---------------------------------------------------------------------------
# Testes de QueryPlanner
# ---------------------------------------------------------------------------


class TestQueryPlanner:
    """Testes do QueryPlanner."""

    def setup_method(self) -> None:
        self.planner = QueryPlanner()

    def test_plan_without_enrichment(self) -> None:
        intent = Intent(
            action="search",
            query="vale da sombra da morte",
            confidence=0.8,
            source="llm",
            raw="vale da sombra da morte",
        )
        plan = self.planner.plan(intent)
        assert plan.original_query == "vale da sombra da morte"
        assert plan.normalized_query == "vale da sombra da morte"
        assert "vale" in plan.keywords
        assert "sombra" in plan.keywords
        assert "morte" in plan.keywords
        assert "da" not in plan.keywords  # stopword
        assert plan.confidence == 0.8
        assert plan.suggested_books == ()

    def test_plan_with_enrichment(self) -> None:
        intent = Intent(
            action="search",
            query="Jesus manda lançar a rede à direita",
            confidence=0.9,
            source="llm",
            raw="Jesus manda lançar a rede à direita",
            enrichment={
                "keywords": ["rede", "direita", "barco"],
                "personagens": ["Jesus"],
                "evento": "pesca milagrosa",
                "livros_sugeridos": ["João"],
                "sinonimos": ["lançar", "jogar"],
            },
        )
        plan = self.planner.plan(intent)
        assert "rede" in plan.keywords
        assert "direita" in plan.keywords
        assert "barco" in plan.keywords
        assert "Jesus" in plan.people
        assert "pesca milagrosa" in plan.events
        assert "João" in plan.suggested_books
        assert "lançar" in plan.boost_terms or "lancar" in plan.boost_terms
        assert "jogar" in plan.boost_terms
        assert "book_filter" in plan.search_modes
        assert plan.confidence == 0.9

    def test_plan_llm_keywords_preferred(self) -> None:
        """Quando LLM fornece keywords, elas devem ser priorizadas."""
        intent = Intent(
            action="search",
            query="quem não tiver pecado",
            confidence=0.9,
            source="llm",
            raw="quem não tiver pecado",
            enrichment={
                "keywords": ["pecado"],
            },
        )
        plan = self.planner.plan(intent)
        # LLM keywords devem estar primeiro
        assert plan.keywords[0] == "pecado"
        # Keywords base não devem incluir stopwords
        assert "quem" not in plan.keywords

    def test_plan_filters_suggested_book_names(self) -> None:
        intent = Intent(
            action="search",
            query="tudo posso naquele que me fortalece",
            confidence=0.9,
            source="llm",
            raw="tudo posso naquele que me fortalece",
            enrichment={
                "livros_sugeridos": ["Filipenses"],
            },
        )
        plan = self.planner.plan(intent)
        assert "suggested_book_names" in plan.filters
        assert "Filipenses" in plan.filters["suggested_book_names"]

    def test_plan_empty_query(self) -> None:
        intent = Intent(
            action="search",
            query="",
            confidence=0.5,
            source="llm",
            raw="",
        )
        plan = self.planner.plan(intent)
        assert plan.original_query == ""
        assert plan.normalized_query == ""
        assert plan.keywords == ()

    def test_plan_none_query_uses_raw(self) -> None:
        intent = Intent(
            action="search",
            query=None,
            confidence=0.5,
            source="llm",
            raw="texto de fallback",
        )
        plan = self.planner.plan(intent)
        assert plan.original_query == "texto de fallback"

    def test_plan_search_modes_without_books(self) -> None:
        intent = Intent(
            action="search",
            query="amor de Deus",
            confidence=0.8,
            source="llm",
            raw="amor de Deus",
        )
        plan = self.planner.plan(intent)
        assert "book_filter" not in plan.search_modes
        assert "or" in plan.search_modes
        assert "keyword_subset" in plan.search_modes
        assert "fuzzy" in plan.search_modes

    def test_plan_search_modes_with_books(self) -> None:
        intent = Intent(
            action="search",
            query="amor de Deus",
            confidence=0.8,
            source="llm",
            raw="amor de Deus",
            enrichment={"livros_sugeridos": ["1 João"]},
        )
        plan = self.planner.plan(intent)
        assert "book_filter" in plan.search_modes

    def test_plan_enrichment_none(self) -> None:
        """Intent sem enrichment não deve quebrar."""
        intent = Intent(
            action="search",
            query="fé",
            confidence=0.7,
            source="parser",
            raw="fé",
        )
        plan = self.planner.plan(intent)
        assert plan.keywords == ("fe",)
        assert plan.suggested_books == ()
        assert plan.boost_terms == ()

    def test_plan_enrichment_empty_dict(self) -> None:
        """Intent com enrichment vazio não deve quebrar."""
        intent = Intent(
            action="search",
            query="fé",
            confidence=0.7,
            source="llm",
            raw="fé",
            enrichment={},
        )
        plan = self.planner.plan(intent)
        assert plan.keywords == ("fe",)

    def test_plan_confidence_from_enrichment(self) -> None:
        intent = Intent(
            action="search",
            query="teste",
            confidence=0.5,
            source="llm",
            raw="teste",
            enrichment={"plan_confidence": 0.95},
        )
        plan = self.planner.plan(intent)
        assert plan.confidence == 0.95
