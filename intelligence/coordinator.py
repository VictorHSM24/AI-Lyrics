"""Coordenador do Sermon Intelligence.

Responsabilidade única:
  - Coletar sinais de todas as estratégias.
  - Combinar sinais via SignalCombiner.
  - Produzir IntelligenceScore para cada candidato.

Nunca executa lógica de negócio — apenas orquestra.

Design:
  - IntelligenceCoordinator é stateless.
  - Usa estratégias, SignalCombiner e IntelligencePolicy.
  - Não conhece implementação interna de nenhum módulo.
"""

from __future__ import annotations

from intelligence.combiner import SignalCombiner
from intelligence.dtos import (
    CandidateInfo,
    IntelligenceRequest,
    IntelligenceScore,
    IntelligenceSignal,
)
from intelligence.policy import IntelligencePolicy
from intelligence.strategies import (
    BookStrategy,
    ConfidenceStrategy,
    ContextStrategy,
    ContinuityStrategy,
    EvaluationStrategy,
    FeedbackStrategy,
    ReferenceStrategy,
    ThemeStrategy,
    all_strategies,
)


class IntelligenceCoordinator:
    """Coordenador que orquestra sinais e produz IntelligenceScores.

    Uso:
        coordinator = IntelligenceCoordinator(policy)
        scores = coordinator.coordinate(request)
    """

    def __init__(
        self,
        policy: IntelligencePolicy | None = None,
        combiner: SignalCombiner | None = None,
        strategies: tuple | None = None,
    ) -> None:
        self._policy = policy or IntelligencePolicy()
        self._combiner = combiner or SignalCombiner(self._policy)
        # Estratégias que não dependem de outros sinais
        self._strategies = strategies if strategies is not None else all_strategies()
        # ConfidenceStrategy é especial — depende dos outros sinais
        self._confidence_strategy = ConfidenceStrategy()

    @property
    def policy(self) -> IntelligencePolicy:
        return self._policy

    @property
    def combiner(self) -> SignalCombiner:
        return self._combiner

    # ------------------------------------------------------------------
    # Coordenação
    # ------------------------------------------------------------------

    def coordinate(
        self, request: IntelligenceRequest
    ) -> tuple[IntelligenceScore, ...]:
        """Coordena sinais para todos os candidatos da requisição.

        Args:
            request: IntelligenceRequest com candidatos.

        Returns:
            Tuple de IntelligenceScore (um por candidato, na ordem original).
        """
        if not request.candidates:
            return ()

        scores = []
        for candidate in request.candidates:
            score = self._coordinate_candidate(candidate, request)
            scores.append(score)
        return tuple(scores)

    # ------------------------------------------------------------------
    # Coordenação individual
    # ------------------------------------------------------------------

    def _coordinate_candidate(
        self, candidate: CandidateInfo, request: IntelligenceRequest
    ) -> IntelligenceScore:
        """Coordena sinais para um único candidato."""
        # 1. Coletar sinais das estratégias independentes
        signals: list[IntelligenceSignal] = []
        for strategy in self._strategies:
            signal = strategy.evaluate(candidate, request, self._policy)
            signals.append(signal)

        # 2. Calcular sinal de confiança (depende dos outros sinais)
        confidence_signal = self._confidence_strategy.evaluate(
            candidate, request, self._policy,
            other_signals=tuple(signals),
        )
        signals.append(confidence_signal)

        # 3. Combinar sinais em IntelligenceScore
        return self._combiner.combine(candidate, tuple(signals))


__all__ = ["IntelligenceCoordinator"]
