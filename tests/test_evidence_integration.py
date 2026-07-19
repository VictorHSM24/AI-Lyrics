"""Testes do Evidence Layer — Factory, Builder e integração com Strategies.

Cobre:
  - EvidenceFactory (todos os helpers: book_match, chapter_match,
    feedback_*, continuity_*, book_recent, reference_*, theme_*,
    evaluation_*, confidence_*, custom).
  - SignalBuilder (build com evidences, value_override, clamp,
    limite de evidências).
  - IntelligenceSignal.evidences (campo novo, has_evidences,
    evidence_count, to_dict com evidences).
  - Integração: todas as 8 strategies produzem evidences.
"""

from __future__ import annotations

import unittest

import sys
sys.path.insert(0, ".")

from intelligence import (
    CandidateInfo,
    Evidence,
    EvidenceFactory,
    EvidencePolicy,
    EvidenceType,
    IntelligenceRequest,
    IntelligenceSignal,
    SignalBuilder,
)
from intelligence.policy import IntelligencePolicy
from intelligence.strategies import (
    BookStrategy,
    ConfidenceStrategy,
    ContextStrategy,
    ContinuityStrategy,
    EvaluationStrategy,
    FeedbackStrategy,
    ReferenceStrategy,
    ThemeStrategy,
    all_strategies,
)


# ---------------------------------------------------------------------------
# EvidenceFactory
# ---------------------------------------------------------------------------


