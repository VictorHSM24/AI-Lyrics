"""Testes dos endpoints /audio — Sprint 15.1.

Cobertura:
  - GET /audio/devices
  - GET /audio/current
  - GET /audio/levels
  - POST /audio/start
  - POST /audio/stop
  - POST /audio/select
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.startup import reset_root, set_root
from api.startup.composition import CompositionRoot


def _make_mock_root() -> CompositionRoot:
    """Cria um CompositionRoot com serviços mockados."""
    from presentation.services_system import (
        AudioPresentationService, SystemPresentationService, InfoPresentationService,
    )
    from presentation.services import (
        PipelinePresentationService, SessionPresentationService,
        MetricsPresentationService, ConfigurationPresentationService,
        HealthPresentationService, DiagnosticPresentationService,
        EventPresentationService,
    )

    # Mock do AudioCaptureService.
    mock_capture = MagicMock()
    mock_capture.capturing = False
    mock_capture.device_index = None
    mock_capture.sample_rate = 16000
    mock_capture.channels = 1
    mock_capture.list_devices.return_value = [
        {"index": 0, "name": "Mic Mock 1", "channels": 1,
         "sample_rate": 16000.0, "is_default": True, "available": True},
        {"index": 1, "name": "Mic Mock 2", "channels": 2,
         "sample_rate": 48000.0, "is_default": False, "available": True},
    ]
    mock_capture.get_current_device.return_value = {
        "index": 0, "name": "Mic Mock 1", "channels": 1,
        "sample_rate": 16000.0, "is_default": True, "available": True,
    }
    mock_capture.get_latest_frame.return_value = None
    mock_capture.start.return_value = {
        "capturing": True, "already": False,
        "device_index": 0, "sample_rate": 16000, "channels": 1,
    }
    mock_capture.stop.return_value = {"capturing": False, "already": False}
    mock_capture.select_device.return_value = {
        "device_index": 1, "restarted": False,
    }

    audio_service = AudioPresentationService(capture_service=mock_capture)

    # Mocks mínimos para outros serviços.
    pipeline_service = MagicMock(spec=PipelinePresentationService)
    session_service = MagicMock(spec=SessionPresentationService)
    metrics_service = MagicMock(spec=MetricsPresentationService)
    config_service = MagicMock(spec=ConfigurationPresentationService)
    health_service = MagicMock(spec=HealthPresentationService)
    diagnostic_service = MagicMock(spec=DiagnosticPresentationService)
    event_service = MagicMock(spec=EventPresentationService)
    system_service = MagicMock(spec=SystemPresentationService)
    info_service = MagicMock(spec=InfoPresentationService)

    root = CompositionRoot(
        config=MagicMock(),
        state=MagicMock(),
        session=MagicMock(),
        metrics=MagicMock(),
        store=MagicMock(),
        bus=MagicMock(),
        policy=MagicMock(),
        pipeline_service=pipeline_service,
        session_service=session_service,
        metrics_service=metrics_service,
        configuration_service=config_service,
        health_service=health_service,
        diagnostic_service=diagnostic_service,
        event_service=event_service,
        audio_service=audio_service,
        system_service=system_service,
        info_service=info_service,
        audio_capture=mock_capture,
        stt=None,
        speech_queue=None,
        speech_pipeline=None,
        speech_worker=None,
        nlu_service=None,
    )
    return root


class TestAudioEndpoints(unittest.TestCase):
    """Testes dos endpoints /audio."""

    def setUp(self):
        reset_root()
        self.root = _make_mock_root()
        set_root(self.root)
        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self):
        reset_root()

    def test_get_devices(self):
        resp = self.client.get("/audio/devices")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("payload", data)
        self.assertIn("devices", data["payload"])
        self.assertEqual(data["payload"]["count"], 2)
        self.assertEqual(data["payload"]["devices"][0]["name"], "Mic Mock 1")

    def test_get_current_device(self):
        resp = self.client.get("/audio/current")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("device", data["payload"])
        self.assertEqual(data["payload"]["device"]["name"], "Mic Mock 1")

    def test_get_levels(self):
        # Sem frame no buffer — retorna zeros.
        resp = self.client.get("/audio/levels")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("rms", data["payload"])
        self.assertIn("peak", data["payload"])
        self.assertEqual(data["payload"]["rms"], 0.0)

    def test_post_start(self):
        resp = self.client.post("/audio/start")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["payload"]["capturing"])
        self.root.audio_capture.start.assert_called_once()

    def test_post_stop(self):
        resp = self.client.post("/audio/stop")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["payload"]["capturing"])
        self.root.audio_capture.stop.assert_called_once()

    def test_post_select(self):
        resp = self.client.post("/audio/select", json={"device_index": 1})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["payload"]["device_index"], 1)
        self.root.audio_capture.select_device.assert_called_once_with(1)

    def test_post_select_invalid_no_body(self):
        resp = self.client.post("/audio/select")
        self.assertEqual(resp.status_code, 422)  # Validation error.

    def test_post_select_invalid_index(self):
        # Mock para lançar ValueError.
        self.root.audio_capture.select_device.side_effect = ValueError("Invalid index")
        resp = self.client.post("/audio/select", json={"device_index": 999})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
