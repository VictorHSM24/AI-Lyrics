"""Testes do Pipeline — EventMetadata, Eventos, Policy, State, Session, Metrics.

Cobre:
  - EventMetadata (imutabilidade, hashability, factories, cadeia causal).
  - Eventos (todos os 15 eventos, imutabilidade, to_dict, event_type).
  - PipelinePolicy (parâmetros, validações, properties).
  - PipelineState (imutabilidade, with_*, properties, reset).
  - PipelineSession (imutabilidade, with_*, properties, to_dict).
  - PipelineMetrics (contadores, latência, throughput, properties).
"""

from __future__ import annotations

import unittest

import sys
sys.path.insert(0, ".")

from pipeline import (
    EventMetadata,
    EvaluationRecorded,
    FeedbackRecorded,
    IntelligenceCompleted,
    PipelineError,
    PipelineMetrics,
    PipelinePaused,
    PipelinePolicy,
    PipelineResumed,
    PipelineSession,
    PipelineStarted,
    PipelineState,
    PipelineStopped,
    PresentationCompleted,
    PresentationRequested,
    RankingCompleted,
    SearchCompleted,
    SearchRequested,
    SpeechRecognized,
    SpeechSegmentReceived,
)
from pipeline.events import (
    PipelineEvent,
    all_event_types,
    all_event_type_names,
    is_pipeline_event,
)


# ---------------------------------------------------------------------------
# EventMetadata
# ---------------------------------------------------------------------------


class TestEventMetadata(unittest.TestCase):
    """Testes do EventMetadata."""

    def test_metadata_is_frozen(self):
        meta = EventMetadata(
            event_id="e1", correlation_id="c1", causation_id=None,
            session_id="s1", timestamp=0.0, origin="test",
        )
        with self.assertRaises(Exception):
            meta.event_id = "e2"  # type: ignore

    def test_metadata_is_hashable(self):
        meta = EventMetadata(
            event_id="e1", correlation_id="c1", causation_id=None,
            session_id="s1", timestamp=0.0, origin="test",
        )
        self.assertIsInstance(hash(meta), int)

    def test_metadata_is_initial(self):
        meta = EventMetadata(
            event_id="e1", correlation_id="c1", causation_id=None,
            session_id="s1", timestamp=0.0, origin="test",
        )
        self.assertTrue(meta.is_initial)

    def test_metadata_is_not_initial(self):
        meta = EventMetadata(
            event_id="e2", correlation_id="c1", causation_id="e1",
            session_id="s1", timestamp=0.0, origin="test",
        )
        self.assertFalse(meta.is_initial)

    def test_metadata_has_metadata(self):
        meta = EventMetadata(
            event_id="e1", correlation_id="c1", causation_id=None,
            session_id="s1", timestamp=0.0, origin="test",
            metadata=(("k", "v"),),
        )
        self.assertTrue(meta.has_metadata)

    def test_metadata_no_metadata(self):
        meta = EventMetadata(
            event_id="e1", correlation_id="c1", causation_id=None,
            session_id="s1", timestamp=0.0, origin="test",
        )
        self.assertFalse(meta.has_metadata)

    def test_metadata_to_dict_keys(self):
        meta = EventMetadata(
            event_id="e1", correlation_id="c1", causation_id=None,
            session_id="s1", timestamp=0.0, origin="test",
            metadata=(("k", "v"),),
        )
        d = meta.to_dict()
        expected = {
            "event_id", "correlation_id", "causation_id", "session_id",
            "timestamp", "origin", "metadata",
        }
        self.assertEqual(set(d.keys()), expected)

    def test_metadata_to_dict_metadata_is_list(self):
        meta = EventMetadata(
            event_id="e1", correlation_id="c1", causation_id=None,
            session_id="s1", timestamp=0.0, origin="test",
            metadata=(("k", "v"),),
        )
        d = meta.to_dict()
        self.assertIsInstance(d["metadata"], list)

    def test_for_initial_generates_ids(self):
        meta = EventMetadata.for_initial(
            session_id="s1", origin="test",
        )
        self.assertTrue(meta.event_id)
        self.assertTrue(meta.correlation_id)
        self.assertIsNone(meta.causation_id)
        self.assertEqual(meta.session_id, "s1")
        self.assertEqual(meta.origin, "test")

    def test_for_initial_with_explicit_ids(self):
        meta = EventMetadata.for_initial(
            session_id="s1", origin="test",
            correlation_id="my-corr", event_id="my-eid",
            timestamp=123.0,
        )
        self.assertEqual(meta.event_id, "my-eid")
        self.assertEqual(meta.correlation_id, "my-corr")
        self.assertEqual(meta.timestamp, 123.0)

    def test_for_next_preserves_correlation(self):
        prev = EventMetadata.for_initial(
            session_id="s1", origin="test",
            correlation_id="c1", event_id="e1",
        )
        nxt = EventMetadata.for_next(previous=prev, origin="handler2")
        self.assertEqual(nxt.correlation_id, "c1")
        self.assertEqual(nxt.causation_id, "e1")
        self.assertEqual(nxt.session_id, "s1")
        self.assertEqual(nxt.origin, "handler2")
        self.assertNotEqual(nxt.event_id, "e1")

    def test_for_next_with_explicit_event_id(self):
        prev = EventMetadata.for_initial(
            session_id="s1", origin="test",
            correlation_id="c1", event_id="e1",
        )
        nxt = EventMetadata.for_next(
            previous=prev, origin="h2", event_id="e2")
        self.assertEqual(nxt.event_id, "e2")

    def test_for_session_event(self):
        meta = EventMetadata.for_session_event(
            session_id="s1", origin="engine",
            correlation_id="lc1", event_id="le1",
        )
        self.assertEqual(meta.correlation_id, "lc1")
        self.assertIsNone(meta.causation_id)

    def test_custom_generators(self):
        calls = []
        def gen():
            calls.append(1)
            return f"custom-{len(calls)}"
        meta = EventMetadata.for_initial(
            session_id="s1", origin="test",
            event_id_generator=gen, correlation_id_generator=gen,
        )
        self.assertTrue(meta.event_id.startswith("custom-"))
        self.assertTrue(meta.correlation_id.startswith("custom-"))


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------


