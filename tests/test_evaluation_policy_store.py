"""Testes de Policy, Store e Repository (Fase 10 — Parte 2).

Cobre:
  - EvaluationPolicy: thresholds, classificações, janelas, severidade.
  - EvaluationStore: CRUD, persistência JSON, to_json/from_json, filtros.
  - EvaluationRepository: CRUD, list_since, list_between, auto_save, flush.
"""

from __future__ import annotations

import os
import tempfile
import unittest

import sys
sys.path.insert(0, ".")

from evaluation import (
    EvaluationPolicy,
    EvaluationRecord,
    EvaluationRepository,
    EvaluationStore,
    QueryClassification,
    TemporalWindow,
)


def make_record(rid="rec_001", ts=1000.0, et="search_executed",
                query="pedro", cls=QueryClassification.CHARACTER,
                book="João", candidate_id="", duration_ms=250.0):
    return EvaluationRecord(
        record_id=rid, timestamp=ts, event_type=et, query=query,
        classification=cls, book=book, candidate_id=candidate_id,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# EvaluationPolicy
# ---------------------------------------------------------------------------


class TestEvaluationPolicy(unittest.TestCase):

    def setUp(self):
        self.policy = EvaluationPolicy()

    def test_min_records_for_confidence(self):
        self.assertGreater(self.policy.min_records_for_confidence, 0)

    def test_min_searches_per_book(self):
        self.assertGreater(self.policy.min_searches_per_book, 0)

    def test_regression_precision_drop(self):
        self.assertGreater(self.policy.regression_precision_drop, 0)

    def test_regression_duration_increase(self):
        self.assertGreater(self.policy.regression_duration_increase, 0)

    def test_regression_corrections_increase(self):
        self.assertGreater(self.policy.regression_corrections_increase, 0)

    def test_regression_no_result_increase(self):
        self.assertGreater(self.policy.regression_no_result_increase, 0)

    def test_top_queries_limit(self):
        self.assertGreater(self.policy.top_queries_limit, 0)

    def test_is_confident_true(self):
        self.assertTrue(self.policy.is_confident(100))

    def test_is_confident_false(self):
        self.assertFalse(self.policy.is_confident(1))

    def test_is_book_confident_true(self):
        self.assertTrue(self.policy.is_book_confident(10))

    def test_is_book_confident_false(self):
        self.assertFalse(self.policy.is_book_confident(1))

    def test_window_seconds_24h(self):
        self.assertEqual(self.policy.window_seconds(TemporalWindow.LAST_24H),
                         86400.0)

    def test_window_seconds_7d(self):
        self.assertEqual(self.policy.window_seconds(TemporalWindow.LAST_7D),
                         604800.0)

    def test_window_seconds_30d(self):
        self.assertEqual(self.policy.window_seconds(TemporalWindow.LAST_30D),
                         2592000.0)

    def test_window_seconds_all(self):
        self.assertEqual(self.policy.window_seconds(TemporalWindow.ALL),
                         float("inf"))

    def test_supported_windows(self):
        windows = self.policy.supported_windows()
        self.assertIn(TemporalWindow.LAST_24H, windows)
        self.assertIn(TemporalWindow.ALL, windows)
        self.assertEqual(len(windows), 4)

    def test_severity_low(self):
        self.assertEqual(self.policy.severity_for_drop(5.0), "low")

    def test_severity_medium(self):
        self.assertEqual(self.policy.severity_for_drop(10.0), "medium")

    def test_severity_high(self):
        self.assertEqual(self.policy.severity_for_drop(25.0), "high")

    def test_all_classifications(self):
        classes = self.policy.all_classifications()
        self.assertIn(QueryClassification.REFERENCE, classes)
        self.assertIn(QueryClassification.UNKNOWN, classes)

    def test_is_valid_classification(self):
        self.assertTrue(
            self.policy.is_valid_classification(QueryClassification.BOOK))


# ---------------------------------------------------------------------------
# EvaluationStore
# ---------------------------------------------------------------------------


class TestEvaluationStoreCRUD(unittest.TestCase):

    def setUp(self):
        self.store = EvaluationStore()
        self.r1 = make_record(rid="r1", ts=1000.0)
        self.r2 = make_record(rid="r2", ts=2000.0, query="amor")

    def test_empty_store(self):
        self.assertEqual(len(self.store), 0)

    def test_add_and_get(self):
        self.store.add(self.r1)
        self.assertEqual(self.store.get("r1"), self.r1)

    def test_get_nonexistent(self):
        self.assertIsNone(self.store.get("nonexistent"))

    def test_has(self):
        self.store.add(self.r1)
        self.assertTrue(self.store.has("r1"))
        self.assertFalse(self.store.has("r2"))

    def test_contains(self):
        self.store.add(self.r1)
        self.assertIn("r1", self.store)

    def test_list_all_empty(self):
        self.assertEqual(self.store.list_all(), ())

    def test_list_all(self):
        self.store.add(self.r1)
        self.store.add(self.r2)
        all_records = self.store.list_all()
        self.assertEqual(len(all_records), 2)

    def test_list_since(self):
        self.store.add(self.r1)
        self.store.add(self.r2)
        since_1500 = self.store.list_since(1500.0)
        self.assertEqual(len(since_1500), 1)
        self.assertEqual(since_1500[0].record_id, "r2")

    def test_list_between(self):
        self.store.add(self.r1)
        self.store.add(self.r2)
        between = self.store.list_between(1000.0, 2000.0)
        self.assertEqual(len(between), 1)
        self.assertEqual(between[0].record_id, "r1")

    def test_list_by_event_type(self):
        self.store.add(self.r1)
        self.store.add(self.r2)
        result = self.store.list_by_event_type("search_executed")
        self.assertEqual(len(result), 2)

    def test_list_by_query(self):
        self.store.add(self.r1)
        self.store.add(self.r2)
        result = self.store.list_by_query("amor")
        self.assertEqual(len(result), 1)

    def test_clear(self):
        self.store.add(self.r1)
        self.store.clear()
        self.assertEqual(len(self.store), 0)

    def test_iter(self):
        self.store.add(self.r1)
        for r in self.store:
            self.assertEqual(r, self.r1)


class TestEvaluationStorePersistence(unittest.TestCase):

    def setUp(self):
        self.store = EvaluationStore()
        self.store.add(make_record(rid="r1", ts=1000.0))
        self.store.add(make_record(rid="r2", ts=2000.0, query="amor"))

    def test_to_json(self):
        json_str = self.store.to_json()
        self.assertIsInstance(json_str, str)
        self.assertIn("records", json_str)

    def test_from_json_roundtrip(self):
        json_str = self.store.to_json()
        store2 = EvaluationStore()
        store2.from_json(json_str)
        self.assertEqual(len(store2), 2)

    def test_save_and_load_file(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            self.store.save(tmp)
            self.assertTrue(os.path.exists(tmp))
            store2 = EvaluationStore()
            store2.load(tmp)
            self.assertEqual(len(store2), 2)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_load_nonexistent(self):
        store = EvaluationStore()
        store.load("nonexistent.json")
        self.assertEqual(len(store), 0)

    def test_save_creates_directory(self):
        tmp_dir = tempfile.mkdtemp()
        tmp = os.path.join(tmp_dir, "sub", "eval.json")
        try:
            self.store.save(tmp)
            self.assertTrue(os.path.exists(tmp))
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# EvaluationRepository
# ---------------------------------------------------------------------------


class TestEvaluationRepository(unittest.TestCase):

    def setUp(self):
        self.repo = EvaluationRepository()
        self.r1 = make_record(rid="r1", ts=1000.0)

    def test_empty(self):
        self.assertEqual(len(self.repo), 0)

    def test_add_and_get(self):
        self.repo.add(self.r1)
        self.assertEqual(self.repo.get("r1"), self.r1)

    def test_has(self):
        self.repo.add(self.r1)
        self.assertTrue(self.repo.has("r1"))

    def test_list_all(self):
        self.repo.add(self.r1)
        self.assertEqual(len(self.repo.list_all()), 1)

    def test_list_since(self):
        self.repo.add(self.r1)
        self.repo.add(make_record(rid="r2", ts=2000.0))
        since = self.repo.list_since(1500.0)
        self.assertEqual(len(since), 1)

    def test_list_between(self):
        self.repo.add(self.r1)
        self.repo.add(make_record(rid="r2", ts=2000.0))
        between = self.repo.list_between(500.0, 1500.0)
        self.assertEqual(len(between), 1)

    def test_clear(self):
        self.repo.add(self.r1)
        self.repo.clear()
        self.assertEqual(len(self.repo), 0)

    def test_contains(self):
        self.repo.add(self.r1)
        self.assertIn("r1", self.repo)

    def test_path_none_default(self):
        self.assertIsNone(self.repo.path)

    def test_auto_save_default_false(self):
        self.assertFalse(self.repo.auto_save)


class TestEvaluationRepositoryPersistence(unittest.TestCase):

    def test_persistence_with_path(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            r = make_record(rid="r1", ts=1000.0)
            repo = EvaluationRepository(tmp)
            repo.add(r)
            repo.flush()
            repo2 = EvaluationRepository(tmp)
            self.assertEqual(len(repo2), 1)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_auto_save(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            r = make_record(rid="r1", ts=1000.0)
            repo = EvaluationRepository(tmp, auto_save=True)
            repo.add(r)
            self.assertTrue(os.path.exists(tmp))
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_load_on_init(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            r = make_record(rid="r1", ts=1000.0)
            repo = EvaluationRepository(tmp)
            repo.add(r)
            repo.flush()
            repo2 = EvaluationRepository(tmp)
            self.assertEqual(len(repo2), 1)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


if __name__ == "__main__":
    unittest.main()
