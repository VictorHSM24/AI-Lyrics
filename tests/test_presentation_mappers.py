"""Testes dos Mappers da Presentation Layer.

Cobre:
  - PipelineMapper: PipelineState → PipelineStatusDTO.
  - SessionMapper: PipelineSession → SessionDTO.
  - MetricsMapper: PipelineMetrics → MetricsDTO.
  - EventMapper: PipelineEvent → EventDTO, EventMetadata → DTO.
  - EvidenceMapper: Evidence → EvidenceDTO.
  - SignalMapper: IntelligenceSignal → SignalDTO.
  - ScoreMapper: IntelligenceScore → ScoreDTO.
  - RecommendationMapper: IntelligenceRecommendation → RecommendationDTO.
  - CandidateMapper: CandidateInfo → CandidateDTO.
  - PresentationMapper: PresentationRequested/Completed → PresentationDTO.
  - ConfigurationMapper: Config → ConfigurationDTO.
  - HealthMapper: constrói HealthDTO.
  - DiagnosticMapper: constrói DiagnosticDTO.
  - LogMapper: constrói LogDTO, from_event.
"""

from __future__ import annotations

import unittest

import sys
sys.path.insert(0, ".")

from pipeline import (
    EventMetadata,
    PipelineMetrics,
    PipelinePolicy,
    PipelineSession,
    PipelineState,
    PresentationCompleted,
    PresentationRequested,
    SearchCompleted,
    SearchRequested,
    SpeechRecognized,
    SpeechSegmentReceived,
)
from presentation import (
    CandidateDTO,
    CandidateMapper,
    ConfigurationMapper,
    DiagnosticDTO,
    DiagnosticMapper,
    EventDTO,
    EventMapper,
    EvidenceDTO,
    EvidenceMapper,
    HealthDTO,
    HealthMapper,
    LogDTO,
    LogMapper,
    MetricsDTO,
    MetricsMapper,
    PipelineMapper,
    PipelineStatusDTO,
    PresentationDTO,
    PresentationMapper,
    RecommendationDTO,
    RecommendationMapper,
    ScoreDTO,
    ScoreMapper,
    SessionDTO,
    SessionMapper,
    SignalDTO,
    SignalMapper,
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
# PipelineMapper
# ---------------------------------------------------------------------------


class TestPipelineMapper(unittest.TestCase):

    def test_to_status_dto(self):
        state = PipelineState(
            running=True, paused=False, last_query="fé",
            last_candidate_id="43:3:16", last_event_type="SearchCompleted",
            last_event_timestamp=100.0, statistics={"count": 5})
        dto = PipelineMapper.to_status_dto(state)
        self.assertIsInstance(dto, PipelineStatusDTO)
        self.assertTrue(dto.running)
        self.assertTrue(dto.is_active)
        self.assertEqual(dto.last_query, "fé")
        self.assertEqual(dto.last_candidate_id, "43:3:16")
        self.assertEqual(dto.statistics, {"count": 5})

    def test_to_status_dto_paused(self):
        state = PipelineState(running=True, paused=True)
        dto = PipelineMapper.to_status_dto(state)
        self.assertTrue(dto.paused)
        self.assertFalse(dto.is_active)

    def test_to_status_dto_idle(self):
        state = PipelineState()
        dto = PipelineMapper.to_status_dto(state)
        self.assertTrue(dto.is_idle)
        self.assertFalse(dto.is_active)

    def test_to_status_dto_with_segment(self):
        meta = _make_meta()
        seg = SpeechSegmentReceived(meta=meta, duration_ms=1000)
        state = PipelineState(running=True, current_segment=seg)
        dto = PipelineMapper.to_status_dto(state)
        self.assertIsNotNone(dto.current_segment)
        self.assertIn("duration_ms", dto.current_segment)


# ---------------------------------------------------------------------------
# SessionMapper
# ---------------------------------------------------------------------------


class TestSessionMapper(unittest.TestCase):

    def test_to_dto(self):
        session = PipelineSession.create(session_id="s1", started_at=100.0)
        session = session.with_segment_processed("c1")
        session = session.with_query_processed()
        dto = SessionMapper.to_dto(session)
        self.assertIsInstance(dto, SessionDTO)
        self.assertEqual(dto.session_id, "s1")
        self.assertTrue(dto.is_active)
        self.assertEqual(dto.processed_segments, 1)
        self.assertEqual(dto.processed_queries, 1)
        self.assertIn("c1", dto.correlation_ids)

    def test_to_dto_ended(self):
        session = PipelineSession.create(session_id="s1", started_at=100.0)
        session = session.with_ended(200.0)
        dto = SessionMapper.to_dto(session)
        self.assertTrue(dto.is_ended)
        self.assertAlmostEqual(dto.duration_s, 100.0)


# ---------------------------------------------------------------------------
# MetricsMapper
# ---------------------------------------------------------------------------


class TestMetricsMapper(unittest.TestCase):

    def test_to_dto(self):
        metrics = PipelineMetrics()
        metrics.record_segment_received()
        metrics.record_segment_processed(latency_ms=100.0)
        metrics.record_query_processed()
        metrics.record_error()
        dto = MetricsMapper.to_dto(metrics)
        self.assertIsInstance(dto, MetricsDTO)
        self.assertEqual(dto.segments_received, 1)
        self.assertEqual(dto.segments_processed, 1)
        self.assertEqual(dto.queries_processed, 1)
        self.assertEqual(dto.errors_total, 1)
        self.assertAlmostEqual(dto.avg_latency_ms, 100.0)

    def test_to_dto_empty(self):
        metrics = PipelineMetrics()
        dto = MetricsMapper.to_dto(metrics)
        self.assertEqual(dto.segments_received, 0)
        self.assertEqual(dto.avg_latency_ms, 0.0)


# ---------------------------------------------------------------------------
# EventMapper
# ---------------------------------------------------------------------------


class TestEventMapper(unittest.TestCase):

    def test_to_metadata_dto(self):
        meta = _make_meta(metadata=(("k", "v"),))
        dto = EventMapper.to_metadata_dto(meta)
        self.assertEqual(dto.event_id, "e1")
        self.assertEqual(dto.correlation_id, "c1")
        self.assertEqual(dto.metadata, (("k", "v"),))

    def test_to_dto(self):
        meta = _make_meta()
        ev = SpeechRecognized(meta=meta, text="hello", confidence=0.9)
        dto = EventMapper.to_dto(ev)
        self.assertIsInstance(dto, EventDTO)
        self.assertEqual(dto.event_type, "SpeechRecognized")
        self.assertEqual(dto.payload["text"], "hello")
        self.assertEqual(dto.payload["confidence"], 0.9)

    def test_to_dto_preserves_correlation(self):
        meta = _make_meta(correlation_id="my-corr")
        ev = SpeechRecognized(meta=meta, text="hello")
        dto = EventMapper.to_dto(ev)
        self.assertEqual(dto.correlation_id, "my-corr")

    def test_to_dto_many(self):
        meta = _make_meta()
        events = (
            SpeechRecognized(meta=meta, text="a"),
            SearchRequested(meta=meta, query="a"),
        )
        dtos = EventMapper.to_dto_many(events)
        self.assertEqual(len(dtos), 2)
        self.assertEqual(dtos[0].event_type, "SpeechRecognized")
        self.assertEqual(dtos[1].event_type, "SearchRequested")


# ---------------------------------------------------------------------------
# EvidenceMapper
# ---------------------------------------------------------------------------


class TestEvidenceMapper(unittest.TestCase):

    def test_to_dto(self):
        from intelligence import Evidence, EvidenceType
        ev = Evidence(
            id="ev1", type=EvidenceType.CONTEXT_BOOK_MATCH,
            description="match", value=0.1, weight=0.15,
            confidence=0.9, metadata=(("k", "v"),), timestamp=100.0)
        dto = EvidenceMapper.to_dto(ev)
        self.assertIsInstance(dto, EvidenceDTO)
        self.assertEqual(dto.id, "ev1")
        self.assertEqual(dto.type, "CONTEXT_BOOK_MATCH")
        self.assertAlmostEqual(dto.contribution, 0.015)

    def test_to_dto_many(self):
        from intelligence import Evidence, EvidenceType
        ev1 = Evidence(id="ev1", type=EvidenceType.CUSTOM, description="a")
        ev2 = Evidence(id="ev2", type=EvidenceType.CUSTOM, description="b")
        dtos = EvidenceMapper.to_dto_many((ev1, ev2))
        self.assertEqual(len(dtos), 2)


# ---------------------------------------------------------------------------
# SignalMapper
# ---------------------------------------------------------------------------


class TestSignalMapper(unittest.TestCase):

    def test_to_dto(self):
        from intelligence import IntelligenceSignal
        sig = IntelligenceSignal(
            signal_type="context", value=0.5, weight=0.3,
            explanation="test")
        dto = SignalMapper.to_dto(sig)
        self.assertIsInstance(dto, SignalDTO)
        self.assertEqual(dto.signal_type, "context")
        self.assertAlmostEqual(dto.contribution, 0.15)

    def test_to_dto_with_evidences(self):
        from intelligence import IntelligenceSignal, Evidence, EvidenceType
        ev = Evidence(id="ev1", type=EvidenceType.CUSTOM, description="d")
        sig = IntelligenceSignal(
            signal_type="context", value=0.5, weight=0.3,
            explanation="test", evidences=(ev,))
        dto = SignalMapper.to_dto(sig)
        self.assertTrue(dto.has_evidences)
        self.assertEqual(dto.evidence_count, 1)


# ---------------------------------------------------------------------------
# ScoreMapper
# ---------------------------------------------------------------------------


class TestScoreMapper(unittest.TestCase):

    def test_to_dto(self):
        from intelligence import IntelligenceScore, ConfidenceLevel
        score = IntelligenceScore(
            candidate_id="43:3:16", base_score=0.85, final_score=0.95,
            context_contribution=0.05, confidence_level=ConfidenceLevel.HIGH,
            explanation="good")
        dto = ScoreMapper.to_dto(score)
        self.assertIsInstance(dto, ScoreDTO)
        self.assertEqual(dto.candidate_id, "43:3:16")
        self.assertEqual(dto.confidence_level, "HIGH")
        self.assertAlmostEqual(dto.total_contribution, 0.05)

    def test_to_dto_many(self):
        from intelligence import IntelligenceScore
        s1 = IntelligenceScore(candidate_id="c1", base_score=0.8, final_score=0.9)
        s2 = IntelligenceScore(candidate_id="c2", base_score=0.7, final_score=0.85)
        dtos = ScoreMapper.to_dto_many((s1, s2))
        self.assertEqual(len(dtos), 2)


# ---------------------------------------------------------------------------
# RecommendationMapper
# ---------------------------------------------------------------------------


class TestRecommendationMapper(unittest.TestCase):

    def test_to_dto(self):
        from intelligence import (
            IntelligenceRecommendation, IntelligenceScore, ConfidenceLevel,
        )
        score = IntelligenceScore(
            candidate_id="43:3:16", base_score=0.85, final_score=0.95,
            confidence_level=ConfidenceLevel.HIGH)
        rec = IntelligenceRecommendation(
            query="fé", scores=(score,), best_candidate_id="43:3:16",
            confidence_level=ConfidenceLevel.HIGH, explanation="good",
            has_candidates=True)
        dto = RecommendationMapper.to_dto(rec)
        self.assertIsInstance(dto, RecommendationDTO)
        self.assertEqual(dto.query, "fé")
        self.assertEqual(dto.best_candidate_id, "43:3:16")
        self.assertEqual(dto.confidence_level, "HIGH")
        self.assertEqual(dto.candidate_count, 1)
        self.assertEqual(dto.ranking, ("43:3:16",))

    def test_to_dto_empty(self):
        from intelligence import IntelligenceRecommendation, ConfidenceLevel
        rec = IntelligenceRecommendation(
            query="fé", confidence_level=ConfidenceLevel.LOW,
            has_candidates=False)
        dto = RecommendationMapper.to_dto(rec)
        self.assertEqual(dto.candidate_count, 0)
        self.assertIsNone(dto.best_score)


# ---------------------------------------------------------------------------
# CandidateMapper
# ---------------------------------------------------------------------------


class TestCandidateMapper(unittest.TestCase):

    def test_to_dto(self):
        from intelligence import CandidateInfo
        cand = CandidateInfo(
            candidate_id="43:3:16", base_score=0.85,
            book="João", chapter=3, verse=16, display="João 3:16")
        dto = CandidateMapper.to_dto(cand)
        self.assertIsInstance(dto, CandidateDTO)
        self.assertEqual(dto.candidate_id, "43:3:16")
        self.assertEqual(dto.book, "João")

    def test_to_dto_many(self):
        from intelligence import CandidateInfo
        c1 = CandidateInfo(candidate_id="c1", base_score=0.8)
        c2 = CandidateInfo(candidate_id="c2", base_score=0.7)
        dtos = CandidateMapper.to_dto_many((c1, c2))
        self.assertEqual(len(dtos), 2)


# ---------------------------------------------------------------------------
# PresentationMapper
# ---------------------------------------------------------------------------


class TestPresentationMapper(unittest.TestCase):

    def test_from_requested(self):
        meta = _make_meta()
        ev = PresentationRequested(
            meta=meta, candidate_id="43:3:16", book_id=43,
            chapter=3, verse=16, version="ACF")
        dto = PresentationMapper.from_requested(ev)
        self.assertIsInstance(dto, PresentationDTO)
        self.assertEqual(dto.candidate_id, "43:3:16")
        self.assertEqual(dto.book_id, 43)
        self.assertEqual(dto.version, "ACF")

    def test_from_completed(self):
        meta = _make_meta()
        ev = PresentationCompleted(
            meta=meta, candidate_id="43:3:16", status="ok",
            verse_id="43:3:16", presented=True)
        dto = PresentationMapper.from_completed(ev)
        self.assertEqual(dto.candidate_id, "43:3:16")
        self.assertEqual(dto.status, "ok")
        self.assertTrue(dto.presented)


# ---------------------------------------------------------------------------
# ConfigurationMapper
# ---------------------------------------------------------------------------


class TestConfigurationMapper(unittest.TestCase):

    def test_to_dto(self):
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
        dto = ConfigurationMapper.to_dto(config)
        self.assertEqual(dto.mode, "auto")
        self.assertEqual(dto.holyrics["base_url"], "http://localhost")
        self.assertEqual(dto.stt["model"], "large-v3")

    def test_to_dto_with_pipeline_policy(self):
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
        policy = PipelinePolicy(recognition_timeout_ms=9999)
        dto = ConfigurationMapper.to_dto(config, pipeline_policy=policy)
        self.assertIsNotNone(dto.pipeline_policy)
        self.assertEqual(dto.pipeline_policy["recognition_timeout_ms"], 9999)


# ---------------------------------------------------------------------------
# HealthMapper
# ---------------------------------------------------------------------------


class TestHealthMapper(unittest.TestCase):

    def test_healthy(self):
        dto = HealthMapper.healthy("pipeline", "OK")
        self.assertEqual(dto.status, "healthy")
        self.assertTrue(dto.is_healthy)

    def test_degraded(self):
        dto = HealthMapper.degraded("pipeline", "slow")
        self.assertTrue(dto.is_degraded)

    def test_unhealthy(self):
        dto = HealthMapper.unhealthy("pipeline", "down")
        self.assertTrue(dto.is_unhealthy)

    def test_unknown(self):
        dto = HealthMapper.unknown("pipeline")
        self.assertEqual(dto.status, "unknown")

    def test_from_state_running(self):
        dto = HealthMapper.from_state("pipeline", True, "running")
        self.assertTrue(dto.is_healthy)

    def test_from_state_not_running(self):
        dto = HealthMapper.from_state("pipeline", False)
        self.assertTrue(dto.is_unhealthy)

    def test_with_details(self):
        dto = HealthMapper.healthy("bus", "OK", {"count": 5})
        self.assertEqual(dto.details, {"count": 5})


# ---------------------------------------------------------------------------
# DiagnosticMapper
# ---------------------------------------------------------------------------


class TestDiagnosticMapper(unittest.TestCase):

    def test_to_dto(self):
        dto = DiagnosticMapper.to_dto(
            component="gpu", category="hardware", available=True,
            info={"name": "RTX 4090"}, warnings=("high_temp",))
        self.assertIsInstance(dto, DiagnosticDTO)
        self.assertEqual(dto.component, "gpu")
        self.assertTrue(dto.available)
        self.assertTrue(dto.has_warnings)

    def test_to_dto_defaults(self):
        dto = DiagnosticMapper.to_dto(
            component="cpu", category="hardware", available=False)
        self.assertEqual(dto.info, {})
        self.assertEqual(dto.warnings, ())
        self.assertEqual(dto.errors, ())


# ---------------------------------------------------------------------------
# LogMapper
# ---------------------------------------------------------------------------


class TestLogMapper(unittest.TestCase):

    def test_to_dto(self):
        dto = LogMapper.to_dto(
            timestamp=100.0, level="INFO", component="test",
            message="hello", correlation_id="c1", session_id="s1")
        self.assertIsInstance(dto, LogDTO)
        self.assertEqual(dto.level, "INFO")
        self.assertEqual(dto.correlation_id, "c1")

    def test_from_event(self):
        meta = _make_meta()
        ev = SpeechRecognized(meta=meta, text="hello")
        dto = LogMapper.from_event(ev, level="INFO")
        self.assertEqual(dto.component, "test")
        self.assertEqual(dto.message, "SpeechRecognized")
        self.assertEqual(dto.correlation_id, "c1")
        self.assertEqual(dto.session_id, "s1")


if __name__ == "__main__":
    unittest.main()
