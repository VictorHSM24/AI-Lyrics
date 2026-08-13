"""Router /configuration — configuração do sistema.

Sprint 14: adicionado PUT /configuration para persistir overrides.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

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


class ConfigurationUpdateModel(BaseModel):
    """Payload para PUT /configuration — overrides parciais.

    Apenas chaves presentes serão atualizadas. Chaves ausentes
    mantêm o valor atual.
    """

    mode: str | None = None
    holyrics: dict | None = None
    stt: dict | None = None
    llm: dict | None = None
    search: dict | None = None
    state: dict | None = None
    cache: dict | None = None
    confidence: dict | None = None
    log: dict | None = None
    audio: dict | None = None


@router.put("")
@router.put("/")
async def update_configuration(
    payload: ConfigurationUpdateModel,
    svc: ConfigurationPresentationService = Depends(get_configuration_service),
) -> dict:
    """Atualiza a configuração e persiste em disco.

    Apenas campos não-null são aplicados. A configuração é
    persistida em config/config.overrides.json e sobrevive a
    reinicializações.
    """
    # Converter para dict, removendo campos null.
    overrides = payload.model_dump(exclude_none=True)
    if not overrides:
        # Nada para atualizar — retorna config atual.
        dto = svc.get_configuration()
        model = ConfigurationModel.from_dto(dto)
        return versioned(model)

    try:
        dto = svc.update_configuration(overrides)
        model = ConfigurationModel.from_dto(dto)

        # Sprint 28: recarregar HolyricsClient em runtime quando o
        # payload incluir holyrics (token/base_url/timeout). Antes,
        # o PUT /configuration persistia o token em disco mas o
        # HolyricsClient ativo no CompositionRoot continuava com o
        # token antigo até reiniciar o servidor. O Wizard já fazia
        # esse reload via _reload_holyrics_client(); agora o endpoint
        # de configuração também faz.
        if "holyrics" in overrides:
            try:
                from api.wizard import _reload_holyrics_client
                _reload_holyrics_client()
            except Exception as e:
                # Não falhar o PUT se o reload falhar — o token já
                # foi persistido e valerá na próxima reinicialização.
                import logging
                logging.getLogger(__name__).warning(
                    "PUT /configuration: HolyricsClient reload failed: %s "
                    "(token persistido, valerá após restart).", e,
                )

        return versioned(model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
