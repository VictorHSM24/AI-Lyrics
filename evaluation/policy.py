"""Política de avaliação do Continuous Evaluation.

Centraliza todos os thresholds, classificações e parâmetros em um único
lugar. Nenhum número mágico espalhado pelo código.

Design:
  - EvaluationPolicy é stateless.
  - Todos os parâmetros são constantes nomeadas.
  - Parâmetros podem ser ajustados sem quebrar compatibilidade.

Parâmetros:
  - Limite mínimo de registros para calcular precisão confiável.
  - Thresholds de regressão (queda de precisão, aumento de tempo, etc.).
  - Tamanho máximo de listas em relatórios (top-N).
  - Janelas temporais suportadas.
"""

from __future__ import annotations

from evaluation.dtos import QueryClassification, TemporalWindow


# ---------------------------------------------------------------------------
# Parâmetros de confiança estatística
# ---------------------------------------------------------------------------

# Número mínimo de registros para considerar uma métrica confiável.
# Abaixo disso, a métrica é reportada mas marcada como "baixa confiança".
_MIN_RECORDS_FOR_CONFIDENCE: int = 10

# Número mínimo de buscas por livro para calcular precisão por livro.
_MIN_SEARCHES_PER_BOOK: int = 5


# ---------------------------------------------------------------------------
# Thresholds de regressão
# ---------------------------------------------------------------------------

# Queda de precisão (em pontos percentuais) para alerta de regressão.
_REGRESSION_PRECISION_DROP: float = 5.0  # 5 p.p.

# Aumento de tempo médio (em %) para alerta de regressão.
_REGRESSION_DURATION_INCREASE: float = 50.0  # 50%

# Aumento de correções manuais (em %) para alerta de regressão.
_REGRESSION_CORRECTIONS_INCREASE: float = 30.0  # 30%

# Aumento de buscas sem resultado (em %) para alerta de regressão.
_REGRESSION_NO_RESULT_INCREASE: float = 50.0  # 50%


# ---------------------------------------------------------------------------
# Limites de relatórios
# ---------------------------------------------------------------------------

# Número máximo de itens em listas de relatórios (top-N).
_TOP_QUERIES_LIMIT: int = 10
_TOP_CANDIDATES_LIMIT: int = 10
_WORST_BOOKS_LIMIT: int = 10
_WORST_THEMES_LIMIT: int = 10


# ---------------------------------------------------------------------------
# Janelas temporais suportadas
# ---------------------------------------------------------------------------

# Duração de cada janela temporal em segundos.
_TEMPORAL_WINDOW_SECONDS: dict[TemporalWindow, float] = {
    TemporalWindow.LAST_24H: 86400.0,      # 24 * 60 * 60
    TemporalWindow.LAST_7D: 604800.0,      # 7 * 24 * 60 * 60
    TemporalWindow.LAST_30D: 2592000.0,    # 30 * 24 * 60 * 60
    TemporalWindow.ALL: float("inf"),
}


# ---------------------------------------------------------------------------
# Severidade de regressões
# ---------------------------------------------------------------------------

# Thresholds de severidade (queda absoluta de precisão em p.p.).
_SEVERITY_LOW_THRESHOLD: float = 5.0
_SEVERITY_MEDIUM_THRESHOLD: float = 10.0
_SEVERITY_HIGH_THRESHOLD: float = 20.0


# ---------------------------------------------------------------------------
# EvaluationPolicy
# ---------------------------------------------------------------------------


class EvaluationPolicy:
    """Política de avaliação — thresholds, classificações, limites.

    Stateless — pode ser instanciada uma vez e reutilizada.
    Todos os parâmetros são acessíveis via properties para permitir
    ajuste futuro sem quebrar compatibilidade.

    Uso:
        policy = EvaluationPolicy()
        if policy.is_confident(record_count):
            precision = metrics.precision
    """

    @property
    def min_records_for_confidence(self) -> int:
        return _MIN_RECORDS_FOR_CONFIDENCE

    @property
    def min_searches_per_book(self) -> int:
        return _MIN_SEARCHES_PER_BOOK

    @property
    def regression_precision_drop(self) -> float:
        return _REGRESSION_PRECISION_DROP

    @property
    def regression_duration_increase(self) -> float:
        return _REGRESSION_DURATION_INCREASE

    @property
    def regression_corrections_increase(self) -> float:
        return _REGRESSION_CORRECTIONS_INCREASE

    @property
    def regression_no_result_increase(self) -> float:
        return _REGRESSION_NO_RESULT_INCREASE

    @property
    def top_queries_limit(self) -> int:
        return _TOP_QUERIES_LIMIT

    @property
    def top_candidates_limit(self) -> int:
        return _TOP_CANDIDATES_LIMIT

    @property
    def worst_books_limit(self) -> int:
        return _WORST_BOOKS_LIMIT

    @property
    def worst_themes_limit(self) -> int:
        return _WORST_THEMES_LIMIT

    @property
    def severity_low_threshold(self) -> float:
        return _SEVERITY_LOW_THRESHOLD

    @property
    def severity_medium_threshold(self) -> float:
        return _SEVERITY_MEDIUM_THRESHOLD

    @property
    def severity_high_threshold(self) -> float:
        return _SEVERITY_HIGH_THRESHOLD

    # ------------------------------------------------------------------
    # Confiança estatística
    # ------------------------------------------------------------------

    def is_confident(self, record_count: int) -> bool:
        """Verifica se há registros suficientes para confiança estatística.

        Args:
            record_count: número de registros.

        Returns:
            True se há registros suficientes.
        """
        return record_count >= _MIN_RECORDS_FOR_CONFIDENCE

    def is_book_confident(self, search_count: int) -> bool:
        """Verifica se há buscas suficientes por livro.

        Args:
            search_count: número de buscas para o livro.

        Returns:
            True se há buscas suficientes.
        """
        return search_count >= _MIN_SEARCHES_PER_BOOK

    # ------------------------------------------------------------------
    # Janelas temporais
    # ------------------------------------------------------------------

    def window_seconds(self, window: TemporalWindow) -> float:
        """Retorna a duração em segundos de uma janela temporal.

        Args:
            window: janela temporal.

        Returns:
            Duração em segundos (ou inf para ALL).
        """
        return _TEMPORAL_WINDOW_SECONDS.get(window, float("inf"))

    def supported_windows(self) -> tuple[TemporalWindow, ...]:
        """Retorna todas as janelas temporais suportadas."""
        return tuple(_TEMPORAL_WINDOW_SECONDS.keys())

    # ------------------------------------------------------------------
    # Severidade
    # ------------------------------------------------------------------

    def severity_for_drop(self, drop_pp: float) -> str:
        """Determina severidade com base na queda de precisão (p.p.).

        Args:
            drop_pp: queda em pontos percentuais.

        Returns:
            "low", "medium", ou "high".
        """
        if drop_pp >= _SEVERITY_HIGH_THRESHOLD:
            return "high"
        if drop_pp >= _SEVERITY_MEDIUM_THRESHOLD:
            return "medium"
        return "low"

    # ------------------------------------------------------------------
    # Classificações
    # ------------------------------------------------------------------

    def all_classifications(self) -> tuple[QueryClassification, ...]:
        """Retorna todas as classificações de consulta suportadas."""
        return tuple(QueryClassification)

    def is_valid_classification(self, classification: QueryClassification) -> bool:
        """Verifica se uma classificação é válida."""
        return isinstance(classification, QueryClassification)


__all__ = ["EvaluationPolicy"]
