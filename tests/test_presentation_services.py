"""Testes de Snapshots, Observers, Services e Adapters.

Cobre:
  - Snapshots: imutabilidade, to_dict, SnapshotFactory.
  - Observers: EventObserver, PipelineObserver, MetricsObserver,
    SessionObserver, inscrição no EventBus, callbacks.
  - Services: PipelinePresentationService, SessionPresentationService,
    MetricsPresentationService, ConfigurationPresentationService,
    HealthPresentationService, DiagnosticPresentationService,
    EventPresentationService.
  - Adapters: RestAdapter, WebSocketAdapter, CliAdapter,
    DashboardAdapter, ReplayAdapter (contratos ABC).
  - Integração completa: Pipeline + Observers + Services.
  - Compatibilidade: Core funciona sem Presentation Layer.
"""

from __future__ import annotations

import unittest

import sys
sys.path.insert(0, ".")

from pipeline import (
    EventMetadata,
    PipelineEventBus,
    PipelineMetrics,
    PipelinePolicy,
    PipelineSession,
    PipelineState,
    SpeechRecognized,
    SpeechSegmentReceived,
    SearchRequested,
    SearchCompleted,
)
from presentation import (
    BaseAdapter,
    BaseObserver,
    CliAdapter,
    ConfigurationPresentationService,
    ConfigurationSnapshot,
    DashboardAdapter,
    DiagnosticPresentationService,
    EventDTO,
    EventObserver,
    EventPresentationService,
    EventSnapshot,
    HealthPresentationService,
    HealthSnapshot,
    LogMapper,
    MetricsObserver,
    MetricsPresentationService,
    MetricsSnapshot,
    PipelineObserver,
    PipelinePresentationService,
    PipelineSnapshot,
    ReplayAdapter,
    RestAdapter,
    SessionObserver,
    SessionPresentationService,
    SessionSnapshot,
    SnapshotFactory,
    WebSocketAdapter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_meta(**kwargs):
    defaults = dict(
        event_id="e1", correlation_id="c1", causation_id=None,
        session_id="s1", timestamp=100.0, origin="test")
    defaults.update(kwargs)
    return EventMetadata(**defaults)


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


class TestSnapshots(unittest.TestCase):
    """Testes dos Snapshots."""

    def test_pipeline_snapshot_is_frozen(self):
        from presentation import PipelineStatusDTO, SessionDTO, MetricsDTO
        status = PipelineStatusDTO(
            running=True, paused=False, is_active=True,
            is_idle=False, is_processing=False, current_segment=None,
            last_query="", last_candidate_id="",
            last_event_type="", last_event_timestamp=0.0)
        session = SessionDTO(
            session_id="s1", started_at=100.0, ended_at=0.0,
            is_active=True, is_ended=False, duration_s=0.0,
            processed_segments=0, processed_queries=0, presentations=0,
            errors=0, error_rate=0.0, presentation_rate=0.0,
            segments_per_minute=0.0, queries_per_minute=0.0,
            unique_correlations=0)
        metrics = MetricsDTO(
            segments_received=0, segments_processed=0, segments_dropped=0,
            queries_processed=0, presentations_executed=0,
            presentations_failed=0, errors_total=0,
            errors_recoverable=0, errors_fatal=0,
            total_latency_ms=0.0, avg_latency_ms=0.0,
            avg_recognition_latency_ms=0.0, avg_search_latency_ms=0.0,
            avg_ranking_latency_ms=0.0, avg_intelligence_latency_ms=0.0,
            avg_presentation_latency_ms=0.0,
            throughput_segments_per_min=0.0, throughput_queries_per_min=0.0,
            error_rate=0.0, drop_rate=0.0,
            presentation_success_rate=0.0,
            processing_success_rate=0.0, duration_s=0.0,
            correlation_count=0)
        snap = PipelineSnapshot(
            timestamp=100.0, status=status, session=session, metrics=metrics)
        with self.assertRaises(Exception):
            snap.timestamp = 200.0  # type: ignore

    def test_pipeline_snapshot_to_dict(self):
        from presentation import PipelineStatusDTO, SessionDTO, MetricsDTO
        status = PipelineStatusDTO(
            running=True, paused=False, is_active=True,
            is_idle=False, is_processing=False, current_segment=None,
            last_query="", last_candidate_id="",
            last_event_type="", last_event_timestamp=0.0)
        session = SessionDTO(
            session_id="s1", started_at=100.0, ended_at=0.0,
            is_active=True, is_ended=False, duration_s=0.0,
            processed_segments=0, processed_queries=0, presentations=0,
            errors=0, error_rate=0.0, presentation_rate=0.0,
            segments_per_minute=0.0, queries_per_minute=0.0,
            unique_correlations=0)
        metrics = MetricsDTO(
            segments_received=0, segments_processed=0, segments_dropped=0,
            queries_processed=0, presentations_executed=0,
            presentations_failed=0, errors_total=0,
            errors_recoverable=0, errors_fatal=0,
            total_latency_ms=0.0, avg_latency_ms=0.0,
            avg_recognition_latency_ms=0.0, avg_search_latency_ms=0.0,
            avg_ranking_latency_ms=0.0, avg_intelligence_latency_ms=0.0,
            avg_presentation_latency_ms=0.0,
            throughput_segments_per_min=0.0, throughput_queries_per_min=0.0,
            error_rate=0.0, drop_rate=0.0,
            presentation_success_rate=0.0,
            processing_success_rate=0.0, duration_s=0.0,
            correlation_count=0)
        snap = PipelineSnapshot(
            timestamp=100.0, status=status, session=session, metrics=metrics)
        d = snap.to_dict()
        self.assertEqual(d["timestamp"], 100.0)
        self.assertIn("status", d)
        self.assertIn("session", d)
        self.assertIn("metrics", d)

    def test_health_snapshot(self):
        from presentation import HealthDTO
        h1 = HealthDTO(component="a", status="healthy")
        h2 = HealthDTO(component="b", status="unhealthy")
        snap = HealthSnapshot(timestamp=100.0, components=(h1, h2))
        self.assertEqual(snap.component_count, 2)
        self.assertEqual(snap.healthy_count, 1)
        self.assertEqual(snap.unhealthy_count, 1)
        self.assertFalse(snap.all_healthy)

    def test_health_snapshot_all_healthy(self):
        from presentation import HealthDTO
        h1 = HealthDTO(component="a", status="healthy")
        h2 = HealthDTO(component="b", status="healthy")
        snap = HealthSnapshot(timestamp=100.0, components=(h1, h2))
        self.assertTrue(snap.all_healthy)

    def test_health_snapshot_component(self):
        from presentation import HealthDTO
        h1 = HealthDTO(component="pipeline", status="healthy")
        snap = HealthSnapshot(timestamp=100.0, components=(h1,))
        c = snap.component("pipeline")
        self.assertIsNotNone(c)
        self.assertEqual(c.status, "healthy")
        self.assertIsNone(snap.component("nonexistent"))

    def test_event_snapshot(self):
        meta = _make_meta()
        from presentation import EventMapper
        ev = SpeechRecognized(meta=meta, text="hello")
        dto = EventMapper.to_dto(ev)
        snap = EventSnapshot(timestamp=100.0, events=(dto,), correlation_id="c1")
        self.assertEqual(snap.event_count, 1)
        self.assertEqual(snap.event_types, ("SpeechRecognized",))
        self.assertEqual(snap.correlation_id, "c1")

    def test_snapshot_factory_pipeline(self):
        state = PipelineState(running=True)
        session = PipelineSession.create(session_id="s1")
        metrics = PipelineMetrics()
        snap = SnapshotFactory.pipeline_snapshot(
            state, session, metrics, timestamp=100.0)
        self.assertIsInstance(snap, PipelineSnapshot)
        self.assertEqual(snap.timestamp, 100.0)
        self.assertTrue(snap.status.running)

    def test_snapshot_factory_session(self):
        session = PipelineSession.create(session_id="s1")
        snap = SnapshotFactory.session_snapshot(session, timestamp=100.0)
        self.assertIsInstance(snap, SessionSnapshot)
        self.assertEqual(snap.session.session_id, "s1")

    def test_snapshot_factory_metrics(self):
        metrics = PipelineMetrics()
        snap = SnapshotFactory.metrics_snapshot(metrics, timestamp=100.0)
        self.assertIsInstance(snap, MetricsSnapshot)

    def test_snapshot_factory_health(self):
        from presentation import HealthDTO
        h = HealthDTO(component="a", status="healthy")
        snap = SnapshotFactory.health_snapshot((h,), timestamp=100.0)
        self.assertIsInstance(snap, HealthSnapshot)
        self.assertEqual(snap.component_count, 1)

    def test_snapshot_factory_event(self):
        meta = _make_meta()
        from presentation import EventMapper
        ev = SpeechRecognized(meta=meta, text="hello")
        dto = EventMapper.to_dto(ev)
        snap = SnapshotFactory.event_snapshot((dto,), correlation_id="c1", timestamp=100.0)
        self.assertIsInstance(snap, EventSnapshot)
        self.assertEqual(snap.event_count, 1)


# ---------------------------------------------------------------------------
# Observers
# ---------------------------------------------------------------------------


class TestEventObserver(unittest.TestCase):

    def test_observe_events(self):
        bus = PipelineEventBus()
        obs = EventObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta, text="hello"))
        bus.publish(SearchRequested(meta=meta, query="hello"))
        self.assertEqual(obs.event_count, 2)
        self.assertEqual(obs.events[0].event_type, "SpeechRecognized")
        self.assertEqual(obs.events[1].event_type, "SearchRequested")

    def test_last_event(self):
        bus = PipelineEventBus()
        obs = EventObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta, text="hello"))
        last = obs.last_event()
        self.assertIsNotNone(last)
        self.assertEqual(last.event_type, "SpeechRecognized")

    def test_last_event_none(self):
        obs = EventObserver()
        self.assertIsNone(obs.last_event())

    def test_events_by_correlation(self):
        bus = PipelineEventBus()
        obs = EventObserver()
        obs.subscribe_to(bus)
        meta1 = _make_meta(correlation_id="c1", event_id="e1")
        meta2 = _make_meta(correlation_id="c2", event_id="e2")
        bus.publish(SpeechRecognized(meta=meta1, text="a"))
        bus.publish(SpeechRecognized(meta=meta2, text="b"))
        c1_events = obs.events_by_correlation("c1")
        self.assertEqual(len(c1_events), 1)
        self.assertEqual(c1_events[0].payload["text"], "a")

    def test_events_by_type(self):
        bus = PipelineEventBus()
        obs = EventObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta, text="a"))
        bus.publish(SearchRequested(meta=meta))
        recognized = obs.events_by_type("SpeechRecognized")
        self.assertEqual(len(recognized), 1)

    def test_snapshot(self):
        bus = PipelineEventBus()
        obs = EventObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta, text="a"))
        snap = obs.snapshot()
        self.assertEqual(snap.event_count, 1)

    def test_clear(self):
        bus = PipelineEventBus()
        obs = EventObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta, text="a"))
        obs.clear()
        self.assertEqual(obs.event_count, 0)
        self.assertIsNone(obs.last_event())

    def test_max_events_limit(self):
        obs = EventObserver(max_events=3)
        bus = PipelineEventBus()
        obs.subscribe_to(bus)
        for i in range(5):
            meta = _make_meta(event_id=f"e{i}")
            bus.publish(SpeechRecognized(meta=meta, text=f"t{i}"))
        self.assertEqual(obs.event_count, 3)
        # Deve manter os últimos 3
        self.assertEqual(obs.events[0].payload["text"], "t2")
        self.assertEqual(obs.events[2].payload["text"], "t4")


