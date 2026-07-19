"""Política do Sermon Intelligence.

Centraliza todos os pesos, limites e thresholds em um único lugar.
Nenhum número mágico espalhado pelo código.

Design:
  - IntelligencePolicy é stateless.
  - Todos os parâmetros são constantes nomeadas.
  - Parâmetros podem ser ajustados sem quebrar compatibilidade.

Parâmetros:
  - Pesos de cada sinal (context, feedback, continuity, etc.).
  - Limite máximo de ajuste (Intelligence nunca vence sozinho).
  - Thresholds de confiança (LOW, MEDIUM, HIGH).
  - Bônus por correspondência de contexto, livro, tema, etc.
"""

from __future__ import annotations

from intelligence.dtos import ConfidenceLevel


# ---------------------------------------------------------------------------
# Pesos dos sinais (importância relativa)
# ---------------------------------------------------------------------------

# Cada peso é multiplicado pelo value do sinal para produzir a contribuição.
# Pesos são normalizados pelo SignalCombiner (soma → 1.0).
_WEIGHT_CONTEXT: float = 0.20
_WEIGHT_FEEDBACK: float = 0.25
_WEIGHT_CONTINUITY: float = 0.15
_WEIGHT_REFERENCE: float = 0.10
_WEIGHT_THEME: float = 0.10
_WEIGHT_BOOK: float = 0.10
_WEIGHT_CONFIDENCE: float = 0.05
_WEIGHT_EVALUATION: float = 0.05


# ---------------------------------------------------------------------------
# Limites de ajuste
# ---------------------------------------------------------------------------

# Limite máximo absoluto do ajuste do Intelligence (sobre o base_score).
# O Intelligence nunca deve vencer sozinho o Ranking — apenas ajustar.
_MAX_INTELLIGENCE_ADJUSTMENT: float = 0.20

# Limite mínimo (penalização máxima).
_MIN_INTELLIGENCE_ADJUSTMENT: float = -0.10


# ---------------------------------------------------------------------------
# Bônus por correspondência
# ---------------------------------------------------------------------------

# Bônus quando o candidato é do livro ativo.
_CONTEXT_BOOK_MATCH_BONUS: float = 0.10

# Bônus quando o candidato é do capítulo ativo (mais específico).
_CONTEXT_CHAPTER_MATCH_BONUS: float = 0.15

# Bônus quando o candidato é do livro recentemente mencionado.
_BOOK_RECENT_MATCH_BONUS: float = 0.08

# Bônus quando o candidato continua a sequência de referências.
_CONTINUITY_MATCH_BONUS: float = 0.12

# Bônus quando o candidato é a última referência resolvida (repetição).
_REFERENCE_REPEAT_BONUS: float = 0.05

# Bônus quando o candidato corresponde a um tema recente.
_THEME_MATCH_BONUS: float = 0.08

# Bônus de feedback (proporcional ao peso de feedback).
_FEEDBACK_STRONG_BONUS: float = 0.12
_FEEDBACK_WEAK_BONUS: float = 0.06


# ---------------------------------------------------------------------------
# Thresholds de confiança
# ---------------------------------------------------------------------------

# Número mínimo de sinais ativos para confiança MEDIUM.
_MIN_SIGNALS_FOR_MEDIUM: int = 3

# Número mínimo de sinais ativos para confiança HIGH.
_MIN_SIGNALS_FOR_HIGH: int = 5

# Score mínimo (final) para confiança HIGH.
_MIN_SCORE_FOR_HIGH: float = 0.85

# Score mínimo (final) para confiança MEDIUM.
_MIN_SCORE_FOR_MEDIUM: float = 0.60


# ---------------------------------------------------------------------------
# Thresholds de avaliação estatística
# ---------------------------------------------------------------------------

# Precisão mínima para que EvaluationSignal contribua positivamente.
_EVAL_PRECISION_THRESHOLD: float = 0.70

# Número mínimo de buscas para confiança estatística.
_EVAL_MIN_SEARCHES: int = 10


# ---------------------------------------------------------------------------
# IntelligencePolicy
# ---------------------------------------------------------------------------


