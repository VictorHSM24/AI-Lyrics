"""Modelos de dados do módulo Holyrics.

Dataclasses para tipar as respostas da API do Holyrics.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BibleVersion:
    """Versão/tradução da Bíblia disponível no Holyrics.

    Campos conforme ``GetBibleVersionsV2``:
      - ``key``: ID do item (ex.: ``"pt_acf"``)
      - ``version``: ID da versão da Bíblia (ex.: ``"pt_acf"``)
      - ``title``: nome da versão (ex.: ``"Almeida Corrigida Fiel"``)
      - ``language``: idioma (opcional, v2.24.0+)
    """

    key: str
    version: str
    title: str
    language: str | None = None


@dataclass(frozen=True)
class TokenInfo:
    """Informações do token (resposta de ``GetTokenInfo``, v2.25.0+)."""

    version: str
    permissions: str


@dataclass(frozen=True)
class ShowVerseResult:
    """Resultado de uma chamada ``ShowVerse``.

    ShowVerse é um ``método sem retorno`` (sem campo ``data``).
    A API apenas confirma ``{"status": "ok"}``.
    """

    status: str
    verse_id: str  # BBCCCVVV enviado
    book_id: int
    chapter: int
    verse: int | None
    version: str


@dataclass(frozen=True)
class HolyricsResponse:
    """Resposta genérica da API do Holyrics."""

    status: str
    data: dict | list | None = None
    error: str | None = None
