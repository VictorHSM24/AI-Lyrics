"""Exceptions — handlers de erro FastAPI.

Converte exceções internas em PresentationErrorModel (JSON),
preservando correlation_id, severity e recoverable.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.schemas import PresentationErrorModel

logger = logging.getLogger("api.exceptions")


def setup_exception_handlers(app: FastAPI) -> None:
    """Registra handlers de exceção na aplicação."""

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
        err = PresentationErrorModel(
            code="SERVICE_NOT_FOUND",
            message=f"Endpoint não encontrado: {request.url.path}",
            recoverable=False,
            severity="low",
        )
        return JSONResponse(status_code=404, content=err.model_dump(mode="json"))

    @app.exception_handler(500)
    async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Erro interno: %s", exc)
        err = PresentationErrorModel(
            code="UNKNOWN",
            message="Erro interno do servidor.",
            details={"exception": type(exc).__name__},
            recoverable=False,
            severity="high",
        )
        return JSONResponse(status_code=500, content=err.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Exceção não tratada: %s", exc)
        err = PresentationErrorModel(
            code="UNKNOWN",
            message=str(exc) or "Erro desconhecido.",
            details={"exception": type(exc).__name__},
            recoverable=False,
            severity="medium",
        )
        return JSONResponse(status_code=500, content=err.model_dump(mode="json"))
