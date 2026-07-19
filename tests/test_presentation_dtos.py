"""Testes dos DTOs da Presentation Layer.

Cobre:
  - Todos os DTOs de apresentação (dtos.py).
  - Todos os DTOs de domínio (dtos_domain.py).
  - Imutabilidade (frozen).
  - Serialização (to_dict).
  - Properties.
  - Valores padrão.
"""

from __future__ import annotations

import unittest

import sys
sys.path.insert(0, ".")

from presentation import (
    CandidateDTO,
    ConfigurationDTO,
    DiagnosticDTO,
    EventDTO,
    EventMetadataDTO,
    EvidenceDTO,
    HealthDTO,
    LogDTO,
    MetricsDTO,
    PipelineStatusDTO,
    PresentationDTO,
    RecommendationDTO,
    ScoreDTO,
    SessionDTO,
    SignalDTO,
)


# ---------------------------------------------------------------------------
# EventMetadataDTO
# ---------------------------------------------------------------------------


class TestEventMetadataDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = EventMetadataDTO(
            event_id="e1", correlation_id="c1", causation_id=None,
            session_id="s1", timestamp=0.0, origin="test")
        with self.assertRaises(Exception):
            dto.event_id = "e2"  # type: ignore

    def test_is_initial(self):
        dto = EventMetadataDTO(
            event_id="e1", correlation_id="c1", causation_id=None,
            session_id="s1", timestamp=0.0, origin="test")
        self.assertTrue(dto.is_initial)

    def test_is_not_initial(self):
        dto = EventMetadataDTO(
            event_id="e2", correlation_id="c1", causation_id="e1",
            session_id="s1", timestamp=0.0, origin="test")
        self.assertFalse(dto.is_initial)

    def test_to_dict(self):
        dto = EventMetadataDTO(
            event_id="e1", correlation_id="c1", causation_id=None,
            session_id="s1", timestamp=100.0, origin="test",
            metadata=(("k", "v"),))
        d = dto.to_dict()
        self.assertEqual(d["event_id"], "e1")
        self.assertEqual(d["correlation_id"], "c1")
        self.assertIsNone(d["causation_id"])
        self.assertEqual(d["metadata"], [("k", "v")])

    def test_defaults(self):
        dto = EventMetadataDTO(
            event_id="e1", correlation_id="c1", causation_id=None,
            session_id="s1", timestamp=0.0, origin="test")
        self.assertEqual(dto.metadata, ())


# ---------------------------------------------------------------------------
# EventDTO
# ---------------------------------------------------------------------------


class TestEventDTO(unittest.TestCase):

    def _make_meta(self):
        return EventMetadataDTO(
            event_id="e1", correlation_id="c1", causation_id=None,
            session_id="s1", timestamp=100.0, origin="test")

    def test_is_frozen(self):
        dto = EventDTO(event_type="Test", meta=self._make_meta())
        with self.assertRaises(Exception):
            dto.event_type = "Modified"  # type: ignore

    def test_properties(self):
        dto = EventDTO(event_type="Test", meta=self._make_meta())
        self.assertEqual(dto.event_id, "e1")
        self.assertEqual(dto.correlation_id, "c1")
        self.assertIsNone(dto.causation_id)
        self.assertEqual(dto.session_id, "s1")
        self.assertEqual(dto.timestamp, 100.0)
        self.assertEqual(dto.origin, "test")

    def test_to_dict(self):
        dto = EventDTO(
            event_type="SpeechRecognized",
            meta=self._make_meta(),
            payload={"text": "hello"})
        d = dto.to_dict()
        self.assertEqual(d["event_type"], "SpeechRecognized")
        self.assertIn("meta", d)
        self.assertEqual(d["payload"], {"text": "hello"})

    def test_defaults(self):
        dto = EventDTO(event_type="Test", meta=self._make_meta())
        self.assertEqual(dto.payload, {})


# ---------------------------------------------------------------------------
# PipelineStatusDTO
# ---------------------------------------------------------------------------


class TestPipelineStatusDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = PipelineStatusDTO(
            running=True, paused=False, is_active=True,
            is_idle=False, is_processing=False, current_segment=None,
            last_query="", last_candidate_id="",
            last_event_type="", last_event_timestamp=0.0)
        with self.assertRaises(Exception):
            dto.running = False  # type: ignore

    def test_to_dict(self):
        dto = PipelineStatusDTO(
            running=True, paused=False, is_active=True,
            is_idle=False, is_processing=False, current_segment=None,
            last_query="fé", last_candidate_id="43:3:16",
            last_event_type="SearchCompleted", last_event_timestamp=100.0,
            statistics={"count": 5})
        d = dto.to_dict()
        self.assertTrue(d["running"])
        self.assertEqual(d["last_query"], "fé")
        self.assertEqual(d["statistics"], {"count": 5})


