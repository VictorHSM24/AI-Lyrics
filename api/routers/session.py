"""Router /session — sessão atual."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_session_service
from api.schemas import SessionModel, versioned
from presentation import SessionPresentationService

router = APIRouter(prefix="/session", tags=["session"])


@router.get("/current")
async def get_current_session(
    svc: SessionPresentationService = Depends(get_session_service),
) -> dict:
    """Retorna a sessão atual."""
    dto = svc.get_session()
    model = SessionModel.from_dto(dto)
    return versioned(model)