class TestPipelineObserver(unittest.TestCase):

    def test_started(self):
        from pipeline import PipelineStarted
        bus = PipelineEventBus()
        obs = PipelineObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(PipelineStarted(meta=meta))
        self.assertTrue(obs.running)
        self.assertFalse(obs.paused)
        self.assertTrue(obs.is_active)

    def test_stopped(self):
        from pipeline import PipelineStarted, PipelineStopped
        bus = PipelineEventBus()
        obs = PipelineObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(PipelineStarted(meta=meta))
        bus.publish(PipelineStopped(meta=meta))
        self.assertFalse(obs.running)
        self.assertFalse(obs.is_active)

    def test_paused_resumed(self):
        from pipeline import PipelineStarted, PipelinePaused, PipelineResumed
        bus = PipelineEventBus()
        obs = PipelineObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(PipelineStarted(meta=meta))
        bus.publish(PipelinePaused(meta=meta))
        self.assertTrue(obs.paused)
        self.assertFalse(obs.is_active)
        bus.publish(PipelineResumed(meta=meta))
        self.assertFalse(obs.paused)
        self.assertTrue(obs.is_active)

    def test_error_recorded(self):
        from pipeline import PipelineError
        bus = PipelineEventBus()
        obs = PipelineObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(PipelineError(
            meta=meta, error_type="ValueError",
            error_message="bad", handler_name="Test",
            recoverable=True))
        self.assertEqual(obs.error_count, 1)

    def test_health(self):
        from pipeline import PipelineStarted
        bus = PipelineEventBus()
        obs = PipelineObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(PipelineStarted(meta=meta))
        health = obs.health()
        self.assertTrue(health.is_healthy)

    def test_reset(self):
        from pipeline import PipelineStarted
        bus = PipelineEventBus()
        obs = PipelineObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(PipelineStarted(meta=meta))
        obs.reset()
        self.assertFalse(obs.running)