class TestEvidenceFactory(unittest.TestCase):
    """Testes da EvidenceFactory."""

    def setUp(self):
        self.factory = EvidenceFactory()

    def test_book_match_evidence(self):
        ev = self.factory.book_match("ev1", "João", "João", value=0.1)
        self.assertEqual(ev.type, EvidenceType.CONTEXT_BOOK_MATCH)
        self.assertIn("João", ev.description)
        self.assertEqual(ev.value, 0.1)
        self.assertGreater(ev.weight, 0.0)

    def test_chapter_match_evidence(self):
        ev = self.factory.chapter_match(
            "ev1", "João", 21, "João", 21, value=0.15)
        self.assertEqual(ev.type, EvidenceType.CONTEXT_CHAPTER_MATCH)
        self.assertIn("21", ev.description)

    def test_context_no_match_evidence(self):
        ev = self.factory.context_no_match("ev1", "João", "Mateus")
        self.assertEqual(ev.value, 0.0)

    def test_feedback_acceptance_evidence(self):
        ev = self.factory.feedback_acceptance("ev1", 5, value=0.2)
        self.assertEqual(ev.type, EvidenceType.FEEDBACK_ACCEPTANCE)
        self.assertIn("5", ev.description)
        self.assertEqual(ev.value, 0.2)

    def test_feedback_rejection_evidence(self):
        ev = self.factory.feedback_rejection("ev1", 3, value=-0.1)
        self.assertEqual(ev.type, EvidenceType.FEEDBACK_REJECTION)
        self.assertEqual(ev.value, -0.1)

    def test_feedback_history_evidence(self):
        ev = self.factory.feedback_history("ev1", 7.5, value=0.1)
        self.assertEqual(ev.type, EvidenceType.FEEDBACK_HISTORY)
        self.assertIn("7.5", ev.description)

    def test_feedback_none_evidence(self):
        ev = self.factory.feedback_none("ev1")
        self.assertEqual(ev.value, 0.0)
        self.assertEqual(ev.confidence, 0.0)

    def test_continuity_book_evidence(self):
        ev = self.factory.continuity_book("ev1", "João", "João", value=0.1)
        self.assertEqual(ev.type, EvidenceType.CONTINUITY_BOOK)

    def test_continuity_chapter_evidence(self):
        ev = self.factory.continuity_chapter(
            "ev1", "João", 3, "João", 3, value=0.15)
        self.assertEqual(ev.type, EvidenceType.CONTINUITY_CHAPTER)

    def test_continuity_none_evidence(self):
        ev = self.factory.continuity_none("ev1", "Mateus 5")
        self.assertEqual(ev.value, 0.0)

    def test_book_recent_evidence(self):
        ev = self.factory.book_recent("ev1", "João", value=0.1)
        self.assertEqual(ev.type, EvidenceType.BOOK_RECENT)
        self.assertIn("João", ev.description)

    def test_book_not_recent_evidence(self):
        ev = self.factory.book_not_recent("ev1", "Mateus")
        self.assertEqual(ev.value, 0.0)

    def test_reference_repeat_evidence(self):
        ev = self.factory.reference_repeat("ev1", "João 3:16", value=0.1)
        self.assertEqual(ev.type, EvidenceType.REFERENCE_REPEAT)

    def test_reference_no_repeat_evidence(self):
        ev = self.factory.reference_no_repeat("ev1")
        self.assertEqual(ev.value, 0.0)

    def test_theme_match_evidence(self):
        ev = self.factory.theme_match("ev1", "fé", value=0.1)
        self.assertEqual(ev.type, EvidenceType.THEME_MATCH)
        self.assertIn("fé", ev.description)

    def test_theme_no_match_evidence(self):
        ev = self.factory.theme_no_match("ev1")
        self.assertEqual(ev.value, 0.0)

    def test_evaluation_precision_evidence(self):
        ev = self.factory.evaluation_precision("ev1", 0.85, value=0.05)
        self.assertEqual(ev.type, EvidenceType.EVALUATION_PRECISION)
        self.assertIn("85.0", ev.description)

    def test_evaluation_volume_evidence(self):
        ev = self.factory.evaluation_volume("ev1", 100, value=0.05)
        self.assertEqual(ev.type, EvidenceType.EVALUATION_VOLUME)
        self.assertIn("100", ev.description)

    def test_evaluation_reliability_reliable(self):
        ev = self.factory.evaluation_reliability("ev1", True, value=0.05)
        self.assertEqual(ev.type, EvidenceType.EVALUATION_RELIABILITY)
        self.assertGreater(ev.confidence, 0.5)

    def test_evaluation_reliability_unreliable(self):
        ev = self.factory.evaluation_reliability("ev1", False, value=0.0)
        self.assertLess(ev.confidence, 0.5)

    def test_evaluation_none_evidence(self):
        ev = self.factory.evaluation_none("ev1")
        self.assertEqual(ev.value, 0.0)

    def test_confidence_consistency_evidence(self):
        ev = self.factory.confidence_consistency(
            "ev1", 3, 1, 2, value=0.05)
        self.assertEqual(ev.type, EvidenceType.CONFIDENCE_CONSISTENCY)
        self.assertIn("3", ev.description)

    def test_confidence_none_evidence(self):
        ev = self.factory.confidence_none("ev1")
        self.assertEqual(ev.value, 0.0)

    def test_custom_evidence(self):
        ev = self.factory.custom(
            "ev1", "evidência ad-hoc", value=0.3, weight=0.5,
            confidence=0.7, metadata=(("k", "v"),))
        self.assertEqual(ev.type, EvidenceType.CUSTOM)
        self.assertEqual(ev.value, 0.3)
        self.assertEqual(ev.weight, 0.5)
        self.assertEqual(ev.confidence, 0.7)
        self.assertEqual(ev.metadata, (("k", "v"),))

    def test_custom_default_weight_from_policy(self):
        """custom sem weight deve usar peso da policy."""
        ev = self.factory.custom("ev1", "test", value=0.1)
        self.assertGreaterEqual(ev.weight, 0.0)

    def test_factory_uses_policy(self):
        """Factory deve usar policy passada."""
        policy = EvidencePolicy()
        factory = EvidenceFactory(policy)
        self.assertIs(factory.policy, policy)


# ---------------------------------------------------------------------------
# SignalBuilder
# ---------------------------------------------------------------------------


