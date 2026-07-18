"""Testes de FeedbackEngine e RankingFeedbackAdapter (Fase 9 — Parte 3).

Cobre:
  - FeedbackEngine: process() para cada evento, get_statistics,
    get_summary, increment_decay, apply_all_decay, reset, flush.
  - RankingFeedbackAdapter: adjust, adjust_batch, get_feedback_summary.
  - Contexto: assinatura diferente = chave diferente.
  - Limite máximo: feedback nunca vence sozinho.
  - Score baixo: feedback não aplicado.
  - Explicabilidade: ScoreBreakdown.explain().
  - Desacoplamento: engine e adapter não conhecem outros componentes.
"""

from __future__ import annotations

import os
import tempfile
import unittest

import sys
sys.path.insert(0, ".")

from feedback import (
    CandidateAccepted,
    CandidateRejected,
    FeedbackEngine,
    FeedbackKey,
    FeedbackRepository,
    FeedbackScope,
    FeedbackStore,
    LearningPolicy,
    ManualReferenceSelected,
    ManualSearch,
    RankingFeedbackAdapter,
    ScoreBreakdown,
    SuggestionIgnored,
    context_signature_from_sermon_context,
)


def make_engine(clock_start=1000.0):
    clock = [clock_start]
    def fake_clock():
        clock[0] += 1.0
        return clock[0]
    repo = FeedbackRepository()
    return FeedbackEngine(repo, clock=fake_clock), repo


def make_key(scope=FeedbackScope.GLOBAL, query="pedro",
             ctx="João", cid="43:21:15"):
    return FeedbackKey(scope=scope, query=query,
                       context_signature=ctx, candidate_id=cid)


# ---------------------------------------------------------------------------
# FeedbackEngine — process()
# ---------------------------------------------------------------------------


class TestEngineProcessAccepted(unittest.TestCase):

    def test_process_accepted_creates_stats(self):
        engine, _ = make_engine()
        key = make_key()
        stats = engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        self.assertEqual(stats.acceptances, 1)
        self.assertEqual(stats.total_weight, 3.0)
        self.assertEqual(stats.first_used, 1001.0)
        self.assertEqual(stats.last_used, 1001.0)

    def test_process_accepted_multiple(self):
        engine, _ = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        engine.process(CandidateAccepted(key=key, timestamp=1002.0))
        stats = engine.process(CandidateAccepted(key=key, timestamp=1003.0))
        self.assertEqual(stats.acceptances, 3)
        self.assertEqual(stats.total_weight, 9.0)
        self.assertEqual(stats.first_used, 1001.0)
        self.assertEqual(stats.last_used, 1003.0)

    def test_process_persists_to_repository(self):
        engine, repo = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        self.assertIsNotNone(repo.get(key))


class TestEngineProcessRejected(unittest.TestCase):

    def test_process_rejected(self):
        engine, _ = make_engine()
        key = make_key()
        stats = engine.process(CandidateRejected(key=key, timestamp=1001.0))
        self.assertEqual(stats.rejections, 1)
        self.assertEqual(stats.total_weight, -1.0)


class TestEngineProcessManualReference(unittest.TestCase):

    def test_process_manual_reference(self):
        engine, _ = make_engine()
        key = make_key()
        stats = engine.process(
            ManualReferenceSelected(key=key, timestamp=1001.0))
        self.assertEqual(stats.manual_selections, 1)
        self.assertEqual(stats.total_weight, 5.0)


class TestEngineProcessSuggestionIgnored(unittest.TestCase):

    def test_process_suggestion_ignored(self):
        engine, _ = make_engine()
        key = make_key()
        stats = engine.process(SuggestionIgnored(key=key, timestamp=1001.0))
        self.assertEqual(stats.ignored, 1)
        self.assertEqual(stats.total_weight, -2.0)


class TestEngineProcessManualSearch(unittest.TestCase):

    def test_process_manual_search_neutral(self):
        engine, _ = make_engine()
        key = make_key()
        stats = engine.process(ManualSearch(key=key, timestamp=1001.0))
        # ManualSearch tem peso 0 e não incrementa contadores específicos
        self.assertEqual(stats.total_weight, 0.0)
        # total_events soma os 4 contadores específicos (0 para ManualSearch)
        self.assertEqual(stats.total_events, 0)
        # Mas last_used é atualizado
        self.assertEqual(stats.last_used, 1001.0)


# ---------------------------------------------------------------------------
# FeedbackEngine — consultas
# ---------------------------------------------------------------------------


