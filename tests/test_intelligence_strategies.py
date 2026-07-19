"""Testes de estratégias (Fase 11 — Parte 2).

Cobre:
  - ContextStrategy: contexto ativo, livro/capítulo match, sem contexto.
  - FeedbackStrategy: feedback positivo, negativo, neutro, sem feedback.
  - ContinuityStrategy: continuidade forte, parcial, sem continuidade.
  - ReferenceStrategy: repetição, sem repetição.
  - ThemeStrategy: tema correspondente, sem correspondência.
  - BookStrategy: livro recente, não recente.
  - ConfidenceStrategy: consistência alta, baixa, mista.
  - EvaluationStrategy: precisão alta, baixa, sem métricas.
"""

from __future__ import annotations

import unittest

import sys
sys.path.insert(0, ".")

from intelligence import (
    BookStrategy,
    CandidateInfo,
    ConfidenceStrategy,
    ContextStrategy,
    ContinuityStrategy,
    EvaluationStrategy,
    FeedbackStrategy,
    IntelligencePolicy,
    IntelligenceRequest,
    IntelligenceSignal,
    ReferenceStrategy,
    ThemeStrategy,
)


def make_candidate(cid="43:21:15", score=0.83, book="João",
                   chapter=21, verse=15, display="João 21:15"):
    return CandidateInfo(candidate_id=cid, base_score=score, book=book,
                         chapter=chapter, verse=verse, display=display)


def make_request(query="pedro", context=None, candidates=(),
                 feedback_summaries=None, evaluation_metrics=None):
    return IntelligenceRequest(
        query=query, context=context, candidates=candidates,
        feedback_summaries=feedback_summaries or {},
        evaluation_metrics=evaluation_metrics,
    )


class FakeContext:
    """Contexto fake para testes (duck-typed)."""
    def __init__(self, book=None, chapter=None, recent_references=(),
                 recent_themes=(), recent_books=(), last_reference=None):
        self.book = book
        self.chapter = chapter
        self.recent_references = recent_references
        self.recent_themes = recent_themes
        self.recent_books = recent_books
        self.last_reference = last_reference


class FakeRef:
    """Referência fake para testes."""
    def __init__(self, book_name="João", chapter=21, verse=15):
        self.book = type("FakeBook", (), {"canonical_name": book_name})()
        self.chapter = chapter
        self.verse_start = verse


class FakeSummary:
    """FeedbackSummary fake para testes."""
    def __init__(self, has_feedback=True, total_weight=9.0,
                 acceptances=3, rejections=0):
        self.has_feedback = has_feedback
        self.total_weight = total_weight
        self.acceptances = acceptances
        self.rejections = rejections


class FakeMetrics:
    """EvaluationMetrics fake para testes."""
    def __init__(self, precision=0.85, total_searches=150):
        self.precision = precision
        self.total_searches = total_searches


# ---------------------------------------------------------------------------
# ContextStrategy
# ---------------------------------------------------------------------------


class TestContextStrategy(unittest.TestCase):

    def setUp(self):
        self.strategy = ContextStrategy()
        self.policy = IntelligencePolicy()

    def test_no_context(self):
        c = make_candidate()
        r = make_request(context=None, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)

    def test_book_match(self):
        ctx = FakeContext(book="João", chapter=None)
        c = make_candidate(book="João")
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertGreater(s.value, 0.0)
        self.assertIn("corresponde", s.explanation)

    def test_chapter_match(self):
        ctx = FakeContext(book="João", chapter=21)
        c = make_candidate(book="João", chapter=21)
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertGreater(s.value, 0.0)
        self.assertIn("corresponde", s.explanation)

    def test_no_match(self):
        ctx = FakeContext(book="Lucas", chapter=15)
        c = make_candidate(book="João", chapter=21)
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)

    def test_chapter_bonus_greater(self):
        ctx_ch = FakeContext(book="João", chapter=21)
        ctx_bk = FakeContext(book="João", chapter=None)
        c = make_candidate(book="João", chapter=21)
        s_ch = self.strategy.evaluate(c, make_request(context=ctx_ch), self.policy)
        s_bk = self.strategy.evaluate(c, make_request(context=ctx_bk), self.policy)
        self.assertGreater(s_ch.value, s_bk.value)


# ---------------------------------------------------------------------------
# FeedbackStrategy
# ---------------------------------------------------------------------------


