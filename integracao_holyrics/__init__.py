"""Módulo de integração com o Holyrics via API REST oficial.

API pública:
    HolyricsClient  — cliente HTTP para ShowVerse, GetBibleVersionsV2, etc.
    BibleVersion, TokenInfo, ShowVerseResult — modelos de resposta.
    HolyricsError e subclasses — exceções de domínio.
"""

from integracao_holyrics.client import HolyricsClient
from integracao_holyrics.exceptions import (
    HolyricsAPIError,
    HolyricsAuthError,
    HolyricsConnectionError,
    HolyricsError,
    HolyricsTimeoutError,
)
from integracao_holyrics.models import BibleVersion, HolyricsResponse, ShowVerseResult, TokenInfo

__all__ = [
    "HolyricsClient",
    "BibleVersion",
    "TokenInfo",
    "ShowVerseResult",
    "HolyricsResponse",
    "HolyricsError",
    "HolyricsConnectionError",
    "HolyricsTimeoutError",
    "HolyricsAuthError",
    "HolyricsAPIError",
]