class TestEngineQueries(unittest.TestCase):

    def test_get_statistics_nonexistent(self):
        engine, _ = make_engine()
        self.assertIsNone(engine.get_statistics(make_key()))

    def test_get_statistics_existing(self):
        engine, _ = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        stats = engine.get_statistics(key)
        self.assertIsNotNone(stats)
        self.assertEqual(stats.acceptances, 1)

    def test_get_summary_nonexistent(self):
        engine, _ = make_engine()
        summary = engine.get_summary(make_key())
        self.assertFalse(summary.has_feedback)
        self.assertEqual(summary.total_events, 0)

    def test_get_summary_existing(self):
        engine, _ = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        engine.process(CandidateAccepted(key=key, timestamp=1002.0))
        summary = engine.get_summary(key)
        self.assertTrue(summary.has_feedback)
        self.assertEqual(summary.total_events, 2)
        self.assertEqual(summary.acceptances, 2)
        self.assertEqual(summary.total_weight, 6.0)


# ---------------------------------------------------------------------------
# FeedbackEngine — decaimento
# ---------------------------------------------------------------------------


class TestEngineDecay(unittest.TestCase):

    def test_increment_decay(self):
        engine, _ = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        stats = engine.increment_decay(key)
        self.assertIsNotNone(stats)
        self.assertEqual(stats.decay_count, 1)

    def test_increment_decay_nonexistent(self):
        engine, _ = make_engine()
        self.assertIsNone(engine.increment_decay(make_key()))

    def test_increment_decay_multiple(self):
        engine, _ = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        for _ in range(5):
            engine.increment_decay(key)
        stats = engine.get_statistics(key)
        self.assertEqual(stats.decay_count, 5)

    def test_apply_all_decay(self):
        engine, _ = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        # Incrementar decaimento além do intervalo
        policy = engine.policy
        for _ in range(policy.decay_interval + 1):
            engine.increment_decay(key)
        count = engine.apply_all_decay()
        self.assertGreaterEqual(count, 1)


# ---------------------------------------------------------------------------
# FeedbackEngine — reset e flush
# ---------------------------------------------------------------------------


class TestEngineResetFlush(unittest.TestCase):

    def test_reset_clears_all(self):
        engine, repo = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        self.assertEqual(len(repo), 1)
        engine.reset()
        self.assertEqual(len(repo), 0)

    def test_flush_persists(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            repo = FeedbackRepository(tmp)
            engine = FeedbackEngine(repo)
            key = make_key()
            engine.process(CandidateAccepted(key=key, timestamp=1001.0))
            engine.flush()
            self.assertTrue(os.path.exists(tmp))
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


# ---------------------------------------------------------------------------
# RankingFeedbackAdapter — adjust()
# ---------------------------------------------------------------------------


class TestAdapterNoFeedback(unittest.TestCase):

    def test_no_feedback_returns_base_score(self):
        engine, _ = make_engine()
        adapter = RankingFeedbackAdapter(engine)
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="João")
        self.assertEqual(b.final_score, 0.83)
        self.assertFalse(b.has_feedback)
        self.assertEqual(b.feedback_bonus, 0.0)

    def test_no_feedback_no_summary(self):
        engine, _ = make_engine()
        adapter = RankingFeedbackAdapter(engine)
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83)
        self.assertIsNone(b.feedback_summary)


class TestAdapterWithFeedback(unittest.TestCase):

    def test_positive_feedback_increases_score(self):
        engine, _ = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        adapter = RankingFeedbackAdapter(engine)
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="João")
        self.assertTrue(b.has_feedback)
        self.assertGreater(b.feedback_bonus, 0.0)
        self.assertGreater(b.final_score, 0.83)

    def test_negative_feedback_decreases_score(self):
        engine, _ = make_engine()
        key = make_key()
        engine.process(CandidateRejected(key=key, timestamp=1001.0))
        engine.process(CandidateRejected(key=key, timestamp=1002.0))
        engine.process(CandidateRejected(key=key, timestamp=1003.0))
        adapter = RankingFeedbackAdapter(engine)
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="João")
        self.assertTrue(b.has_feedback)
        self.assertLess(b.feedback_bonus, 0.0)
        self.assertLess(b.final_score, 0.83)

    def test_feedback_capped_at_max(self):
        engine, _ = make_engine()
        key = make_key()
        # Muitas aceitações → peso enorme → bônus satura no teto
        for _ in range(20):
            engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        adapter = RankingFeedbackAdapter(engine)
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="João")
        self.assertTrue(b.feedback_capped)
        self.assertEqual(b.feedback_bonus, adapter.policy.max_feedback_bonus)

    def test_feedback_does_not_exceed_max_bonus(self):
        engine, _ = make_engine()
        key = make_key()
        for _ in range(100):
            engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        adapter = RankingFeedbackAdapter(engine)
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="João")
        self.assertLessEqual(b.feedback_bonus, adapter.policy.max_feedback_bonus)


