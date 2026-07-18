"""Testes unitários do módulo core/pipeline_orchestrator.py.

Estratégia:
  - Testa-se o fluxo completo com mocks das dependências.
  - Testa-se cada action (show, search, next, none, uncertain).
  - Testa-se erros em cada stage (parser, search, decision, execute).
  - Verifica-se que LogEntry é sempre produzida.
  - Verifica-se que PipelineMetrics é atualizada corretamente.
  - 100% determinístico.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from busca.searcher import SearchResult
from config.models import ConfidenceConfig
from core.decision import DecisionEngine
from core.exceptions import PipelineError, StateError
from core.pipeline_metrics import PipelineMetrics, StageTiming
from core.pipeline_orchestrator import PipelineOrchestrator
from core.types import Confidence, Decision, Intent, LogEntry, Utterance, VerseRef
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
    query: str | None = None,
) -> Intent:
    return Intent(
        action=action,
        book=book,
        book_id=book_id,
        chapter=chapter,
        verse=verse,
        confidence=confidence,
        query=query,
        raw="joão 3 16",
    )


def _utterance(
    text: str = "joão 3 16",
    c_stt: float = 0.95,
    audio_ms: int = 2000,
) -> Utterance:
    return Utterance(text=text, c_stt=c_stt, audio_ms=audio_ms)


def _mock_parser(intent: Intent | None = None) -> MagicMock:
    parser = MagicMock()
    parser.parse.return_value = intent or _intent()
    return parser


def _mock_searcher(results: list[SearchResult] | None = None) -> MagicMock:
    searcher = MagicMock()
    searcher.search.return_value = results if results is not None else [
        _search_result()
    ]
    return searcher


def _real_engine(
    state_mgr: BibleStateManager | None = None,
    holyrics: MagicMock | None = None,
) -> DecisionEngine:
    return DecisionEngine(
        _conf_config(),
        state_mgr or _state_manager(),
        holyrics_client=holyrics,
    )


# ---------------------------------------------------------------------------
# Testes básicos
# ---------------------------------------------------------------------------


class TestProcessUtteranceBasic:
    """Testes básicos de process_utterance."""

    def test_returns_log_entry(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(), _real_engine(), _state_manager()
        )
        entry = orch.process_utterance(_utterance())
        assert isinstance(entry, LogEntry)

    def test_log_entry_has_required_fields(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(), _real_engine(), _state_manager()
        )
        entry = orch.process_utterance(_utterance())
        assert entry.ts
        assert entry.id
        assert entry.audio_ms == 2000
        assert entry.total_ms >= 0
        assert isinstance(entry.parser, dict)
        assert isinstance(entry.search, dict)
        assert isinstance(entry.decision, dict)
        assert isinstance(entry.holyrics, dict)
        assert isinstance(entry.confidence, dict)
        assert isinstance(entry.stt, dict)
        assert isinstance(entry.llm, dict)
        assert isinstance(entry.cache, dict)

    def test_log_entry_id_is_unique(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(), _real_engine(), _state_manager()
        )
        e1 = orch.process_utterance(_utterance())
        e2 = orch.process_utterance(_utterance())
        assert e1.id != e2.id

    def test_log_entry_ts_is_iso(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(), _real_engine(), _state_manager()
        )
        entry = orch.process_utterance(_utterance())
        # ISO 8601 contém 'T' e timezone ou '+'
        assert "T" in entry.ts

    def test_metrics_updated_utterance(self) -> None:
        metrics = PipelineMetrics()
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(), _real_engine(),
            _state_manager(), metrics=metrics,
        )
        orch.process_utterance(_utterance())
        assert metrics.total_utterances == 1

    def test_custom_metrics_used(self) -> None:
        metrics = PipelineMetrics()
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(), _real_engine(),
            _state_manager(), metrics=metrics,
        )
        assert orch.metrics is metrics


# ---------------------------------------------------------------------------
# Fluxo: action == "show"
# ---------------------------------------------------------------------------


class TestActionShow:
    """Testes do fluxo quando action == "show"."""

    def test_show_executes(self) -> None:
        holyrics = MagicMock()
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="show")),
            _mock_searcher(),
            _real_engine(holyrics=holyrics),
            _state_manager(),
        )
        entry = orch.process_utterance(_utterance(c_stt=0.95))
        assert entry.decision["outcome"] == "execute"
        assert entry.holyrics.get("ref") == "João 3:16"
        assert orch.metrics.total_executes == 1

    def test_show_no_search_stage(self) -> None:
        """action=show não chama search."""
        searcher = _mock_searcher()
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="show")),
            searcher,
            _real_engine(),
            _state_manager(),
        )
        entry = orch.process_utterance(_utterance())
        # search dict deve estar vazio (não executado)
        assert entry.search == {}
        searcher.search.assert_not_called()

    def test_show_parser_timing_recorded(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="show")),
            _mock_searcher(),
            _real_engine(),
            _state_manager(),
        )
        orch.process_utterance(_utterance())
        assert orch.metrics.stage_count("parser") == 1
        assert orch.metrics.stage_errors("parser") == 0

    def test_show_decision_timing_recorded(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="show")),
            _mock_searcher(),
            _real_engine(),
            _state_manager(),
        )
        orch.process_utterance(_utterance())
        assert orch.metrics.stage_count("decision") == 1

    def test_show_holyrics_timing_recorded(self) -> None:
        holyrics = MagicMock()
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="show")),
            _mock_searcher(),
            _real_engine(holyrics=holyrics),
            _state_manager(),
        )
        orch.process_utterance(_utterance(c_stt=0.95))
        assert orch.metrics.stage_count("holyrics") == 1


# ---------------------------------------------------------------------------
# Fluxo: action == "search"
# ---------------------------------------------------------------------------


class TestActionSearch:
    """Testes do fluxo quando action == "search"."""

    def test_search_calls_searcher(self) -> None:
        searcher = _mock_searcher([_search_result()])
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="search", query="deus amou")),
            searcher,
            _real_engine(),
            _state_manager(),
        )
        entry = orch.process_utterance(_utterance(c_stt=0.95))
        searcher.search.assert_called_once()
        assert entry.search.get("results_count") == 1
        assert entry.search.get("top_reference") == "João 3:16"

    def test_search_timing_recorded(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="search", query="deus")),
            _mock_searcher([_search_result()]),
            _real_engine(),
            _state_manager(),
        )
        orch.process_utterance(_utterance(c_stt=0.95))
        assert orch.metrics.stage_count("search") == 1

    def test_search_executes_with_results(self) -> None:
        holyrics = MagicMock()
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="search", query="deus amou", confidence=0.98)),
            _mock_searcher([_search_result(c_search=0.98)]),
            _real_engine(holyrics=holyrics),
            _state_manager(),
        )
        entry = orch.process_utterance(_utterance(c_stt=0.98))
        # c_final = 0.98 * 0.98 * 0.98 = 0.941 >= min_execute=0.85
        assert entry.decision["outcome"] == "execute"
        assert entry.holyrics.get("ref") is not None

    def test_search_no_searcher_records_error(self) -> None:
        """action=search mas searcher=None → erro de search registrado."""
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="search", query="deus")),
            None,
            _real_engine(),
            _state_manager(),
        )
        entry = orch.process_utterance(_utterance(c_stt=0.95))
        assert orch.metrics.stage_errors("search") == 1
        assert entry.search.get("error") == "searcher not available"


# ---------------------------------------------------------------------------
# Fluxo: action == "none"
# ---------------------------------------------------------------------------


class TestActionNone:
    """Testes do fluxo quando action == "none"."""

    def test_none_ignored(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="none", confidence=0.0)),
            _mock_searcher(),
            _real_engine(),
            _state_manager(),
        )
        entry = orch.process_utterance(_utterance())
        assert entry.decision["outcome"] == "ignore"
        assert entry.holyrics == {}

    def test_none_no_search(self) -> None:
        searcher = _mock_searcher()
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="none")),
            searcher,
            _real_engine(),
            _state_manager(),
        )
        orch.process_utterance(_utterance())
        searcher.search.assert_not_called()

    def test_none_no_execute(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="none")),
            _mock_searcher(),
            _real_engine(),
            _state_manager(),
        )
        orch.process_utterance(_utterance())
        assert orch.metrics.total_executes == 0


# ---------------------------------------------------------------------------
# Fluxo: action == "uncertain"
# ---------------------------------------------------------------------------


class TestActionUncertain:
    """Testes do fluxo quando action == "uncertain"."""

    def test_uncertain_forwards_to_llm(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="uncertain", confidence=0.5)),
            _mock_searcher(),
            _real_engine(),
            _state_manager(),
        )
        entry = orch.process_utterance(_utterance(c_stt=0.9))
        assert entry.decision["outcome"] == "forward_to_llm"
        # LLM não disponível (llm_client=None) — llm dict indica skipped
        assert entry.llm.get("skipped") is True
        assert entry.llm.get("reason") == "llm_not_available"

    def test_uncertain_no_execute(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="uncertain")),
            _mock_searcher(),
            _real_engine(),
            _state_manager(),
        )
        orch.process_utterance(_utterance())
        assert orch.metrics.total_executes == 0


# ---------------------------------------------------------------------------
# Fluxo: action == "next"
# ---------------------------------------------------------------------------


class TestActionNext:
    """Testes do fluxo quando action == "next"."""

    def test_next_executes(self) -> None:
        holyrics = MagicMock()
        state_mgr = _state_manager()
        # Set initial state
        state_mgr.set(VerseRef(book_id=43, book="João", chapter=3, verse=16))
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="next", confidence=0.99)),
            _mock_searcher(),
            _real_engine(holyrics=holyrics, state_mgr=state_mgr),
            state_mgr,
        )
        entry = orch.process_utterance(_utterance(c_stt=0.95))
        assert entry.decision["outcome"] == "execute"
        assert entry.holyrics.get("ref") is not None


# ---------------------------------------------------------------------------
# Tratamento de erros por stage
# ---------------------------------------------------------------------------


class TestParserError:
    """Testes de erro no stage parser."""

    def test_parser_error_returns_log_entry(self) -> None:
        parser = MagicMock()
        parser.parse.side_effect = StateError("parse boom")
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager()
        )
        entry = orch.process_utterance(_utterance())
        assert isinstance(entry, LogEntry)
        assert entry.parser.get("success") is False
        assert "parse boom" in entry.parser.get("error", "")

    def test_parser_error_records_metric(self) -> None:
        parser = MagicMock()
        parser.parse.side_effect = StateError("fail")
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager()
        )
        orch.process_utterance(_utterance())
        assert orch.metrics.stage_errors("parser") == 1
        assert orch.metrics.total_errors == 1

    def test_parser_error_skips_subsequent_stages(self) -> None:
        parser = MagicMock()
        parser.parse.side_effect = StateError("fail")
        searcher = _mock_searcher()
        orch = PipelineOrchestrator(
            parser, searcher, _real_engine(), _state_manager()
        )
        orch.process_utterance(_utterance())
        # Search e decision não devem ser chamados
        searcher.search.assert_not_called()
        assert orch.metrics.stage_count("search") == 0
        assert orch.metrics.stage_count("decision") == 0


class TestSearchError:
    """Testes de erro no stage search."""

    def test_search_error_continues_pipeline(self) -> None:
        from busca.exceptions import SearchError

        searcher = MagicMock()
        searcher.search.side_effect = SearchError("fts failed")
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="search", query="deus")),
            searcher,
            _real_engine(),
            _state_manager(),
        )
        entry = orch.process_utterance(_utterance(c_stt=0.95))
        # Pipeline continua — decision recebe search_results=None
        assert isinstance(entry, LogEntry)
        assert entry.search.get("success") is False
        assert orch.metrics.stage_errors("search") == 1

    def test_search_error_decision_still_runs(self) -> None:
        from busca.exceptions import SearchError

        searcher = MagicMock()
        searcher.search.side_effect = SearchError("fail")
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="search", query="deus")),
            searcher,
            _real_engine(),
            _state_manager(),
        )
        orch.process_utterance(_utterance(c_stt=0.95))
        assert orch.metrics.stage_count("decision") == 1


class TestDecisionError:
    """Testes de erro no stage decision."""

    def test_decision_error_returns_log_entry(self) -> None:
        from core.exceptions import DecisionError

        engine = MagicMock()
        engine.evaluate.side_effect = DecisionError("bad intent")
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(), engine, _state_manager()
        )
        entry = orch.process_utterance(_utterance())
        assert isinstance(entry, LogEntry)
        assert entry.decision.get("success") is False
        assert "bad intent" in entry.decision.get("error", "")

    def test_decision_error_no_execute(self) -> None:
        from core.exceptions import DecisionError

        engine = MagicMock()
        engine.evaluate.side_effect = DecisionError("fail")
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(), engine, _state_manager()
        )
        orch.process_utterance(_utterance())
        assert orch.metrics.total_executes == 0
        assert orch.metrics.stage_count("holyrics") == 0


class TestExecuteError:
    """Testes de erro no stage execute (holyrics)."""

    def test_execute_error_records_metric(self) -> None:
        from core.exceptions import DecisionError

        engine = MagicMock()
        # evaluate retorna decision com outcome=execute
        engine.evaluate.return_value = Decision(
            action="show",
            outcome="execute",
            confidence=0.95,
            requires_confirmation=False,
            forward_to_llm=False,
            ignore=False,
            reason="ok",
            intent=_intent(),
            confidence_breakdown=Confidence(c_stt=0.95, c_intent=0.95),
        )
        engine.execute.side_effect = DecisionError("holyrics offline")
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(), engine, _state_manager()
        )
        entry = orch.process_utterance(_utterance(c_stt=0.95))
        assert orch.metrics.stage_errors("holyrics") == 1
        assert entry.holyrics.get("success") is False
        assert "holyrics offline" in entry.holyrics.get("error", "")


# ---------------------------------------------------------------------------
# LogEntry — estrutura detalhada
# ---------------------------------------------------------------------------


class TestLogEntryStructure:
    """Testes da estrutura detalhada da LogEntry."""

    def test_parser_dict_has_action_and_confidence(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="show", confidence=0.95)),
            _mock_searcher(),
            _real_engine(),
            _state_manager(),
        )
        entry = orch.process_utterance(_utterance())
        assert entry.parser["action"] == "show"
        assert entry.parser["confidence"] == 0.95

    def test_parser_dict_truncates_raw(self) -> None:
        long_raw = "x" * 1000
        parser = MagicMock()
        parser.parse.return_value = _intent(action="show")
        parser.parse.return_value.raw = long_raw
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager()
        )
        entry = orch.process_utterance(_utterance())
        assert len(entry.parser["raw"]) <= 500

    def test_confidence_dict_has_c_final(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="show", confidence=0.95)),
            _mock_searcher(),
            _real_engine(),
            _state_manager(),
        )
        entry = orch.process_utterance(_utterance(c_stt=0.95))
        assert "c_final" in entry.confidence
        assert entry.confidence["c_stt"] == 0.95
        assert entry.confidence["c_intent"] == 0.95

    def test_stt_dict_has_c_stt_and_audio_ms(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(), _real_engine(), _state_manager()
        )
        entry = orch.process_utterance(_utterance(c_stt=0.88, audio_ms=1500))
        assert entry.stt["c_stt"] == 0.88
        assert entry.stt["audio_ms"] == 1500

    def test_search_dict_has_top_score(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="search", query="deus")),
            _mock_searcher([_search_result(score=0.92)]),
            _real_engine(),
            _state_manager(),
        )
        entry = orch.process_utterance(_utterance(c_stt=0.95))
        assert entry.search["top_score"] == 0.92

    def test_total_ms_positive(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(), _real_engine(), _state_manager()
        )
        entry = orch.process_utterance(_utterance())
        assert entry.total_ms >= 0


# ---------------------------------------------------------------------------
# Integração real com DecisionEngine
# ---------------------------------------------------------------------------


class TestRealIntegration:
    """Testes de integração com DecisionEngine real (sem mocks de engine)."""

    def test_show_executes_with_real_engine(self) -> None:
        holyrics = MagicMock()
        state_mgr = _state_manager()
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="show", confidence=0.98)),
            _mock_searcher(),
            _real_engine(state_mgr=state_mgr, holyrics=holyrics),
            state_mgr,
        )
        entry = orch.process_utterance(_utterance(c_stt=0.98))
        assert entry.decision["outcome"] == "execute"
        assert entry.holyrics["ref"] == "João 3:16"
        holyrics.show_verse.assert_called_once()

    def test_low_c_stt_ignored(self) -> None:
        holyrics = MagicMock()
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="show", confidence=0.95)),
            _mock_searcher(),
            _real_engine(holyrics=holyrics),
            _state_manager(),
        )
        entry = orch.process_utterance(_utterance(c_stt=0.1))
        assert entry.decision["outcome"] == "ignore"
        holyrics.show_verse.assert_not_called()

    def test_multiple_utterances_accumulate_metrics(self) -> None:
        metrics = PipelineMetrics()
        holyrics = MagicMock()
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="show", confidence=0.95)),
            _mock_searcher(),
            _real_engine(holyrics=holyrics),
            _state_manager(),
            metrics=metrics,
        )
        for _ in range(5):
            orch.process_utterance(_utterance(c_stt=0.95))
        assert metrics.total_utterances == 5
        assert metrics.stage_count("parser") == 5
        assert metrics.stage_count("decision") == 5
        assert metrics.stage_count("holyrics") == 5
        assert metrics.total_executes == 5

    def test_snapshot_after_processing(self) -> None:
        metrics = PipelineMetrics()
        holyrics = MagicMock()
        orch = PipelineOrchestrator(
            _mock_parser(_intent(action="show", confidence=0.95)),
            _mock_searcher(),
            _real_engine(holyrics=holyrics),
            _state_manager(),
            metrics=metrics,
        )
        orch.process_utterance(_utterance(c_stt=0.95))
        snap = metrics.snapshot()
        assert snap.total_utterances == 1
        assert snap.total_executes == 1
        assert "parser" in snap.stage_counts
        assert "decision" in snap.stage_counts
