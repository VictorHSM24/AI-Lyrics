"""Tipos de domínio para livros bíblicos e tabela canônica de aliases.

``BookTable`` é singleton compartilhado entre ``parser``, ``estado`` e
``core/decision`` para garantir consistência livro↔ID.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def _normalize_alias(s: str) -> str:
    """Normaliza string para busca: lowercase, sem diacritics, whitespace único."""
    nfkd = unicodedata.normalize("NFKD", s)
    without_diacritics = "".join(c for c in nfkd if not unicodedata.combining(c))
    collapsed = re.sub(r"\s+", " ", without_diacritics)
    return collapsed.strip().lower()


@dataclass(frozen=True)
class Book:
    """Livro canônico da Bíblia."""

    id: int  # 1..66
    canonical: str  # "1 Coríntios"
    aliases: list[str]  # ["1 coríntios", "i coríntios", ...]
    priority: int = 0  # prioridade para desambiguação de aliases (maior = preferido)


@dataclass
class BookMatch:
    """Resultado de uma resolução de livro via BookTable."""

    book: Book
    matched_alias: str
    start: int  # índice na string de entrada normalizada
    end: int


class BookTable:
    """Índice de livros bíblicos com resolução por alias (longest-match)."""

    def __init__(self, books: list[Book]) -> None:
        self._by_id: dict[int, Book] = {b.id: b for b in books}
        # Mapeia alias normalizada -> (Book, alias_original).
        self._by_alias: dict[str, tuple[Book, str]] = {}
        for book in books:
            for alias in book.aliases:
                norm = _normalize_alias(alias)
                if norm in self._by_alias and self._by_alias[norm][0].id != book.id:
                    # Alias duplicada entre livros — não fatal; longest-match resolve.
                    # O livro com ID menor (geralmente o sem ordinal) prevalece.
                    existing_book, _ = self._by_alias[norm]
                    if book.id < existing_book.id:
                        self._by_alias[norm] = (book, alias)
                else:
                    self._by_alias[norm] = (book, alias)
        # Ordenar aliases normalizadas por len desc para longest-match.
        self._sorted_aliases: list[str] = sorted(self._by_alias.keys(), key=len, reverse=True)

    def resolve(self, raw: str) -> BookMatch | None:
        """Resolve ``raw`` para um ``BookMatch`` via longest-match contra aliases.

        Normaliza ``raw`` (lowercase, sem acentos) e procura a alias mais longa
        que aparece como **palavra completa** (word-boundary) em ``raw``.
        Retorna ``None`` se nenhuma alias casar.
        """
        norm = _normalize_alias(raw)
        if not norm:
            return None
        for alias_norm in self._sorted_aliases:
            idx = self._word_find(norm, alias_norm)
            if idx != -1:
                book, alias_original = self._by_alias[alias_norm]
                return BookMatch(
                    book=book,
                    matched_alias=alias_original,
                    start=idx,
                    end=idx + len(alias_norm),
                )
        return None

    @staticmethod
    def _word_find(text: str, word: str) -> int:
        """Encontra ``word`` em ``text`` respeitando word boundaries.

        Retorna o índice do início do match, ou -1 se não encontrado.
        Word boundary: início/fim da string ou caractere não alfanumérico
        (espaço, pontuação) antes e depois do match.
        """
        idx = 0
        while True:
            pos = text.find(word, idx)
            if pos == -1:
                return -1
            before_ok = pos == 0 or not text[pos - 1].isalnum()
            after_pos = pos + len(word)
            after_ok = after_pos >= len(text) or not text[after_pos].isalnum()
            if before_ok and after_ok:
                return pos
            idx = pos + 1

    def by_id(self, book_id: int) -> Book:
        """Retorna o ``Book`` com ``book_id`` ou levanta ``KeyError``."""
        if book_id not in self._by_id:
            raise KeyError(f"book_id {book_id} not found (valid range: 1..66)")
        return self._by_id[book_id]

    def all_books(self) -> list[Book]:
        """Retorna todos os livros ordenados por ID."""
        return [self._by_id[i] for i in sorted(self._by_id)]
