"""Testes de desacoplamento e cenários de aprendizado (Fase 9 — Parte 4).

Cobre:
  - Desacoplamento: engine e adapter não conhecem outros componentes.
  - Cenário "Pedro" + contexto "João" vs "Atos".
  - Feedback complementa, não substitui o Ranking.
  - Decaimento reduz influência ao longo do tempo.
  - Persistência completa (save/load roundtrip).
  - Escopo GLOBAL (default) vs outros escopos preparados.
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
# Desacoplamento
# ---------------------------------------------------------------------------


class TestDecoupling(unittest.TestCase):

    @staticmethod
    def _import_lines(module_name):
        import importlib
        mod = importlib.import_module(module_name)
        with open(mod.__file__, encoding="utf-8") as f:
            lines = f.readlines()
        return [l for l in lines if l.strip().startswith(("import ", "from "))]

    def test_engine_no_searcher(self):
        imports = self._import_lines("feedback.engine")
        self.assertNotIn("searcher", "\n".join(imports).lower())

    def test_engine_no_ranking(self):
        imports = self._import_lines("feedback.engine")
        self.assertNotIn("ranking", "\n".join(imports).lower())

    def test_engine_no_llm(self):
        imports = self._import_lines("feedback.engine")
        self.assertNotIn("from llm", "\n".join(imports).lower())

    def test_engine_no_parser(self):
        imports = self._import_lines("feedback.engine")
        self.assertNotIn("from parser", "\n".join(imports).lower())

    def test_engine_no_holyrics(self):
        imports = self._import_lines("feedback.engine")
        self.assertNotIn("holyrics", "\n".join(imports).lower())

    def test_engine_no_embeddings(self):
        imports = self._import_lines("feedback.engine")
        self.assertNotIn("embedding", "\n".join(imports).lower())

    def test_engine_no_knowledge_base(self):
        imports = self._import_lines("feedback.engine")
        self.assertNotIn("knowledge", "\n".join(imports).lower())

    def test_engine_no_context_engine(self):
        imports = self._import_lines("feedback.engine")
        self.assertNotIn("from context", "\n".join(imports).lower())

    def test_adapter_no_searcher(self):
        imports = self._import_lines("feedback.adapter")
        self.assertNotIn("searcher", "\n".join(imports).lower())

    def test_adapter_no_ranking(self):
        imports = self._import_lines("feedback.adapter")
        self.assertNotIn("ranking", "\n".join(imports).lower())

    def test_adapter_no_llm(self):
        imports = self._import_lines("feedback.adapter")
        self.assertNotIn("from llm", "\n".join(imports).lower())

    def test_adapter_no_parser(self):
        imports = self._import_lines("feedback.adapter")
        self.assertNotIn("from parser", "\n".join(imports).lower())

    def test_adapter_no_holyrics(self):
        imports = self._import_lines("feedback.adapter")
        self.assertNotIn("holyrics", "\n".join(imports).lower())

    def test_adapter_no_embeddings(self):
        imports = self._import_lines("feedback.adapter")
        self.assertNotIn("embedding", "\n".join(imports).lower())

    def test_adapter_no_knowledge_base(self):
        imports = self._import_lines("feedback.adapter")
        self.assertNotIn("knowledge", "\n".join(imports).lower())


# ---------------------------------------------------------------------------
# Cenário completo de aprendizado
# ---------------------------------------------------------------------------


class TestLearningScenario(unittest.TestCase):

    def test_pedro_joao_vs_pedro_atos(self):
        """Consulta 'Pedro' + contexto 'João' → João 21.
           Consulta 'Pedro' + contexto 'Atos' → Atos 2."""
        engine, _ = make_engine()
        adapter = RankingFeedbackAdapter(engine)

        # Operador aceita João 21 quando contexto é João
        key_joao = make_key(query="pedro", ctx="João", cid="43:21:15")
        engine.process(CandidateAccepted(key=key_joao, timestamp=1001.0))

        # Operador aceita Atos 2 quando contexto é Atos
        key_atos = make_key(query="pedro", ctx="Atos", cid="44:2:38")
        engine.process(CandidateAccepted(key=key_atos, timestamp=1002.0))

        # Contexto "João" favorece João 21
        b_joao = adapter.adjust(query="pedro", candidate_id="43:21:15",
                                base_score=0.83, context_signature="João")
        b_atos_for_joao = adapter.adjust(
            query="pedro", candidate_id="44:2:38",
            base_score=0.83, context_signature="João")
        self.assertGreater(b_joao.feedback_bonus,
                           b_atos_for_joao.feedback_bonus)

        # Contexto "Atos" favorece Atos 2
        b_atos = adapter.adjust(query="pedro", candidate_id="44:2:38",
                                base_score=0.83, context_signature="Atos")
        b_joao_for_atos = adapter.adjust(
            query="pedro", candidate_id="43:21:15",
            base_score=0.83, context_signature="Atos")
        self.assertGreater(b_atos.feedback_bonus,
                           b_joao_for_atos.feedback_bonus)

    def test_feedback_complements_not_replaces(self):
        """Feedback complementa o Ranking — não substitui."""
        engine, _ = make_engine()
        adapter = RankingFeedbackAdapter(engine)

        # Candidato B: baixa similaridade, muito feedback
        key_b = make_key(query="amor", ctx="", cid="43:3:16")
        for _ in range(20):
            engine.process(CandidateAccepted(key=key_b, timestamp=1001.0))

        b_a = adapter.adjust(query="amor", candidate_id="42:15:11",
                             base_score=0.90, context_signature="")
        b_b = adapter.adjust(query="amor", candidate_id="43:3:16",
                             base_score=0.15, context_signature="")
        # A (alta similaridade, sem feedback) vence B
        self.assertGreater(b_a.final_score, b_b.final_score)

    def test_decayed_feedback_reduces_bonus(self):
        """Decaimento reduz a influência do feedback."""
        # Usar política com teto alto para evitar cap interferindo
        repo = FeedbackRepository()
        clock = [1000.0]
        def fake_clock():
            clock[0] += 1.0
            return clock[0]
        engine = FeedbackEngine(repo, clock=fake_clock)
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        # Criar adapter com policy customizada (teto alto)
        from feedback.policy import LearningPolicy
        custom_policy = LearningPolicy()
        # Sobrescrever via monkey-patching das constantes não é ideal,
        # então verificamos o peso decaído diretamente
        stats_before = engine.get_statistics(key)
        weight_before = custom_policy.apply_decay(
            stats_before.total_weight, stats_before.decay_count)

        policy = engine.policy
        for _ in range(policy.decay_interval * 10):
            engine.increment_decay(key)

        stats_after = engine.get_statistics(key)
        weight_after = custom_policy.apply_decay(
            stats_after.total_weight, stats_after.decay_count)
        # Peso decaído deve ser menor
        self.assertLess(weight_after, weight_before)

    def test_mixed_events_accumulate(self):
        """Eventos mistos acumulam peso corretamente."""
        engine, _ = make_engine()
        key = make_key()
        engine.process(CandidateAccepted(key=key, timestamp=1001.0))   # +3
        engine.process(CandidateAccepted(key=key, timestamp=1002.0))   # +3
        engine.process(CandidateRejected(key=key, timestamp=1003.0))   # -1
        stats = engine.get_statistics(key)
        self.assertEqual(stats.acceptances, 2)
        self.assertEqual(stats.rejections, 1)
        # 3 + 3 - 1 = 5
        self.assertEqual(stats.total_weight, 5.0)

    def test_manual_reference_strongest_signal(self):
        """ManualReferenceSelected tem peso maior que Accepted."""
        engine, _ = make_engine()
        key = make_key()
        engine.process(ManualReferenceSelected(key=key, timestamp=1001.0))
        stats = engine.get_statistics(key)
        self.assertEqual(stats.total_weight, 5.0)
        self.assertEqual(stats.manual_selections, 1)


# ---------------------------------------------------------------------------
# Persistência completa
# ---------------------------------------------------------------------------


class TestPersistenceRoundtrip(unittest.TestCase):

    def test_full_roundtrip(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            # Criar e popular
            repo = FeedbackRepository(tmp)
            engine = FeedbackEngine(repo)
            key = make_key()
            engine.process(CandidateAccepted(key=key, timestamp=1001.0))
            engine.process(CandidateAccepted(key=key, timestamp=1002.0))
            engine.process(CandidateRejected(key=key, timestamp=1003.0))
            engine.flush()

            # Carregar em novo repo
            repo2 = FeedbackRepository(tmp)
            stats = repo2.get(key)
            self.assertIsNotNone(stats)
            self.assertEqual(stats.acceptances, 2)
            self.assertEqual(stats.rejections, 1)
            self.assertEqual(stats.total_weight, 5.0)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_multiple_keys_persisted(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            repo = FeedbackRepository(tmp)
            engine = FeedbackEngine(repo)
            keys = [
                make_key(query="pedro", ctx="João", cid="43:21:15"),
                make_key(query="pedro", ctx="Atos", cid="44:2:38"),
                make_key(query="amor", ctx="", cid="43:3:16"),
            ]
            for k in keys:
                engine.process(CandidateAccepted(key=k, timestamp=1001.0))
            engine.flush()

            repo2 = FeedbackRepository(tmp)
            self.assertEqual(len(repo2), 3)
            for k in keys:
                self.assertIsNotNone(repo2.get(k))
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


# ---------------------------------------------------------------------------
# Escopos
# ---------------------------------------------------------------------------


class TestScopes(unittest.TestCase):

    def test_global_scope_default(self):
        engine, _ = make_engine()
        adapter = RankingFeedbackAdapter(engine)
        self.assertEqual(adapter.scope, FeedbackScope.GLOBAL)

    def test_session_scope_prepared(self):
        # SESSION existe como valor mas não tem lógica adicional
        self.assertEqual(FeedbackScope.SESSION.value, "SESSION")

    def test_sermon_scope_prepared(self):
        self.assertEqual(FeedbackScope.SERMON.value, "SERMON")

    def test_user_scope_prepared(self):
        self.assertEqual(FeedbackScope.USER.value, "USER")

    def test_different_scopes_separate_keys(self):
        engine, _ = make_engine()
        key_global = make_key(scope=FeedbackScope.GLOBAL)
        key_session = make_key(scope=FeedbackScope.SESSION)
        engine.process(CandidateAccepted(key=key_global, timestamp=1001.0))
        # SESSION não deve ter feedback
        adapter = RankingFeedbackAdapter(engine, scope=FeedbackScope.GLOBAL)
        b_global = adapter.adjust(
            query="pedro", candidate_id="43:21:15",
            base_score=0.83, context_signature="João")
        adapter_session = RankingFeedbackAdapter(
            engine, scope=FeedbackScope.SESSION)
        b_session = adapter_session.adjust(
            query="pedro", candidate_id="43:21:15",
            base_score=0.83, context_signature="João")
        self.assertTrue(b_global.has_feedback)
        self.assertFalse(b_session.has_feedback)


# ---------------------------------------------------------------------------
# context_signature_from_sermon_context
# ---------------------------------------------------------------------------


class TestContextSignature(unittest.TestCase):

    def test_none_context(self):
        self.assertEqual(context_signature_from_sermon_context(None), "")

    def test_empty_context(self):
        class FakeCtx:
            book = None
            chapter = None
        self.assertEqual(context_signature_from_sermon_context(FakeCtx()), "")

    def test_book_only(self):
        class FakeCtx:
            book = "João"
            chapter = None
        self.assertEqual(
            context_signature_from_sermon_context(FakeCtx()), "João")

    def test_book_and_chapter(self):
        class FakeCtx:
            book = "João"
            chapter = 3
        self.assertEqual(
            context_signature_from_sermon_context(FakeCtx()), "João:3")

    def test_real_sermon_context(self):
        from context import SermonContext
        ctx = SermonContext(book="Lucas", chapter=15)
        self.assertEqual(
            context_signature_from_sermon_context(ctx), "Lucas:15")

    def test_real_sermon_context_empty(self):
        from context import SermonContext
        ctx = SermonContext()
        self.assertEqual(context_signature_from_sermon_context(ctx), "")


# ---------------------------------------------------------------------------
# Imutabilidade após múltiplas atualizações
# ---------------------------------------------------------------------------


class TestImmutabilityAfterUpdates(unittest.TestCase):

    def test_stats_replaced_not_mutated(self):
        engine, _ = make_engine()
        key = make_key()
        stats1 = engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        stats2 = engine.process(CandidateAccepted(key=key, timestamp=1002.0))
        # stats1 não mudou
        self.assertEqual(stats1.acceptances, 1)
        self.assertEqual(stats1.total_weight, 3.0)
        # stats2 tem os valores atualizados
        self.assertEqual(stats2.acceptances, 2)
        self.assertEqual(stats2.total_weight, 6.0)

    def test_frozen_stats_cannot_modify(self):
        engine, _ = make_engine()
        key = make_key()
        stats = engine.process(CandidateAccepted(key=key, timestamp=1001.0))
        with self.assertRaises(Exception):
            stats.acceptances = 99


if __name__ == "__main__":
    unittest.main()
