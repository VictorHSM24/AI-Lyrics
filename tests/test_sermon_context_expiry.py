"""Testes de expiração, janela de contexto e cenários (FASE 8 — Parte 3).

Cobre:
  - ContextReset via evento.
  - Múltiplas atualizações e ordem cronológica.
  - Expiração natural (livro, capítulo, referência).
  - Janela de contexto (tamanho máximo do histórico).
  - Configuração customizada (ContextWindowConfig).
  - Cenário completo de sermão.
  - Desacoplamento (engine não conhece outros componentes).
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


def make_engine(config=None):
    """Engine com clock determinístico para testes."""
    clock = [1000.0]

    def fake_clock():
        clock[0] += 1.0
        return clock[0]

    return SermonContextEngine(config=config, clock=fake_clock)


def make_ref(book=BibleBook.JOAO, chapter=3, verse_start=16, verse_end=None):
    return BibleReference(book=book, chapter=chapter, verse_start=verse_start, verse_end=verse_end)


# ---------------------------------------------------------------------------
# Engine — ContextReset
# ---------------------------------------------------------------------------


class TestEngineContextReset(unittest.TestCase):
    """Engine processa ContextReset."""

    def test_reset_event_returns_empty(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        ctx = engine.process(ctx, ContextReset(reason="novo sermão"))
        self.assertTrue(ctx.is_empty)

    def test_reset_event_clears_book(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        ctx = engine.process(ctx, ContextReset())
        self.assertIsNone(ctx.book)

    def test_reset_event_clears_themes(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ThemeMentioned(theme="amor"))
        ctx = engine.process(ctx, ContextReset())
        self.assertEqual(ctx.recent_themes, ())

    def test_reset_event_preserves_old_context(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        old_ctx = ctx
        ctx = engine.process(ctx, ContextReset())
        self.assertEqual(old_ctx.book, "João")
        self.assertTrue(ctx.is_empty)


# ---------------------------------------------------------------------------
# Engine — Múltiplas atualizações e ordem cronológica
# ---------------------------------------------------------------------------


class TestEngineMultipleUpdates(unittest.TestCase):
    """Múltiplas atualizações e ordem cronológica."""

    def test_update_count_increments(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        ctx = engine.process(ctx, ChapterChanged(chapter=3))
        ctx = engine.process(ctx, ThemeMentioned(theme="amor"))
        self.assertEqual(ctx.update_count, 3)

    def test_chronological_order_references(self):
        engine = make_engine()
        ctx = engine.reset()
        refs = [
            make_ref(BibleBook.JOAO, 3, 16),
            make_ref(BibleBook.ROMANOS, 8, 28),
            make_ref(BibleBook.SALMOS, 23),
            make_ref(BibleBook.LUCAS, 15),
        ]
        for ref in refs:
            ctx = engine.process(ctx, ReferenceResolved(reference=ref))
        self.assertEqual(ctx.recent_references[0], refs[3])
        self.assertEqual(ctx.recent_references[1], refs[2])
        self.assertEqual(ctx.recent_references[2], refs[1])
        self.assertEqual(ctx.recent_references[3], refs[0])

    def test_consecutive_references_same_book(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ReferenceResolved(reference=make_ref(BibleBook.JOAO, 3, 16)))
        ctx = engine.process(ctx, ReferenceResolved(reference=make_ref(BibleBook.JOAO, 3, 17)))
        ctx = engine.process(ctx, ReferenceResolved(reference=make_ref(BibleBook.JOAO, 4, 1)))
        self.assertEqual(ctx.book, "João")
        self.assertEqual(len(ctx.recent_references), 3)

    def test_book_change_then_reference(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        ctx = engine.process(ctx, ChapterChanged(chapter=3))
        ctx = engine.process(ctx, ReferenceCompleted(reference=make_ref()))
        self.assertEqual(ctx.book, "João")
        self.assertEqual(ctx.chapter, 3)
        self.assertEqual(ctx.last_reference.to_string(), "João 3:16")


# ---------------------------------------------------------------------------
# Expiração natural
# ---------------------------------------------------------------------------


class TestExpiryBook(unittest.TestCase):
    """Expiração do livro ativo."""

    def test_book_expires_after_n_updates(self):
        config = ContextWindowConfig(book_expiry=5)
        engine = make_engine(config=config)
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        self.assertEqual(ctx.book, "João")
        # Processar 6 eventos sem mencionar o livro
        for i in range(6):
            ctx = engine.process(ctx, ThemeMentioned(theme=f"tema_{i}"))
        # Livro deve ter expirado
        self.assertIsNone(ctx.book)
        self.assertIsNone(ctx.book_id)

    def test_book_not_expired_within_window(self):
        config = ContextWindowConfig(book_expiry=5)
        engine = make_engine(config=config)
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        # Processar 4 eventos (ainda dentro da janela)
        for i in range(4):
            ctx = engine.process(ctx, ThemeMentioned(theme=f"tema_{i}"))
        self.assertEqual(ctx.book, "João")

    def test_book_renewed_by_new_mention(self):
        config = ContextWindowConfig(book_expiry=5)
        engine = make_engine(config=config)
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        # 3 eventos
        for i in range(3):
            ctx = engine.process(ctx, ThemeMentioned(theme=f"tema_{i}"))
        # Renovar menção ao livro
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        # Mais 3 eventos
        for i in range(3):
            ctx = engine.process(ctx, ThemeMentioned(theme=f"tema2_{i}"))
        # Livro ainda ativo (renovado)
        self.assertEqual(ctx.book, "João")


class TestExpiryChapter(unittest.TestCase):
    """Expiração do capítulo ativo."""

    def test_chapter_expires_after_n_updates(self):
        config = ContextWindowConfig(chapter_expiry=3)
        engine = make_engine(config=config)
        ctx = engine.reset()
        ctx = engine.process(ctx, ChapterChanged(chapter=3))
        self.assertEqual(ctx.chapter, 3)
        for i in range(4):
            ctx = engine.process(ctx, ThemeMentioned(theme=f"t{i}"))
        self.assertIsNone(ctx.chapter)

    def test_chapter_not_expired_within_window(self):
        config = ContextWindowConfig(chapter_expiry=3)
        engine = make_engine(config=config)
        ctx = engine.reset()
        ctx = engine.process(ctx, ChapterChanged(chapter=3))
        for i in range(2):
            ctx = engine.process(ctx, ThemeMentioned(theme=f"t{i}"))
        self.assertEqual(ctx.chapter, 3)


class TestExpiryReference(unittest.TestCase):
    """Expiração da referência ativa."""

    def test_reference_expires_with_book(self):
        config = ContextWindowConfig(book_expiry=5)
        engine = make_engine(config=config)
        ctx = engine.reset()
        ref = make_ref()
        ctx = engine.process(ctx, ReferenceResolved(reference=ref))
        self.assertIsNotNone(ctx.last_reference)
        for i in range(6):
            ctx = engine.process(ctx, ThemeMentioned(theme=f"t{i}"))
        self.assertIsNone(ctx.last_reference)
        self.assertIsNone(ctx.book)


# ---------------------------------------------------------------------------
# Janela de contexto (tamanho máximo)
# ---------------------------------------------------------------------------


class TestContextWindow(unittest.TestCase):
    """Janela de contexto limita o tamanho do histórico."""

    def test_max_references(self):
        config = ContextWindowConfig(max_references=3)
        engine = make_engine(config=config)
        ctx = engine.reset()
        for i in range(5):
            ctx = engine.process(ctx, ReferenceResolved(
                reference=make_ref(BibleBook.JOAO, i + 1, 1)))
        self.assertEqual(len(ctx.recent_references), 3)
        # Mais recente primeiro
        self.assertEqual(ctx.recent_references[0].chapter, 5)

    def test_max_books(self):
        config = ContextWindowConfig(max_books=2)
        engine = make_engine(config=config)
        ctx = engine.reset()
        for name, bid in [("João", 43), ("Lucas", 42), ("Mateus", 40)]:
            ctx = engine.process(ctx, BookChanged(book=name, book_id=bid))
        self.assertEqual(len(ctx.recent_books), 2)
        self.assertEqual(ctx.recent_books[0], "Mateus")

    def test_max_themes(self):
        config = ContextWindowConfig(max_themes=3)
        engine = make_engine(config=config)
        ctx = engine.reset()
        for i in range(5):
            ctx = engine.process(ctx, ThemeMentioned(theme=f"tema_{i}"))
        self.assertEqual(len(ctx.recent_themes), 3)
        self.assertEqual(ctx.recent_themes[0], "tema_4")

    def test_max_characters(self):
        config = ContextWindowConfig(max_characters=2)
        engine = make_engine(config=config)
        ctx = engine.reset()
        for name in ["Pedro", "João", "Jesus"]:
            ctx = engine.process(ctx, EntityMentioned(name=name))
        self.assertEqual(len(ctx.recent_characters), 2)
        self.assertEqual(ctx.recent_characters[0], "Jesus")

    def test_max_concepts(self):
        config = ContextWindowConfig(max_concepts=2)
        engine = make_engine(config=config)
        ctx = engine.reset()
        for cid in ["filho_prodigo", "bom_pastor", "lazaro"]:
            ctx = engine.process(ctx, ConceptMentioned(concept_id=cid))
        self.assertEqual(len(ctx.recent_concepts), 2)
        self.assertEqual(ctx.recent_concepts[0], "lazaro")

    def test_max_events(self):
        config = ContextWindowConfig(max_events=2)
        engine = make_engine(config=config)
        ctx = engine.reset()
        for ev in ["dilúvio", "êxodo", "Pentecostes"]:
            ctx = engine.process(ctx, EventMentioned(event=ev))
        self.assertEqual(len(ctx.recent_events), 2)
        self.assertEqual(ctx.recent_events[0], "Pentecostes")


# ---------------------------------------------------------------------------
# Configuração customizada
# ---------------------------------------------------------------------------


class TestContextWindowConfig(unittest.TestCase):
    """ContextWindowConfig é ajustável."""

    def test_default_config(self):
        config = ContextWindowConfig()
        self.assertEqual(config.max_references, 10)
        self.assertEqual(config.max_books, 5)
        self.assertEqual(config.max_themes, 8)
        self.assertEqual(config.book_expiry, 15)

    def test_custom_config(self):
        config = ContextWindowConfig(
            max_references=20, max_books=10, book_expiry=30
        )
        self.assertEqual(config.max_references, 20)
        self.assertEqual(config.max_books, 10)
        self.assertEqual(config.book_expiry, 30)

    def test_engine_uses_custom_config(self):
        config = ContextWindowConfig(max_references=2)
        engine = make_engine(config=config)
        ctx = engine.reset()
        for i in range(5):
            ctx = engine.process(ctx, ReferenceResolved(
                reference=make_ref(BibleBook.JOAO, i + 1, 1)))
        self.assertEqual(len(ctx.recent_references), 2)


# ---------------------------------------------------------------------------
# Cenário completo de sermão
# ---------------------------------------------------------------------------


class TestSermonScenario(unittest.TestCase):
    """Cenário completo: evolução do contexto durante um sermão."""

    def test_full_sermon_scenario(self):
        """Simula um sermão completo com múltiplas referências."""
        engine = make_engine()
        ctx = engine.reset()

        # 1. "Abram em João capítulo 3"
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        ctx = engine.process(ctx, ChapterChanged(chapter=3))
        self.assertEqual(ctx.book, "João")
        self.assertEqual(ctx.chapter, 3)

        # 2. "versículo 16"
        ctx = engine.process(ctx, ReferenceCompleted(reference=make_ref()))
        self.assertEqual(ctx.last_reference.to_string(), "João 3:16")

        # 3. "Pedro andou sobre as águas"
        ctx = engine.process(ctx, EntityMentioned(name="Pedro", entity_type="person"))
        ctx = engine.process(ctx, ConceptMentioned(concept_id="pedro_anda_sobre_aguas"))
        self.assertIn("Pedro", ctx.recent_characters)
        self.assertIn("pedro_anda_sobre_aguas", ctx.recent_concepts)

        # 4. "tema: fé e coragem"
        ctx = engine.process(ctx, ThemeMentioned(theme="fé"))
        ctx = engine.process(ctx, ThemeMentioned(theme="coragem"))
        self.assertIn("fé", ctx.recent_themes)
        self.assertIn("coragem", ctx.recent_themes)

        # 5. "Agora vamos para Lucas 15"
        ctx = engine.process(ctx, BookChanged(book="Lucas", book_id=42))
        ctx = engine.process(ctx, ChapterChanged(chapter=15))
        ctx = engine.process(ctx, ReferenceResolved(
            reference=make_ref(BibleBook.LUCAS, 15, 11, 32)))
        self.assertEqual(ctx.book, "Lucas")
        self.assertEqual(ctx.chapter, 15)
        self.assertEqual(ctx.last_reference.to_string(), "Lucas 15:11-32")

        # 6. Contexto anterior preservado
        self.assertIn("João", ctx.recent_books)
        self.assertIn("Lucas", ctx.recent_books)
        self.assertIn("Pedro", ctx.recent_characters)

    def test_sermon_reset_between_sermons(self):
        """Reset entre sermões limpa o contexto."""
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        ctx = engine.process(ctx, ThemeMentioned(theme="amor"))
        # Fim do sermão
        ctx = engine.process(ctx, ContextReset(reason="fim do sermão"))
        self.assertTrue(ctx.is_empty)
        # Novo sermão
        ctx = engine.process(ctx, BookChanged(book="Romanos", book_id=45))
        self.assertEqual(ctx.book, "Romanos")
        self.assertNotIn("João", ctx.recent_books)


# ---------------------------------------------------------------------------
# Persistência das últimas referências, personagens, conceitos, temas
# ---------------------------------------------------------------------------


class TestPersistenceRecent(unittest.TestCase):
    """Persistência dos últimos itens no histórico."""

    def test_recent_references_persisted(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ReferenceResolved(reference=make_ref(BibleBook.JOAO, 3, 16)))
        ctx = engine.process(ctx, ReferenceResolved(reference=make_ref(BibleBook.LUCAS, 15)))
        self.assertEqual(len(ctx.recent_references), 2)

    def test_recent_characters_persisted(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, EntityMentioned(name="Pedro"))
        ctx = engine.process(ctx, EntityMentioned(name="Jesus"))
        ctx = engine.process(ctx, ThemeMentioned(theme="fé"))
        # Personagens ainda presentes após tema
        self.assertIn("Pedro", ctx.recent_characters)
        self.assertIn("Jesus", ctx.recent_characters)

    def test_recent_concepts_persisted(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ConceptMentioned(concept_id="filho_prodigo"))
        ctx = engine.process(ctx, ThemeMentioned(theme="amor"))
        ctx = engine.process(ctx, EntityMentioned(name="Pedro"))
        self.assertIn("filho_prodigo", ctx.recent_concepts)

    def test_recent_themes_persisted(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, ThemeMentioned(theme="amor"))
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        ctx = engine.process(ctx, ReferenceResolved(reference=make_ref()))
        self.assertIn("amor", ctx.recent_themes)

    def test_recent_books_persisted_after_reference(self):
        engine = make_engine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        ctx = engine.process(ctx, ReferenceResolved(reference=make_ref(BibleBook.LUCAS, 15)))
        self.assertIn("João", ctx.recent_books)
        self.assertIn("Lucas", ctx.recent_books)


# ---------------------------------------------------------------------------
# Imutabilidade após múltiplas atualizações
# ---------------------------------------------------------------------------


class TestImmutabilityAfterUpdates(unittest.TestCase):
    """Contextos anteriores permanecem válidos após múltiplas atualizações."""

    def test_old_context_unchanged_after_new_update(self):
        engine = make_engine()
        ctx0 = engine.reset()
        ctx1 = engine.process(ctx0, BookChanged(book="João", book_id=43))
        ctx2 = engine.process(ctx1, ChapterChanged(chapter=3))
        ctx3 = engine.process(ctx2, ThemeMentioned(theme="amor"))
        # ctx0 não mudou
        self.assertTrue(ctx0.is_empty)
        self.assertEqual(ctx0.update_count, 0)
        # ctx1 não mudou
        self.assertEqual(ctx1.book, "João")
        self.assertIsNone(ctx1.chapter)
        self.assertEqual(ctx1.update_count, 1)
        # ctx2 não mudou
        self.assertEqual(ctx2.book, "João")
        self.assertEqual(ctx2.chapter, 3)
        self.assertEqual(ctx2.recent_themes, ())
        # ctx3 tem tudo
        self.assertEqual(ctx3.book, "João")
        self.assertEqual(ctx3.chapter, 3)
        self.assertIn("amor", ctx3.recent_themes)

    def test_all_contexts_are_distinct_objects(self):
        engine = make_engine()
        ctx0 = engine.reset()
        ctx1 = engine.process(ctx0, BookChanged(book="João", book_id=43))
        ctx2 = engine.process(ctx1, ChapterChanged(chapter=3))
        self.assertIsNot(ctx0, ctx1)
        self.assertIsNot(ctx1, ctx2)
        self.assertIsNot(ctx0, ctx2)


if __name__ == "__main__":
    unittest.main()
