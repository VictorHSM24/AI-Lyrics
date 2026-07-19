"""Combinador de sinais do Sermon Intelligence.

Responsabilidade única:
  - Receber uma lista de IntelligenceSignal.
  - Combinar em um IntelligenceScore.
  - Aplicar limites (cap).
  - Calcular nível de confiança.

Nenhuma outra responsabilidade. Não conhece estratégias, engine, etc.

Design:
  - SignalCombiner é stateless.
  - Usa IntelligencePolicy para pesos e limites.
  - Combina sinais por soma ponderada de contribuições.
"""

from __future__ import annotations

from intelligence.dtos import (
    CandidateInfo,
    ConfidenceLevel,
    IntelligenceScore,
    IntelligenceSignal,
)
from intelligence.policy import IntelligencePolicy


class SignalCombiner:
    """Combinador de sinais em IntelligenceScore.

    Uso:
        combiner = SignalCombiner(policy)
        score = combiner.combine(candidate, base_score, signals)
    """

    def __init__(self, policy: IntelligencePolicy | None = None) -> None:
        self._policy = policy or IntelligencePolicy()

    @property
    def policy(self) -> IntelligencePolicy:
        return self._policy

    # ------------------------------------------------------------------
    # Combinação
    # ------------------------------------------------------------------

    def combine(
        self,
        candidate: CandidateInfo,
        signals: tuple[IntelligenceSignal, ...],
    ) -> IntelligenceScore:
        """Combina sinais em um IntelligenceScore.

        Args:
            candidate: CandidateInfo do candidato.
            signals: tuple de IntelligenceSignal.

        Returns:
            IntelligenceScore com score final e decomposição.
        """
        # Mapear sinais por tipo
        signal_map: dict[str, IntelligenceSignal] = {}
        for s in signals:
            signal_map[s.signal_type] = s

        # Calcular contribuições individuais
        context_contrib = self._contribution(signal_map, "context")
        feedback_contrib = self._contribution(signal_map, "feedback")
        continuity_contrib = self._contribution(signal_map, "continuity")
        reference_contrib = self._contribution(signal_map, "reference")
        theme_contrib = self._contribution(signal_map, "theme")
        book_contrib = self._contribution(signal_map, "book")
        confidence_contrib = self._contribution(signal_map, "confidence")
        evaluation_contrib = self._contribution(signal_map, "evaluation")

        # Soma de todas as contribuições
        total_adjustment = (
            context_contrib + feedback_contrib + continuity_contrib
            + reference_contrib + theme_contrib + book_contrib
            + confidence_contrib + evaluation_contrib
        )

        # Aplicar cap
        capped_adjustment = self._policy.cap_adjustment(total_adjustment)

        # Score final
        final_score = candidate.base_score + capped_adjustment
        final_score = max(0.0, min(1.0, final_score))

        # Contar sinais ativos (contribuição != 0)
        active_count = sum(
            1 for s in signals
            if s.value != 0.0
        )

        # Nível de confiança
        confidence = self._policy.confidence_from_signals_and_score(
            active_count, final_score
        )

        # Explicação
        explanation = self._build_explanation(
            candidate, final_score, confidence,
            context_contrib, feedback_contrib, continuity_contrib,
            reference_contrib, theme_contrib, book_contrib,
            confidence_contrib, evaluation_contrib,
        )

        return IntelligenceScore(
            candidate_id=candidate.candidate_id,
            base_score=candidate.base_score,
            final_score=final_score,
            context_contribution=context_contrib,
            feedback_contribution=feedback_contrib,
            continuity_contribution=continuity_contrib,
            reference_contribution=reference_contrib,
            theme_contribution=theme_contrib,
            book_contribution=book_contrib,
            confidence_contribution=confidence_contrib,
            evaluation_contribution=evaluation_contrib,
            confidence_level=confidence,
            signals=signals,
            explanation=explanation,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _contribution(
        self, signal_map: dict[str, IntelligenceSignal], signal_type: str
    ) -> float:
        """Extrai a contribuição de um sinal (value * weight)."""
        signal = signal_map.get(signal_type)
        if signal is None:
            return 0.0
        return signal.contribution

    def _build_explanation(
        self, candidate: CandidateInfo, final_score: float,
        confidence: ConfidenceLevel,
        context: float, feedback: float, continuity: float,
        reference: float, theme: float, book: float,
        confidence_val: float, evaluation: float,
    ) -> str:
        """Constrói explicação textual do score."""
        parts = [f"+{candidate.base_score:.2f} Base"]
        if context != 0:
            parts.append(f"{context:+.2f} Contexto")
        if feedback != 0:
            parts.append(f"{feedback:+.2f} Feedback")
        if continuity != 0:
            parts.append(f"{continuity:+.2f} Continuidade")
        if reference != 0:
            parts.append(f"{reference:+.2f} Referência")
        if theme != 0:
            parts.append(f"{theme:+.2f} Tema")
        if book != 0:
            parts.append(f"{book:+.2f} Livro")
        if confidence_val != 0:
            parts.append(f"{confidence_val:+.2f} Confiança")
        if evaluation != 0:
            parts.append(f"{evaluation:+.2f} Estatística")
        parts.append(f"→ {final_score:.2f}")
        parts.append(f"({confidence.value})")
        return ", ".join(parts)


__all__ = ["SignalCombiner"]
