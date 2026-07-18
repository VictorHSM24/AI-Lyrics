"""Testes para BibleBook, BibleReference, e parser de referências bíblicas.

Cobre a FASE 7.6 — Canonical Bible References:
  - BibleBook: enum 1..66, canonical_name, aliases, from_name.
  - BibleReference: DTO imutável, properties, serialização.
  - Parser: string → BibleReference (vários formatos).
  - Ranges, single verse, chapter.
  - Equality, hash, ordering.
  - Normalização, abreviações, numerais romanos.
  - Compatibilidade com Knowledge Base.
"""

from __future__ import annotations

import unittest

sys_path_setup = True

import os
import sys

sys.path.insert(0, ".")

from busca.bible_reference import (
    BibleBook,
    BibleReference,
    parse_bible_reference,
    parse_references,
    references_to_strings,
)
from busca.biblical_entity import BiblicalEntity, BiblicalEntityType
from busca.knowledge_enricher import KnowledgeBase, KnowledgeEnricher, KnowledgeMatch
from core.types import Intent


KB_PATH = os.path.join("config", "knowledge_base.json")


# ---------------------------------------------------------------------------
# BibleBook
# ---------------------------------------------------------------------------


class TestBibleBook(unittest.TestCase):
    """Testes do enum BibleBook."""

    def test_66_books_exist(self):
        """Existem exatamente 66 livros."""
        books = list(BibleBook)
        self.assertEqual(len(books), 66)

    def test_ids_sequential_1_to_66(self):
        """IDs são sequenciais de 1 a 66."""
        ids = sorted(int(b) for b in BibleBook)
        self.assertEqual(ids, list(range(1, 67)))

    def test_canonical_name_genesis(self):
        """Gênesis tem nome canônico correto."""
        self.assertEqual(BibleBook.GENESIS.canonical_name, "Gênesis")

    def test_canonical_name_joao(self):
        """João tem nome canônico correto."""
        self.assertEqual(BibleBook.JOAO.canonical_name, "João")

    def test_canonical_name_apocalipse(self):
        """Apocalipse tem nome canônico correto."""
        self.assertEqual(BibleBook.APOCALIPSE.canonical_name, "Apocalipse")

    def test_canonical_name_1_corintios(self):
        """1 Coríntios tem nome canônico correto."""
        self.assertEqual(BibleBook.PRIMEIRO_CORINTIOS.canonical_name, "1 Coríntios")

    def test_canonical_name_2_joao(self):
        """2 João tem nome canônico correto."""
        self.assertEqual(BibleBook.SEGUNDO_JOAO.canonical_name, "2 João")

    def test_canonical_name_3_joao(self):
        """3 João tem nome canônico correto."""
        self.assertEqual(BibleBook.TERCEIRO_JOAO.canonical_name, "3 João")

    def test_int_value(self):
        """BibleBook é IntEnum — int() retorna o ID."""
        self.assertEqual(int(BibleBook.GENESIS), 1)
        self.assertEqual(int(BibleBook.APOCALIPSE), 66)
        self.assertEqual(int(BibleBook.JOAO), 43)

    def test_from_name_full_name(self):
        """from_name resolve nomes completos."""
        self.assertEqual(BibleBook.from_name("João"), BibleBook.JOAO)
        self.assertEqual(BibleBook.from_name("Gênesis"), BibleBook.GENESIS)
        self.assertEqual(BibleBook.from_name("Apocalipse"), BibleBook.APOCALIPSE)

    def test_from_name_case_insensitive(self):
        """from_name é case-insensitive."""
        self.assertEqual(BibleBook.from_name("joão"), BibleBook.JOAO)
        self.assertEqual(BibleBook.from_name("JOÃO"), BibleBook.JOAO)
        self.assertEqual(BibleBook.from_name("Joao"), BibleBook.JOAO)

    def test_from_name_with_accents(self):
        """from_name funciona com e sem acentos."""
        self.assertEqual(BibleBook.from_name("João"), BibleBook.JOAO)
        self.assertEqual(BibleBook.from_name("Joao"), BibleBook.JOAO)

    def test_from_name_abbreviation(self):
        """from_name resolve abreviações."""
        self.assertEqual(BibleBook.from_name("Jo"), BibleBook.JOAO)
        self.assertEqual(BibleBook.from_name("Gn"), BibleBook.GENESIS)
        self.assertEqual(BibleBook.from_name("Ap"), BibleBook.APOCALIPSE)
        self.assertEqual(BibleBook.from_name("Mt"), BibleBook.MATEUS)
        self.assertEqual(BibleBook.from_name("Lc"), BibleBook.LUCAS)

    def test_from_name_roman_numerals(self):
        """from_name resolve numerais romanos."""
        self.assertEqual(BibleBook.from_name("II Reis"), BibleBook.SEGUNDO_REIS)
        self.assertEqual(BibleBook.from_name("I Coríntios"), BibleBook.PRIMEIRO_CORINTIOS)
        self.assertEqual(BibleBook.from_name("III João"), BibleBook.TERCEIRO_JOAO)
        self.assertEqual(BibleBook.from_name("I Pedro"), BibleBook.PRIMEIRO_PEDRO)

    def test_from_name_arabic_numerals(self):
        """from_name resolve numerais arábicos."""
        self.assertEqual(BibleBook.from_name("1 Reis"), BibleBook.PRIMEIRO_REIS)
        self.assertEqual(BibleBook.from_name("2 Coríntios"), BibleBook.SEGUNDO_CORINTIOS)
        self.assertEqual(BibleBook.from_name("3 João"), BibleBook.TERCEIRO_JOAO)

    def test_from_name_salmos_synonym(self):
        """from_name resolve sinônimos (Salmo → Salmos)."""
        self.assertEqual(BibleBook.from_name("Salmo"), BibleBook.SALMOS)
        self.assertEqual(BibleBook.from_name("Salmos"), BibleBook.SALMOS)

    def test_from_name_invalid_returns_none(self):
        """from_name retorna None para nomes inválidos."""
        self.assertIsNone(BibleBook.from_name("LivroInexistente"))
        self.assertIsNone(BibleBook.from_name("xyz"))

    def test_from_name_empty_returns_none(self):
        """from_name retorna None para string vazia."""
        self.assertIsNone(BibleBook.from_name(""))
        self.assertIsNone(BibleBook.from_name("   "))

    def test_aliases_non_empty(self):
        """Todos os livros têm pelo menos 1 alias."""
        for book in BibleBook:
            self.assertGreaterEqual(len(book.aliases), 1,
                                    f"{book.canonical_name} has no aliases")

    def test_int_enum_comparison(self):
        """BibleBook pode ser comparado com int."""
        self.assertEqual(BibleBook.GENESIS, 1)
        self.assertEqual(BibleBook.APOCALIPSE, 66)
        self.assertLess(BibleBook.GENESIS, BibleBook.APOCALIPSE)


