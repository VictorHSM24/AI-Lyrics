"""Testes de DTOs e eventos do Continuous Evaluation (Fase 10 — Parte 1).

Cobre:
  - QueryClassification (enum, valores).
  - TemporalWindow (enum, valores).
  - EvaluationRecord (imutabilidade, serialização, hashable).
  - EvaluationMetrics (imutabilidade, properties, serialização).
  - TemporalSlice (imutabilidade, serialização).
  - EvaluationSummary (imutabilidade, serialização).
  - EvaluationReport (imutabilidade, to_text, serialização).
  - RegressionAlert (imutabilidade, serialização).
  - Eventos (imutabilidade, herança de EvaluationEvent).
"""

from __future__ import annotations

import unittest

import sys
sys.path.insert(0, ".")

from evaluation import (
    CandidateAccepted,
    CandidatePresented,
    CandidateRejected,
    EvaluationEvent,
    EvaluationMetrics,
    EvaluationRecord,
    EvaluationReport,
    EvaluationReset,
    EvaluationSummary,
    ManualCorrection,
    NoResultFound,
    QueryClassification,
    RegressionAlert,
    SearchExecuted,
    SearchFailed,
    TemporalSlice,
    TemporalWindow,
)


def make_record(**kwargs):
    defaults = dict(
        record_id="rec_001",
        timestamp=1000.0,
        event_type="search_executed",
        query="pedro",
        classification=QueryClassification.CHARACTER,
    )
    defaults.update(kwargs)
    return EvaluationRecord(**defaults)


# ---------------------------------------------------------------------------
# QueryClassification
# ---------------------------------------------------------------------------


class TestQueryClassification(unittest.TestCase):

    def test_reference_value(self):
        self.assertEqual(QueryClassification.REFERENCE.value, "REFERENCE")

    def test_book_value(self):
        self.assertEqual(QueryClassification.BOOK.value, "BOOK")

    def test_character_value(self):
        self.assertEqual(QueryClassification.CHARACTER.value, "CHARACTER")

    def test_concept_value(self):
        self.assertEqual(QueryClassification.CONCEPT.value, "CONCEPT")

    def test_theme_value(self):
        self.assertEqual(QueryClassification.THEME.value, "THEME")

    def test_event_value(self):
        self.assertEqual(QueryClassification.EVENT.value, "EVENT")

    def test_unknown_value(self):
        self.assertEqual(QueryClassification.UNKNOWN.value, "UNKNOWN")

    def test_from_string(self):
        self.assertIs(QueryClassification("CHARACTER"), QueryClassification.CHARACTER)

    def test_is_str_enum(self):
        self.assertIsInstance(QueryClassification.REFERENCE, str)


# ---------------------------------------------------------------------------
# TemporalWindow
# ---------------------------------------------------------------------------


class TestTemporalWindow(unittest.TestCase):

    def test_last_24h_value(self):
        self.assertEqual(TemporalWindow.LAST_24H.value, "LAST_24H")

    def test_last_7d_value(self):
        self.assertEqual(TemporalWindow.LAST_7D.value, "LAST_7D")

    def test_last_30d_value(self):
        self.assertEqual(TemporalWindow.LAST_30D.value, "LAST_30D")

    def test_all_value(self):
        self.assertEqual(TemporalWindow.ALL.value, "ALL")

    def test_from_string(self):
        self.assertIs(TemporalWindow("LAST_24H"), TemporalWindow.LAST_24H)


# ---------------------------------------------------------------------------
# EvaluationRecord
# ---------------------------------------------------------------------------


