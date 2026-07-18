"""Exceções específicas do domínio Holyrics."""

from __future__ import annotations

from core.exceptions import AILyricsError


class HolyricsError(AILyricsError):
    """Erro genérico de comunicação com o Holyrics."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HolyricsConnectionError(HolyricsError):
    """Holyrics offline ou inalcançável (erro de conexão)."""


class HolyricsTimeoutError(HolyricsError):
    """Tempo limite esgotado ao contatar o Holyrics."""

    def __init__(self, message: str, *, timeout_s: float | None = None) -> None:
        super().__init__(message)
        self.timeout_s = timeout_s


class HolyricsAuthError(HolyricsError):
    """Token inválido ou permissões insuficientes (HTTP 401/403)."""

    def __init__(self, message: str, *, status_code: int = 403) -> None:
        super().__init__(message, status_code=status_code)


class HolyricsAPIError(HolyricsError):
    """API retornou status=error ou HTTP 4xx/5xx não tratado."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_key: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.error_key = error_key
