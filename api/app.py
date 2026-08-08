"""App FastAPI — ponto de entrada da API.

A aplicação FastAPI apenas registra routers, middlewares e
exception handlers. Nenhuma lógica de negócio aqui.

Para rodar:
    uvicorn api.app:app --reload --port 8000
"""

from __future__ import annotations

# Sprint 27 — Registrar DLLs CUDA ANTES de qualquer import que carregue
# ctranslate2/faster_whisper. Sem isto, a inferência GPU falha com
# "Library cublas64_12.dll is not found" no Windows.
from core.cuda_setup import setup_cuda_dlls  # noqa: F401 (side-effect import)

import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.exceptions import setup_exception_handlers
from api.middlewares import setup_middlewares
from api.routers import ALL_ROUTERS
from api.schemas import CURRENT_API_VERSION
from api.wizard import router as wizard_router
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

    # Routers REST — registrados ANTES do StaticFiles/catch-all para
    # que as rotas da API tenham precedência sobre o fallback do SPA.
    for r in ALL_ROUTERS:
        app.include_router(r)
        logger.info("Router registrado: %s (prefix=%s)", r.tags, getattr(r, "prefix", ""))

    # Sprint 23.0 — Wizard de primeira execução (router separado, não é
    # operação de runtime; fica em api/wizard.py por isolamento conceitual).
    app.include_router(wizard_router)
    logger.info("Router Wizard registrado (prefix=/wizard)")

    # WebSocket.
    app.include_router(websocket_router)
    logger.info("Router WebSocket registrado")

    # ------------------------------------------------------------------
    # Sprint 23.0 fix — Servir frontend React (SPA) em produção.
    #
    # Em desenvolvimento, o frontend roda no vite dev server (porta 5173)
    # e a API só serve endpoints REST. Em produção (PyInstaller), o
    # frontend buildado está em frontend/dist/ dentro do bundle, e a
    # própria API precisa servi-lo.
    #
    # Estratégia:
    #   1. Montar StaticFiles em /assets para JS/CSS/imagens (vite build
    #      coloca tudo hashed em assets/).
    #   2. Rotas explícitas GET para cada path do react-router que
    #      retornam index.html, permitindo que o react-router
    #      (createBrowserRouter) funcione com history API.
    #   3. Rota catch-all GET /{path:path} que serve arquivos estáticos
    #      de frontend/dist (favicon.ico, etc.) ou retorna 404 JSON
    #      para paths não-SPA e não-API.
    #
    # As rotas da API (/health, /wizard/*, /api/*, /ws, etc.) já estão
    # registradas acima e têm precedência sobre o catch-all.
    # ------------------------------------------------------------------
    from core.paths import resource_path
    frontend_dist = resource_path("frontend/dist")
    if frontend_dist.is_dir():
        assets_dir = frontend_dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
            logger.info("StaticFiles montado em /assets (dir=%s)", assets_dir)

        index_html = frontend_dist / "index.html"

        # Rotas explícitas do react-router (frontend/src/router/index.tsx).
        # Cada uma retorna index.html para o react-router cuidar no cliente.
        # Paths não listados aqui caem no catch-all abaixo, que serve
        # arquivos estáticos ou retorna 404 JSON (preservando o
        # comportamento esperado pela API para endpoints inexistentes).
        SPA_ROUTES = [
            "",
            "startup",
            "wizard",
            "console",
            "operador",
            "sessoes",
            "replay",
            "logs",
            "configuracoes",
            "diagnostico",
            "sobre",
        ]

        def _serve_index():
            if index_html.is_file():
                return FileResponse(str(index_html))
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Frontend não buildado. Rode npm run build.")

        for route in SPA_ROUTES:
            if route == "":
                app.get("/")(_serve_index)
            else:
                app.get(f"/{route}")(_serve_index)
        logger.info("SPA rotas registradas: %s", SPA_ROUTES)

        # Catch-all para arquivos estáticos não-API (favicon.ico, etc.).
        # Não serve index.html para paths desconhecidos — esses retornam
        # 404 JSON via exception handler, preservando o contrato da API.
        @app.get("/{full_path:path}")
        async def static_catch_all(full_path: str):
            # Paths que parecem de API retornam 404 JSON.
            if full_path.startswith(("api/", "wizard/", "health", "info", "system",
                                     "audio", "pipeline", "session", "metrics",
                                     "configuration", "diagnostics", "events",
                                     "operator", "ws")):
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail=f"Endpoint não encontrado: /{full_path}")
            # Se o path corresponde a um arquivo estático em frontend/dist,
            # servi-lo (favicon.ico, robots.txt, etc.).
            candidate = frontend_dist / full_path
            if candidate.is_file():
                return FileResponse(str(candidate))
            # Path desconhecido não-API: retorna 404 JSON (não index.html)
            # para preservar o contrato da API para endpoints inexistentes.
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Endpoint não encontrado: /{full_path}")

        logger.info("Static catch-all registrado (frontend/dist=%s)", frontend_dist)
    else:
        logger.warning(
            "Frontend não encontrado em %s — modo API-only. "
            "Em desenvolvimento, rode o frontend via `npm run dev`.",
            frontend_dist,
        )

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
        # Sprint 21.9 — encerrar telemetria graciosamente (drena fila).
        try:
            from telemetry import shutdown_recorder
            shutdown_recorder()
        except Exception:
            pass
        # Sprint 22.0 — encerrar BibleRetriever (libera índice em memória).
        try:
            from api.startup import get_root
            retriever = getattr(get_root(), "bible_retriever", None)
            if retriever is not None:
                retriever.close()
        except Exception:
            pass
        # Sprint 23.1 — terminar subprocess do ollama pull se ativo.
        try:
            from api.wizard import cleanup_ollama_pull
            cleanup_ollama_pull()
        except Exception:
            pass

    return app


# Instância singleton (usada por uvicorn).
app = create_app()