class TestPipelineEvents(unittest.TestCase):
    """Testes dos eventos tipados."""

    def _make_meta(self):
        return EventMetadata.for_initial(
            session_id="s1", origin="test",
            correlation_id="c1", event_id="e1", timestamp=0.0,
        )

    def test_all_event_types_count(self):
        """Deve haver 15 tipos de evento."""
        types = all_event_types()
        self.assertEqual(len(types), 15)

    def test_all_event_type_names(self):
        names = all_event_type_names()
        self.assertEqual(len(names), 15)
        self.assertIn("SpeechSegmentReceived", names)
        self.assertIn("PipelineError", names)

    def test_is_pipeline_event(self):
        meta = self._make_meta()
        ev = SpeechSegmentReceived(meta=meta)
        self.assertTrue(is_pipeline_event(ev))
        self.assertFalse(is_pipeline_event("not an event"))

    def test_event_is_frozen(self):
        meta = self._make_meta()
        ev = SpeechSegmentReceived(meta=meta)
        with self.assertRaises(Exception):
            ev.text = "modified"  # type: ignore

    def test_event_is_hashable(self):
        meta = self._make_meta()
        ev = SpeechRecognized(meta=meta, text="hello")
        self.assertIsInstance(hash(ev), int)

    def test_event_properties(self):
        meta = self._make_meta()
        ev = SpeechRecognized(meta=meta, text="hello")
        self.assertEqual(ev.event_type, "SpeechRecognized")
        self.assertEqual(ev.event_id, "e1")
        self.assertEqual(ev.correlation_id, "c1")
        self.assertIsNone(ev.causation_id)
        self.assertEqual(ev.session_id, "s1")
        self.assertEqual(ev.origin, "test")

    def test_event_to_dict_has_meta(self):
        meta = self._make_meta()
        ev = SpeechRecognized(meta=meta, text="hello")
        d = ev.to_dict()
        self.assertIn("meta", d)
        self.assertIn("event_type", d)
        self.assertEqual(d["event_type"], "SpeechRecognized")
        self.assertEqual(d["text"], "hello")

    def test_speech_segment_received_fields(self):
        meta = self._make_meta()
        ev = SpeechSegmentReceived(
            meta=meta, audio=b"abc", start_time=1.0, end_time=2.0,
            duration_ms=1000, chunk_count=2)
        self.assertEqual(ev.audio, b"abc")
        self.assertEqual(ev.duration_ms, 1000)
        self.assertEqual(ev.chunk_count, 2)

    def test_speech_recognized_fields(self):
        meta = self._make_meta()
        ev = SpeechRecognized(
            meta=meta, text="hello", language="pt", confidence=0.9,
            processing_ms=100)
        self.assertEqual(ev.text, "hello")
        self.assertEqual(ev.confidence, 0.9)

    def test_search_requested_fields(self):
        meta = self._make_meta()
        ev = SearchRequested(
            meta=meta, query="fé", intent_action="search",
            intent_book="João", intent_chapter=3, intent_verse=16)
        self.assertEqual(ev.query, "fé")
        self.assertEqual(ev.intent_book, "João")

    def test_search_completed_fields(self):
        meta = self._make_meta()
        ev = SearchCompleted(
            meta=meta, query="fé", results=(), result_count=0, search_ms=50)
        self.assertEqual(ev.result_count, 0)

    def test_ranking_completed_fields(self):
        meta = self._make_meta()
        ev = RankingCompleted(
            meta=meta, query="fé", ranked_candidates=(), candidate_count=0)
        self.assertEqual(ev.candidate_count, 0)

    def test_intelligence_completed_fields(self):
        meta = self._make_meta()
        ev = IntelligenceCompleted(
            meta=meta, query="fé", recommendation=None,
            best_candidate_id="43:3:16", confidence_level="HIGH")
        self.assertEqual(ev.best_candidate_id, "43:3:16")

    def test_presentation_requested_fields(self):
        meta = self._make_meta()
        ev = PresentationRequested(
            meta=meta, candidate_id="43:3:16", book_id=43,
            chapter=3, verse=16, version="ACF")
        self.assertEqual(ev.book_id, 43)

    def test_presentation_completed_fields(self):
        meta = self._make_meta()
        ev = PresentationCompleted(
            meta=meta, candidate_id="43:3:16", status="ok",
            verse_id="43:3:16", presented=True)
        self.assertTrue(ev.presented)

    def test_feedback_recorded_fields(self):
        meta = self._make_meta()
        ev = FeedbackRecorded(
            meta=meta, candidate_id="43:3:16", feedback_type="accepted",
            scope="GLOBAL", query="fé")
        self.assertEqual(ev.feedback_type, "accepted")

    def test_evaluation_recorded_fields(self):
        meta = self._make_meta()
        ev = EvaluationRecorded(
            meta=meta, query="fé", classification="REFERENCE",
            candidate_id="43:3:16", duration_ms=200)
        self.assertEqual(ev.classification, "REFERENCE")

    def test_pipeline_started_fields(self):
        meta = self._make_meta()
        ev = PipelineStarted(meta=meta)
        self.assertEqual(ev.event_type, "PipelineStarted")

    def test_pipeline_stopped_fields(self):
        meta = self._make_meta()
        ev = PipelineStopped(meta=meta, reason="end")
        self.assertEqual(ev.reason, "end")

    def test_pipeline_paused_fields(self):
        meta = self._make_meta()
        ev = PipelinePaused(meta=meta, reason="wait")
        self.assertEqual(ev.reason, "wait")

    def test_pipeline_resumed_fields(self):
        meta = self._make_meta()
        ev = PipelineResumed(meta=meta, reason="go")
        self.assertEqual(ev.reason, "go")

    def test_pipeline_error_fields(self):
        meta = self._make_meta()
        ev = PipelineError(
            meta=meta, error_type="ValueError", error_message="bad",
            handler_name="SearchHandler", recoverable=True)
        self.assertEqual(ev.error_type, "ValueError")
        self.assertTrue(ev.recoverable)

    def test_all_events_inherit_pipeline_event(self):
        for cls in all_event_types():
            self.assertTrue(issubclass(cls, PipelineEvent))


