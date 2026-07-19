"""Testes de DTOs, sinais e policy (Fase 11 — Parte 1).

Cobre:
  - ConfidenceLevel (enum, valores).
  - CandidateInfo (imutabilidade, serialização).
  - IntelligenceRequest (imutabilidade, defaults).
  - IntelligenceSignal (imutabilidade, contribution, herança).
  - IntelligenceScore (imutabilidade, properties, explain, serialização).
  - IntelligenceRecommendation (imutabilidade, properties, explain).
  - Sinais tipados (8 ativos + 6 futuros, imutabilidade, signal_type).
  - Registry de sinais.
  - IntelligencePolicy (pesos, limites, bônus, confiança, cap).
"""

from __future__ import annotations

import unittest

import sys
sys.path.insert(0, ".")

from intelligence import (
    ACTIVE_SIGNAL_TYPES,
    ALL_SIGNAL_TYPES,
    BookSignal,
    CandidateInfo,
    ChurchProfileSignal,
    ConfidenceLevel,
    ConfidenceSignal,
    ContextSignal,
    ContinuitySignal,
    EmotionSignal,
    EvaluationSignal,
    FeedbackSignal,
    FUTURE_SIGNAL_TYPES,
    IntelligencePolicy,
    IntelligenceRecommendation,
    IntelligenceRequest,
    IntelligenceScore,
    IntelligenceSignal,
    LanguageSignal,
    OperatorSignal,
    ReferenceSignal,
    SemanticSignal,
    TemporalSignal,
    ThemeSignal,
)


# ---------------------------------------------------------------------------
# ConfidenceLevel
# ---------------------------------------------------------------------------


class TestConfidenceLevel(unittest.TestCase):

    def test_low(self):
        self.assertEqual(ConfidenceLevel.LOW.value, "LOW")

    def test_medium(self):
        self.assertEqual(ConfidenceLevel.MEDIUM.value, "MEDIUM")

    def test_high(self):
        self.assertEqual(ConfidenceLevel.HIGH.value, "HIGH")

    def test_from_string(self):
        self.assertIs(ConfidenceLevel("HIGH"), ConfidenceLevel.HIGH)

    def test_is_str_enum(self):
        self.assertIsInstance(ConfidenceLevel.LOW, str)


# ---------------------------------------------------------------------------
# CandidateInfo
# ---------------------------------------------------------------------------


class TestCandidateInfo(unittest.TestCase):

    def test_creation(self):
        c = CandidateInfo(candidate_id="43:21:15", base_score=0.83,
                          book="João", chapter=21, verse=15)
        self.assertEqual(c.candidate_id, "43:21:15")
        self.assertEqual(c.base_score, 0.83)
        self.assertEqual(c.book, "João")

    def test_defaults(self):
        c = CandidateInfo(candidate_id="x", base_score=0.5)
        self.assertEqual(c.book, "")
        self.assertIsNone(c.chapter)

    def test_frozen(self):
        c = CandidateInfo(candidate_id="x", base_score=0.5)
        with self.assertRaises(Exception):
            c.base_score = 0.9

    def test_to_dict(self):
        c = CandidateInfo(candidate_id="43:21:15", base_score=0.83,
                          book="João", chapter=21)
        d = c.to_dict()
        self.assertEqual(d["candidate_id"], "43:21:15")
        self.assertEqual(d["book"], "João")


# ---------------------------------------------------------------------------
# IntelligenceRequest
# ---------------------------------------------------------------------------


class TestIntelligenceRequest(unittest.TestCase):

    def test_defaults(self):
        r = IntelligenceRequest(query="pedro")
        self.assertEqual(r.query, "pedro")
        self.assertIsNone(r.context)
        self.assertEqual(r.candidates, ())
        self.assertEqual(r.feedback_summaries, {})
        self.assertIsNone(r.evaluation_metrics)

    def test_frozen(self):
        r = IntelligenceRequest(query="pedro")
        with self.assertRaises(Exception):
            r.query = "outro"

    def test_to_dict(self):
        r = IntelligenceRequest(query="pedro")
        d = r.to_dict()
        self.assertEqual(d["query"], "pedro")
        self.assertFalse(d["has_context"])


# ---------------------------------------------------------------------------
# IntelligenceSignal
# ---------------------------------------------------------------------------


class TestIntelligenceSignal(unittest.TestCase):

    def test_creation(self):
        s = IntelligenceSignal(signal_type="context", value=0.15,
                               weight=0.20, explanation="match")
        self.assertEqual(s.signal_type, "context")
        self.assertEqual(s.value, 0.15)

    def test_frozen(self):
        s = IntelligenceSignal(signal_type="x", value=0.1, weight=0.2)
        with self.assertRaises(Exception):
            s.value = 0.5

    def test_contribution(self):
        s = IntelligenceSignal(signal_type="x", value=0.15, weight=0.20)
        self.assertAlmostEqual(s.contribution, 0.03)

    def test_contribution_negative(self):
        s = IntelligenceSignal(signal_type="x", value=-0.10, weight=0.25)
        self.assertAlmostEqual(s.contribution, -0.025)

    def test_to_dict(self):
        s = IntelligenceSignal(signal_type="context", value=0.15,
                               weight=0.20, explanation="match")
        d = s.to_dict()
        self.assertEqual(d["signal_type"], "context")
        self.assertAlmostEqual(d["contribution"], 0.03)


