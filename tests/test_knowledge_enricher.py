"""Testes para KnowledgeEnricher, KnowledgeBase, KnowledgeMatch e integração
com QueryPlanner (FASE 7 — Knowledge Enrichment).

Cobre:
  - KnowledgeMatch DTO (imutabilidade, campos opcionais, is_found).
  - KnowledgeBase (carregamento, find, find_all, aliases, normalização).
  - KnowledgeEnricher (enrich, enrich_all, no-op quando desativado).
  - QueryPlanner com KnowledgeMatch (prioridade KB > LLM > base).
  - 21 consultas conceituais da FASE 10.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, ".")

from busca.knowledge_enricher import (
    KnowledgeBase,
    KnowledgeEnricher,
    KnowledgeMatch,
    _normalize,
)
from busca.query_planner import QueryPlanner
from core.types import Intent


# Caminho para a base de conhecimento real
KB_PATH = os.path.join("config", "knowledge_base.json")


# ---------------------------------------------------------------------------
# KnowledgeMatch DTO
# ---------------------------------------------------------------------------


class TestKnowledgeMatch(unittest.TestCase):
    """Testes do KnowledgeMatch DTO."""

    def test_default_empty_match(self):
        """KnowledgeMatch vazio tem is_found=False."""
        m = KnowledgeMatch()
        self.assertFalse(m.is_found)
        self.assertEqual(m.concept, "")
        self.assertEqual(m.confidence, 0.0)
        self.assertEqual(m.books, ())
        self.assertEqual(m.chapters, ())

    def test_frozen_immutability(self):
        """KnowledgeMatch é frozen — não pode ser modificado."""
        m = KnowledgeMatch(concept="filho pródigo", confidence=0.95)
        with self.assertRaises(Exception):
            m.concept = "bom pastor"  # type: ignore

    def test_is_found_true_when_concept_and_confidence(self):
        """is_found=True quando concept não-vazio e confidence > 0."""
        m = KnowledgeMatch(concept="filho pródigo", confidence=0.95)
        self.assertTrue(m.is_found)

    def test_is_found_false_when_zero_confidence(self):
        """is_found=False quando confidence=0 mesmo com concept."""
        m = KnowledgeMatch(concept="filho pródigo", confidence=0.0)
        self.assertFalse(m.is_found)

    def test_all_optional_fields(self):
        """Todos os campos são opcionais e têm defaults."""
        m = KnowledgeMatch(
            concept="bom pastor",
            aliases=("o bom pastor",),
            books=("João",),
            chapters=(10,),
            characters=("Jesus",),
            events=("parábola do bom pastor",),
            themes=("Jesus", "ovelhas"),
            keywords=("pastor", "ovelhas"),
            boost_terms=("bom pastor",),
            confidence=0.95,
            matched_alias="bom pastor",
        )
        self.assertEqual(m.concept, "bom pastor")
        self.assertEqual(m.aliases, ("o bom pastor",))
        self.assertEqual(m.books, ("João",))
        self.assertEqual(m.chapters, (10,))
        self.assertEqual(m.characters, ("Jesus",))
        self.assertEqual(m.events, ("parábola do bom pastor",))
        self.assertEqual(m.themes, ("Jesus", "ovelhas"))
        self.assertEqual(m.keywords, ("pastor", "ovelhas"))
        self.assertEqual(m.boost_terms, ("bom pastor",))
        self.assertEqual(m.confidence, 0.95)
        self.assertEqual(m.matched_alias, "bom pastor")


# ---------------------------------------------------------------------------
# KnowledgeBase
# ---------------------------------------------------------------------------


class TestKnowledgeBase(unittest.TestCase):
    """Testes do KnowledgeBase (carregamento e busca)."""

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase(KB_PATH)

    def test_loads_successfully(self):
        """Base carrega sem erro."""
        self.assertTrue(self.kb.is_loaded)
        self.assertGreater(self.kb.size, 20)

    def test_file_not_found_warning(self):
        """Base com arquivo inexistente não carrega mas não erro."""
        kb = KnowledgeBase("/nonexistent/path.json")
        self.assertFalse(kb.is_loaded)
        self.assertEqual(kb.size, 0)

    def test_find_filho_prodigo(self):
        """find('filho pródigo') retorna conceito correto."""
        entry = self.kb.find("filho pródigo")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.concept, "filho pródigo")
        self.assertIn("Lucas", entry.books)
        self.assertIn(15, entry.chapters)

    def test_find_with_alias(self):
        """find com alias retorna conceito correto."""
        entry = self.kb.find("filho perdido")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.concept, "filho pródigo")

    def test_find_bom_pastor(self):
        """find('bom pastor') retorna conceito correto."""
        entry = self.kb.find("bom pastor")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.concept, "bom pastor")
        self.assertIn("João", entry.books)
        self.assertIn(10, entry.chapters)

    def test_find_no_match(self):
        """find com query que não matcha retorna None."""
        entry = self.kb.find("receita de bolo")
        self.assertIsNone(entry)

    def test_find_empty_query(self):
        """find com query vazia retorna None."""
        self.assertIsNone(self.kb.find(""))
        self.assertIsNone(self.kb.find("   "))

    def test_find_case_insensitive(self):
        """find é case-insensitive."""
        entry_lower = self.kb.find("filho pródigo")
        entry_upper = self.kb.find("FILHO PRÓDIGO")
        entry_mixed = self.kb.find("Filho Pródigo")
        self.assertIsNotNone(entry_lower)
        self.assertIsNotNone(entry_upper)
        self.assertIsNotNone(entry_mixed)
        self.assertEqual(entry_lower.concept, entry_upper.concept)
        self.assertEqual(entry_lower.concept, entry_mixed.concept)

    def test_find_with_accents_normalized(self):
        """find normaliza acentos."""
        entry_with_accents = self.kb.find("filho pródigo")
        entry_without_accents = self.kb.find("filho prodigo")
        self.assertIsNotNone(entry_with_accents)
        self.assertIsNotNone(entry_without_accents)
        self.assertEqual(entry_with_accents.concept, entry_without_accents.concept)

    def test_find_partial_query(self):
        """find com query que contém o conceito como substring."""
        entry = self.kb.find("me fale sobre o filho pródigo")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.concept, "filho pródigo")

    def test_find_all_multiple_matches(self):
        """find_all retorna múltiplos conceitos quando aplicável."""
        # "Elias no monte Carmelo" pode matchar tanto "profeta Elias"
        # quanto "monte Carmelo"
        entries = self.kb.find_all("Elias no monte Carmelo")
        self.assertGreaterEqual(len(entries), 1)
        concepts = [e.concept for e in entries]
        # Pelo menos um dos dois deve estar presente
        self.assertTrue(
            "profeta elias" in concepts or "monte carmelo" in concepts,
            f"Expected Elias or Carmelo in {concepts}",
        )

    def test_find_all_empty_query(self):
        """find_all com query vazia retorna lista vazia."""
        self.assertEqual(self.kb.find_all(""), [])

    def test_find_most_specific_alias(self):
        """find prefere alias mais longo (mais específico)."""
        # "parábola do filho pródigo" é mais específico que "filho pródigo"
        entry = self.kb.find("parábola do filho pródigo")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.concept, "filho pródigo")


# ---------------------------------------------------------------------------
# KnowledgeEnricher
# ---------------------------------------------------------------------------


class TestKnowledgeEnricher(unittest.TestCase):
    """Testes do KnowledgeEnricher."""

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase(KB_PATH)
        cls.enricher = KnowledgeEnricher(cls.kb)

    def _make_intent(self, query: str) -> Intent:
        return Intent(action="search", query=query, confidence=0.8, source="llm", raw=query)

    def test_enrich_filho_prodigo(self):
        """enrich('filho pródigo') retorna KnowledgeMatch correto."""
        intent = self._make_intent("filho pródigo")
        match = self.enricher.enrich(intent)
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "filho pródigo")
        self.assertIn("Lucas", match.books)
        self.assertIn(15, match.chapters)
        self.assertGreater(match.confidence, 0.0)

    def test_enrich_bom_pastor(self):
        """enrich('bom pastor') retorna KnowledgeMatch correto."""
        intent = self._make_intent("bom pastor")
        match = self.enricher.enrich(intent)
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "bom pastor")
        self.assertIn("João", match.books)

    def test_enrich_no_match(self):
        """enrich com query que não matcha retorna KnowledgeMatch vazio."""
        intent = self._make_intent("receita de bolo")
        match = self.enricher.enrich(intent)
        self.assertFalse(match.is_found)
        self.assertEqual(match.concept, "")

    def test_enrich_with_alias(self):
        """enrich com alias retorna conceito correto."""
        intent = self._make_intent("filho perdido")
        match = self.enricher.enrich(intent)
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "filho pródigo")

    def test_enrich_empty_intent(self):
        """enrich com Intent vazio retorna KnowledgeMatch vazio."""
        intent = Intent(action="search", query="", confidence=0.8, source="llm", raw="")
        match = self.enricher.enrich(intent)
        self.assertFalse(match.is_found)

    def test_enrich_falls_back_to_raw(self):
        """enrich usa intent.raw quando intent.query é None."""
        intent = Intent(action="search", query=None, confidence=0.8, source="llm", raw="bom pastor")
        match = self.enricher.enrich(intent)
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "bom pastor")

    def test_enrich_all_returns_list(self):
        """enrich_all retorna lista de KnowledgeMatch."""
        intent = self._make_intent("Elias no monte Carmelo")
        matches = self.enricher.enrich_all(intent)
        self.assertIsInstance(matches, list)
        self.assertGreaterEqual(len(matches), 1)
        for m in matches:
            self.assertTrue(m.is_found)

    def test_enrich_all_empty_returns_empty_list(self):
        """enrich_all com query que não matcha retorna lista vazia."""
        intent = self._make_intent("receita de bolo")
        matches = self.enricher.enrich_all(intent)
        self.assertEqual(matches, [])

    def test_enricher_without_base_is_noop(self):
        """KnowledgeEnricher sem base é no-op."""
        enricher = KnowledgeEnricher(None)
        intent = self._make_intent("filho pródigo")
        match = enricher.enrich(intent)
        self.assertFalse(match.is_found)
        self.assertFalse(enricher.is_available)

    def test_enricher_with_empty_base_is_noop(self):
        """KnowledgeEnricher com base vazia é no-op."""
        kb = KnowledgeBase("/nonexistent/path.json")
        enricher = KnowledgeEnricher(kb)
        intent = self._make_intent("filho pródigo")
        match = enricher.enrich(intent)
        self.assertFalse(match.is_found)
        self.assertFalse(enricher.is_available)

    def test_enrich_matched_alias(self):
        """enrich preenche matched_alias com o alias que matchou."""
        intent = self._make_intent("filho perdido")
        match = self.enricher.enrich(intent)
        self.assertTrue(match.is_found)
        self.assertEqual(match.matched_alias, "filho perdido")

    def test_enrich_does_not_modify_intent(self):
        """enrich não modifica o Intent."""
        intent = self._make_intent("filho pródigo")
        original_query = intent.query
        original_enrichment = intent.enrichment
        _ = self.enricher.enrich(intent)
        self.assertEqual(intent.query, original_query)
        self.assertEqual(intent.enrichment, original_enrichment)


# ---------------------------------------------------------------------------
# QueryPlanner com KnowledgeMatch
# ---------------------------------------------------------------------------


class TestQueryPlannerWithKnowledge(unittest.TestCase):
    """Testes do QueryPlanner consumindo KnowledgeMatch."""

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase(KB_PATH)
        cls.enricher = KnowledgeEnricher(cls.kb)
        cls.planner = QueryPlanner()

    def _make_intent(self, query: str, enrichment: dict | None = None) -> Intent:
        return Intent(
            action="search",
            query=query,
            confidence=0.8,
            source="llm",
            raw=query,
            enrichment=enrichment,
        )

    def test_plan_without_knowledge_uses_base_extraction(self):
        """plan sem KnowledgeMatch usa extração base (compatibilidade)."""
        intent = self._make_intent("amor ao próximo")
        plan = self.planner.plan(intent, knowledge=None)
        self.assertGreater(len(plan.keywords), 0)
        self.assertIn("amor", plan.keywords)

    def test_plan_with_knowledge_adds_books(self):
        """plan com KnowledgeMatch adiciona livros sugeridos."""
        intent = self._make_intent("filho pródigo")
        match = self.enricher.enrich(intent)
        plan = self.planner.plan(intent, knowledge=match)
        # KB books são normalizados para lowercase pelo _merge_unique
        self.assertIn("lucas", [b.lower() for b in plan.suggested_books])
        self.assertIn("book_filter", plan.search_modes)

    def test_plan_with_knowledge_adds_keywords(self):
        """plan com KnowledgeMatch adiciona keywords do conceito."""
        intent = self._make_intent("filho pródigo")
        match = self.enricher.enrich(intent)
        plan = self.planner.plan(intent, knowledge=match)
        # Keywords do conceito "filho pródigo"
        self.assertIn("pai", plan.keywords)
        self.assertIn("filho", plan.keywords)

    def test_plan_with_knowledge_adds_boost_terms(self):
        """plan com KnowledgeMatch adiciona boost_terms."""
        intent = self._make_intent("filho pródigo")
        match = self.enricher.enrich(intent)
        plan = self.planner.plan(intent, knowledge=match)
        self.assertGreater(len(plan.boost_terms), 0)

    def test_plan_with_knowledge_adds_chapters_to_filters(self):
        """plan com KnowledgeMatch adiciona chapters aos filters."""
        intent = self._make_intent("filho pródigo")
        match = self.enricher.enrich(intent)
        plan = self.planner.plan(intent, knowledge=match)
        self.assertIn("suggested_chapters", plan.filters)
        self.assertIn(15, plan.filters["suggested_chapters"])

    def test_plan_knowledge_overrides_llm_books(self):
        """Knowledge tem prioridade sobre LLM para livros sugeridos."""
        # LLM sugere Mateus, mas Knowledge diz Lucas
        intent = self._make_intent(
            "filho pródigo",
            enrichment={"livros_sugeridos": ["Mateus"]},
        )
        match = self.enricher.enrich(intent)
        plan = self.planner.plan(intent, knowledge=match)
        # Knowledge tem prioridade — Lucas deve aparecer
        self.assertIn("lucas", [b.lower() for b in plan.suggested_books])

    def test_plan_knowledge_merges_with_llm_keywords(self):
        """Knowledge keywords são mergeadas com LLM keywords."""
        intent = self._make_intent(
            "filho pródigo",
            enrichment={"keywords": ["parábola", "jesus"]},
        )
        match = self.enricher.enrich(intent)
        plan = self.planner.plan(intent, knowledge=match)
        # Tanto keywords do LLM quanto do Knowledge devem estar presentes
        keywords_lower = [k.lower() for k in plan.keywords]
        self.assertIn("parabola", keywords_lower)  # do LLM
        self.assertIn("pai", keywords_lower)  # do Knowledge

    def test_plan_knowledge_confidence_used(self):
        """plan usa confidence do KnowledgeMatch quando disponível."""
        intent = self._make_intent("filho pródigo")
        match = self.enricher.enrich(intent)
        plan = self.planner.plan(intent, knowledge=match)
        self.assertEqual(plan.confidence, match.confidence)

    def test_plan_without_knowledge_preserves_llm_capitalization(self):
        """plan sem KnowledgeMatch preserva capitalização do LLM (compat)."""
        intent = self._make_intent(
            "Jesus manda lançar a rede",
            enrichment={"personagens": ["Jesus"], "livros_sugeridos": ["João"]},
        )
        plan = self.planner.plan(intent, knowledge=None)
        # Preserva capitalização original do LLM
        self.assertIn("Jesus", plan.people)
        self.assertIn("João", plan.suggested_books)

    def test_plan_with_empty_knowledge_match(self):
        """plan com KnowledgeMatch vazio (is_found=False) funciona como sem KB."""
        intent = self._make_intent("amor ao próximo")
        match = KnowledgeMatch()  # vazio
        plan = self.planner.plan(intent, knowledge=match)
        # Deve funcionar como se não houvesse knowledge
        self.assertGreater(len(plan.keywords), 0)


# ---------------------------------------------------------------------------
# FASE 10 — 21 consultas conceituais
# ---------------------------------------------------------------------------


class TestConceptualQueries(unittest.TestCase):
    """21 consultas conceituais que demonstram enriquecimento.

    Cada teste verifica que o QueryPlanner recebeu enriquecimento
    adicional do KnowledgeEnricher.
    """

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase(KB_PATH)
        cls.enricher = KnowledgeEnricher(cls.kb)
        cls.planner = QueryPlanner()

    def _enrich_and_plan(self, query: str):
        intent = Intent(action="search", query=query, confidence=0.8, source="llm", raw=query)
        match = self.enricher.enrich(intent)
        plan = self.planner.plan(intent, knowledge=match)
        return match, plan

    def test_filho_prodigo(self):
        """'filho pródigo' → Lucas 15."""
        match, plan = self._enrich_and_plan("filho pródigo")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "filho pródigo")
        self.assertIn("lucas", [b.lower() for b in plan.suggested_books])
        self.assertIn(15, plan.filters.get("suggested_chapters", []))

    def test_jovem_rico(self):
        """'jovem rico' → Mateus 19, Marcos 10, Lucas 18."""
        match, plan = self._enrich_and_plan("jovem rico")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "jovem rico")
        books_lower = [b.lower() for b in plan.suggested_books]
        self.assertIn("mateus", books_lower)

    def test_bom_pastor(self):
        """'bom pastor' → João 10."""
        match, plan = self._enrich_and_plan("bom pastor")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "bom pastor")
        self.assertIn("joao", [b.lower() for b in plan.suggested_books])

    def test_mulher_samaritana(self):
        """'mulher samaritana' → João 4."""
        match, plan = self._enrich_and_plan("mulher samaritana")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "mulher samaritana")
        self.assertIn("joao", [b.lower() for b in plan.suggested_books])

    def test_pedro_andando_sobre_aguas(self):
        """'Pedro andando sobre as águas' → Mateus 14."""
        match, plan = self._enrich_and_plan("Pedro andando sobre as águas")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "pedro anda sobre as águas")
        books_lower = [b.lower() for b in plan.suggested_books]
        self.assertIn("mateus", books_lower)

    def test_escada_de_jaco(self):
        """'escada de Jacó' → Gênesis 28."""
        match, plan = self._enrich_and_plan("escada de Jacó")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "escada de jacó")
        self.assertIn("genesis", [b.lower() for b in plan.suggested_books])

    def test_vale_ossos_secos(self):
        """'vale de ossos secos' → Ezequiel 37."""
        match, plan = self._enrich_and_plan("vale de ossos secos")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "vale de ossos secos")
        self.assertIn("ezequiel", [b.lower() for b in plan.suggested_books])

    def test_sarca_ardente(self):
        """'sarça ardente' → Êxodo 3."""
        match, plan = self._enrich_and_plan("sarça ardente")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "sarça ardente")
        self.assertIn("exodo", [b.lower() for b in plan.suggested_books])

    def test_fruto_do_espirito(self):
        """'fruto do Espírito' → Gálatas 5."""
        match, plan = self._enrich_and_plan("fruto do Espírito")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "fruto do espírito")
        self.assertIn("galatas", [b.lower() for b in plan.suggested_books])

    def test_armadura_de_deus(self):
        """'armadura de Deus' → Efésios 6."""
        match, plan = self._enrich_and_plan("armadura de Deus")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "armadura de deus")
        self.assertIn("efesios", [b.lower() for b in plan.suggested_books])

    def test_bom_samaritano(self):
        """'bom samaritano' → Lucas 10."""
        match, plan = self._enrich_and_plan("bom samaritano")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "bom samaritano")
        self.assertIn("lucas", [b.lower() for b in plan.suggested_books])

    def test_rei_davi(self):
        """'rei Davi' → 1 Samuel, 2 Samuel, Salmos."""
        match, plan = self._enrich_and_plan("rei Davi")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "rei davi")

    def test_rainha_ester(self):
        """'rainha Ester' → Ester."""
        match, plan = self._enrich_and_plan("rainha Ester")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "rainha ester")
        self.assertIn("ester", [b.lower() for b in plan.suggested_books])

    def test_profeta_elias(self):
        """'profeta Elias' → 1 Reis, 2 Reis."""
        match, plan = self._enrich_and_plan("profeta Elias")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "profeta elias")

    def test_monte_carmelo(self):
        """'Monte Carmelo' → 1 Reis 18."""
        match, plan = self._enrich_and_plan("Monte Carmelo")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "monte carmelo")
        self.assertIn("1 reis", [b.lower() for b in plan.suggested_books])

    def test_monte_sinai(self):
        """'Monte Sinai' → Êxodo 19."""
        match, plan = self._enrich_and_plan("Monte Sinai")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "monte sinai")
        self.assertIn("exodo", [b.lower() for b in plan.suggested_books])

    def test_mar_vermelho(self):
        """'mar vermelho' → Êxodo 14."""
        match, plan = self._enrich_and_plan("mar vermelho")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "mar vermelho")
        self.assertIn("exodo", [b.lower() for b in plan.suggested_books])

    def test_ladrao_na_cruz(self):
        """'ladrão na cruz' → Lucas 23."""
        match, plan = self._enrich_and_plan("ladrão na cruz")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "ladrão na cruz")
        books_lower = [b.lower() for b in plan.suggested_books]
        self.assertIn("lucas", books_lower)

    def test_dez_virgens(self):
        """'parábola das dez virgens' → Mateus 25."""
        match, plan = self._enrich_and_plan("parábola das dez virgens")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "parábola das dez virgens")
        self.assertIn("mateus", [b.lower() for b in plan.suggested_books])

    def test_pedra_angular(self):
        """'pedra angular' → Salmos, Isaías, Efésios, 1 Pedro."""
        match, plan = self._enrich_and_plan("pedra angular")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "pedra angular")

    def test_videira_verdadeira(self):
        """'videira verdadeira' → João 15."""
        match, plan = self._enrich_and_plan("videira verdadeira")
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "videira verdadeira")
        self.assertIn("joao", [b.lower() for b in plan.suggested_books])


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestNormalize(unittest.TestCase):
    """Testes da função _normalize."""

    def test_lowercase(self):
        self.assertEqual(_normalize("FILHO"), "filho")

    def test_remove_accents(self):
        self.assertEqual(_normalize("pródigo"), "prodigo")
        self.assertEqual(_normalize("João"), "joao")
        self.assertEqual(_normalize("Êxodo"), "exodo")

    def test_collapse_whitespace(self):
        self.assertEqual(_normalize("filho   pródigo"), "filho prodigo")

    def test_strip(self):
        self.assertEqual(_normalize("  filho  "), "filho")

    def test_empty(self):
        self.assertEqual(_normalize(""), "")


if __name__ == "__main__":
    unittest.main()
