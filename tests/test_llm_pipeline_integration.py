"""Testes de integração LLM + Pipeline.

Testa o fluxo completo do orquestrador quando o parser retorna
``action="uncertain"`` e o LLM é injetado. Usa mocks para o LLMClient
— não requer Ollama rodando.

Casos obrigatórios:
  1. uncertain → LLM retorna search → Searcher chamado
  2. uncertain → LLM retorna show → Decision segue fluxo normal
  3. uncertain → LLM retorna none → pipeline ignora segmento
  4. uncertain → LLM offline (None) → forward_to_llm preservado
  5. uncertain → LLM retorna uncertain → conversão para none
  6. Parser resolve normalmente → LLM nunca chamado
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from busca.searcher import SearchResult
from config.models import ConfidenceConfig
from core.decision import DecisionEngine
from core.pipeline_metrics import PipelineMetrics
from core.pipeline_orchestrator import PipelineOrchestrator
from core.types import Intent, Utterance, VerseRef
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
        chapter_counts={43: 21, 1: 50, 45: 16, 49: 13},
        verse_counts={
            (43, 3): 36, (1, 1): 31, (45, 8): 39, (49, 11): 40,
        },
    )


def _book_names() -> dict[int, str]:
    return {43: "João", 1: "Gênesis", 45: "Romanos", 49: "Hebreus"}


def _state_manager() -> BibleStateManager:
    return BibleStateManager(
        structure=_structure(),
        book_names=_book_names(),
        default_version="ACF",
    )


def _search_result(
    book: str = "Romanos",
    book_id: int = 45,
    chapter: int = 8,
    verse: int = 28,
    score: float = 0.95,
    c_search: float = 0.9,
    ambiguous: bool = False,
) -> SearchResult:
    return SearchResult(
        reference=f"{book} {chapter}:{verse}",
        book=book,
        book_id=book_id,
        chapter=chapter,
        verse=verse,
        text="Todas as coisas cooperam para o bem...",
        version="ACF",
        score=score,
        c_search=c_search,
        ambiguous=ambiguous,
        match_type="fts",
    )


def _utterance(
    text: str = "aquele texto que diz que todas as coisas cooperam para o bem",
    c_stt: float = 0.90,
) -> Utterance:
    return Utterance(text=text, c_stt=c_stt, audio_ms=2000)


def _mock_parser(intent: Intent) -> MagicMock:
    parser = MagicMock()
    parser.parse.return_value = intent
    return parser


def _mock_searcher(results: list[SearchResult] | None = None) -> MagicMock:
    searcher = MagicMock()
    searcher.search.return_value = results if results is not None else [
        _search_result()
    ]
    return searcher


def _mock_llm(intent: Intent) -> MagicMock:
    llm = MagicMock()
    llm.interpret.return_value = intent
    llm.is_available.return_value = True
    return llm


def _real_engine(
    state_mgr: BibleStateManager | None = None,
    holyrics: MagicMock | None = None,
) -> DecisionEngine:
    return DecisionEngine(
        _conf_config(),
        state_mgr or _state_manager(),
        holyrics_client=holyrics,
    )


def _intent_uncertain(confidence: float = 0.0) -> Intent:
    return Intent(
        action="uncertain",
        confidence=confidence,
        source="parser",
        raw="aquele texto",
    )


def _intent_search(query: str = "todas as coisas cooperam para o bem") -> Intent:
    return Intent(
        action="search",
        query=query,
        confidence=0.92,
        source="llm",
        raw="aquele texto",
    )


def _intent_show(
    book: str = "Hebreus",
    book_id: int = 49,
    chapter: int = 11,
    verse: int = 1,
) -> Intent:
    return Intent(
        action="show",
        book=book,
        book_id=book_id,
        chapter=chapter,
        verse=verse,
        confidence=0.98,
        source="llm",
        raw="abre hebreus 11 1",
    )


def _intent_none() -> Intent:
    return Intent(
        action="none",
        confidence=0.0,
        source="llm",
        raw="texto irreconhecível",
    )


def _intent_show_parser() -> Intent:
    return Intent(
        action="show",
        book="João",
        book_id=43,
        chapter=3,
        verse=16,
        confidence=0.95,
        source="parser",
        raw="joão 3 16",
    )


# ---------------------------------------------------------------------------
# Caso 1: uncertain → LLM retorna search → Searcher chamado
# ---------------------------------------------------------------------------


class TestUncertainLLMReturnsSearch:
    """Parser uncertain → LLM retorna search → Searcher deve ser chamado."""

    def test_searcher_is_called(self) -> None:
        parser = _mock_parser(_intent_uncertain())
        searcher = _mock_searcher([_search_result()])
        llm = _mock_llm(_intent_search())
        orch = PipelineOrchestrator(
            parser, searcher, _real_engine(), _state_manager(),
            llm_client=llm,
        )
        entry = orch.process_utterance(_utterance())

        # LLM foi chamado
        llm.interpret.assert_called_once()
        # Searcher foi chamado com a query do LLM
        searcher.search.assert_called_once()
        call_args = searcher.search.call_args
        query = call_args[0][0] if call_args[0] else call_args[1].get("query", "")
        assert "todas as coisas cooperam" in query

    def test_llm_dict_populated(self) -> None:
        parser = _mock_parser(_intent_uncertain())
        searcher = _mock_searcher([_search_result()])
        llm = _mock_llm(_intent_search())
        orch = PipelineOrchestrator(
            parser, searcher, _real_engine(), _state_manager(),
            llm_client=llm,
        )
        entry = orch.process_utterance(_utterance())

        assert entry.llm.get("action") == "search"
        assert entry.llm.get("confidence") == 0.92
        assert entry.llm.get("source") == "llm"
        assert "todas as coisas cooperam" in entry.llm.get("query", "")

    def test_metrics_recorded(self) -> None:
        parser = _mock_parser(_intent_uncertain())
        searcher = _mock_searcher([_search_result()])
        llm = _mock_llm(_intent_search())
        metrics = PipelineMetrics()
        orch = PipelineOrchestrator(
            parser, searcher, _real_engine(), _state_manager(),
            metrics=metrics, llm_client=llm,
        )
        orch.process_utterance(_utterance())

        assert metrics.llm_calls == 1
        assert metrics.llm_success == 1
        assert metrics.llm_failures == 0
        assert metrics.llm_avg_latency_ms > 0


# ---------------------------------------------------------------------------
# Caso 2: uncertain → LLM retorna show → Decision segue fluxo normal
# ---------------------------------------------------------------------------


class TestUncertainLLMReturnsShow:
    """Parser uncertain → LLM retorna show → Decision deve seguir fluxo normal."""

    def test_decision_executes(self) -> None:
        holyrics = MagicMock()
        state_mgr = _state_manager()
        parser = _mock_parser(_intent_uncertain())
        llm = _mock_llm(_intent_show())
        orch = PipelineOrchestrator(
            parser, _mock_searcher(),
            _real_engine(state_mgr=state_mgr, holyrics=holyrics),
            state_mgr, llm_client=llm,
        )
        entry = orch.process_utterance(_utterance(c_stt=0.95))

        # LLM foi chamado
        llm.interpret.assert_called_once()
        # Decision deve ter executado (c_stt alta + c_intent alta)
        assert entry.decision["outcome"] == "execute"
        # Holyrics foi chamado
        assert entry.holyrics.get("ref") is not None

    def test_searcher_not_called(self) -> None:
        parser = _mock_parser(_intent_uncertain())
        searcher = _mock_searcher()
        llm = _mock_llm(_intent_show())
        orch = PipelineOrchestrator(
            parser, searcher, _real_engine(), _state_manager(),
            llm_client=llm,
        )
        orch.process_utterance(_utterance())

        # Searcher não deve ser chamado para action="show"
        searcher.search.assert_not_called()


# ---------------------------------------------------------------------------
# Caso 3: uncertain → LLM retorna none → pipeline ignora segmento
# ---------------------------------------------------------------------------


class TestUncertainLLMReturnsNone:
    """Parser uncertain → LLM retorna none → pipeline deve ignorar."""

    def test_outcome_is_ignore(self) -> None:
        parser = _mock_parser(_intent_uncertain())
        llm = _mock_llm(_intent_none())
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager(),
            llm_client=llm,
        )
        entry = orch.process_utterance(_utterance())

        assert entry.decision["outcome"] == "ignore"
        assert entry.llm.get("action") == "none"
        assert entry.llm.get("confidence") == 0.0

    def test_no_holyrics_execution(self) -> None:
        holyrics = MagicMock()
        parser = _mock_parser(_intent_uncertain())
        llm = _mock_llm(_intent_none())
        orch = PipelineOrchestrator(
            parser, _mock_searcher(),
            _real_engine(holyrics=holyrics), _state_manager(),
            llm_client=llm,
        )
        orch.process_utterance(_utterance())

        # Holyrics não deve ser chamado
        holyrics.show_verse.assert_not_called()

    def test_searcher_not_called(self) -> None:
        parser = _mock_parser(_intent_uncertain())
        searcher = _mock_searcher()
        llm = _mock_llm(_intent_none())
        orch = PipelineOrchestrator(
            parser, searcher, _real_engine(), _state_manager(),
            llm_client=llm,
        )
        orch.process_utterance(_utterance())

        searcher.search.assert_not_called()


# ---------------------------------------------------------------------------
# Caso 4: uncertain → LLM offline (None) → forward_to_llm preservado
# ---------------------------------------------------------------------------


class TestUncertainLLMOffline:
    """Parser uncertain → LLM não disponível → forward_to_llm preservado."""

    def test_forward_to_llm_preserved(self) -> None:
        parser = _mock_parser(_intent_uncertain())
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager(),
            llm_client=None,  # LLM não disponível
        )
        entry = orch.process_utterance(_utterance())

        assert entry.decision["outcome"] == "forward_to_llm"
        assert entry.llm.get("skipped") is True
        assert entry.llm.get("reason") == "llm_not_available"

    def test_no_llm_metrics(self) -> None:
        parser = _mock_parser(_intent_uncertain())
        metrics = PipelineMetrics()
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager(),
            metrics=metrics, llm_client=None,
        )
        orch.process_utterance(_utterance())

        assert metrics.llm_calls == 0


# ---------------------------------------------------------------------------
# Caso 5: uncertain → LLM retorna uncertain → conversão para none
# ---------------------------------------------------------------------------


class TestUncertainLLMReturnsUncertain:
    """Parser uncertain → LLM retorna uncertain → converter para none."""

    def test_converted_to_none(self) -> None:
        parser = _mock_parser(_intent_uncertain())
        # LLM retorna uncertain (não deveria, mas pode acontecer)
        llm_uncertain = _mock_llm(Intent(
            action="uncertain",
            confidence=0.5,
            source="llm",
            raw="texto ambíguo",
        ))
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager(),
            llm_client=llm_uncertain,
        )
        entry = orch.process_utterance(_utterance())

        # Deve ser convertido para none e ignorado
        assert entry.decision["outcome"] == "ignore"
        assert entry.llm.get("action") == "none"

    def test_no_loop(self) -> None:
        """Garante que LLM é chamado apenas uma vez (não há loop)."""
        parser = _mock_parser(_intent_uncertain())
        llm_uncertain = _mock_llm(Intent(
            action="uncertain",
            confidence=0.5,
            source="llm",
            raw="texto",
        ))
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager(),
            llm_client=llm_uncertain,
        )
        orch.process_utterance(_utterance())

        # LLM chamado exatamente 1 vez (não 2, não 3)
        assert llm_uncertain.interpret.call_count == 1


# ---------------------------------------------------------------------------
# Caso 6: Parser resolve normalmente → LLM nunca chamado
# ---------------------------------------------------------------------------


class TestParserResolvedLLMNotCalled:
    """Parser resolve → LLM nunca deve ser chamado."""

    def test_llm_not_called_for_show(self) -> None:
        parser = _mock_parser(_intent_show_parser())
        llm = _mock_llm(_intent_search())  # nunca deve ser usado
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager(),
            llm_client=llm,
        )
        entry = orch.process_utterance(_utterance("joão 3 16"))

        llm.interpret.assert_not_called()
        assert entry.llm.get("skipped") is True
        assert entry.llm.get("reason") == "parser_resolved"

    def test_llm_not_called_for_next(self) -> None:
        parser = _mock_parser(Intent(
            action="next", confidence=0.99, source="parser", raw="próximo",
        ))
        llm = _mock_llm(_intent_search())
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager(),
            llm_client=llm,
        )
        orch.process_utterance(_utterance("próximo"))

        llm.interpret.assert_not_called()

    def test_llm_not_called_for_none(self) -> None:
        parser = _mock_parser(Intent(
            action="none", confidence=0.0, source="parser", raw="olá",
        ))
        llm = _mock_llm(_intent_search())
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager(),
            llm_client=llm,
        )
        orch.process_utterance(_utterance("olá"))

        llm.interpret.assert_not_called()


# ---------------------------------------------------------------------------
# Testes de métricas LLM
# ---------------------------------------------------------------------------


class TestLLMMetrics:
    """Testa métricas derivadas de LLM no PipelineMetrics."""

    def test_llm_metrics_after_successful_call(self) -> None:
        parser = _mock_parser(_intent_uncertain())
        llm = _mock_llm(_intent_search())
        metrics = PipelineMetrics()
        orch = PipelineOrchestrator(
            parser, _mock_searcher([_search_result()]),
            _real_engine(), _state_manager(),
            metrics=metrics, llm_client=llm,
        )
        orch.process_utterance(_utterance())

        assert metrics.llm_calls == 1
        assert metrics.llm_success == 1
        assert metrics.llm_failures == 0
        assert metrics.llm_avg_latency_ms >= 0

    def test_llm_metrics_after_multiple_calls(self) -> None:
        parser = _mock_parser(_intent_uncertain())
        llm = _mock_llm(_intent_search())
        metrics = PipelineMetrics()
        orch = PipelineOrchestrator(
            parser, _mock_searcher([_search_result()]),
            _real_engine(), _state_manager(),
            metrics=metrics, llm_client=llm,
        )
        for _ in range(3):
            orch.process_utterance(_utterance())

        assert metrics.llm_calls == 3
        assert metrics.llm_success == 3

    def test_llm_metrics_zero_when_not_called(self) -> None:
        parser = _mock_parser(_intent_show_parser())
        metrics = PipelineMetrics()
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager(),
            metrics=metrics, llm_client=_mock_llm(_intent_search()),
        )
        orch.process_utterance(_utterance("joão 3 16"))

        assert metrics.llm_calls == 0
        assert metrics.llm_success == 0
        assert metrics.llm_failures == 0
        assert metrics.llm_avg_latency_ms == 0.0


# ---------------------------------------------------------------------------
# Testes de LogEntry LLM
# ---------------------------------------------------------------------------


class TestLLMLogEntry:
    """Testa o bloco LLM no LogEntry."""

    def test_llm_dict_when_called(self) -> None:
        parser = _mock_parser(_intent_uncertain())
        llm = _mock_llm(_intent_search())
        orch = PipelineOrchestrator(
            parser, _mock_searcher([_search_result()]),
            _real_engine(), _state_manager(), llm_client=llm,
        )
        entry = orch.process_utterance(_utterance())

        assert "duration_ms" in entry.llm
        assert entry.llm["success"] is True
        assert entry.llm["action"] == "search"
        assert entry.llm["confidence"] == 0.92
        assert entry.llm["source"] == "llm"
        assert "query" in entry.llm

    def test_llm_dict_when_skipped_parser_resolved(self) -> None:
        parser = _mock_parser(_intent_show_parser())
        llm = _mock_llm(_intent_search())
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager(),
            llm_client=llm,
        )
        entry = orch.process_utterance(_utterance("joão 3 16"))

        assert entry.llm.get("skipped") is True
        assert entry.llm.get("reason") == "parser_resolved"

    def test_llm_dict_when_skipped_not_available(self) -> None:
        parser = _mock_parser(_intent_uncertain())
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager(),
            llm_client=None,
        )
        entry = orch.process_utterance(_utterance())

        assert entry.llm.get("skipped") is True
        assert entry.llm.get("reason") == "llm_not_available"

    def test_llm_dict_empty_when_no_llm_and_parser_resolved(self) -> None:
        """Quando llm_client=None e parser resolve, llm dict fica vazio."""
        parser = _mock_parser(_intent_show_parser())
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager(),
            llm_client=None,
        )
        entry = orch.process_utterance(_utterance("joão 3 16"))

        # Parser resolveu e LLM não está disponível → llm vazio
        assert entry.llm == {}
