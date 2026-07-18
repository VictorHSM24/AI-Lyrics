"""Testes unitários do módulo core/confirmation.py.

Estratégia:
  - Testa-se CandidateSelector com SearchResult reais e mocks do DecisionEngine.
  - Testa-se build_candidates() com vários cenários (ambíguo, não-ambíguo,
    lista vazia, lista com 1 elemento, lista com None).
  - Testa-se select() com índices válidos e inválidos.
  - Testa-se que select() não modifica search_results original.
  - Testa-se que select() não modifica Decision original.
  - Testa-se ProcessResult via PipelineOrchestrator.process_utterance_detailed().
  - 100% determinístico.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from busca.searcher import SearchResult
from config.models import ConfidenceConfig
from core.confirmation import (
    Candidate,
    CandidateList,
    CandidateSelector,
    ConfirmationPolicy,
    ProcessResult,
    SelectionResult,
)
from core.decision import DecisionEngine
from core.pipeline_orchestrator import PipelineOrchestrator
from core.types import Decision, Intent, LogEntry, Utterance, VerseRef
from estado.state import BibleStructure, BibleStateManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _conf_config() -> ConfidenceConfig:
    return ConfidenceConfig(
        min_execute=0.85,
        min_confirm=0.60,
        stt_min=0.50,
        parser_high=0.90,
        parser_compact=0.85,
    )


def _structure() -> BibleStructure:
    return BibleStructure(
        chapter_counts={43: 21, 1: 50, 45: 16, 58: 13},
        verse_counts={(43, 3): 36, (1, 1): 31, (45, 8): 39, (58, 4): 16},
    )


def _book_names() -> dict[int, str]:
    return {43: "João", 1: "Gênesis", 45: "Romanos", 58: "Hebreus"}


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
    version: str = "ACF",
    text: str = "Porque Deus amou o mundo...",
    match_type: str = "hybrid",
) -> SearchResult:
    return SearchResult(
        reference=f"{book} {chapter}:{verse}",
        book=book,
        book_id=book_id,
        chapter=chapter,
        verse=verse,
        text=text,
        version=version,
        score=score,
        c_search=c_search,
        ambiguous=ambiguous,
        match_type=match_type,
    )


def _intent(
    action: str = "search",
    query: str | None = "amor de deus",
    confidence: float = 0.9,
) -> Intent:
    return Intent(
        action=action,
        confidence=confidence,
        query=query,
        raw="o amor de deus",
    )


def _utterance(
    text: str = "o amor de deus",
    c_stt: float = 0.95,
) -> Utterance:
    return Utterance(text=text, c_stt=c_stt, audio_ms=2000)


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


def _ambiguous_results() -> list[SearchResult]:
    """Dois resultados ambíguos: João 3:16 e Gênesis 1:1."""
    return [
        _search_result(
            book="João", book_id=43, chapter=3, verse=16,
            score=0.80, c_search=0.80, ambiguous=True,
            text="Porque Deus amou o mundo de tal maneira...",
        ),
        _search_result(
            book="Gênesis", book_id=1, chapter=1, verse=1,
            score=0.78, c_search=0.78, ambiguous=True,
            text="No princípio criou Deus os céus e a terra...",
        ),
    ]


# ---------------------------------------------------------------------------
# Testes de Candidate (DTO)
# ---------------------------------------------------------------------------


class TestCandidateDTO:
    """Testes do DTO Candidate."""

    def test_candidate_is_frozen(self) -> None:
        c = Candidate(
            index=1, book="João", book_id=43, chapter=3, verse=16,
            version="ACF", reference="João 3:16", score=0.95,
            c_search=0.9, snippet="Porque Deus amou...",
        )
        with pytest.raises(AttributeError):
            c.book = "Gênesis"  # type: ignore[misc]

    def test_candidate_fields(self) -> None:
        c = Candidate(
            index=2, book="Gênesis", book_id=1, chapter=1, verse=1,
            version="ACF", reference="Gênesis 1:1", score=0.78,
            c_search=0.78, snippet="No princípio...",
        )
        assert c.index == 2
        assert c.book == "Gênesis"
        assert c.book_id == 1
        assert c.chapter == 1
        assert c.verse == 1
        assert c.version == "ACF"
        assert c.reference == "Gênesis 1:1"
        assert c.score == 0.78
        assert c.c_search == 0.78
        assert c.snippet == "No princípio..."

    def test_display_reference_with_verse(self) -> None:
        c = Candidate(
            index=1, book="Filipenses", book_id=50, chapter=4, verse=13,
            version="ARA", reference="Filipenses 4:13", score=0.95,
            c_search=0.9, snippet="tudo posso...",
        )
        assert c.display_reference == "Filipenses 4:13 (ARA)"

    def test_display_reference_acf(self) -> None:
        c = Candidate(
            index=1, book="João", book_id=43, chapter=3, verse=16,
            version="ACF", reference="João 3:16", score=0.95,
            c_search=0.9, snippet="Porque Deus amou...",
        )
        assert c.display_reference == "João 3:16 (ACF)"

    def test_display_reference_naa(self) -> None:
        c = Candidate(
            index=1, book="Salmos", book_id=19, chapter=23, verse=4,
            version="NAA", reference="Salmos 23:4", score=0.95,
            c_search=0.9, snippet="Ainda que eu ande...",
        )
        assert c.display_reference == "Salmos 23:4 (NAA)"

    def test_display_reference_is_property_not_field(self) -> None:
        """display_reference é uma property, não um field do dataclass."""
        c = Candidate(
            index=1, book="João", book_id=43, chapter=3, verse=16,
            version="ACF", reference="João 3:16", score=0.95,
            c_search=0.9, snippet="...",
        )
        # Não deve aparecer como field do dataclass
        field_names = [f.name for f in c.__dataclass_fields__.values()]
        assert "display_reference" not in field_names
        # Mas deve ser acessível como atributo
        assert hasattr(c, "display_reference")

    def test_display_reference_not_settable(self) -> None:
        """display_reference é read-only (frozen dataclass + property)."""
        c = Candidate(
            index=1, book="João", book_id=43, chapter=3, verse=16,
            version="ACF", reference="João 3:16", score=0.95,
            c_search=0.9, snippet="...",
        )
        with pytest.raises(AttributeError):
            c.display_reference = "outra coisa"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Testes de CandidateList (DTO)
# ---------------------------------------------------------------------------


class TestCandidateListDTO:
    """Testes do DTO CandidateList."""

    def test_len(self) -> None:
        cl = CandidateList(
            candidates=(
                Candidate(1, "João", 43, 3, 16, "ACF", "João 3:16", 0.8, 0.8, "..."),
                Candidate(2, "Gênesis", 1, 1, 1, "ACF", "Gênesis 1:1", 0.78, 0.78, "..."),
            ),
            query="amor",
            total=2,
        )
        assert len(cl) == 2

    def test_iter(self) -> None:
        cl = CandidateList(
            candidates=(
                Candidate(1, "João", 43, 3, 16, "ACF", "João 3:16", 0.8, 0.8, "..."),
                Candidate(2, "Gênesis", 1, 1, 1, "ACF", "Gênesis 1:1", 0.78, 0.78, "..."),
            ),
        )
        books = [c.book for c in cl]
        assert books == ["João", "Gênesis"]

    def test_getitem(self) -> None:
        cl = CandidateList(
            candidates=(
                Candidate(1, "João", 43, 3, 16, "ACF", "João 3:16", 0.8, 0.8, "..."),
                Candidate(2, "Gênesis", 1, 1, 1, "ACF", "Gênesis 1:1", 0.78, 0.78, "..."),
            ),
        )
        assert cl[0].book == "João"
        assert cl[1].book == "Gênesis"

    def test_empty(self) -> None:
        cl = CandidateList(candidates=())
        assert len(cl) == 0
        assert list(cl) == []


# ---------------------------------------------------------------------------
# Testes de CandidateSelector.build_candidates
# ---------------------------------------------------------------------------


class TestBuildCandidates:
    """Testes de CandidateSelector.build_candidates()."""

    def test_ambiguous_with_two_results_returns_candidates(self) -> None:
        engine = _real_engine()
        selector = CandidateSelector(engine)
        results = _ambiguous_results()
        cl = selector.build_candidates(results, query="amor de deus")
        assert cl is not None
        assert len(cl) == 2
        assert cl.total == 2
        assert cl.query == "amor de deus"
        assert cl.candidates[0].index == 1
        assert cl.candidates[0].book == "João"
        assert cl.candidates[1].index == 2
        assert cl.candidates[1].book == "Gênesis"

    def test_non_ambiguous_returns_none(self) -> None:
        engine = _real_engine()
        selector = CandidateSelector(engine)
        results = [
            _search_result(ambiguous=False),
            _search_result(book="Gênesis", book_id=1, ambiguous=False),
        ]
        cl = selector.build_candidates(results)
        assert cl is None

    def test_single_result_returns_none(self) -> None:
        engine = _real_engine()
        selector = CandidateSelector(engine)
        results = [_search_result(ambiguous=True)]
        cl = selector.build_candidates(results)
        assert cl is None

    def test_empty_results_returns_none(self) -> None:
        engine = _real_engine()
        selector = CandidateSelector(engine)
        cl = selector.build_candidates([])
        assert cl is None

    def test_none_results_returns_none(self) -> None:
        engine = _real_engine()
        selector = CandidateSelector(engine)
        cl = selector.build_candidates(None)
        assert cl is None

    def test_snippet_truncation(self) -> None:
        engine = _real_engine()
        selector = CandidateSelector(engine)
        long_text = "A" * 200
        results = [
            _search_result(ambiguous=True, text=long_text),
            _search_result(book="Gênesis", book_id=1, ambiguous=True, text=long_text),
        ]
        cl = selector.build_candidates(results)
        assert cl is not None
        # Snippet deve ser truncado com "..."
        assert cl.candidates[0].snippet.endswith("...")
        assert len(cl.candidates[0].snippet) <= 123  # 120 + "..."

    def test_snippet_not_truncated_when_short(self) -> None:
        engine = _real_engine()
        selector = CandidateSelector(engine)
        short_text = "Texto curto"
        results = [
            _search_result(ambiguous=True, text=short_text),
            _search_result(book="Gênesis", book_id=1, ambiguous=True, text=short_text),
        ]
        cl = selector.build_candidates(results)
        assert cl is not None
        assert cl.candidates[0].snippet == short_text

    def test_candidates_preserve_all_fields(self) -> None:
        engine = _real_engine()
        selector = CandidateSelector(engine)
        results = _ambiguous_results()
        cl = selector.build_candidates(results)
        assert cl is not None
        c = cl.candidates[0]
        r = results[0]
        assert c.book == r.book
        assert c.book_id == r.book_id
        assert c.chapter == r.chapter
        assert c.verse == r.verse
        assert c.version == r.version
        assert c.reference == r.reference
        assert c.score == r.score
        assert c.c_search == r.c_search

    def test_three_candidates(self) -> None:
        engine = _real_engine()
        selector = CandidateSelector(engine)
        results = [
            _search_result(ambiguous=True, score=0.80),
            _search_result(book="Gênesis", book_id=1, ambiguous=True, score=0.78),
            _search_result(book="Hebreus", book_id=58, chapter=4, verse=4,
                          ambiguous=True, score=0.76),
        ]
        cl = selector.build_candidates(results)
        assert cl is not None
        assert len(cl) == 3
        assert cl.candidates[0].index == 1
        assert cl.candidates[1].index == 2
        assert cl.candidates[2].index == 3


# ---------------------------------------------------------------------------
# Testes de CandidateSelector.select
# ---------------------------------------------------------------------------


class TestSelect:
    """Testes de CandidateSelector.select()."""

    def test_select_first_candidate(self) -> None:
        holyrics = MagicMock()
        holyrics.show_verse.return_value = True
        engine = _real_engine(holyrics=holyrics)
        selector = CandidateSelector(engine)
        results = _ambiguous_results()
        cl = selector.build_candidates(results, query="amor")
        assert cl is not None

        # Decision original com outcome="confirm"
        decision = Decision(
            action="search", outcome="confirm", confidence=0.76,
            requires_confirmation=True, forward_to_llm=False, ignore=False,
            reason="search ambiguous", intent=_intent(),
        )

        result = selector.select(cl, results, decision, index=1)
        assert result.success is True
        assert result.selected_result is results[0]
        assert result.ref is not None
        assert result.ref.book == "João"
        assert result.ref.chapter == 3
        assert result.ref.verse == 16

    def test_select_second_candidate(self) -> None:
        holyrics = MagicMock()
        holyrics.show_verse.return_value = True
        engine = _real_engine(holyrics=holyrics)
        selector = CandidateSelector(engine)
        results = _ambiguous_results()
        cl = selector.build_candidates(results)
        assert cl is not None

        decision = Decision(
            action="search", outcome="confirm", confidence=0.76,
            requires_confirmation=True, forward_to_llm=False, ignore=False,
            reason="search ambiguous", intent=_intent(),
        )

        result = selector.select(cl, results, decision, index=2)
        assert result.success is True
        assert result.selected_result is results[1]
        assert result.ref is not None
        assert result.ref.book == "Gênesis"
        assert result.ref.chapter == 1
        assert result.ref.verse == 1

    def test_select_invalid_index_zero(self) -> None:
        engine = _real_engine()
        selector = CandidateSelector(engine)
        results = _ambiguous_results()
        cl = selector.build_candidates(results)
        assert cl is not None

        decision = Decision(
            action="search", outcome="confirm", confidence=0.76,
            requires_confirmation=True, forward_to_llm=False, ignore=False,
            reason="search ambiguous", intent=_intent(),
        )

        with pytest.raises(ValueError, match="fora do range"):
            selector.select(cl, results, decision, index=0)

    def test_select_invalid_index_too_large(self) -> None:
        engine = _real_engine()
        selector = CandidateSelector(engine)
        results = _ambiguous_results()
        cl = selector.build_candidates(results)
        assert cl is not None

        decision = Decision(
            action="search", outcome="confirm", confidence=0.76,
            requires_confirmation=True, forward_to_llm=False, ignore=False,
            reason="search ambiguous", intent=_intent(),
        )

        with pytest.raises(ValueError, match="fora do range"):
            selector.select(cl, results, decision, index=3)

    def test_select_preserves_original_search_results(self) -> None:
        holyrics = MagicMock()
        holyrics.show_verse.return_value = True
        engine = _real_engine(holyrics=holyrics)
        selector = CandidateSelector(engine)
        results = _ambiguous_results()
        original_len = len(results)
        original_first = results[0]

        cl = selector.build_candidates(results)
        assert cl is not None

        decision = Decision(
            action="search", outcome="confirm", confidence=0.76,
            requires_confirmation=True, forward_to_llm=False, ignore=False,
            reason="search ambiguous", intent=_intent(),
        )

        selector.select(cl, results, decision, index=2)

        # search_results original não foi modificado
        assert len(results) == original_len
        assert results[0] is original_first
        assert results[0].book == "João"
        assert results[1].book == "Gênesis"

    def test_select_preserves_original_decision(self) -> None:
        holyrics = MagicMock()
        holyrics.show_verse.return_value = True
        engine = _real_engine(holyrics=holyrics)
        selector = CandidateSelector(engine)
        results = _ambiguous_results()

        cl = selector.build_candidates(results)
        assert cl is not None

        decision = Decision(
            action="search", outcome="confirm", confidence=0.76,
            requires_confirmation=True, forward_to_llm=False, ignore=False,
            reason="search ambiguous", intent=_intent(),
        )

        selector.select(cl, results, decision, index=1)

        # Decision original não foi modificado
        assert decision.outcome == "confirm"
        assert decision.requires_confirmation is True

    def test_select_decision_error_returns_failure(self) -> None:
        # Engine sem holyrics — execute() vai falhar? Não, vai dry-run.
        # Para forçar erro, usar engine que levanta DecisionError.
        engine = MagicMock(spec=DecisionEngine)
        from core.exceptions import DecisionError
        engine.execute.side_effect = DecisionError("holyrics offline")

        selector = CandidateSelector(engine)
        results = _ambiguous_results()
        cl = selector.build_candidates(results)
        assert cl is not None

        decision = Decision(
            action="search", outcome="confirm", confidence=0.76,
            requires_confirmation=True, forward_to_llm=False, ignore=False,
            reason="search ambiguous", intent=_intent(),
        )

        result = selector.select(cl, results, decision, index=1)
        assert result.success is False
        assert result.error is not None
        assert "holyrics offline" in result.error
        assert result.selected_result is results[0]

    def test_select_calls_engine_execute_with_single_element_list(self) -> None:
        holyrics = MagicMock()
        holyrics.show_verse.return_value = True
        engine = _real_engine(holyrics=holyrics)
        selector = CandidateSelector(engine)
        results = _ambiguous_results()
        cl = selector.build_candidates(results)
        assert cl is not None

        decision = Decision(
            action="search", outcome="confirm", confidence=0.76,
            requires_confirmation=True, forward_to_llm=False, ignore=False,
            reason="search ambiguous", intent=_intent(),
        )

        # Spy no execute para verificar argumentos
        original_execute = engine.execute
        captured_args: list = []
        def spy_execute(dec, sr):
            captured_args.append((dec, sr))
            return original_execute(dec, sr)
        engine.execute = spy_execute  # type: ignore[assignment]

        selector.select(cl, results, decision, index=2)

        assert len(captured_args) == 1
        exec_decision, exec_search_results = captured_args[0]
        assert exec_decision.outcome == "execute"
        assert len(exec_search_results) == 1
        assert exec_search_results[0].book == "Gênesis"


# ---------------------------------------------------------------------------
# Testes de ConfirmationPolicy
# ---------------------------------------------------------------------------


class TestConfirmationPolicy:
    """Testes da política de confirmação."""

    def test_ambiguous_true_returns_true(self) -> None:
        policy = ConfirmationPolicy()
        assert policy.requires_confirmation(ambiguous=True) is True

    def test_ambiguous_false_returns_false(self) -> None:
        policy = ConfirmationPolicy()
        assert policy.requires_confirmation(ambiguous=False) is False

    def test_default_total_results_zero(self) -> None:
        """total_results default é 0 — não afeta resultado hoje."""
        policy = ConfirmationPolicy()
        assert policy.requires_confirmation(ambiguous=True, total_results=0) is True
        assert policy.requires_confirmation(ambiguous=False, total_results=0) is False

    def test_total_results_does_not_affect_today(self) -> None:
        """Hoje total_results não afeta a decisão — apenas ambiguous."""
        policy = ConfirmationPolicy()
        assert policy.requires_confirmation(ambiguous=True, total_results=5) is True
        assert policy.requires_confirmation(ambiguous=False, total_results=5) is False
        assert policy.requires_confirmation(ambiguous=True, total_results=1) is True
        assert policy.requires_confirmation(ambiguous=False, total_results=1) is False

    def test_future_params_accepted_but_ignored(self) -> None:
        """Parâmetros futuros são aceitos mas não afetam a decisão hoje."""
        policy = ConfirmationPolicy()
        # Todos os parâmetros futuros devem ser aceitos sem erro
        assert policy.requires_confirmation(
            ambiguous=True, total_results=3,
            score_gap=0.05, top_k=10, confidence=0.85,
            embedding_score=0.9, rerank_score=0.88, llm_confidence=0.92,
        ) is True
        assert policy.requires_confirmation(
            ambiguous=False, total_results=3,
            score_gap=0.01, top_k=10, confidence=0.99,
            embedding_score=0.95, rerank_score=0.98, llm_confidence=0.95,
        ) is False

    def test_future_params_all_none(self) -> None:
        """Parâmetros futuros como None não afetam a decisão."""
        policy = ConfirmationPolicy()
        assert policy.requires_confirmation(
            ambiguous=True,
            score_gap=None, top_k=None, confidence=None,
            embedding_score=None, rerank_score=None, llm_confidence=None,
        ) is True

    def test_policy_is_stateless(self) -> None:
        """Policy não tem estado — mesma instância pode ser reutilizada."""
        policy = ConfirmationPolicy()
        assert policy.requires_confirmation(ambiguous=True) is True
        assert policy.requires_confirmation(ambiguous=False) is False
        assert policy.requires_confirmation(ambiguous=True) is True
        assert policy.requires_confirmation(ambiguous=False) is False

    def test_two_instances_identical_behavior(self) -> None:
        """Duas instâncias diferentes têm comportamento idêntico."""
        p1 = ConfirmationPolicy()
        p2 = ConfirmationPolicy()
        assert p1.requires_confirmation(ambiguous=True) == p2.requires_confirmation(ambiguous=True)
        assert p1.requires_confirmation(ambiguous=False) == p2.requires_confirmation(ambiguous=False)


# ---------------------------------------------------------------------------
# Testes de ProcessResult via PipelineOrchestrator
# ---------------------------------------------------------------------------


class TestProcessUtteranceDetailed:
    """Testes de PipelineOrchestrator.process_utterance_detailed()."""

    def test_returns_process_result(self) -> None:
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(), _real_engine(), _state_manager()
        )
        result = orch.process_utterance_detailed(_utterance())
        assert isinstance(result, ProcessResult)
        assert isinstance(result.log_entry, LogEntry)

    def test_process_utterance_still_returns_log_entry(self) -> None:
        """process_utterance() deve continuar retornando LogEntry (compat)."""
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(), _real_engine(), _state_manager()
        )
        entry = orch.process_utterance(_utterance())
        assert isinstance(entry, LogEntry)

    def test_detailed_non_ambiguous_no_candidates(self) -> None:
        """Busca não-ambígua → candidates=None, requires_confirmation=False."""
        results = [_search_result(ambiguous=False, c_search=0.98)]
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(results), _real_engine(), _state_manager()
        )
        result = orch.process_utterance_detailed(
            _utterance(c_stt=0.98)
        )
        assert result.candidates is None
        assert result.requires_confirmation is False
        assert result.decision is not None
        assert result.decision.outcome == "execute"
        assert result.search_results is results

    def test_detailed_ambiguous_returns_candidates(self) -> None:
        """Busca ambígua com 2 resultados → candidates preenchido."""
        results = _ambiguous_results()
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(results), _real_engine(), _state_manager()
        )
        result = orch.process_utterance_detailed(_utterance())
        assert result.candidates is not None
        assert len(result.candidates) == 2
        assert result.requires_confirmation is True
        assert result.decision is not None
        assert result.decision.outcome == "confirm"
        assert result.search_results is results

    def test_detailed_ambiguous_single_result_no_candidates(self) -> None:
        """Busca ambígua com 1 resultado → candidates=None (precisa >= 2)."""
        results = [_search_result(ambiguous=True)]
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(results), _real_engine(), _state_manager()
        )
        result = orch.process_utterance_detailed(_utterance())
        assert result.candidates is None
        # Ainda requires_confirmation=True porque outcome=confirm
        assert result.requires_confirmation is True

    def test_detailed_action_none_no_candidates(self) -> None:
        """action=none → candidates=None, requires_confirmation=False."""
        intent = Intent(action="none", confidence=0.0, raw="olá")
        orch = PipelineOrchestrator(
            _mock_parser(intent), _mock_searcher(), _real_engine(), _state_manager()
        )
        result = orch.process_utterance_detailed(
            _utterance(text="olá", c_stt=0.5)
        )
        assert result.candidates is None
        assert result.requires_confirmation is False
        assert result.decision is not None
        assert result.decision.outcome == "ignore"

    def test_detailed_action_show_no_candidates(self) -> None:
        """action=show → candidates=None (não é busca)."""
        intent = Intent(
            action="show", book="João", book_id=43, chapter=3, verse=16,
            confidence=0.95, raw="joão 3 16",
        )
        orch = PipelineOrchestrator(
            _mock_parser(intent), None, _real_engine(), _state_manager()
        )
        result = orch.process_utterance_detailed(
            _utterance(text="joão 3 16", c_stt=0.98)
        )
        assert result.candidates is None
        assert result.requires_confirmation is False
        assert result.decision is not None
        assert result.decision.outcome == "execute"

    def test_detailed_candidates_query_from_intent(self) -> None:
        """Candidates devem ter query do intent."""
        results = _ambiguous_results()
        intent = _intent(query="minha query específica")
        orch = PipelineOrchestrator(
            _mock_parser(intent), _mock_searcher(results),
            _real_engine(), _state_manager(),
        )
        result = orch.process_utterance_detailed(_utterance())
        assert result.candidates is not None
        assert result.candidates.query == "minha query específica"

    def test_detailed_log_entry_same_as_process_utterance(self) -> None:
        """LogEntry de detailed deve ser idêntico ao de process_utterance."""
        results = _ambiguous_results()
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(results), _real_engine(), _state_manager()
        )
        entry_normal = orch.process_utterance(_utterance())
        entry_detailed = orch.process_utterance_detailed(_utterance())
        # Mesmo outcome e campos
        assert entry_normal.decision["outcome"] == entry_detailed.log_entry.decision["outcome"]
        assert entry_normal.search["ambiguous"] == entry_detailed.log_entry.search["ambiguous"]

    def test_detailed_parser_error_returns_process_result(self) -> None:
        """Erro no parser → retorna ProcessResult com log_entry (sem decision)."""
        from core.exceptions import StateError
        parser = MagicMock()
        parser.parse.side_effect = StateError("parse boom")
        orch = PipelineOrchestrator(
            parser, _mock_searcher(), _real_engine(), _state_manager()
        )
        result = orch.process_utterance_detailed(_utterance())
        assert isinstance(result, ProcessResult)
        assert isinstance(result.log_entry, LogEntry)
        assert result.decision is None
        assert result.search_results is None
        assert result.candidates is None
        assert result.requires_confirmation is False


# ---------------------------------------------------------------------------
# Testes de integração: select após process_utterance_detailed
# ---------------------------------------------------------------------------


class TestIntegrationSelectAfterDetailed:
    """Testa o fluxo completo: detailed → select → execute."""

    def test_full_flow_ambiguous_select_second(self) -> None:
        """Fluxo completo: busca ambígua → detailed → select(2) → execute."""
        holyrics = MagicMock()
        holyrics.show_verse.return_value = True
        engine = _real_engine(holyrics=holyrics)
        results = _ambiguous_results()
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(results), engine, _state_manager()
        )

        # 1. process_utterance_detailed
        result = orch.process_utterance_detailed(_utterance())
        assert result.candidates is not None
        assert result.requires_confirmation is True
        assert result.decision is not None
        assert result.decision.outcome == "confirm"

        # 2. Interface escolhe índice 2 (Gênesis 1:1)
        selector = CandidateSelector(engine)
        selection = selector.select(
            result.candidates, result.search_results, result.decision, index=2
        )

        # 3. Execução bem-sucedida
        assert selection.success is True
        assert selection.ref is not None
        assert selection.ref.book == "Gênesis"
        assert selection.ref.chapter == 1
        assert selection.ref.verse == 1
        assert selection.selected_result is results[1]

        # 4. Holyrics foi chamado
        holyrics.show_verse.assert_called_once()

    def test_full_flow_ambiguous_select_first(self) -> None:
        """Fluxo completo: busca ambígua → detailed → select(1) → execute."""
        holyrics = MagicMock()
        holyrics.show_verse.return_value = True
        engine = _real_engine(holyrics=holyrics)
        results = _ambiguous_results()
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(results), engine, _state_manager()
        )

        result = orch.process_utterance_detailed(_utterance())
        assert result.candidates is not None

        selector = CandidateSelector(engine)
        selection = selector.select(
            result.candidates, result.search_results, result.decision, index=1
        )

        assert selection.success is True
        assert selection.ref is not None
        assert selection.ref.book == "João"
        assert selection.ref.chapter == 3
        assert selection.ref.verse == 16

    def test_full_flow_non_ambiguous_no_select_needed(self) -> None:
        """Busca não-ambígua → não há candidates → execute direto."""
        holyrics = MagicMock()
        holyrics.show_verse.return_value = True
        engine = _real_engine(holyrics=holyrics)
        results = [_search_result(ambiguous=False, c_search=0.98)]
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(results), engine, _state_manager()
        )

        result = orch.process_utterance_detailed(
            _utterance(c_stt=0.98)
        )
        assert result.candidates is None
        assert result.requires_confirmation is False
        assert result.decision.outcome == "execute"
        # Holyrics já foi chamado pelo pipeline
        holyrics.show_verse.assert_called_once()

    def test_full_flow_search_results_preserved_after_select(self) -> None:
        """search_results original permanece intacto após select."""
        holyrics = MagicMock()
        holyrics.show_verse.return_value = True
        engine = _real_engine(holyrics=holyrics)
        results = _ambiguous_results()
        orch = PipelineOrchestrator(
            _mock_parser(), _mock_searcher(results), engine, _state_manager()
        )

        result = orch.process_utterance_detailed(_utterance())
        selector = CandidateSelector(engine)
        selector.select(
            result.candidates, result.search_results, result.decision, index=2
        )

        # search_results ainda tem 2 elementos
        assert len(result.search_results) == 2
        assert result.search_results[0].book == "João"
        assert result.search_results[1].book == "Gênesis"