# ---------------------------------------------------------------------------
# PipelinePolicy
# ---------------------------------------------------------------------------


class TestPipelinePolicy(unittest.TestCase):
    """Testes da PipelinePolicy."""

    def test_policy_is_frozen(self):
        p = PipelinePolicy()
        with self.assertRaises(Exception):
            p.search_timeout_ms = 999  # type: ignore

    def test_policy_defaults(self):
        p = PipelinePolicy()
        self.assertGreater(p.recognition_timeout_ms, 0)
        self.assertGreater(p.search_timeout_ms, 0)
        self.assertGreater(p.max_results_per_search, 0)

    def test_policy_total_timeout(self):
        p = PipelinePolicy()
        self.assertGreater(p.total_timeout_ms, 0)

    def test_policy_is_segment_valid(self):
        p = PipelinePolicy()
        self.assertTrue(p.is_segment_valid(1000))
        self.assertFalse(p.is_segment_valid(0))
        self.assertFalse(p.is_segment_valid(p.max_segment_duration_ms + 1))

    def test_policy_is_query_valid(self):
        p = PipelinePolicy()
        self.assertTrue(p.is_query_valid("fé"))
        self.assertFalse(p.is_query_valid(""))
        self.assertFalse(p.is_query_valid("x" * (p.max_query_length + 1)))

    def test_policy_should_continue_on_error(self):
        p = PipelinePolicy()
        self.assertTrue(p.should_continue_on_error(True))
        self.assertFalse(p.should_continue_on_error(False))
        p2 = PipelinePolicy(continue_on_error=False)
        self.assertFalse(p2.should_continue_on_error(True))

    def test_policy_retry_count_for(self):
        p = PipelinePolicy(max_retries_search=3)
        self.assertEqual(p.retry_count_for("search"), 3)
        self.assertEqual(p.retry_count_for("unknown"), 0)

    def test_policy_backpressure_prepared(self):
        p = PipelinePolicy()
        # Backpressure preparado mas desativado por padrão
        self.assertFalse(p.backpressure_enabled)
        self.assertGreater(p.backpressure_threshold, 0)