# ---------------------------------------------------------------------------
# BibleReference — criação e properties
# ---------------------------------------------------------------------------


class TestBibleReferenceProperties(unittest.TestCase):
    """Testes das properties de BibleReference."""

    def test_single_verse(self):
        """Versículo único: is_single_verse=True."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        self.assertTrue(ref.is_single_verse)
        self.assertFalse(ref.is_range)
        self.assertFalse(ref.is_chapter)

    def test_range(self):
        """Intervalo: is_range=True."""
        ref = BibleReference(book=BibleBook.MATEUS, chapter=5, verse_start=1, verse_end=12)
        self.assertTrue(ref.is_range)
        self.assertFalse(ref.is_single_verse)
        self.assertFalse(ref.is_chapter)

    def test_chapter_only(self):
        """Capítulo inteiro: is_chapter=True."""
        ref = BibleReference(book=BibleBook.LUCAS, chapter=15)
        self.assertTrue(ref.is_chapter)
        self.assertFalse(ref.is_single_verse)
        self.assertFalse(ref.is_range)

    def test_book_id(self):
        """book_id retorna o ID do livro."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        self.assertEqual(ref.book_id, 43)

    def test_length_single_verse(self):
        """length=1 para versículo único."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        self.assertEqual(ref.length, 1)

    def test_length_range(self):
        """length=N para intervalo."""
        ref = BibleReference(book=BibleBook.MATEUS, chapter=5, verse_start=1, verse_end=12)
        self.assertEqual(ref.length, 12)

    def test_length_chapter_none(self):
        """length=None para capítulo inteiro."""
        ref = BibleReference(book=BibleBook.LUCAS, chapter=15)
        self.assertIsNone(ref.length)

    def test_display_property(self):
        """display retorna a string canônica."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        self.assertEqual(ref.display, "João 3:16")

    def test_frozen_immutability(self):
        """BibleReference é frozen."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        with self.assertRaises(Exception):
            ref.chapter = 4  # type: ignore

    def test_hashable(self):
        """BibleReference é hashable (pode ser usado em set/dict)."""
        ref1 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ref2 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        s = {ref1, ref2}
        self.assertEqual(len(s), 1)  # Mesmo hash → 1 elemento

    def test_equality(self):
        """BibleReference implementa equality."""
        ref1 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ref2 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ref3 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=17)
        self.assertEqual(ref1, ref2)
        self.assertNotEqual(ref1, ref3)

    def test_ordering_by_book(self):
        """BibleReference é ordenável (por book_id, chapter, verse)."""
        ref1 = BibleReference(book=BibleBook.GENESIS, chapter=1)
        ref2 = BibleReference(book=BibleBook.APOCALIPSE, chapter=22)
        self.assertLess(ref1, ref2)

    def test_ordering_same_book(self):
        """Ordenação dentro do mesmo livro por capítulo."""
        ref1 = BibleReference(book=BibleBook.JOAO, chapter=1)
        ref2 = BibleReference(book=BibleBook.JOAO, chapter=3)
        self.assertLess(ref1, ref2)

    def test_ordering_same_chapter(self):
        """Ordenação dentro do mesmo capítulo por versículo."""
        ref1 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ref2 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=17)
        self.assertLess(ref1, ref2)


# ---------------------------------------------------------------------------
# Serialização
# ---------------------------------------------------------------------------


class TestBibleReferenceSerialization(unittest.TestCase):
    """Testes de serialização e desserialização."""

    def test_to_string_single_verse(self):
        """to_string para versículo único."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        self.assertEqual(ref.to_string(), "João 3:16")

    def test_to_string_range(self):
        """to_string para intervalo."""
        ref = BibleReference(book=BibleBook.MATEUS, chapter=5, verse_start=1, verse_end=12)
        self.assertEqual(ref.to_string(), "Mateus 5:1-12")

    def test_to_string_chapter(self):
        """to_string para capítulo inteiro."""
        ref = BibleReference(book=BibleBook.LUCAS, chapter=15)
        self.assertEqual(ref.to_string(), "Lucas 15")

    def test_to_dict_single_verse(self):
        """to_dict para versículo único."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        d = ref.to_dict()
        self.assertEqual(d["book_id"], 43)
        self.assertEqual(d["book"], "João")
        self.assertEqual(d["chapter"], 3)
        self.assertEqual(d["verse_start"], 16)
        self.assertEqual(d["display"], "João 3:16")
        self.assertFalse(d["is_range"])
        self.assertTrue(d["is_single_verse"])
        self.assertFalse(d["is_chapter"])

    def test_to_dict_range(self):
        """to_dict para intervalo."""
        ref = BibleReference(book=BibleBook.MATEUS, chapter=5, verse_start=1, verse_end=12)
        d = ref.to_dict()
        self.assertTrue(d["is_range"])
        self.assertFalse(d["is_single_verse"])
        self.assertEqual(d["verse_end"], 12)

    def test_to_dict_chapter(self):
        """to_dict para capítulo inteiro."""
        ref = BibleReference(book=BibleBook.LUCAS, chapter=15)
        d = ref.to_dict()
        self.assertTrue(d["is_chapter"])
        self.assertIsNone(d["verse_start"])

    def test_from_dict_single_verse(self):
        """from_dict para versículo único."""
        d = {"book_id": 43, "chapter": 3, "verse_start": 16}
        ref = BibleReference.from_dict(d)
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.JOAO)
        self.assertEqual(ref.chapter, 3)
        self.assertEqual(ref.verse_start, 16)

    def test_from_dict_range(self):
        """from_dict para intervalo."""
        d = {"book_id": 40, "chapter": 5, "verse_start": 1, "verse_end": 12}
        ref = BibleReference.from_dict(d)
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.MATEUS)
        self.assertTrue(ref.is_range)

    def test_from_dict_by_name(self):
        """from_dict resolve por nome do livro."""
        d = {"book": "João", "chapter": 3, "verse_start": 16}
        ref = BibleReference.from_dict(d)
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.JOAO)

    def test_from_dict_invalid_book(self):
        """from_dict retorna None para livro inválido."""
        d = {"book_id": 999, "chapter": 3}
        self.assertIsNone(BibleReference.from_dict(d))

    def test_from_dict_invalid_chapter(self):
        """from_dict retorna None para capítulo inválido."""
        d = {"book_id": 43, "chapter": 0}
        self.assertIsNone(BibleReference.from_dict(d))

    def test_roundtrip_to_dict_from_dict(self):
        """to_dict → from_dict preserva dados."""
        ref1 = BibleReference(book=BibleBook.MATEUS, chapter=5, verse_start=1, verse_end=12)
        d = ref1.to_dict()
        ref2 = BibleReference.from_dict(d)
        self.assertIsNotNone(ref2)
        self.assertEqual(ref1, ref2)

    def test_roundtrip_to_string_from_string(self):
        """to_string → from_string preserva dados."""
        ref1 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        s = ref1.to_string()
        ref2 = BibleReference.from_string(s)
        self.assertIsNotNone(ref2)
        self.assertEqual(ref1, ref2)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestBibleReferenceParser(unittest.TestCase):
    """Testes do parser de strings → BibleReference."""

    def test_parse_single_verse(self):
        """Parser: João 3:16 → versículo único."""
        ref = parse_bible_reference("João 3:16")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.JOAO)
        self.assertEqual(ref.chapter, 3)
        self.assertEqual(ref.verse_start, 16)
        self.assertTrue(ref.is_single_verse)

    def test_parse_chapter_only(self):
        """Parser: Lucas 15 → capítulo inteiro."""
        ref = parse_bible_reference("Lucas 15")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.LUCAS)
        self.assertEqual(ref.chapter, 15)
        self.assertTrue(ref.is_chapter)

    def test_parse_range(self):
        """Parser: Mateus 5:1-12 → intervalo."""
        ref = parse_bible_reference("Mateus 5:1-12")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.MATEUS)
        self.assertEqual(ref.chapter, 5)
        self.assertEqual(ref.verse_start, 1)
        self.assertEqual(ref.verse_end, 12)
        self.assertTrue(ref.is_range)

    def test_parse_salmo_23(self):
        """Parser: Salmo 23 → Salmos 23."""
        ref = parse_bible_reference("Salmo 23")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.SALMOS)
        self.assertEqual(ref.chapter, 23)

    def test_parse_1_corintios_13(self):
        """Parser: 1 Coríntios 13 → capítulo."""
        ref = parse_bible_reference("1 Coríntios 13")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.PRIMEIRO_CORINTIOS)
        self.assertEqual(ref.chapter, 13)

    def test_parse_ii_reis_2(self):
        """Parser: II Reis 2 → 2 Reis 2 (numeral romano)."""
        ref = parse_bible_reference("II Reis 2")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.SEGUNDO_REIS)
        self.assertEqual(ref.chapter, 2)

    def test_parse_1_joao_4_8(self):
        """Parser: 1 João 4:8 → versículo único."""
        ref = parse_bible_reference("1 João 4:8")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.PRIMEIRO_JOAO)
        self.assertEqual(ref.chapter, 4)
        self.assertEqual(ref.verse_start, 8)

    def test_parse_apocalipse_21(self):
        """Parser: Apocalipse 21 → capítulo."""
        ref = parse_bible_reference("Apocalipse 21")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.APOCALIPSE)
        self.assertEqual(ref.chapter, 21)

    def test_parse_genesis_1_1(self):
        """Parser: Gênesis 1:1 → versículo único."""
        ref = parse_bible_reference("Gênesis 1:1")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.GENESIS)
        self.assertEqual(ref.chapter, 1)
        self.assertEqual(ref.verse_start, 1)

    def test_parse_case_insensitive(self):
        """Parser é case-insensitive."""
        ref = parse_bible_reference("joão 3:16")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.JOAO)

    def test_parse_no_accents(self):
        """Parser funciona sem acentos."""
        ref = parse_bible_reference("Joao 3:16")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.JOAO)

    def test_parse_with_extra_whitespace(self):
        """Parser tolera whitespace extra."""
        ref = parse_bible_reference("  João   3:16  ")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.JOAO)
        self.assertEqual(ref.chapter, 3)

    def test_parse_invalid_book(self):
        """Parser retorna None para livro inválido."""
        self.assertIsNone(parse_bible_reference("LivroInexistente 3:16"))

    def test_parse_empty_string(self):
        """Parser retorna None para string vazia."""
        self.assertIsNone(parse_bible_reference(""))
        self.assertIsNone(parse_bible_reference("   "))

    def test_parse_no_chapter(self):
        """Parser retorna None se não há capítulo."""
        self.assertIsNone(parse_bible_reference("João"))

    def test_parse_invalid_chapter_zero(self):
        """Parser retorna None para capítulo 0."""
        self.assertIsNone(parse_bible_reference("João 0"))

    def test_parse_invalid_verse_zero(self):
        """Parser retorna None para versículo 0."""
        self.assertIsNone(parse_bible_reference("João 3:0"))

    def test_parse_invalid_range(self):
        """Parser retorna None para intervalo inválido (end < start)."""
        self.assertIsNone(parse_bible_reference("João 3:16-10"))

    def test_parse_abbreviation(self):
        """Parser resolve abreviações."""
        ref = parse_bible_reference("Jo 3:16")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.JOAO)

    def test_parse_mateus_abbreviation(self):
        """Parser resolve abreviação 'Mt'."""
        ref = parse_bible_reference("Mt 5:1-12")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.MATEUS)

    def test_parse_from_string_classmethod(self):
        """BibleReference.from_string é equivalente a parse_bible_reference."""
        ref1 = BibleReference.from_string("João 3:16")
        ref2 = parse_bible_reference("João 3:16")
        self.assertEqual(ref1, ref2)


# ---------------------------------------------------------------------------
# Helpers em lote
# ---------------------------------------------------------------------------


class TestBatchHelpers(unittest.TestCase):
    """Testes de parse_references e references_to_strings."""

    def test_parse_references_valid(self):
        """parse_references converte lista de strings."""
        refs = parse_references(["João 3:16", "Lucas 15", "Mateus 5:1-12"])
        self.assertEqual(len(refs), 3)
        self.assertEqual(refs[0].book, BibleBook.JOAO)
        self.assertEqual(refs[1].book, BibleBook.LUCAS)
        self.assertEqual(refs[2].book, BibleBook.MATEUS)

    def test_parse_references_skips_invalid(self):
        """parse_references ignora strings inválidas."""
        refs = parse_references(["João 3:16", "InvalidBook 1", "Lucas 15"])
        self.assertEqual(len(refs), 2)

    def test_parse_references_empty(self):
        """parse_references retorna lista vazia para input vazio."""
        self.assertEqual(parse_references([]), [])

    def test_references_to_strings(self):
        """references_to_strings converte BibleReference → strings."""
        refs = parse_references(["João 3:16", "Lucas 15"])
        strings = references_to_strings(refs)
        self.assertEqual(strings, ["João 3:16", "Lucas 15"])

    def test_roundtrip_batch(self):
        """Roundtrip: strings → BibleReference → strings."""
        original = ["João 3:16", "Lucas 15:11-32", "Mateus 5:1-12", "Apocalipse 21"]
        refs = parse_references(original)
        result = references_to_strings(refs)
        self.assertEqual(result, original)


# ---------------------------------------------------------------------------
# Compatibilidade com Knowledge Base
# ---------------------------------------------------------------------------


class TestKnowledgeBaseCompatibility(unittest.TestCase):
    """Testa que a Knowledge Base carrega references como BibleReference."""

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase(KB_PATH)

    def test_references_are_bible_reference_objects(self):
        """references carregadas são BibleReference (não strings)."""
        entity = self.kb.get_entity("filho_prodigo")
        for ref in entity.references:
            self.assertIsInstance(ref, BibleReference)

    def test_references_parseable(self):
        """Todas as references carregadas são parseable."""
        entities = self.kb.all_entities()
        for entity in entities:
            for ref in entity.references:
                # to_string deve produzir string válida
                s = ref.to_string()
                self.assertTrue(s)
                # from_string deve conseguir reparsear
                reparsed = BibleReference.from_string(s)
                self.assertIsNotNone(reparsed, f"Cannot reparse: {s}")

    def test_filho_prodigo_reference(self):
        """filho_prodigo tem reference Lucas 15:11-32."""
        entity = self.kb.get_entity("filho_prodigo")
        self.assertGreater(len(entity.references), 0)
        ref = entity.references[0]
        self.assertEqual(ref.book, BibleBook.LUCAS)
        self.assertEqual(ref.chapter, 15)
        self.assertEqual(ref.verse_start, 11)
        self.assertEqual(ref.verse_end, 32)
        self.assertTrue(ref.is_range)

    def test_bom_pastor_reference(self):
        """bom_pastor tem reference João 10:1-18."""
        entity = self.kb.get_entity("bom_pastor")
        self.assertGreater(len(entity.references), 0)
        ref = entity.references[0]
        self.assertEqual(ref.book, BibleBook.JOAO)
        self.assertEqual(ref.chapter, 10)

    def test_monte_sinai_reference(self):
        """monte_sinai tem references Êxodo 19 e 20."""
        entity = self.kb.get_entity("monte_sinai")
        self.assertGreaterEqual(len(entity.references), 2)
        books = [r.book for r in entity.references]
        self.assertIn(BibleBook.EXODO, books)

    def test_enrich_returns_bible_reference_objects(self):
        """enrich retorna references como BibleReference."""
        from busca.knowledge_enricher import KnowledgeEnricher
        enricher = KnowledgeEnricher(self.kb)
        intent = Intent(action="search", query="filho pródigo",
                        confidence=0.8, source="llm", raw="filho pródigo")
        match = enricher.enrich(intent)
        self.assertTrue(match.is_found)
        for ref in match.references:
            self.assertIsInstance(ref, BibleReference)

    def test_enrich_reference_to_string(self):
        """enrich references podem ser convertidas para string."""
        from busca.knowledge_enricher import KnowledgeEnricher
        enricher = KnowledgeEnricher(self.kb)
        intent = Intent(action="search", query="filho pródigo",
                        confidence=0.8, source="llm", raw="filho pródigo")
        match = enricher.enrich(intent)
        self.assertTrue(match.is_found)
        strings = [r.to_string() for r in match.references]
        self.assertIn("Lucas 15:11-32", strings)

    def test_all_entities_references_valid(self):
        """Todas as entidades com references têm BibleReference válidas."""
        for entity in self.kb.all_entities():
            for ref in entity.references:
                self.assertIsInstance(ref, BibleReference)
                self.assertGreater(ref.chapter, 0)
                self.assertGreater(ref.book_id, 0)
                self.assertLessEqual(ref.book_id, 66)

    def test_json_unchanged(self):
        """JSON continua com strings (não foi modificado)."""
        import json
        with open(KB_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for concept in data["concepts"]:
            refs = concept.get("references", [])
            for r in refs:
                # No JSON ainda são strings
                self.assertIsInstance(r, str)


# ---------------------------------------------------------------------------
# Casos específicos da especificação
# ---------------------------------------------------------------------------


class TestSpecificationCases(unittest.TestCase):
    """Casos específicos listados na FASE 11."""

    def test_joao_3_16(self):
        """João 3:16 → BibleReference correto."""
        ref = parse_bible_reference("João 3:16")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.JOAO)
        self.assertEqual(ref.chapter, 3)
        self.assertEqual(ref.verse_start, 16)
        self.assertTrue(ref.is_single_verse)

    def test_lucas_15(self):
        """Lucas 15 → BibleReference correto."""
        ref = parse_bible_reference("Lucas 15")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.LUCAS)
        self.assertEqual(ref.chapter, 15)
        self.assertTrue(ref.is_chapter)

    def test_mateus_5_1_12(self):
        """Mateus 5:1-12 → BibleReference correto."""
        ref = parse_bible_reference("Mateus 5:1-12")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.MATEUS)
        self.assertEqual(ref.chapter, 5)
        self.assertEqual(ref.verse_start, 1)
        self.assertEqual(ref.verse_end, 12)
        self.assertTrue(ref.is_range)
        self.assertEqual(ref.length, 12)

    def test_salmo_23(self):
        """Salmo 23 → BibleReference correto (Salmos)."""
        ref = parse_bible_reference("Salmo 23")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.SALMOS)
        self.assertEqual(ref.chapter, 23)
        self.assertTrue(ref.is_chapter)

    def test_1_corintios_13(self):
        """1 Coríntios 13 → BibleReference correto."""
        ref = parse_bible_reference("1 Coríntios 13")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.PRIMEIRO_CORINTIOS)
        self.assertEqual(ref.chapter, 13)

    def test_ii_reis_2(self):
        """II Reis 2 → BibleReference correto (numeral romano)."""
        ref = parse_bible_reference("II Reis 2")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.SEGUNDO_REIS)
        self.assertEqual(ref.chapter, 2)

    def test_1_joao_4_8(self):
        """1 João 4:8 → BibleReference correto."""
        ref = parse_bible_reference("1 João 4:8")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.PRIMEIRO_JOAO)
        self.assertEqual(ref.chapter, 4)
        self.assertEqual(ref.verse_start, 8)

    def test_apocalipse_21(self):
        """Apocalipse 21 → BibleReference correto."""
        ref = parse_bible_reference("Apocalipse 21")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.book, BibleBook.APOCALIPSE)
        self.assertEqual(ref.chapter, 21)


# ---------------------------------------------------------------------------
# Property id — identificador canônico (FASE 7.7)
# ---------------------------------------------------------------------------


class TestBibleReferenceId(unittest.TestCase):
    """Testes da property `id` (identificador canônico calculado)."""

    def test_id_chapter_only(self):
        """ID para capítulo: 'book_id:chapter'."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3)
        self.assertEqual(ref.id, "43:3")

    def test_id_single_verse(self):
        """ID para versículo único: 'book_id:chapter:verse'."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        self.assertEqual(ref.id, "43:3:16")

    def test_id_range(self):
        """ID para intervalo: 'book_id:chapter:start-end'."""
        ref = BibleReference(book=BibleBook.LUCAS, chapter=15, verse_start=11, verse_end=32)
        self.assertEqual(ref.id, "42:15:11-32")

    def test_id_genesis_1_1(self):
        """ID para Gênesis 1:1."""
        ref = BibleReference(book=BibleBook.GENESIS, chapter=1, verse_start=1)
        self.assertEqual(ref.id, "1:1:1")

    def test_id_apocalipse_21(self):
        """ID para Apocalipse 21 (capítulo)."""
        ref = BibleReference(book=BibleBook.APOCALIPSE, chapter=21)
        self.assertEqual(ref.id, "66:21")

    def test_id_mateus_5_1_12(self):
        """ID para Mateus 5:1-12 (intervalo)."""
        ref = BibleReference(book=BibleBook.MATEUS, chapter=5, verse_start=1, verse_end=12)
        self.assertEqual(ref.id, "40:5:1-12")

    def test_id_single_verse_with_verse_end_equal(self):
        """ID para versículo único com verse_end == verse_start (não é range)."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16, verse_end=16)
        self.assertEqual(ref.id, "43:3:16")

    def test_id_is_readonly(self):
        """id é property somente leitura — não pode ser atribuído."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        with self.assertRaises(Exception):
            ref.id = "99:1"  # type: ignore

    def test_id_is_property_not_attribute(self):
        """id é uma property, não um campo armazenado."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        # id não aparece como campo no dataclass
        import dataclasses
        field_names = [f.name for f in dataclasses.fields(ref)]
        self.assertNotIn("id", field_names)

    def test_id_uniqueness_different_books(self):
        """IDs são únicos para livros diferentes."""
        ref1 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ref2 = BibleReference(book=BibleBook.LUCAS, chapter=3, verse_start=16)
        self.assertNotEqual(ref1.id, ref2.id)

    def test_id_uniqueness_different_chapters(self):
        """IDs são únicos para capítulos diferentes no mesmo livro."""
        ref1 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ref2 = BibleReference(book=BibleBook.JOAO, chapter=4, verse_start=16)
        self.assertNotEqual(ref1.id, ref2.id)

    def test_id_uniqueness_different_verses(self):
        """IDs são únicos para versículos diferentes no mesmo capítulo."""
        ref1 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ref2 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=17)
        self.assertNotEqual(ref1.id, ref2.id)

    def test_id_consistency(self):
        """ID é consistente — mesma referência sempre produz mesmo ID."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        id1 = ref.id
        id2 = ref.id
        self.assertEqual(id1, id2)

    def test_id_derived_from_state(self):
        """ID é derivado do estado — não armazenado."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        # ID deve refletir book_id, chapter, verse_start
        self.assertEqual(ref.id, f"{ref.book_id}:{ref.chapter}:{ref.verse_start}")

    def test_id_does_not_affect_hash(self):
        """id não afeta hash (hash é baseado em book, chapter, verses)."""
        ref1 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ref2 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        self.assertEqual(hash(ref1), hash(ref2))

    def test_id_does_not_affect_serialization(self):
        """id não aparece em to_dict (não é persistido)."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        d = ref.to_dict()
        self.assertNotIn("id", d)

    def test_id_from_parsed_reference(self):
        """ID funciona em referências criadas via parser."""
        ref = parse_bible_reference("João 3:16")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.id, "43:3:16")

    def test_id_from_parsed_chapter(self):
        """ID funciona em capítulos criados via parser."""
        ref = parse_bible_reference("Apocalipse 21")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.id, "66:21")

    def test_id_from_parsed_range(self):
        """ID funciona em intervalos criados via parser."""
        ref = parse_bible_reference("Lucas 15:11-32")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.id, "42:15:11-32")

    def test_id_all_66_books(self):
        """ID funciona para todos os 66 livros."""
        for book in BibleBook:
            ref = BibleReference(book=book, chapter=1)
            expected = f"{int(book)}:1"
            self.assertEqual(ref.id, expected,
                             f"Wrong id for {book.canonical_name}")

    def test_id_can_be_used_as_dict_key(self):
        """ID pode ser usado como chave de dict (é string)."""
        ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        d = {ref.id: "value"}
        self.assertEqual(d["43:3:16"], "value")

    def test_id_chapter_vs_verse_distinct(self):
        """ID de capítulo é diferente de ID de versículo no mesmo capítulo."""
        chapter_ref = BibleReference(book=BibleBook.JOAO, chapter=3)
        verse_ref = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        self.assertNotEqual(chapter_ref.id, verse_ref.id)
        self.assertEqual(chapter_ref.id, "43:3")
        self.assertEqual(verse_ref.id, "43:3:16")


# ---------------------------------------------------------------------------
# Preparação para o futuro
# ---------------------------------------------------------------------------


class TestFutureReadiness(unittest.TestCase):
    """Testa que a estrutura facilita futuras funcionalidades."""

    def test_can_compare_same_book(self):
        """Referências do mesmo livro podem ser comparadas."""
        ref1 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ref2 = BibleReference(book=BibleBook.JOAO, chapter=4, verse_start=1)
        self.assertLess(ref1, ref2)

    def test_can_group_by_book(self):
        """Referências podem ser agrupadas por livro."""
        refs = [
            BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16),
            BibleReference(book=BibleBook.LUCAS, chapter=15),
            BibleReference(book=BibleBook.JOAO, chapter=4, verse_start=1),
        ]
        by_book: dict[int, list] = {}
        for r in refs:
            by_book.setdefault(r.book_id, []).append(r)
        self.assertEqual(len(by_book[43]), 2)  # João
        self.assertEqual(len(by_book[42]), 1)  # Lucas

    def test_can_identify_same_chapter(self):
        """Referências podem identificar capítulos iguais."""
        ref1 = BibleReference(book=BibleBook.LUCAS, chapter=15, verse_start=11)
        ref2 = BibleReference(book=BibleBook.LUCAS, chapter=15, verse_start=25)
        self.assertEqual(ref1.book_id, ref2.book_id)
        self.assertEqual(ref1.chapter, ref2.chapter)

    def test_can_sort_references(self):
        """Referências podem ser ordenadas."""
        refs = [
            BibleReference(book=BibleBook.APOCALIPSE, chapter=21),
            BibleReference(book=BibleBook.GENESIS, chapter=1),
            BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16),
        ]
        refs_sorted = sorted(refs)
        self.assertEqual(refs_sorted[0].book, BibleBook.GENESIS)
        self.assertEqual(refs_sorted[1].book, BibleBook.JOAO)
        self.assertEqual(refs_sorted[2].book, BibleBook.APOCALIPSE)

    def test_can_use_in_set(self):
        """Referências podem ser usadas em set (deduplicação)."""
        ref1 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ref2 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=16)
        ref3 = BibleReference(book=BibleBook.JOAO, chapter=3, verse_start=17)
        s = {ref1, ref2, ref3}
        self.assertEqual(len(s), 2)  # ref1 == ref2 → 2 únicos

    def test_metadata_extensible(self):
        """metadata permite extensão futura."""
        ref = BibleReference(
            book=BibleBook.JOAO,
            chapter=3,
            verse_start=16,
            metadata={"source": "knowledge_base", "confidence": 0.95},
        )
        self.assertEqual(ref.metadata["source"], "knowledge_base")
        self.assertEqual(ref.metadata["confidence"], 0.95)

    def test_version_field(self):
        """version permite especificar versão bíblica."""
        ref = BibleReference(
            book=BibleBook.JOAO,
            chapter=3,
            verse_start=16,
            version="ACF",
        )
        self.assertEqual(ref.version, "ACF")


if __name__ == "__main__":
    unittest.main()
