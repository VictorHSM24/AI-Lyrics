"""Testes dos eventos tipados e SermonContextEngine (FASE 8 — Parte 2).

Cobre:
  - Eventos: criação, imutabilidade, campos.
  - Engine: reset(), process() com cada tipo de evento.
  - BookChanged, ChapterChanged, ReferenceResolved, ReferenceCompleted.
  - ReferenceRepeated, ThemeMentioned, EntityMentioned, ConceptMentioned.
  - EventMentioned, ContextReset.
  - Ordem cronológica, múltiplas atualizações, referências consecutivas.
"""

from __future__ import annotations

import unittest

import sys
import os

sys.path.insert(0, ".")

from context import (
    BookChanged,
    ChapterChanged,
    ConceptMentioned,
    ContextReset,
    ContextWindowConfig,
    EntityMentioned,
    EventMentioned,
    ReferenceCompleted,
    ReferenceRepeated,
    ReferenceResolved,
    SermonContext,
    SermonContextEngine,
    ThemeMentioned,
)
from busca.bible_reference import BibleBook, BibleReference


def make_engine():
    """Engine com clock determinístico para testes."""
    clock = [1000.0]

    def fake_clock():
        clock[0] += 1.0
        return clock[0]

    return SermonContextEngine(clock=fake_clock)


def make_ref(book=BibleBook.JOAO, chapter=3, verse_start=16, verse_end=None):
    return BibleReference(book=book, chapter=chapter, verse_start=verse_start, verse_end=verse_end)


# ---------------------------------------------------------------------------
# Engine — reset()
# ---------------------------------------------------------------------------


class TestEngineReset(unittest.TestCase):
    """Engine.reset() retorna contexto vazio."""

    def test_reset_returns_empty_context(self):
        engine = make_engine()
        ctx = engine.reset()
        self.assertTrue(ctx.is_empty)

    def test_reset_update_count_zero(self):
        engine = make_engine()
        ctx = engine.reset()
        self.assertEqual(ctx.update_count, 0)

    def test_reset_has_timestamps(self):
        engine = make_engine()
        ctx = engine.reset()
        self.assertGreater(ctx.created_at, 0)
        self.assertGreaterEqual(ctx.updated_at, ctx.created_at)


# ---------------------------------------------------------------------------
# Engine — BookChanged
# ---------------------------------------------------------------------------


