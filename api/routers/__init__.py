"""Routers package — agrega todos os routers REST."""

from api.routers.audio import router as audio_router
from api.routers.configuration import router as configuration_router
from api.routers.diagnostics import router as diagnostics_router
from api.routers.events import router as events_router
from api.routers.health import router as health_router
from api.routers.info import router as info_router
from api.routers.metrics import router as metrics_router
from api.routers.pipeline import router as pipeline_router
from api.routers.session import router as session_router
from api.routers.system import router as system_router

ALL_ROUTERS = [
    health_router,
    info_router,
    system_router,
    audio_router,
    pipeline_router,
    session_router,
    metrics_router,
    configuration_router,
    diagnostics_router,
    events_router,
]

__all__ = ["ALL_ROUTERS"]
