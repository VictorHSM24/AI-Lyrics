"""Testes unitários do módulo core/pipeline_metrics.py.

Estratégia:
  - PipelineMetrics é puro acumulador — testável sem mocks.
  - StageTiming e PipelineMetricsSnapshot são imutáveis (frozen).
  - 100% determinístico.
"""

from __future__ import annotations

import pytest

from core.pipeline_metrics import (
    PipelineMetrics,
    PipelineMetricsSnapshot,
    StageTiming,
)


# ---------------------------------------------------------------------------
# StageTiming
# ---------------------------------------------------------------------------


class TestStageTiming:
    """Testes do dataclass imutável StageTiming."""

    def test_create_success(self) -> None:
        t = StageTiming(stage="stt", duration_ms=42.5, success=True)
        assert t.stage == "stt"
        assert t.duration_ms == 42.5
        assert t.success is True
        assert t.error_msg is None

    def test_create_failure(self) -> None:
        t = StageTiming(
            stage="parser",
            duration_ms=10.0,
            success=False,
            error_msg="syntax error",
        )
        assert t.success is False
        assert t.error_msg == "syntax error"

    def test_is_frozen(self) -> None:
        t = StageTiming(stage="stt", duration_ms=1.0, success=True)
        with pytest.raises(Exception):
            t.duration_ms = 99.0  # type: ignore[misc]

    def test_equality(self) -> None:
        a = StageTiming(stage="stt", duration_ms=1.0, success=True)
        b = StageTiming(stage="stt", duration_ms=1.0, success=True)
        assert a == b

    def test_inequality(self) -> None:
        a = StageTiming(stage="stt", duration_ms=1.0, success=True)
        b = StageTiming(stage="stt", duration_ms=2.0, success=True)
        assert a != b


# ---------------------------------------------------------------------------
# PipelineMetrics — registro
# ---------------------------------------------------------------------------


class TestRecord:
    """Testes de PipelineMetrics.record()."""

    def test_record_single_success(self) -> None:
        m = PipelineMetrics()
        m.record(StageTiming(stage="stt", duration_ms=100.0, success=True))
        assert m.stage_count("stt") == 1
        assert m.stage_errors("stt") == 0
        assert m.stage_total_time_ms("stt") == 100.0
        assert m.total_errors == 0

    def test_record_single_failure(self) -> None:
        m = PipelineMetrics()
        m.record(
            StageTiming(
                stage="parser",
                duration_ms=5.0,
                success=False,
                error_msg="boom",
            )
        )
        assert m.stage_count("parser") == 1
        assert m.stage_errors("parser") == 1
        assert m.total_errors == 1

    def test_record_multiple_same_stage(self) -> None:
        m = PipelineMetrics()
        m.record(StageTiming(stage="stt", duration_ms=100.0, success=True))
        m.record(StageTiming(stage="stt", duration_ms=200.0, success=True))
        m.record(StageTiming(stage="stt", duration_ms=300.0, success=True))
        assert m.stage_count("stt") == 3
        assert m.stage_total_time_ms("stt") == 600.0
        assert m.avg_time_ms("stt") == 200.0

    def test_record_multiple_different_stages(self) -> None:
        m = PipelineMetrics()
        m.record(StageTiming(stage="stt", duration_ms=100.0, success=True))
        m.record(StageTiming(stage="parser", duration_ms=10.0, success=True))
        m.record(StageTiming(stage="decision", duration_ms=1.0, success=True))
        assert m.stage_count("stt") == 1
        assert m.stage_count("parser") == 1
        assert m.stage_count("decision") == 1

    def test_record_mixed_success_failure(self) -> None:
        m = PipelineMetrics()
        m.record(StageTiming(stage="stt", duration_ms=100.0, success=True))
        m.record(
            StageTiming(
                stage="stt", duration_ms=50.0, success=False, error_msg="x"
            )
        )
        m.record(StageTiming(stage="stt", duration_ms=200.0, success=True))
        assert m.stage_count("stt") == 3
        assert m.stage_errors("stt") == 1
        assert m.total_errors == 1
        assert m.stage_total_time_ms("stt") == 350.0

    def test_record_zero_duration(self) -> None:
        m = PipelineMetrics()
        m.record(StageTiming(stage="decision", duration_ms=0.0, success=True))
        assert m.stage_count("decision") == 1
        assert m.avg_time_ms("decision") == 0.0


