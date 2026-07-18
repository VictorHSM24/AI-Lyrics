"""Testes unitários do módulo core/decision.py.

Estratégia:
  - DecisionEngine.evaluate() é lógica pura — testável sem Holyrics/State.
  - DecisionEngine.execute() testa side effects com mocks.
  - Não requer rede, GPU, nem áudio.
  - 100% determinístico.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from busca.searcher import SearchResult
from config.models import ConfidenceConfig
from core.decision import DecisionEngine, DecisionMetrics, _clamp, _extract_search_confidence
from core.exceptions import DecisionError
from core.types import Confidence, Decision, Intent, VerseRef
from estado.state import BibleState, BibleStructure, BibleStateManager
from integracao_holyrics import HolyricsError


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
    """Estrutura bíblica mínima para testes."""
    return BibleStructure(
        chapter_counts={43: 21, 1: 50, 45: 16},
        verse_counts={
            (43, 3): 36,
            (1, 1): 31,
            (45, 8): 39,
        },
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
    book_id: int | None = 43,
    chapter: int | None = 3,
    verse: int | None = 16,
    confidence: float = 0.98,
    source: str = "parser",
    query: str | None = None,
) -> Intent:
    return Intent(
        action=action,  # type: ignore[arg-type]
        book="João" if book_id == 43 else None,
        book_id=book_id,
        chapter=chapter,
        verse=verse,
        confidence=confidence,
        source=source,  # type: ignore[arg-type]
        query=query,
        raw="teste",
    )


@pytest.fixture
def engine() -> DecisionEngine:
    """DecisionEngine sem Holyrics (dry-run)."""
    return DecisionEngine(
        confidence_config=_conf_config(),
        state_manager=_state_manager(),
        holyrics_client=None,
        mode="auto",
    )


@pytest.fixture
def engine_with_holyrics() -> DecisionEngine:
    """DecisionEngine com Holyrics mockado."""
    holyrics = MagicMock()
    holyrics.show_verse.return_value = MagicMock(status="ok")
    return DecisionEngine(
        confidence_config=_conf_config(),
        state_manager=_state_manager(),
        holyrics_client=holyrics,
        mode="auto",
    )


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

class TestClamp:
    def test_within_range(self) -> None:
        assert _clamp(0.5) == 0.5

    def test_below(self) -> None:
        assert _clamp(-0.5) == 0.0

    def test_above(self) -> None:
        assert _clamp(1.5) == 1.0

    def test_custom_range(self) -> None:
        assert _clamp(5, 0, 10) == 5


class TestExtractSearchConfidence:
    def test_empty(self) -> None:
        c, amb = _extract_search_confidence([])
        assert c == 1.0
        assert amb is False

    def test_non_ambiguous(self) -> None:
        results = [_search_result(c_search=0.9, ambiguous=False)]
        c, amb = _extract_search_confidence(results)
        assert c == 0.9
        assert amb is False

    def test_ambiguous(self) -> None:
        results = [_search_result(c_search=0.5, ambiguous=True)]
        c, amb = _extract_search_confidence(results)
        assert c == 0.5
        assert amb is True


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_defaults(self) -> None:
        c = Confidence()
        assert c.c_stt == 1.0
        assert c.c_intent == 1.0
        assert c.c_search == 1.0
        assert c.c_final == 1.0

    def test_multiplication(self) -> None:
        c = Confidence(c_stt=0.9, c_intent=0.8, c_search=0.7)
        assert abs(c.c_final - 0.504) < 0.001

    def test_zero_stt(self) -> None:
        c = Confidence(c_stt=0.0, c_intent=1.0, c_search=1.0)
        assert c.c_final == 0.0


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

class TestDecision:
    def test_construction(self) -> None:
        d = Decision(
            action="show",
            outcome="execute",
            confidence=0.96,
            requires_confirmation=False,
            forward_to_llm=False,
            ignore=False,
            reason="c_final=0.96 >= min_execute=0.85",
            intent=_intent(),
        )
        assert d.action == "show"
        assert d.outcome == "execute"
        assert d.confidence == 0.96
        assert d.requires_confirmation is False
        assert d.forward_to_llm is False
        assert d.ignore is False

    def test_mutable(self) -> None:
        """Decision é mutável (ref pode ser setado após construção)."""
        d = Decision(
            action="show", outcome="execute", confidence=0.9,
            requires_confirmation=False, forward_to_llm=False, ignore=False,
            reason="ok", intent=_intent(),
        )
        d.ref = VerseRef(book_id=43, book="João", chapter=3, verse=16)
        assert d.ref is not None
        assert d.ref.verse == 16


# ---------------------------------------------------------------------------
# DecisionMetrics
# ---------------------------------------------------------------------------

class TestDecisionMetrics:
    def test_defaults(self) -> None:
        m = DecisionMetrics()
        assert m.total_evaluations == 0
        assert m.avg_time_ms == 0.0

    def test_avg_time(self) -> None:
        m = DecisionMetrics()
        m.total_evaluations = 5
        m.total_time_ms = 50.0
        assert m.avg_time_ms == 10.0

    def test_reset(self) -> None:
        m = DecisionMetrics()
        m.total_evaluations = 10
        m.execute = 5
        m.reset()
        assert m.total_evaluations == 0
        assert m.execute == 0


# ---------------------------------------------------------------------------
# DecisionEngine — evaluate (pure logic)
# ---------------------------------------------------------------------------

class TestEvaluateShow:
    def test_show_high_confidence_execute(self, engine: DecisionEngine) -> None:
        """show com c_stt=0.9, c_intent=0.98 → execute (c_final=0.882)."""
        intent = _intent(action="show", confidence=0.98)
        decision = engine.evaluate(intent, c_stt=0.9)
        assert decision.outcome == "execute"
        assert decision.action == "show"
        assert decision.confidence == pytest.approx(0.882, abs=0.01)
        assert decision.requires_confirmation is False
        assert decision.forward_to_llm is False
        assert decision.ignore is False

    def test_show_medium_confidence_confirm(self, engine: DecisionEngine) -> None:
        """show com c_final em [0.60, 0.85) → confirm."""
        intent = _intent(action="show", confidence=0.75)
        decision = engine.evaluate(intent, c_stt=0.9)
        # c_final = 0.9 * 0.75 = 0.675 → confirm
        assert decision.outcome == "confirm"
        assert decision.requires_confirmation is True

    def test_show_low_confidence_ignore(self, engine: DecisionEngine) -> None:
        """show com c_final < 0.60 → ignore."""
        intent = _intent(action="show", confidence=0.5)
        decision = engine.evaluate(intent, c_stt=0.9)
        # c_final = 0.9 * 0.5 = 0.45 → ignore
        assert decision.outcome == "ignore"
        assert decision.ignore is True

    def test_show_perfect_confidence(self, engine: DecisionEngine) -> None:
        """show com c_stt=1.0, c_intent=1.0 → execute (c_final=1.0)."""
        intent = _intent(action="show", confidence=1.0)
        decision = engine.evaluate(intent, c_stt=1.0)
        assert decision.outcome == "execute"
        assert decision.confidence == 1.0


class TestEvaluateNext:
    def test_next_high_confidence_execute(self, engine: DecisionEngine) -> None:
        """next com alta confiança → execute."""
        intent = _intent(action="next", book_id=None, chapter=None, verse=None, confidence=0.98)
        decision = engine.evaluate(intent, c_stt=0.95)
        assert decision.outcome == "execute"
        assert decision.action == "next"

    def test_next_low_stt_ignore(self, engine: DecisionEngine) -> None:
        """next com c_stt baixo → ignore (antes de avaliar c_intent)."""
        intent = _intent(action="next", confidence=0.98)
        decision = engine.evaluate(intent, c_stt=0.3)
        assert decision.outcome == "ignore"
        assert "stt_min" in decision.reason


class TestEvaluateUncertain:
    def test_uncertain_forwards_to_llm(self, engine: DecisionEngine) -> None:
        """action=uncertain → forward_to_llm."""
        intent = _intent(action="uncertain", book_id=None, chapter=None, verse=None,
                         confidence=0.0, query="deus amou o mundo")
        decision = engine.evaluate(intent, c_stt=0.9)
        assert decision.outcome == "forward_to_llm"
        assert decision.forward_to_llm is True
        assert decision.ignore is False

    def test_uncertain_low_stt_ignored(self, engine: DecisionEngine) -> None:
        """action=uncertain com c_stt < stt_min → ignore (não forward)."""
        intent = _intent(action="uncertain", confidence=0.0)
        decision = engine.evaluate(intent, c_stt=0.3)
        assert decision.outcome == "ignore"
        assert decision.forward_to_llm is False


class TestEvaluateNone:
    def test_none_ignored(self, engine: DecisionEngine) -> None:
        """action=none → ignore direto."""
        intent = _intent(action="none", book_id=None, chapter=None, verse=None,
                         confidence=0.0)
        decision = engine.evaluate(intent, c_stt=0.95)
        assert decision.outcome == "ignore"
        assert decision.ignore is True
        assert "none" in decision.reason


class TestEvaluateSearch:
    def test_search_non_ambiguous_high_confidence_execute(
        self, engine: DecisionEngine
    ) -> None:
        """search com resultado não ambíguo e alta confiança → execute."""
        intent = _intent(action="search", book_id=None, chapter=None, verse=None,
                         confidence=0.9, query="deus amou o mundo")
        results = [_search_result(c_search=0.95, ambiguous=False)]
        decision = engine.evaluate(intent, c_stt=0.95, search_results=results)
        # c_final = 0.95 * 0.9 * 0.95 = 0.812 → confirm (não execute!)
        # 0.812 < 0.85 → confirm
        assert decision.outcome == "confirm"
        assert decision.requires_confirmation is True

    def test_search_non_ambiguous_very_high_confidence_execute(
        self, engine: DecisionEngine
    ) -> None:
        """search com c_final >= min_execute → execute."""
        intent = _intent(action="search", confidence=0.98, query="deus amou o mundo")
        results = [_search_result(c_search=0.98, ambiguous=False)]
        decision = engine.evaluate(intent, c_stt=0.98, search_results=results)
        # c_final = 0.98 * 0.98 * 0.98 = 0.941 → execute
        assert decision.outcome == "execute"

    def test_search_ambiguous_always_confirm(self, engine: DecisionEngine) -> None:
        """search ambíguo → confirm independentemente do score."""
        intent = _intent(action="search", confidence=0.98, query="fé")
        results = [_search_result(c_search=0.98, ambiguous=True)]
        decision = engine.evaluate(intent, c_stt=0.98, search_results=results)
        assert decision.outcome == "confirm"
        assert decision.requires_confirmation is True
        assert "ambiguous" in decision.reason.lower()

    def test_search_no_results_ambiguous(self, engine: DecisionEngine) -> None:
        """action=search sem search_results → tratado como ambíguo → confirm."""
        intent = _intent(action="search", confidence=0.9, query="xyz")
        decision = engine.evaluate(intent, c_stt=0.9, search_results=None)
        assert decision.outcome == "confirm"

    def test_search_empty_results_ambiguous(self, engine: DecisionEngine) -> None:
        """action=search com results=[] → c_search=1.0, não ambíguo."""
        intent = _intent(action="search", confidence=0.98, query="xyz")
        decision = engine.evaluate(intent, c_stt=0.98, search_results=[])
        # c_search=1.0, ambiguous=False → c_final = 0.98*0.98*1.0 = 0.96 → execute
        assert decision.outcome == "execute"


class TestEvaluateSttMin:
    def test_stt_below_min_ignored(self, engine: DecisionEngine) -> None:
        """c_stt < stt_min → ignore mesmo com c_intent alta."""
        intent = _intent(action="show", confidence=1.0)
        decision = engine.evaluate(intent, c_stt=0.3)
        assert decision.outcome == "ignore"
        assert "stt_min" in decision.reason

    def test_stt_exactly_min_not_ignored(self, engine: DecisionEngine) -> None:
        """c_stt == stt_min → não é ignorado (borderline)."""
        intent = _intent(action="show", confidence=1.0)
        decision = engine.evaluate(intent, c_stt=0.50)
        # c_stt=0.50 == stt_min=0.50 → não ignore
        # c_final = 0.50 * 1.0 = 0.50 → ignore (abaixo de min_confirm)
        # Mas o motivo é diferente: não é "stt too low"
        assert "stt_min" not in decision.reason


class TestEvaluateMode:
    def test_mode_confirm_forces_confirmation(self) -> None:
        """mode=confirm → execute vira confirm."""
        engine = DecisionEngine(
            confidence_config=_conf_config(),
            state_manager=_state_manager(),
            mode="confirm",
        )
        intent = _intent(action="show", confidence=1.0)
        decision = engine.evaluate(intent, c_stt=1.0)
        # c_final=1.0 >= min_execute → seria execute, mas mode=confirm → confirm
        assert decision.outcome == "confirm"
        assert "mode=confirm" in decision.reason

    def test_mode_auto_executes(self, engine: DecisionEngine) -> None:
        """mode=auto → execute se c_final >= min_execute."""
        intent = _intent(action="show", confidence=1.0)
        decision = engine.evaluate(intent, c_stt=1.0)
        assert decision.outcome == "execute"


# ---------------------------------------------------------------------------
# DecisionEngine — execute (side effects)
# ---------------------------------------------------------------------------

class TestExecute:
    def test_execute_show_calls_holyrics_and_state(
        self, engine_with_holyrics: DecisionEngine
    ) -> None:
        """execute com action=show → chama state.set() e holyrics.show_verse()."""
        intent = _intent(action="show", book_id=43, chapter=3, verse=16,
                         confidence=1.0)
        decision = engine_with_holyrics.evaluate(intent, c_stt=1.0)
        assert decision.outcome == "execute"

        ref = engine_with_holyrics.execute(decision)
        assert ref is not None
        assert ref.book_id == 43
        assert ref.chapter == 3
        assert ref.verse == 16

        # Verificar que Holyrics foi chamado
        engine_with_holyrics._holyrics.show_verse.assert_called_once()
        call_args = engine_with_holyrics._holyrics.show_verse.call_args
        assert call_args.kwargs["book_id"] == 43
        assert call_args.kwargs["chapter"] == 3
        assert call_args.kwargs["verse"] == 16

    def test_execute_next_uses_state_apply(
        self, engine_with_holyrics: DecisionEngine
    ) -> None:
        """execute com action=next → state.apply() resolve próximo versículo."""
        # Configurar state inicial em João 3:16
        engine_with_holyrics._state.set(VerseRef(
            book_id=43, book="João", chapter=3, verse=16, version="ACF"
        ))

        intent = _intent(action="next", book_id=None, chapter=None, verse=None,
                         confidence=1.0)
        decision = engine_with_holyrics.evaluate(intent, c_stt=1.0)
        assert decision.outcome == "execute"

        ref = engine_with_holyrics.execute(decision)
        assert ref is not None
        assert ref.verse == 17  # próximo após 16

    def test_execute_search_uses_top_result(
        self, engine_with_holyrics: DecisionEngine
    ) -> None:
        """execute com action=search → usa top-1 SearchResult."""
        intent = _intent(action="search", book_id=None, chapter=None, verse=None,
                         confidence=1.0, query="deus amou o mundo")
        results = [_search_result(book_id=43, chapter=3, verse=16, c_search=1.0)]
        decision = engine_with_holyrics.evaluate(intent, c_stt=1.0,
                                                  search_results=results)
        assert decision.outcome == "execute"

        ref = engine_with_holyrics.execute(decision, search_results=results)
        assert ref is not None
        assert ref.book_id == 43
        assert ref.chapter == 3
        assert ref.verse == 16

    def test_execute_dry_run_no_holyrics(self, engine: DecisionEngine) -> None:
        """execute sem Holyrics → atualiza state mas não chama Holyrics."""
        intent = _intent(action="show", confidence=1.0)
        decision = engine.evaluate(intent, c_stt=1.0)
        ref = engine.execute(decision)
        assert ref is not None
        assert ref.book_id == 43

    def test_execute_non_execute_raises(self, engine: DecisionEngine) -> None:
        """execute com outcome != execute → DecisionError."""
        intent = _intent(action="show", confidence=0.3)
        decision = engine.evaluate(intent, c_stt=0.9)
        assert decision.outcome == "ignore"

        with pytest.raises(DecisionError, match="cannot execute"):
            engine.execute(decision)

    def test_execute_holyrics_error_raises_decision_error(
        self, engine_with_holyrics: DecisionEngine
    ) -> None:
        """Erro do Holyrics → DecisionError."""
        engine_with_holyrics._holyrics.show_verse.side_effect = HolyricsError("conn failed")

        intent = _intent(action="show", confidence=1.0)
        decision = engine_with_holyrics.evaluate(intent, c_stt=1.0)
        with pytest.raises(DecisionError, match="holyrics error"):
            engine_with_holyrics.execute(decision)


# ---------------------------------------------------------------------------
# DecisionEngine — métricas
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_metrics_updated(self, engine: DecisionEngine) -> None:
        engine.evaluate(_intent(action="show", confidence=1.0), c_stt=1.0)
        engine.evaluate(_intent(action="show", confidence=0.5), c_stt=0.9)
        engine.evaluate(_intent(action="none", confidence=0.0), c_stt=0.9)

        assert engine.metrics.total_evaluations == 3
        assert engine.metrics.execute == 1
        assert engine.metrics.ignore >= 1
        assert engine.metrics.total_time_ms > 0

    def test_metrics_forward_to_llm(self, engine: DecisionEngine) -> None:
        engine.evaluate(_intent(action="uncertain", confidence=0.0), c_stt=0.9)
        assert engine.metrics.forward_to_llm == 1

    def test_metrics_confirm(self, engine: DecisionEngine) -> None:
        engine.evaluate(_intent(action="show", confidence=0.7), c_stt=0.9)
        assert engine.metrics.confirm == 1


# ---------------------------------------------------------------------------
# Cenários dos fluxos obrigatórios
# ---------------------------------------------------------------------------

class TestObligatoryFlows:
    """Testa os 5 fluxos obrigatórios do enunciado."""

    def test_flow1_parser_show_to_holyrics(
        self, engine_with_holyrics: DecisionEngine
    ) -> None:
        """Fluxo 1: Parser 'João 3:16' → show → Holyrics."""
        intent = _intent(action="show", book_id=43, chapter=3, verse=16,
                         confidence=0.98)
        decision = engine_with_holyrics.evaluate(intent, c_stt=0.95)
        assert decision.outcome == "execute"
        assert decision.action == "show"

        ref = engine_with_holyrics.execute(decision)
        assert ref is not None
        assert ref.reference == "João 3:16"
        engine_with_holyrics._holyrics.show_verse.assert_called_once()

    def test_flow2_next_uses_state(
        self, engine_with_holyrics: DecisionEngine
    ) -> None:
        """Fluxo 2: Parser 'next' + State João 3:16 → João 3:17 → Holyrics."""
        engine_with_holyrics._state.set(VerseRef(
            book_id=43, book="João", chapter=3, verse=16, version="ACF"
        ))

        intent = _intent(action="next", book_id=None, chapter=None, verse=None,
                         confidence=0.98)
        decision = engine_with_holyrics.evaluate(intent, c_stt=0.95)
        assert decision.outcome == "execute"

        ref = engine_with_holyrics.execute(decision)
        assert ref is not None
        assert ref.verse == 17
        engine_with_holyrics._holyrics.show_verse.assert_called_once()

    def test_flow3_uncertain_forwards_to_llm(self, engine: DecisionEngine) -> None:
        """Fluxo 3: Parser 'uncertain' + query → forward_to_llm."""
        intent = _intent(
            action="uncertain",
            book_id=None, chapter=None, verse=None,
            confidence=0.0,
            query="aquele texto que fala que Deus amou o mundo",
        )
        decision = engine.evaluate(intent, c_stt=0.9)
        assert decision.outcome == "forward_to_llm"
        assert decision.forward_to_llm is True
        assert decision.intent.query == "aquele texto que fala que Deus amou o mundo"

    def test_flow4_ambiguous_search_requests_confirmation(
        self, engine: DecisionEngine
    ) -> None:
        """Fluxo 4: SearchResult ambiguous → request_confirmation."""
        intent = _intent(action="search", confidence=0.98, query="fé")
        results = [_search_result(c_search=0.95, ambiguous=True)]
        decision = engine.evaluate(intent, c_stt=0.95, search_results=results)
        assert decision.outcome == "confirm"
        assert decision.requires_confirmation is True

    def test_flow5_low_confidence_ignored(self, engine: DecisionEngine) -> None:
        """Fluxo 5: confidence abaixo do limite → ignore."""
        intent = _intent(action="show", confidence=0.3)
        decision = engine.evaluate(intent, c_stt=0.9)
        # c_final = 0.9 * 0.3 = 0.27 < 0.60 → ignore
        assert decision.outcome == "ignore"
        assert decision.ignore is True


# ---------------------------------------------------------------------------
# Determinismo
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_inputs_same_output(self, engine: DecisionEngine) -> None:
        """Mesmas entradas → mesma Decision (100% determinístico)."""
        intent = _intent(action="show", confidence=0.85)
        d1 = engine.evaluate(intent, c_stt=0.9)
        d2 = engine.evaluate(intent, c_stt=0.9)
        assert d1.outcome == d2.outcome
        assert d1.confidence == d2.confidence
        assert d1.reason == d2.reason

    def test_different_stt_different_outcome(self, engine: DecisionEngine) -> None:
        """c_stt diferente → outcome pode mudar."""
        intent = _intent(action="show", confidence=0.89)
        d_high = engine.evaluate(intent, c_stt=0.95)
        d_low = engine.evaluate(intent, c_stt=0.5)
        # c_final high = 0.95*0.89 = 0.8455 → execute (>= min_execute=0.85? 0.8455 < 0.85 → confirm)
        # c_final low = 0.5*0.89 = 0.445 → ignore
        assert d_high.outcome in ("execute", "confirm")
        assert d_low.outcome == "ignore"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_clamp_confidence_above_1(self, engine: DecisionEngine) -> None:
        """c_stt > 1.0 → clamp para 1.0."""
        intent = _intent(action="show", confidence=1.0)
        decision = engine.evaluate(intent, c_stt=1.5)
        assert decision.confidence <= 1.0

    def test_clamp_confidence_below_0(self, engine: DecisionEngine) -> None:
        """c_stt < 0.0 → clamp para 0.0."""
        intent = _intent(action="show", confidence=1.0)
        decision = engine.evaluate(intent, c_stt=-0.5)
        assert decision.outcome == "ignore"

    def test_confidence_breakdown_present(self, engine: DecisionEngine) -> None:
        """Decision deve ter confidence_breakdown preenchido."""
        intent = _intent(action="show", confidence=0.9)
        decision = engine.evaluate(intent, c_stt=0.95)
        assert decision.confidence_breakdown is not None
        assert decision.confidence_breakdown.c_stt == 0.95
        assert decision.confidence_breakdown.c_intent == 0.9
        assert decision.confidence_breakdown.c_search == 1.0

    def test_search_confidence_breakdown(self, engine: DecisionEngine) -> None:
        """Search Decision deve ter c_search no breakdown."""
        intent = _intent(action="search", confidence=0.9, query="deus")
        results = [_search_result(c_search=0.85, ambiguous=False)]
        decision = engine.evaluate(intent, c_stt=0.9, search_results=results)
        assert decision.confidence_breakdown is not None
        assert decision.confidence_breakdown.c_search == 0.85

    def test_reason_is_human_readable(self, engine: DecisionEngine) -> None:
        """Reason deve ser string não-vazia e legível."""
        intent = _intent(action="show", confidence=0.89)
        decision = engine.evaluate(intent, c_stt=0.95)
        assert len(decision.reason) > 5
        assert "c_final" in decision.reason or "min_execute" in decision.reason


# ---------------------------------------------------------------------------
# Bypass de referências explícitas de alta confiança
# ---------------------------------------------------------------------------


class TestExplicitReferenceBypass:
    """Testa o bypass que executa referências explícitas (action=show)
    com alta confiança do parser, independentemente do c_stt (desde que
    c_stt >= stt_min).

    Motivação: o Whisper tem confiança naturalmente baixa para frases
    curtas como "João 3:16" (c_stt ~0.30). Se o parser reconheceu a
    referência com alta confiança e todos os campos estão presentes,
    o c_stt não deve impedir a execução.
    """

    def test_bypass_executes_with_low_stt(self, engine: DecisionEngine) -> None:
        """show + c_intent=0.95 + c_stt=0.55 (>= stt_min=0.50) → execute.

        Sem bypass: c_final = 0.55*0.95 = 0.5225 < min_execute=0.85 → confirm.
        Com bypass: execute (explicit_reference_high_confidence).
        """
        intent = _intent(action="show", confidence=0.95)
        decision = engine.evaluate(intent, c_stt=0.55)
        assert decision.outcome == "execute"
        assert decision.reason == "explicit_reference_high_confidence"

    def test_bypass_executes_with_very_low_stt_above_min(self, engine: DecisionEngine) -> None:
        """show + c_intent=0.98 + c_stt=0.51 (acima de stt_min=0.50) → execute."""
        intent = _intent(action="show", confidence=0.98)
        decision = engine.evaluate(intent, c_stt=0.51)
        assert decision.outcome == "execute"
        assert "explicit_reference" in decision.reason

    def test_bypass_does_not_apply_below_stt_min(self, engine: DecisionEngine) -> None:
        """show + c_intent=0.95 + c_stt=0.30 (< stt_min=0.50) → ignore.

        O stt_min continua protegendo contra lixo de áudio.
        O bypass não se aplica porque c_stt < stt_min (step 2 retorna antes).
        """
        intent = _intent(action="show", confidence=0.95)
        decision = engine.evaluate(intent, c_stt=0.30)
        assert decision.outcome == "ignore"
        assert "stt_min" in decision.reason

    def test_bypass_does_not_apply_low_intent(self, engine: DecisionEngine) -> None:
        """show + c_intent=0.85 (< parser_high=0.90) → fluxo normal.

        Sem bypass: c_final = 0.9*0.85 = 0.765 → confirm.
        """
        intent = _intent(action="show", confidence=0.85)
        decision = engine.evaluate(intent, c_stt=0.90)
        assert decision.outcome == "confirm"
        assert "explicit_reference" not in decision.reason

    def test_bypass_does_not_apply_intent_at_boundary_below(self, engine: DecisionEngine) -> None:
        """show + c_intent=0.89 (< parser_high=0.90) → fluxo normal."""
        intent = _intent(action="show", confidence=0.89)
        decision = engine.evaluate(intent, c_stt=0.95)
        assert "explicit_reference" not in decision.reason

    def test_bypass_applies_at_exact_boundary(self, engine: DecisionEngine) -> None:
        """show + c_intent=0.90 (== parser_high=0.90) → execute (>= é inclusivo)."""
        intent = _intent(action="show", confidence=0.90)
        decision = engine.evaluate(intent, c_stt=0.55)
        assert decision.outcome == "execute"
        assert "explicit_reference" in decision.reason

    def test_bypass_does_not_apply_missing_book(self, engine: DecisionEngine) -> None:
        """show + book=None → fluxo normal (bypass exige book presente)."""
        intent = _intent(action="show", book_id=43, chapter=3, verse=16, confidence=0.95)
        intent = Intent(
            action="show", book=None, book_id=43, chapter=3, verse=16,
            confidence=0.95, source="parser", raw="teste",
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert "explicit_reference" not in decision.reason

    def test_bypass_does_not_apply_missing_chapter(self, engine: DecisionEngine) -> None:
        """show + chapter=None → fluxo normal (bypass exige chapter presente)."""
        intent = Intent(
            action="show", book="João", book_id=43, chapter=None, verse=16,
            confidence=0.95, source="parser", raw="teste",
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert "explicit_reference" not in decision.reason

    def test_bypass_does_not_apply_missing_verse(self, engine: DecisionEngine) -> None:
        """show + verse=None → fluxo normal (bypass exige verse presente)."""
        intent = Intent(
            action="show", book="João", book_id=43, chapter=3, verse=None,
            confidence=0.95, source="parser", raw="teste",
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert "explicit_reference" not in decision.reason

    def test_bypass_does_not_apply_to_next(self, engine: DecisionEngine) -> None:
        """next + c_intent=0.95 → fluxo normal (bypass só para show)."""
        intent = _intent(
            action="next", book_id=None, chapter=None, verse=None, confidence=0.95,
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert "explicit_reference" not in decision.reason

    def test_bypass_does_not_apply_to_previous(self, engine: DecisionEngine) -> None:
        """previous + c_intent=0.95 → fluxo normal."""
        intent = _intent(
            action="previous", book_id=None, chapter=None, verse=None, confidence=0.95,
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert "explicit_reference" not in decision.reason

    def test_bypass_does_not_apply_to_search(self, engine: DecisionEngine) -> None:
        """search + c_intent=0.95 → fluxo normal (bypass só para show)."""
        intent = _intent(action="search", confidence=0.95, query="deus amou")
        decision = engine.evaluate(intent, c_stt=0.55)
        assert "explicit_reference" not in decision.reason

    def test_bypass_does_not_apply_to_uncertain(self, engine: DecisionEngine) -> None:
        """uncertain → forward_to_llm (bypass não se aplica)."""
        intent = _intent(
            action="uncertain", book_id=None, chapter=None, verse=None,
            confidence=0.95, query="teste",
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert decision.outcome == "forward_to_llm"
        assert "explicit_reference" not in decision.reason

    def test_bypass_mode_confirm_still_confirms(self) -> None:
        """bypass + mode=confirm → confirm (mode respeitado)."""
        engine = DecisionEngine(
            confidence_config=_conf_config(),
            state_manager=_state_manager(),
            holyrics_client=None,
            mode="confirm",
        )
        intent = _intent(action="show", confidence=0.95)
        decision = engine.evaluate(intent, c_stt=0.55)
        assert decision.outcome == "confirm"
        assert decision.requires_confirmation is True
        assert "mode=confirm" in decision.reason
        assert "explicit_reference" in decision.reason

    def test_bypass_c_final_still_calculated(self, engine: DecisionEngine) -> None:
        """c_final continua sendo c_stt * c_intent * c_search no Confidence."""
        intent = _intent(action="show", confidence=0.95)
        decision = engine.evaluate(intent, c_stt=0.55)
        assert decision.confidence_breakdown is not None
        cb = decision.confidence_breakdown
        assert cb.c_stt == 0.55
        assert cb.c_intent == 0.95
        assert cb.c_search == 1.0
        # c_final = 0.55 * 0.95 * 1.0 = 0.5225
        assert abs(cb.c_final - 0.5225) < 0.001

    def test_bypass_confidence_value_is_c_final(self, engine: DecisionEngine) -> None:
        """decision.confidence = c_final (transparência do cálculo real)."""
        intent = _intent(action="show", confidence=0.95)
        decision = engine.evaluate(intent, c_stt=0.55)
        # c_final = 0.55 * 0.95 = 0.5225
        assert abs(decision.confidence - 0.5225) < 0.001

    def test_bypass_logs_reason(self, engine: DecisionEngine, caplog) -> None:
        """Log deve conter reason=explicit_reference_high_confidence."""
        import logging
        caplog.set_level(logging.INFO, logger="core.decision")
        intent = _intent(action="show", confidence=0.95)
        engine.evaluate(intent, c_stt=0.55)
        # Verificar que o log contém a razão
        log_text = " ".join(r.message for r in caplog.records)
        assert "explicit_reference_high_confidence" in log_text

    # --- Casos obrigatórios do enunciado ---

    def test_bypass_joao_3_16(self, engine: DecisionEngine) -> None:
        """João 3:16 com c_stt=0.28 (acima de stt_min=0.10 em config real).

        Com config de teste (stt_min=0.50), uso c_stt=0.55 para simular.
        """
        intent = _intent(action="show", book_id=43, chapter=3, verse=16,
                         confidence=0.95)
        decision = engine.evaluate(intent, c_stt=0.55)
        assert decision.outcome == "execute"

    def test_bypass_romanos_8_28(self, engine: DecisionEngine) -> None:
        """Romanos 8:28 com c_stt baixo → execute."""
        intent = Intent(
            action="show", book="Romanos", book_id=45, chapter=8, verse=28,
            confidence=0.95, source="parser", raw="romanos 8 28",
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert decision.outcome == "execute"

    def test_bypass_hebreus_11_1(self, engine: DecisionEngine) -> None:
        """Hebreus 11:1 com c_stt baixo → execute."""
        intent = Intent(
            action="show", book="Hebreus", book_id=49, chapter=11, verse=1,
            confidence=0.95, source="parser", raw="hebreus 11 1",
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert decision.outcome == "execute"

    # --- Casos que NÃO devem usar bypass ---

    def test_no_bypass_proximo(self, engine: DecisionEngine) -> None:
        """"próximo" não deve usar bypass (action=next)."""
        intent = _intent(
            action="next", book_id=None, chapter=None, verse=None, confidence=0.98,
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert "explicit_reference" not in decision.reason

    def test_no_bypass_anterior(self, engine: DecisionEngine) -> None:
        """"anterior" não deve usar bypass (action=previous)."""
        intent = _intent(
            action="previous", book_id=None, chapter=None, verse=None, confidence=0.98,
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert "explicit_reference" not in decision.reason

    def test_no_bypass_mais_dois(self, engine: DecisionEngine) -> None:
        """"mais dois" não deve usar bypass (action=jump)."""
        intent = _intent(
            action="jump", book_id=None, chapter=None, verse=None, confidence=0.98,
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert "explicit_reference" not in decision.reason

    def test_no_bypass_search_cooperam(self, engine: DecisionEngine) -> None:
        """"todas as coisas cooperam" não deve usar bypass (action=search)."""
        intent = _intent(
            action="search", book_id=None, chapter=None, verse=None,
            confidence=0.92, query="todas as coisas cooperam para o bem",
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert "explicit_reference" not in decision.reason

    def test_no_bypass_search_vale_sombra(self, engine: DecisionEngine) -> None:
        """"vale da sombra da morte" não deve usar bypass (action=search)."""
        intent = _intent(
            action="search", book_id=None, chapter=None, verse=None,
            confidence=0.94, query="vale da sombra da morte",
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert "explicit_reference" not in decision.reason

    def test_no_bypass_search_tudo_posso(self, engine: DecisionEngine) -> None:
        """"tudo posso naquele que me fortalece" não deve usar bypass."""
        intent = _intent(
            action="search", book_id=None, chapter=None, verse=None,
            confidence=0.95, query="tudo posso naquele que me fortalece",
        )
        decision = engine.evaluate(intent, c_stt=0.55)
        assert "explicit_reference" not in decision.reason
