"""Router /configuration — configuração do sistema."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_configuration_service
from api.schemas import ConfigurationModel, versioned
from presentation import ConfigurationPresentationService

router = APIRouter(prefix="/configuration", tags=["configuration"])


@router.get("")
@router.get("/")
async def get_configuration(
    svc: ConfigurationPresentationService = Depends(get_configuration_service),
) -> dict:
    """Retorna a configuração atual."""
    dto = svc.get_configuration()
    model = ConfigurationModel.from_dto(dto)
    return versioned(model)