class TestFeedbackStrategy(unittest.TestCase):

    def setUp(self):
        self.strategy = FeedbackStrategy()
        self.policy = IntelligencePolicy()

    def test_no_feedback(self):
        c = make_candidate()
        r = make_request(candidates=(c,), feedback_summaries={})
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)

    def test_positive_feedback_strong(self):
        c = make_candidate()
        summary = FakeSummary(total_weight=10.0, acceptances=5)
        r = make_request(candidates=(c,),
                         feedback_summaries={c.candidate_id: summary})
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertGreater(s.value, 0.0)
        self.assertIn("positivo", s.explanation)

    def test_positive_feedback_weak(self):
        c = make_candidate()
        summary = FakeSummary(total_weight=3.0, acceptances=1)
        r = make_request(candidates=(c,),
                         feedback_summaries={c.candidate_id: summary})
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertGreater(s.value, 0.0)

    def test_negative_feedback(self):
        c = make_candidate()
        summary = FakeSummary(total_weight=-3.0, acceptances=0, rejections=3)
        r = make_request(candidates=(c,),
                         feedback_summaries={c.candidate_id: summary})
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertLess(s.value, 0.0)
        self.assertIn("negativo", s.explanation)

    def test_neutral_feedback(self):
        c = make_candidate()
        summary = FakeSummary(total_weight=0.0, acceptances=0, rejections=0)
        r = make_request(candidates=(c,),
                         feedback_summaries={c.candidate_id: summary})
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)

    def test_has_feedback_false(self):
        c = make_candidate()
        summary = FakeSummary(has_feedback=False)
        r = make_request(candidates=(c,),
                         feedback_summaries={c.candidate_id: summary})
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)


# ---------------------------------------------------------------------------
# ContinuityStrategy
# ---------------------------------------------------------------------------


class TestContinuityStrategy(unittest.TestCase):

    def setUp(self):
        self.strategy = ContinuityStrategy()
        self.policy = IntelligencePolicy()

    def test_no_recent_refs(self):
        ctx = FakeContext(recent_references=())
        c = make_candidate()
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)

    def test_continuity_same_book_chapter(self):
        ref = FakeRef(book_name="João", chapter=21, verse=15)
        ctx = FakeContext(recent_references=(ref,))
        c = make_candidate(book="João", chapter=21)
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertGreater(s.value, 0.0)
        self.assertIn("Continuidade", s.explanation)

    def test_continuity_same_book_only(self):
        ref = FakeRef(book_name="João", chapter=21)
        ctx = FakeContext(recent_references=(ref,))
        c = make_candidate(book="João", chapter=3)
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertGreater(s.value, 0.0)
        self.assertIn("parcial", s.explanation)

    def test_no_continuity(self):
        ref = FakeRef(book_name="Lucas", chapter=15)
        ctx = FakeContext(recent_references=(ref,))
        c = make_candidate(book="João", chapter=21)
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)


# ---------------------------------------------------------------------------
# ReferenceStrategy
# ---------------------------------------------------------------------------


class TestReferenceStrategy(unittest.TestCase):

    def setUp(self):
        self.strategy = ReferenceStrategy()
        self.policy = IntelligencePolicy()

    def test_no_last_reference(self):
        ctx = FakeContext(last_reference=None)
        c = make_candidate()
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)

    def test_exact_match(self):
        ref = FakeRef(book_name="João", chapter=21, verse=15)
        ctx = FakeContext(last_reference=ref)
        c = make_candidate(book="João", chapter=21, verse=15)
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertGreater(s.value, 0.0)
        self.assertIn("última referência", s.explanation)

    def test_no_match(self):
        ref = FakeRef(book_name="Lucas", chapter=15, verse=11)
        ctx = FakeContext(last_reference=ref)
        c = make_candidate(book="João", chapter=21, verse=15)
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)


# ---------------------------------------------------------------------------
# ThemeStrategy
# ---------------------------------------------------------------------------


class TestThemeStrategy(unittest.TestCase):

    def setUp(self):
        self.strategy = ThemeStrategy()
        self.policy = IntelligencePolicy()

    def test_no_themes(self):
        ctx = FakeContext(recent_themes=())
        c = make_candidate()
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)

    def test_theme_match(self):
        ctx = FakeContext(recent_themes=("graça", "salvação"))
        c = make_candidate(display="graça de Deus em João 3:16")
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertGreater(s.value, 0.0)
        self.assertIn("graça", s.explanation)

    def test_no_theme_match(self):
        ctx = FakeContext(recent_themes=("graça",))
        c = make_candidate(display="João 21:15")
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)

    def test_no_display(self):
        ctx = FakeContext(recent_themes=("graça",))
        c = make_candidate(display="")
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)