class TestEvaluationRecord(unittest.TestCase):

    def test_creation_defaults(self):
        r = make_record()
        self.assertEqual(r.record_id, "rec_001")
        self.assertEqual(r.event_type, "search_executed")
        self.assertEqual(r.candidate_id, "")
        self.assertEqual(r.duration_ms, 0.0)

    def test_frozen(self):
        r = make_record()
        with self.assertRaises(Exception):
            r.query = "outro"

    def test_hashable(self):
        r = make_record()
        hash(r)

    def test_to_dict(self):
        r = make_record(candidate_id="43:3:16", duration_ms=250.0)
        d = r.to_dict()
        self.assertEqual(d["record_id"], "rec_001")
        self.assertEqual(d["candidate_id"], "43:3:16")
        self.assertEqual(d["duration_ms"], 250.0)
        self.assertEqual(d["classification"], "CHARACTER")

    def test_from_dict_roundtrip(self):
        r = make_record(candidate_id="43:3:16", book="João",
                        metadata=(("key", "value"),))
        d = r.to_dict()
        r2 = EvaluationRecord.from_dict(d)
        self.assertEqual(r, r2)
        self.assertEqual(r2.book, "João")
        self.assertEqual(r2.metadata, (("key", "value"),))

    def test_equality(self):
        r1 = make_record()
        r2 = make_record()
        self.assertEqual(r1, r2)

    def test_inequality(self):
        r1 = make_record(query="pedro")
        r2 = make_record(query="paulo")
        self.assertNotEqual(r1, r2)


# ---------------------------------------------------------------------------
# EvaluationMetrics
# ---------------------------------------------------------------------------


class TestEvaluationMetrics(unittest.TestCase):

    def test_default_values(self):
        m = EvaluationMetrics()
        self.assertEqual(m.total_searches, 0)
        self.assertEqual(m.total_accepted, 0)
        self.assertEqual(m.avg_duration_ms, 0.0)

    def test_frozen(self):
        m = EvaluationMetrics()
        with self.assertRaises(Exception):
            m.total_searches = 1

    def test_acceptance_rate_zero(self):
        m = EvaluationMetrics()
        self.assertEqual(m.acceptance_rate, 0.0)

    def test_acceptance_rate(self):
        m = EvaluationMetrics(total_presented=10, total_accepted=7)
        self.assertAlmostEqual(m.acceptance_rate, 0.7)

    def test_rejection_rate(self):
        m = EvaluationMetrics(total_presented=10, total_rejected=3)
        self.assertAlmostEqual(m.rejection_rate, 0.3)

    def test_precision_zero(self):
        m = EvaluationMetrics()
        self.assertEqual(m.precision, 0.0)

    def test_precision(self):
        m = EvaluationMetrics(total_accepted=7, total_rejected=2,
                              total_manual_corrections=1)
        # 7 / (7 + 2 + 1) = 0.7
        self.assertAlmostEqual(m.precision, 0.7)

    def test_avg_duration_ms(self):
        m = EvaluationMetrics(total_searches=4, total_duration_ms=1000.0)
        self.assertAlmostEqual(m.avg_duration_ms, 250.0)

    def test_no_result_rate(self):
        m = EvaluationMetrics(total_searches=100, total_no_result=5)
        self.assertAlmostEqual(m.no_result_rate, 0.05)

    def test_to_dict(self):
        m = EvaluationMetrics(total_searches=10, total_accepted=8)
        d = m.to_dict()
        self.assertEqual(d["total_searches"], 10)
        self.assertEqual(d["total_accepted"], 8)

    def test_from_dict_roundtrip(self):
        m = EvaluationMetrics(total_searches=10, total_accepted=8,
                              total_rejected=2)
        d = m.to_dict()
        m2 = EvaluationMetrics.from_dict(d)
        self.assertEqual(m, m2)


# ---------------------------------------------------------------------------
# TemporalSlice
# ---------------------------------------------------------------------------


