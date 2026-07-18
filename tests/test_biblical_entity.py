"""Testes para BiblicalEntity, BiblicalEntityType, e grafo de conhecimento.

Cobre a FASE 7.5 — Biblical Knowledge Graph:
  - BiblicalEntityType enum (valores, from_string, extensibilidade).
  - BiblicalEntity DTO (imutabilidade, campos opcionais, to_entity).
  - KnowledgeBase com grafo (get_entity, get_related_entities, all_entities).
  - KnowledgeMatch com novos campos (entity_id, entity_type, related, places).
  - QueryPlan com novos campos (entity_id, entity_type, related).
  - Compatibilidade: todos os conceitos antigos continuam funcionando.
  - Relacionamentos coerentes entre conceitos.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, ".")

from busca.biblical_entity import BiblicalEntity, BiblicalEntityType
from busca.bible_reference import BibleBook, BibleReference, parse_bible_reference
from busca.knowledge_enricher import KnowledgeBase, KnowledgeEnricher, KnowledgeMatch
from busca.query_planner import QueryPlanner
from core.types import Intent


KB_PATH = os.path.join("config", "knowledge_base.json")


# ---------------------------------------------------------------------------
# BiblicalEntityType
# ---------------------------------------------------------------------------


class TestBiblicalEntityType(unittest.TestCase):
    """Testes do enum BiblicalEntityType."""

    def test_all_expected_types_exist(self):
        """Todos os tipos esperados estão presentes."""
        self.assertEqual(BiblicalEntityType.PERSON.value, "PERSON")
        self.assertEqual(BiblicalEntityType.PLACE.value, "PLACE")
        self.assertEqual(BiblicalEntityType.EVENT.value, "EVENT")
        self.assertEqual(BiblicalEntityType.PARABLE.value, "PARABLE")
        self.assertEqual(BiblicalEntityType.MIRACLE.value, "MIRACLE")
        self.assertEqual(BiblicalEntityType.PROPHECY.value, "PROPHECY")
        self.assertEqual(BiblicalEntityType.THEME.value, "THEME")
        self.assertEqual(BiblicalEntityType.OBJECT.value, "OBJECT")
        self.assertEqual(BiblicalEntityType.SYMBOL.value, "SYMBOL")
        self.assertEqual(BiblicalEntityType.DOCTRINE.value, "DOCTRINE")
        self.assertEqual(BiblicalEntityType.METAPHOR.value, "METAPHOR")
        self.assertEqual(BiblicalEntityType.OUTRO.value, "OUTRO")

    def test_from_string_valid(self):
        """from_string converte strings válidas."""
        self.assertEqual(BiblicalEntityType.from_string("PARABLE"), BiblicalEntityType.PARABLE)
        self.assertEqual(BiblicalEntityType.from_string("MIRACLE"), BiblicalEntityType.MIRACLE)
        self.assertEqual(BiblicalEntityType.from_string("PERSON"), BiblicalEntityType.PERSON)

    def test_from_string_case_insensitive(self):
        """from_string é case-insensitive."""
        self.assertEqual(BiblicalEntityType.from_string("parable"), BiblicalEntityType.PARABLE)
        self.assertEqual(BiblicalEntityType.from_string("Miracle"), BiblicalEntityType.MIRACLE)

    def test_from_string_invalid_returns_outro(self):
        """from_string retorna OUTRO para tipos desconhecidos."""
        self.assertEqual(BiblicalEntityType.from_string("UNKNOWN"), BiblicalEntityType.OUTRO)
        self.assertEqual(BiblicalEntityType.from_string("xyz"), BiblicalEntityType.OUTRO)

    def test_from_string_empty_returns_outro(self):
        """from_string retorna OUTRO para string vazia."""
        self.assertEqual(BiblicalEntityType.from_string(""), BiblicalEntityType.OUTRO)
        self.assertEqual(BiblicalEntityType.from_string("  "), BiblicalEntityType.OUTRO)

    def test_str_enum_compatibility(self):
        """BiblicalEntityType é str enum — compara com strings."""
        self.assertEqual(BiblicalEntityType.PARABLE, "PARABLE")
        self.assertEqual(BiblicalEntityType.MIRACLE, "MIRACLE")

    def test_extensibility_new_type(self):
        """Novos tipos podem ser adicionados sem quebrar código existente."""
        # Todos os membros existentes continuam acessíveis
        for member in BiblicalEntityType:
            self.assertIsNotNone(member.value)


# ---------------------------------------------------------------------------
# BiblicalEntity
# ---------------------------------------------------------------------------


class TestBiblicalEntity(unittest.TestCase):
    """Testes do BiblicalEntity DTO."""

    def test_frozen_immutability(self):
        """BiblicalEntity é frozen — não pode ser modificado."""
        entity = BiblicalEntity(
            id="filho_prodigo",
            name="filho pródigo",
            type=BiblicalEntityType.PARABLE,
        )
        with self.assertRaises(Exception):
            entity.id = "bom_pastor"  # type: ignore

    def test_required_fields(self):
        """id, name, type são os campos principais."""
        entity = BiblicalEntity(
            id="filho_prodigo",
            name="filho pródigo",
            type=BiblicalEntityType.PARABLE,
        )
        self.assertEqual(entity.id, "filho_prodigo")
        self.assertEqual(entity.name, "filho pródigo")
        self.assertEqual(entity.type, BiblicalEntityType.PARABLE)

    def test_all_optional_fields_default(self):
        """Todos os outros campos são opcionais com defaults."""
        entity = BiblicalEntity(
            id="test",
            name="test",
            type=BiblicalEntityType.OUTRO,
        )
        self.assertEqual(entity.aliases, ())
        self.assertEqual(entity.books, ())
        self.assertEqual(entity.chapters, ())
        self.assertEqual(entity.characters, ())
        self.assertEqual(entity.places, ())
        self.assertEqual(entity.events, ())
        self.assertEqual(entity.themes, ())
        self.assertEqual(entity.keywords, ())
        self.assertEqual(entity.boost_terms, ())
        self.assertEqual(entity.related, ())
        self.assertEqual(entity.references, ())
        self.assertEqual(entity.metadata, {})
        self.assertEqual(entity.confidence, 0.9)

    def test_all_fields_set(self):
        """Todos os campos podem ser preenchidos."""
        entity = BiblicalEntity(
            id="filho_prodigo",
            name="filho pródigo",
            type=BiblicalEntityType.PARABLE,
            aliases=("filho perdido",),
            books=("Lucas",),
            chapters=(15,),
            characters=("pai", "filho"),
            places=("Betânia",),
            events=("parábola do filho pródigo",),
            themes=("arrependimento",),
            keywords=("filho", "perdido"),
            boost_terms=("pródigo",),
            related=("bom_pastor",),
            references=(BibleReference.from_string("Lucas 15:11-32"),),
            metadata={"key": "value"},
            confidence=0.95,
        )
        self.assertEqual(entity.aliases, ("filho perdido",))
        self.assertEqual(entity.places, ("Betânia",))
        self.assertEqual(entity.related, ("bom_pastor",))
        self.assertEqual(len(entity.references), 1)
        self.assertEqual(entity.references[0].to_string(), "Lucas 15:11-32")
        self.assertEqual(entity.metadata, {"key": "value"})

    def test_related_count(self):
        """related_count retorna número de relacionados."""
        entity = BiblicalEntity(
            id="test",
            name="test",
            type=BiblicalEntityType.OUTRO,
            related=("a", "b", "c"),
        )
        self.assertEqual(entity.related_count, 3)

    def test_related_count_zero(self):
        """related_count é 0 quando não há relacionados."""
        entity = BiblicalEntity(id="test", name="test", type=BiblicalEntityType.OUTRO)
        self.assertEqual(entity.related_count, 0)


# ---------------------------------------------------------------------------
# KnowledgeBase — Grafo
# ---------------------------------------------------------------------------


class TestKnowledgeBaseGraph(unittest.TestCase):
    """Testes do KnowledgeBase como grafo de conhecimento."""

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase(KB_PATH)

    def test_all_entries_have_id(self):
        """Todas as entradas têm entity_id (gerado ou explícito)."""
        for entry in self.kb.all_entities():
            self.assertTrue(entry.id, f"Entity without id: {entry.name}")

    def test_all_entries_have_type(self):
        """Todas as entradas têm type definido."""
        for entry in self.kb.all_entities():
            self.assertIsInstance(entry.type, BiblicalEntityType)

    def test_get_entity_by_id(self):
        """get_entity recupera entidade pelo ID."""
        entity = self.kb.get_entity("filho_prodigo")
        self.assertIsNotNone(entity)
        self.assertEqual(entity.id, "filho_prodigo")
        self.assertEqual(entity.type, BiblicalEntityType.PARABLE)

    def test_get_entity_not_found(self):
        """get_entity retorna None para ID inexistente."""
        self.assertIsNone(self.kb.get_entity("nonexistent_id"))

    def test_get_related_entities(self):
        """get_related_entities recupera entidades relacionadas."""
        related = self.kb.get_related_entities("filho_prodigo")
        # filho_prodigo está relacionado com bom_pastor, bom_samaritano, dracma_perdida
        ids = [e.id for e in related]
        self.assertIn("bom_pastor", ids)
        self.assertIn("bom_samaritano", ids)

    def test_get_related_entities_empty(self):
        """get_related_entities retorna lista vazia se sem relacionados."""
        # Criar uma KB temporária com um conceito sem related
        import tempfile, json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"concepts": [{"name": "test", "aliases": [], "books": [], "chapters": []}]}, f)
            tmp_path = f.name
        try:
            kb = KnowledgeBase(tmp_path)
            self.assertEqual(kb.get_related_entities("test"), [])
        finally:
            os.unlink(tmp_path)

    def test_get_related_entities_nonexistent(self):
        """get_related_entities retorna vazio para ID inexistente."""
        self.assertEqual(self.kb.get_related_entities("nonexistent"), [])

    def test_all_entities(self):
        """all_entities retorna lista de BiblicalEntity."""
        entities = self.kb.all_entities()
        self.assertEqual(len(entities), self.kb.size)
        for e in entities:
            self.assertIsInstance(e, BiblicalEntity)

    def test_total_relationships_positive(self):
        """total_relationships é positivo (há relacionamentos)."""
        self.assertGreater(self.kb.total_relationships, 0)

    def test_relationships_are_bidirectional_or_documented(self):
        """Relacionamentos principais são coerentes (não necessariamente bidirecionais)."""
        # filho_prodigo → bom_pastor
        filho = self.kb.get_entity("filho_prodigo")
        self.assertIn("bom_pastor", filho.related)
        # bom_pastor → filho_prodigo (bidirecional)
        pastor = self.kb.get_entity("bom_pastor")
        self.assertIn("filho_prodigo", pastor.related)

    def test_34_concepts_loaded(self):
        """Base carrega 34 conceitos."""
        self.assertEqual(self.kb.size, 34)

    def test_86_relationships(self):
        """Total de relacionamentos é 86."""
        self.assertEqual(self.kb.total_relationships, 86)

    def test_average_relationships_per_entity(self):
        """Média de relacionamentos por entidade é ~2.5."""
        avg = self.kb.total_relationships / self.kb.size
        self.assertGreater(avg, 1.5)
        self.assertLess(avg, 4.0)

    def test_entity_types_distribution(self):
        """Distribuição de tipos cobre múltiplos tipos."""
        entities = self.kb.all_entities()
        types = set(e.type for e in entities)
        # Pelo menos 5 tipos diferentes
        self.assertGreaterEqual(len(types), 5)

    def test_parables_have_type_parable(self):
        """Parábolas têm type=PARABLE."""
        for eid in ["filho_prodigo", "bom_samaritano", "dez_virgens"]:
            entity = self.kb.get_entity(eid)
            self.assertEqual(entity.type, BiblicalEntityType.PARABLE,
                             f"{eid} should be PARABLE")

    def test_miracles_have_type_miracle(self):
        """Milagres têm type=MIRACLE."""
        for eid in ["pesca_milagrosa", "pedro_anda_sobre_aguas", "multiplicacao_paes", "mar_vermelho", "lazaro"]:
            entity = self.kb.get_entity(eid)
            self.assertEqual(entity.type, BiblicalEntityType.MIRACLE,
                             f"{eid} should be MIRACLE")

    def test_persons_have_type_person(self):
        """Pessoas têm type=PERSON."""
        for eid in ["rei_davi", "rainha_ester", "profeta_elias", "rainha_de_saba"]:
            entity = self.kb.get_entity(eid)
            self.assertEqual(entity.type, BiblicalEntityType.PERSON,
                             f"{eid} should be PERSON")

    def test_places_have_type_place(self):
        """Lugares têm type=PLACE."""
        entity = self.kb.get_entity("monte_sinai")
        self.assertEqual(entity.type, BiblicalEntityType.PLACE)

    def test_references_populated(self):
        """Entidades têm references estruturadas como BibleReference."""
        entity = self.kb.get_entity("filho_prodigo")
        self.assertGreater(len(entity.references), 0)
        ref = entity.references[0]
        # references são BibleReference (FASE 7.6)
        from busca.bible_reference import BibleReference
        self.assertIsInstance(ref, BibleReference)
        self.assertIn("Lucas 15", ref.to_string())

    def test_places_populated(self):
        """Algumas entidades têm places."""
        entity = self.kb.get_entity("mulher_samaritana")
        self.assertGreater(len(entity.places), 0)
        places_lower = [p.lower() for p in entity.places]
        self.assertIn("sicar", places_lower)


# ---------------------------------------------------------------------------
# KnowledgeMatch — novos campos do grafo
# ---------------------------------------------------------------------------


class TestKnowledgeMatchGraphFields(unittest.TestCase):
    """Testes dos novos campos do KnowledgeMatch (FASE 7.5)."""

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase(KB_PATH)
        cls.enricher = KnowledgeEnricher(cls.kb)

    def _make_intent(self, query: str) -> Intent:
        return Intent(action="search", query=query, confidence=0.8, source="llm", raw=query)

    def test_entity_id_populated(self):
        """enrich preenche entity_id."""
        match = self.enricher.enrich(self._make_intent("filho pródigo"))
        self.assertTrue(match.is_found)
        self.assertEqual(match.entity_id, "filho_prodigo")

    def test_entity_type_populated(self):
        """enrich preenche entity_type."""
        match = self.enricher.enrich(self._make_intent("filho pródigo"))
        self.assertTrue(match.is_found)
        self.assertEqual(match.entity_type, BiblicalEntityType.PARABLE)

    def test_related_populated(self):
        """enrich preenche related."""
        match = self.enricher.enrich(self._make_intent("filho pródigo"))
        self.assertTrue(match.is_found)
        self.assertIn("bom_pastor", match.related)

    def test_references_populated(self):
        """enrich preenche references."""
        match = self.enricher.enrich(self._make_intent("filho pródigo"))
        self.assertTrue(match.is_found)
        self.assertGreater(len(match.references), 0)

    def test_places_populated(self):
        """enrich preenche places quando disponível."""
        match = self.enricher.enrich(self._make_intent("mulher samaritana"))
        self.assertTrue(match.is_found)
        self.assertGreater(len(match.places), 0)

    def test_entity_type_miracle(self):
        """enrich identifica type=MIRACLE para milagres."""
        match = self.enricher.enrich(self._make_intent("pesca milagrosa"))
        self.assertTrue(match.is_found)
        self.assertEqual(match.entity_type, BiblicalEntityType.MIRACLE)

    def test_entity_type_person(self):
        """enrich identifica type=PERSON para pessoas."""
        match = self.enricher.enrich(self._make_intent("rei Davi"))
        self.assertTrue(match.is_found)
        self.assertEqual(match.entity_type, BiblicalEntityType.PERSON)

    def test_entity_type_place(self):
        """enrich identifica type=PLACE para lugares."""
        match = self.enricher.enrich(self._make_intent("Monte Sinai"))
        self.assertTrue(match.is_found)
        self.assertEqual(match.entity_type, BiblicalEntityType.PLACE)

    def test_entity_type_doctrine(self):
        """enrich identifica type=DOCTRINE para doutrinas."""
        match = self.enricher.enrich(self._make_intent("fruto do Espírito"))
        self.assertTrue(match.is_found)
        self.assertEqual(match.entity_type, BiblicalEntityType.DOCTRINE)

    def test_entity_type_metaphor(self):
        """enrich identifica type=METAPHOR para metáforas."""
        match = self.enricher.enrich(self._make_intent("bom pastor"))
        self.assertTrue(match.is_found)
        self.assertEqual(match.entity_type, BiblicalEntityType.METAPHOR)

    def test_entity_type_symbol(self):
        """enrich identifica type=SYMBOL para símbolos."""
        match = self.enricher.enrich(self._make_intent("pedra angular"))
        self.assertTrue(match.is_found)
        self.assertEqual(match.entity_type, BiblicalEntityType.SYMBOL)

    def test_entity_type_object(self):
        """enrich identifica type=OBJECT para objetos."""
        match = self.enricher.enrich(self._make_intent("arca de Noé"))
        self.assertTrue(match.is_found)
        self.assertEqual(match.entity_type, BiblicalEntityType.OBJECT)

    def test_entity_type_prophecy(self):
        """enrich identifica type=PROPHECY para profecias."""
        match = self.enricher.enrich(self._make_intent("vale de ossos secos"))
        self.assertTrue(match.is_found)
        self.assertEqual(match.entity_type, BiblicalEntityType.PROPHECY)

    def test_empty_match_has_default_graph_fields(self):
        """KnowledgeMatch vazio tem defaults seguros para campos do grafo."""
        match = KnowledgeMatch()
        self.assertEqual(match.entity_id, "")
        self.assertEqual(match.entity_type, BiblicalEntityType.OUTRO)
        self.assertEqual(match.related, ())
        self.assertEqual(match.references, ())
        self.assertEqual(match.places, ())

    def test_enrich_all_returns_graph_fields(self):
        """enrich_all retorna campos do grafo para cada match."""
        intent = self._make_intent("Elias no monte Carmelo")
        matches = self.enricher.enrich_all(intent)
        self.assertGreaterEqual(len(matches), 1)
        for m in matches:
            self.assertTrue(m.entity_id)
            self.assertIsInstance(m.entity_type, BiblicalEntityType)


# ---------------------------------------------------------------------------
# QueryPlan — novos campos do grafo
# ---------------------------------------------------------------------------


class TestQueryPlanGraphFields(unittest.TestCase):
    """Testes dos novos campos do QueryPlan (FASE 7.5)."""

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase(KB_PATH)
        cls.enricher = KnowledgeEnricher(cls.kb)
        cls.planner = QueryPlanner()

    def _make_intent(self, query: str) -> Intent:
        return Intent(action="search", query=query, confidence=0.8, source="llm", raw=query)

    def test_plan_without_knowledge_has_empty_graph_fields(self):
        """plan sem KnowledgeMatch tem entity_id vazio."""
        intent = self._make_intent("amor ao próximo")
        plan = self.planner.plan(intent, knowledge=None)
        self.assertEqual(plan.entity_id, "")
        self.assertEqual(plan.entity_type, "")
        self.assertEqual(plan.related, ())

    def test_plan_with_knowledge_populates_entity_id(self):
        """plan com KnowledgeMatch preenche entity_id."""
        intent = self._make_intent("filho pródigo")
        match = self.enricher.enrich(intent)
        plan = self.planner.plan(intent, knowledge=match)
        self.assertEqual(plan.entity_id, "filho_prodigo")

    def test_plan_with_knowledge_populates_entity_type(self):
        """plan com KnowledgeMatch preenche entity_type."""
        intent = self._make_intent("filho pródigo")
        match = self.enricher.enrich(intent)
        plan = self.planner.plan(intent, knowledge=match)
        self.assertEqual(plan.entity_type, "PARABLE")

    def test_plan_with_knowledge_populates_related(self):
        """plan com KnowledgeMatch preenche related."""
        intent = self._make_intent("filho pródigo")
        match = self.enricher.enrich(intent)
        plan = self.planner.plan(intent, knowledge=match)
        self.assertIn("bom_pastor", plan.related)

    def test_plan_with_knowledge_populates_places(self):
        """plan com KnowledgeMatch preenche places da KB."""
        intent = self._make_intent("mulher samaritana")
        match = self.enricher.enrich(intent)
        plan = self.planner.plan(intent, knowledge=match)
        # KB places são normalizadas para lowercase
        places_lower = [p.lower() for p in plan.places]
        self.assertIn("sicar", places_lower)

    def test_plan_entity_type_is_string(self):
        """entity_type no QueryPlan é string (não enum)."""
        intent = self._make_intent("filho pródigo")
        match = self.enricher.enrich(intent)
        plan = self.planner.plan(intent, knowledge=match)
        self.assertIsInstance(plan.entity_type, str)


# ---------------------------------------------------------------------------
# Compatibilidade — todos os conceitos antigos continuam funcionando
# ---------------------------------------------------------------------------


class TestBackwardCompatibility(unittest.TestCase):
    """Garante que todos os conceitos antigos continuam funcionando."""

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase(KB_PATH)
        cls.enricher = KnowledgeEnricher(cls.kb)
        cls.planner = QueryPlanner()

    def test_all_34_concepts_findable(self):
        """Todos os 34 conceitos podem ser encontrados por seus aliases."""
        entities = self.kb.all_entities()
        for entity in entities:
            # Cada entidade deve ser encontrável pelo seu nome
            found = self.kb.find(entity.name)
            self.assertIsNotNone(found, f"Cannot find concept: {entity.name}")

    def test_all_concepts_have_aliases(self):
        """Todos os conceitos têm pelo menos 1 alias."""
        for entity in self.kb.all_entities():
            self.assertGreaterEqual(len(entity.aliases), 1,
                                    f"{entity.name} has no aliases")

    def test_all_concepts_have_books(self):
        """Todos os conceitos têm pelo menos 1 livro."""
        for entity in self.kb.all_entities():
            self.assertGreaterEqual(len(entity.books), 1,
                                    f"{entity.name} has no books")

    def test_all_concepts_have_keywords(self):
        """Todos os conceitos têm pelo menos 3 keywords."""
        for entity in self.kb.all_entities():
            self.assertGreaterEqual(len(entity.keywords), 3,
                                    f"{entity.name} has too few keywords")

    def test_all_concepts_have_confidence(self):
        """Todos os conceitos têm confidence > 0."""
        for entity in self.kb.all_entities():
            self.assertGreater(entity.confidence, 0.0,
                               f"{entity.name} has zero confidence")

    def test_enrich_still_returns_all_original_fields(self):
        """enrich ainda retorna todos os campos originais."""
        intent = Intent(action="search", query="filho pródigo", confidence=0.8, source="llm", raw="filho pródigo")
        match = self.enricher.enrich(intent)
        self.assertTrue(match.is_found)
        self.assertEqual(match.concept, "filho pródigo")
        self.assertGreater(len(match.aliases), 0)
        self.assertIn("lucas", [b.lower() for b in match.books])
        self.assertIn(15, match.chapters)
        self.assertGreater(len(match.characters), 0)
        self.assertGreater(len(match.events), 0)
        self.assertGreater(len(match.themes), 0)
        self.assertGreater(len(match.keywords), 0)
        self.assertGreater(len(match.boost_terms), 0)
        self.assertGreater(match.confidence, 0.0)
        self.assertTrue(match.matched_alias)

    def test_plan_still_works_without_knowledge(self):
        """plan() sem knowledge continua funcionando como antes."""
        intent = Intent(action="search", query="amor ao próximo", confidence=0.8, source="llm", raw="amor ao próximo")
        plan = self.planner.plan(intent, knowledge=None)
        self.assertGreater(len(plan.keywords), 0)
        self.assertIn("amor", plan.keywords)

    def test_plan_still_works_with_llm_enrichment(self):
        """plan() com LLM enrichment (sem knowledge) continua funcionando."""
        intent = Intent(
            action="search",
            query="Jesus manda lançar a rede",
            confidence=0.9,
            source="llm",
            raw="Jesus manda lançar a rede",
            enrichment={"personagens": ["Jesus"], "livros_sugeridos": ["João"]},
        )
        plan = self.planner.plan(intent, knowledge=None)
        self.assertIn("Jesus", plan.people)
        self.assertIn("João", plan.suggested_books)

    def test_json_backward_compatible_old_format(self):
        """JSON no formato antigo (sem id/type/related) ainda carrega."""
        import tempfile, json
        old_format = {
            "concepts": [
                {
                    "concept": "teste antigo",
                    "aliases": ["teste"],
                    "books": ["João"],
                    "chapters": [1],
                    "characters": [],
                    "events": [],
                    "themes": [],
                    "keywords": ["teste"],
                    "boost_terms": [],
                    "confidence": 0.9,
                }
            ]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(old_format, f)
            tmp_path = f.name
        try:
            kb = KnowledgeBase(tmp_path)
            self.assertTrue(kb.is_loaded)
            self.assertEqual(kb.size, 1)
            entry = kb.find("teste antigo")
            self.assertIsNotNone(entry)
            self.assertEqual(entry.concept, "teste antigo")
            # entity_id é gerado automaticamente
            self.assertTrue(entry.entity_id)
            # type é OUTRO quando não especificado
            self.assertEqual(entry.entity_type, BiblicalEntityType.OUTRO)
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Relacionamentos específicos
# ---------------------------------------------------------------------------


class TestSpecificRelationships(unittest.TestCase):
    """Testa relacionamentos específicos entre conceitos."""

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase(KB_PATH)

    def test_filho_prodigo_related_to_bom_pastor(self):
        """filho_prodigo → bom_pastor."""
        entity = self.kb.get_entity("filho_prodigo")
        self.assertIn("bom_pastor", entity.related)

    def test_bom_pastor_related_to_filho_prodigo(self):
        """bom_pastor → filho_prodigo (bidirecional)."""
        entity = self.kb.get_entity("bom_pastor")
        self.assertIn("filho_prodigo", entity.related)

    def test_arca_de_noe_related_to_diluvio(self):
        """arca_de_noe → diluvio."""
        entity = self.kb.get_entity("arca_de_noe")
        self.assertIn("diluvio", entity.related)

    def test_diluvio_related_to_arca_de_noe(self):
        """diluvio → arca_de_noe (bidirecional)."""
        entity = self.kb.get_entity("diluvio")
        self.assertIn("arca_de_noe", entity.related)

    def test_pentecostes_related_to_fruto_do_espirito(self):
        """pentecostes → fruto_do_espirito."""
        entity = self.kb.get_entity("pentecostes")
        self.assertIn("fruto_do_espirito", entity.related)

    def test_profeta_elias_related_to_monte_carmelo(self):
        """profeta_elias → monte_carmelo."""
        entity = self.kb.get_entity("profeta_elias")
        self.assertIn("monte_carmelo", entity.related)

    def test_monte_carmelo_related_to_profeta_elias(self):
        """monte_carmelo → profeta_elias (bidirecional)."""
        entity = self.kb.get_entity("monte_carmelo")
        self.assertIn("profeta_elias", entity.related)

    def test_exodo_related_to_mar_vermelho(self):
        """exodo → mar_vermelho."""
        entity = self.kb.get_entity("exodo")
        self.assertIn("mar_vermelho", entity.related)

    def test_sarca_ardente_related_to_monte_sinai(self):
        """sarca_ardente → monte_sinai."""
        entity = self.kb.get_entity("sarca_ardente")
        self.assertIn("monte_sinai", entity.related)

    def test_fruto_do_espirito_related_to_armadura_de_deus(self):
        """fruto_do_espirito → armadura_de_deus."""
        entity = self.kb.get_entity("fruto_do_espirito")
        self.assertIn("armadura_de_deus", entity.related)

    def test_pedro_anda_sobre_aguas_related_to_pesca_milagrosa(self):
        """pedro_anda_sobre_aguas → pesca_milagrosa."""
        entity = self.kb.get_entity("pedro_anda_sobre_aguas")
        self.assertIn("pesca_milagrosa", entity.related)

    def test_transfiguracao_related_to_pedro_anda_sobre_aguas(self):
        """transfiguracao → pedro_anda_sobre_aguas."""
        entity = self.kb.get_entity("transfiguracao")
        self.assertIn("pedro_anda_sobre_aguas", entity.related)

    def test_torre_de_babel_related_to_pentecostes(self):
        """torre_de_babel → pentecostes (confusão de línguas → línguas de fogo)."""
        entity = self.kb.get_entity("torre_de_babel")
        self.assertIn("pentecostes", entity.related)

    def test_get_related_entities_returns_entities(self):
        """get_related_entities retorna BiblicalEntity objects."""
        related = self.kb.get_related_entities("filho_prodigo")
        for e in related:
            self.assertIsInstance(e, BiblicalEntity)
        ids = [e.id for e in related]
        self.assertIn("bom_pastor", ids)

    def test_no_self_references(self):
        """Nenhuma entidade se referencia a si mesma."""
        for entity in self.kb.all_entities():
            self.assertNotIn(entity.id, entity.related,
                             f"{entity.id} self-references")


if __name__ == "__main__":
    unittest.main()
