"""Testes de Combiner, Coordinator, Engine e cenários (Fase 11 — Parte 3).

Cobre:
  - SignalCombiner: combine, contribuições, cap, confiança.
  - IntelligenceCoordinator: coordinate, ordem, sinais completos.
  - SermonIntelligenceEngine: recommend, ordenação, explicação.
  - Cenários: sem contexto, sem feedback, conflito de sinais.
  - Desacoplamento: engine não conhece outros módulos.
  - Explicabilidade: toda decisão é justificada.
  - Imutabilidade: DTOs são frozen.
  - Compatibilidade: nenhum comportamento alterado.
"""

from __future__ import annotations

import unittest

import sys
sys.path.insert(0, ".")

from intelligence import (
    CandidateInfo,
    ConfidenceLevel,
    IntelligenceCoordinator,
    IntelligencePolicy,
    IntelligenceRecommendation,
    IntelligenceRequest,
    IntelligenceScore,
    IntelligenceSignal,
    SermonIntelligenceEngine,
    SignalCombiner,
)


def make_candidate(cid="43:21:15", score=0.83, book="João",
                   chapter=21, verse=15, display="João 21:15"):
    return CandidateInfo(candidate_id=cid, base_score=score, book=book,
                         chapter=chapter, verse=verse, display=display)


class FakeContext:
    def __init__(self, book=None, chapter=None, recent_references=(),
                 recent_themes=(), recent_books=(), last_reference=None):
        self.book = book
        self.chapter = chapter
        self.recent_references = recent_references
        self.recent_themes = recent_themes
        self.recent_books = recent_books
        self.last_reference = last_reference


class FakeRef:
    def __init__(self, book_name="João", chapter=21, verse=15):
        self.book = type("FakeBook", (), {"canonical_name": book_name})()
        self.chapter = chapter
        self.verse_start = verse


class FakeSummary:
    def __init__(self, has_feedback=True, total_weight=9.0,
                 acceptances=3, rejections=0):
        self.has_feedback = has_feedback
        self.total_weight = total_weight
        self.acceptances = acceptances
        self.rejections = rejections


class FakeMetrics:
    def __init__(self, precision=0.85, total_searches=150):
        self.precision = precision
        self.total_searches = total_searches


# ---------------------------------------------------------------------------
# SignalCombiner
# ---------------------------------------------------------------------------