class TestMetricsObserver(unittest.TestCase):

    def test_counts(self):
        bus = PipelineEventBus()
        obs = MetricsObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta, text="a"))
        bus.publish(SpeechRecognized(meta=meta, text="b"))
        bus.publish(SearchRequested(meta=meta))
        self.assertEqual(obs.total_events, 3)
        self.assertEqual(obs.count_for("SpeechRecognized"), 2)
        self.assertEqual(obs.count_for("SearchRequested"), 1)

    def test_event_types(self):
        bus = PipelineEventBus()
        obs = MetricsObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta))
        bus.publish(SearchRequested(meta=meta))
        types = obs.event_types
        self.assertIn("SpeechRecognized", types)
        self.assertIn("SearchRequested", types)

    def test_reset(self):
        bus = PipelineEventBus()
        obs = MetricsObserver()
        obs.subscribe_to(bus)
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta))
        obs.reset()
        self.assertEqual(obs.total_events, 0)


class TestSessionObserver(unittest.TestCase):

    def test_session_tracking(self):
        bus = PipelineEventBus()
        obs = SessionObserver()
        obs.subscribe_to(bus)
        meta1 = _make_meta(session_id="s1")
        meta2 = _make_meta(session_id="s2", event_id="e2")
        bus.publish(SpeechRecognized(meta=meta1, text="a"))
        bus.publish(SpeechRecognized(meta=meta2, text="b"))
        self.assertEqual(obs.session_count, 2)
        self.assertIn("s1", obs.session_ids)
        self.assertIn("s2", obs.session_ids)

    def test_events_for_session(self):
        bus = PipelineEventBus()
        obs = SessionObserver()
        obs.subscribe_to(bus)
        meta1 = _make_meta(session_id="s1", event_id="e1")
        meta2 = _make_meta(session_id="s1", event_id="e2")
        meta3 = _make_meta(session_id="s2", event_id="e3")
        bus.publish(SpeechRecognized(meta=meta1, text="a"))
        bus.publish(SpeechRecognized(meta=meta2, text="b"))
        bus.publish(SpeechRecognized(meta=meta3, text="c"))
        s1_events = obs.events_for_session("s1")
        self.assertEqual(len(s1_events), 2)

    def test_current_session(self):
        bus = PipelineEventBus()
        obs = SessionObserver()
        obs.subscribe_to(bus)
        meta = _make_meta(session_id="s1")
        bus.publish(SpeechRecognized(meta=meta, text="a"))
        self.assertEqual(obs.current_session_id, "s1")


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


