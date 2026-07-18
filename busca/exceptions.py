"""Exceções do módulo busca."""

from __future__ import annotations

from core.exceptions import AILyricsError


class SearchError(AILyricsError):
    """Erro genérico do módulo de busca."""


class IndexerError(SearchError):
    """Erro durante construção/rebuild do índice FTS5."""