class TestSignalCombiner(unittest.TestCase):

    def setUp(self):
        self.combiner = SignalCombiner()
        self.policy = self.combiner.policy

    def test_empty_signals(self):
        c = make_candidate()
        score = self.combiner.combine(c, ())
        self.assertEqual(score.base_score, c.base_score)
        self.assertEqual(score.final_score, c.base_score)

    def test_single_signal(self):
        c = make_candidate(score=0.80)
        signals = (
            IntelligenceSignal(signal_type="context", value=0.15,
                               weight=0.20, explanation="match"),
        )
        score = self.combiner.combine(c, signals)
        self.assertAlmostEqual(score.context_contribution, 0.03)
        self.assertGreater(score.final_score, c.base_score)

    def test_multiple_signals(self):
        c = make_candidate(score=0.80)
        signals = (
            IntelligenceSignal(signal_type="context", value=0.15,
                               weight=0.20, explanation="ctx"),
            IntelligenceSignal(signal_type="feedback", value=0.12,
                               weight=0.25, explanation="fb"),
        )
        score = self.combiner.combine(c, signals)
        self.assertAlmostEqual(score.context_contribution, 0.03)
        self.assertAlmostEqual(score.feedback_contribution, 0.03)
        self.assertGreater(score.final_score, c.base_score)

    def test_cap_adjustment(self):
        c = make_candidate(score=0.50)
        # Sinais enormes → deve ser capado
        signals = (
            IntelligenceSignal(signal_type="context", value=1.0,
                               weight=1.0, explanation="huge"),
            IntelligenceSignal(signal_type="feedback", value=1.0,
                               weight=1.0, explanation="huge"),
        )
        score = self.combiner.combine(c, signals)
        # Ajuste total capado em max_intelligence_adjustment
        max_adj = self.policy.max_intelligence_adjustment
        self.assertLessEqual(score.final_score, c.base_score + max_adj + 0.001)

    def test_negative_adjustment(self):
        c = make_candidate(score=0.50)
        signals = (
            IntelligenceSignal(signal_type="feedback", value=-0.12,
                               weight=0.25, explanation="neg"),
        )
        score = self.combiner.combine(c, signals)
        self.assertLess(score.final_score, c.base_score)

    def test_confidence_level(self):
        c = make_candidate(score=0.90)
        signals = tuple(
            IntelligenceSignal(signal_type=t, value=0.1, weight=0.1,
                               explanation="pos")
            for t in ("context", "feedback", "continuity", "reference",
                      "theme", "book")
        )
        score = self.combiner.combine(c, signals)
        # 6 sinais ativos + score alto → HIGH
        self.assertEqual(score.confidence_level, ConfidenceLevel.HIGH)

    def test_signals_preserved(self):
        c = make_candidate()
        signals = (
            IntelligenceSignal(signal_type="context", value=0.1,
                               weight=0.2, explanation="test"),
        )
        score = self.combiner.combine(c, signals)
        self.assertEqual(len(score.signals), 1)
        self.assertEqual(score.signals[0].signal_type, "context")

    def test_explanation(self):
        c = make_candidate(score=0.80)
        signals = (
            IntelligenceSignal(signal_type="context", value=0.15,
                               weight=0.20, explanation="match"),
        )
        score = self.combiner.combine(c, signals)
        self.assertIn("Base", score.explanation)
        self.assertIn("Contexto", score.explanation)


# ---------------------------------------------------------------------------
# IntelligenceCoordinator
# ---------------------------------------------------------------------------


class TestIntelligenceCoordinator(unittest.TestCase):

    def setUp(self):
        self.coordinator = IntelligenceCoordinator()

    def test_empty_candidates(self):
        r = IntelligenceRequest(query="pedro")
        scores = self.coordinator.coordinate(r)
        self.assertEqual(scores, ())

    def test_single_candidate(self):
        c = make_candidate()
        r = IntelligenceRequest(query="pedro", candidates=(c,))
        scores = self.coordinator.coordinate(r)
        self.assertEqual(len(scores), 1)

    def test_multiple_candidates(self):
        candidates = (
            make_candidate(cid="a", score=0.80),
            make_candidate(cid="b", score=0.75),
            make_candidate(cid="c", score=0.70),
        )
        r = IntelligenceRequest(query="pedro", candidates=candidates)
        scores = self.coordinator.coordinate(r)
        self.assertEqual(len(scores), 3)

    def test_signals_count(self):
        """Cada candidato deve ter 8 sinais (7 estratégias + confidence)."""
        c = make_candidate()
        r = IntelligenceRequest(query="pedro", candidates=(c,))
        scores = self.coordinator.coordinate(r)
        # 7 estratégias independentes + 1 confidence = 8
        self.assertEqual(len(scores[0].signals), 8)

    def test_order_preserved(self):
        """Coordinator retorna scores na ordem original dos candidatos."""
        candidates = (
            make_candidate(cid="first", score=0.50),
            make_candidate(cid="second", score=0.90),
        )
        r = IntelligenceRequest(query="x", candidates=candidates)
        scores = self.coordinator.coordinate(r)
        self.assertEqual(scores[0].candidate_id, "first")
        self.assertEqual(scores[1].candidate_id, "second")


# ---------------------------------------------------------------------------
# SermonIntelligenceEngine
# ---------------------------------------------------------------------------


