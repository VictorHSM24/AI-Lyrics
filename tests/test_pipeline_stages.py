"""Testes unitários do módulo core/pipeline_stages.py.

Estratégia:
  - Cada stage é testado com mocks das dependências.
  - Testa-se sucesso (retorna resultado + StageTiming.success=True).
  - Testa-se falha com exceção de domínio (PipelineError + StageTiming anexado).
  - Testa-se falha com exceção genérica (PipelineError + StageTiming anexado).
  - Verifica-se que StageTiming.duration_ms é >= 0.
  - 100% determinístico.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from busca.searcher import SearchResult
from config.models import ConfidenceConfig
from core.decision import DecisionEngine
from core.exceptions import AILyricsError, DecisionError, PipelineError, StateError
from core.pipeline_metrics import StageTiming
from core.pipeline_stages import (
    _measure,
    execute_decision,
    run_decision,
    run_parser,
    run_search,
)
from core.types import Confidence, Decision, Intent, VerseRef
from estado.state import BibleState, BibleStructure, BibleStateManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _conf_config(
    min_execute: float = 0.85,
    min_confirm: float = 0.60,
    stt_min: float = 0.50,
) -> ConfidenceConfig:
    return ConfidenceConfig(
        min_execute=min_execute,
        min_confirm=min_confirm,
        stt_min=stt_min,
        parser_high=0.90,
        parser_compact=0.85,
    )


def _structure() -> BibleStructure:
    return BibleStructure(
        chapter_counts={43: 21, 1: 50, 45: 16},
        verse_counts={(43, 3): 36, (1, 1): 31, (45, 8): 39},
    )


def _book_names() -> dict[int, str]:
    return {43: "João", 1: "Gênesis", 45: "Romanos"}


def _state_manager() -> BibleStateManager:
    return BibleStateManager(
        structure=_structure(),
        book_names=_book_names(),
        default_version="ACF",
    )


def _search_result(
    book: str = "João",
    book_id: int = 43,
    chapter: int = 3,
    verse: int = 16,
    score: float = 0.95,
    c_search: float = 0.9,
    ambiguous: bool = False,
    match_type: str = "hybrid",
) -> SearchResult:
    return SearchResult(
        reference=f"{book} {chapter}:{verse}",
        book=book,
        book_id=book_id,
        chapter=chapter,
        verse=verse,
        text="Porque Deus amou o mundo...",
        version="ACF",
        score=score,
        c_search=c_search,
        ambiguous=ambiguous,
        match_type=match_type,
    )


def _intent(
    action: str = "show",
    book: str = "João",
    book_id: int = 43,
    chapter: int = 3,
    verse: int = 16,
    confidence: float = 0.95,
) -> Intent:
    return Intent(
        action=action,
        book=book,
        book_id=book_id,
        chapter=chapter,
        verse=verse,
        confidence=confidence,
        raw="joão 3 16",
    )


def _decision(
    outcome: str = "execute",
    intent: Intent | None = None,
    confidence: float = 0.95,
) -> Decision:
    return Decision(
        action="show",
        outcome=outcome,
        confidence=confidence,
        requires_confirmation=False,
        forward_to_llm=False,
        ignore=False,
        reason="c_final >= min_execute",
        intent=intent or _intent(),
        ref=None,
        confidence_breakdown=Confidence(c_stt=1.0, c_intent=0.95, c_search=1.0),
    )


# ---------------------------------------------------------------------------
# _measure (helper interno)
# ---------------------------------------------------------------------------


class TestMeasure:
    """Testes do helper _measure."""

    def test_success(self) -> None:
        def fn() -> int:
            return 42

        result, timing = _measure("test", fn)
        assert result == 42
        assert isinstance(timing, StageTiming)
        assert timing.stage == "test"
        assert timing.success is True
        assert timing.error_msg is None
        assert timing.duration_ms >= 0.0

    def test_domain_error(self) -> None:
        def fn() -> None:
            raise StateError("bad state")

        with pytest.raises(PipelineError) as exc_info:
            _measure("test", fn)
        assert "stage 'test' failed" in str(exc_info.value)
        assert "StateError" in str(exc_info.value)
        assert "bad state" in str(exc_info.value)
        # StageTiming anexado
        timing = exc_info.value.stage_timing
        assert timing is not None
        assert timing.stage == "test"
        assert timing.success is False
        assert "bad state" in timing.error_msg
        assert timing.duration_ms >= 0.0

    def test_generic_error(self) -> None:
        def fn() -> None:
            raise ValueError("oops")

        with pytest.raises(PipelineError) as exc_info:
            _measure("test", fn)
        assert "unexpected" in str(exc_info.value)
        assert "ValueError" in str(exc_info.value)
        timing = exc_info.value.stage_timing
        assert timing is not None
        assert timing.success is False
        assert "oops" in timing.error_msg

    def test_preserves_cause(self) -> None:
        def fn() -> None:
            raise StateError("orig")

        with pytest.raises(PipelineError) as exc_info:
            _measure("test", fn)
        assert isinstance(exc_info.value.__cause__, StateError)

    def test_with_args_kwargs(self) -> None:
        def fn(a: int, b: int, *, c: int) -> int:
            return a + b + c

        result, timing = _measure("test", fn, 1, 2, c=3)
        assert result == 6
        assert timing.success is True


# ---------------------------------------------------------------------------
# run_parser
# ---------------------------------------------------------------------------


class TestRunParser:
    """Testes do stage run_parser."""

    def test_success(self) -> None:
        parser = MagicMock()
        expected_intent = _intent()
        parser.parse.return_value = expected_intent

        intent, timing = run_parser(parser, "joão 3 16")
        assert intent is expected_intent
        assert timing.stage == "parser"
        assert timing.success is True
        assert timing.error_msg is None
        parser.parse.assert_called_once_with("joão 3 16", None)

    def test_success_with_state(self) -> None:
        parser = MagicMock()
        parser.parse.return_value = _intent()
        state = BibleState()

        intent, timing = run_parser(parser, "próximo", state=state)
        assert timing.success is True
        parser.parse.assert_called_once_with("próximo", state)

    def test_domain_error(self) -> None:
        parser = MagicMock()
        parser.parse.side_effect = StateError("parse failed")

        with pytest.raises(PipelineError) as exc_info:
            run_parser(parser, "joão")
        assert "parser" in str(exc_info.value)
        timing = exc_info.value.stage_timing
        assert timing.stage == "parser"
        assert timing.success is False
        assert "parse failed" in timing.error_msg

    def test_generic_error(self) -> None:
        parser = MagicMock()
        parser.parse.side_effect = RuntimeError("unexpected")

        with pytest.raises(PipelineError) as exc_info:
            run_parser(parser, "joão")
        assert "unexpected" in str(exc_info.value)
        timing = exc_info.value.stage_timing
        assert timing.success is False

    def test_empty_text(self) -> None:
        parser = MagicMock()
        parser.parse.return_value = Intent(action="none", raw="")

        intent, timing = run_parser(parser, "")
        assert intent.action == "none"
        assert timing.success is True


# ---------------------------------------------------------------------------
# run_search
# ---------------------------------------------------------------------------


class TestRunSearch:
    """Testes do stage run_search."""

    def test_success(self) -> None:
        searcher = MagicMock()
        results = [_search_result()]
        searcher.search.return_value = results

        out, timing = run_search(searcher, "deus amou o mundo")
        assert out is results
        assert timing.stage == "search"
        assert timing.success is True
        searcher.search.assert_called_once_with(
            "deus amou o mundo", top_k=None, version=None, state=None
        )

    def test_success_with_kwargs(self) -> None:
        searcher = MagicMock()
        searcher.search.return_value = [_search_result()]
        state = BibleState()

        out, timing = run_search(
            searcher, "deus", top_k=5, version="NVI", state=state
        )
        assert timing.success is True
        searcher.search.assert_called_once_with(
            "deus", top_k=5, version="NVI", state=state
        )

    def test_empty_results(self) -> None:
        searcher = MagicMock()
        searcher.search.return_value = []

        out, timing = run_search(searcher, "xyz")
        assert out == []
        assert timing.success is True

    def test_domain_error(self) -> None:
        from busca.exceptions import SearchError

        searcher = MagicMock()
        searcher.search.side_effect = SearchError("fts failed")

        with pytest.raises(PipelineError) as exc_info:
            run_search(searcher, "deus")
        assert "search" in str(exc_info.value)
        timing = exc_info.value.stage_timing
        assert timing.stage == "search"
        assert timing.success is False
        assert "fts failed" in timing.error_msg

    def test_generic_error(self) -> None:
        searcher = MagicMock()
        searcher.search.side_effect = OSError("disk error")

        with pytest.raises(PipelineError) as exc_info:
            run_search(searcher, "deus")
        assert "unexpected" in str(exc_info.value)
        timing = exc_info.value.stage_timing
        assert timing.success is False


# ---------------------------------------------------------------------------
# run_decision
# ---------------------------------------------------------------------------


class TestRunDecision:
    """Testes do stage run_decision."""

    def test_success(self) -> None:
        engine = MagicMock(spec=DecisionEngine)
        expected_decision = _decision()
        engine.evaluate.return_value = expected_decision

        intent = _intent()
        decision, timing = run_decision(engine, intent, c_stt=0.95)
        assert decision is expected_decision
        assert timing.stage == "decision"
        assert timing.success is True
        engine.evaluate.assert_called_once_with(intent, 0.95, None)

    def test_success_with_search_results(self) -> None:
        engine = MagicMock(spec=DecisionEngine)
        engine.evaluate.return_value = _decision()
        results = [_search_result()]

        decision, timing = run_decision(
            engine, _intent(action="search"), c_stt=0.9, search_results=results
        )
        assert timing.success is True
        engine.evaluate.assert_called_once_with(
            _intent(action="search"), 0.9, results
        )

    def test_domain_error(self) -> None:
        engine = MagicMock(spec=DecisionEngine)
        engine.evaluate.side_effect = DecisionError("bad intent")

        with pytest.raises(PipelineError) as exc_info:
            run_decision(engine, _intent())
        assert "decision" in str(exc_info.value)
        timing = exc_info.value.stage_timing
        assert timing.stage == "decision"
        assert timing.success is False
        assert "bad intent" in timing.error_msg

    def test_generic_error(self) -> None:
        engine = MagicMock(spec=DecisionEngine)
        engine.evaluate.side_effect = TypeError("wrong type")

        with pytest.raises(PipelineError) as exc_info:
            run_decision(engine, _intent())
        assert "unexpected" in str(exc_info.value)
        timing = exc_info.value.stage_timing
        assert timing.success is False


# ---------------------------------------------------------------------------
# execute_decision
# ---------------------------------------------------------------------------


class TestExecuteDecision:
    """Testes do stage execute_decision."""

    def test_success(self) -> None:
        engine = MagicMock(spec=DecisionEngine)
        ref = VerseRef(book_id=43, book="João", chapter=3, verse=16)
        engine.execute.return_value = ref

        decision = _decision()
        out_ref, timing = execute_decision(engine, decision)
        assert out_ref is ref
        assert timing.stage == "holyrics"
        assert timing.success is True
        engine.execute.assert_called_once_with(decision, None)

    def test_success_with_search_results(self) -> None:
        engine = MagicMock(spec=DecisionEngine)
        engine.execute.return_value = VerseRef(
            book_id=43, book="João", chapter=3, verse=16
        )
        results = [_search_result()]

        out_ref, timing = execute_decision(
            engine, _decision(), search_results=results
        )
        assert timing.success is True
        engine.execute.assert_called_once_with(_decision(), results)

    def test_success_returns_none(self) -> None:
        """execute pode retornar None se não resolve ref."""
        engine = MagicMock(spec=DecisionEngine)
        engine.execute.return_value = None

        out_ref, timing = execute_decision(engine, _decision())
        assert out_ref is None
        assert timing.success is True

    def test_domain_error(self) -> None:
        engine = MagicMock(spec=DecisionEngine)
        engine.execute.side_effect = DecisionError("holyrics offline")

        with pytest.raises(PipelineError) as exc_info:
            execute_decision(engine, _decision())
        assert "holyrics" in str(exc_info.value)
        timing = exc_info.value.stage_timing
        assert timing.stage == "holyrics"
        assert timing.success is False
        assert "holyrics offline" in timing.error_msg

    def test_generic_error(self) -> None:
        engine = MagicMock(spec=DecisionEngine)
        engine.execute.side_effect = ConnectionError("network down")

        with pytest.raises(PipelineError) as exc_info:
            execute_decision(engine, _decision())
        assert "unexpected" in str(exc_info.value)
        timing = exc_info.value.stage_timing
        assert timing.success is False
        assert "network down" in timing.error_msg


# ---------------------------------------------------------------------------
# Integração real (sem mocks de DecisionEngine)
# ---------------------------------------------------------------------------


class TestRealDecisionEngine:
    """Testes de integração com DecisionEngine real."""

    def test_run_decision_real_engine(self) -> None:
        state_mgr = _state_manager()
        engine = DecisionEngine(_conf_config(), state_mgr, holyrics_client=None)
        intent = _intent(action="show", confidence=0.95)

        decision, timing = run_decision(engine, intent, c_stt=0.95)
        assert decision.outcome == "execute"
        assert timing.stage == "decision"
        assert timing.success is True
        assert timing.duration_ms >= 0.0

    def test_execute_decision_real_engine(self) -> None:
        state_mgr = _state_manager()
        engine = DecisionEngine(_conf_config(), state_mgr, holyrics_client=None)
        intent = _intent(action="show", confidence=0.95)

        decision, _ = run_decision(engine, intent, c_stt=0.95)
        ref, timing = execute_decision(engine, decision)
        assert ref is not None
        assert ref.book == "João"
        assert ref.chapter == 3
        assert ref.verse == 16
        assert timing.stage == "holyrics"
        assert timing.success is True

    def test_run_decision_ignores_low_c_stt(self) -> None:
        state_mgr = _state_manager()
        engine = DecisionEngine(_conf_config(), state_mgr)
        intent = _intent(action="show", confidence=0.95)

        decision, timing = run_decision(engine, intent, c_stt=0.1)
        assert decision.outcome == "ignore"
        assert timing.success is True


# ---------------------------------------------------------------------------
# StageTiming em erros — verificação de integridade
# ---------------------------------------------------------------------------


class TestStageTimingOnError:
    """Verifica que StageTiming anexado ao PipelineError é válido."""

    def test_timing_has_positive_duration_on_error(self) -> None:
        parser = MagicMock()
        parser.parse.side_effect = StateError("fail")

        with pytest.raises(PipelineError) as exc_info:
            run_parser(parser, "joão")
        timing = exc_info.value.stage_timing
        assert timing.duration_ms >= 0.0

    def test_timing_error_msg_matches_exception(self) -> None:
        searcher = MagicMock()
        from busca.exceptions import SearchError

        searcher.search.side_effect = SearchError("specific error msg")

        with pytest.raises(PipelineError) as exc_info:
            run_search(searcher, "query")
        timing = exc_info.value.stage_timing
        assert "specific error msg" in timing.error_msg

    def test_pipeline_error_is_ailyrics_error(self) -> None:
        parser = MagicMock()
        parser.parse.side_effect = StateError("fail")

        with pytest.raises(PipelineError) as exc_info:
            run_parser(parser, "x")
        assert isinstance(exc_info.value, AILyricsError)