# ---------------------------------------------------------------------------
# PipelineMetrics — contadores de utterance/execute
# ---------------------------------------------------------------------------


class TestCounters:
    """Testes dos contadores de utterance e execute."""

    def test_record_utterance(self) -> None:
        m = PipelineMetrics()
        m.record_utterance()
        m.record_utterance()
        m.record_utterance()
        assert m.total_utterances == 3

    def test_record_execute(self) -> None:
        m = PipelineMetrics()
        m.record_execute()
        m.record_execute()
        assert m.total_executes == 2

    def test_initial_zero(self) -> None:
        m = PipelineMetrics()
        assert m.total_utterances == 0
        assert m.total_executes == 0
        assert m.total_errors == 0


# ---------------------------------------------------------------------------
# PipelineMetrics — médias
# ---------------------------------------------------------------------------


class TestAverages:
    """Testes de PipelineMetrics.avg_time_ms()."""

    def test_avg_empty_stage(self) -> None:
        m = PipelineMetrics()
        assert m.avg_time_ms("stt") == 0.0

    def test_avg_single(self) -> None:
        m = PipelineMetrics()
        m.record(StageTiming(stage="stt", duration_ms=150.0, success=True))
        assert m.avg_time_ms("stt") == 150.0

    def test_avg_multiple(self) -> None:
        m = PipelineMetrics()
        for d in (100.0, 200.0, 300.0, 400.0):
            m.record(StageTiming(stage="stt", duration_ms=d, success=True))
        assert m.avg_time_ms("stt") == 250.0

    def test_avg_unknown_stage(self) -> None:
        m = PipelineMetrics()
        m.record(StageTiming(stage="stt", duration_ms=100.0, success=True))
        assert m.avg_time_ms("parser") == 0.0

    def test_avg_includes_failures(self) -> None:
        """Falhas também contam no tempo médio (tempo até falhar)."""
        m = PipelineMetrics()
        m.record(StageTiming(stage="stt", duration_ms=100.0, success=True))
        m.record(
            StageTiming(
                stage="stt", duration_ms=200.0, success=False, error_msg="x"
            )
        )
        assert m.avg_time_ms("stt") == 150.0


