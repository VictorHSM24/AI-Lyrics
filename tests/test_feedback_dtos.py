"""Testes de DTOs e eventos do Feedback Learning (Fase 9 — Parte 1).

Cobre:
  - FeedbackScope (enum, valores).
  - FeedbackKey (imutabilidade, hashable, to_dict/from_dict).
  - FeedbackRecord (imutabilidade, serialização).
  - FeedbackStatistics (imutabilidade, properties, serialização).
  - FeedbackSummary (imutabilidade, serialização).
  - ScoreBreakdown (imutabilidade, explain(), serialização).
  - Eventos (imutabilidade, herança de FeedbackEvent).
"""

from __future__ import annotations

import unittest

import sys
sys.path.insert(0, ".")

from feedback import (
    CandidateAccepted,
    CandidateRejected,
    FeedbackEvent,
    FeedbackKey,
    FeedbackRecord,
    FeedbackScope,
    FeedbackStatistics,
    FeedbackSummary,
    ManualReferenceSelected,
    ManualSearch,
    ScoreBreakdown,
    SuggestionIgnored,
)


def make_key(scope=FeedbackScope.GLOBAL, query="pedro",
             ctx="João", cid="43:21:15"):
    return FeedbackKey(scope=scope, query=query,
                       context_signature=ctx, candidate_id=cid)


# ---------------------------------------------------------------------------
# FeedbackScope
# ---------------------------------------------------------------------------


class TestFeedbackScope(unittest.TestCase):

    def test_global_value(self):
        self.assertEqual(FeedbackScope.GLOBAL.value, "GLOBAL")

    def test_session_value(self):
        self.assertEqual(FeedbackScope.SESSION.value, "SESSION")

    def test_sermon_value(self):
        self.assertEqual(FeedbackScope.SERMON.value, "SERMON")

    def test_user_value(self):
        self.assertEqual(FeedbackScope.USER.value, "USER")

    def test_is_str_enum(self):
        self.assertIsInstance(FeedbackScope.GLOBAL, str)

    def test_from_string(self):
        self.assertIs(FeedbackScope("GLOBAL"), FeedbackScope.GLOBAL)


# ---------------------------------------------------------------------------
# FeedbackKey
# ---------------------------------------------------------------------------


class TestFeedbackKey(unittest.TestCase):

    def test_creation(self):
        k = make_key()
        self.assertEqual(k.scope, FeedbackScope.GLOBAL)
        self.assertEqual(k.query, "pedro")
        self.assertEqual(k.context_signature, "João")
        self.assertEqual(k.candidate_id, "43:21:15")

    def test_frozen(self):
        k = make_key()
        with self.assertRaises(Exception):
            k.query = "outro"

    def test_hashable(self):
        k = make_key()
        hash(k)  # não levanta
        s = {k}
        self.assertIn(k, s)

    def test_equality(self):
        k1 = make_key()
        k2 = make_key()
        self.assertEqual(k1, k2)

    def test_inequality_different_query(self):
        k1 = make_key(query="pedro")
        k2 = make_key(query="paulo")
        self.assertNotEqual(k1, k2)

    def test_inequality_different_context(self):
        k1 = make_key(ctx="João")
        k2 = make_key(ctx="Atos")
        self.assertNotEqual(k1, k2)

    def test_inequality_different_scope(self):
        k1 = make_key(scope=FeedbackScope.GLOBAL)
        k2 = make_key(scope=FeedbackScope.SESSION)
        self.assertNotEqual(k1, k2)

    def test_to_dict(self):
        k = make_key()
        d = k.to_dict()
        self.assertEqual(d["scope"], "GLOBAL")
        self.assertEqual(d["query"], "pedro")
        self.assertEqual(d["context_signature"], "João")
        self.assertEqual(d["candidate_id"], "43:21:15")

    def test_from_dict_roundtrip(self):
        k = make_key()
        d = k.to_dict()
        k2 = FeedbackKey.from_dict(d)
        self.assertEqual(k, k2)

    def test_empty_context_allowed(self):
        k = make_key(ctx="")
        self.assertEqual(k.context_signature, "")

    def test_in_dict_as_key(self):
        k = make_key()
        d = {k: "value"}
        self.assertEqual(d[k], "value")


# ---------------------------------------------------------------------------
# FeedbackRecord
# ---------------------------------------------------------------------------