class TestEngineBookChanged(unittest.TestCase):
    """Engine processa BookChanged."""

    def test_book_changed_sets_book(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        self.assertEqual(ctx.book, "João")
        self.assertEqual(ctx.book_id, 43)

    def test_book_changed_adds_to_recent_books(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        self.assertIn("João", ctx.recent_books)

    def test_book_changed_increments_count(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        self.assertEqual(ctx.update_count, 1)

    def test_book_changed_updates_last_book_update(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        self.assertEqual(ctx.last_book_update, 1)

    def test_book_changed_does_not_modify_original(self):
        engine = make_engine()
        ctx = engine.reset()
        original_count = ctx.update_count
        new_ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        self.assertEqual(ctx.update_count, original_count)
        self.assertEqual(new_ctx.update_count, 1)

    def test_multiple_book_changes_keeps_recent(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        ctx = engine.process(ctx, BookChanged(book="Lucas", book_id=42))
        ctx = engine.process(ctx, BookChanged(book="Mateus", book_id=40))
        # Mais recente primeiro
        self.assertEqual(ctx.recent_books[0], "Mateus")
        self.assertIn("Lucas", ctx.recent_books)
        self.assertIn("João", ctx.recent_books)
        self.assertEqual(ctx.book, "Mateus")


# ---------------------------------------------------------------------------
# Engine — ChapterChanged
# ---------------------------------------------------------------------------


class TestEngineChapterChanged(unittest.TestCase):
    """Engine processa ChapterChanged."""

    def test_chapter_changed_sets_chapter(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ChapterChanged(chapter=3))
        self.assertEqual(ctx.chapter, 3)

    def test_chapter_changed_preserves_book(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        ctx = engine.process(ctx, ChapterChanged(chapter=3))
        self.assertEqual(ctx.book, "João")
        self.assertEqual(ctx.chapter, 3)

    def test_chapter_changed_increments_count(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ChapterChanged(chapter=3))
        self.assertEqual(ctx.update_count, 1)


# ---------------------------------------------------------------------------
# Engine — ReferenceResolved
# ---------------------------------------------------------------------------


class TestEngineReferenceResolved(unittest.TestCase):
    """Engine processa ReferenceResolved."""

    def test_reference_resolved_sets_last_reference(self):
        engine = make_engine()
        ctx = engine.reset()
        ref = make_ref()
        ctx = engine.process(ctx, ReferenceResolved(reference=ref))
        self.assertEqual(ctx.last_reference, ref)

    def test_reference_resolved_adds_to_recent(self):
        engine = make_engine()
        ctx = engine.reset()
        ref = make_ref()
        ctx = engine.process(ctx, ReferenceResolved(reference=ref))
        self.assertEqual(len(ctx.recent_references), 1)
        self.assertEqual(ctx.recent_references[0], ref)

    def test_reference_resolved_updates_book_and_chapter(self):
        engine = make_engine()
        ctx = engine.reset()
        ref = make_ref()
        ctx = engine.process(ctx, ReferenceResolved(reference=ref))
        self.assertEqual(ctx.book, "João")
        self.assertEqual(ctx.book_id, 43)
        self.assertEqual(ctx.chapter, 3)

    def test_reference_resolved_adds_book_to_recent(self):
        engine = make_engine()
        ctx = engine.reset()
        ref = make_ref()
        ctx = engine.process(ctx, ReferenceResolved(reference=ref))
        self.assertIn("João", ctx.recent_books)

    def test_multiple_references_keeps_order(self):
        engine = make_engine()
        ctx = engine.reset()
        ref1 = make_ref(BibleBook.JOAO, 3, 16)
        ref2 = make_ref(BibleBook.LUCAS, 15)
        ref3 = make_ref(BibleBook.MATEUS, 5, 1, 12)
        ctx = engine.process(ctx, ReferenceResolved(reference=ref1))
        ctx = engine.process(ctx, ReferenceResolved(reference=ref2))
        ctx = engine.process(ctx, ReferenceResolved(reference=ref3))
        # Mais recente primeiro
        self.assertEqual(ctx.recent_references[0], ref3)
        self.assertEqual(ctx.recent_references[1], ref2)
        self.assertEqual(ctx.recent_references[2], ref1)


# ---------------------------------------------------------------------------
# Engine — ReferenceCompleted
# ---------------------------------------------------------------------------


class TestEngineReferenceCompleted(unittest.TestCase):
    """Engine processa ReferenceCompleted (contexto ativo + versículo)."""

    def test_reference_completed_sets_reference(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        ctx = engine.process(ctx, ChapterChanged(chapter=3))
        ref = make_ref()
        ctx = engine.process(ctx, ReferenceCompleted(reference=ref))
        self.assertEqual(ctx.last_reference, ref)

    def test_reference_completed_adds_to_recent(self):
        engine = make_engine()
        ctx = engine.reset()
        ref = make_ref()
        ctx = engine.process(ctx, ReferenceCompleted(reference=ref))
        self.assertIn(ref, ctx.recent_references)

    def test_reference_completed_updates_chapter(self):
        engine = make_engine()
        ctx = engine.reset()
        ref = make_ref()
        ctx = engine.process(ctx, ReferenceCompleted(reference=ref))
        self.assertEqual(ctx.chapter, 3)


# ---------------------------------------------------------------------------
# Engine — ReferenceRepeated
# ---------------------------------------------------------------------------


class TestEngineReferenceRepeated(unittest.TestCase):
    """Engine processa ReferenceRepeated (mantém referência ativa)."""

    def test_reference_repeated_keeps_reference(self):
        engine = make_engine()
        ctx = engine.reset()
        ref = make_ref()
        ctx = engine.process(ctx, ReferenceResolved(reference=ref))
        ctx = engine.process(ctx, ReferenceRepeated(hint="aquele versículo"))
        self.assertEqual(ctx.last_reference, ref)

    def test_reference_repeated_no_reference_no_change(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ReferenceRepeated(hint="aquele versículo"))
        self.assertIsNone(ctx.last_reference)

    def test_reference_repeated_adds_to_recent(self):
        engine = make_engine()
        ctx = engine.reset()
        ref = make_ref()
        ctx = engine.process(ctx, ReferenceResolved(reference=ref))
        ctx = engine.process(ctx, ReferenceRepeated(hint="aquele versículo"))
        # Referência repetida deve estar no topo do histórico
        self.assertEqual(ctx.recent_references[0], ref)


# ---------------------------------------------------------------------------
# Engine — ThemeMentioned, EntityMentioned, ConceptMentioned, EventMentioned
# ---------------------------------------------------------------------------


class TestEngineThemeMentioned(unittest.TestCase):
    """Engine processa ThemeMentioned."""

    def test_theme_mentioned_adds_to_recent(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ThemeMentioned(theme="amor de Deus"))
        self.assertIn("amor de Deus", ctx.recent_themes)

    def test_multiple_themes_keeps_order(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ThemeMentioned(theme="amor"))
        ctx = engine.process(ctx, ThemeMentioned(theme="graça"))
        ctx = engine.process(ctx, ThemeMentioned(theme="fé"))
        self.assertEqual(ctx.recent_themes[0], "fé")
        self.assertEqual(ctx.recent_themes[1], "graça")
        self.assertEqual(ctx.recent_themes[2], "amor")

    def test_theme_mentioned_dedup(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ThemeMentioned(theme="amor"))
        ctx = engine.process(ctx, ThemeMentioned(theme="graça"))
        ctx = engine.process(ctx, ThemeMentioned(theme="amor"))
        # "amor" movido para o início, sem duplicata
        self.assertEqual(ctx.recent_themes[0], "amor")
        self.assertEqual(len(ctx.recent_themes), 2)

    def test_theme_mentioned_empty_ignored(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ThemeMentioned(theme=""))
        self.assertEqual(ctx.recent_themes, ())


class TestEngineEntityMentioned(unittest.TestCase):
    """Engine processa EntityMentioned."""

    def test_entity_mentioned_adds_character(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, EntityMentioned(name="Pedro", entity_type="person"))
        self.assertIn("Pedro", ctx.recent_characters)

    def test_multiple_entities_keeps_order(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, EntityMentioned(name="Pedro"))
        ctx = engine.process(ctx, EntityMentioned(name="Jesus"))
        ctx = engine.process(ctx, EntityMentioned(name="João"))
        self.assertEqual(ctx.recent_characters[0], "João")

    def test_entity_mentioned_dedup(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, EntityMentioned(name="Pedro"))
        ctx = engine.process(ctx, EntityMentioned(name="Jesus"))
        ctx = engine.process(ctx, EntityMentioned(name="Pedro"))
        self.assertEqual(ctx.recent_characters[0], "Pedro")
        self.assertEqual(len(ctx.recent_characters), 2)

    def test_entity_mentioned_empty_ignored(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, EntityMentioned(name=""))
        self.assertEqual(ctx.recent_characters, ())


class TestEngineConceptMentioned(unittest.TestCase):
    """Engine processa ConceptMentioned."""

    def test_concept_mentioned_adds_id(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ConceptMentioned(concept_id="filho_prodigo", concept_name="filho pródigo"))
        self.assertIn("filho_prodigo", ctx.recent_concepts)

    def test_multiple_concepts_keeps_order(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ConceptMentioned(concept_id="filho_prodigo"))
        ctx = engine.process(ctx, ConceptMentioned(concept_id="bom_pastor"))
        self.assertEqual(ctx.recent_concepts[0], "bom_pastor")

    def test_concept_mentioned_dedup(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ConceptMentioned(concept_id="filho_prodigo"))
        ctx = engine.process(ctx, ConceptMentioned(concept_id="bom_pastor"))
        ctx = engine.process(ctx, ConceptMentioned(concept_id="filho_prodigo"))
        self.assertEqual(ctx.recent_concepts[0], "filho_prodigo")
        self.assertEqual(len(ctx.recent_concepts), 2)


class TestEngineEventMentioned(unittest.TestCase):
    """Engine processa EventMentioned."""

    def test_event_mentioned_adds_event(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, EventMentioned(event="parábola do filho pródigo"))
        self.assertIn("parábola do filho pródigo", ctx.recent_events)

    def test_multiple_events_keeps_order(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, EventMentioned(event="dilúvio"))
        ctx = engine.process(ctx, EventMentioned(event="êxodo"))
        self.assertEqual(ctx.recent_events[0], "êxodo")

    def test_event_mentioned_empty_ignored(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, EventMentioned(event=""))
        self.assertEqual(ctx.recent_events, ())


# ---------------------------------------------------------------------------
# Desacoplamento
# ---------------------------------------------------------------------------


class TestDecoupling(unittest.TestCase):
    """Engine é desacoplada — não conhece outros componentes."""

    @staticmethod
    def _import_lines():
        """Extrai apenas as linhas de import do engine.py."""
        import context.engine as engine_module
        with open(engine_module.__file__, encoding="utf-8") as f:
            lines = f.readlines()
        return [l for l in lines if l.strip().startswith(("import ", "from "))]

    def test_engine_no_searcher_dependency(self):
        """Engine não importa Searcher."""
        imports = self._import_lines()
        source = "\n".join(imports)
        self.assertNotIn("searcher", source.lower())

    def test_engine_no_ranking_dependency(self):
        """Engine não importa Ranking."""
        imports = self._import_lines()
        source = "\n".join(imports)
        self.assertNotIn("ranking", source.lower())

    def test_engine_no_llm_dependency(self):
        """Engine não importa LLM."""
        imports = self._import_lines()
        source = "\n".join(imports)
        self.assertNotIn("from llm", source.lower())

    def test_engine_no_parser_dependency(self):
        """Engine não importa Parser."""
        imports = self._import_lines()
        source = "\n".join(imports)
        self.assertNotIn("from parser", source.lower())

    def test_engine_no_knowledge_base_dependency(self):
        """Engine não importa KnowledgeBase."""
        imports = self._import_lines()
        source = "\n".join(imports)
        self.assertNotIn("knowledge_enricher", source.lower())
        self.assertNotIn("knowledge_base", source.lower())

    def test_engine_no_holyrics_dependency(self):
        """Engine não importa Holyrics."""
        imports = self._import_lines()
        source = "\n".join(imports)
        self.assertNotIn("holyrics", source.lower())

    def test_engine_no_embeddings_dependency(self):
        """Engine não importa Embeddings."""
        imports = self._import_lines()
        source = "\n".join(imports)
        self.assertNotIn("embedding", source.lower())


if __name__ == "__main__":
    unittest.main()
