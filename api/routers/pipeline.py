"""Router /pipeline — estado e controle do pipeline."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_pipeline_service, get_composition_root
from api.schemas import (
    PipelineSnapshotModel,
    PipelineStatusModel,
    SessionModel,
    MetricsModel,
    versioned,
)
from presentation import PipelinePresentationService

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Sprint 17.1 — Controle de ciclo de vida
# ---------------------------------------------------------------------------


@router.post("/start")
@router.post("/start/")
async def start_pipeline(
    svc: PipelinePresentationService = Depends(get_pipeline_service),
    root=Depends(get_composition_root),
) -> dict:
    """Inicia o pipeline completo: AudioCapture → VAD → Whisper → EventBus.

    Orquestra todos os componentes da cadeia de reconhecimento:
      1. AudioCaptureService (captura de microfone)
      2. SpeechPipelineService (VAD)
      3. SpeechWorker (Whisper STT)
      4. BiblicalNLUService (interpretação — já inscrito no EventBus)
      5. PipelineState → running=True
      6. Publica PipelineStarted no EventBus
    """
    try:
        # 1. Iniciar captura de áudio.
        if root.audio_capture is not None:
            try:
                root.audio_capture.start()
            except Exception as e:
                logger.warning("Audio capture start failed: %s", e)

        # 2. Iniciar Speech Pipeline (VAD).
        if root.speech_pipeline is not None and not root.speech_pipeline.is_running:
            root.speech_pipeline.start()

        # 3. Iniciar Speech Worker (Whisper).
        if root.speech_worker is not None and not root.speech_worker.is_running:
            root.speech_worker.start()

        # 4. Atualizar estado lógico do pipeline + publicar PipelineStarted.
        svc.start()

        # 5. Retornar status atualizado.
        dto = svc.get_status()
        model = PipelineStatusModel.from_dto(dto)
        return versioned(model)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("Pipeline start failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
@router.post("/stop/")
async def stop_pipeline(
    svc: PipelinePresentationService = Depends(get_pipeline_service),
    root=Depends(get_composition_root),
) -> dict:
    """Para o pipeline completo: AudioCapture → VAD → Whisper → EventBus.

    Orquestra a parada de todos os componentes na ordem inversa:
      1. Speech Worker (Whisper) — para de consumir segmentos
      2. Speech Pipeline (VAD) — para de processar áudio
      3. AudioCaptureService — para a captura
      4. PipelineState → running=False
      5. Publica PipelineStopped no EventBus
    """
    try:
        # 1. Parar Speech Worker.
        if root.speech_worker is not None and root.speech_worker.is_running:
            root.speech_worker.stop()

        # 2. Parar Speech Pipeline (VAD).
        if root.speech_pipeline is not None and root.speech_pipeline.is_running:
            root.speech_pipeline.stop()

        # 3. Parar captura de áudio.
        if root.audio_capture is not None:
            try:
                root.audio_capture.stop()
            except Exception as e:
                logger.warning("Audio capture stop failed: %s", e)

        # 4. Atualizar estado lógico + publicar PipelineStopped.
        svc.stop(reason="manual_stop")

        # 5. Retornar status atualizado.
        dto = svc.get_status()
        model = PipelineStatusModel.from_dto(dto)
        return versioned(model)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("Pipeline stop failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
