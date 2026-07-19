"""Testes da API FastAPI — endpoints REST e WebSocket.

Valida que a API expõe corretamente a Presentation Layer via
endpoints REST e WebSocket, sem acessar o Core diretamente.

Cobertura:
  - Endpoints REST (health, pipeline, session, metrics, configuration, events, info)
  - Versionamento (Versioned<T> envelope)
  - WebSocket (hello, heartbeat, eventos)
  - Composition root
  - Schemas Pydantic
  - Error handling
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from fastapi.testclient import TestClient

from api.app import create_app
from api.startup import (
    CompositionRoot,
    create_composition_root,
    get_root,
    reset_root,
)
from api.websocket import reset_ws_manager


# ---------------------------------------------------------------------------
# Helper — cria app e client isolados para cada teste.
# ---------------------------------------------------------------------------


def _make_client() -> TestClient:
    """Cria um TestClient com composition root fresco."""
    reset_root()
    reset_ws_manager()
    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Composition Root
# ---------------------------------------------------------------------------


class TestCompositionRoot(unittest.TestCase):
    """Testa a inicialização do composition root."""

    def test_create_composition_root(self):
        root = create_composition_root()
        self.assertIsInstance(root, CompositionRoot)
        self.assertIsNotNone(root.bus)
        self.assertIsNotNone(root.store)
        self.assertIsNotNone(root.state)
        self.assertIsNotNone(root.session)
        self.assertIsNotNone(root.metrics)
        self.assertIsNotNone(root.policy)
        # Presentation Services
        self.assertIsNotNone(root.pipeline_service)
        self.assertIsNotNone(root.session_service)
        self.assertIsNotNone(root.metrics_service)
        self.assertIsNotNone(root.configuration_service)
        self.assertIsNotNone(root.health_service)
        self.assertIsNotNone(root.diagnostic_service)
        self.assertIsNotNone(root.event_service)

    def test_get_root_singleton(self):
        reset_root()
        r1 = get_root()
        r2 = get_root()
        self.assertIs(r1, r2)

    def test_reset_root(self):
        reset_root()
        r1 = get_root()
        reset_root()
        r2 = get_root()
        self.assertIsNot(r1, r2)


# ---------------------------------------------------------------------------
# Endpoints REST — Info
# ---------------------------------------------------------------------------


class TestInfoEndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_info_returns_version(self):
        r = self.client.get("/info")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        # Sprint 14: /info agora retorna Versioned<InfoDTO>.
        self.assertIn("api", data)
        self.assertIn("payload", data)
        payload = data["payload"]
        self.assertEqual(payload["name"], "AI Lyrics API")
        self.assertIn("version", payload)
        self.assertIn("api_version", payload)
        self.assertIn("major", payload["api_version"])
        self.assertIn("server_time", payload)

    def test_info_trailing_slash(self):
        r = self.client.get("/info/")
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# Endpoints REST — Health
# ---------------------------------------------------------------------------


class TestHealthEndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_health_returns_snapshot(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        # Versioned<T> envelope
        self.assertIn("api", data)
        self.assertIn("payload", data)
        payload = data["payload"]
        self.assertIn("timestamp", payload)
        self.assertIn("components", payload)
        self.assertIn("component_count", payload)
        self.assertIn("all_healthy", payload)

    def test_health_live(self):
        r = self.client.get("/health/live")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "alive")

    def test_health_ready(self):
        r = self.client.get("/health/ready")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("ready", data)
        self.assertIn("all_healthy", data)


# ---------------------------------------------------------------------------
# Endpoints REST — Pipeline
# ---------------------------------------------------------------------------


class TestPipelineEndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_pipeline_status(self):
        r = self.client.get("/pipeline/status")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        payload = data["payload"]
        self.assertIn("running", payload)
        self.assertIn("paused", payload)
        self.assertIn("is_active", payload)

    def test_pipeline_session(self):
        r = self.client.get("/pipeline/session")
        self.assertEqual(r.status_code, 200)
        payload = r.json()["payload"]
        self.assertIn("session_id", payload)

    def test_pipeline_metrics(self):
        r = self.client.get("/pipeline/metrics")
        self.assertEqual(r.status_code, 200)
        payload = r.json()["payload"]
        self.assertIn("segments_received", payload)

    def test_pipeline_snapshot(self):
        r = self.client.get("/pipeline/snapshot")
        self.assertEqual(r.status_code, 200)
        payload = r.json()["payload"]
        self.assertIn("timestamp", payload)
        self.assertIn("status", payload)
        self.assertIn("session", payload)
        self.assertIn("metrics", payload)


# ---------------------------------------------------------------------------
# Endpoints REST — Session
# ---------------------------------------------------------------------------


class TestSessionEndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_session_current(self):
        r = self.client.get("/session/current")
        self.assertEqual(r.status_code, 200)
        payload = r.json()["payload"]
        self.assertIn("session_id", payload)
        self.assertEqual(payload["session_id"], "session-api-default")


# ---------------------------------------------------------------------------
# Endpoints REST — Metrics
# ---------------------------------------------------------------------------


class TestMetricsEndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_metrics(self):
        r = self.client.get("/metrics")
        self.assertEqual(r.status_code, 200)
        payload = r.json()["payload"]
        self.assertIn("segments_received", payload)
        self.assertIn("avg_latency_ms", payload)
        self.assertIn("throughput_segments_per_min", payload)


# ---------------------------------------------------------------------------
# Endpoints REST — Configuration
# ---------------------------------------------------------------------------


class TestConfigurationEndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_configuration(self):
        r = self.client.get("/configuration")
        self.assertEqual(r.status_code, 200)
        payload = r.json()["payload"]
        # Sprint 14: config real carregada de config.yaml.
        # mode pode ser "auto", "confirm" ou "quick".
        self.assertIn(payload["mode"], {"auto", "confirm", "quick", "production"})
        self.assertIn("holyrics", payload)
        self.assertIn("stt", payload)
        self.assertIn("llm", payload)


# ---------------------------------------------------------------------------
# Endpoints REST — Diagnostics
# ---------------------------------------------------------------------------


class TestDiagnosticsEndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_diagnostics(self):
        r = self.client.get("/diagnostics")
        self.assertEqual(r.status_code, 200)
        payload = r.json()["payload"]
        self.assertIn("diagnostics", payload)
        self.assertIsInstance(payload["diagnostics"], list)
        self.assertGreater(len(payload["diagnostics"]), 0)


# ---------------------------------------------------------------------------
# Endpoints REST — Events
# ---------------------------------------------------------------------------


class TestEventsEndpoint(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_events_all(self):
        r = self.client.get("/events")
        self.assertEqual(r.status_code, 200)
        payload = r.json()["payload"]
        self.assertIn("events", payload)
        self.assertIn("count", payload)

    def test_events_by_correlation(self):
        r = self.client.get("/events/by-correlation", params={"correlation_id": "nonexistent"})
        self.assertEqual(r.status_code, 200)
        payload = r.json()["payload"]
        self.assertEqual(payload["count"], 0)

    def test_events_by_session(self):
        r = self.client.get("/events/by-session", params={"session_id": "nonexistent"})
        self.assertEqual(r.status_code, 200)
        payload = r.json()["payload"]
        self.assertEqual(payload["count"], 0)

    def test_events_snapshot(self):
        r = self.client.get("/events/snapshot")
        self.assertEqual(r.status_code, 200)
        payload = r.json()["payload"]
        self.assertIn("timestamp", payload)
        self.assertIn("events", payload)
        self.assertIn("event_count", payload)


# ---------------------------------------------------------------------------
# Versionamento — Versioned<T> envelope
# ---------------------------------------------------------------------------


class TestVersioning(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_all_endpoints_return_versioned(self):
        """Todos os endpoints de consulta devem retornar Versioned<T>."""
        endpoints = [
            "/health",
            "/pipeline/status",
            "/pipeline/session",
            "/pipeline/metrics",
            "/pipeline/snapshot",
            "/session/current",
            "/metrics",
            "/configuration",
            "/diagnostics",
            "/events",
            "/events/snapshot",
        ]
        for ep in endpoints:
            with self.subTest(endpoint=ep):
                r = self.client.get(ep)
                self.assertEqual(r.status_code, 200, f"{ep} returned {r.status_code}")
                data = r.json()
                self.assertIn("api", data, f"{ep} missing 'api' in response")
                self.assertIn("payload", data, f"{ep} missing 'payload' in response")
                api = data["api"]
                self.assertIn("major", api)
                self.assertIn("minor", api)
                self.assertIn("patch", api)

    def test_api_version_is_foundation(self):
        r = self.client.get("/pipeline/status")
        api = r.json()["api"]
        self.assertEqual(api["major"], 0)
        self.assertEqual(api["minor"], 1)
        self.assertEqual(api["patch"], 0)
        self.assertEqual(api["pre"], "foundation")


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


class TestWebSocket(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_websocket_hello(self):
        """WebSocket envia 'hello' com versão da API ao conectar."""
        with self.client.websocket_connect("/ws/events") as ws:
            raw = ws.receive_text()
            msg = json.loads(raw)
            self.assertEqual(msg["type"], "hello")
            self.assertIn("api", msg)
            self.assertEqual(msg["api"]["major"], 0)
            self.assertIn("server_time", msg)

    def test_websocket_heartbeat(self):
        """WebSocket responde heartbeat com heartbeat_ack."""
        with self.client.websocket_connect("/ws/events") as ws:
            # Consome hello.
            ws.receive_text()
            # Envia heartbeat.
            ws.send_text(json.dumps({"type": "heartbeat"}))
            raw = ws.receive_text()
            msg = json.loads(raw)
            self.assertEqual(msg["type"], "heartbeat_ack")
            self.assertIn("server_time", msg)

    def test_websocket_ping(self):
        """WebSocket responde ping com heartbeat_ack."""
        with self.client.websocket_connect("/ws/events") as ws:
            ws.receive_text()  # hello
            ws.send_text(json.dumps({"type": "ping"}))
            raw = ws.receive_text()
            msg = json.loads(raw)
            self.assertEqual(msg["type"], "heartbeat_ack")


# ---------------------------------------------------------------------------
# Schemas Pydantic
# ---------------------------------------------------------------------------


class TestSchemas(unittest.TestCase):

    def test_api_version_model(self):
        from api.schemas import ApiVersionModel
        v = ApiVersionModel(major=0, minor=1, patch=0, pre="foundation")
        self.assertEqual(v.major, 0)
        self.assertEqual(v.pre, "foundation")

    def test_versioned_helper(self):
        from api.schemas import versioned, ApiVersionModel
        result = versioned({"foo": "bar"})
        self.assertIn("api", result)
        self.assertIn("payload", result)
        self.assertEqual(result["payload"]["foo"], "bar")

    def test_versioned_with_model(self):
        from api.schemas import versioned, ApiVersionModel
        v = ApiVersionModel(major=1, minor=0, patch=0)
        result = versioned(v)
        self.assertEqual(result["payload"]["major"], 1)

    def test_presentation_error_model(self):
        from api.schemas import PresentationErrorModel
        e = PresentationErrorModel(
            code="UNKNOWN",
            message="Test error",
            recoverable=True,
            severity="low",
        )
        self.assertEqual(e.code, "UNKNOWN")
        self.assertTrue(e.recoverable)
        self.assertEqual(e.severity, "low")

    def test_ws_hello_model(self):
        from api.schemas import WsHelloModel, ApiVersionModel
        h = WsHelloModel(api=ApiVersionModel(major=0, minor=1, patch=0), server_time=100.0)
        self.assertEqual(h.type, "hello")
        self.assertEqual(h.server_time, 100.0)


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------


class TestErrorHandling(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_404_returns_presentation_error(self):
        r = self.client.get("/nonexistent")
        self.assertEqual(r.status_code, 404)
        data = r.json()
        self.assertIn("code", data)
        self.assertEqual(data["code"], "SERVICE_NOT_FOUND")
        self.assertIn("message", data)


# ---------------------------------------------------------------------------
# CORS Middleware
# ---------------------------------------------------------------------------


class TestCorsMiddleware(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_cors_headers_present(self):
        r = self.client.options(
            "/info",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS preflight deve retornar 200.
        self.assertIn(r.status_code, (200, 204))


if __name__ == "__main__":
    unittest.main()