class IntelligencePolicy:
    """Política do Intelligence — pesos, limites, thresholds.

    Stateless — pode ser instanciada uma vez e reutilizada.
    Todos os parâmetros são acessíveis via properties.

    Uso:
        policy = IntelligencePolicy()
        weight = policy.weight_context
        max_adj = policy.max_intelligence_adjustment
    """

    # ------------------------------------------------------------------
    # Pesos
    # ------------------------------------------------------------------

    @property
    def weight_context(self) -> float:
        return _WEIGHT_CONTEXT

    @property
    def weight_feedback(self) -> float:
        return _WEIGHT_FEEDBACK

    @property
    def weight_continuity(self) -> float:
        return _WEIGHT_CONTINUITY

    @property
    def weight_reference(self) -> float:
        return _WEIGHT_REFERENCE

    @property
    def weight_theme(self) -> float:
        return _WEIGHT_THEME

    @property
    def weight_book(self) -> float:
        return _WEIGHT_BOOK

    @property
    def weight_confidence(self) -> float:
        return _WEIGHT_CONFIDENCE

    @property
    def weight_evaluation(self) -> float:
        return _WEIGHT_EVALUATION

    @property
    def total_weight(self) -> float:
        """Soma de todos os pesos."""
        return (
            _WEIGHT_CONTEXT + _WEIGHT_FEEDBACK + _WEIGHT_CONTINUITY
            + _WEIGHT_REFERENCE + _WEIGHT_THEME + _WEIGHT_BOOK
            + _WEIGHT_CONFIDENCE + _WEIGHT_EVALUATION
        )

    # ------------------------------------------------------------------
    # Limites
    # ------------------------------------------------------------------

    @property
    def max_intelligence_adjustment(self) -> float:
        return _MAX_INTELLIGENCE_ADJUSTMENT

    @property
    def min_intelligence_adjustment(self) -> float:
        return _MIN_INTELLIGENCE_ADJUSTMENT

    # ------------------------------------------------------------------
    # Bônus
    # ------------------------------------------------------------------

    @property
    def context_book_match_bonus(self) -> float:
        return _CONTEXT_BOOK_MATCH_BONUS

    @property
    def context_chapter_match_bonus(self) -> float:
        return _CONTEXT_CHAPTER_MATCH_BONUS

    @property
    def book_recent_match_bonus(self) -> float:
        return _BOOK_RECENT_MATCH_BONUS

    @property
    def continuity_match_bonus(self) -> float:
        return _CONTINUITY_MATCH_BONUS

    @property
    def reference_repeat_bonus(self) -> float:
        return _REFERENCE_REPEAT_BONUS

    @property
    def theme_match_bonus(self) -> float:
        return _THEME_MATCH_BONUS

    @property
    def feedback_strong_bonus(self) -> float:
        return _FEEDBACK_STRONG_BONUS

    @property
    def feedback_weak_bonus(self) -> float:
        return _FEEDBACK_WEAK_BONUS

    # ------------------------------------------------------------------
    # Confiança
    # ------------------------------------------------------------------

    @property
    def min_signals_for_medium(self) -> int:
        return _MIN_SIGNALS_FOR_MEDIUM

    @property
    def min_signals_for_high(self) -> int:
        return _MIN_SIGNALS_FOR_HIGH

    @property
    def min_score_for_high(self) -> float:
        return _MIN_SCORE_FOR_HIGH

    @property
    def min_score_for_medium(self) -> float:
        return _MIN_SCORE_FOR_MEDIUM

    # ------------------------------------------------------------------
    # Avaliação
    # ------------------------------------------------------------------

    @property
    def eval_precision_threshold(self) -> float:
        return _EVAL_PRECISION_THRESHOLD

    @property
    def eval_min_searches(self) -> int:
        return _EVAL_MIN_SEARCHES

    # ------------------------------------------------------------------
    # Métodos utilitários
    # ------------------------------------------------------------------

    def cap_adjustment(self, adjustment: float) -> float:
        """Limita o ajuste ao intervalo [min, max].

        Args:
            adjustment: ajuste calculado.

        Returns:
            Ajuste limitado.
        """
        return max(_MIN_INTELLIGENCE_ADJUSTMENT,
                   min(_MAX_INTELLIGENCE_ADJUSTMENT, adjustment))

    def confidence_from_signals_and_score(
        self, active_signal_count: int, final_score: float
    ) -> ConfidenceLevel:
        """Determina nível de confiança a partir de sinais e score.

        A confiança nunca é binária — combina número de sinais ativos
        e score final.

        Args:
            active_signal_count: número de sinais com contribuição != 0.
            final_score: score final do candidato.

        Returns:
            ConfidenceLevel (LOW, MEDIUM, HIGH).
        """
        if (active_signal_count >= _MIN_SIGNALS_FOR_HIGH
                and final_score >= _MIN_SCORE_FOR_HIGH):
            return ConfidenceLevel.HIGH
        if (active_signal_count >= _MIN_SIGNALS_FOR_MEDIUM
                and final_score >= _MIN_SCORE_FOR_MEDIUM):
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW

    def all_weights(self) -> dict[str, float]:
        """Retorna dict com todos os pesos por nome."""
        return {
            "context": _WEIGHT_CONTEXT,
            "feedback": _WEIGHT_FEEDBACK,
            "continuity": _WEIGHT_CONTINUITY,
            "reference": _WEIGHT_REFERENCE,
            "theme": _WEIGHT_THEME,
            "book": _WEIGHT_BOOK,
            "confidence": _WEIGHT_CONFIDENCE,
            "evaluation": _WEIGHT_EVALUATION,
        }


__all__ = ["IntelligencePolicy"]