class TestPipelinePresentationService(unittest.TestCase):

    def test_get_status(self):
        state = PipelineState(running=True)
        session = PipelineSession.create(session_id="s1")
        metrics = PipelineMetrics()
        svc = PipelinePresentationService(state, session, metrics)
        status = svc.get_status()
        self.assertTrue(status.running)
        self.assertTrue(status.is_active)

    def test_get_session(self):
        state = PipelineState()
        session = PipelineSession.create(session_id="s1")
        metrics = PipelineMetrics()
        svc = PipelinePresentationService(state, session, metrics)
        sess = svc.get_session()
        self.assertEqual(sess.session_id, "s1")

    def test_get_metrics(self):
        state = PipelineState()
        session = PipelineSession.create(session_id="s1")
        metrics = PipelineMetrics()
        metrics.record_segment_received()
        svc = PipelinePresentationService(state, session, metrics)
        m = svc.get_metrics()
        self.assertEqual(m.segments_received, 1)

    def test_get_snapshot(self):
        state = PipelineState(running=True)
        session = PipelineSession.create(session_id="s1")
        metrics = PipelineMetrics()
        bus = PipelineEventBus()
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta, text="hello"))
        svc = PipelinePresentationService(state, session, metrics, bus)
        snap = svc.get_snapshot()
        self.assertIsInstance(snap, PipelineSnapshot)
        self.assertTrue(snap.status.running)
        self.assertIsNotNone(snap.last_event)

    def test_is_running(self):
        state = PipelineState(running=True)
        session = PipelineSession.create(session_id="s1")
        metrics = PipelineMetrics()
        svc = PipelinePresentationService(state, session, metrics)
        self.assertTrue(svc.is_running())
        self.assertTrue(svc.is_active())

    def test_is_paused(self):
        state = PipelineState(running=True, paused=True)
        session = PipelineSession.create(session_id="s1")
        metrics = PipelineMetrics()
        svc = PipelinePresentationService(state, session, metrics)
        self.assertTrue(svc.is_paused())
        self.assertFalse(svc.is_active())


