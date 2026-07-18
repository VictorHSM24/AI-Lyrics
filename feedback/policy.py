"""Política de pesos do Feedback Learning.

Centraliza todos os pesos e parâmetros do Feedback Learning em um único
lugar. Nenhum número mágico espalhado pelo código.

Design:
  - LearningPolicy é stateless.
  - Todos os pesos são constantes nomeadas.
  - Pesos podem ser ajustados sem quebrar compatibilidade.
  - weight_for(event) retorna o peso para um evento.

Pesos iniciais (calibrados para complementar o Ranking, não substituir):
  - CandidateAccepted:       +3  (preferência positiva moderada)
  - CandidateRejected:       -1  (preferência negativa leve)
  - ManualReferenceSelected: +5  (preferência positiva forte)
  - SuggestionIgnored:       -2  (preferência negativa moderada)
  - ManualSearch:             0  (neutro — apenas registra)

Limites:
  - max_feedback_bonus: teto absoluto do bônus de feedback no score.
      Garante que o feedback nunca pode vencer sozinho o Ranking.
  - min_base_score_for_feedback: score mínimo do candidato para que o
      feedback seja aplicado. Se a similaridade for muito baixa, o
      feedback não ajuda (feedback complementa, não substitui).
"""

from __future__ import annotations

from feedback.events import (
    CandidateAccepted,
    CandidateRejected,
    FeedbackEvent,
    ManualReferenceSelected,
    ManualSearch,
    SuggestionIgnored,
)


# ---------------------------------------------------------------------------
# Pesos por tipo de evento (centralizados)
# ---------------------------------------------------------------------------

_WEIGHT_CANDIDATE_ACCEPTED: float = 3.0
_WEIGHT_CANDIDATE_REJECTED: float = -1.0
_WEIGHT_MANUAL_REFERENCE_SELECTED: float = 5.0
_WEIGHT_SUGGESTION_IGNORED: float = -2.0
_WEIGHT_MANUAL_SEARCH: float = 0.0


# ---------------------------------------------------------------------------
# Limites de influência do feedback
# ---------------------------------------------------------------------------

# Teto absoluto do bônus de feedback no score final [0.0, 1.0].
# Garante que o feedback NUNCA pode vencer sozinho o Ranking.
# Ex.: se max_feedback_bonus = 0.15, o feedback pode adicionar no máximo
# 0.15 ao score, mesmo que o peso acumulado seja enorme.
_MAX_FEEDBACK_BONUS: float = 0.15

# Floor absoluto do bônus de feedback (penalização máxima).
# Garante que o feedback negativo não destrói completamente um candidato.
_MIN_FEEDBACK_BONUS: float = -0.10

# Score mínimo do candidato (similaridade) para que o feedback seja aplicado.
# Se a similaridade for muito baixa, o feedback não ajuda — o candidato
# não deve assumir a primeira posição apenas por preferência anterior.
_MIN_BASE_SCORE_FOR_FEEDBACK: float = 0.10


# ---------------------------------------------------------------------------
# Parâmetros de decaimento
# ---------------------------------------------------------------------------

# Fator de decaimento por uso sem reutilização.
# A cada N eventos sem reutilização, o peso acumulado é multiplicado por
# este fator. Ex.: 0.95 = perde 5% do peso a cada decaimento.
_DECAY_FACTOR: float = 0.95

# Intervalo de decaimento: a quantos eventos sem reutilização o decaimento
# é aplicado. Ex.: 10 = a cada 10 eventos sem reutilização, aplica o fator.
_DECAY_INTERVAL: int = 10

# Peso mínimo após decaimento (não decai para zero absoluto).
_MIN_DECAYED_WEIGHT: float = 0.01


# ---------------------------------------------------------------------------
# Conversão peso → bônus
# ---------------------------------------------------------------------------

# Fator de conversão de peso acumulado para bônus no score.
# O peso acumulado (ex.: +30 após várias aceitações) é convertido em bônus
# via uma função sigmoide limitada.
# Ex.: weight_to_bonus(30) ≈ 0.12 (próximo do teto).
_BONUS_SCALE: float = 10.0  # escala da sigmoide (quanto maior, mais suave)


# ---------------------------------------------------------------------------
# LearningPolicy
# ---------------------------------------------------------------------------


