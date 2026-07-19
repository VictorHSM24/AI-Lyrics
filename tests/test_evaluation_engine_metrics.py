"""Testes de Engine e MetricsCalculator (Fase 10 — Parte 3).

Cobre:
  - EvaluationEngine: record() para cada evento, list_records, reset,
    flush, clock e id_generator injetáveis.
  - MetricsCalculator: calculate, temporal_slice, all_temporal_slices,
    precision_by_book, precision_by_classification, hardest_queries,
    top_candidates.
"""

from __future__ import annotations

import os
import tempfile
import unittest

import sys
sys.path.insert(0, ".")

from evaluation import (
    CandidateAccepted,
    CandidatePresented,
    CandidateRejected,
    EvaluationEngine,
    EvaluationMetrics,
    EvaluationRecord,
    EvaluationRepository,
    ManualCorrection,
    MetricsCalculator,
    NoResultFound,
    QueryClassification,
    SearchExecuted,
    SearchFailed,
    TemporalWindow,
)


def make_engine(clock_start=1000.0):
    clock = [clock_start]
    def fake_clock():
        clock[0] += 1.0
        return clock[0]
    id_counter = [0]
    def fake_id():
        id_counter[0] += 1
        return f"rec_{id_counter[0]:04d}"
    repo = EvaluationRepository()
    return EvaluationEngine(repo, clock=fake_clock, id_generator=fake_id), repo


# ---------------------------------------------------------------------------
# EvaluationEngine — record()
# ---------------------------------------------------------------------------


class TestEngineRecordSearchExecuted(unittest.TestCase):

    def test_record_search_executed(self):
        engine, repo = make_engine()
        r = engine.record(SearchExecuted(
            query="pedro", classification=QueryClassification.CHARACTER,
            duration_ms=250, result_count=5, book="João", timestamp=1001.0))
        self.assertEqual(r.event_type, "search_executed")
        self.assertEqual(r.query, "pedro")
        self.assertEqual(r.duration_ms, 250.0)
        self.assertEqual(r.book, "João")
        self.assertEqual(len(repo), 1)

    def test_record_uses_clock_when_no_timestamp(self):
        engine, repo = make_engine()
        r = engine.record(SearchExecuted(query="pedro"))
        # clock começa em 1001 (após primeiro incremento)
        self.assertGreater(r.timestamp, 1000.0)


class TestEngineRecordCandidateEvents(unittest.TestCase):

    def test_candidate_presented(self):
        engine, _ = make_engine()
        r = engine.record(CandidatePresented(
            candidate_id="43:3:16", rank_position=1, timestamp=1001.0))
        self.assertEqual(r.event_type, "candidate_presented")
        self.assertEqual(r.candidate_id, "43:3:16")

    def test_candidate_accepted(self):
        engine, _ = make_engine()
        r = engine.record(CandidateAccepted(
            candidate_id="43:3:16", book="João", timestamp=1001.0))
        self.assertEqual(r.event_type, "candidate_accepted")
        self.assertEqual(r.book, "João")

    def test_candidate_rejected(self):
        engine, _ = make_engine()
        r = engine.record(CandidateRejected(
            candidate_id="43:3:16", book="João", timestamp=1001.0))
        self.assertEqual(r.event_type, "candidate_rejected")

    def test_manual_correction(self):
        engine, _ = make_engine()
        r = engine.record(ManualCorrection(
            original_candidate_id="a", corrected_candidate_id="b",
            book="João", timestamp=1001.0))
        self.assertEqual(r.event_type, "manual_correction")
        self.assertEqual(r.candidate_id, "b")  # corrected


class TestEngineRecordFailures(unittest.TestCase):

    def test_search_failed(self):
        engine, _ = make_engine()
        r = engine.record(SearchFailed(
            error_message="timeout", timestamp=1001.0))
        self.assertEqual(r.event_type, "search_failed")

    def test_no_result_found(self):
        engine, _ = make_engine()
        r = engine.record(NoResultFound(
            book="Gênesis", timestamp=1001.0))
        self.assertEqual(r.event_type, "no_result_found")


class TestEngineReset(unittest.TestCase):

    def test_reset_clears_records(self):
        engine, repo = make_engine()
        engine.record(SearchExecuted(query="pedro", timestamp=1001.0))
        self.assertEqual(len(repo), 1)
        engine.reset()
        self.assertEqual(len(repo), 0)


class TestEngineQueries(unittest.TestCase):

    def test_list_records(self):
        engine, _ = make_engine()
        engine.record(SearchExecuted(query="a", timestamp=1001.0))
        engine.record(SearchExecuted(query="b", timestamp=1002.0))
        records = engine.list_records()
        self.assertEqual(len(records), 2)

    def test_list_since(self):
        engine, _ = make_engine()
        engine.record(SearchExecuted(query="a", timestamp=1001.0))
        engine.record(SearchExecuted(query="b", timestamp=2001.0))
        since = engine.list_since(1500.0)
        self.assertEqual(len(since), 1)

    def test_record_count(self):
        engine, _ = make_engine()
        engine.record(SearchExecuted(query="a", timestamp=1001.0))
        self.assertEqual(engine.record_count(), 1)

    def test_get_record(self):
        engine, _ = make_engine()
        r = engine.record(SearchExecuted(query="a", timestamp=1001.0))
        self.assertEqual(engine.get_record(r.record_id), r)


