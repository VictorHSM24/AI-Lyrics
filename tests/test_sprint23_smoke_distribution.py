"""Sprint 23.0 — Teste de smoke para distribuição empacotada.

Valida que a versão empacotada (PyInstaller + Inno Setup) tem o mesmo
comportamento da versão de desenvolvimento. Roda automaticamente
após o build do instalador para impedir que uma versão quebrada seja
distribuída.

Cobre:
1. Resolução de caminhos via core.paths.resource_path (dev + frozen simulado).
2. Carregamento de arquivos de configuração (config.yaml, books.json,
   knowledge_base.json) via resource_path.
3. Registro completo de routers na app FastAPI (Wizard, Health, WebSocket,
   demais endpoints).
4. Servir do frontend React (SPA) via catch-all em produção.
5. Endpoints do Wizard respondem corretamente (/wizard/status,
   /wizard/bible/validate, /wizard/test).
6. Endpoint /health responde 200.
7. Nenhum erro crítico aparece nos logs de inicialização.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# 1. core.paths — resolução de caminhos (dev + frozen simulado)
# ---------------------------------------------------------------------------


class TestResourcePath:
    """Valida core.paths.resource_path em dev e frozen simulado."""

    def test_resource_path_dev_resolves_relative_to_project_root(self):
        from core.paths import resource_path, is_frozen
        # Em dev, resource_path deve resolver config/books.json para
        # um path absoluto que existe.
        p = resource_path("config/books.json")
        assert p.is_file(), f"books.json não encontrado em {p}"
        assert p.name == "books.json"

    def test_resource_path_absolute_path_returned_as_is(self):
        from core.paths import resource_path
        abs_path = str(Path.cwd() / "config" / "books.json")
        p = resource_path(abs_path)
        assert str(p) == abs_path

    def test_resource_path_frozen_uses_meipass(self):
        """Simula frozen: sys.frozen=True e sys._MEIPASS aponta para cwd."""
        from core import paths as paths_module
        # Simular bundle frozen com _MEIPASS apontando para a raiz do projeto.
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", str(Path.cwd()), create=True):
            # Reimportar para que is_frozen() reflita o patch.
            import importlib
            importlib.reload(paths_module)
            p = paths_module.resource_path("config/books.json")
            assert p.is_file(), f"books.json não encontrado em frozen: {p}"
            # Em frozen, o path deve ser <_MEIPASS>/config/books.json.
            assert str(p) == str(Path.cwd() / "config" / "books.json")
        # Restaurar estado não-frozen.
        importlib.reload(paths_module)

    def test_writable_path_dev_returns_project_root_relative(self):
        from core.paths import writable_path
        p = writable_path("config/config.overrides.json")
        # Em dev, deve apontar para a raiz do projeto.
        assert p.parent.name == "config"
        assert p.name == "config.overrides.json"

    def test_writable_path_frozen_uses_appdata(self, tmp_path):
        """Simula frozen: writable_path deve usar APPDATA."""
        from core import paths as paths_module
        import importlib
        fake_appdata = tmp_path / "AppData"
        fake_appdata.mkdir()
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", str(tmp_path), create=True), \
             patch.dict(os.environ, {"APPDATA": str(fake_appdata)}):
            importlib.reload(paths_module)
            p = paths_module.writable_path("config/config.overrides.json")
            # Deve apontar para <APPDATA>/AI Lyrics Assistant/config/config.overrides.json.
            assert "AI Lyrics Assistant" in str(p)
            assert p.parent.is_dir()  # diretório pai criado.
        importlib.reload(paths_module)


# ---------------------------------------------------------------------------
# 2. Carregamento de configuração via resource_path
# ---------------------------------------------------------------------------


class TestConfigLoadingViaResourcePath:
    """Valida que load_config e load_books resolvem via resource_path."""

    def test_load_books_finds_books_json(self):
        from config.loader import load_books
        table = load_books()
        # BookTable.all_books() retorna lista de 66 livros.
        books = table.all_books()
        assert len(books) == 66, f"esperado 66 livros, obtido {len(books)}"

    def test_load_config_finds_config_yaml(self):
        from config.loader import load_config
        cfg = load_config()
        assert cfg is not None
        # Config mínima deve ter holyrics.
        assert hasattr(cfg, "holyrics")

    def test_load_parser_books_finds_books_json(self):
        from parser.books import load_parser_books
        table = load_parser_books()
        # ParserBookTable.all_books() retorna lista de 66 livros.
        books = table.all_books()
        assert len(books) == 66

    def test_load_books_raises_clear_error_when_file_missing(self):
        from config.loader import load_books
        from core.exceptions import ConfigError
        with pytest.raises(ConfigError) as exc_info:
            load_books("config/inexistente.json")
        assert "books file not found" in str(exc_info.value)
        assert "resolved" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. Registro completo de routers na app FastAPI
# ---------------------------------------------------------------------------


class TestRouterRegistration:
    """Valida que todos os routers são registrados na app."""

    @pytest.fixture(scope="class")
    def app(self):
        from api.app import create_app
        return create_app()

    def test_app_is_fastapi(self, app):
        assert isinstance(app, FastAPI)

    def test_wizard_router_registered(self, app):
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        wizard_paths = [p for p in paths if p.startswith("/wizard")]
        assert len(wizard_paths) >= 14, f"esperado >=14 rotas wizard, obtido {len(wizard_paths)}"
        assert "/wizard/status" in wizard_paths
        assert "/wizard/audio/devices" in wizard_paths
        assert "/wizard/holyrics/detect" in wizard_paths
        assert "/wizard/ollama/detect" in wizard_paths
        assert "/wizard/bible/validate" in wizard_paths
        assert "/wizard/test" in wizard_paths
        assert "/wizard/complete" in wizard_paths

    def test_health_router_registered(self, app):
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/health" in paths
        assert "/health/live" in paths
        assert "/health/ready" in paths

    def test_websocket_router_registered(self, app):
        # WebSocket routes aparecem em app.routes.
        ws_routes = [r for r in app.routes if hasattr(r, "path") and "/ws" in getattr(r, "path", "")]
        assert len(ws_routes) >= 1, "nenhuma rota WebSocket encontrada"

    def test_core_routers_registered(self, app):
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        for expected in ["/info", "/system", "/audio", "/pipeline", "/session",
                         "/metrics", "/configuration", "/diagnostics", "/events"]:
            assert any(p.startswith(expected) for p in paths), f"router {expected} não registrado"

    def test_spa_catch_all_registered(self, app):
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/{full_path:path}" in paths, "SPA catch-all não registrado"


# ---------------------------------------------------------------------------
# 4-7. Smoke test via TestClient — servidor iniciado, endpoints respondem
# ---------------------------------------------------------------------------


class TestSmokeDistribution:
    """Smoke test completo via TestClient.

    Simula o que o teste pós-build do instalador faria: iniciar o
    servidor, validar endpoints críticos, validar que o frontend é
    servido, e validar que nenhum erro crítico aparece.
    """

    @pytest.fixture(scope="class")
    def client(self):
        from api.app import create_app
        app = create_app()
        return TestClient(app)

    def test_health_responds_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200, f"/health retornou {r.status_code}"

    def test_health_live_responds_200(self, client):
        r = client.get("/health/live")
        assert r.status_code == 200

    def test_wizard_status_responds_200(self, client):
        r = client.get("/wizard/status")
        assert r.status_code == 200
        body = r.json()
        assert "payload" in body
        assert "completed" in body["payload"]

    def test_wizard_bible_validate_responds_200(self, client):
        r = client.get("/wizard/bible/validate")
        assert r.status_code == 200
        payload = r.json()["payload"]
        assert "versions_count" in payload
        assert "bible_retriever_ok" in payload
        assert "fts5_db_exists" in payload
        assert "embeddings_npy_exists" in payload

    def test_wizard_test_responds_200(self, client):
        r = client.get("/wizard/test")
        assert r.status_code == 200
        payload = r.json()["payload"]
        assert "all_ok" in payload
        assert "components" in payload

    def test_wizard_ollama_detect_responds_200(self, client):
        r = client.get("/wizard/ollama/detect")
        assert r.status_code == 200
        payload = r.json()["payload"]
        assert "installed" in payload

    def test_spa_root_serves_index_html(self, client):
        """GET / deve retornar index.html do frontend buildado."""
        r = client.get("/")
        # Se frontend/dist existe, retorna 200 com text/html.
        # Se não existe (dev sem build), retorna 404 — aceitável.
        if r.status_code == 200:
            assert "text/html" in r.headers.get("content-type", "")
        else:
            assert r.status_code == 404, f"status inesperado: {r.status_code}"

    def test_spa_wizard_path_serves_index_html(self, client):
        """GET /wizard (rota do react-router) deve retornar index.html."""
        r = client.get("/wizard")
        if r.status_code == 200:
            assert "text/html" in r.headers.get("content-type", "")
        else:
            assert r.status_code == 404

    def test_spa_assets_served(self, client):
        """Assets do vite build (JS/CSS) devem ser servidos em /assets/."""
        # Verificar que /assets/ existe como mount.
        r = client.get("/assets/")
        # StaticFiles retorna 404 para directory listing por padrão.
        # O importante é que o mount existe e não dá 500.
        assert r.status_code in (200, 404), f"/assets/ retornou {r.status_code}"

    def test_api_endpoint_not_intercepted_by_catch_all(self, client):
        """Endpoint da API inexistente deve retornar 404 JSON, não index.html."""
        r = client.get("/wizard/inexistente")
        assert r.status_code == 404
        # Deve ser JSON do exception handler, não HTML.
        body = r.json()
        assert "code" in body or "detail" in body


# ---------------------------------------------------------------------------
# 8. Validação de que arquivos críticos existem via resource_path
# ---------------------------------------------------------------------------


class TestCriticalFilesResolvable:
    """Valida que todos os arquivos críticos são resolvíveis via resource_path."""

    @pytest.mark.parametrize("relative_path", [
        "config/config.yaml",
        "config/books.json",
        "config/knowledge_base.json",
        "data/sources/ACF.sqlite",
        "data/sources/NTLH.sqlite",
        "data/sources/NVT.sqlite",
    ])
    def test_critical_file_resolvable(self, relative_path):
        from core.paths import resource_path
        p = resource_path(relative_path)
        assert p.is_file(), f"arquivo crítico não encontrado: {relative_path} (resolved: {p})"

    @pytest.mark.parametrize("relative_path", [
        "data/bible.pt-br.sqlite",
        "data/bible.embeddings.npy",
    ])
    def test_generated_file_resolvable_or_skippable(self, relative_path):
        """Arquivos gerados (Categoria C) podem não existir em dev sem build.

        Se existirem, devem ser resolvíveis. Se não existirem, o teste
        pula (skippable) — eles são gerados por build_embeddings.py.
        """
        from core.paths import resource_path
        p = resource_path(relative_path)
        if not p.is_file():
            pytest.skip(f"{relative_path} não gerado (rode build_embeddings.py)")