class LearningPolicy:
    """Política de pesos e parâmetros do Feedback Learning.

    Stateless — pode ser instanciada uma vez e reutilizada.
    Todos os pesos e limites são acessíveis via properties para permitir
    ajuste futuro sem quebrar compatibilidade.

    Uso:
        policy = LearningPolicy()
        weight = policy.weight_for(event)
        bonus = policy.weight_to_bonus(accumulated_weight)
        capped = policy.cap_bonus(bonus)
    """

    @property
    def weight_candidate_accepted(self) -> float:
        return _WEIGHT_CANDIDATE_ACCEPTED

    @property
    def weight_candidate_rejected(self) -> float:
        return _WEIGHT_CANDIDATE_REJECTED

    @property
    def weight_manual_reference_selected(self) -> float:
        return _WEIGHT_MANUAL_REFERENCE_SELECTED

    @property
    def weight_suggestion_ignored(self) -> float:
        return _WEIGHT_SUGGESTION_IGNORED

    @property
    def weight_manual_search(self) -> float:
        return _WEIGHT_MANUAL_SEARCH

    @property
    def max_feedback_bonus(self) -> float:
        """Teto absoluto do bônus de feedback."""
        return _MAX_FEEDBACK_BONUS

    @property
    def min_feedback_bonus(self) -> float:
        """Floor absoluto do bônus de feedback (penalização máx)."""
        return _MIN_FEEDBACK_BONUS

    @property
    def min_base_score_for_feedback(self) -> float:
        """Score mínimo do candidato para aplicar feedback."""
        return _MIN_BASE_SCORE_FOR_FEEDBACK

    @property
    def decay_factor(self) -> float:
        """Fator de decaimento por uso sem reutilização."""
        return _DECAY_FACTOR

    @property
    def decay_interval(self) -> int:
        """Intervalo de eventos para aplicar decaimento."""
        return _DECAY_INTERVAL

    @property
    def min_decayed_weight(self) -> float:
        """Peso mínimo após decaimento."""
        return _MIN_DECAYED_WEIGHT

    @property
    def bonus_scale(self) -> float:
        """Escala da sigmoide de conversão peso → bônus."""
        return _BONUS_SCALE

    # ------------------------------------------------------------------
    # Peso por evento
    # ------------------------------------------------------------------

    def weight_for(self, event: FeedbackEvent) -> float:
        """Retorna o peso para um evento.

        Args:
            event: evento tipado.

        Returns:
            Peso (positivo = preferência, negativo = aversão).
        """
        if isinstance(event, CandidateAccepted):
            return _WEIGHT_CANDIDATE_ACCEPTED
        if isinstance(event, CandidateRejected):
            return _WEIGHT_CANDIDATE_REJECTED
        if isinstance(event, ManualReferenceSelected):
            return _WEIGHT_MANUAL_REFERENCE_SELECTED
        if isinstance(event, SuggestionIgnored):
            return _WEIGHT_SUGGESTION_IGNORED
        if isinstance(event, ManualSearch):
            return _WEIGHT_MANUAL_SEARCH
        # Evento desconhecido — peso neutro
        return 0.0

    def event_type_name(self, event: FeedbackEvent) -> str:
        """Retorna o nome do tipo do evento (para estatísticas).

        Args:
            event: evento tipado.

        Returns:
            Nome do tipo: "accepted", "rejected", "manual_reference",
            "manual_search", "suggestion_ignored", ou "unknown".
        """
        if isinstance(event, CandidateAccepted):
            return "accepted"
        if isinstance(event, CandidateRejected):
            return "rejected"
        if isinstance(event, ManualReferenceSelected):
            return "manual_reference"
        if isinstance(event, ManualSearch):
            return "manual_search"
        if isinstance(event, SuggestionIgnored):
            return "suggestion_ignored"
        return "unknown"

    # ------------------------------------------------------------------
    # Conversão peso → bônus
    # ------------------------------------------------------------------

    def weight_to_bonus(self, accumulated_weight: float) -> float:
        """Converte peso acumulado em bônus de score.

        Usa uma função sigmoide para mapear o peso acumulado (que pode
        crescer indefinidamente) para um bônus no intervalo [-1, 1].
        O bônus é então limitado por cap_bonus().

        Fórmula: bonus = tanh(accumulated_weight / BONUS_SCALE)

        Args:
            accumulated_weight: peso acumulado (com decaimento aplicado).

        Returns:
            Bônus no intervalo [-1, 1] (antes do cap).
        """
        import math
        return math.tanh(accumulated_weight / _BONUS_SCALE)

    def cap_bonus(self, bonus: float) -> float:
        """Limita o bônus ao intervalo [min_feedback_bonus, max_feedback_bonus].

        Garante que o feedback nunca pode vencer sozinho o Ranking.

        Args:
            bonus: bônus calculado (antes do cap).

        Returns:
            Bônus limitado.
        """
        return max(_MIN_FEEDBACK_BONUS, min(_MAX_FEEDBACK_BONUS, bonus))

    def should_apply_feedback(self, base_score: float) -> bool:
        """Verifica se o feedback deve ser aplicado a um candidato.

        Se a similaridade (base_score) for muito baixa, o feedback não
        ajuda — o candidato não deve assumir a primeira posição apenas
        por preferência anterior.

        Args:
            base_score: score original do Ranking (similaridade).

        Returns:
            True se o feedback deve ser aplicado.
        """
        return base_score >= _MIN_BASE_SCORE_FOR_FEEDBACK

    # ------------------------------------------------------------------
    # Decaimento
    # ------------------------------------------------------------------

    def apply_decay(self, total_weight: float, decay_count: int) -> float:
        """Aplica decaimento ao peso acumulado.

        O decaimento é determinístico: a cada `decay_interval` contagens,
        o peso é multiplicado por `decay_factor`. Não decai abaixo de
        `min_decayed_weight`.

        Args:
            total_weight: peso acumulado atual.
            decay_count: contador de decaimento atual.

        Returns:
            Peso após decaimento.
        """
        if decay_count <= 0 or total_weight <= 0:
            return total_weight
        # Número de aplicações do fator de decaimento
        num_applications = decay_count // _DECAY_INTERVAL
        if num_applications <= 0:
            return total_weight
        # Aplicar fator de decaimento
        factor = _DECAY_FACTOR ** num_applications
        decayed = total_weight * factor
        # Não decai abaixo do mínimo
        return max(_MIN_DECAYED_WEIGHT, decayed)


__all__ = ["LearningPolicy"]
