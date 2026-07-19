"""Cliente HTTP para a API REST oficial do Holyrics.

Documentação da API: https://github.com/holyrics/API-Server

Notas técnicas (inconsistências entre API oficial e arquitetura):
  1. ShowVerse: os parâmetros ``id``/``ids``/``references``, ``version`` e
     ``quick_presentation`` são enviados no nível raiz do payload JSON.
     Testes empíricos contra Holyrics 2.28.1 confirmaram que o wrapper
     ``{"input": {...}}`` causa "Item not found"; os campos no raiz funcionam.
  2. GetBibleVersions está deprecated (substituído por GetBibleVersionsV2 desde
     v2.23.0). Este cliente usa GetBibleVersionsV2.
  3. O parâmetro ``version`` aceita "nome ou abreviação". A arquitetura usa
     "ACF" como default, mas a API retorna keys como "pt_acf". O cliente
     repassa o valor configurado sem validar — se "ACF" não funcionar, usar
     "pt_acf" ou "Almeida Corrigida Fiel" no config.yaml.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from integracao_holyrics.exceptions import (
    HolyricsAPIError,
    HolyricsAuthError,
    HolyricsConnectionError,
    HolyricsError,
    HolyricsTimeoutError,
)
from integracao_holyrics.models import BibleVersion, ShowVerseResult, TokenInfo

logger = logging.getLogger(__name__)


def _format_verse_id(book_id: int, chapter: int, verse: int | None) -> str:
    """Formata ID no padrão BBCCCVVV (zero-padded).

    Ex.: book=43, chapter=3, verse=16 -> "43003016".
    Se verse for None, usa 000 (capítulo inteiro).
    """
    v = verse if verse is not None else 0
    return f"{book_id:02d}{chapter:03d}{v:03d}"


class HolyricsClient:
    """Cliente para a API REST oficial do Holyrics.

    Comunicação via HTTP POST local com token.
    Suporta timeout configurável e retry limitado.

    Args:
        base_url: URL base (ex.: ``"http://127.0.0.1:3000/api"``).
        token: token de acesso criado no Holyrics.
        timeout_s: timeout por requisição em segundos (default: 2.0).
        max_retries: número de retentativas em caso de timeout (default: 1).
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout_s: float = 2.0,
        max_retries: int = 1,
    ) -> None:
        # Normalizar base_url: remover trailing slash.
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_s = timeout_s
        self._max_retries = max(0, max_retries)
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    # ------------------------------------------------------------------
    # Operações públicas
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        """Verifica se o Holyrics está reachável e o token é válido.

        Usa ``GetTokenInfo`` (v2.25.0+) com timeout curto (1 s).
        Retorna ``True`` se conectou e o token é válido, ``False`` caso contrário.
        """
        try:
            self._post("GetTokenInfo", {}, timeout_s=1.0)
            return True
        except HolyricsError as e:
            logger.warning("test_connection failed: %s", e)
            return False

    def test_connection_detailed(self) -> dict:
        """Testa conexão e retorna detalhes do resultado.

        Diferente de ``test_connection()``, não captura exceções —
        propaga-as para que o chamador possa distinguir entre
        erro de conexão, timeout, auth, etc.

        Retorna dict com:
          - ok: bool
          - message: str
          - latency_ms: int
          - error_type: str (opcional)
        """
        import time as _time
        t0 = _time.monotonic()
        try:
            self._post("GetTokenInfo", {}, timeout_s=1.0)
            latency_ms = int((_time.monotonic() - t0) * 1000)
            return {"ok": True, "message": "Conexão bem-sucedida", "latency_ms": latency_ms}
        except HolyricsAuthError as e:
            latency_ms = int((_time.monotonic() - t0) * 1000)
            return {"ok": False, "message": "Token inválido", "latency_ms": latency_ms, "error_type": "auth"}
        except HolyricsConnectionError as e:
            latency_ms = int((_time.monotonic() - t0) * 1000)
            return {"ok": False, "message": "Conexão recusada", "latency_ms": latency_ms, "error_type": "connection"}
        except HolyricsTimeoutError as e:
            latency_ms = int((_time.monotonic() - t0) * 1000)
            return {"ok": False, "message": "Tempo limite esgotado", "latency_ms": latency_ms, "error_type": "timeout"}
        except HolyricsAPIError as e:
            latency_ms = int((_time.monotonic() - t0) * 1000)
            return {"ok": False, "message": f"Erro da API: {e}", "latency_ms": latency_ms, "error_type": "api"}
        except HolyricsError as e:
            latency_ms = int((_time.monotonic() - t0) * 1000)
            return {"ok": False, "message": f"Erro: {e}", "latency_ms": latency_ms, "error_type": "generic"}

    def health_check(self) -> bool:
        """Verifica se o Holyrics está reachável e responsivo.

        Alias semântico para ``test_connection``. Retorna ``True`` se saudável.
        """
        return self.test_connection()

    def get_bible_versions(self) -> list[BibleVersion]:
        """Lista as versões da Bíblia disponíveis no Holyrics.

        Usa ``GetBibleVersionsV2`` (v2.23.0+).
        ``GetBibleVersions`` (v1) está deprecated.

        Returns:
            Lista de ``BibleVersion``.

        Raises:
            HolyricsConnectionError: Holyrics offline.
            HolyricsTimeoutError: tempo limite esgotado.
            HolyricsAuthError: token inválido.
            HolyricsAPIError: erro na API.
        """
        response = self._post("GetBibleVersionsV2", {})
        data = response.get("data", [])
        if not isinstance(data, list):
            raise HolyricsAPIError(
                f"GetBibleVersionsV2: expected list in 'data', got {type(data).__name__}"
            )
        versions: list[BibleVersion] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            lang_obj = item.get("language")
            lang_name = lang_obj.get("name") if isinstance(lang_obj, dict) else None
            versions.append(
                BibleVersion(
                    key=str(item.get("key", "")),
                    version=str(item.get("version", "")),
                    title=str(item.get("title", "")),
                    language=lang_name,
                )
            )
        return versions

    def show_verse(
        self,
        book_id: int,
        chapter: int,
        verse: int | None,
        version: str = "ACF",
        quick: bool = False,
    ) -> ShowVerseResult:
        """Inicia apresentação de um versículo no Holyrics via ``ShowVerse``.

        Args:
            book_id: ID do livro (1..66).
            chapter: capítulo (1..150).
            verse: versículo (1..200) ou ``None`` para capítulo inteiro.
            version: nome ou abreviação da tradução (default: ``"ACF"``).
            quick: se ``True``, usa ``quick_presentation`` (popup sem encerrar
                apresentação atual).

        Returns:
            ``ShowVerseResult`` com status e referência enviada.

        Raises:
            HolyricsConnectionError: Holyrics offline.
            HolyricsTimeoutError: tempo limite esgotado (após retries).
            HolyricsAuthError: token inválido (403).
            HolyricsAPIError: erro na API ou HTTP 4xx/5xx.
        """
        verse_id = _format_verse_id(book_id, chapter, verse)
        payload: dict[str, Any] = {
            "id": verse_id,
            "version": version,
            "quick_presentation": quick,
        }
        response = self._post("ShowVerse", payload)
        return ShowVerseResult(
            status=str(response.get("status", "unknown")),
            verse_id=verse_id,
            book_id=book_id,
            chapter=chapter,
            verse=verse,
            version=version,
        )

    def show_verse_references(
        self,
        references: str,
        version: str = "ACF",
        quick: bool = False,
    ) -> dict:
        """Inicia apresentação usando referências em linguagem natural.

        Delega a resolução da referência para o Holyrics.

        Args:
            references: texto livre (ex.: ``"João 3:16"``, ``"Rm 12:2"``).
            version: nome ou abreviação da tradução.
            quick: se ``True``, usa ``quick_presentation``.

        Returns:
            Resposta JSON do Holyrics.

        Raises:
            HolyricsConnectionError, HolyricsTimeoutError, HolyricsAuthError, HolyricsAPIError.
        """
        payload: dict[str, Any] = {
            "references": references,
            "version": version,
            "quick_presentation": quick,
        }
        return self._post("ShowVerse", payload)

    def get_token_info(self) -> TokenInfo:
        """Obtém informações do token (``GetTokenInfo``, v2.25.0+).

        Returns:
            ``TokenInfo`` com versão e permissões.

        Raises:
            HolyricsConnectionError, HolyricsTimeoutError, HolyricsAuthError, HolyricsAPIError.
        """
        response = self._post("GetTokenInfo", {})
        data = response.get("data", {})
        if not isinstance(data, dict):
            raise HolyricsAPIError(
                f"GetTokenInfo: expected object in 'data', got {type(data).__name__}"
            )
        return TokenInfo(
            version=str(data.get("version", "")),
            permissions=str(data.get("permissions", "")),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_url(self, action: str) -> str:
        """Constrói a URL completa para uma action."""
        return f"{self._base_url}/{action}"

    def _post(
        self,
        action: str,
        payload: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """Executa POST com retry em caso de timeout.

        Args:
            action: nome da action (ex.: ``"ShowVerse"``).
            payload: corpo JSON.
            timeout_s: timeout overrideself._timeout_s.

        Returns:
            Resposta JSON parseada.

        Raises:
            HolyricsConnectionError, HolyricsTimeoutError, HolyricsAuthError, HolyricsAPIError.
        """
        url = self._build_url(action)
        params = {"token": self._token}
        effective_timeout = timeout_s if timeout_s is not None else self._timeout_s
        last_error: Exception | None = None
        total_retries = self._max_retries + 1

        for attempt in range(total_retries):
            t0 = time.monotonic()
            try:
                logger.debug(
                    "POST %s (attempt %d/%d, timeout=%.1fs)",
                    url,
                    attempt + 1,
                    total_retries,
                    effective_timeout,
                )
                resp = self._session.post(
                    url,
                    params=params,
                    json=payload,
                    timeout=effective_timeout,
                )
                duration_ms = (time.monotonic() - t0) * 1000
                logger.debug(
                    "POST %s -> HTTP %d (%.1f ms)",
                    url,
                    resp.status_code,
                    duration_ms,
                )
                return self._handle_response(resp, action)
            except requests.exceptions.Timeout as e:
                duration_ms = (time.monotonic() - t0) * 1000
                logger.warning(
                    "POST %s timeout (%.1f ms, attempt %d/%d)",
                    url,
                    duration_ms,
                    attempt + 1,
                    total_retries,
                )
                last_error = HolyricsTimeoutError(
                    f"{action}: timeout after {effective_timeout}s",
                    timeout_s=effective_timeout,
                )
                # Continua para retry.
            except requests.exceptions.ConnectionError as e:
                logger.warning("POST %s connection error: %s", url, e)
                # Erro de conexão não vale a pena retentar (Holyrics offline).
                raise HolyricsConnectionError(
                    f"{action}: cannot connect to Holyrics at {self._base_url}"
                ) from e
            except requests.exceptions.RequestException as e:
                logger.error("POST %s request error: %s", url, e)
                raise HolyricsConnectionError(f"{action}: {e}") from e

        # Esgotou retries.
        assert last_error is not None
        raise last_error

    @staticmethod
    def _handle_response(resp: requests.Response, action: str) -> dict[str, Any]:
        """Processa a resposta HTTP, validando status e corpo JSON.

        Raises:
            HolyricsAuthError: HTTP 401/403.
            HolyricsAPIError: HTTP 4xx/5xx ou status=error no JSON.
        """
        # HTTP 401/403 -> erro de autenticação.
        if resp.status_code in (401, 403):
            raise HolyricsAuthError(
                f"{action}: authentication failed (HTTP {resp.status_code})",
                status_code=resp.status_code,
            )

        # HTTP 4xx/5xx (exceto 401/403 já tratados).
        if resp.status_code >= 400:
            raise HolyricsAPIError(
                f"{action}: HTTP {resp.status_code} - {resp.text[:200]}",
                status_code=resp.status_code,
            )

        # Parse JSON.
        try:
            body = resp.json()
        except ValueError as e:
            raise HolyricsAPIError(
                f"{action}: invalid JSON response: {e}"
            ) from e

        if not isinstance(body, dict):
            raise HolyricsAPIError(
                f"{action}: expected JSON object, got {type(body).__name__}"
            )

        # status=error na resposta JSON.
        status = body.get("status")
        if status == "error":
            error_msg = body.get("error", "unknown error")
            # error pode ser string ou objeto (internet endpoint).
            error_key = None
            if isinstance(error_msg, dict):
                error_key = error_msg.get("key")
                error_msg = error_msg.get("message", str(error_msg))
            raise HolyricsAPIError(
                f"{action}: API error: {error_msg}",
                error_key=error_key,
            )

        return body
