"""Router /pipeline — estado do pipeline."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_pipeline_service
from api.schemas import (
    PipelineSnapshotModel,
    PipelineStatusModel,
    SessionModel,
    MetricsModel,
    versioned,
)
from presentation import PipelinePresentationService

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/status")
async def get_pipeline_status(
    svc: PipelinePresentationService = Depends(get_pipeline_service),
) -> dict:
    """Retorna o status atual do pipeline."""
    dto = svc.get_status()
    model = PipelineStatusModel.from_dto(dto)
    return versioned(model)


@router.get("/session")
async def get_pipeline_session(
    svc: PipelinePresentationService = Depends(get_pipeline_service),
) -> dict:
    """Retorna a sessão atual do pipeline."""
    dto = svc.get_session()
    model = SessionModel.from_dto(dto)
    return versioned(model)


@router.get("/metrics")
async def get_pipeline_metrics(
    svc: PipelinePresentationService = Depends(get_pipeline_service),
) -> dict:
    """Retorna as métricas atuais do pipeline."""
    dto = svc.get_metrics()
    model = MetricsModel.from_dto(dto)
    return versioned(model)


@router.get("/snapshot")
async def get_pipeline_snapshot(
    svc: PipelinePresentationService = Depends(get_pipeline_service),
) -> dict:
    """Retorna snapshot completo do pipeline."""
    dto = svc.get_snapshot()
    model = PipelineSnapshotModel.from_dto(dto)
    return versioned(model)
