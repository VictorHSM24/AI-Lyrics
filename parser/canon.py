"""Limites canônicos (capítulos por livro, versículos por capítulo).

Usado pelo parser de fala para NUNCA emitir uma referência
canonicamente impossível (ex.: "Amós 19:99" — Amós tem 9 capítulos).

Fonte: ``config/canon_bounds.json``, gerado de forma determinística a
partir da base FTS5 local por ``scripts/build_canon_bounds.py``. Se o
arquivo não existir, cai para a contagem padrão de capítulos (sem
validação de versículo).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

__all__ = ["CanonBounds", "load_canon_bounds", "STANDARD_CHAPTERS"]

# Capítulos por livro no cânon protestante (ids 1..66).
STANDARD_CHAPTERS: tuple[int, ...] = (
    50, 40, 27, 36, 34, 24, 21, 4, 31, 24, 22, 25, 29, 36, 10, 13, 10, 42,
    150, 31, 12, 8, 66, 52, 5, 48, 12, 14, 3, 9, 1, 4, 7, 3, 3, 3, 2, 14, 4,
    28, 16, 24, 21, 28, 16, 16, 13, 6, 6, 4, 4, 5, 3, 6, 4, 3, 1, 13, 5, 5,
    3, 5, 1, 1, 1, 22,
)


class CanonBounds:
    """Consulta de limites canônicos por livro/capítulo.

    Args:
        verses_per_chapter: ``{book_id: [max_verse_cap1, max_verse_cap2, ...]}``.
            Se ``None``, apenas a contagem padrão de capítulos é validada.
    """

    def __init__(self, verses_per_chapter: dict[int, list[int]] | None = None) -> None:
        self._verses = verses_per_chapter or {}

    def chapters(self, book_id: int) -> int:
        """Número de capítulos do livro (0 se id inválido)."""
        if book_id in self._verses:
            return len(self._verses[book_id])
        if 1 <= book_id <= 66:
            return STANDARD_CHAPTERS[book_id - 1]
        return 0

    def max_verse(self, book_id: int, chapter: int) -> int | None:
        """Maior versículo do capítulo, ou ``None`` se desconhecido."""
        verses = self._verses.get(book_id)
        if not verses or not (1 <= chapter <= len(verses)):
            return None
        return verses[chapter - 1]

    def valid_chapter(self, book_id: int, chapter: int) -> bool:
        return 1 <= chapter <= self.chapters(book_id)

    def valid_verse(self, book_id: int, chapter: int, verse: int) -> bool:
        if not self.valid_chapter(book_id, chapter) or verse < 1:
            return False
        mv = self.max_verse(book_id, chapter)
        return mv is None or verse <= mv


@lru_cache(maxsize=4)
def load_canon_bounds(path: str = "config/canon_bounds.json") -> CanonBounds:
    """Carrega os limites (cacheado). Nunca levanta — cai para o padrão."""
    try:
        from core.paths import resource_path
        resolved = resource_path(path)
        with open(resolved, encoding="utf-8") as f:
            raw = json.load(f)
        data = {int(k): [int(x) for x in v] for k, v in raw.items()}
        return CanonBounds(data)
    except Exception as e:  # arquivo ausente/corrompido → só capítulos
        logger.warning(
            "canon bounds indisponível (%s): validando apenas capítulos.", e,
        )
        return CanonBounds()