class TestSessionPresentationService(unittest.TestCase):

    def test_get_session(self):
        session = PipelineSession.create(session_id="s1", started_at=100.0)
        svc = SessionPresentationService(session)
        dto = svc.get_session()
        self.assertEqual(dto.session_id, "s1")

    def test_get_snapshot(self):
        session = PipelineSession.create(session_id="s1")
        svc = SessionPresentationService(session)
        snap = svc.get_snapshot()
        self.assertIsInstance(snap, SessionSnapshot)

    def test_properties(self):
        session = PipelineSession.create(session_id="s1", started_at=100.0)
        session = session.with_segment_processed("c1")
        svc = SessionPresentationService(session)
        self.assertEqual(svc.session_id, "s1")
        self.assertTrue(svc.is_active)
        self.assertEqual(svc.processed_segments, 1)

    def test_has_correlation(self):
        session = PipelineSession.create(session_id="s1")
        session = session.with_segment_processed("c1")
        svc = SessionPresentationService(session)
        self.assertTrue(svc.has_correlation("c1"))
        self.assertFalse(svc.has_correlation("c2"))


class TestMetricsPresentationService(unittest.TestCase):

    def test_get_metrics(self):
        metrics = PipelineMetrics()
        metrics.record_segment_received()
        metrics.record_segment_processed(latency_ms=100.0)
        svc = MetricsPresentationService(metrics)
        dto = svc.get_metrics()
        self.assertEqual(dto.segments_received, 1)
        self.assertAlmostEqual(dto.avg_latency_ms, 100.0)

    def test_get_snapshot(self):
        metrics = PipelineMetrics()
        svc = MetricsPresentationService(metrics)
        snap = svc.get_snapshot()
        self.assertIsInstance(snap, MetricsSnapshot)

    def test_properties(self):
        metrics = PipelineMetrics()
        metrics.record_segment_received()
        svc = MetricsPresentationService(metrics)
        self.assertEqual(svc.segments_received, 1)


class TestConfigurationPresentationService(unittest.TestCase):

    def test_get_configuration(self):
        from config import (
            Config, HolyricsConfig, STTConfig, LLMConfig, SearchConfig,
            StateConfig, CacheConfig, ConfidenceConfig, LogConfig, VadConfig,
        )
        config = Config(
            holyrics=HolyricsConfig(base_url="http://localhost", token="t", timeout_ms=5000),
            stt=STTConfig(model="large-v3", device="cpu", compute_type="int8",
                          language="pt", chunk_length_s=30,
                          vad=VadConfig(mode="webrtcvad", min_speech_ms=500,
                                        pause_threshold_ms=800)),
            llm=LLMConfig(base_url="http://localhost", model="llama3",
                          lazy_load=True, timeout_ms=5000, max_tokens=100),
            search=SearchConfig(fts5_db="db.sqlite", embeddings_path="emb.pt",
                                embedding_model="model", embedding_device="cpu",
                                rrf_k=60, top_k=50, search_gap=0.2),
            state=StateConfig(default_version="ACF", persist_path="state.json"),
            cache=CacheConfig(recent_capacity=100, embedding_capacity=50,
                              holyrics_ttl_s=300, current_verse_ttl_s=60),
            confidence=ConfidenceConfig(min_execute=0.85, min_confirm=0.7,
                                         stt_min=0.5, parser_high=0.85,
                                         parser_compact=0.75),
            log=LogConfig(path="log.txt", level="INFO"),
            mode="auto",
        )
        svc = ConfigurationPresentationService(config)
        dto = svc.get_configuration()
        self.assertEqual(dto.mode, "auto")
        self.assertEqual(dto.stt["model"], "large-v3")

    def test_get_snapshot(self):
        from config import (
            Config, HolyricsConfig, STTConfig, LLMConfig, SearchConfig,
            StateConfig, CacheConfig, ConfidenceConfig, LogConfig, VadConfig,
        )
        config = Config(
            holyrics=HolyricsConfig(base_url="http://localhost", token="t", timeout_ms=5000),
            stt=STTConfig(model="large-v3", device="cpu", compute_type="int8",
                          language="pt", chunk_length_s=30,
                          vad=VadConfig(mode="webrtcvad", min_speech_ms=500,
                                        pause_threshold_ms=800)),
            llm=LLMConfig(base_url="http://localhost", model="llama3",
                          lazy_load=True, timeout_ms=5000, max_tokens=100),
            search=SearchConfig(fts5_db="db.sqlite", embeddings_path="emb.pt",
                                embedding_model="model", embedding_device="cpu",
                                rrf_k=60, top_k=50, search_gap=0.2),
            state=StateConfig(default_version="ACF", persist_path="state.json"),
            cache=CacheConfig(recent_capacity=100, embedding_capacity=50,
                              holyrics_ttl_s=300, current_verse_ttl_s=60),
            confidence=ConfidenceConfig(min_execute=0.85, min_confirm=0.7,
                                         stt_min=0.5, parser_high=0.85,
                                         parser_compact=0.75),
            log=LogConfig(path="log.txt", level="INFO"),
            mode="auto",
        )
        svc = ConfigurationPresentationService(config)
        snap = svc.get_snapshot()
        self.assertIsInstance(snap, ConfigurationSnapshot)


