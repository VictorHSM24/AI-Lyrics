"""Router /info — metadados da API (versão, status)."""

from __future__ import annotations

import time

from fastapi import APIRouter

from api.schemas import CURRENT_API_VERSION

router = APIRouter(prefix="/info", tags=["info"])


@router.get("")
@router.get("/")
async def get_info() -> dict:
    """Metadados da API — versão, nome, timestamp."""
    return {
        "name": "AI Lyrics API",
        "version": CURRENT_API_VERSION.model_dump(mode="json"),
        "server_time": time.time(),
    }
