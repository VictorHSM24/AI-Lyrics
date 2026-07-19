"""Detector de regressões para Continuous Evaluation.

Responsabilidade única:
  - Comparar métricas anteriores com atuais.
  - Detectar regressões (queda de precisão, aumento de tempo, etc.).
  - Retornar RegressionAlerts.

Não toma decisões automáticas. Apenas registra.

Design:
  - RegressionDetector é stateless.
  - Usa EvaluationPolicy para thresholds.
  - detect() retorna tuple de RegressionAlert.
"""

from __future__ import annotations

from evaluation.dtos import EvaluationMetrics, RegressionAlert
from evaluation.policy import EvaluationPolicy


class RegressionDetector:
    """Detector de regressões em métricas de avaliação.

    Uso:
        detector = RegressionDetector()
        alerts = detector.detect(previous_metrics, current_metrics, now)
    """

    def __init__(self, policy: EvaluationPolicy | None = None) -> None:
        self._policy = policy or EvaluationPolicy()

    @property
    def policy(self) -> EvaluationPolicy:
        return self._policy

    # ------------------------------------------------------------------
    # Detecção
    # ------------------------------------------------------------------

    def detect(
        self,
        previous: EvaluationMetrics,
        current: EvaluationMetrics,
        now: float,
    ) -> tuple[RegressionAlert, ...]:
        """Detecta regressões comparando métricas anteriores e atuais.

        Args:
            previous: métricas do período anterior.
            current: métricas do período atual.
            now: timestamp da detecção.

        Returns:
            Tuple de RegressionAlert (vazia se nenhuma regressão).
        """
        alerts: list[RegressionAlert] = []

        # 1. Queda de precisão
        alert = self._check_precision_drop(previous, current, now)
        if alert is not None:
            alerts.append(alert)

        # 2. Aumento de tempo médio
        alert = self._check_duration_increase(previous, current, now)
        if alert is not None:
            alerts.append(alert)

        # 3. Aumento de correções manuais
        alert = self._check_corrections_increase(previous, current, now)
        if alert is not None:
            alerts.append(alert)

        # 4. Aumento de buscas sem resultado
        alert = self._check_no_result_increase(previous, current, now)
        if alert is not None:
            alerts.append(alert)

        return tuple(alerts)

    # ------------------------------------------------------------------
    # Checks individuais
    # ------------------------------------------------------------------

    def _check_precision_drop(
        self, previous: EvaluationMetrics, current: EvaluationMetrics, now: float
    ) -> RegressionAlert | None:
        """Verifica queda de precisão (em pontos percentuais)."""
        if previous.precision == 0:
            return None
        drop_pp = (previous.precision - current.precision) * 100
        if drop_pp >= self._policy.regression_precision_drop:
            severity = self._policy.severity_for_drop(drop_pp)
            return RegressionAlert(
                metric_name="precision",
                description=(
                    f"Precisão caiu {drop_pp:.1f} p.p. "
                    f"({previous.precision * 100:.1f}% → "
                    f"{current.precision * 100:.1f}%)"
                ),
                previous_value=previous.precision,
                current_value=current.precision,
                threshold=self._policy.regression_precision_drop,
                detected_at=now,
                severity=severity,
            )
        return None

    def _check_duration_increase(
        self, previous: EvaluationMetrics, current: EvaluationMetrics, now: float
    ) -> RegressionAlert | None:
        """Verifica aumento de tempo médio (em %)."""
        if previous.avg_duration_ms == 0:
            return None
        increase_pct = (
            (current.avg_duration_ms - previous.avg_duration_ms)
            / previous.avg_duration_ms * 100
        )
        if increase_pct >= self._policy.regression_duration_increase:
            return RegressionAlert(
                metric_name="avg_duration_ms",
                description=(
                    f"Tempo médio aumentou {increase_pct:.1f}% "
                    f"({previous.avg_duration_ms:.0f} ms → "
                    f"{current.avg_duration_ms:.0f} ms)"
                ),
                previous_value=previous.avg_duration_ms,
                current_value=current.avg_duration_ms,
                threshold=self._policy.regression_duration_increase,
                detected_at=now,
                severity="medium",
            )
        return None

    def _check_corrections_increase(
        self, previous: EvaluationMetrics, current: EvaluationMetrics, now: float
    ) -> RegressionAlert | None:
        """Verifica aumento de correções manuais (em %)."""
        if previous.total_manual_corrections == 0:
            return None
        increase_pct = (
            (current.total_manual_corrections
             - previous.total_manual_corrections)
            / previous.total_manual_corrections * 100
        )
        if increase_pct >= self._policy.regression_corrections_increase:
            return RegressionAlert(
                metric_name="total_manual_corrections",
                description=(
                    f"Correções manuais aumentaram {increase_pct:.1f}% "
                    f"({previous.total_manual_corrections} → "
                    f"{current.total_manual_corrections})"
                ),
                previous_value=float(previous.total_manual_corrections),
                current_value=float(current.total_manual_corrections),
                threshold=self._policy.regression_corrections_increase,
                detected_at=now,
                severity="medium",
            )
        return None

    def _check_no_result_increase(
        self, previous: EvaluationMetrics, current: EvaluationMetrics, now: float
    ) -> RegressionAlert | None:
        """Verifica aumento de buscas sem resultado (em %)."""
        if previous.total_no_result == 0:
            return None
        increase_pct = (
            (current.total_no_result - previous.total_no_result)
            / previous.total_no_result * 100
        )
        if increase_pct >= self._policy.regression_no_result_increase:
            return RegressionAlert(
                metric_name="total_no_result",
                description=(
                    f"Buscas sem resultado aumentaram {increase_pct:.1f}% "
                    f"({previous.total_no_result} → "
                    f"{current.total_no_result})"
                ),
                previous_value=float(previous.total_no_result),
                current_value=float(current.total_no_result),
                threshold=self._policy.regression_no_result_increase,
                detected_at=now,
                severity="low",
            )
        return None


__all__ = ["RegressionDetector"]
