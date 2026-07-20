"""Testes dos endpoints POST /pipeline/start e POST /pipeline/stop (Sprint 17.1).

Cobre:
  - POST /pipeline/start inicia AudioCapture + SpeechPipeline + SpeechWorker.
  - POST /pipeline/stop para todos os componentes na ordem inversa.
  - PipelineState é atualizado (running=True/False).
  - Eventos PipelineStarted/PipelineStopped são publicados no EventBus.
  - Endpoint é idempotente (start quando já rodando não falha).
  - Resposta retorna PipelineStatusModel atualizado.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.app import create_app
from api.startup import reset_root, set_root
from api.startup.composition import CompositionRoot
from pipeline.bus import PipelineEventBus
from pipeline.events import PipelineStarted, PipelineStopped
from pipeline.state import PipelineState
from pipeline.session import PipelineSession
from pipeline.metrics import PipelineMetrics
from presentation.services import PipelinePresentationService


def _make_composition_root(
    audio_capture=None,
    speech_pipeline=None,
    speech_worker=None,
    bus=None,
    state=None,
    pipeline_service=None,
) -> CompositionRoot:
    """Cria um CompositionRoot mock para testes."""
    if bus is None:
        bus = PipelineEventBus(store=MagicMock())
    if state is None:
        state = PipelineState()
    if pipeline_service is None:
        session = PipelineSession.create(session_id="test-session")
        metrics = PipelineMetrics()
        pipeline_service = PipelinePresentationService(
            state=state, session=session, metrics=metrics, bus=bus,
        )

    return CompositionRoot(
        bus=bus,
        store=MagicMock(),
        state=state,
        session=MagicMock(),
        metrics=MagicMock(),
        policy=MagicMock(),
        config=MagicMock(),
        pipeline_service=pipeline_service,
        session_service=MagicMock(),
        metrics_service=MagicMock(),
        configuration_service=MagicMock(),
        health_service=MagicMock(),
        diagnostic_service=MagicMock(),
        event_service=MagicMock(),
        audio_service=MagicMock(),
        system_service=MagicMock(),
        info_service=MagicMock(),
        audio_capture=audio_capture,
        stt=None,
        speech_queue=None,
        speech_pipeline=speech_pipeline,
        speech_worker=speech_worker,
        nlu_service=None,
    )


class TestPipelineStartStop(unittest.TestCase):
    """Testes dos endpoints POST /pipeline/start e /pipeline/stop."""

    def setUp(self):
        reset_root()
        self.audio_capture = MagicMock()
        self.audio_capture.start = MagicMock(return_value={"device_index": 0})
        self.audio_capture.stop = MagicMock(return_value={"device_index": 0})
        self.audio_capture.capturing = False

        self.speech_pipeline = MagicMock()
        self.speech_pipeline.is_running = False
        def _sp_start():
            self.speech_pipeline.is_running = True
        def _sp_stop():
            self.speech_pipeline.is_running = False
        self.speech_pipeline.start = MagicMock(side_effect=_sp_start)
        self.speech_pipeline.stop = MagicMock(side_effect=_sp_stop)

        self.speech_worker = MagicMock()
        self.speech_worker.is_running = False
        def _sw_start():
            self.speech_worker.is_running = True
        def _sw_stop():
            self.speech_worker.is_running = False
        self.speech_worker.start = MagicMock(side_effect=_sw_start)
        self.speech_worker.stop = MagicMock(side_effect=_sw_stop)

        self.bus = PipelineEventBus(store=MagicMock())
        self.state = PipelineState()
        self.session = PipelineSession.create(session_id="test-session")
        self.metrics = PipelineMetrics()
        self.pipeline_service = PipelinePresentationService(
            state=self.state, session=self.session, metrics=self.metrics, bus=self.bus,
        )

        self.root = _make_composition_root(
            audio_capture=self.audio_capture,
            speech_pipeline=self.speech_pipeline,
            speech_worker=self.speech_worker,
            bus=self.bus,
            state=self.state,
            pipeline_service=self.pipeline_service,
        )
        set_root(self.root)

        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self):
        reset_root()

    def test_start_pipeline(self):
        """POST /pipeline/start inicia todos os componentes."""
        resp = self.client.post("/pipeline/start")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        payload = data["payload"]
        self.assertTrue(payload["running"])

        # Verificar que os componentes foram iniciados.
        self.audio_capture.start.assert_called_once()
        self.speech_pipeline.start.assert_called_once()
        self.speech_worker.start.assert_called_once()

    def test_stop_pipeline(self):
        """POST /pipeline/stop para todos os componentes."""
        # Primeiro iniciar.
        self.client.post("/pipeline/start")
        # Resetar mocks para verificar stop.
        self.audio_capture.stop.reset_mock()
        self.speech_pipeline.stop.reset_mock()
        self.speech_worker.stop.reset_mock()

        resp = self.client.post("/pipeline/stop")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        payload = data["payload"]
        self.assertFalse(payload["running"])

        # Verificar que os componentes foram parados.
        self.audio_capture.stop.assert_called_once()
        self.speech_pipeline.stop.assert_called_once()
        self.speech_worker.stop.assert_called_once()

    def test_start_publishes_pipeline_started_event(self):
        """POST /pipeline/start publica PipelineStarted no EventBus."""
        events = []
        self.bus.subscribe(PipelineStarted, events.append)

        self.client.post("/pipeline/start")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "PipelineStarted")

    def test_stop_publishes_pipeline_stopped_event(self):
        """POST /pipeline/stop publica PipelineStopped no EventBus."""
        events = []
        self.bus.subscribe(PipelineStopped, events.append)

        self.client.post("/pipeline/start")
        self.client.post("/pipeline/stop")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "PipelineStopped")

    def test_start_is_idempotent(self):
        """POST /pipeline/start é idempotente — não falha se já rodando."""
        self.client.post("/pipeline/start")
        # Segundo start não deve falhar.
        resp = self.client.post("/pipeline/start")
        self.assertEqual(resp.status_code, 200)

    def test_stop_is_idempotent(self):
        """POST /pipeline/stop é idempotente — não falha se já parado."""
        resp = self.client.post("/pipeline/stop")
        self.assertEqual(resp.status_code, 200)

    def test_start_updates_pipeline_state(self):
        """POST /pipeline/start atualiza PipelineState.running=True."""
        self.assertFalse(self.pipeline_service.is_running())
        self.client.post("/pipeline/start")
        self.assertTrue(self.pipeline_service.is_running())

    def test_stop_updates_pipeline_state(self):
        """POST /pipeline/stop atualiza PipelineState.running=False."""
        self.client.post("/pipeline/start")
        self.assertTrue(self.pipeline_service.is_running())
        self.client.post("/pipeline/stop")
        self.assertFalse(self.pipeline_service.is_running())

    def test_start_without_audio_capture(self):
        """POST /pipeline/start funciona mesmo sem audio_capture."""
        root = _make_composition_root(
            audio_capture=None,
            speech_pipeline=self.speech_pipeline,
            speech_worker=self.speech_worker,
            bus=self.bus,
            state=self.state,
            pipeline_service=self.pipeline_service,
        )
        set_root(root)
        resp = self.client.post("/pipeline/start")
        self.assertEqual(resp.status_code, 200)

    def test_start_without_speech_pipeline(self):
        """POST /pipeline/start funciona mesmo sem speech_pipeline."""
        root = _make_composition_root(
            audio_capture=self.audio_capture,
            speech_pipeline=None,
            speech_worker=self.speech_worker,
            bus=self.bus,
            state=self.state,
            pipeline_service=self.pipeline_service,
        )
        set_root(root)
        resp = self.client.post("/pipeline/start")
        self.assertEqual(resp.status_code, 200)

    def test_start_without_speech_worker(self):
        """POST /pipeline/start funciona mesmo sem speech_worker."""
        root = _make_composition_root(
            audio_capture=self.audio_capture,
            speech_pipeline=self.speech_pipeline,
            speech_worker=None,
            bus=self.bus,
            state=self.state,
            pipeline_service=self.pipeline_service,
        )
        set_root(root)
        resp = self.client.post("/pipeline/start")
        self.assertEqual(resp.status_code, 200)

    def test_start_stop_full_cycle(self):
        """Ciclo completo: start → verificar rodando → stop → verificar parado."""
        # Start
        resp = self.client.post("/pipeline/start")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["payload"]["running"])

        # Stop
        resp = self.client.post("/pipeline/stop")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["payload"]["running"])

        # Start novamente (deve funcionar)
        resp = self.client.post("/pipeline/start")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["payload"]["running"])

        # Stop novamente
        resp = self.client.post("/pipeline/stop")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["payload"]["running"])


if __name__ == "__main__":
    unittest.main()
