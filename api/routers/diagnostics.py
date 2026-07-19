"""Router /diagnostics — diagnósticos do sistema."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_diagnostic_service
from api.schemas import DiagnosticModel, versioned
from presentation import DiagnosticPresentationService

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("")
@router.get("/")
async def get_diagnostics(
    svc: DiagnosticPresentationService = Depends(get_diagnostic_service),
) -> dict:
    """Retorna diagnósticos de todos os componentes."""
    dtos = svc.all_diagnostics()
    models = tuple(DiagnosticModel.from_dto(d) for d in dtos)
    return versioned({"diagnostics": [m.model_dump(mode="json") for m in models]})
