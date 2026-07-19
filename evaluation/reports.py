"""Gerador de relatórios para Continuous Evaluation.

Responsabilidade única:
  - Receber registros (ou métricas calculadas).
  - Gerar EvaluationReport / EvaluationSummary.
  - Formatar relatórios legíveis.

Não conhece Engine, Repository, Searcher, etc.
Apenas recebe dados e produz relatórios.

Design:
  - ReportGenerator é stateless.
  - Usa MetricsCalculator e EvaluationPolicy.
  - generate() retorna EvaluationReport completo.
"""

from __future__ import annotations

from evaluation.dtos import (
    EvaluationReport,
    EvaluationSummary,
    TemporalWindow,
)
from evaluation.metrics import MetricsCalculator
from evaluation.policy import EvaluationPolicy
from evaluation.regressions import RegressionDetector


class ReportGenerator:
    """Gerador de relatórios de avaliação.

    Uso:
        gen = ReportGenerator()
        report = gen.generate(records, window=TemporalWindow.ALL, now=...)
        print(report.to_text())
    """

    def __init__(
        self,
        calculator: MetricsCalculator | None = None,
        policy: EvaluationPolicy | None = None,
        regression_detector: RegressionDetector | None = None,
    ) -> None:
        self._policy = policy or EvaluationPolicy()
        self._calc = calculator or MetricsCalculator(self._policy)
        self._regression = regression_detector or RegressionDetector(self._policy)

    @property
    def policy(self) -> EvaluationPolicy:
        return self._policy

    @property
    def calculator(self) -> MetricsCalculator:
        return self._calc

    # ------------------------------------------------------------------
    # Geração de relatórios
    # ------------------------------------------------------------------

    def generate(
        self,
        records: tuple,
        window: TemporalWindow = TemporalWindow.ALL,
        now: float = 0.0,
        previous_metrics=None,
    ) -> EvaluationReport:
        """Gera relatório completo de avaliação.

        Args:
            records: tuple de EvaluationRecord.
            window: janela temporal do relatório.
            now: timestamp atual (para fatias temporais).
            previous_metrics: métricas anteriores (para detectar regressões).
                Se None, não detecta regressões.

        Returns:
            EvaluationReport completo.
        """
        # Filtrar registros pela janela
        seconds = self._policy.window_seconds(window)
        if seconds == float("inf"):
            filtered = records
        else:
            start = now - seconds
            filtered = tuple(r for r in records if r.timestamp >= start)

        # Calcular métricas agregadas
        metrics = self._calc.calculate(filtered)

        # Calcular listas para resumo
        hardest = self._calc.hardest_queries(filtered)
        top_cands = self._calc.top_candidates(filtered)
        worst_books_raw = self._calc.precision_by_book(filtered)
        worst_books = tuple(
            (b, p) for b, p, _ in worst_books_raw
        )

        summary = EvaluationSummary(
            total_records=len(filtered),
            metrics=metrics,
            hardest_queries=hardest,
            top_candidates=top_cands,
            worst_books=worst_books,
            worst_themes=(),  # reservado para futuro
        )

        # Fatias temporais
        slices = self._calc.all_temporal_slices(records, now) if now > 0 else ()

        # Regressões
        regressions = ()
        if previous_metrics is not None:
            regressions = self._regression.detect(
                previous_metrics, metrics, now
            )

        return EvaluationReport(
            generated_at=now if now > 0 else max(
                (r.timestamp for r in records), default=0.0
            ),
            window=window,
            summary=summary,
            temporal_slices=slices,
            regressions=regressions,
        )

    def generate_summary(
        self, records: tuple
    ) -> EvaluationSummary:
        """Gera apenas o resumo (sem fatias temporais ou regressões).

        Args:
            records: tuple de EvaluationRecord.

        Returns:
            EvaluationSummary.
        """
        metrics = self._calc.calculate(records)
        hardest = self._calc.hardest_queries(records)
        top_cands = self._calc.top_candidates(records)
        worst_books_raw = self._calc.precision_by_book(records)
        worst_books = tuple((b, p) for b, p, _ in worst_books_raw)

        return EvaluationSummary(
            total_records=len(records),
            metrics=metrics,
            hardest_queries=hardest,
            top_candidates=top_cands,
            worst_books=worst_books,
            worst_themes=(),
        )

    def to_text(self, report: EvaluationReport) -> str:
        """Converte relatório para texto legível.

        Args:
            report: EvaluationReport.

        Returns:
            String formatada.
        """
        return report.to_text()


__all__ = ["ReportGenerator"]
