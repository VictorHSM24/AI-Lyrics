"""Router /info — metadados da API (versão, build, status).

Sprint 14: estendido para incluir build_id, commit, build_date,
frontend_version e sdk_compatibility via InfoPresentationService.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_info_service
from api.schemas import versioned
from presentation import InfoPresentationService

router = APIRouter(prefix="/info", tags=["info"])


@router.get("")
@router.get("/")
async def get_info(
    svc: InfoPresentationService = Depends(get_info_service),
) -> dict:
    """Metadados da API — versão, nome, build, timestamp."""
    info = svc.get_info()
    return versioned(info.to_dict())
