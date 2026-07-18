"""Testes unitários do módulo integracao_holyrics.

Usa ``unittest.mock`` para simular respostas HTTP — nenhum Holyrics real é necessário.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from integracao_holyrics import (
    BibleVersion,
    HolyricsAPIError,
    HolyricsAuthError,
    HolyricsClient,
    HolyricsConnectionError,
    HolyricsTimeoutError,
    ShowVerseResult,
    TokenInfo,
)
from integracao_holyrics.client import _format_verse_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
) -> MagicMock:
    """Cria um mock de requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text or (str(json_data) if json_data else "")
    resp.json.return_value = json_data or {}
    return resp


def _make_client(**kwargs) -> HolyricsClient:
    """Cria um HolyricsClient com defaults de teste."""
    defaults = {
        "base_url": "http://127.0.0.1:3000/api",
        "token": "test-token",
        "timeout_s": 2.0,
        "max_retries": 1,
    }
    defaults.update(kwargs)
    return HolyricsClient(**defaults)


# ---------------------------------------------------------------------------
# _format_verse_id
# ---------------------------------------------------------------------------

class TestFormatVerseId:
    def test_basic(self) -> None:
        assert _format_verse_id(43, 3, 16) == "43003016"

    def test_single_digit_book(self) -> None:
        assert _format_verse_id(1, 1, 1) == "01001001"

    def test_large_chapter(self) -> None:
        assert _format_verse_id(19, 23, 1) == "19023001"

    def test_verse_none_chapter_only(self) -> None:
        assert _format_verse_id(43, 3, None) == "43003000"

    def test_max_book_id(self) -> None:
        assert _format_verse_id(66, 1, 1) == "66001001"


# ---------------------------------------------------------------------------
# test_connection / health_check
# ---------------------------------------------------------------------------

