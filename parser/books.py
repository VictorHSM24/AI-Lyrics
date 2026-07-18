"""Resolução de livros bíblicos para o parser determinístico.

Re-exporta ``Book``, ``BookTable``, ``BookMatch`` de ``config.books`` (não
redefine) e adiciona ``ParserBookTable`` com:

  - Normalização completa via ``Normalizer`` (lowercase, diacritics,
    ordinais, romanos, extenso) — alinhada com o pipeline do parser.
  - Resolução de ambiguidades por **prioridade** (campo ``priority`` no
    ``books.json``; maior prioridade vence).
  - **Confiança** da correspondência (1.0 para alias única; 0.5 para alias
    ambígua resolvida por prioridade).
  - **Longest-match** para evitar conflitos entre livros semelhantes
    (ex.: "1 João" vs "João").

Estratégias adotadas (vide relatório técnico de ambiguidades):
  - **Estratégia A**: aliases ambíguas retornam ``confidence=0.5`` e
    ``ambiguous=True`` — o parser pode acionar fallback LLM.
  - **Estratégia C**: prioridade por frequência litúrgica no
    ``books.json`` (João > Josué > Jó para "jo"; Hebreus > Habacuque
    para "hb"; Esdras = Ezequiel para "ez" — genuinamente ambíguo).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Final

from config.books import Book, BookMatch, BookTable, _normalize_alias
from parser.normalizer import Normalizer

__all__ = [
    "Book",
    "BookMatch",
    "BookTable",
    "BookResolveResult",
    "ParserBookTable",
    "load_parser_books",
]

# Confiança para alias ambígua resolvida por prioridade.
_AMBIGUOUS_CONFIDENCE: Final[float] = 0.5

# Confiança para alias única (não ambígua).
_UNIQUE_CONFIDENCE: Final[float] = 1.0


@dataclass(frozen=True)
class BookResolveResult:
    """Resultado da resolução de livro via ``ParserBookTable``.

    Diferencia-se de ``BookMatch`` por incluir confiança e flag de
    ambiguidade, permitindo ao parser decidir sobre fallback LLM.
    """

    book: Book
    matched_alias: str  # alias original (não normalizada)
    confidence: float  # 0.0..1.0
    ambiguous: bool  # True se a alias mapeia para >1 livro
    start: int  # índice na string de entrada normalizada
    end: int


class ParserBookTable:
    """Índice de livros bíblicos com resolução por prioridade e confiança.

    Diferencia-se de ``config.books.BookTable`` por:
      1. Usar ``Normalizer`` (não apenas lowercase+diacritics) para
         normalizar aliases e input — alinhado com o pipeline do parser.
      2. Resolver ambiguidades por ``priority`` (maior vence).
      3. Retornar ``BookResolveResult`` com ``confidence`` e ``ambiguous``.

    Args:
        books: lista de ``Book`` (tipicamente de ``load_books``).
        normalizer: instância de ``Normalizer`` (criada internamente se
            omitida).
    """

    def __init__(
        self,
        books: list[Book],
        normalizer: Normalizer | None = None,
    ) -> None:
        self._normalizer = normalizer or Normalizer()
        self._by_id: dict[int, Book] = {b.id: b for b in books}

        # Mapear alias normalizada -> (Book, alias_original).
        # Para ambiguidades: maior priority vince; empate = menor ID.
        self._by_alias: dict[str, tuple[Book, str]] = {}
        # Rastrear quais aliases são ambíguas (mapeiam para >1 livro).
        self._ambiguous: set[str] = set()

        # Primeiro, agrupar todas as aliases por forma normalizada.
        alias_groups: dict[str, list[tuple[Book, str]]] = {}
        for book in books:
            for alias in book.aliases:
                norm = self._normalizer.normalize(alias)
                if not norm:
                    continue
                alias_groups.setdefault(norm, []).append((book, alias))

        # Resolver cada grupo.
        for norm, group in alias_groups.items():
            unique_books = set(t[0].id for t in group)
            if len(unique_books) > 1:
                self._ambiguous.add(norm)
                # Escolher pelo maior priority; empate = menor ID.
                best = max(group, key=lambda t: (t[0].priority, -t[0].id))
            else:
                # Alias não ambígua — usar a primeira ocorrência.
                best = group[0]
            self._by_alias[norm] = best

        # Ordenar aliases por len desc para longest-match.
        self._sorted_aliases: list[str] = sorted(
            self._by_alias.keys(), key=len, reverse=True
        )

    def resolve(self, raw: str) -> BookResolveResult | None:
        """Resolve ``raw`` para um ``BookResolveResult`` via longest-match.

        Normaliza ``raw`` com ``Normalizer`` (lowercase, diacritics,
        ordinais, romanos, extenso) e procura a alias mais longa que
        aparece como **palavra completa** (word-boundary) em ``raw``.

        Args:
            raw: texto de entrada (tipicamente saída do STT normalizada
                ou não — o método normaliza internamente).

        Returns:
            ``BookResolveResult`` com confiança e flag de ambiguidade,
            ou ``None`` se nenhuma alias casar.
        """
        norm = self._normalizer.normalize(raw)
        if not norm:
            return None

        for alias_norm in self._sorted_aliases:
            idx = self._word_find(norm, alias_norm)
            if idx != -1:
                book, alias_original = self._by_alias[alias_norm]
                is_amb = alias_norm in self._ambiguous
                confidence = _AMBIGUOUS_CONFIDENCE if is_amb else _UNIQUE_CONFIDENCE
                return BookResolveResult(
                    book=book,
                    matched_alias=alias_original,
                    confidence=confidence,
                    ambiguous=is_amb,
                    start=idx,
                    end=idx + len(alias_norm),
                )
        return None

    def by_id(self, book_id: int) -> Book:
        """Retorna o ``Book`` com ``book_id`` ou levanta ``KeyError``."""
        if book_id not in self._by_id:
            raise KeyError(f"book_id {book_id} not found (valid range: 1..66)")
        return self._by_id[book_id]

    def all_books(self) -> list[Book]:
        """Retorna todos os livros ordenados por ID."""
        return [self._by_id[i] for i in sorted(self._by_id)]

    def ambiguous_aliases(self) -> set[str]:
        """Retorna o conjunto de aliases normalizadas que são ambíguas."""
        return set(self._ambiguous)

    @staticmethod
    def _word_find(text: str, word: str) -> int:
        """Encontra ``word`` em ``text`` respeitando word boundaries.

        Retorna o índice do início do match, ou -1 se não encontrado.
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


