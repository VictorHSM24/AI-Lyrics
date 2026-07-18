"""Testes de LearningPolicy, Store e Repository (Fase 9 — Parte 2).

Cobre:
  - LearningPolicy: pesos, weight_for, event_type_name, weight_to_bonus,
    cap_bonus, should_apply_feedback, apply_decay.
  - FeedbackStore: CRUD, persistência JSON, to_json/from_json.
  - FeedbackRepository: CRUD, list_by_query, list_by_scope, auto_save,
    flush, persistência.
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
    FeedbackKey,
    FeedbackRepository,
    FeedbackScope,
    FeedbackStatistics,
    FeedbackStore,
    LearningPolicy,
    ManualReferenceSelected,
    ManualSearch,
    SuggestionIgnored,
)


def make_key(scope=FeedbackScope.GLOBAL, query="pedro",
             ctx="João", cid="43:21:15"):
    return FeedbackKey(scope=scope, query=query,
                       context_signature=ctx, candidate_id=cid)


# ---------------------------------------------------------------------------
# LearningPolicy
# ---------------------------------------------------------------------------


class TestLearningPolicyWeights(unittest.TestCase):

    def setUp(self):
        self.policy = LearningPolicy()

    def test_weight_candidate_accepted(self):
        self.assertEqual(self.policy.weight_candidate_accepted, 3.0)

    def test_weight_candidate_rejected(self):
        self.assertEqual(self.policy.weight_candidate_rejected, -1.0)

    def test_weight_manual_reference_selected(self):
        self.assertEqual(self.policy.weight_manual_reference_selected, 5.0)

    def test_weight_suggestion_ignored(self):
        self.assertEqual(self.policy.weight_suggestion_ignored, -2.0)

    def test_weight_manual_search(self):
        self.assertEqual(self.policy.weight_manual_search, 0.0)


class TestLearningPolicyWeightFor(unittest.TestCase):

    def setUp(self):
        self.policy = LearningPolicy()
        self.key = make_key()

    def test_weight_for_accepted(self):
        ev = CandidateAccepted(key=self.key)
        self.assertEqual(self.policy.weight_for(ev), 3.0)

    def test_weight_for_rejected(self):
        ev = CandidateRejected(key=self.key)
        self.assertEqual(self.policy.weight_for(ev), -1.0)

    def test_weight_for_manual_reference(self):
        ev = ManualReferenceSelected(key=self.key)
        self.assertEqual(self.policy.weight_for(ev), 5.0)

    def test_weight_for_suggestion_ignored(self):
        ev = SuggestionIgnored(key=self.key)
        self.assertEqual(self.policy.weight_for(ev), -2.0)

    def test_weight_for_manual_search(self):
        ev = ManualSearch(key=self.key)
        self.assertEqual(self.policy.weight_for(ev), 0.0)


class TestLearningPolicyEventTypeName(unittest.TestCase):

    def setUp(self):
        self.policy = LearningPolicy()
        self.key = make_key()

    def test_accepted_name(self):
        self.assertEqual(
            self.policy.event_type_name(CandidateAccepted(key=self.key)),
            "accepted")

    def test_rejected_name(self):
        self.assertEqual(
            self.policy.event_type_name(CandidateRejected(key=self.key)),
            "rejected")

    def test_manual_reference_name(self):
        self.assertEqual(
            self.policy.event_type_name(ManualReferenceSelected(key=self.key)),
            "manual_reference")

    def test_manual_search_name(self):
        self.assertEqual(
            self.policy.event_type_name(ManualSearch(key=self.key)),
            "manual_search")

    def test_suggestion_ignored_name(self):
        self.assertEqual(
            self.policy.event_type_name(SuggestionIgnored(key=self.key)),
            "suggestion_ignored")


class TestLearningPolicyBonus(unittest.TestCase):

    def setUp(self):
        self.policy = LearningPolicy()

    def test_weight_to_bonus_zero(self):
        self.assertAlmostEqual(self.policy.weight_to_bonus(0.0), 0.0)

    def test_weight_to_bonus_positive(self):
        bonus = self.policy.weight_to_bonus(10.0)
        self.assertGreater(bonus, 0.0)
        self.assertLess(bonus, 1.0)

    def test_weight_to_bonus_negative(self):
        bonus = self.policy.weight_to_bonus(-10.0)
        self.assertLess(bonus, 0.0)
        self.assertGreater(bonus, -1.0)

    def test_weight_to_bonus_saturates(self):
        # Peso muito grande → bônus satura em 1.0 (tanh)
        bonus = self.policy.weight_to_bonus(1000.0)
        self.assertAlmostEqual(bonus, 1.0, places=5)

    def test_cap_bonus_within_range(self):
        self.assertAlmostEqual(self.policy.cap_bonus(0.05), 0.05)

    def test_cap_bonus_above_max(self):
        capped = self.policy.cap_bonus(0.5)
        self.assertEqual(capped, self.policy.max_feedback_bonus)

    def test_cap_bonus_below_min(self):
        capped = self.policy.cap_bonus(-0.5)
        self.assertEqual(capped, self.policy.min_feedback_bonus)

    def test_should_apply_feedback_high_score(self):
        self.assertTrue(self.policy.should_apply_feedback(0.83))

    def test_should_apply_feedback_low_score(self):
        self.assertFalse(self.policy.should_apply_feedback(0.05))

    def test_should_apply_feedback_boundary(self):
        # boundary = min_base_score_for_feedback
        b = self.policy.min_base_score_for_feedback
        self.assertTrue(self.policy.should_apply_feedback(b))


class TestLearningPolicyDecay(unittest.TestCase):

    def setUp(self):
        self.policy = LearningPolicy()

    def test_decay_zero_count(self):
        self.assertEqual(self.policy.apply_decay(10.0, 0), 10.0)

    def test_decay_below_interval(self):
        # decay_count < decay_interval → não decai
        interval = self.policy.decay_interval
        self.assertEqual(self.policy.apply_decay(10.0, interval - 1), 10.0)

    def test_decay_at_interval(self):
        # decay_count == decay_interval → 1 aplicação
        interval = self.policy.decay_interval
        factor = self.policy.decay_factor
        result = self.policy.apply_decay(10.0, interval)
        self.assertAlmostEqual(result, 10.0 * factor)

    def test_decay_multiple_intervals(self):
        interval = self.policy.decay_interval
        factor = self.policy.decay_factor
        result = self.policy.apply_decay(10.0, interval * 3)
        self.assertAlmostEqual(result, 10.0 * (factor ** 3))

    def test_decay_does_not_go_below_min(self):
        interval = self.policy.decay_interval
        result = self.policy.apply_decay(10.0, interval * 1000)
        self.assertGreaterEqual(result, self.policy.min_decayed_weight)

    def test_decay_negative_weight_no_decay(self):
        # Peso negativo não decai (apenas positivos decaem)
        result = self.policy.apply_decay(-5.0, 100)
        self.assertEqual(result, -5.0)


# ---------------------------------------------------------------------------
# FeedbackStore
# ---------------------------------------------------------------------------


class TestFeedbackStoreCRUD(unittest.TestCase):

    def setUp(self):
        self.store = FeedbackStore()
        self.key = make_key()
        self.stats = FeedbackStatistics(key=self.key, acceptances=3,
                                        total_weight=9.0)

    def test_empty_store(self):
        self.assertEqual(len(self.store), 0)

    def test_put_and_get(self):
        self.store.put(self.key, self.stats)
        self.assertEqual(self.store.get(self.key), self.stats)

    def test_get_nonexistent(self):
        self.assertIsNone(self.store.get(self.key))

    def test_has(self):
        self.store.put(self.key, self.stats)
        self.assertTrue(self.store.has(self.key))

    def test_has_nonexistent(self):
        self.assertFalse(self.store.has(self.key))

    def test_contains(self):
        self.store.put(self.key, self.stats)
        self.assertIn(self.key, self.store)

    def test_delete(self):
        self.store.put(self.key, self.stats)
        self.assertTrue(self.store.delete(self.key))
        self.assertIsNone(self.store.get(self.key))

    def test_delete_nonexistent(self):
        self.assertFalse(self.store.delete(self.key))

    def test_list_keys_empty(self):
        self.assertEqual(self.store.list_keys(), ())

    def test_list_keys(self):
        self.store.put(self.key, self.stats)
        keys = self.store.list_keys()
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0], self.key)

    def test_list_all(self):
        self.store.put(self.key, self.stats)
        all_stats = self.store.list_all()
        self.assertEqual(len(all_stats), 1)

    def test_clear(self):
        self.store.put(self.key, self.stats)
        self.store.clear()
        self.assertEqual(len(self.store), 0)

    def test_iter(self):
        self.store.put(self.key, self.stats)
        for stats in self.store:
            self.assertEqual(stats, self.stats)

    def test_put_overwrites(self):
        self.store.put(self.key, self.stats)
        new_stats = FeedbackStatistics(key=self.key, acceptances=5)
        self.store.put(self.key, new_stats)
        self.assertEqual(self.store.get(self.key).acceptances, 5)


class TestFeedbackStorePersistence(unittest.TestCase):

    def setUp(self):
        self.store = FeedbackStore()
        self.key = make_key()
        self.stats = FeedbackStatistics(key=self.key, acceptances=3,
                                        total_weight=9.0,
                                        first_used=1000.0,
                                        last_used=1005.0)

    def test_to_json_empty(self):
        json_str = self.store.to_json()
        self.assertIsInstance(json_str, str)

    def test_to_json_with_data(self):
        self.store.put(self.key, self.stats)
        json_str = self.store.to_json()
        self.assertIn("entries", json_str)

    def test_from_json_roundtrip(self):
        self.store.put(self.key, self.stats)
        json_str = self.store.to_json()
        store2 = FeedbackStore()
        store2.from_json(json_str)
        self.assertEqual(len(store2), 1)
        loaded = store2.get(self.key)
        self.assertEqual(loaded.acceptances, 3)
        self.assertEqual(loaded.total_weight, 9.0)

    def test_save_and_load_file(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            self.store.put(self.key, self.stats)
            self.store.save(tmp)
            self.assertTrue(os.path.exists(tmp))
            store2 = FeedbackStore()
            store2.load(tmp)
            self.assertEqual(len(store2), 1)
            loaded = store2.get(self.key)
            self.assertEqual(loaded, self.stats)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_load_nonexistent_file(self):
        store = FeedbackStore()
        store.load("nonexistent.json")
        self.assertEqual(len(store), 0)

    def test_save_creates_directory(self):
        tmp_dir = tempfile.mkdtemp()
        tmp = os.path.join(tmp_dir, "sub", "feedback.json")
        try:
            self.store.put(self.key, self.stats)
            self.store.save(tmp)
            self.assertTrue(os.path.exists(tmp))
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# FeedbackRepository
# ---------------------------------------------------------------------------


class TestFeedbackRepository(unittest.TestCase):

    def setUp(self):
        self.repo = FeedbackRepository()
        self.key = make_key()
        self.stats = FeedbackStatistics(key=self.key, acceptances=3,
                                        total_weight=9.0)

    def test_empty_repo(self):
        self.assertEqual(len(self.repo), 0)

    def test_save_and_get(self):
        self.repo.save(self.stats)
        self.assertEqual(self.repo.get(self.key), self.stats)

    def test_get_nonexistent(self):
        self.assertIsNone(self.repo.get(self.key))

    def test_delete(self):
        self.repo.save(self.stats)
        self.assertTrue(self.repo.delete(self.key))
        self.assertIsNone(self.repo.get(self.key))

    def test_delete_nonexistent(self):
        self.assertFalse(self.repo.delete(self.key))

    def test_list_all(self):
        self.repo.save(self.stats)
        all_stats = self.repo.list_all()
        self.assertEqual(len(all_stats), 1)

    def test_list_by_query(self):
        self.repo.save(self.stats)
        results = self.repo.list_by_query("pedro", FeedbackScope.GLOBAL)
        self.assertEqual(len(results), 1)
        results = self.repo.list_by_query("outro", FeedbackScope.GLOBAL)
        self.assertEqual(len(results), 0)

    def test_list_by_scope(self):
        self.repo.save(self.stats)
        results = self.repo.list_by_scope(FeedbackScope.GLOBAL)
        self.assertEqual(len(results), 1)
        results = self.repo.list_by_scope(FeedbackScope.SESSION)
        self.assertEqual(len(results), 0)

    def test_clear(self):
        self.repo.save(self.stats)
        self.repo.clear()
        self.assertEqual(len(self.repo), 0)

    def test_contains(self):
        self.repo.save(self.stats)
        self.assertIn(self.key, self.repo)

    def test_path_none_in_memory(self):
        self.assertIsNone(self.repo.path)

    def test_auto_save_default_false(self):
        self.assertFalse(self.repo.auto_save)


class TestFeedbackRepositoryPersistence(unittest.TestCase):

    def test_persistence_with_path(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            key = make_key()
            stats = FeedbackStatistics(key=key, acceptances=3,
                                        total_weight=9.0)
            repo = FeedbackRepository(tmp)
            repo.save(stats)
            repo.flush()
            # Novo repo carrega do mesmo arquivo
            repo2 = FeedbackRepository(tmp)
            self.assertEqual(len(repo2), 1)
            loaded = repo2.get(key)
            self.assertEqual(loaded.acceptances, 3)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_auto_save(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            key = make_key()
            stats = FeedbackStatistics(key=key, acceptances=3,
                                        total_weight=9.0)
            repo = FeedbackRepository(tmp, auto_save=True)
            repo.save(stats)
            # auto_save → arquivo deve existir
            self.assertTrue(os.path.exists(tmp))
            repo2 = FeedbackRepository(tmp)
            self.assertEqual(len(repo2), 1)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_load_on_init(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            key = make_key()
            stats = FeedbackStatistics(key=key, acceptances=5)
            repo = FeedbackRepository(tmp)
            repo.save(stats)
            repo.flush()
            # Novo repo deve carregar automaticamente
            repo2 = FeedbackRepository(tmp)
            self.assertEqual(len(repo2), 1)
            loaded = repo2.get(key)
            self.assertEqual(loaded.acceptances, 5)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


if __name__ == "__main__":
    unittest.main()
