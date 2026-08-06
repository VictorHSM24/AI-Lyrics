"""Router /system — informações de sistema (Sprint 14).

Sprint 27 — POST /system/restart para reiniciar o backend após
alterações de configuração que exigem recarga (ex: modelo STT).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import get_system_service
from api.schemas import versioned
from presentation import SystemPresentationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])

# ---------------------------------------------------------------------------
# Sprint 27 — Restart graceful.
#
# O loop de supervisão em main.py cria o Server uvicorn e registra a
# referência aqui via set_server_ref(). Quando POST /system/restart é
# chamado, setamos should_exit=True no Server (que faz o uvicorn parar
# graciosamente) e um flag _restart_requested. O loop em main.py detecta
# o flag, recarrega os módulos de config do disco, e recria a app.
# ---------------------------------------------------------------------------

_server_ref: Any = None
_restart_requested: bool = False


def set_server_ref(server: Any) -> None:
    """Registra a referência do Server uvicorn para o restart."""
    global _server_ref
    _server_ref = server


def was_restart_requested() -> bool:
    """Retorna True se POST /system/restart foi chamado desde o último reset."""
    return _restart_requested


def reset_restart_flag() -> None:
    """Reseta o flag de restart (chamado pelo loop de supervisão)."""
    global _restart_requested
    _restart_requested = False


@router.get("")
@router.get("/")
async def get_system_info(
    svc: SystemPresentationService = Depends(get_system_service),
) -> dict:
    """Retorna informações consolidadas do sistema."""
    info = svc.get_info()
    return versioned(info.to_dict())


@router.post("/restart")
async def restart_backend() -> dict:
    """Solicita reinício do backend.

    Sinaliza o Server uvicorn para parar graciosamente (should_exit).
    O loop de supervisão em main.py detecta o flag e recria a app
    recarregando a configuração do disco.

    Retorna 200 imediatamente — o shutdown acontece em background
    após a resposta ser enviada.
    """
    global _restart_requested
    _restart_requested = True
    logger.info("POST /system/restart — reinício solicitado.")

    if _server_ref is not None:
        # force_exit=True faz o uvicorn não esperar conexões pendentes.
        _server_ref.should_exit = True
        _server_ref.force_exit = True
        logger.info("Sinal de shutdown enviado ao Server uvicorn.")
    else:
        logger.warning(
            "Server ref não registrada — restart pode não funcionar "
            "se main.py não estiver rodando o loop de supervisão."
        )

    return versioned({"status": "restarting", "message": "Backend reiniciando."})