class TestTemporalSlice(unittest.TestCase):

    def test_creation(self):
        m = EvaluationMetrics(total_searches=5)
        s = TemporalSlice(
            window=TemporalWindow.LAST_24H,
            start_timestamp=900.0,
            end_timestamp=1000.0,
            metrics=m,
            record_count=5,
        )
        self.assertEqual(s.window, TemporalWindow.LAST_24H)
        self.assertEqual(s.record_count, 5)

    def test_frozen(self):
        m = EvaluationMetrics()
        s = TemporalSlice(
            window=TemporalWindow.ALL, start_timestamp=0,
            end_timestamp=1000, metrics=m, record_count=0,
        )
        with self.assertRaises(Exception):
            s.record_count = 99

    def test_to_dict(self):
        m = EvaluationMetrics(total_searches=5)
        s = TemporalSlice(
            window=TemporalWindow.LAST_7D, start_timestamp=0,
            end_timestamp=1000, metrics=m, record_count=5,
        )
        d = s.to_dict()
        self.assertEqual(d["window"], "LAST_7D")
        self.assertEqual(d["record_count"], 5)


# ---------------------------------------------------------------------------
# EvaluationSummary
# ---------------------------------------------------------------------------


class TestEvaluationSummary(unittest.TestCase):

    def test_creation(self):
        m = EvaluationMetrics(total_searches=10)
        s = EvaluationSummary(total_records=10, metrics=m)
        self.assertEqual(s.total_records, 10)
        self.assertEqual(s.hardest_queries, ())

    def test_frozen(self):
        m = EvaluationMetrics()
        s = EvaluationSummary(total_records=0, metrics=m)
        with self.assertRaises(Exception):
            s.total_records = 99

    def test_to_dict(self):
        m = EvaluationMetrics(total_searches=10)
        s = EvaluationSummary(total_records=10, metrics=m,
                              hardest_queries=(("pedro", 3),))
        d = s.to_dict()
        self.assertEqual(d["total_records"], 10)
        self.assertEqual(d["hardest_queries"], [("pedro", 3)])


# ---------------------------------------------------------------------------
# EvaluationReport
# ---------------------------------------------------------------------------


class TestEvaluationReport(unittest.TestCase):

    def test_creation(self):
        m = EvaluationMetrics(total_searches=10, total_accepted=8)
        s = EvaluationSummary(total_records=10, metrics=m)
        r = EvaluationReport(
            generated_at=1000.0,
            window=TemporalWindow.ALL,
            summary=s,
        )
        self.assertEqual(r.window, TemporalWindow.ALL)

    def test_frozen(self):
        m = EvaluationMetrics()
        s = EvaluationSummary(total_records=0, metrics=m)
        r = EvaluationReport(generated_at=0, window=TemporalWindow.ALL,
                             summary=s)
        with self.assertRaises(Exception):
            r.generated_at = 999

    def test_to_text_basic(self):
        m = EvaluationMetrics(total_searches=1520, total_accepted=1480,
                              total_manual_corrections=31,
                              total_no_result=9,
                              total_duration_ms=471200.0)
        s = EvaluationSummary(total_records=1520, metrics=m)
        r = EvaluationReport(generated_at=1000.0, window=TemporalWindow.ALL,
                             summary=s)
        text = r.to_text()
        self.assertIn("Buscas: 1520", text)
        self.assertIn("Acertos: 1480", text)
        self.assertIn("Correções: 31", text)
        self.assertIn("Sem resultado: 9", text)

    def test_to_text_with_hardest(self):
        m = EvaluationMetrics()
        s = EvaluationSummary(total_records=10, metrics=m,
                              hardest_queries=(("amor", 5), ("fé", 3)))
        r = EvaluationReport(generated_at=0, window=TemporalWindow.ALL,
                             summary=s)
        text = r.to_text()
        self.assertIn("Consultas mais difíceis", text)
        self.assertIn("amor", text)

    def test_to_text_with_regressions(self):
        m = EvaluationMetrics()
        s = EvaluationSummary(total_records=10, metrics=m)
        alert = RegressionAlert(
            metric_name="precision", description="Queda de 10%",
            previous_value=0.9, current_value=0.8, threshold=5.0,
            detected_at=1000.0,
        )
        r = EvaluationReport(generated_at=0, window=TemporalWindow.ALL,
                             summary=s, regressions=(alert,))
        text = r.to_text()
        self.assertIn("Regressões detectadas", text)

    def test_to_dict(self):
        m = EvaluationMetrics(total_searches=10)
        s = EvaluationSummary(total_records=10, metrics=m)
        r = EvaluationReport(generated_at=1000.0, window=TemporalWindow.ALL,
                             summary=s)
        d = r.to_dict()
        self.assertEqual(d["window"], "ALL")
        self.assertEqual(d["generated_at"], 1000.0)