def load_parser_books(
    path: str = "config/books.json",
    normalizer: Normalizer | None = None,
) -> ParserBookTable:
    """Carrega ``books.json`` e retorna ``ParserBookTable``.

    Args:
        path: caminho para o arquivo JSON.
        normalizer: instância de ``Normalizer`` (criada internamente se
            omitida).

    Returns:
        ``ParserBookTable`` com os 66 livros.

    Raises:
        FileNotFoundError: arquivo ausente.
        ValueError: JSON inválido ou schema incorreto.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"books file not found: {path}")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError(f"books root must be a list, got {type(raw).__name__}")
    books: list[Book] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"books[{i}] must be an object")
        if "id" not in entry or "canonical" not in entry or "aliases" not in entry:
            raise ValueError(f"books[{i}] missing required field")
        book_id = entry["id"]
        if not isinstance(book_id, int) or not (1 <= book_id <= 66):
            raise ValueError(f"books[{i}].id must be int in 1..66, got {book_id!r}")
        books.append(
            Book(
                id=book_id,
                canonical=str(entry["canonical"]),
                aliases=list(entry["aliases"]),
                priority=int(entry.get("priority", 0)),
            )
        )
    if len(books) != 66:
        raise ValueError(f"expected 66 books, got {len(books)}")
    return ParserBookTable(books, normalizer=normalizer)