# ---------------------------------------------------------------------------
# PipelineState
# ---------------------------------------------------------------------------


class TestPipelineState(unittest.TestCase):
    """Testes do PipelineState."""

    def test_state_defaults(self):
        s = PipelineState()
        self.assertFalse(s.running)
        self.assertFalse(s.paused)
        self.assertIsNone(s.current_segment)
        self.assertEqual(s.last_query, "")
        self.assertFalse(s.is_active)
        self.assertTrue(s.is_idle)

    def test_state_is_frozen(self):
        s = PipelineState()
        with self.assertRaises(Exception):
            s.running = True  # type: ignore

    def test_state_with_running(self):
        s = PipelineState().with_running(True)
        self.assertTrue(s.running)
        self.assertTrue(s.is_active)

    def test_state_with_paused(self):
        s = PipelineState().with_running(True).with_paused(True)
        self.assertTrue(s.paused)
        self.assertFalse(s.is_active)

    def test_state_with_current_segment(self):
        s = PipelineState().with_running(True).with_current_segment("seg1")
        self.assertEqual(s.current_segment, "seg1")
        self.assertTrue(s.is_processing)

    def test_state_with_last_query(self):
        s = PipelineState().with_last_query("fé")
        self.assertEqual(s.last_query, "fé")
        self.assertTrue(s.has_last_query)

    def test_state_with_last_candidate(self):
        s = PipelineState().with_last_candidate("43:3:16")
        self.assertTrue(s.has_last_candidate)

    def test_state_with_last_event(self):
        s = PipelineState().with_last_event("SearchCompleted", 123.0)
        self.assertEqual(s.last_event_type, "SearchCompleted")
        self.assertEqual(s.last_event_timestamp, 123.0)

    def test_state_with_statistics(self):
        s = PipelineState().with_statistics({"count": 5})
        self.assertEqual(s.statistics["count"], 5)

    def test_state_with_incremented_stat(self):
        s = PipelineState().with_incremented_stat("count")
        s = s.with_incremented_stat("count")
        self.assertEqual(s.statistics["count"], 2)

    def test_state_reset(self):
        s = (PipelineState()
             .with_running(True)
             .with_last_query("test")
             .reset())
        self.assertFalse(s.running)
        self.assertEqual(s.last_query, "")

    def test_state_to_dict(self):
        s = PipelineState().with_running(True)
        d = s.to_dict()
        self.assertTrue(d["running"])
        self.assertTrue(d["is_active"])