class TestSignalBuilder(unittest.TestCase):
    """Testes do SignalBuilder."""

    def setUp(self):
        self.builder = SignalBuilder()
        self.factory = EvidenceFactory()

    def test_build_basic_signal(self):
        """build deve produzir IntelligenceSignal com campos corretos."""
        signal = self.builder.build(
            signal_type="context", weight=0.2,
            evidences=(), explanation="test")
        self.assertIsInstance(signal, IntelligenceSignal)
        self.assertEqual(signal.signal_type, "context")
        self.assertEqual(signal.weight, 0.2)
        self.assertEqual(signal.explanation, "test")
        self.assertEqual(signal.evidences, ())

    def test_build_with_evidences(self):
        """build deve anexar evidences ao signal."""
        ev1 = self.factory.book_match("ev1", "João", "João", value=0.1)
        ev2 = self.factory.chapter_match(
            "ev2", "João", 21, "João", 21, value=0.15)
        signal = self.builder.build(
            signal_type="context", weight=0.2,
            evidences=(ev1, ev2), explanation="test")
        self.assertEqual(len(signal.evidences), 2)
        self.assertTrue(signal.has_evidences)
        self.assertEqual(signal.evidence_count, 2)

    def test_build_calculates_value_from_evidences(self):
        """build deve calcular value a partir das contribuições."""
        ev1 = self.factory.book_match("ev1", "João", "João", value=0.1)
        ev2 = self.factory.chapter_match(
            "ev2", "João", 21, "João", 21, value=0.15)
        signal = self.builder.build(
            signal_type="context", weight=0.2,
            evidences=(ev1, ev2), explanation="test")
        # value = sum(value*weight) / sum(weight)
        expected = (ev1.contribution + ev2.contribution) / (ev1.weight + ev2.weight)
        self.assertAlmostEqual(signal.value, expected, places=3)

    def test_build_value_override(self):
        """value_override deve substituir cálculo automático."""
        ev1 = self.factory.book_match("ev1", "João", "João", value=0.1)
        signal = self.builder.build(
            signal_type="context", weight=0.2,
            evidences=(ev1,), explanation="test",
            value_override=0.42)
        self.assertEqual(signal.value, 0.42)

    def test_build_clamps_value_to_positive(self):
        """value deve ser limitado a [-1.0, 1.0]."""
        ev = self.factory.custom("ev1", "test", value=10.0, weight=1.0)
        signal = self.builder.build(
            signal_type="test", weight=0.1,
            evidences=(ev,), explanation="test")
        self.assertLessEqual(signal.value, 1.0)

    def test_build_clamps_value_to_negative(self):
        """value negativo grande deve ser limitado a -1.0."""
        ev = self.factory.custom("ev1", "test", value=-10.0, weight=1.0)
        signal = self.builder.build(
            signal_type="test", weight=0.1,
            evidences=(ev,), explanation="test")
        self.assertGreaterEqual(signal.value, -1.0)

    def test_build_no_evidences_value_zero(self):
        """build sem evidences deve ter value=0."""
        signal = self.builder.build(
            signal_type="test", weight=0.1,
            evidences=(), explanation="test")
        self.assertEqual(signal.value, 0.0)
        self.assertFalse(signal.has_evidences)

    def test_build_zero_weight_evidences(self):
        """build com evidences de peso zero deve ter value=0."""
        ev = Evidence(
            id="ev1", type=EvidenceType.CUSTOM, description="test",
            value=0.5, weight=0.0)
        signal = self.builder.build(
            signal_type="test", weight=0.1,
            evidences=(ev,), explanation="test")
        self.assertEqual(signal.value, 0.0)

    def test_build_limits_evidences_count(self):
        """build deve limitar número de evidences ao máximo da policy."""
        policy = EvidencePolicy()
        max_ev = policy.max_evidences_per_signal
        # Criar mais evidences que o limite
        evidences = tuple(
            Evidence(id=f"ev{i}", type=EvidenceType.CUSTOM, description="t")
            for i in range(max_ev + 10)
        )
        builder = SignalBuilder(policy)
        signal = builder.build(
            signal_type="test", weight=0.1,
            evidences=evidences, explanation="test")
        self.assertEqual(signal.evidence_count, max_ev)

    def test_build_uses_policy(self):
        """Builder deve usar policy passada."""
        policy = EvidencePolicy()
        builder = SignalBuilder(policy)
        self.assertIs(builder.policy, policy)


# ---------------------------------------------------------------------------
# IntelligenceSignal.evidences (campo novo)
# ---------------------------------------------------------------------------


