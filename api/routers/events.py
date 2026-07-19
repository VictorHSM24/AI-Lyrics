"""Router /events — eventos e histórico."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.dependencies import get_event_service
from api.schemas import EventModel, EventSnapshotModel, versioned
from presentation import EventPresentationService

router = APIRouter(prefix="/events", tags=["events"])


@router.get("")
@router.get("/")
async def get_all_events(
    svc: EventPresentationService = Depends(get_event_service),
) -> dict:
    """Retorna todos os eventos armazenados."""
    dtos = svc.get_all_events()
    models = [EventModel.from_dto(e).model_dump(mode="json") for e in dtos]
    return versioned({"events": models, "count": len(models)})


@router.get("/by-correlation")
async def get_events_by_correlation(
    correlation_id: str = Query(..., description="Correlation ID"),
    svc: EventPresentationService = Depends(get_event_service),
) -> dict:
    """Retorna eventos de um correlation_id."""
    dtos = svc.get_events_by_correlation(correlation_id)
    models = [EventModel.from_dto(e).model_dump(mode="json") for e in dtos]
    return versioned({"events": models, "count": len(models), "correlation_id": correlation_id})


@router.get("/by-session")
async def get_events_by_session(
    session_id: str = Query(..., description="Session ID"),
    svc: EventPresentationService = Depends(get_event_service),
) -> dict:
    """Retorna eventos de um session_id."""
    dtos = svc.get_events_by_session(session_id)
    models = [EventModel.from_dto(e).model_dump(mode="json") for e in dtos]
    return versioned({"events": models, "count": len(models), "session_id": session_id})


@router.get("/snapshot")
async def get_event_snapshot(
    correlation_id: str = Query("", description="Correlation ID opcional"),
    svc: EventPresentationService = Depends(get_event_service),
) -> dict:
    """Retorna snapshot de eventos."""
    dto = svc.get_snapshot(correlation_id or "")
    model = EventSnapshotModel.from_dto(dto)
    return versioned(model)