# ---------------------------------------------------------------------------
# IntelligenceScore
# ---------------------------------------------------------------------------


class TestIntelligenceScore(unittest.TestCase):

    def test_creation(self):
        s = IntelligenceScore(candidate_id="43:21:15", base_score=0.83,
                              final_score=0.90)
        self.assertEqual(s.candidate_id, "43:21:15")
        self.assertAlmostEqual(s.final_score, 0.90)

    def test_frozen(self):
        s = IntelligenceScore(candidate_id="x", base_score=0.5,
                              final_score=0.6)
        with self.assertRaises(Exception):
            s.final_score = 1.0

    def test_total_contribution(self):
        s = IntelligenceScore(
            candidate_id="x", base_score=0.80, final_score=0.90,
            context_contribution=0.03, feedback_contribution=0.04,
            continuity_contribution=0.02,
        )
        self.assertAlmostEqual(s.total_contribution, 0.09)

    def test_explain(self):
        s = IntelligenceScore(
            candidate_id="x", base_score=0.83, final_score=0.90,
            context_contribution=0.03, feedback_contribution=0.04,
            confidence_level=ConfidenceLevel.HIGH,
        )
        text = s.explain()
        self.assertIn("Base", text)
        self.assertIn("Contexto", text)
        self.assertIn("Feedback", text)
        self.assertIn("HIGH", text)

    def test_to_dict(self):
        s = IntelligenceScore(candidate_id="x", base_score=0.83,
                              final_score=0.90)
        d = s.to_dict()
        self.assertEqual(d["candidate_id"], "x")
        self.assertEqual(d["confidence_level"], "LOW")


# ---------------------------------------------------------------------------
# IntelligenceRecommendation
# ---------------------------------------------------------------------------


class TestIntelligenceRecommendation(unittest.TestCase):

    def test_empty(self):
        r = IntelligenceRecommendation(query="pedro")
        self.assertEqual(r.scores, ())
        self.assertIsNone(r.best_score)
        self.assertEqual(r.ranking, ())

    def test_frozen(self):
        r = IntelligenceRecommendation(query="x")
        with self.assertRaises(Exception):
            r.query = "y"

    def test_best_score(self):
        s1 = IntelligenceScore(candidate_id="a", base_score=0.8,
                                final_score=0.9)
        s2 = IntelligenceScore(candidate_id="b", base_score=0.7,
                                final_score=0.8)
        r = IntelligenceRecommendation(query="x", scores=(s1, s2))
        self.assertEqual(r.best_score, s1)

    def test_ranking(self):
        s1 = IntelligenceScore(candidate_id="a", base_score=0.8,
                                final_score=0.9)
        s2 = IntelligenceScore(candidate_id="b", base_score=0.7,
                                final_score=0.8)
        r = IntelligenceRecommendation(query="x", scores=(s1, s2))
        self.assertEqual(r.ranking, ("a", "b"))

    def test_explain_empty(self):
        r = IntelligenceRecommendation(query="x", has_candidates=False)
        text = r.explain()
        self.assertIn("sem candidatos", text)

    def test_explain_with_scores(self):
        s = IntelligenceScore(candidate_id="a", base_score=0.8,
                               final_score=0.9,
                               confidence_level=ConfidenceLevel.HIGH)
        r = IntelligenceRecommendation(query="x", scores=(s,),
                                       has_candidates=True)
        text = r.explain()
        self.assertIn("recomendação", text)

    def test_to_dict(self):
        r = IntelligenceRecommendation(query="x")
        d = r.to_dict()
        self.assertEqual(d["query"], "x")


# ---------------------------------------------------------------------------
# Sinais tipados
# ---------------------------------------------------------------------------


class TestSignalsTyped(unittest.TestCase):

    def test_context_signal_type(self):
        s = ContextSignal(value=0.1, weight=0.2)
        self.assertEqual(s.signal_type, "context")

    def test_feedback_signal_type(self):
        s = FeedbackSignal(value=0.1, weight=0.2)
        self.assertEqual(s.signal_type, "feedback")

    def test_continuity_signal_type(self):
        s = ContinuitySignal(value=0.1, weight=0.2)
        self.assertEqual(s.signal_type, "continuity")

    def test_reference_signal_type(self):
        s = ReferenceSignal(value=0.1, weight=0.2)
        self.assertEqual(s.signal_type, "reference")

    def test_theme_signal_type(self):
        s = ThemeSignal(value=0.1, weight=0.2)
        self.assertEqual(s.signal_type, "theme")

    def test_book_signal_type(self):
        s = BookSignal(value=0.1, weight=0.2)
        self.assertEqual(s.signal_type, "book")

    def test_confidence_signal_type(self):
        s = ConfidenceSignal(value=0.1, weight=0.2)
        self.assertEqual(s.signal_type, "confidence")

    def test_evaluation_signal_type(self):
        s = EvaluationSignal(value=0.1, weight=0.2)
        self.assertEqual(s.signal_type, "evaluation")

    def test_all_inherit_base(self):
        self.assertIsInstance(ContextSignal(), IntelligenceSignal)
        self.assertIsInstance(FeedbackSignal(), IntelligenceSignal)

    def test_all_frozen(self):
        s = ContextSignal(value=0.1, weight=0.2)
        with self.assertRaises(Exception):
            s.value = 0.5


