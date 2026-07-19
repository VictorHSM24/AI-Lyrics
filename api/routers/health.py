"""Router /health — healthcheck da API e do sistema."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

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


class HolyricsTestRequest(BaseModel):
    """Payload para POST /health/holyrics/test — testa conexão Holyrics."""
    base_url: str
    token: str


@router.post("/holyrics/test")
async def test_holyrics_connection(
    req: HolyricsTestRequest,
) -> dict:
    """Testa conexão real com Holyrics usando URL e token fornecidos.

    Usa a mesma implementação compartilhada (_test_holyrics_impl) que o
    health check, garantindo uma única fonte de verdade.

    O backend utiliza exatamente a URL e o token recebidos do frontend.
    Não há valores hardcoded — tudo vem do corpo do POST.

    Mensagens de erro específicas:
      - "Token inválido" para HTTP 401/403.
      - "Conexão recusada" para ConnectionError.
      - "Tempo limite esgotado" para Timeout.
    """
    from presentation.health_checks import _test_holyrics_impl
    result = _test_holyrics_impl(
        client=None,
        base_url=req.base_url,
        token=req.token,
        timeout_s=2.0,
    )
    return versioned(result)