class TestFeedbackRecord(unittest.TestCase):

    def test_creation(self):
        k = make_key()
        r = FeedbackRecord(key=k, event_type="accepted",
                           weight=3.0, timestamp=1000.0)
        self.assertEqual(r.key, k)
        self.assertEqual(r.event_type, "accepted")
        self.assertEqual(r.weight, 3.0)
        self.assertEqual(r.timestamp, 1000.0)
        self.assertEqual(r.decay_count, 0)

    def test_frozen(self):
        k = make_key()
        r = FeedbackRecord(key=k, event_type="accepted",
                           weight=3.0, timestamp=1000.0)
        with self.assertRaises(Exception):
            r.weight = 5.0

    def test_hashable(self):
        k = make_key()
        r = FeedbackRecord(key=k, event_type="accepted",
                           weight=3.0, timestamp=1000.0)
        hash(r)

    def test_to_dict(self):
        k = make_key()
        r = FeedbackRecord(key=k, event_type="accepted",
                           weight=3.0, timestamp=1000.0, decay_count=2)
        d = r.to_dict()
        self.assertEqual(d["event_type"], "accepted")
        self.assertEqual(d["weight"], 3.0)
        self.assertEqual(d["decay_count"], 2)

    def test_from_dict_roundtrip(self):
        k = make_key()
        r = FeedbackRecord(key=k, event_type="accepted",
                           weight=3.0, timestamp=1000.0, decay_count=1)
        d = r.to_dict()
        r2 = FeedbackRecord.from_dict(d)
        self.assertEqual(r, r2)


# ---------------------------------------------------------------------------
# FeedbackStatistics
# ---------------------------------------------------------------------------


class TestFeedbackStatistics(unittest.TestCase):

    def test_default_values(self):
        k = make_key()
        s = FeedbackStatistics(key=k)
        self.assertEqual(s.acceptances, 0)
        self.assertEqual(s.rejections, 0)
        self.assertEqual(s.manual_selections, 0)
        self.assertEqual(s.ignored, 0)
        self.assertEqual(s.total_weight, 0.0)
        self.assertEqual(s.last_used, 0.0)
        self.assertEqual(s.first_used, 0.0)
        self.assertEqual(s.decay_count, 0)

    def test_frozen(self):
        k = make_key()
        s = FeedbackStatistics(key=k)
        with self.assertRaises(Exception):
            s.acceptances = 1

    def test_total_events_zero(self):
        k = make_key()
        s = FeedbackStatistics(key=k)
        self.assertEqual(s.total_events, 0)

    def test_total_events_sum(self):
        k = make_key()
        s = FeedbackStatistics(key=k, acceptances=3, rejections=1,
                               manual_selections=2, ignored=1)
        self.assertEqual(s.total_events, 7)

    def test_frequency_zero_when_no_events(self):
        k = make_key()
        s = FeedbackStatistics(key=k)
        self.assertEqual(s.frequency, 0.0)

    def test_frequency_zero_when_same_timestamp(self):
        k = make_key()
        s = FeedbackStatistics(key=k, acceptances=1,
                               first_used=1000.0, last_used=1000.0)
        self.assertEqual(s.frequency, 0.0)

    def test_frequency_positive(self):
        k = make_key()
        s = FeedbackStatistics(key=k, acceptances=10,
                               first_used=1000.0, last_used=1100.0)
        self.assertGreater(s.frequency, 0.0)

    def test_to_dict(self):
        k = make_key()
        s = FeedbackStatistics(key=k, acceptances=3, total_weight=9.0)
        d = s.to_dict()
        self.assertEqual(d["acceptances"], 3)
        self.assertEqual(d["total_weight"], 9.0)

    def test_from_dict_roundtrip(self):
        k = make_key()
        s = FeedbackStatistics(key=k, acceptances=3, rejections=1,
                               total_weight=8.0, decay_count=2)
        d = s.to_dict()
        s2 = FeedbackStatistics.from_dict(d)
        self.assertEqual(s, s2)

    def test_hashable(self):
        k = make_key()
        s = FeedbackStatistics(key=k)
        hash(s)


# ---------------------------------------------------------------------------
# FeedbackSummary
# ---------------------------------------------------------------------------


class TestFeedbackSummary(unittest.TestCase):

    def test_creation(self):
        k = make_key()
        s = FeedbackSummary(key=k, total_events=5, total_weight=15.0,
                            acceptances=3, rejections=1,
                            manual_selections=1, ignored=0,
                            decay_count=0, last_used=1000.0,
                            has_feedback=True)
        self.assertEqual(s.total_events, 5)
        self.assertTrue(s.has_feedback)

    def test_frozen(self):
        k = make_key()
        s = FeedbackSummary(key=k, total_events=0, total_weight=0.0,
                            acceptances=0, rejections=0,
                            manual_selections=0, ignored=0,
                            decay_count=0, last_used=0.0,
                            has_feedback=False)
        with self.assertRaises(Exception):
            s.total_events = 1

    def test_to_dict(self):
        k = make_key()
        s = FeedbackSummary(key=k, total_events=3, total_weight=9.0,
                            acceptances=3, rejections=0,
                            manual_selections=0, ignored=0,
                            decay_count=0, last_used=1000.0,
                            has_feedback=True)
        d = s.to_dict()
        self.assertEqual(d["total_events"], 3)
        self.assertTrue(d["has_feedback"])


