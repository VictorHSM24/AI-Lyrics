"""Testes do SermonContext DTO e imutabilidade (FASE 8 — Parte 1).

Cobre:
  - Criação de contexto vazio.
  - Propriedades do contexto vazio.
  - Imutabilidade do DTO (frozen).
  - with_update() retorna novo contexto.
  - to_dict() serialização.
  - Contadores e timestamps.
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
    EntityMentioned,
    EventMentioned,
    ReferenceResolved,
    SermonContext,
    ThemeMentioned,
)
from busca.bible_reference import BibleBook, BibleReference


# ---------------------------------------------------------------------------
# Eventos — imutabilidade
# ---------------------------------------------------------------------------


class TestEventsImmutable(unittest.TestCase):
    """Eventos são frozen dataclasses."""

    def test_book_changed_frozen(self):
        ev = BookChanged(book="João", book_id=43)
        with self.assertRaises(Exception):
            ev.book = "Lucas"  # type: ignore

    def test_chapter_changed_frozen(self):
        ev = ChapterChanged(chapter=3)
        with self.assertRaises(Exception):
            ev.chapter = 5  # type: ignore

    def test_reference_resolved_frozen(self):
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ev = ReferenceResolved(reference=ref)
        with self.assertRaises(Exception):
            ev.reference = None  # type: ignore

    def test_theme_mentioned_frozen(self):
        ev = ThemeMentioned(theme="amor")
        with self.assertRaises(Exception):
            ev.theme = "graça"  # type: ignore

    def test_entity_mentioned_frozen(self):
        ev = EntityMentioned(name="Pedro", entity_type="person")
        with self.assertRaises(Exception):
            ev.name = "João"  # type: ignore

    def test_concept_mentioned_frozen(self):
        ev = ConceptMentioned(concept_id="filho_prodigo", concept_name="filho pródigo")
        with self.assertRaises(Exception):
            ev.concept_id = "bom_pastor"  # type: ignore

    def test_event_mentioned_frozen(self):
        ev = EventMentioned(event="parábola do filho pródigo")
        with self.assertRaises(Exception):
            ev.event = "dilúvio"  # type: ignore

    def test_context_reset_frozen(self):
        ev = ContextReset(reason="novo sermão")
        with self.assertRaises(Exception):
            ev.reason = "outro"  # type: ignore


class TestSermonContextEmpty(unittest.TestCase):
    """Contexto vazio recém-criado."""

    def test_empty_context_is_empty(self):
        ctx = SermonContext()
        self.assertTrue(ctx.is_empty)

    def test_empty_context_no_book(self):
        ctx = SermonContext()
        self.assertIsNone(ctx.book)
        self.assertIsNone(ctx.book_id)

    def test_empty_context_no_chapter(self):
        ctx = SermonContext()
        self.assertIsNone(ctx.chapter)

    def test_empty_context_no_reference(self):
        ctx = SermonContext()
        self.assertIsNone(ctx.last_reference)

    def test_empty_context_empty_collections(self):
        ctx = SermonContext()
        self.assertEqual(ctx.recent_references, ())
        self.assertEqual(ctx.recent_books, ())
        self.assertEqual(ctx.recent_themes, ())
        self.assertEqual(ctx.recent_characters, ())
        self.assertEqual(ctx.recent_concepts, ())
        self.assertEqual(ctx.recent_events, ())

    def test_empty_context_zero_counters(self):
        ctx = SermonContext()
        self.assertEqual(ctx.update_count, 0)
        self.assertEqual(ctx.last_book_update, 0)
        self.assertEqual(ctx.last_chapter_update, 0)
        self.assertEqual(ctx.last_theme_update, 0)
        self.assertEqual(ctx.last_character_update, 0)
        self.assertEqual(ctx.last_concept_update, 0)
        self.assertEqual(ctx.last_event_update, 0)

    def test_empty_context_no_active_state(self):
        ctx = SermonContext()
        self.assertFalse(ctx.has_active_book)
        self.assertFalse(ctx.has_active_chapter)
        self.assertFalse(ctx.has_active_reference)


class TestSermonContextImmutability(unittest.TestCase):
    """Imutabilidade do DTO (frozen)."""

    def test_frozen_cannot_set_book(self):
        ctx = SermonContext()
        with self.assertRaises(Exception):
            ctx.book = "João"  # type: ignore

    def test_frozen_cannot_set_chapter(self):
        ctx = SermonContext()
        with self.assertRaises(Exception):
            ctx.chapter = 3  # type: ignore

    def test_frozen_cannot_set_collection(self):
        ctx = SermonContext()
        with self.assertRaises(Exception):
            ctx.recent_books = ("João",)  # type: ignore

    def test_frozen_cannot_set_counter(self):
        ctx = SermonContext()
        with self.assertRaises(Exception):
            ctx.update_count = 1  # type: ignore

    def test_with_update_returns_new_context(self):
        ctx = SermonContext()
        new_ctx = ctx.with_update(book="João", book_id=43)
        self.assertIsNot(ctx, new_ctx)
        self.assertIsNone(ctx.book)
        self.assertEqual(new_ctx.book, "João")

    def test_with_update_increments_count(self):
        ctx = SermonContext()
        new_ctx = ctx.with_update(book="João")
        self.assertEqual(ctx.update_count, 0)
        self.assertEqual(new_ctx.update_count, 1)

    def test_with_update_preserves_other_fields(self):
        ctx = SermonContext(book="Lucas", book_id=42, chapter=15)
        new_ctx = ctx.with_update(chapter=16)
        self.assertEqual(new_ctx.book, "Lucas")
        self.assertEqual(new_ctx.book_id, 42)
        self.assertEqual(new_ctx.chapter, 16)

    def test_with_update_does_not_modify_original(self):
        ctx = SermonContext(book="Lucas")
        new_ctx = ctx.with_update(book="João")
        self.assertEqual(ctx.book, "Lucas")
        self.assertEqual(new_ctx.book, "João")


class TestSermonContextProperties(unittest.TestCase):
    """Properties do SermonContext."""

    def test_has_active_book_true(self):
        ctx = SermonContext(book="João", book_id=43)
        self.assertTrue(ctx.has_active_book)

    def test_has_active_book_false(self):
        ctx = SermonContext()
        self.assertFalse(ctx.has_active_book)

    def test_has_active_chapter_true(self):
        ctx = SermonContext(chapter=3)
        self.assertTrue(ctx.has_active_chapter)

    def test_has_active_chapter_false(self):
        ctx = SermonContext()
        self.assertFalse(ctx.has_active_chapter)

    def test_has_active_reference_true(self):
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ctx = SermonContext(last_reference=ref)
        self.assertTrue(ctx.has_active_reference)

    def test_has_active_reference_false(self):
        ctx = SermonContext()
        self.assertFalse(ctx.has_active_reference)

    def test_is_empty_with_book(self):
        ctx = SermonContext(book="João")
        self.assertFalse(ctx.is_empty)

    def test_is_empty_with_reference(self):
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ctx = SermonContext(last_reference=ref)
        self.assertFalse(ctx.is_empty)

    def test_is_empty_with_theme(self):
        ctx = SermonContext(recent_themes=("amor",))
        self.assertFalse(ctx.is_empty)


class TestSermonContextSerialization(unittest.TestCase):
    """Serialização to_dict()."""

    def test_to_dict_empty(self):
        ctx = SermonContext()
        d = ctx.to_dict()
        self.assertIsNone(d["book"])
        self.assertIsNone(d["chapter"])
        self.assertIsNone(d["last_reference"])
        self.assertEqual(d["recent_books"], [])
        self.assertEqual(d["update_count"], 0)

    def test_to_dict_with_book(self):
        ctx = SermonContext(book="João", book_id=43, chapter=3)
        d = ctx.to_dict()
        self.assertEqual(d["book"], "João")
        self.assertEqual(d["book_id"], 43)
        self.assertEqual(d["chapter"], 3)

    def test_to_dict_with_reference(self):
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ctx = SermonContext(last_reference=ref)
        d = ctx.to_dict()
        self.assertEqual(d["last_reference"], "João 3:16")

    def test_to_dict_with_collections(self):
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ctx = SermonContext(
            recent_references=(ref,),
            recent_books=("João", "Lucas"),
            recent_themes=("amor", "graça"),
            recent_characters=("Pedro",),
        )
        d = ctx.to_dict()
        self.assertEqual(d["recent_references"], ["João 3:16"])
        self.assertEqual(d["recent_books"], ["João", "Lucas"])
        self.assertEqual(d["recent_themes"], ["amor", "graça"])
        self.assertEqual(d["recent_characters"], ["Pedro"])

    def test_to_dict_with_counters(self):
        ctx = SermonContext(update_count=5, last_book_update=3)
        d = ctx.to_dict()
        self.assertEqual(d["update_count"], 5)
        self.assertEqual(d["last_book_update"], 3)


class TestSermonContextTimestamps(unittest.TestCase):
    """Timestamps no SermonContext."""

    def test_default_timestamps_zero(self):
        ctx = SermonContext()
        self.assertEqual(ctx.created_at, 0.0)
        self.assertEqual(ctx.updated_at, 0.0)

    def test_custom_timestamps(self):
        ctx = SermonContext(created_at=1000.0, updated_at=1005.0)
        self.assertEqual(ctx.created_at, 1000.0)
        self.assertEqual(ctx.updated_at, 1005.0)

    def test_with_update_changes_updated_at(self):
        ctx = SermonContext(created_at=1000.0, updated_at=1000.0)
        new_ctx = ctx.with_update(book="João", updated_at=1005.0)
        self.assertEqual(new_ctx.created_at, 1000.0)
        self.assertEqual(new_ctx.updated_at, 1005.0)


if __name__ == "__main__":
    unittest.main()