# ---------------------------------------------------------------------------
# PipelineSession
# ---------------------------------------------------------------------------


class TestPipelineSession(unittest.TestCase):
    """Testes da PipelineSession."""

    def test_session_create(self):
        s = PipelineSession.create(session_id="s1", started_at=100.0)
        self.assertEqual(s.session_id, "s1")
        self.assertEqual(s.started_at, 100.0)
        self.assertTrue(s.is_active)
        self.assertFalse(s.is_ended)

    def test_session_is_frozen(self):
        s = PipelineSession.create(session_id="s1")
        with self.assertRaises(Exception):
            s.processed_segments = 5  # type: ignore

    def test_session_with_segment_processed(self):
        s = PipelineSession.create(session_id="s1")
        s2 = s.with_segment_processed("corr1")
        self.assertEqual(s2.processed_segments, 1)
        self.assertIn("corr1", s2.correlation_ids)

    def test_session_with_segment_dedup_correlation(self):
        s = PipelineSession.create(session_id="s1")
        s2 = s.with_segment_processed("corr1")
        s3 = s2.with_segment_processed("corr1")
        self.assertEqual(s3.processed_segments, 2)
        self.assertEqual(len(s3.correlation_ids), 1)

    def test_session_with_query_processed(self):
        s = PipelineSession.create(session_id="s1")
        s2 = s.with_query_processed()
        self.assertEqual(s2.processed_queries, 1)

    def test_session_with_presentation(self):
        s = PipelineSession.create(session_id="s1")
        s2 = s.with_presentation()
        self.assertEqual(s2.presentations, 1)

    def test_session_with_error(self):
        s = PipelineSession.create(session_id="s1")
        s2 = s.with_error()
        self.assertEqual(s2.errors, 1)

    def test_session_with_ended(self):
        s = PipelineSession.create(session_id="s1", started_at=100.0)
        s2 = s.with_ended(200.0)
        self.assertTrue(s2.is_ended)
        self.assertEqual(s2.ended_at, 200.0)
        self.assertAlmostEqual(s2.duration_s, 100.0)

    def test_session_has_correlation(self):
        s = PipelineSession.create(session_id="s1")
        s2 = s.with_segment_processed("corr1")
        self.assertTrue(s2.has_correlation("corr1"))
        self.assertFalse(s2.has_correlation("corr2"))

    def test_session_unique_correlations(self):
        s = PipelineSession.create(session_id="s1")
        s = s.with_segment_processed("c1").with_segment_processed("c2")
        self.assertEqual(s.unique_correlations, 2)

    def test_session_error_rate(self):
        s = PipelineSession.create(session_id="s1")
        s = s.with_segment_processed("c1").with_error()
        self.assertEqual(s.error_rate, 1.0)

    def test_session_presentation_rate(self):
        s = PipelineSession.create(session_id="s1")
        s = s.with_query_processed().with_presentation()
        self.assertEqual(s.presentation_rate, 1.0)

    def test_session_to_dict(self):
        s = PipelineSession.create(session_id="s1", started_at=100.0)
        d = s.to_dict()
        self.assertEqual(d["session_id"], "s1")
        self.assertTrue(d["is_active"])
        self.assertEqual(d["processed_segments"], 0)


# ---------------------------------------------------------------------------
# PipelineMetrics
# ---------------------------------------------------------------------------