class TestFutureSignals(unittest.TestCase):

    def test_semantic_signal_type(self):
        self.assertEqual(SemanticSignal().signal_type, "semantic")

    def test_operator_signal_type(self):
        self.assertEqual(OperatorSignal().signal_type, "operator")

    def test_church_profile_signal_type(self):
        self.assertEqual(ChurchProfileSignal().signal_type, "church_profile")

    def test_language_signal_type(self):
        self.assertEqual(LanguageSignal().signal_type, "language")

    def test_temporal_signal_type(self):
        self.assertEqual(TemporalSignal().signal_type, "temporal")

    def test_emotion_signal_type(self):
        self.assertEqual(EmotionSignal().signal_type, "emotion")


class TestSignalRegistry(unittest.TestCase):

    def test_active_signals_count(self):
        self.assertEqual(len(ACTIVE_SIGNAL_TYPES), 8)

    def test_future_signals_count(self):
        self.assertEqual(len(FUTURE_SIGNAL_TYPES), 6)

    def test_all_signals_count(self):
        self.assertEqual(len(ALL_SIGNAL_TYPES), 14)

    def test_active_contains_context(self):
        self.assertIn("context", ACTIVE_SIGNAL_TYPES)

    def test_future_contains_semantic(self):
        self.assertIn("semantic", FUTURE_SIGNAL_TYPES)

    def test_no_overlap(self):
        active_set = set(ACTIVE_SIGNAL_TYPES)
        future_set = set(FUTURE_SIGNAL_TYPES)
        self.assertEqual(active_set & future_set, set())


# ---------------------------------------------------------------------------
# IntelligencePolicy
# ---------------------------------------------------------------------------


class TestIntelligencePolicy(unittest.TestCase):

    def setUp(self):
        self.policy = IntelligencePolicy()

    def test_weights_positive(self):
        self.assertGreater(self.policy.weight_context, 0)
        self.assertGreater(self.policy.weight_feedback, 0)
        self.assertGreater(self.policy.weight_continuity, 0)

    def test_total_weight(self):
        self.assertGreater(self.policy.total_weight, 0)

    def test_max_adjustment(self):
        self.assertGreater(self.policy.max_intelligence_adjustment, 0)

    def test_min_adjustment(self):
        self.assertLess(self.policy.min_intelligence_adjustment, 0)

    def test_cap_adjustment_within_bounds(self):
        self.assertAlmostEqual(
            self.policy.cap_adjustment(0.05), 0.05)

    def test_cap_adjustment_above_max(self):
        self.assertAlmostEqual(
            self.policy.cap_adjustment(1.0),
            self.policy.max_intelligence_adjustment)

    def test_cap_adjustment_below_min(self):
        self.assertAlmostEqual(
            self.policy.cap_adjustment(-1.0),
            self.policy.min_intelligence_adjustment)

    def test_confidence_low(self):
        c = self.policy.confidence_from_signals_and_score(1, 0.50)
        self.assertEqual(c, ConfidenceLevel.LOW)

    def test_confidence_medium(self):
        c = self.policy.confidence_from_signals_and_score(3, 0.70)
        self.assertEqual(c, ConfidenceLevel.MEDIUM)

    def test_confidence_high(self):
        c = self.policy.confidence_from_signals_and_score(5, 0.90)
        self.assertEqual(c, ConfidenceLevel.HIGH)

    def test_confidence_low_score(self):
        # Muitos sinais mas score baixo → LOW
        c = self.policy.confidence_from_signals_and_score(10, 0.40)
        self.assertEqual(c, ConfidenceLevel.LOW)

    def test_all_weights(self):
        w = self.policy.all_weights()
        self.assertIn("context", w)
        self.assertIn("feedback", w)
        self.assertEqual(len(w), 8)

    def test_bonuses_positive(self):
        self.assertGreater(self.policy.context_book_match_bonus, 0)
        self.assertGreater(self.policy.context_chapter_match_bonus, 0)
        self.assertGreater(self.policy.feedback_strong_bonus, 0)

    def test_chapter_bonus_greater_than_book(self):
        # Capítulo é mais específico → bônus maior
        self.assertGreaterEqual(
            self.policy.context_chapter_match_bonus,
            self.policy.context_book_match_bonus)


if __name__ == "__main__":
    unittest.main()