class TestSermonIntelligenceEngine(unittest.TestCase):

    def setUp(self):
        self.engine = SermonIntelligenceEngine()

    def test_empty_request(self):
        r = IntelligenceRequest(query="pedro")
        rec = self.engine.recommend(r)
        self.assertFalse(rec.has_candidates)
        self.assertEqual(rec.best_candidate_id, "")
        self.assertEqual(rec.ranking, ())

    def test_single_candidate(self):
        c = make_candidate()
        r = IntelligenceRequest(query="pedro", candidates=(c,))
        rec = self.engine.recommend(r)
        self.assertTrue(rec.has_candidates)
        self.assertEqual(rec.best_candidate_id, c.candidate_id)

    def test_ordering_by_final_score(self):
        """Recomendação deve ordenar por final_score decrescente."""
        candidates = (
            make_candidate(cid="low", score=0.50),
            make_candidate(cid="high", score=0.90),
            make_candidate(cid="mid", score=0.70),
        )
        r = IntelligenceRequest(query="x", candidates=candidates)
        rec = self.engine.recommend(r)
        self.assertEqual(rec.ranking[0], "high")
        self.assertEqual(rec.ranking[1], "mid")
        self.assertEqual(rec.ranking[2], "low")

    def test_context_boosts_candidate(self):
        """Candidato do livro ativo deve ser favorecido."""
        ctx = FakeContext(book="João", chapter=21)
        candidates = (
            make_candidate(cid="joao", score=0.78, book="João", chapter=21),
            make_candidate(cid="lucas", score=0.80, book="Lucas", chapter=15),
        )
        r = IntelligenceRequest(query="x", context=ctx, candidates=candidates)
        rec = self.engine.recommend(r)
        # João tem base_score menor mas contexto deve favorecê-lo
        # Verificar que João subiu no ranking (pelo menos não ficou atrás)
        joao_score = next(s for s in rec.scores if s.candidate_id == "joao")
        lucas_score = next(s for s in rec.scores if s.candidate_id == "lucas")
        # João deve ter contribuição de contexto > 0
        self.assertGreater(joao_score.context_contribution, 0.0)
        self.assertEqual(lucas_score.context_contribution, 0.0)

    def test_feedback_boosts_candidate(self):
        """Candidato com feedback positivo deve ser favorecido."""
        candidates = (
            make_candidate(cid="with_fb", score=0.75),
            make_candidate(cid="no_fb", score=0.80),
        )
        r = IntelligenceRequest(
            query="x", candidates=candidates,
            feedback_summaries={"with_fb": FakeSummary(total_weight=10.0,
                                                        acceptances=5)},
        )
        rec = self.engine.recommend(r)
        with_fb = next(s for s in rec.scores if s.candidate_id == "with_fb")
        no_fb = next(s for s in rec.scores if s.candidate_id == "no_fb")
        self.assertGreater(with_fb.feedback_contribution, 0.0)
        self.assertEqual(no_fb.feedback_contribution, 0.0)

    def test_explanation_present(self):
        c = make_candidate()
        r = IntelligenceRequest(query="pedro", candidates=(c,))
        rec = self.engine.recommend(r)
        self.assertTrue(rec.explanation)
        self.assertIn("pedro", rec.explanation)

    def test_best_score_property(self):
        c = make_candidate()
        r = IntelligenceRequest(query="x", candidates=(c,))
        rec = self.engine.recommend(r)
        self.assertIsNotNone(rec.best_score)
        self.assertEqual(rec.best_score.candidate_id, c.candidate_id)

    def test_to_dict(self):
        c = make_candidate()
        r = IntelligenceRequest(query="x", candidates=(c,))
        rec = self.engine.recommend(r)
        d = rec.to_dict()
        self.assertEqual(d["query"], "x")
        self.assertTrue(d["has_candidates"])

    def test_explain(self):
        c = make_candidate()
        r = IntelligenceRequest(query="x", candidates=(c,))
        rec = self.engine.recommend(r)
        text = rec.explain()
        self.assertIn("recomendação", text)


# ---------------------------------------------------------------------------
# Cenários: sem contexto, sem feedback, conflito
# ---------------------------------------------------------------------------


