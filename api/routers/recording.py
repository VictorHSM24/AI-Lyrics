"""Router /recording — gravação de auditoria do pipeline.

Expõe o PipelineAuditRecorder (CompositionRoot.audit_recorder):
iniciar/parar gravação do resultado do pipeline em arquivos locais
(events.jsonl, errors.jsonl, telemetry.jsonl, summary.json), com
diretório de saída personalizável (default ~/Documents/AI-Lyrics/gravacoes).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_composition_root
from api.schemas import (
    RecordingEntryModel,
    RecordingStatusModel,
    versioned,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recording", tags=["recording"])


class RecordingStartRequest(BaseModel):
    """Body opcional do POST /recording/start."""

    output_dir: str | None = None  # override pontual (não persiste)
    label: str = ""                # rótulo livre da gravação


class RecordingDirRequest(BaseModel):
    """Body do POST /recording/output-dir (persiste preferência)."""

    output_dir: str


def _recorder(root=Depends(get_composition_root)):
    """Resolve o PipelineAuditRecorder do composition root."""
    rec = getattr(root, "audit_recorder", None)
    if rec is None:
        raise HTTPException(
            status_code=503,
            detail="PipelineAuditRecorder não disponível.",
        )
    return rec


@router.get("/status")
async def get_recording_status(rec=Depends(_recorder)) -> dict:
    """Retorna o status atual da gravação de auditoria."""
    return versioned(RecordingStatusModel(**rec.status()))


@router.get("/recordings")
async def list_recordings(
    limit: int = 20,
    rec=Depends(_recorder),
) -> dict:
    """Lista gravações anteriores (mais recentes primeiro)."""
    entries = [
        RecordingEntryModel(**e).model_dump(mode="json")
        for e in rec.list_recordings(limit=max(1, min(limit, 100)))
    ]
    return versioned({"recordings": entries, "count": len(entries)})


@router.post("/start")
async def start_recording(
    req: RecordingStartRequest | None = None,
    rec=Depends(_recorder),
) -> dict:
    """Inicia a gravação do resultado do pipeline.

    Cria <output_dir>/gravacao_<timestamp>/ com events.jsonl,
    errors.jsonl e telemetry.jsonl. Todos os eventos do EventBus são
    gravados até POST /recording/stop.
    """
    try:
        session_dir = rec.start(
            output_dir=(req.output_dir if req else None),
            label=(req.label if req else ""),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    status = rec.status()
    status["session_dir"] = str(session_dir)
    return versioned(RecordingStatusModel(**status))


@router.post("/stop")
async def stop_recording(rec=Depends(_recorder)) -> dict:
    """Para a gravação e finaliza o summary.json.

    Retorna o status atualizado com last_summary preenchido.
    """
    summary = rec.stop()
    if not summary.get("ok"):
        raise HTTPException(status_code=409, detail=summary["message"])
    return versioned(RecordingStatusModel(**rec.status()))


@router.post("/output-dir")
async def set_output_dir(
    req: RecordingDirRequest,
    rec=Depends(_recorder),
) -> dict:
    """Define e persiste o diretório base de gravação.

    Valida que o diretório pode ser criado/escrito. A preferência é
    persistida em data/recording_prefs.json e usada nas próximas
    gravações (inclusive após restart).
    """
    try:
        rec.set_output_dir(req.output_dir)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return versioned(RecordingStatusModel(**rec.status()))