class TestPipelineMetrics(unittest.TestCase):
    """Testes da PipelineMetrics."""

    def test_metrics_defaults(self):
        m = PipelineMetrics()
        self.assertEqual(m.segments_received, 0)
        self.assertEqual(m.queries_processed, 0)

    def test_metrics_record_segment_received(self):
        m = PipelineMetrics()
        m.record_segment_received()
        self.assertEqual(m.segments_received, 1)

    def test_metrics_record_segment_processed(self):
        m = PipelineMetrics()
        m.record_segment_processed(latency_ms=100.0)
        self.assertEqual(m.segments_processed, 1)
        self.assertEqual(m.total_latency_ms, 100.0)

    def test_metrics_record_segment_dropped(self):
        m = PipelineMetrics()
        m.record_segment_dropped()
        self.assertEqual(m.segments_dropped, 1)

    def test_metrics_record_query_processed(self):
        m = PipelineMetrics()
        m.record_query_processed()
        self.assertEqual(m.queries_processed, 1)

    def test_metrics_record_presentation(self):
        m = PipelineMetrics()
        m.record_presentation(success=True)
        m.record_presentation(success=False)
        self.assertEqual(m.presentations_executed, 1)
        self.assertEqual(m.presentations_failed, 1)

    def test_metrics_record_error(self):
        m = PipelineMetrics()
        m.record_error(recoverable=True)
        m.record_error(recoverable=False)
        self.assertEqual(m.errors_total, 2)
        self.assertEqual(m.errors_recoverable, 1)
        self.assertEqual(m.errors_fatal, 1)

    def test_metrics_avg_latency(self):
        m = PipelineMetrics()
        m.record_segment_processed(latency_ms=100.0)
        m.record_segment_processed(latency_ms=200.0)
        self.assertAlmostEqual(m.avg_latency_ms, 150.0)

    def test_metrics_avg_latency_no_segments(self):
        m = PipelineMetrics()
        self.assertEqual(m.avg_latency_ms, 0.0)

    def test_metrics_throughput(self):
        m = PipelineMetrics()
        m.started_at = 0.0
        m.last_event_at = 60.0
        m.record_segment_processed()
        self.assertGreater(m.throughput_segments_per_min, 0)

    def test_metrics_error_rate(self):
        m = PipelineMetrics()
        m.record_segment_received()
        m.record_segment_received()
        m.record_error()
        self.assertEqual(m.error_rate, 0.5)

    def test_metrics_drop_rate(self):
        m = PipelineMetrics()
        m.record_segment_received()
        m.record_segment_received()
        m.record_segment_dropped()
        self.assertEqual(m.drop_rate, 0.5)

    def test_metrics_presentation_success_rate(self):
        m = PipelineMetrics()
        m.record_presentation(success=True)
        m.record_presentation(success=False)
        self.assertEqual(m.presentation_success_rate, 0.5)

    def test_metrics_processing_success_rate(self):
        m = PipelineMetrics()
        m.record_segment_received()
        m.record_segment_processed()
        self.assertEqual(m.processing_success_rate, 1.0)

    def test_metrics_reset(self):
        m = PipelineMetrics()
        m.record_segment_received()
        m.record_error()
        m.reset()
        self.assertEqual(m.segments_received, 0)
        self.assertEqual(m.errors_total, 0)

    def test_metrics_to_dict(self):
        m = PipelineMetrics()
        m.record_segment_received()
        d = m.to_dict()
        self.assertEqual(d["segments_received"], 1)
        self.assertIn("avg_latency_ms", d)
        self.assertIn("throughput_segments_per_min", d)

    def test_metrics_latencies_by_stage(self):
        m = PipelineMetrics()
        m.record_recognition_latency(10.0)
        m.record_search_latency(20.0)
        m.record_ranking_latency(5.0)
        m.record_intelligence_latency(15.0)
        m.record_presentation_latency(30.0)
        m.record_feedback_latency(5.0)
        m.record_evaluation_latency(5.0)
        m.record_segment_processed()
        m.record_query_processed()
        self.assertAlmostEqual(m.avg_recognition_latency_ms, 10.0)
        self.assertAlmostEqual(m.avg_search_latency_ms, 20.0)


if __name__ == "__main__":
    unittest.main()
