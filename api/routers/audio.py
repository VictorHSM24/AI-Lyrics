"""Router /audio — dispositivos, níveis e controle de captura (Sprint 15.1).

Endpoints:
  GET  /audio/devices  — lista dispositivos
  GET  /audio/current  — dispositivo atual
  GET  /audio/levels   — níveis RMS/Peak atuais
  POST /audio/start    — inicia captura
  POST /audio/stop     — para captura
  POST /audio/select   — seleciona dispositivo
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_audio_service, get_composition_root
from api.schemas import versioned
from presentation import AudioPresentationService

router = APIRouter(prefix="/audio", tags=["audio"])


# ---------------------------------------------------------------------------
# Modelos de request.
# ---------------------------------------------------------------------------


class SelectDeviceModel(BaseModel):
    """Payload para POST /audio/select."""
    device_index: int


# ---------------------------------------------------------------------------
# Endpoints GET.
# ---------------------------------------------------------------------------


@router.get("/devices")
@router.get("/devices/")
async def list_devices(
    svc: AudioPresentationService = Depends(get_audio_service),
) -> dict:
    """Lista dispositivos de entrada de áudio disponíveis."""
    devices = svc.list_devices()
    return versioned({
        "devices": [d.to_dict() for d in devices],
        "count": len(devices),
    })


@router.get("/current")
@router.get("/current/")
async def get_current_device(
    svc: AudioPresentationService = Depends(get_audio_service),
) -> dict:
    """Retorna o dispositivo de áudio atualmente configurado."""
    device = svc.get_current_device()
    if device is None:
        return versioned({"device": None})
    return versioned({"device": device.to_dict()})


@router.get("/levels")
@router.get("/levels/")
async def get_levels(
    svc: AudioPresentationService = Depends(get_audio_service),
) -> dict:
    """Retorna níveis de áudio em tempo real (RMS / peak)."""
    levels = svc.get_levels()
    return versioned(levels.to_dict())


# ---------------------------------------------------------------------------
# Endpoints POST — controle de captura.
# ---------------------------------------------------------------------------


@router.post("/start")
@router.post("/start/")
async def start_capture(
    svc: AudioPresentationService = Depends(get_audio_service),
    root=Depends(get_composition_root),
) -> dict:
    """Inicia a captura de áudio em tempo real."""
    try:
        result = svc.start_capture()
        # Sprint 16 — Iniciar Speech Pipeline (VAD + Worker) junto com captura.
        if root.speech_pipeline is not None and not root.speech_pipeline.is_running:
            root.speech_pipeline.start()
        if root.speech_worker is not None and not root.speech_worker.is_running:
            root.speech_worker.start()
        # Emitir evento WebSocket audio.started.
        from api.websocket.audio_events import get_audio_event_publisher
        try:
            publisher = get_audio_event_publisher()
            publisher.emit_started(
                device_index=result.get("device_index"),
                sample_rate=result.get("sample_rate", 16000),
                channels=result.get("channels", 1),
            )
        except Exception:
            pass  # WebSocket publisher é opcional.
        return versioned(result)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
@router.post("/stop/")
async def stop_capture(
    svc: AudioPresentationService = Depends(get_audio_service),
    root=Depends(get_composition_root),
) -> dict:
    """Para a captura de áudio."""
    try:
        # Sprint 16 — Parar Speech Pipeline (VAD + Worker) junto com captura.
        if root.speech_pipeline is not None and root.speech_pipeline.is_running:
            root.speech_pipeline.stop()
        if root.speech_worker is not None and root.speech_worker.is_running:
            root.speech_worker.stop()
        result = svc.stop_capture()
        # Emitir evento WebSocket audio.stopped.
        from api.websocket.audio_events import get_audio_event_publisher
        try:
            publisher = get_audio_event_publisher()
            publisher.emit_stopped()
        except Exception:
            pass
        return versioned(result)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/select")
@router.post("/select/")
async def select_device(
    payload: SelectDeviceModel,
    svc: AudioPresentationService = Depends(get_audio_service),
) -> dict:
    """Seleciona um dispositivo de entrada.

    Se a captura estiver ativa, interrompe, troca o dispositivo e
    reinicia automaticamente.
    """
    try:
        result = svc.select_device(payload.device_index)
        # Emitir evento WebSocket audio.device.changed.
        from api.websocket.audio_events import get_audio_event_publisher
        try:
            publisher = get_audio_event_publisher()
            publisher.emit_device_changed(
                device_index=result["device_index"],
                restarted=result.get("restarted", False),
            )
        except Exception:
            pass
        return versioned(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