# ---------------------------------------------------------------------------
# PipelineMetrics — snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    """Testes de PipelineMetrics.snapshot()."""

    def test_snapshot_empty(self) -> None:
        m = PipelineMetrics()
        s = m.snapshot()
        assert isinstance(s, PipelineMetricsSnapshot)
        assert s.total_utterances == 0
        assert s.total_executes == 0
        assert s.total_errors == 0
        assert s.avg_stage_ms == {}
        assert s.stage_counts == {}
        assert s.stage_errors == {}
        assert s.stage_total_ms == {}

    def test_snapshot_reflects_state(self) -> None:
        m = PipelineMetrics()
        m.record_utterance()
        m.record_utterance()
        m.record_execute()
        m.record(StageTiming(stage="stt", duration_ms=100.0, success=True))
        m.record(StageTiming(stage="stt", duration_ms=200.0, success=True))
        m.record(
            StageTiming(
                stage="parser", duration_ms=10.0, success=False, error_msg="e"
            )
        )
        s = m.snapshot()
        assert s.total_utterances == 2
        assert s.total_executes == 1
        assert s.total_errors == 1
        assert s.stage_counts == {"stt": 2, "parser": 1}
        assert s.stage_errors == {"parser": 1}
        assert s.avg_stage_ms["stt"] == 150.0
        assert s.avg_stage_ms["parser"] == 10.0
        assert s.stage_total_ms["stt"] == 300.0
        assert s.stage_total_ms["parser"] == 10.0

    def test_snapshot_is_frozen(self) -> None:
        m = PipelineMetrics()
        m.record(StageTiming(stage="stt", duration_ms=100.0, success=True))
        s = m.snapshot()
        with pytest.raises(Exception):
            s.total_utterances = 99  # type: ignore[misc]

    def test_snapshot_is_independent(self) -> None:
        """Mutação após snapshot não afeta snapshot já produzido."""
        m = PipelineMetrics()
        m.record(StageTiming(stage="stt", duration_ms=100.0, success=True))
        s1 = m.snapshot()
        m.record(StageTiming(stage="stt", duration_ms=200.0, success=True))
        m.record_utterance()
        s2 = m.snapshot()
        assert s1.stage_counts == {"stt": 1}
        assert s2.stage_counts == {"stt": 2}
        assert s1.total_utterances == 0
        assert s2.total_utterances == 1

    def test_snapshot_dicts_are_copies(self) -> None:
        """Dicionários do snapshot são cópias — mutá-los não afeta metrics."""
        m = PipelineMetrics()
        m.record(StageTiming(stage="stt", duration_ms=100.0, success=True))
        s = m.snapshot()
        s.avg_stage_ms["stt"] = 999.0
        # metrics original não foi afetada
        assert m.avg_time_ms("stt") == 100.0

    def test_multiple_snapshots_independent(self) -> None:
        m = PipelineMetrics()
        m.record(StageTiming(stage="stt", duration_ms=100.0, success=True))
        s1 = m.snapshot()
        m.record(StageTiming(stage="stt", duration_ms=300.0, success=True))
        s2 = m.snapshot()
        assert s1.avg_stage_ms["stt"] == 100.0
        assert s2.avg_stage_ms["stt"] == 200.0
        assert s1 is not s2


# ---------------------------------------------------------------------------
# PipelineMetrics — reset
# ---------------------------------------------------------------------------


class TestReset:
    """Testes de PipelineMetrics.reset()."""

    def test_reset_clears_all(self) -> None:
        m = PipelineMetrics()
        m.record_utterance()
        m.record_execute()
        m.record(StageTiming(stage="stt", duration_ms=100.0, success=True))
        m.record(
            StageTiming(
                stage="stt", duration_ms=50.0, success=False, error_msg="x"
            )
        )
        m.reset()
        assert m.total_utterances == 0
        assert m.total_executes == 0
        assert m.total_errors == 0
        assert m.stage_count("stt") == 0
        assert m.stage_errors("stt") == 0
        assert m.stage_total_time_ms("stt") == 0.0
        assert m.avg_time_ms("stt") == 0.0

    def test_reset_empty_metrics(self) -> None:
        m = PipelineMetrics()
        m.reset()
        assert m.total_utterances == 0

    def test_can_record_after_reset(self) -> None:
        m = PipelineMetrics()
        m.record(StageTiming(stage="stt", duration_ms=100.0, success=True))
        m.reset()
        m.record(StageTiming(stage="stt", duration_ms=50.0, success=True))
        assert m.stage_count("stt") == 1
        assert m.avg_time_ms("stt") == 50.0


# ---------------------------------------------------------------------------
# PipelineMetrics — consultas auxiliares
# ---------------------------------------------------------------------------


class TestQueries:
    """Testes dos métodos de consulta stage_total_time_ms, stage_errors."""

    def test_stage_total_time_unknown(self) -> None:
        m = PipelineMetrics()
        assert m.stage_total_time_ms("stt") == 0.0

    def test_stage_errors_unknown(self) -> None:
        m = PipelineMetrics()
        assert m.stage_errors("stt") == 0

    def test_stage_count_unknown(self) -> None:
        m = PipelineMetrics()
        assert m.stage_count("stt") == 0

    def test_all_stages_tracked(self) -> None:
        m = PipelineMetrics()
        for stage in ("stt", "parser", "llm", "search", "decision", "holyrics"):
            m.record(StageTiming(stage=stage, duration_ms=10.0, success=True))
        for stage in ("stt", "parser", "llm", "search", "decision", "holyrics"):
            assert m.stage_count(stage) == 1
            assert m.avg_time_ms(stage) == 10.0
