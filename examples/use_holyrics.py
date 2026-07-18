"""Exemplo de uso do módulo integracao_holyrics.

Executa: python examples/use_holyrics.py

Este exemplo usa mocks para simular respostas do Holyrics — não requer
Holyrics rodando. Para testar com Holyrics real, descomente a seção
"Holyrics real" e ajuste o token.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from integracao_holyrics import (
    BibleVersion,
    HolyricsClient,
    HolyricsConnectionError,
    ShowVerseResult,
    TokenInfo,
)


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = str(json_data or {})
    resp.json.return_value = json_data or {}
    return resp


def demo_with_mocks() -> None:
    """Demonstra o cliente usando mocks (sem Holyrics real)."""
    print("=== Demo com mocks (sem Holyrics real) ===\n")

    client = HolyricsClient(
        base_url="http://127.0.0.1:3000/api",
        token="demo-token",
        timeout_s=2.0,
        max_retries=1,
    )

    # --- test_connection ---
    with patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _mock_response(
            200,
            {"status": "ok", "data": {"version": "2.25.0", "permissions": "ShowVerse,GetBibleVersionsV2"}},
        )
        connected = client.test_connection()
        print(f"test_connection() -> {connected}")

        info = client.get_token_info()
        print(f"get_token_info()  -> version={info.version}, permissions={info.permissions}")

    # --- get_bible_versions ---
    with patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _mock_response(
            200,
            {
                "status": "ok",
                "data": [
                    {"key": "pt_acf", "version": "pt_acf", "title": "Almeida Corrigida Fiel",
                     "language": {"name": "Portuguese"}},
                    {"key": "pt_nvi", "version": "pt_nvi", "title": "Nova Versão Internacional",
                     "language": {"name": "Portuguese"}},
                    {"key": "en_kjv", "version": "en_kjv", "title": "King James Version",
                     "language": {"name": "English"}},
                ],
            },
        )
        versions = client.get_bible_versions()
        print(f"\nget_bible_versions() -> {len(versions)} versões:")
        for v in versions:
            print(f"  {v.key:10s}  {v.title:40s}  lang={v.language}")

    # --- show_verse ---
    with patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _mock_response(200, {"status": "ok"})
        result = client.show_verse(43, 3, 16, version="ACF")
        print(f"\nshow_verse(43, 3, 16, 'ACF') -> status={result.status}, verse_id={result.verse_id}")

        result2 = client.show_verse(19, 23, 1, version="pt_acf", quick=True)
        print(f"show_verse(19, 23, 1, 'pt_acf', quick=True) -> verse_id={result2.verse_id}")

    # --- show_verse_references ---
    with patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _mock_response(200, {"status": "ok"})
        resp = client.show_verse_references("João 3:16", version="ACF")
        print(f"\nshow_verse_references('João 3:16') -> status={resp['status']}")

    # --- Holyrics offline ---
    with patch.object(client._session, "post") as mock_post:
        mock_post.side_effect = requests.exceptions.ConnectionError("refused")
        connected = client.test_connection()
        print(f"\ntest_connection() com Holyrics offline -> {connected}")

    print("\n=== Demo concluído ===")


def demo_with_real_holyrics() -> None:
    """Demonstra o cliente com Holyrics real (descomente para usar)."""
    token = os.environ.get("HOLYRICS_TOKEN", "")
    if not token:
        print("\n[Holyrics real] Defina HOLYRICS_TOKEN para testar com Holyrics real.")
        return

    client = HolyricsClient(
        base_url="http://127.0.0.1:3000/api",
        token=token,
        timeout_s=2.0,
        max_retries=1,
    )

    print("\n=== Holyrics real ===")
    if not client.test_connection():
        print("Holyrics offline. Verifique se o API Server está ativo.")
        return

    print("Holyrics online!")
    versions = client.get_bible_versions()
    print(f"Versões disponíveis: {len(versions)}")
    for v in versions[:5]:
        print(f"  {v.key}: {v.title}")

    # Exibe João 3:16
    result = client.show_verse(43, 3, 16, version="ACF")
    print(f"ShowVerse -> {result.status} ({result.verse_id})")


if __name__ == "__main__":
    demo_with_mocks()
    demo_with_real_holyrics()
