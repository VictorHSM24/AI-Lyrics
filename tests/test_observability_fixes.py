"""Testes das correções de observabilidade (débitos técnicos pós live-test).

Cobre:
  - Bus wildcard "*" recebe TODOS os eventos (incluindo TelemetryEvents).
  - AuditingEventStore delega consultas e persiste eventos no recorder.
  - HealthPresentationService usa estado vivo do pipeline_service.
  - ws_client_count_provider fornece contagem real de clientes.
  - MetricsMapper inclui seção "streaming" quando coletor presente.
"""

from __future__ import annotations

import time

import pytest

from pipeline.auditing_event_store import AuditingEventStore
from pipeline.bus import PipelineEventBus
from pipeline.event_store import EventStorePolicy, MemoryEventStore
from pipeline.state import PipelineState
from presentation.mappers import MetricsMapper
from presentation.services import (
    DiagnosticPresentationService,
    HealthPresentationService,
    PipelinePresentationService,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_event():
    """Cria um evento operacional real."""
    from pipeline.events import PipelineStarted
    from pipeline.metadata import EventMetadata

    return PipelineStarted(meta=EventMetadata.for_initial(
        origin="test", session_id="test-session",
    ))


@pytest.fixture(autouse=True)
def _recorder(tmp_path, monkeypatch):
    """Configura recorder real em tmp_path por teste."""
    from telemetry.recorder import configure_recorder, shutdown_recorder

    configure_recorder(output_dir=str(tmp_path), enabled=True)
    yield
    shutdown_recorder()


# ---------------------------------------------------------------------------
# Wildcard "*" no EventBus
# ---------------------------------------------------------------------------


class TestWildcardSubscription:
    def test_wildcard_receives_all_events(self):
        bus = PipelineEventBus()
        received = []
        bus.subscribe("*", received.append)

        bus.publish(_make_event())
        bus.publish(_make_event())

        assert len(received) == 2

    def test_wildcard_receives_telemetry_events(self):
        """TelemetryEvents não são persistidos, mas handlers devem receber."""
        from dataclasses import dataclass
        from pipeline.events import TelemetryEvent
        from pipeline.metadata import EventMetadata

        bus = PipelineEventBus()
        received = []
        bus.subscribe("*", received.append)

        @dataclass(frozen=True)
        class _Tel(TelemetryEvent):
            pass

        evt = _Tel(meta=EventMetadata.for_initial(
            session_id="t", origin="t",
        ))
        bus.publish(evt)

        assert received == [evt]
        # Telemetria não vai para o store.
        assert bus.event_count() == 0

    def test_wildcard_does_not_duplicate_handler(self):
        bus = PipelineEventBus()
        received = []
        bus.subscribe("*", received.append)
        bus.subscribe("*", received.append)
        bus.publish(_make_event())
        assert len(received) == 1

    def test_invalid_event_type_still_raises(self):
        bus = PipelineEventBus()
        with pytest.raises(TypeError):
            bus.subscribe("not-a-class", lambda e: None)


# ---------------------------------------------------------------------------
# AuditingEventStore
# ---------------------------------------------------------------------------


class TestAuditingEventStore:
    def test_delegates_queries(self):
        inner = MemoryEventStore(EventStorePolicy())
        store = AuditingEventStore(inner)
        evt = _make_event()
        store.append(evt)

        assert store.count() == 1
        assert store.last() is evt
        assert store.all() == (evt,)
        assert inner.count() == 1

    def test_append_many_audits_each(self, tmp_path):
        store = AuditingEventStore(MemoryEventStore())
        store.append_many([_make_event(), _make_event()])
        assert store.count() == 2

        # Aguardar a thread do recorder drenar.
        from telemetry import get_recorder
        rec = get_recorder()
        time.sleep(0.5)
        session_dir = rec.session_dir
        events_file = session_dir / "events.jsonl"
        assert events_file.exists()
        lines = events_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_events_jsonl_content(self, tmp_path):
        store = AuditingEventStore(MemoryEventStore())
        store.append(_make_event())
        time.sleep(0.5)

        from telemetry import get_recorder
        events_file = get_recorder().session_dir / "events.jsonl"
        line = events_file.read_text(encoding="utf-8").strip()
        import json
        data = json.loads(line)
        assert data["event"] == "PipelineStarted"
        assert "timestamp" in data
        assert "payload" in data

    def test_policy_and_statistics_delegate(self):
        policy = EventStorePolicy(max_events=10)
        inner = MemoryEventStore(policy)
        store = AuditingEventStore(inner)
        assert store.policy is policy
        assert store.statistics is inner.statistics


# ---------------------------------------------------------------------------
# HealthPresentationService — estado vivo do pipeline
# ---------------------------------------------------------------------------


def _pipeline_service():
    state = PipelineState()
    from pipeline.metrics import PipelineMetrics
    return PipelinePresentationService(
        state=state, session=None, metrics=PipelineMetrics(),
    )


class TestHealthLiveState:
    def test_pipeline_health_reflects_live_state(self):
        svc = _pipeline_service()
        # Snapshot congelada: running=False.
        stale_state = PipelineState()
        health = HealthPresentationService(
            pipeline_state=stale_state,
            pipeline_service=svc,
        )
        assert health.pipeline_health().status == "unhealthy"

        # Iniciar pipeline — o service substitui seu _state interno.
        svc._set_state(svc._state.with_running(True))
        h = health.pipeline_health()
        assert h.status == "healthy"
        assert h.message == "Pipeline em execução"

        svc._set_state(svc._state.with_paused(True))
        assert health.pipeline_health().status == "degraded"

        svc._set_state(svc._state.with_running(False))
        assert health.pipeline_health().status == "unhealthy"

    def test_pipeline_health_fallback_to_snapshot(self):
        stale = PipelineState()
        health = HealthPresentationService(pipeline_state=stale)
        assert health.pipeline_health().status == "unhealthy"

    def test_pipeline_health_unknown_when_nothing(self):
        health = HealthPresentationService()
        assert health.pipeline_health().status == "unknown"

    def test_ws_client_count_provider(self):
        health = HealthPresentationService(
            ws_client_count_provider=lambda: 3,
        )
        h = health.websocket_health()
        assert h.details["connected_clients"] == 3

    def test_ws_client_count_static_fallback(self):
        health = HealthPresentationService(ws_client_count=2)
        h = health.websocket_health()
        assert h.details["connected_clients"] == 2


class TestDiagnosticLiveState:
    def test_pipeline_diagnostic_reflects_live_state(self):
        svc = _pipeline_service()
        diag = DiagnosticPresentationService(
            pipeline_state=PipelineState(),
            pipeline_service=svc,
        )
        d = diag.pipeline_diagnostic()
        assert d.available is False

        svc._set_state(svc._state.with_running(True))
        d = diag.pipeline_diagnostic()
        assert d.available is True
        assert d.info["running"] is True


# ---------------------------------------------------------------------------
# MetricsMapper — seção streaming
# ---------------------------------------------------------------------------


class _StubStreamingMetrics:
    def to_dict(self):
        return {"streaming_stt": {"total_windows": 42}}


class TestMetricsStreaming:
    def test_streaming_section_present(self):
        from pipeline.metrics import PipelineMetrics
        dto = MetricsMapper.to_dto(
            PipelineMetrics(), streaming=_StubStreamingMetrics(),
        )
        assert dto.streaming is not None
        assert dto.streaming["streaming_stt"]["total_windows"] == 42

    def test_streaming_none_when_absent(self):
        from pipeline.metrics import PipelineMetrics
        dto = MetricsMapper.to_dto(PipelineMetrics())
        assert dto.streaming is None

    def test_streaming_dict_passthrough(self):
        from pipeline.metrics import PipelineMetrics
        dto = MetricsMapper.to_dto(
            PipelineMetrics(), streaming={"custom": 1},
        )
        assert dto.streaming == {"custom": 1}