class TestHealthPresentationService(unittest.TestCase):

    def test_pipeline_health_active(self):
        state = PipelineState(running=True)
        svc = HealthPresentationService(pipeline_state=state)
        health = svc.pipeline_health()
        self.assertTrue(health.is_healthy)

    def test_pipeline_health_paused(self):
        state = PipelineState(running=True, paused=True)
        svc = HealthPresentationService(pipeline_state=state)
        health = svc.pipeline_health()
        self.assertTrue(health.is_degraded)

    def test_pipeline_health_stopped(self):
        state = PipelineState()
        svc = HealthPresentationService(pipeline_state=state)
        health = svc.pipeline_health()
        self.assertTrue(health.is_unhealthy)

    def test_pipeline_health_no_state(self):
        svc = HealthPresentationService()
        health = svc.pipeline_health()
        self.assertEqual(health.status, "unknown")

    def test_event_bus_health(self):
        bus = PipelineEventBus()
        svc = HealthPresentationService(bus=bus, store=bus.store)
        health = svc.event_bus_health()
        self.assertTrue(health.is_healthy)
        self.assertIn("event_count", health.details)

    def test_event_store_health(self):
        bus = PipelineEventBus()
        svc = HealthPresentationService(bus=bus, store=bus.store)
        health = svc.event_store_health()
        self.assertTrue(health.is_healthy)

    def test_all_components(self):
        state = PipelineState(running=True)
        bus = PipelineEventBus()
        svc = HealthPresentationService(pipeline_state=state, bus=bus, store=bus.store)
        components = svc.all_components()
        # Sprint 15.2: 12 components (backend, websocket, eventstream, pipeline,
        # microphone, speech_recognition, searcher, holyrics, event_bus, event_store, ranking, intelligence).
        self.assertEqual(len(components), 12)

    def test_get_snapshot(self):
        state = PipelineState(running=True)
        svc = HealthPresentationService(pipeline_state=state)
        snap = svc.get_snapshot()
        self.assertIsInstance(snap, HealthSnapshot)
        self.assertEqual(snap.component_count, 12)

    def test_component_by_name(self):
        state = PipelineState(running=True)
        svc = HealthPresentationService(pipeline_state=state)
        c = svc.component("pipeline")
        self.assertIsNotNone(c)
        self.assertEqual(c.component, "pipeline")
        self.assertIsNone(svc.component("nonexistent"))


class TestDiagnosticPresentationService(unittest.TestCase):

    def test_microphone_diagnostic(self):
        svc = DiagnosticPresentationService()
        d = svc.microphone_diagnostic()
        self.assertEqual(d.component, "microphone")
        self.assertEqual(d.category, "hardware")

    def test_gpu_diagnostic(self):
        svc = DiagnosticPresentationService()
        d = svc.gpu_diagnostic()
        self.assertEqual(d.component, "gpu")

    def test_pipeline_diagnostic(self):
        state = PipelineState(running=True)
        svc = DiagnosticPresentationService(pipeline_state=state)
        d = svc.pipeline_diagnostic()
        self.assertTrue(d.available)
        self.assertTrue(d.info["running"])

    def test_pipeline_diagnostic_no_state(self):
        svc = DiagnosticPresentationService()
        d = svc.pipeline_diagnostic()
        self.assertFalse(d.available)
        self.assertTrue(d.has_errors)

    def test_event_store_diagnostic(self):
        bus = PipelineEventBus()
        svc = DiagnosticPresentationService(bus=bus, store=bus.store)
        d = svc.event_store_diagnostic()
        self.assertTrue(d.available)

    def test_event_bus_diagnostic(self):
        bus = PipelineEventBus()
        svc = DiagnosticPresentationService(bus=bus, store=bus.store)
        d = svc.event_bus_diagnostic()
        self.assertTrue(d.available)

    def test_all_diagnostics(self):
        svc = DiagnosticPresentationService()
        diags = svc.all_diagnostics()
        self.assertEqual(len(diags), 7)

    def test_component_by_name(self):
        svc = DiagnosticPresentationService()
        d = svc.component("microphone")
        self.assertIsNotNone(d)
        self.assertIsNone(svc.component("nonexistent"))