# ---------------------------------------------------------------------------
# BookStrategy
# ---------------------------------------------------------------------------


class TestBookStrategy(unittest.TestCase):

    def setUp(self):
        self.strategy = BookStrategy()
        self.policy = IntelligencePolicy()

    def test_no_recent_books(self):
        ctx = FakeContext(recent_books=())
        c = make_candidate(book="João")
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)

    def test_book_in_recent(self):
        ctx = FakeContext(recent_books=("João", "Lucas"))
        c = make_candidate(book="João")
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertGreater(s.value, 0.0)
        self.assertIn("recentemente", s.explanation)

    def test_book_not_in_recent(self):
        ctx = FakeContext(recent_books=("Lucas", "Atos"))
        c = make_candidate(book="João")
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)

    def test_no_book_in_candidate(self):
        ctx = FakeContext(recent_books=("João",))
        c = make_candidate(book="")
        r = make_request(context=ctx, candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)


# ---------------------------------------------------------------------------
# ConfidenceStrategy
# ---------------------------------------------------------------------------


class TestConfidenceStrategy(unittest.TestCase):

    def setUp(self):
        self.strategy = ConfidenceStrategy()
        self.policy = IntelligencePolicy()

    def test_no_signals(self):
        c = make_candidate()
        r = make_request(candidates=(c,))
        s = self.strategy.evaluate(c, r, self.policy, other_signals=())
        self.assertEqual(s.value, 0.0)

    def test_all_positive(self):
        c = make_candidate()
        r = make_request(candidates=(c,))
        signals = (
            IntelligenceSignal(signal_type="context", value=0.1, weight=0.2),
            IntelligenceSignal(signal_type="feedback", value=0.1, weight=0.2),
        )
        s = self.strategy.evaluate(c, r, self.policy, other_signals=signals)
        self.assertGreater(s.value, 0.0)
        self.assertIn("Alta consistência", s.explanation)

    def test_all_negative(self):
        c = make_candidate()
        r = make_request(candidates=(c,))
        signals = (
            IntelligenceSignal(signal_type="context", value=-0.1, weight=0.2),
            IntelligenceSignal(signal_type="feedback", value=-0.1, weight=0.2),
        )
        s = self.strategy.evaluate(c, r, self.policy, other_signals=signals)
        self.assertLess(s.value, 0.0)
        self.assertIn("Baixa consistência", s.explanation)

    def test_mixed(self):
        c = make_candidate()
        r = make_request(candidates=(c,))
        signals = (
            IntelligenceSignal(signal_type="context", value=0.1, weight=0.2),
            IntelligenceSignal(signal_type="feedback", value=-0.1, weight=0.2),
        )
        s = self.strategy.evaluate(c, r, self.policy, other_signals=signals)
        self.assertIn("mista", s.explanation)


# ---------------------------------------------------------------------------
# EvaluationStrategy
# ---------------------------------------------------------------------------


class TestEvaluationStrategy(unittest.TestCase):

    def setUp(self):
        self.strategy = EvaluationStrategy()
        self.policy = IntelligencePolicy()

    def test_no_metrics(self):
        c = make_candidate()
        r = make_request(candidates=(c,), evaluation_metrics=None)
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)

    def test_high_precision(self):
        c = make_candidate()
        r = make_request(candidates=(c,),
                         evaluation_metrics=FakeMetrics(precision=0.90, total_searches=100))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertGreater(s.value, 0.0)
        self.assertIn("positiva", s.explanation)

    def test_low_precision(self):
        c = make_candidate()
        r = make_request(candidates=(c,),
                         evaluation_metrics=FakeMetrics(precision=0.40, total_searches=100))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertLess(s.value, 0.0)
        self.assertIn("negativa", s.explanation)

    def test_neutral_precision(self):
        c = make_candidate()
        r = make_request(candidates=(c,),
                         evaluation_metrics=FakeMetrics(precision=0.60, total_searches=100))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)

    def test_too_few_searches(self):
        c = make_candidate()
        r = make_request(candidates=(c,),
                         evaluation_metrics=FakeMetrics(precision=0.90, total_searches=5))
        s = self.strategy.evaluate(c, r, self.policy)
        self.assertEqual(s.value, 0.0)
        self.assertIn("Poucas", s.explanation)


if __name__ == "__main__":
    unittest.main()