class TestEngineFlush(unittest.TestCase):

    def test_flush(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            repo = EvaluationRepository(tmp)
            engine = EvaluationEngine(repo)
            engine.record(SearchExecuted(query="a", timestamp=1001.0))
            engine.flush()
            self.assertTrue(os.path.exists(tmp))
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


# ---------------------------------------------------------------------------
# MetricsCalculator — calculate()
# ---------------------------------------------------------------------------


class TestMetricsCalculate(unittest.TestCase):

    def setUp(self):
        self.calc = MetricsCalculator()

    def test_empty_records(self):
        m = self.calc.calculate(())
        self.assertEqual(m.total_searches, 0)
        self.assertEqual(m.precision, 0.0)

    def test_counts(self):
        records = (
            EvaluationRecord("r1", 1000, "search_executed",
                             duration_ms=250, book="João"),
            EvaluationRecord("r2", 1001, "candidate_presented",
                             candidate_id="43:3:16"),
            EvaluationRecord("r3", 1002, "candidate_accepted",
                             candidate_id="43:3:16", book="João"),
            EvaluationRecord("r4", 1003, "candidate_rejected",
                             candidate_id="42:1:1", book="Lucas"),
            EvaluationRecord("r5", 1004, "manual_correction",
                             book="João"),
            EvaluationRecord("r6", 1005, "no_result_found",
                             book="Gênesis"),
            EvaluationRecord("r7", 1006, "search_failed"),
        )
        m = self.calc.calculate(records)
        self.assertEqual(m.total_searches, 1)
        self.assertEqual(m.total_presented, 1)
        self.assertEqual(m.total_accepted, 1)
        self.assertEqual(m.total_rejected, 1)
        self.assertEqual(m.total_manual_corrections, 1)
        self.assertEqual(m.total_no_result, 1)
        self.assertEqual(m.total_failed, 1)
        self.assertAlmostEqual(m.total_duration_ms, 250.0)
        self.assertAlmostEqual(m.avg_duration_ms, 250.0)

    def test_by_classification(self):
        records = (
            EvaluationRecord("r1", 1000, "search_executed",
                             classification=QueryClassification.CHARACTER),
            EvaluationRecord("r2", 1001, "search_executed",
                             classification=QueryClassification.CHARACTER),
            EvaluationRecord("r3", 1002, "search_executed",
                             classification=QueryClassification.THEME),
        )
        m = self.calc.calculate(records)
        # CHARACTER deve ter 2, THEME 1
        cls_dict = dict(m.by_classification)
        self.assertEqual(cls_dict[QueryClassification.CHARACTER], 2)
        self.assertEqual(cls_dict[QueryClassification.THEME], 1)

    def test_by_book(self):
        records = (
            EvaluationRecord("r1", 1000, "search_executed", book="João"),
            EvaluationRecord("r2", 1001, "search_executed", book="João"),
            EvaluationRecord("r3", 1002, "search_executed", book="Lucas"),
        )
        m = self.calc.calculate(records)
        book_dict = dict(m.by_book)
        self.assertEqual(book_dict["João"], 2)
        self.assertEqual(book_dict["Lucas"], 1)


# ---------------------------------------------------------------------------
# MetricsCalculator — temporal_slice
# ---------------------------------------------------------------------------


class TestMetricsTemporalSlice(unittest.TestCase):

    def setUp(self):
        self.calc = MetricsCalculator()

    def test_temporal_slice_all(self):
        records = (
            EvaluationRecord("r1", 1000, "search_executed"),
            EvaluationRecord("r2", 2000, "search_executed"),
        )
        s = self.calc.temporal_slice(records, TemporalWindow.ALL, now=3000.0)
        self.assertEqual(s.window, TemporalWindow.ALL)
        self.assertEqual(s.record_count, 2)
        self.assertEqual(s.metrics.total_searches, 2)

    def test_temporal_slice_24h(self):
        records = (
            EvaluationRecord("r1", 1000, "search_executed"),
            EvaluationRecord("r2", 200000, "search_executed"),
        )
        # now = 200000 + 1000 = 201000
        # 24h = 86400, start = 201000 - 86400 = 114600
        s = self.calc.temporal_slice(records, TemporalWindow.LAST_24H,
                                     now=201000.0)
        # r2 (200000) >= 114600 → incluído
        # r1 (1000) < 114600 → excluído
        self.assertEqual(s.record_count, 1)

    def test_all_temporal_slices(self):
        records = (EvaluationRecord("r1", 1000, "search_executed"),)
        slices = self.calc.all_temporal_slices(records, now=2000.0)
        self.assertEqual(len(slices), 4)


# ---------------------------------------------------------------------------
# MetricsCalculator — precision_by_book
# ---------------------------------------------------------------------------


class TestMetricsPrecisionByBook(unittest.TestCase):

    def setUp(self):
        self.calc = MetricsCalculator()

    def test_precision_by_book(self):
        # João: 8 aceitos, 1 rejeitado, 1 correção → 80%
        # Lucas: 3 aceitos, 1 rejeitado → 75% (abaixo do min_searches=5? 4 total)
        records = []
        for i in range(8):
            records.append(EvaluationRecord(
                f"j_a_{i}", 1000+i, "candidate_accepted", book="João"))
        records.append(EvaluationRecord(
            "j_r", 1100, "candidate_rejected", book="João"))
        records.append(EvaluationRecord(
            "j_c", 1101, "manual_correction", book="João"))
        for i in range(3):
            records.append(EvaluationRecord(
                f"l_a_{i}", 1200+i, "candidate_accepted", book="Lucas"))
        records.append(EvaluationRecord(
            "l_r", 1300, "candidate_rejected", book="Lucas"))

        result = self.calc.precision_by_book(tuple(records))
        # João tem 10 eventos (>= min_searches_per_book=5)
        # Lucas tem 4 eventos (< 5) → não aparece
        books = [b for b, _, _ in result]
        self.assertIn("João", books)
        self.assertNotIn("Lucas", books)

    def test_precision_by_book_empty(self):
        result = self.calc.precision_by_book(())
        self.assertEqual(result, ())


# ---------------------------------------------------------------------------
# MetricsCalculator — hardest_queries e top_candidates
# ---------------------------------------------------------------------------


class TestMetricsHardestAndTop(unittest.TestCase):

    def setUp(self):
        self.calc = MetricsCalculator()

    def test_hardest_queries(self):
        records = (
            EvaluationRecord("r1", 1000, "candidate_rejected", query="amor"),
            EvaluationRecord("r2", 1001, "manual_correction", query="amor"),
            EvaluationRecord("r3", 1002, "no_result_found", query="amor"),
            EvaluationRecord("r4", 1003, "candidate_rejected", query="fé"),
            EvaluationRecord("r5", 1004, "candidate_accepted", query="graça"),
        )
        result = self.calc.hardest_queries(records)
        # amor tem 3 falhas, fé tem 1, graça tem 0
        self.assertEqual(result[0][0], "amor")
        self.assertEqual(result[0][1], 3)

    def test_hardest_queries_limit(self):
        records = tuple(
            EvaluationRecord(f"r{i}", 1000+i, "candidate_rejected",
                             query=f"q{i}")
            for i in range(20)
        )
        result = self.calc.hardest_queries(records, limit=5)
        self.assertEqual(len(result), 5)

    def test_top_candidates(self):
        records = (
            EvaluationRecord("r1", 1000, "candidate_accepted",
                             candidate_id="43:3:16"),
            EvaluationRecord("r2", 1001, "candidate_accepted",
                             candidate_id="43:3:16"),
            EvaluationRecord("r3", 1002, "candidate_accepted",
                             candidate_id="42:1:1"),
        )
        result = self.calc.top_candidates(records)
        # 43:3:16 tem 2 aceitos, 42:1:1 tem 1
        self.assertEqual(result[0][0], "43:3:16")
        self.assertEqual(result[0][1], 2)

    def test_top_candidates_limit(self):
        records = tuple(
            EvaluationRecord(f"r{i}", 1000+i, "candidate_accepted",
                             candidate_id=f"c{i}")
            for i in range(20)
        )
        result = self.calc.top_candidates(records, limit=5)
        self.assertEqual(len(result), 5)


# ---------------------------------------------------------------------------
# MetricsCalculator — precision_by_classification
# ---------------------------------------------------------------------------


class TestMetricsPrecisionByClassification(unittest.TestCase):

    def setUp(self):
        self.calc = MetricsCalculator()

    def test_precision_by_classification(self):
        records = (
            EvaluationRecord("r1", 1000, "candidate_accepted",
                             classification=QueryClassification.CHARACTER),
            EvaluationRecord("r2", 1001, "candidate_rejected",
                             classification=QueryClassification.CHARACTER),
            EvaluationRecord("r3", 1002, "candidate_accepted",
                             classification=QueryClassification.THEME),
        )
        result = self.calc.precision_by_classification(records)
        cls_dict = {c: (p, n) for c, p, n in result}
        # CHARACTER: 1/(1+1) = 0.5
        self.assertAlmostEqual(cls_dict[QueryClassification.CHARACTER][0], 0.5)
        # THEME: 1/1 = 1.0
        self.assertAlmostEqual(cls_dict[QueryClassification.THEME][0], 1.0)


if __name__ == "__main__":
    unittest.main()