class TestEventPresentationService(unittest.TestCase):

    def test_get_all_events(self):
        bus = PipelineEventBus()
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta, text="a"))
        bus.publish(SearchRequested(meta=meta))
        svc = EventPresentationService(bus)
        events = svc.get_all_events()
        self.assertEqual(len(events), 2)

    def test_get_event_count(self):
        bus = PipelineEventBus()
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta))
        svc = EventPresentationService(bus)
        self.assertEqual(svc.get_event_count(), 1)

    def test_get_last_event(self):
        bus = PipelineEventBus()
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta, text="hello"))
        svc = EventPresentationService(bus)
        last = svc.get_last_event()
        self.assertIsNotNone(last)
        self.assertEqual(last.event_type, "SpeechRecognized")

    def test_get_last_event_none(self):
        bus = PipelineEventBus()
        svc = EventPresentationService(bus)
        self.assertIsNone(svc.get_last_event())

    def test_get_events_by_correlation(self):
        bus = PipelineEventBus()
        meta1 = _make_meta(correlation_id="c1", event_id="e1")
        meta2 = _make_meta(correlation_id="c2", event_id="e2")
        bus.publish(SpeechRecognized(meta=meta1, text="a"))
        bus.publish(SpeechRecognized(meta=meta2, text="b"))
        svc = EventPresentationService(bus)
        c1_events = svc.get_events_by_correlation("c1")
        self.assertEqual(len(c1_events), 1)
        self.assertEqual(c1_events[0].payload["text"], "a")

    def test_get_events_by_session(self):
        bus = PipelineEventBus()
        meta1 = _make_meta(session_id="s1", event_id="e1")
        meta2 = _make_meta(session_id="s2", event_id="e2")
        bus.publish(SpeechRecognized(meta=meta1, text="a"))
        bus.publish(SpeechRecognized(meta=meta2, text="b"))
        svc = EventPresentationService(bus)
        s1_events = svc.get_events_by_session("s1")
        self.assertEqual(len(s1_events), 1)

    def test_get_events_by_type(self):
        bus = PipelineEventBus()
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta, text="a"))
        bus.publish(SearchRequested(meta=meta))
        svc = EventPresentationService(bus)
        recognized = svc.get_events_by_type(SpeechRecognized)
        self.assertEqual(len(recognized), 1)

    def test_get_events_between(self):
        bus = PipelineEventBus()
        meta1 = _make_meta(timestamp=100.0, event_id="e1")
        meta2 = _make_meta(timestamp=200.0, event_id="e2")
        meta3 = _make_meta(timestamp=300.0, event_id="e3")
        bus.publish(SpeechRecognized(meta=meta1, text="a"))
        bus.publish(SpeechRecognized(meta=meta2, text="b"))
        bus.publish(SpeechRecognized(meta=meta3, text="c"))
        svc = EventPresentationService(bus)
        events = svc.get_events_between(150.0, 250.0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["text"], "b")

    def test_get_snapshot(self):
        bus = PipelineEventBus()
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta, text="a"))
        svc = EventPresentationService(bus)
        snap = svc.get_snapshot()
        self.assertIsInstance(snap, EventSnapshot)
        self.assertEqual(snap.event_count, 1)

    def test_get_snapshot_with_correlation(self):
        bus = PipelineEventBus()
        meta1 = _make_meta(correlation_id="c1", event_id="e1")
        meta2 = _make_meta(correlation_id="c2", event_id="e2")
        bus.publish(SpeechRecognized(meta=meta1, text="a"))
        bus.publish(SpeechRecognized(meta=meta2, text="b"))
        svc = EventPresentationService(bus)
        snap = svc.get_snapshot(correlation_id="c1")
        self.assertEqual(snap.event_count, 1)
        self.assertEqual(snap.correlation_id, "c1")

    def test_get_logs(self):
        bus = PipelineEventBus()
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta, text="a"))
        svc = EventPresentationService(bus)
        logs = svc.get_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].component, "test")
        self.assertEqual(logs[0].message, "SpeechRecognized")


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class TestAdapters(unittest.TestCase):

    def test_rest_adapter_is_abstract(self):
        with self.assertRaises(TypeError):
            RestAdapter()  # type: ignore

    def test_websocket_adapter_is_abstract(self):
        with self.assertRaises(TypeError):
            WebSocketAdapter()  # type: ignore

    def test_cli_adapter_is_abstract(self):
        with self.assertRaises(TypeError):
            CliAdapter()  # type: ignore

    def test_dashboard_adapter_is_abstract(self):
        with self.assertRaises(TypeError):
            DashboardAdapter()  # type: ignore

    def test_replay_adapter_is_abstract(self):
        with self.assertRaises(TypeError):
            ReplayAdapter()  # type: ignore

    def test_rest_adapter_has_methods(self):
        methods = [
            "get_pipeline_status", "get_session", "get_metrics",
            "get_configuration", "get_health", "get_events",
            "get_diagnostics",
        ]
        for m in methods:
            self.assertTrue(hasattr(RestAdapter, m))

    def test_websocket_adapter_has_methods(self):
        methods = [
            "serialize_snapshot", "serialize_event",
            "serialize_metrics", "serialize_health",
        ]
        for m in methods:
            self.assertTrue(hasattr(WebSocketAdapter, m))

    def test_cli_adapter_has_methods(self):
        methods = [
            "format_status", "format_metrics", "format_session",
            "format_events", "format_health", "format_configuration",
        ]
        for m in methods:
            self.assertTrue(hasattr(CliAdapter, m))

    def test_dashboard_adapter_has_methods(self):
        methods = [
            "get_dashboard_data", "get_session_history",
            "get_correlation_flow",
        ]
        for m in methods:
            self.assertTrue(hasattr(DashboardAdapter, m))

    def test_replay_adapter_has_methods(self):
        methods = [
            "get_replay_events", "get_replay_sessions",
            "get_replay_correlations",
        ]
        for m in methods:
            self.assertTrue(hasattr(ReplayAdapter, m))

    def test_base_adapter_properties(self):
        """BaseAdapter deve ter properties para todos os services."""
        # Criar uma subclasse concreta para testar
        class ConcreteAdapter(BaseAdapter):
            pass
        adapter = ConcreteAdapter()
        self.assertIsNone(adapter.pipeline_service)
        self.assertIsNone(adapter.session_service)


