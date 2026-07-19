"""App FastAPI — ponto de entrada da API.

A aplicação FastAPI apenas registra routers, middlewares e
exception handlers. Nenhuma lógica de negócio aqui.

Para rodar:
    uvicorn api.app:app --reload --port 8000
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from api.exceptions import setup_exception_handlers
from api.middlewares import setup_middlewares
from api.routers import ALL_ROUTERS
from api.schemas import CURRENT_API_VERSION
from api.websocket import websocket_router

# Logging estruturado (infraestrutura apenas — sem logs de negócio).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("api")


def create_app() -> FastAPI:
    """Cria a aplicação FastAPI com todos os routers e middlewares."""
    app = FastAPI(
        title="AI Lyrics API",
        description=(
            "API REST + WebSocket que expõe a Presentation Layer do "
            "AI Lyrics. Nenhum endpoint acessa o Core diretamente."
        ),
        version=f"{CURRENT_API_VERSION.major}.{CURRENT_API_VERSION.minor}.{CURRENT_API_VERSION.patch}",
    )

    # Middlewares (CORS, logging).
    setup_middlewares(app)

    # Exception handlers.
    setup_exception_handlers(app)

    # Routers REST.
    for r in ALL_ROUTERS:
        app.include_router(r)

    # WebSocket.
    app.include_router(websocket_router)

    # Eventos de lifecycle.
    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info("API iniciando — composition root inicializado.")
        # O CompositionRoot é inicializado lazy via get_root().
        # Aqui apenas garantimos que está pronto.
        from api.startup import get_root
        root = get_root()
        logger.info("Composition root pronto.")

        # Sprint 15.1 — conectar AudioCaptureService ao WebSocket publisher.
        try:
            from api.websocket.audio_events import connect_audio_capture_to_publisher
            connect_audio_capture_to_publisher(root.audio_capture)
        except Exception as e:
            logger.warning("Failed to connect audio capture to publisher: %s", e)

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        logger.info("API encerrando.")
        from api.websocket import get_event_publisher
        try:
            get_event_publisher().stop()
        except Exception:
            pass
        # Sprint 15.1 — parar audio capture e publisher.
        try:
            from api.websocket.audio_events import get_audio_event_publisher
            get_audio_event_publisher().stop()
        except Exception:
            pass
        try:
            from api.startup import get_root
            get_root().audio_capture.shutdown()
        except Exception:
            pass

    return app


# Instância singleton (usada por uvicorn).
app = create_app()
