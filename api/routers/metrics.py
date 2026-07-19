"""Router /metrics — métricas do sistema."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_metrics_service
from api.schemas import MetricsModel, versioned
from presentation import MetricsPresentationService

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("")
@router.get("/")
async def get_metrics(
    svc: MetricsPresentationService = Depends(get_metrics_service),
) -> dict:
    """Retorna as métricas atuais."""
    dto = svc.get_metrics()
    model = MetricsModel.from_dto(dto)
    return versioned(model)