# ---------------------------------------------------------------------------
# SessionDTO
# ---------------------------------------------------------------------------


class TestSessionDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = SessionDTO(
            session_id="s1", started_at=100.0, ended_at=0.0,
            is_active=True, is_ended=False, duration_s=50.0,
            processed_segments=5, processed_queries=3, presentations=2,
            errors=1, error_rate=0.2, presentation_rate=0.67,
            segments_per_minute=6.0, queries_per_minute=3.6,
            unique_correlations=5)
        with self.assertRaises(Exception):
            dto.session_id = "s2"  # type: ignore

    def test_to_dict(self):
        dto = SessionDTO(
            session_id="s1", started_at=100.0, ended_at=0.0,
            is_active=True, is_ended=False, duration_s=50.0,
            processed_segments=5, processed_queries=3, presentations=2,
            errors=1, error_rate=0.2, presentation_rate=0.67,
            segments_per_minute=6.0, queries_per_minute=3.6,
            unique_correlations=5, correlation_ids=("c1", "c2"))
        d = dto.to_dict()
        self.assertEqual(d["session_id"], "s1")
        self.assertEqual(d["correlation_ids"], ["c1", "c2"])
        self.assertTrue(d["is_active"])


# ---------------------------------------------------------------------------
# MetricsDTO
# ---------------------------------------------------------------------------


class TestMetricsDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = MetricsDTO(
            segments_received=10, segments_processed=8, segments_dropped=2,
            queries_processed=7, presentations_executed=5,
            presentations_failed=1, errors_total=3,
            errors_recoverable=2, errors_fatal=1,
            total_latency_ms=800.0, avg_latency_ms=100.0,
            avg_recognition_latency_ms=10.0, avg_search_latency_ms=20.0,
            avg_ranking_latency_ms=5.0, avg_intelligence_latency_ms=15.0,
            avg_presentation_latency_ms=30.0,
            throughput_segments_per_min=12.0, throughput_queries_per_min=8.0,
            error_rate=0.3, drop_rate=0.2,
            presentation_success_rate=0.83,
            processing_success_rate=0.8, duration_s=60.0,
            correlation_count=10)
        with self.assertRaises(Exception):
            dto.segments_received = 999  # type: ignore

    def test_to_dict(self):
        dto = MetricsDTO(
            segments_received=10, segments_processed=8, segments_dropped=2,
            queries_processed=7, presentations_executed=5,
            presentations_failed=1, errors_total=3,
            errors_recoverable=2, errors_fatal=1,
            total_latency_ms=800.0, avg_latency_ms=100.0,
            avg_recognition_latency_ms=10.0, avg_search_latency_ms=20.0,
            avg_ranking_latency_ms=5.0, avg_intelligence_latency_ms=15.0,
            avg_presentation_latency_ms=30.0,
            throughput_segments_per_min=12.0, throughput_queries_per_min=8.0,
            error_rate=0.3, drop_rate=0.2,
            presentation_success_rate=0.83,
            processing_success_rate=0.8, duration_s=60.0,
            correlation_count=10)
        d = dto.to_dict()
        self.assertEqual(d["segments_received"], 10)
        self.assertEqual(d["error_rate"], 0.3)


# ---------------------------------------------------------------------------
# ConfigurationDTO
# ---------------------------------------------------------------------------


class TestConfigurationDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = ConfigurationDTO(
            mode="auto", holyrics={}, stt={}, llm={}, search={},
            state={}, cache={}, confidence={}, log={})
        with self.assertRaises(Exception):
            dto.mode = "manual"  # type: ignore

    def test_to_dict(self):
        dto = ConfigurationDTO(
            mode="auto", holyrics={"base_url": "http://localhost"},
            stt={"model": "large-v3"}, llm={"model": "llama3"},
            search={"top_k": 50}, state={"default_version": "ACF"},
            cache={"recent_capacity": 100}, confidence={"min_execute": 0.85},
            log={"level": "INFO"}, audio={"sample_rate": 16000},
            pipeline_policy={"recognition_timeout_ms": 5000})
        d = dto.to_dict()
        self.assertEqual(d["mode"], "auto")
        self.assertEqual(d["holyrics"]["base_url"], "http://localhost")
        self.assertIsNotNone(d["audio"])
        self.assertIsNotNone(d["pipeline_policy"])

    def test_optional_fields_none(self):
        dto = ConfigurationDTO(
            mode="auto", holyrics={}, stt={}, llm={}, search={},
            state={}, cache={}, confidence={}, log={})
        d = dto.to_dict()
        self.assertIsNone(d["audio"])
        self.assertIsNone(d["pipeline_policy"])


# ---------------------------------------------------------------------------
# HealthDTO
# ---------------------------------------------------------------------------


class TestHealthDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = HealthDTO(component="pipeline", status="healthy")
        with self.assertRaises(Exception):
            dto.status = "unhealthy"  # type: ignore

    def test_is_healthy(self):
        dto = HealthDTO(component="pipeline", status="healthy")
        self.assertTrue(dto.is_healthy)
        self.assertFalse(dto.is_degraded)
        self.assertFalse(dto.is_unhealthy)

    def test_is_degraded(self):
        dto = HealthDTO(component="pipeline", status="degraded")
        self.assertTrue(dto.is_degraded)

    def test_is_unhealthy(self):
        dto = HealthDTO(component="pipeline", status="unhealthy")
        self.assertTrue(dto.is_unhealthy)

    def test_to_dict(self):
        dto = HealthDTO(
            component="pipeline", status="healthy",
            message="OK", details={"uptime": 100})
        d = dto.to_dict()
        self.assertEqual(d["component"], "pipeline")
        self.assertEqual(d["status"], "healthy")
        self.assertTrue(d["is_healthy"])


# ---------------------------------------------------------------------------
# DiagnosticDTO
# ---------------------------------------------------------------------------


class TestDiagnosticDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = DiagnosticDTO(
            component="microphone", category="hardware", available=True)
        with self.assertRaises(Exception):
            dto.available = False  # type: ignore

    def test_has_warnings(self):
        dto = DiagnosticDTO(
            component="mic", category="hardware", available=True,
            warnings=("low_volume",))
        self.assertTrue(dto.has_warnings)
        self.assertFalse(dto.has_errors)

    def test_has_errors(self):
        dto = DiagnosticDTO(
            component="mic", category="hardware", available=False,
            errors=("not_found",))
        self.assertTrue(dto.has_errors)

    def test_to_dict(self):
        dto = DiagnosticDTO(
            component="gpu", category="hardware", available=True,
            info={"name": "RTX 4090"}, warnings=("high_temp",),
            errors=())
        d = dto.to_dict()
        self.assertEqual(d["component"], "gpu")
        self.assertTrue(d["available"])
        self.assertTrue(d["has_warnings"])
        self.assertFalse(d["has_errors"])


# ---------------------------------------------------------------------------
# LogDTO
# ---------------------------------------------------------------------------


class TestLogDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = LogDTO(
            timestamp=100.0, level="INFO", component="test",
            message="hello")
        with self.assertRaises(Exception):
            dto.level = "ERROR"  # type: ignore

    def test_to_dict(self):
        dto = LogDTO(
            timestamp=100.0, level="INFO", component="test",
            message="hello", correlation_id="c1", session_id="s1")
        d = dto.to_dict()
        self.assertEqual(d["level"], "INFO")
        self.assertEqual(d["correlation_id"], "c1")


# ---------------------------------------------------------------------------
# CandidateDTO
# ---------------------------------------------------------------------------


class TestCandidateDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = CandidateDTO(candidate_id="43:3:16", base_score=0.85)
        with self.assertRaises(Exception):
            dto.candidate_id = "x"  # type: ignore

    def test_to_dict(self):
        dto = CandidateDTO(
            candidate_id="43:3:16", base_score=0.85,
            book="João", chapter=3, verse=16, display="João 3:16")
        d = dto.to_dict()
        self.assertEqual(d["candidate_id"], "43:3:16")
        self.assertEqual(d["book"], "João")


# ---------------------------------------------------------------------------
# EvidenceDTO
# ---------------------------------------------------------------------------


class TestEvidenceDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = EvidenceDTO(id="ev1", type="CONTEXT_BOOK_MATCH", description="test")
        with self.assertRaises(Exception):
            dto.id = "ev2"  # type: ignore

    def test_to_dict(self):
        dto = EvidenceDTO(
            id="ev1", type="CONTEXT_BOOK_MATCH", description="match",
            value=0.1, weight=0.15, confidence=0.9, contribution=0.015,
            metadata=(("k", "v"),), timestamp=100.0)
        d = dto.to_dict()
        self.assertEqual(d["id"], "ev1")
        self.assertEqual(d["type"], "CONTEXT_BOOK_MATCH")
        self.assertEqual(d["contribution"], 0.015)


# ---------------------------------------------------------------------------
# SignalDTO
# ---------------------------------------------------------------------------


class TestSignalDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = SignalDTO(
            signal_type="context", value=0.5, weight=0.3,
            contribution=0.15, explanation="test")
        with self.assertRaises(Exception):
            dto.signal_type = "x"  # type: ignore

    def test_has_evidences(self):
        ev = EvidenceDTO(id="ev1", type="TEST", description="d")
        dto = SignalDTO(
            signal_type="context", value=0.5, weight=0.3,
            contribution=0.15, explanation="test", evidences=(ev,))
        self.assertTrue(dto.has_evidences)
        self.assertEqual(dto.evidence_count, 1)

    def test_no_evidences(self):
        dto = SignalDTO(
            signal_type="context", value=0.5, weight=0.3,
            contribution=0.15, explanation="test")
        self.assertFalse(dto.has_evidences)
        self.assertEqual(dto.evidence_count, 0)

    def test_to_dict(self):
        ev = EvidenceDTO(id="ev1", type="TEST", description="d")
        dto = SignalDTO(
            signal_type="context", value=0.5, weight=0.3,
            contribution=0.15, explanation="test", evidences=(ev,))
        d = dto.to_dict()
        self.assertEqual(d["signal_type"], "context")
        self.assertEqual(d["evidence_count"], 1)
        self.assertEqual(len(d["evidences"]), 1)


# ---------------------------------------------------------------------------
# ScoreDTO
# ---------------------------------------------------------------------------


class TestScoreDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = ScoreDTO(
            candidate_id="43:3:16", base_score=0.85, final_score=0.95)
        with self.assertRaises(Exception):
            dto.final_score = 1.0  # type: ignore

    def test_total_contribution(self):
        dto = ScoreDTO(
            candidate_id="43:3:16", base_score=0.85, final_score=0.95,
            context_contribution=0.05, feedback_contribution=0.03,
            continuity_contribution=0.02)
        self.assertAlmostEqual(dto.total_contribution, 0.10)

    def test_signal_count(self):
        s1 = SignalDTO(signal_type="a", value=0.1, weight=0.1,
                       contribution=0.01, explanation="a")
        dto = ScoreDTO(
            candidate_id="43:3:16", base_score=0.85, final_score=0.95,
            signals=(s1,))
        self.assertEqual(dto.signal_count, 1)

    def test_to_dict(self):
        dto = ScoreDTO(
            candidate_id="43:3:16", base_score=0.85, final_score=0.95,
            confidence_level="HIGH", explanation="good match")
        d = dto.to_dict()
        self.assertEqual(d["candidate_id"], "43:3:16")
        self.assertEqual(d["confidence_level"], "HIGH")


# ---------------------------------------------------------------------------
# RecommendationDTO
# ---------------------------------------------------------------------------


class TestRecommendationDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = RecommendationDTO(
            query="fé", best_candidate_id="43:3:16",
            confidence_level="HIGH", explanation="test",
            has_candidates=True)
        with self.assertRaises(Exception):
            dto.query = "x"  # type: ignore

    def test_best_score(self):
        s = ScoreDTO(candidate_id="43:3:16", base_score=0.85, final_score=0.95)
        dto = RecommendationDTO(
            query="fé", best_candidate_id="43:3:16",
            confidence_level="HIGH", explanation="test",
            has_candidates=True, scores=(s,))
        self.assertIsNotNone(dto.best_score)
        self.assertEqual(dto.best_score.candidate_id, "43:3:16")

    def test_best_score_none(self):
        dto = RecommendationDTO(
            query="fé", best_candidate_id="",
            confidence_level="LOW", explanation="no candidates",
            has_candidates=False)
        self.assertIsNone(dto.best_score)

    def test_candidate_count(self):
        s1 = ScoreDTO(candidate_id="c1", base_score=0.8, final_score=0.9)
        s2 = ScoreDTO(candidate_id="c2", base_score=0.7, final_score=0.85)
        dto = RecommendationDTO(
            query="fé", best_candidate_id="c1",
            confidence_level="HIGH", explanation="test",
            has_candidates=True, scores=(s1, s2))
        self.assertEqual(dto.candidate_count, 2)

    def test_to_dict(self):
        dto = RecommendationDTO(
            query="fé", best_candidate_id="43:3:16",
            confidence_level="HIGH", explanation="test",
            has_candidates=True, ranking=("43:3:16",))
        d = dto.to_dict()
        self.assertEqual(d["query"], "fé")
        self.assertEqual(d["ranking"], ["43:3:16"])


# ---------------------------------------------------------------------------
# PresentationDTO
# ---------------------------------------------------------------------------


class TestPresentationDTO(unittest.TestCase):

    def test_is_frozen(self):
        dto = PresentationDTO(
            candidate_id="43:3:16", book_id=43, chapter=3,
            verse=16, version="ACF")
        with self.assertRaises(Exception):
            dto.candidate_id = "x"  # type: ignore

    def test_to_dict(self):
        dto = PresentationDTO(
            candidate_id="43:3:16", book_id=43, chapter=3,
            verse=16, version="ACF", status="ok",
            verse_id="43:3:16", presented=True)
        d = dto.to_dict()
        self.assertEqual(d["candidate_id"], "43:3:16")
        self.assertTrue(d["presented"])


if __name__ == "__main__":
    unittest.main()