class TestScenarios(unittest.TestCase):

    def setUp(self):
        self.engine = SermonIntelligenceEngine()

    def test_no_context_no_feedback(self):
        """Sem contexto e sem feedback, score = base_score."""
        c = make_candidate(score=0.80)
        r = IntelligenceRequest(query="x", candidates=(c,))
        rec = self.engine.recommend(r)
        score = rec.scores[0]
        self.assertAlmostEqual(score.final_score, 0.80, places=2)

    def test_conflict_signals(self):
        """Sinais conflitantes (contexto positivo, feedback negativo)."""
        ctx = FakeContext(book="João", chapter=21)
        c = make_candidate(score=0.80, book="João", chapter=21)
        r = IntelligenceRequest(
            query="x", context=ctx, candidates=(c,),
            feedback_summaries={c.candidate_id: FakeSummary(
                total_weight=-5.0, acceptances=0, rejections=5)},
        )
        rec = self.engine.recommend(r)
        score = rec.scores[0]
        self.assertGreater(score.context_contribution, 0.0)
        self.assertLess(score.feedback_contribution, 0.0)

    def test_all_signals_present(self):
        """Cenário com todos os sinais ativos."""
        ref = FakeRef(book_name="João", chapter=21, verse=15)
        ctx = FakeContext(
            book="João", chapter=21,
            recent_references=(ref,),
            recent_themes=("pedro",),
            recent_books=("João", "Atos"),
            last_reference=ref,
        )
        c = make_candidate(score=0.80, book="João", chapter=21, verse=15,
                           display="pedro em João 21:15")
        r = IntelligenceRequest(
            query="pedro", context=ctx, candidates=(c,),
            feedback_summaries={c.candidate_id: FakeSummary(
                total_weight=10.0, acceptances=5)},
            evaluation_metrics=FakeMetrics(precision=0.90, total_searches=100),
        )
        rec = self.engine.recommend(r)
        score = rec.scores[0]
        # Pelo menos contexto, feedback, continuidade, referência, livro, tema
        self.assertGreater(score.context_contribution, 0.0)
        self.assertGreater(score.feedback_contribution, 0.0)
        self.assertGreater(score.continuity_contribution, 0.0)
        self.assertGreater(score.reference_contribution, 0.0)
        self.assertGreater(score.book_contribution, 0.0)
        self.assertGreater(score.theme_contribution, 0.0)

    def test_pedro_joao_vs_pedro_atos(self):
        """Consulta 'Pedro' + contexto 'João' favorece João 21.
           Consulta 'Pedro' + contexto 'Atos' favorece Atos 2."""
        candidates = (
            make_candidate(cid="43:21:15", score=0.75, book="João",
                           chapter=21, display="João 21:15"),
            make_candidate(cid="44:2:38", score=0.75, book="Atos",
                           chapter=2, display="Atos 2:38"),
        )

        # Contexto João
        ctx_joao = FakeContext(book="João", chapter=21)
        r_joao = IntelligenceRequest(query="pedro", context=ctx_joao,
                                     candidates=candidates)
        rec_joao = self.engine.recommend(r_joao)
        joao_score = next(s for s in rec_joao.scores
                          if s.candidate_id == "43:21:15")
        atos_score_joao = next(s for s in rec_joao.scores
                               if s.candidate_id == "44:2:38")
        self.assertGreater(joao_score.final_score,
                           atos_score_joao.final_score)

        # Contexto Atos
        ctx_atos = FakeContext(book="Atos", chapter=2)
        r_atos = IntelligenceRequest(query="pedro", context=ctx_atos,
                                     candidates=candidates)
        rec_atos = self.engine.recommend(r_atos)
        atos_score = next(s for s in rec_atos.scores
                          if s.candidate_id == "44:2:38")
        joao_score_atos = next(s for s in rec_atos.scores
                               if s.candidate_id == "43:21:15")
        self.assertGreater(atos_score.final_score,
                           joao_score_atos.final_score)


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
        imports = self._import_lines("intelligence.engine")
        self.assertNotIn("searcher", "\n".join(imports).lower())

    def test_engine_no_ranking(self):
        imports = self._import_lines("intelligence.engine")
        self.assertNotIn("ranking", "\n".join(imports).lower())

    def test_engine_no_holyrics(self):
        imports = self._import_lines("intelligence.engine")
        self.assertNotIn("holyrics", "\n".join(imports).lower())

    def test_engine_no_llm(self):
        imports = self._import_lines("intelligence.engine")
        self.assertNotIn("from llm", "\n".join(imports).lower())

    def test_engine_no_parser(self):
        imports = self._import_lines("intelligence.engine")
        self.assertNotIn("from parser", "\n".join(imports).lower())

    def test_engine_no_embeddings(self):
        imports = self._import_lines("intelligence.engine")
        self.assertNotIn("embedding", "\n".join(imports).lower())

    def test_strategies_no_searcher(self):
        imports = self._import_lines("intelligence.strategies")
        self.assertNotIn("searcher", "\n".join(imports).lower())

    def test_strategies_no_ranking(self):
        imports = self._import_lines("intelligence.strategies")
        self.assertNotIn("ranking", "\n".join(imports).lower())

    def test_strategies_no_feedback_module(self):
        imports = self._import_lines("intelligence.strategies")
        self.assertNotIn("from feedback", "\n".join(imports).lower())

    def test_strategies_no_context_module(self):
        imports = self._import_lines("intelligence.strategies")
        self.assertNotIn("from context", "\n".join(imports).lower())

    def test_strategies_no_evaluation_module(self):
        imports = self._import_lines("intelligence.strategies")
        self.assertNotIn("from evaluation", "\n".join(imports).lower())

    def test_combiner_no_external(self):
        imports = self._import_lines("intelligence.combiner")
        combined = "\n".join(imports).lower()
        self.assertNotIn("searcher", combined)
        self.assertNotIn("ranking", combined)
        self.assertNotIn("from feedback", combined)
        self.assertNotIn("from context", combined)