class TestAdapterLowScore(unittest.TestCase):

    def test_low_score_no_feedback_applied(self):
        engine, _ = make_engine()
        key = make_key()
        for _ in range(10):
            engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        adapter = RankingFeedbackAdapter(engine)
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.05, context_signature="João")
        self.assertFalse(b.has_feedback)
        self.assertEqual(b.feedback_bonus, 0.0)
        self.assertEqual(b.final_score, 0.05)

    def test_score_at_boundary_applies(self):
        engine, _ = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        adapter = RankingFeedbackAdapter(engine)
        boundary = adapter.policy.min_base_score_for_feedback
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=boundary, context_signature="João")
        self.assertTrue(b.has_feedback)


# ---------------------------------------------------------------------------
# RankingFeedbackAdapter — contexto
# ---------------------------------------------------------------------------


class TestAdapterContext(unittest.TestCase):

    def test_different_context_no_feedback(self):
        engine, _ = make_engine()
        key = make_key(ctx="João")
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        adapter = RankingFeedbackAdapter(engine)
        # Contexto diferente → não há feedback
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="Atos")
        self.assertFalse(b.has_feedback)

    def test_same_context_has_feedback(self):
        engine, _ = make_engine()
        key = make_key(ctx="João")
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        adapter = RankingFeedbackAdapter(engine)
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="João")
        self.assertTrue(b.has_feedback)

    def test_empty_context_separate_from_filled(self):
        engine, _ = make_engine()
        key_empty = make_key(ctx="")
        engine.process(CandidateAccepted(key=key_empty, timestamp=1001.0))
        adapter = RankingFeedbackAdapter(engine)
        # Com contexto "João" → não acha (foi registrado sem contexto)
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="João")
        self.assertFalse(b.has_feedback)
        # Sem contexto → acha
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="")
        self.assertTrue(b.has_feedback)


# ---------------------------------------------------------------------------
# RankingFeedbackAdapter — adjust_batch
# ---------------------------------------------------------------------------


class TestAdapterBatch(unittest.TestCase):

    def test_batch_same_order(self):
        engine, _ = make_engine()
        adapter = RankingFeedbackAdapter(engine)
        candidates = (("43:3:16", 0.83), ("42:15:11", 0.75), ("40:5:3", 0.60))
        breakdowns = adapter.adjust_batch(
            query="amor", candidates=candidates, context_signature="")
        self.assertEqual(len(breakdowns), 3)
        self.assertEqual(breakdowns[0].candidate_id, "43:3:16")
        self.assertEqual(breakdowns[2].candidate_id, "40:5:3")

    def test_batch_empty(self):
        engine, _ = make_engine()
        adapter = RankingFeedbackAdapter(engine)
        breakdowns = adapter.adjust_batch(
            query="amor", candidates=(), context_signature="")
        self.assertEqual(len(breakdowns), 0)


# ---------------------------------------------------------------------------
# RankingFeedbackAdapter — get_feedback_summary
# ---------------------------------------------------------------------------


class TestAdapterSummary(unittest.TestCase):

    def test_summary_no_feedback(self):
        engine, _ = make_engine()
        adapter = RankingFeedbackAdapter(engine)
        s = adapter.get_feedback_summary(
            query="pedro", candidate_id="43:21:15",
            context_signature="João")
        self.assertFalse(s.has_feedback)

    def test_summary_with_feedback(self):
        engine, _ = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        adapter = RankingFeedbackAdapter(engine)
        s = adapter.get_feedback_summary(
            query="pedro", candidate_id="43:21:15",
            context_signature="João")
        self.assertTrue(s.has_feedback)
        self.assertEqual(s.acceptances, 1)


# ---------------------------------------------------------------------------
# Explicabilidade
# ---------------------------------------------------------------------------


class TestExplainability(unittest.TestCase):

    def test_explain_no_feedback(self):
        engine, _ = make_engine()
        adapter = RankingFeedbackAdapter(engine)
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="João")
        text = b.explain()
        self.assertIn("Similaridade", text)
        self.assertNotIn("Feedback", text)

    def test_explain_with_feedback(self):
        engine, _ = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        adapter = RankingFeedbackAdapter(engine)
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="João")
        text = b.explain()
        self.assertIn("Similaridade", text)
        self.assertIn("Feedback", text)

    def test_explain_with_capped(self):
        engine, _ = make_engine()
        key = make_key()
        for _ in range(20):
            engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        adapter = RankingFeedbackAdapter(engine)
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="João")
        text = b.explain()
        self.assertIn("limitado", text)

    def test_breakdown_to_dict(self):
        engine, _ = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        adapter = RankingFeedbackAdapter(engine)
        b = adapter.adjust(query="pedro", candidate_id="43:21:15",
                           base_score=0.83, context_signature="João")
        d = b.to_dict()
        self.assertIn("base_score", d)
        self.assertIn("feedback_bonus", d)
        self.assertIn("final_score", d)
        self.assertTrue(d["has_feedback"])


if __name__ == "__main__":
    unittest.main()