# ---------------------------------------------------------------------------
# RegressionAlert
# ---------------------------------------------------------------------------


class TestRegressionAlert(unittest.TestCase):

    def test_creation(self):
        a = RegressionAlert(
            metric_name="precision", description="Queda",
            previous_value=0.9, current_value=0.8, threshold=5.0,
            detected_at=1000.0, severity="high",
        )
        self.assertEqual(a.metric_name, "precision")
        self.assertEqual(a.severity, "high")

    def test_frozen(self):
        a = RegressionAlert(
            metric_name="x", description="y", previous_value=0,
            current_value=0, threshold=0, detected_at=0,
        )
        with self.assertRaises(Exception):
            a.severity = "high"

    def test_to_dict(self):
        a = RegressionAlert(
            metric_name="precision", description="Queda",
            previous_value=0.9, current_value=0.8, threshold=5.0,
            detected_at=1000.0,
        )
        d = a.to_dict()
        self.assertEqual(d["metric_name"], "precision")
        self.assertEqual(d["threshold"], 5.0)


# ---------------------------------------------------------------------------
# Eventos — imutabilidade e herança
# ---------------------------------------------------------------------------


class TestEventsImmutable(unittest.TestCase):

    def test_search_executed_frozen(self):
        ev = SearchExecuted(query="pedro", duration_ms=250)
        with self.assertRaises(Exception):
            ev.query = "outro"

    def test_candidate_presented_frozen(self):
        ev = CandidatePresented(candidate_id="43:3:16", rank_position=1)
        with self.assertRaises(Exception):
            ev.candidate_id = "outro"

    def test_candidate_accepted_frozen(self):
        ev = CandidateAccepted(candidate_id="43:3:16", book="João")
        with self.assertRaises(Exception):
            ev.book = "Lucas"

    def test_candidate_rejected_frozen(self):
        ev = CandidateRejected(candidate_id="43:3:16")
        with self.assertRaises(Exception):
            ev.candidate_id = ""

    def test_manual_correction_frozen(self):
        ev = ManualCorrection(
            original_candidate_id="a", corrected_candidate_id="b")
        with self.assertRaises(Exception):
            ev.original_candidate_id = "c"

    def test_search_failed_frozen(self):
        ev = SearchFailed(error_message="timeout")
        with self.assertRaises(Exception):
            ev.error_message = "outro"

    def test_no_result_found_frozen(self):
        ev = NoResultFound(book="Gênesis")
        with self.assertRaises(Exception):
            ev.book = "João"

    def test_evaluation_reset_frozen(self):
        ev = EvaluationReset(reason="novo")
        with self.assertRaises(Exception):
            ev.reason = "outro"

    def test_all_inherit_evaluation_event(self):
        self.assertIsInstance(SearchExecuted(), EvaluationEvent)
        self.assertIsInstance(CandidatePresented(), EvaluationEvent)
        self.assertIsInstance(CandidateAccepted(), EvaluationEvent)
        self.assertIsInstance(CandidateRejected(), EvaluationEvent)
        self.assertIsInstance(ManualCorrection(), EvaluationEvent)
        self.assertIsInstance(SearchFailed(), EvaluationEvent)
        self.assertIsInstance(NoResultFound(), EvaluationEvent)
        self.assertIsInstance(EvaluationReset(), EvaluationEvent)

    def test_default_timestamp_zero(self):
        self.assertEqual(SearchExecuted().timestamp, 0.0)

    def test_default_classification_unknown(self):
        self.assertEqual(SearchExecuted().classification,
                         QueryClassification.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