# ---------------------------------------------------------------------------
# ScoreBreakdown
# ---------------------------------------------------------------------------


class TestScoreBreakdown(unittest.TestCase):

    def test_creation_no_feedback(self):
        b = ScoreBreakdown(candidate_id="43:3:16", base_score=0.83,
                           feedback_bonus=0.0, context_bonus=0.0,
                           final_score=0.83)
        self.assertEqual(b.base_score, 0.83)
        self.assertFalse(b.has_feedback)

    def test_frozen(self):
        b = ScoreBreakdown(candidate_id="x", base_score=0.5,
                           feedback_bonus=0.0, context_bonus=0.0,
                           final_score=0.5)
        with self.assertRaises(Exception):
            b.base_score = 0.9

    def test_explain_no_feedback(self):
        b = ScoreBreakdown(candidate_id="x", base_score=0.83,
                           feedback_bonus=0.0, context_bonus=0.0,
                           final_score=0.83)
        text = b.explain()
        self.assertIn("Similaridade", text)
        self.assertNotIn("Feedback", text)

    def test_explain_with_feedback(self):
        b = ScoreBreakdown(candidate_id="x", base_score=0.83,
                           feedback_bonus=0.09, context_bonus=0.0,
                           final_score=0.92, has_feedback=True)
        text = b.explain()
        self.assertIn("Similaridade", text)
        self.assertIn("Feedback", text)

    def test_explain_with_capped(self):
        b = ScoreBreakdown(candidate_id="x", base_score=0.83,
                           feedback_bonus=0.15, context_bonus=0.0,
                           final_score=0.98, has_feedback=True,
                           feedback_capped=True)
        text = b.explain()
        self.assertIn("limitado", text)

    def test_explain_with_context(self):
        b = ScoreBreakdown(candidate_id="x", base_score=0.83,
                           feedback_bonus=0.0, context_bonus=0.05,
                           final_score=0.88)
        text = b.explain()
        self.assertIn("Contexto", text)

    def test_to_dict(self):
        b = ScoreBreakdown(candidate_id="x", base_score=0.83,
                           feedback_bonus=0.09, context_bonus=0.0,
                           final_score=0.92, has_feedback=True)
        d = b.to_dict()
        self.assertEqual(d["base_score"], 0.83)
        self.assertEqual(d["feedback_bonus"], 0.09)


# ---------------------------------------------------------------------------
# Eventos — imutabilidade e herança
# ---------------------------------------------------------------------------


class TestEventsImmutable(unittest.TestCase):

    def test_candidate_accepted_frozen(self):
        k = make_key()
        ev = CandidateAccepted(key=k, timestamp=1000.0)
        with self.assertRaises(Exception):
            ev.timestamp = 2000.0

    def test_candidate_rejected_frozen(self):
        k = make_key()
        ev = CandidateRejected(key=k)
        with self.assertRaises(Exception):
            ev.key = make_key(query="outro")

    def test_manual_reference_selected_frozen(self):
        k = make_key()
        ev = ManualReferenceSelected(key=k)
        with self.assertRaises(Exception):
            ev.key = None

    def test_manual_search_frozen(self):
        k = make_key()
        ev = ManualSearch(key=k, query_text="pedro")
        with self.assertRaises(Exception):
            ev.query_text = "outro"

    def test_suggestion_ignored_frozen(self):
        k = make_key()
        ev = SuggestionIgnored(key=k)
        with self.assertRaises(Exception):
            ev.key = None

    def test_all_inherit_feedback_event(self):
        k = make_key()
        self.assertIsInstance(CandidateAccepted(key=k), FeedbackEvent)
        self.assertIsInstance(CandidateRejected(key=k), FeedbackEvent)
        self.assertIsInstance(ManualReferenceSelected(key=k), FeedbackEvent)
        self.assertIsInstance(ManualSearch(key=k), FeedbackEvent)
        self.assertIsInstance(SuggestionIgnored(key=k), FeedbackEvent)

    def test_default_timestamp_zero(self):
        k = make_key()
        ev = CandidateAccepted(key=k)
        self.assertEqual(ev.timestamp, 0.0)

    def test_custom_timestamp(self):
        k = make_key()
        ev = CandidateAccepted(key=k, timestamp=12345.0)
        self.assertEqual(ev.timestamp, 12345.0)


if __name__ == "__main__":
    unittest.main()