class TestConnection:
    @patch("integracao_holyrics.client.requests.Session.post")
    def test_test_connection_success(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(
            200,
            {"status": "ok", "data": {"version": "2.25.0", "permissions": "ShowVerse"}},
        )
        client = _make_client()
        assert client.test_connection() is True

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_test_connection_offline(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = requests.exceptions.ConnectionError("refused")
        client = _make_client()
        assert client.test_connection() is False

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_test_connection_auth_error(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(403, {"status": "error", "error": "invalid token"})
        client = _make_client()
        assert client.test_connection() is False

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_health_check_alias(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(
            200,
            {"status": "ok", "data": {"version": "2.25.0", "permissions": "ShowVerse"}},
        )
        client = _make_client()
        assert client.health_check() is True


# ---------------------------------------------------------------------------
# get_token_info
# ---------------------------------------------------------------------------

class TestGetTokenInfo:
    @patch("integracao_holyrics.client.requests.Session.post")
    def test_success(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(
            200,
            {"status": "ok", "data": {"version": "2.25.0", "permissions": "ShowVerse,GetBibleVersionsV2"}},
        )
        client = _make_client()
        info = client.get_token_info()
        assert isinstance(info, TokenInfo)
        assert info.version == "2.25.0"
        assert "ShowVerse" in info.permissions

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_auth_error(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(403, {"status": "error", "error": "invalid token"})
        client = _make_client()
        with pytest.raises(HolyricsAuthError, match="authentication failed"):
            client.get_token_info()


# ---------------------------------------------------------------------------
# get_bible_versions
# ---------------------------------------------------------------------------

class TestGetBibleVersions:
    @patch("integracao_holyrics.client.requests.Session.post")
    def test_success(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(
            200,
            {
                "status": "ok",
                "data": [
                    {
                        "key": "pt_acf",
                        "version": "pt_acf",
                        "title": "Almeida Corrigida Fiel",
                        "language": {"id": "pt", "iso": "pt", "name": "Portuguese", "alt_name": "Português"},
                    },
                    {
                        "key": "en_kjv",
                        "version": "en_kjv",
                        "title": "King James Version",
                        "language": {"id": "en", "iso": "en", "name": "English", "alt_name": "English"},
                    },
                ],
            },
        )
        client = _make_client()
        versions = client.get_bible_versions()
        assert len(versions) == 2
        assert isinstance(versions[0], BibleVersion)
        assert versions[0].key == "pt_acf"
        assert versions[0].title == "Almeida Corrigida Fiel"
        assert versions[0].language == "Portuguese"
        assert versions[1].key == "en_kjv"

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_empty_list(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, {"status": "ok", "data": []})
        client = _make_client()
        assert client.get_bible_versions() == []

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_uses_v2_endpoint(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, {"status": "ok", "data": []})
        client = _make_client()
        client.get_bible_versions()
        # Verifica que a URL chamada é GetBibleVersionsV2, não GetBibleVersions.
        call_args = mock_post.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        assert "GetBibleVersionsV2" in url


# ---------------------------------------------------------------------------
# show_verse
# ---------------------------------------------------------------------------

class TestShowVerse:
    @patch("integracao_holyrics.client.requests.Session.post")
    def test_success_with_verse(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, {"status": "ok"})
        client = _make_client()
        result = client.show_verse(43, 3, 16, version="ACF")
        assert isinstance(result, ShowVerseResult)
        assert result.status == "ok"
        assert result.verse_id == "43003016"
        assert result.book_id == 43
        assert result.chapter == 3
        assert result.verse == 16
        assert result.version == "ACF"

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_success_chapter_only(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, {"status": "ok"})
        client = _make_client()
        result = client.show_verse(43, 3, None, version="ACF")
        assert result.verse_id == "43003000"
        assert result.verse is None

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_quick_presentation(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, {"status": "ok"})
        client = _make_client()
        client.show_verse(43, 3, 16, quick=True)
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["quick_presentation"] is True

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_payload_format(self, mock_post: MagicMock) -> None:
        """Verifica que o payload envia id, version e quick_presentation no raiz."""
        mock_post.return_value = _mock_response(200, {"status": "ok"})
        client = _make_client()
        client.show_verse(19, 23, 1, version="pt_acf")
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["id"] == "19023001"
        assert payload["version"] == "pt_acf"
        assert payload["quick_presentation"] is False
        assert "input" not in payload

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_auth_error_403(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(403, {"status": "error", "error": "invalid token"})
        client = _make_client()
        with pytest.raises(HolyricsAuthError, match="authentication failed"):
            client.show_verse(43, 3, 16)

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_api_error_status(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(
            200, {"status": "error", "error": "verse not found"}
        )
        client = _make_client()
        with pytest.raises(HolyricsAPIError, match="verse not found"):
            client.show_verse(43, 3, 16)

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_http_500(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(500, text="Internal Server Error")
        client = _make_client()
        with pytest.raises(HolyricsAPIError, match="HTTP 500"):
            client.show_verse(43, 3, 16)

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_no_input_wrapper_in_payload(self, mock_post: MagicMock) -> None:
        """Reproduz o bug do Holyrics 2.28.1: wrapper 'input' causa 'Item not found'.

        O payload deve enviar 'id' no nível raiz, não dentro de 'input'.
        Veja evidências: payload com input.id → 'Item not found';
        payload com id no raiz → 'ok'.
        """
        mock_post.return_value = _mock_response(200, {"status": "ok"})
        client = _make_client()
        client.show_verse(43, 3, 16)
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        # O campo 'id' deve estar no raiz, não dentro de 'input'
        assert "id" in payload
        assert payload["id"] == "43003016"
        assert "input" not in payload


# ---------------------------------------------------------------------------
# show_verse_references
# ---------------------------------------------------------------------------

class TestShowVerseReferences:
    @patch("integracao_holyrics.client.requests.Session.post")
    def test_success(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, {"status": "ok"})
        client = _make_client()
        result = client.show_verse_references("João 3:16", version="ACF")
        assert result["status"] == "ok"
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["references"] == "João 3:16"
        assert "input" not in payload

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_multiple_references(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, {"status": "ok"})
        client = _make_client()
        client.show_verse_references("Rm 12:2  Gn 1:1-3  Sl 23")
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert "Rm 12:2" in payload["references"]


# ---------------------------------------------------------------------------
# Timeout e retry
# ---------------------------------------------------------------------------

class TestTimeoutRetry:
    @patch("integracao_holyrics.client.requests.Session.post")
    def test_timeout_then_success(self, mock_post: MagicMock) -> None:
        """Primeira tentativa timeout, segunda sucesso."""
        mock_post.side_effect = [
            requests.exceptions.Timeout("timeout"),
            _mock_response(200, {"status": "ok"}),
        ]
        client = _make_client(max_retries=1)
        result = client.show_verse(43, 3, 16)
        assert result.status == "ok"
        assert mock_post.call_count == 2

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_timeout_all_retries(self, mock_post: MagicMock) -> None:
        """Todas as tentativas timeout -> HolyricsTimeoutError."""
        mock_post.side_effect = requests.exceptions.Timeout("timeout")
        client = _make_client(max_retries=1, timeout_s=0.5)
        with pytest.raises(HolyricsTimeoutError, match="timeout after 0.5s"):
            client.show_verse(43, 3, 16)
        assert mock_post.call_count == 2  # 1 tentativa + 1 retry

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_no_retries(self, mock_post: MagicMock) -> None:
        """max_retries=0 -> só 1 tentativa."""
        mock_post.side_effect = requests.exceptions.Timeout("timeout")
        client = _make_client(max_retries=0)
        with pytest.raises(HolyricsTimeoutError):
            client.show_verse(43, 3, 16)
        assert mock_post.call_count == 1

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_connection_error_no_retry(self, mock_post: MagicMock) -> None:
        """ConnectionError não retenta (Holyrics offline)."""
        mock_post.side_effect = requests.exceptions.ConnectionError("refused")
        client = _make_client(max_retries=3)
        with pytest.raises(HolyricsConnectionError, match="cannot connect"):
            client.show_verse(43, 3, 16)
        assert mock_post.call_count == 1  # não retenta


# ---------------------------------------------------------------------------
# URL building
# ---------------------------------------------------------------------------

class TestUrlBuilding:
    @patch("integracao_holyrics.client.requests.Session.post")
    def test_url_format(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, {"status": "ok"})
        client = _make_client(base_url="http://127.0.0.1:3000/api/")
        client.show_verse(43, 3, 16)
        call_args = mock_post.call_args
        url = call_args[0][0]
        assert url == "http://127.0.0.1:3000/api/ShowVerse"

    @patch("integracao_holyrics.client.requests.Session.post")
    def test_token_in_params(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, {"status": "ok"})
        client = _make_client(token="my-secret")
        client.show_verse(43, 3, 16)
        call_args = mock_post.call_args
        params = call_args[1]["params"]
        assert params["token"] == "my-secret"