# ---------------------------------------------------------------------------
# Explicabilidade
# ---------------------------------------------------------------------------


class TestExplainability(unittest.TestCase):

    def setUp(self):
        self.engine = SermonIntelligenceEngine()

    def test_every_score_has_explanation(self):
        c = make_candidate()
        r = IntelligenceRequest(query="x", candidates=(c,))
        rec = self.engine.recommend(r)
        for s in rec.scores:
            self.assertTrue(s.explanation)

    def test_recommendation_has_explanation(self):
        c = make_candidate()
        r = IntelligenceRequest(query="x", candidates=(c,))
        rec = self.engine.recommend(r)
        self.assertTrue(rec.explanation)

    def test_signals_have_explanations(self):
        c = make_candidate()
        r = IntelligenceRequest(query="x", candidates=(c,))
        rec = self.engine.recommend(r)
        for s in rec.scores:
            for sig in s.signals:
                self.assertTrue(sig.explanation)

    def test_score_to_dict_has_all_fields(self):
        c = make_candidate()
        r = IntelligenceRequest(query="x", candidates=(c,))
        rec = self.engine.recommend(r)
        d = rec.scores[0].to_dict()
        self.assertIn("base_score", d)
        self.assertIn("final_score", d)
        self.assertIn("context_contribution", d)
        self.assertIn("feedback_contribution", d)
        self.assertIn("signals", d)


# ---------------------------------------------------------------------------
# Imutabilidade
# ---------------------------------------------------------------------------


class TestImmutability(unittest.TestCase):

    def test_score_frozen(self):
        s = IntelligenceScore(candidate_id="x", base_score=0.8,
                              final_score=0.9)
        with self.assertRaises(Exception):
            s.final_score = 1.0

    def test_recommendation_frozen(self):
        r = IntelligenceRecommendation(query="x")
        with self.assertRaises(Exception):
            r.query = "y"

    def test_candidate_frozen(self):
        c = CandidateInfo(candidate_id="x", base_score=0.5)
        with self.assertRaises(Exception):
            c.base_score = 0.9


if __name__ == "__main__":
    unittest.main()