# ---------------------------------------------------------------------------
# Integração completa
# ---------------------------------------------------------------------------


class TestFullIntegration(unittest.TestCase):
    """Teste de integração completa: Pipeline + Observers + Services."""

    def test_full_integration(self):
        # 1. Setup pipeline
        bus = PipelineEventBus()
        state = PipelineState(running=True)
        session = PipelineSession.create(session_id="s1", started_at=100.0)
        metrics = PipelineMetrics()

        # 2. Register observers
        event_obs = EventObserver()
        pipe_obs = PipelineObserver()
        metrics_obs = MetricsObserver()
        session_obs = SessionObserver()
        for obs in [event_obs, pipe_obs, metrics_obs, session_obs]:
            obs.subscribe_to(bus)

        # 3. Publish events
        meta1 = _make_meta(correlation_id="c1", event_id="e1")
        bus.publish(SpeechSegmentReceived(meta=meta1, duration_ms=1000))
        meta2 = _make_meta(correlation_id="c1", event_id="e2", causation_id="e1")
        bus.publish(SpeechRecognized(meta=meta2, text="joao 3 16", confidence=0.9))

        # 4. Services
        pipe_svc = PipelinePresentationService(state, session, metrics, bus)
        event_svc = EventPresentationService(bus)
        health_svc = HealthPresentationService(state, bus, bus.store)

        # 5. Verify
        self.assertEqual(event_obs.event_count, 2)
        self.assertEqual(metrics_obs.total_events, 2)
        self.assertEqual(session_obs.session_count, 1)

        snap = pipe_svc.get_snapshot()
        self.assertTrue(snap.status.running)

        events = event_svc.get_all_events()
        self.assertEqual(len(events), 2)

        c1_events = event_svc.get_events_by_correlation("c1")
        self.assertEqual(len(c1_events), 2)

        health = health_svc.get_snapshot()
        self.assertEqual(health.component_count, 12)


# ---------------------------------------------------------------------------
# Compatibilidade
# ---------------------------------------------------------------------------


class TestCompatibility(unittest.TestCase):
    """Testes de compatibilidade — Core funciona sem Presentation Layer."""

    def test_pipeline_works_without_presentation(self):
        """Pipeline funciona sem a Presentation Layer."""
        bus = PipelineEventBus()
        meta = _make_meta()
        bus.publish(SpeechRecognized(meta=meta, text="hello"))
        self.assertEqual(bus.event_count(), 1)

    def test_intelligence_works_without_presentation(self):
        """Intelligence funciona sem a Presentation Layer."""
        from intelligence import SermonIntelligenceEngine
        engine = SermonIntelligenceEngine()
        self.assertIsNotNone(engine)

    def test_presentation_does_not_modify_core(self):
        """Presentation Layer não modifica objetos do Core."""
        bus = PipelineEventBus()
        meta = _make_meta()
        ev = SpeechRecognized(meta=meta, text="hello")
        bus.publish(ev)
        svc = EventPresentationService(bus)
        events = svc.get_all_events()
        # O evento original não deve ser modificado
        self.assertEqual(ev.text, "hello")
        self.assertEqual(events[0].payload["text"], "hello")


if __name__ == "__main__":
    unittest.main()