class TestIntelligenceSignalEvidences(unittest.TestCase):
    """Testes do campo evidences em IntelligenceSignal."""

    def test_signal_default_evidences_empty(self):
        """IntelligenceSignal deve ter evidences=() por default."""
        signal = IntelligenceSignal(
            signal_type="test", value=0.1, weight=0.2, explanation="t")
        self.assertEqual(signal.evidences, ())
        self.assertFalse(signal.has_evidences)
        self.assertEqual(signal.evidence_count, 0)

    def test_signal_with_evidences(self):
        """IntelligenceSignal deve aceitar evidences no construtor."""
        ev = Evidence(
            id="ev1", type=EvidenceType.CUSTOM, description="test")
        signal = IntelligenceSignal(
            signal_type="test", value=0.1, weight=0.2,
            explanation="t", evidences=(ev,))
        self.assertEqual(len(signal.evidences), 1)
        self.assertTrue(signal.has_evidences)
        self.assertEqual(signal.evidence_count, 1)

    def test_signal_to_dict_includes_evidences(self):
        """to_dict deve incluir lista de evidences."""
        ev = Evidence(
            id="ev1", type=EvidenceType.CUSTOM, description="test",
            value=0.5, weight=0.3)
        signal = IntelligenceSignal(
            signal_type="test", value=0.1, weight=0.2,
            explanation="t", evidences=(ev,))
        d = signal.to_dict()
        self.assertIn("evidences", d)
        self.assertIsInstance(d["evidences"], list)
        self.assertEqual(len(d["evidences"]), 1)
        self.assertEqual(d["evidences"][0]["id"], "ev1")

    def test_signal_to_dict_evidences_empty(self):
        """to_dict com evidences=() deve ter lista vazia."""
        signal = IntelligenceSignal(
            signal_type="test", value=0.1, weight=0.2, explanation="t")
        d = signal.to_dict()
        self.assertEqual(d["evidences"], [])

    def test_signal_is_hashable_with_evidences(self):
        """IntelligenceSignal com evidences deve ser hashable."""
        ev = Evidence(
            id="ev1", type=EvidenceType.CUSTOM, description="test")
        signal = IntelligenceSignal(
            signal_type="test", value=0.1, weight=0.2,
            explanation="t", evidences=(ev,))
        self.assertIsInstance(hash(signal), int)


# ---------------------------------------------------------------------------
# Integração: Strategies produzem evidences
# ---------------------------------------------------------------------------


class _MockContext:
    """Context mock para testes."""

    def __init__(self, book=None, chapter=None, recent_references=(),
                 last_reference=None, recent_themes=(), recent_books=()):
        self.book = book
        self.chapter = chapter
        self.recent_references = recent_references
        self.last_reference = last_reference
        self.recent_themes = recent_themes
        self.recent_books = recent_books


class _MockBook:
    def __init__(self, name):
        self.canonical_name = name


class _MockReference:
    def __init__(self, book_name, chapter, verse):
        self.book = _MockBook(book_name)
        self.chapter = chapter
        self.verse_start = verse


class _MockFeedbackSummary:
    def __init__(self, has_feedback, total_weight, acceptances, rejections):
        self.has_feedback = has_feedback
        self.total_weight = total_weight
        self.acceptances = acceptances
        self.rejections = rejections


class _MockMetrics:
    def __init__(self, precision, total_searches):
        self.precision = precision
        self.total_searches = total_searches


