"""Testes de Reports, Regressions e cenários (Fase 10 — Parte 4).

Cobre:
  - ReportGenerator: generate, generate_summary, to_text.
  - RegressionDetector: detect, checks individuais, severidade.
  - Cenários completos: sermão, persistência, desacoplamento.
  - Explicabilidade: rastreabilidade de métricas.
  - Compatibilidade: nenhum comportamento alterado.
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
    EvaluationReport,
    EvaluationRepository,
    EvaluationSummary,
    ManualCorrection,
    MetricsCalculator,
    NoResultFound,
    QueryClassification,
    RegressionAlert,
    RegressionDetector,
    ReportGenerator,
    SearchExecuted,
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
# ReportGenerator
# ---------------------------------------------------------------------------


class TestReportGenerator(unittest.TestCase):

    def setUp(self):
        self.gen = ReportGenerator()

    def test_generate_empty(self):
        report = self.gen.generate((), window=TemporalWindow.ALL, now=1000.0)
        self.assertEqual(report.summary.total_records, 0)
        self.assertEqual(report.summary.metrics.total_searches, 0)

    def test_generate_with_records(self):
        records = (
            EvaluationRecord("r1", 1000, "search_executed",
                             query="pedro", duration_ms=250, book="João"),
            EvaluationRecord("r2", 1001, "candidate_presented",
                             candidate_id="43:3:16"),
            EvaluationRecord("r3", 1002, "candidate_accepted",
                             candidate_id="43:3:16", book="João"),
        )
        report = self.gen.generate(records, window=TemporalWindow.ALL,
                                   now=1010.0)
        self.assertEqual(report.summary.total_records, 3)
        self.assertEqual(report.summary.metrics.total_searches, 1)
        self.assertEqual(report.summary.metrics.total_accepted, 1)

    def test_generate_with_temporal_slices(self):
        records = (
            EvaluationRecord("r1", 1000, "search_executed"),
            EvaluationRecord("r2", 200000, "search_executed"),
        )
        report = self.gen.generate(records, window=TemporalWindow.ALL,
                                   now=200000.0)
        self.assertEqual(len(report.temporal_slices), 4)

    def test_generate_summary(self):
        records = (
            EvaluationRecord("r1", 1000, "search_executed"),
        )
        summary = self.gen.generate_summary(records)
        self.assertEqual(summary.total_records, 1)

    def test_to_text(self):
        records = (
            EvaluationRecord("r1", 1000, "search_executed", duration_ms=250),
            EvaluationRecord("r2", 1001, "candidate_accepted"),
        )
        report = self.gen.generate(records, window=TemporalWindow.ALL,
                                   now=1010.0)
        text = self.gen.to_text(report)
        self.assertIn("Relatório", text)
        self.assertIn("Buscas:", text)

    def test_to_text_with_regressions(self):
        records = (
            EvaluationRecord("r1", 1000, "candidate_accepted"),
        )
        prev = EvaluationMetrics(total_accepted=10, total_rejected=0,
                                 total_manual_corrections=0)
        # Atual: 1/(1+0+0) = 100% — sem regressão
        report = self.gen.generate(records, window=TemporalWindow.ALL,
                                   now=1010.0, previous_metrics=prev)
        # Sem regressão (melhorou)
        self.assertEqual(len(report.regressions), 0)

    def test_generate_with_hardest_queries(self):
        records = (
            EvaluationRecord("r1", 1000, "candidate_rejected", query="amor"),
            EvaluationRecord("r2", 1001, "manual_correction", query="amor"),
        )
        report = self.gen.generate(records, window=TemporalWindow.ALL,
                                   now=1010.0)
        self.assertGreater(len(report.summary.hardest_queries), 0)
        self.assertEqual(report.summary.hardest_queries[0][0], "amor")


# ---------------------------------------------------------------------------
# RegressionDetector
# ---------------------------------------------------------------------------


class TestRegressionDetector(unittest.TestCase):

    def setUp(self):
        self.detector = RegressionDetector()

    def test_no_regression_when_improving(self):
        prev = EvaluationMetrics(total_accepted=5, total_rejected=5)
        curr = EvaluationMetrics(total_accepted=10, total_rejected=0)
        alerts = self.detector.detect(prev, curr, now=1000.0)
        self.assertEqual(len(alerts), 0)

    def test_precision_drop(self):
        prev = EvaluationMetrics(total_accepted=90, total_rejected=10)
        curr = EvaluationMetrics(total_accepted=70, total_rejected=30)
        alerts = self.detector.detect(prev, curr, now=1000.0)
        # prev: 90%, curr: 70% → drop 20 p.p. (>= 5)
        precision_alerts = [a for a in alerts if a.metric_name == "precision"]
        self.assertEqual(len(precision_alerts), 1)
        self.assertEqual(precision_alerts[0].severity, "high")

    def test_duration_increase(self):
        prev = EvaluationMetrics(total_searches=10, total_duration_ms=1000.0)
        curr = EvaluationMetrics(total_searches=10, total_duration_ms=2000.0)
        alerts = self.detector.detect(prev, curr, now=1000.0)
        # 100% increase (>= 50%)
        duration_alerts = [a for a in alerts if a.metric_name == "avg_duration_ms"]
        self.assertEqual(len(duration_alerts), 1)

    def test_corrections_increase(self):
        prev = EvaluationMetrics(total_manual_corrections=10)
        curr = EvaluationMetrics(total_manual_corrections=20)
        alerts = self.detector.detect(prev, curr, now=1000.0)
        corr_alerts = [a for a in alerts
                       if a.metric_name == "total_manual_corrections"]
        self.assertEqual(len(corr_alerts), 1)

    def test_no_result_increase(self):
        prev = EvaluationMetrics(total_no_result=10)
        curr = EvaluationMetrics(total_no_result=20)
        alerts = self.detector.detect(prev, curr, now=1000.0)
        nr_alerts = [a for a in alerts if a.metric_name == "total_no_result"]
        self.assertEqual(len(nr_alerts), 1)

    def test_no_regression_when_previous_zero(self):
        # Se previous = 0, não detecta (evita divisão por zero)
        prev = EvaluationMetrics()
        curr = EvaluationMetrics(total_no_result=100)
        alerts = self.detector.detect(prev, curr, now=1000.0)
        # total_no_result anterior = 0 → não detecta
        nr_alerts = [a for a in alerts if a.metric_name == "total_no_result"]
        self.assertEqual(len(nr_alerts), 0)

    def test_severity_low(self):
        # prev: 96/100 = 96%, curr: 90/100 = 90% → drop 6 p.p. → low
        prev = EvaluationMetrics(total_accepted=96, total_rejected=4)
        curr = EvaluationMetrics(total_accepted=90, total_rejected=10)
        alerts = self.detector.detect(prev, curr, now=1000.0)
        precision_alerts = [a for a in alerts if a.metric_name == "precision"]
        self.assertEqual(len(precision_alerts), 1)
        self.assertEqual(precision_alerts[0].severity, "low")

    def test_severity_medium(self):
        # prev: 90/100 = 90%, curr: 79/100 = 79% → drop 11 p.p. → medium
        prev = EvaluationMetrics(total_accepted=90, total_rejected=10)
        curr = EvaluationMetrics(total_accepted=79, total_rejected=21)
        alerts = self.detector.detect(prev, curr, now=1000.0)
        precision_alerts = [a for a in alerts if a.metric_name == "precision"]
        self.assertEqual(len(precision_alerts), 1)
        self.assertEqual(precision_alerts[0].severity, "medium")

    def test_alert_has_all_fields(self):
        prev = EvaluationMetrics(total_accepted=90, total_rejected=10)
        curr = EvaluationMetrics(total_accepted=70, total_rejected=30)
        alerts = self.detector.detect(prev, curr, now=1234.0)
        a = alerts[0]
        self.assertEqual(a.detected_at, 1234.0)
        self.assertGreater(a.threshold, 0)
        self.assertGreater(a.previous_value, a.current_value)


# ---------------------------------------------------------------------------
# Cenário completo
# ---------------------------------------------------------------------------


class TestFullScenario(unittest.TestCase):

    def test_sermon_scenario(self):
        """Simula um sermão com múltiplas buscas e decisões."""
        engine, _ = make_engine()

        # Busca 1: "Pedro" em João → aceito
        engine.record(SearchExecuted(
            query="pedro", classification=QueryClassification.CHARACTER,
            duration_ms=250, result_count=5, book="João", timestamp=1001.0))
        engine.record(CandidatePresented(
            query="pedro", candidate_id="43:21:15", rank_position=1,
            timestamp=1002.0))
        engine.record(CandidateAccepted(
            query="pedro", candidate_id="43:21:15", book="João",
            timestamp=1003.0))

        # Busca 2: "amor" → rejeitado + correção manual
        engine.record(SearchExecuted(
            query="amor", classification=QueryClassification.THEME,
            duration_ms=180, result_count=3, timestamp=1004.0))
        engine.record(CandidatePresented(
            query="amor", candidate_id="43:3:16", rank_position=1,
            timestamp=1005.0))
        engine.record(CandidateRejected(
            query="amor", candidate_id="43:3:16", book="João",
            timestamp=1006.0))
        engine.record(ManualCorrection(
            query="amor", original_candidate_id="43:3:16",
            corrected_candidate_id="62:1:1", book="1 João",
            timestamp=1007.0))

        # Busca 3: "dilúvio" → sem resultado
        engine.record(SearchExecuted(
            query="dilúvio", classification=QueryClassification.EVENT,
            duration_ms=300, result_count=0, book="Gênesis",
            timestamp=1008.0))
        engine.record(NoResultFound(
            query="dilúvio", book="Gênesis", timestamp=1009.0))

        # Gerar relatório
        gen = ReportGenerator()
        records = engine.list_records()
        report = gen.generate(records, window=TemporalWindow.ALL, now=1010.0)

        self.assertEqual(report.summary.metrics.total_searches, 3)
        self.assertEqual(report.summary.metrics.total_accepted, 1)
        self.assertEqual(report.summary.metrics.total_rejected, 1)
        self.assertEqual(report.summary.metrics.total_manual_corrections, 1)
        self.assertEqual(report.summary.metrics.total_no_result, 1)

        # Consultas mais difíceis
        hardest = report.summary.hardest_queries
        self.assertGreater(len(hardest), 0)
        # "amor" tem 2 falhas (rejeição + correção)
        # "dilúvio" tem 1 falha (sem resultado)
        self.assertEqual(hardest[0][0], "amor")

    def test_persistence_roundtrip(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            repo = EvaluationRepository(tmp)
            engine = EvaluationEngine(repo)
            engine.record(SearchExecuted(
                query="pedro", duration_ms=250, timestamp=1001.0))
            engine.flush()

            repo2 = EvaluationRepository(tmp)
            engine2 = EvaluationEngine(repo2)
            records = engine2.list_records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].query, "pedro")
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


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
        imports = self._import_lines("evaluation.engine")
        self.assertNotIn("searcher", "\n".join(imports).lower())

    def test_engine_no_ranking(self):
        imports = self._import_lines("evaluation.engine")
        self.assertNotIn("ranking", "\n".join(imports).lower())

    def test_engine_no_feedback(self):
        imports = self._import_lines("evaluation.engine")
        self.assertNotIn("feedback", "\n".join(imports).lower())

    def test_engine_no_context(self):
        imports = self._import_lines("evaluation.engine")
        self.assertNotIn("from context", "\n".join(imports).lower())

    def test_engine_no_llm(self):
        imports = self._import_lines("evaluation.engine")
        self.assertNotIn("from llm", "\n".join(imports).lower())

    def test_engine_no_holyrics(self):
        imports = self._import_lines("evaluation.engine")
        self.assertNotIn("holyrics", "\n".join(imports).lower())

    def test_metrics_no_searcher(self):
        imports = self._import_lines("evaluation.metrics")
        self.assertNotIn("searcher", "\n".join(imports).lower())

    def test_reports_no_searcher(self):
        imports = self._import_lines("evaluation.reports")
        self.assertNotIn("searcher", "\n".join(imports).lower())

    def test_regressions_no_searcher(self):
        imports = self._import_lines("evaluation.regressions")
        self.assertNotIn("searcher", "\n".join(imports).lower())


# ---------------------------------------------------------------------------
# Explicabilidade — rastreabilidade
# ---------------------------------------------------------------------------


class TestExplainability(unittest.TestCase):

    def test_record_has_query_and_candidate(self):
        """Toda métrica é rastreável até o registro original."""
        engine, _ = make_engine()
        r = engine.record(SearchExecuted(
            query="pedro", classification=QueryClassification.CHARACTER,
            timestamp=1001.0))
        # Pode-se recuperar o registro pelo ID
        retrieved = engine.get_record(r.record_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.query, "pedro")
        self.assertEqual(retrieved.classification, QueryClassification.CHARACTER)

    def test_metrics_breakdown_by_classification(self):
        """Métricas podem ser decompostas por classificação."""
        records = (
            EvaluationRecord("r1", 1000, "search_executed",
                             classification=QueryClassification.CHARACTER),
            EvaluationRecord("r2", 1001, "search_executed",
                             classification=QueryClassification.THEME),
        )
        calc = MetricsCalculator()
        m = calc.calculate(records)
        self.assertEqual(len(m.by_classification), 2)

    def test_report_to_dict_includes_all(self):
        """Relatório serializado inclui todos os dados para auditoria."""
        records = (EvaluationRecord("r1", 1000, "search_executed"),)
        gen = ReportGenerator()
        report = gen.generate(records, window=TemporalWindow.ALL, now=1010.0)
        d = report.to_dict()
        self.assertIn("summary", d)
        self.assertIn("temporal_slices", d)
        self.assertIn("regressions", d)


# ---------------------------------------------------------------------------
# Imutabilidade após múltiplas atualizações
# ---------------------------------------------------------------------------


class TestImmutability(unittest.TestCase):

    def test_records_are_frozen(self):
        engine, _ = make_engine()
        r = engine.record(SearchExecuted(query="a", timestamp=1001.0))
        with self.assertRaises(Exception):
            r.query = "b"

    def test_metrics_are_frozen(self):
        calc = MetricsCalculator()
        m = calc.calculate(())
        with self.assertRaises(Exception):
            m.total_searches = 99

    def test_report_is_frozen(self):
        gen = ReportGenerator()
        report = gen.generate((), window=TemporalWindow.ALL, now=1000.0)
        with self.assertRaises(Exception):
            report.generated_at = 999


if __name__ == "__main__":
    unittest.main()
