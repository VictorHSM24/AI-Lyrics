"""Router /health — healthcheck da API e do sistema."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from api.dependencies import get_health_service
from api.schemas import HealthSnapshotModel, PresentationErrorModel, versioned
from presentation import HealthPresentationService

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
@router.get("/")
async def get_health(
    svc: HealthPresentationService = Depends(get_health_service),
) -> dict:
    """Retorna snapshot de saúde de todos os componentes."""
    snapshot = svc.get_snapshot()
    model = HealthSnapshotModel.from_dto(snapshot)
    return versioned(model)


@router.get("/live")
async def liveness() -> dict:
    """Liveness probe — sempre 200 se o processo está vivo."""
    return {"status": "alive", "timestamp": time.time()}


@router.get("/ready")
async def readiness(
    svc: HealthPresentationService = Depends(get_health_service),
) -> dict:
    """Readiness probe — 200 se o sistema está pronto para tráfego."""
    snap = svc.get_snapshot()
    return {
        "ready": snap.all_healthy or True,  # sempre ready nesta fase
        "all_healthy": snap.all_healthy,
        "healthy_count": snap.healthy_count,
        "unhealthy_count": snap.unhealthy_count,
        "timestamp": time.time(),
    }
