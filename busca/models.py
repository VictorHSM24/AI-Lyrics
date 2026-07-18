"""Modelos de dados do indexador FTS5."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerseRow:
    """Uma linha da tabela FTS5 ``verses``.

    Campos alinhados com ``bible_source.json`` (Blueprint §2) e o schema
    FTS5 da doc. técnica §5.5.
    """

    book: str          # nome canônico PT-BR (ex.: "João")
    book_id: int       # 1..66
    chapter: int
    verse: int
    text: str
    version: str       # ex.: "ACF"

    @property
    def id(self) -> str:
        """ID no formato BBCCCVVV (zero-padded)."""
        return f"{self.book_id:02d}{self.chapter:03d}{self.verse:03d}"


@dataclass(frozen=True)
class IndexStats:
    """Estatísticas de uma importação/rebuild do índice."""

    db_path: str
    total_verses: int          # total de linhas na tabela verses
    versions: list[str]        # versões presentes
    verses_per_version: dict[str, int]
    skipped_invalid: int       # versículos pulados (book_id fora de range, texto vazio)
    duration_ms: float
    rebuilt: bool              # True se a tabela foi dropada e recriada