class TestStrategiesProduceEvidences(unittest.TestCase):
    """Verifica que todas as strategies produzem evidences."""

    def setUp(self):
        self.policy = IntelligencePolicy()

    def _make_request(self, context, candidate,
                      feedback_summaries=None, evaluation_metrics=None):
        return IntelligenceRequest(
            query="test", context=context, candidates=(candidate,),
            feedback_summaries=feedback_summaries or {},
            evaluation_metrics=evaluation_metrics,
        )

    def test_context_strategy_chapter_match_produces_evidences(self):
        """ContextStrategy com match de capítulo deve produzir 2 evidences."""
        ctx = _MockContext(book="João", chapter=21)
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        req = self._make_request(ctx, cand)
        signal = ContextStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)
        self.assertEqual(signal.evidence_count, 2)

    def test_context_strategy_book_match_produces_one_evidence(self):
        """ContextStrategy com match só de livro deve produzir 1 evidence."""
        ctx = _MockContext(book="João", chapter=21)
        cand = CandidateInfo("43:20:15", 0.8, "João", 20, 15, "João 20:15")
        req = self._make_request(ctx, cand)
        signal = ContextStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)
        self.assertEqual(signal.evidence_count, 1)

    def test_context_strategy_no_match_produces_evidence(self):
        """ContextStrategy sem match deve produzir 1 evidence (no_match)."""
        ctx = _MockContext(book="João", chapter=21)
        cand = CandidateInfo("40:1:1", 0.8, "Mateus", 1, 1, "Mateus 1:1")
        req = self._make_request(ctx, cand)
        signal = ContextStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)

    def test_context_strategy_no_context_produces_evidence(self):
        """ContextStrategy sem contexto deve produzir 1 evidence."""
        ctx = _MockContext(book=None, chapter=None)
        cand = CandidateInfo("40:1:1", 0.8, "Mateus", 1, 1, "Mateus 1:1")
        req = self._make_request(ctx, cand)
        signal = ContextStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)

    def test_feedback_strategy_positive_produces_evidences(self):
        """FeedbackStrategy com feedback positivo deve produzir evidences."""
        ctx = _MockContext()
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        summary = _MockFeedbackSummary(True, 7.0, 5, 1)
        req = self._make_request(
            ctx, cand,
            feedback_summaries={cand.candidate_id: summary})
        signal = FeedbackStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)
        # acceptance + history (rejection também, pois rejections > 0)
        self.assertGreaterEqual(signal.evidence_count, 2)

    def test_feedback_strategy_negative_produces_evidences(self):
        """FeedbackStrategy com feedback negativo deve produzir evidences."""
        ctx = _MockContext()
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        summary = _MockFeedbackSummary(True, -3.0, 1, 5)
        req = self._make_request(
            ctx, cand,
            feedback_summaries={cand.candidate_id: summary})
        signal = FeedbackStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)
        self.assertLess(signal.value, 0.0)

    def test_feedback_strategy_no_feedback_produces_evidence(self):
        """FeedbackStrategy sem feedback deve produzir 1 evidence."""
        ctx = _MockContext()
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        req = self._make_request(ctx, cand)
        signal = FeedbackStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)
        self.assertEqual(signal.evidence_count, 1)

    def test_continuity_strategy_chapter_match_produces_evidence(self):
        """ContinuityStrategy com match deve produzir evidence."""
        ref = _MockReference("João", 21, 15)
        ctx = _MockContext(recent_references=(ref,))
        cand = CandidateInfo("43:21:25", 0.8, "João", 21, 25, "João 21:25")
        req = self._make_request(ctx, cand)
        signal = ContinuityStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)

    def test_continuity_strategy_book_match_produces_evidence(self):
        """ContinuityStrategy com match só de livro deve produzir evidence."""
        ref = _MockReference("João", 21, 15)
        ctx = _MockContext(recent_references=(ref,))
        cand = CandidateInfo("43:22:1", 0.8, "João", 22, 1, "João 22:1")
        req = self._make_request(ctx, cand)
        signal = ContinuityStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)

    def test_continuity_strategy_no_recent_produces_evidence(self):
        """ContinuityStrategy sem recentes deve produzir evidence."""
        ctx = _MockContext(recent_references=())
        cand = CandidateInfo("43:21:25", 0.8, "João", 21, 25, "João 21:25")
        req = self._make_request(ctx, cand)
        signal = ContinuityStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)

    def test_reference_strategy_match_produces_evidence(self):
        """ReferenceStrategy com match deve produzir evidence."""
        ref = _MockReference("João", 21, 15)
        ctx = _MockContext(last_reference=ref)
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        req = self._make_request(ctx, cand)
        signal = ReferenceStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)

    def test_reference_strategy_no_last_produces_evidence(self):
        """ReferenceStrategy sem last_reference deve produzir evidence."""
        ctx = _MockContext(last_reference=None)
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        req = self._make_request(ctx, cand)
        signal = ReferenceStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)

    def test_theme_strategy_match_produces_evidence(self):
        """ThemeStrategy com match deve produzir evidence."""
        ctx = _MockContext(recent_themes=("fé",))
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15 fé")
        req = self._make_request(ctx, cand)
        signal = ThemeStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)
        self.assertGreater(signal.value, 0.0)

    def test_theme_strategy_no_themes_produces_evidence(self):
        """ThemeStrategy sem temas deve produzir evidence."""
        ctx = _MockContext(recent_themes=())
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        req = self._make_request(ctx, cand)
        signal = ThemeStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)

    def test_book_strategy_recent_produces_evidence(self):
        """BookStrategy com livro recente deve produzir evidence."""
        ctx = _MockContext(recent_books=("João",))
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        req = self._make_request(ctx, cand)
        signal = BookStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)
        self.assertGreater(signal.value, 0.0)

    def test_book_strategy_not_recent_produces_evidence(self):
        """BookStrategy com livro não recente deve produzir evidence."""
        ctx = _MockContext(recent_books=("Mateus",))
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        req = self._make_request(ctx, cand)
        signal = BookStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)
        self.assertEqual(signal.value, 0.0)

    def test_book_strategy_no_recent_books_produces_evidence(self):
        """BookStrategy sem recent_books deve produzir evidence."""
        ctx = _MockContext(recent_books=())
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        req = self._make_request(ctx, cand)
        signal = BookStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)

    def test_evaluation_strategy_positive_produces_evidences(self):
        """EvaluationStrategy com precisão alta deve produzir evidences."""
        ctx = _MockContext()
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        metrics = _MockMetrics(precision=0.85, total_searches=100)
        req = self._make_request(ctx, cand, evaluation_metrics=metrics)
        signal = EvaluationStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)
        # volume + precision + reliability
        self.assertEqual(signal.evidence_count, 3)

    def test_evaluation_strategy_negative_produces_evidences(self):
        """EvaluationStrategy com precisão baixa deve produzir evidences."""
        ctx = _MockContext()
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        metrics = _MockMetrics(precision=0.30, total_searches=100)
        req = self._make_request(ctx, cand, evaluation_metrics=metrics)
        signal = EvaluationStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)
        self.assertLess(signal.value, 0.0)

    def test_evaluation_strategy_no_metrics_produces_evidence(self):
        """EvaluationStrategy sem métricas deve produzir 1 evidence."""
        ctx = _MockContext()
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        req = self._make_request(ctx, cand, evaluation_metrics=None)
        signal = EvaluationStrategy().evaluate(cand, req, self.policy)
        self.assertTrue(signal.has_evidences)
        self.assertEqual(signal.evidence_count, 1)

    def test_confidence_strategy_produces_evidence(self):
        """ConfidenceStrategy deve produzir evidence."""
        ctx = _MockContext()
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        req = self._make_request(ctx, cand)
        # Sinais mock
        other_signals = (
            IntelligenceSignal(signal_type="context", value=0.1, weight=0.2),
            IntelligenceSignal(signal_type="feedback", value=0.05, weight=0.1),
        )
        signal = ConfidenceStrategy().evaluate(
            cand, req, self.policy, other_signals=other_signals)
        self.assertTrue(signal.has_evidences)

    def test_confidence_strategy_no_signals_produces_evidence(self):
        """ConfidenceStrategy sem sinais deve produzir 1 evidence."""
        ctx = _MockContext()
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15")
        req = self._make_request(ctx, cand)
        signal = ConfidenceStrategy().evaluate(
            cand, req, self.policy, other_signals=())
        self.assertTrue(signal.has_evidences)
        self.assertEqual(signal.evidence_count, 1)

    def test_all_strategies_produce_evidences(self):
        """Todas as 8 strategies devem produzir ao menos 1 evidence."""
        ctx = _MockContext(
            book="João", chapter=21,
            recent_references=(_MockReference("João", 21, 15),),
            last_reference=_MockReference("João", 21, 15),
            recent_themes=("fé",),
            recent_books=("João",),
        )
        cand = CandidateInfo("43:21:15", 0.8, "João", 21, 15, "João 21:15 fé")
        summary = _MockFeedbackSummary(True, 7.0, 5, 1)
        metrics = _MockMetrics(precision=0.85, total_searches=100)
        req = self._make_request(
            ctx, cand,
            feedback_summaries={cand.candidate_id: summary},
            evaluation_metrics=metrics)

        strategies = all_strategies()
        for strat in strategies:
            signal = strat.evaluate(cand, req, self.policy)
            self.assertTrue(
                signal.has_evidences,
                f"{strat.__class__.__name__} não produziu evidences"
            )


if __name__ == "__main__":
    unittest.main()
