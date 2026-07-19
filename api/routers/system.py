"""Router /system — informações de sistema (Sprint 14)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_system_service
from api.schemas import versioned
from presentation import SystemPresentationService

router = APIRouter(prefix="/system", tags=["system"])


@router.get("")
@router.get("/")
async def get_system_info(
    svc: SystemPresentationService = Depends(get_system_service),
) -> dict:
    """Retorna informações consolidadas do sistema."""
    info = svc.get_info()
    return versioned(info.to_dict())
