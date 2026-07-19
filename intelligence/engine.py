"""Engine do Sermon Intelligence.

Ponto de entrada público do módulo. Coordena todas as estratégias,
combina sinais e produz uma recomendação de ordenação.

Responsabilidade:
  - Receber IntelligenceRequest.
  - Delegar para IntelligenceCoordinator.
  - Ordenar scores por final_score.
  - Produzir IntelligenceRecommendation.

Nunca executa busca, nunca calcula embeddings, nunca interpreta áudio,
nunca consulta Holyrics, nunca modifica Feedback/Context/Evaluation/Ranking.

Design:
  - SermonIntelligenceEngine é stateless.
  - Usa IntelligenceCoordinator e IntelligencePolicy.
  - Não conhece implementação interna de nenhum módulo.
  - Interage apenas através de interfaces públicas (duck-typing).
"""

from __future__ import annotations

from intelligence.coordinator import IntelligenceCoordinator
from intelligence.dtos import (
    ConfidenceLevel,
    IntelligenceRecommendation,
    IntelligenceRequest,
    IntelligenceScore,
)
from intelligence.policy import IntelligencePolicy


class SermonIntelligenceEngine:
    """Engine que produz recomendações de ordenação.

    Uso:
        engine = SermonIntelligenceEngine()
        recommendation = engine.recommend(request)
        print(recommendation.explain())

    Desacoplamento:
        - Não conhece Searcher, Ranking, Feedback, Evaluation, Context,
          Holyrics, Parser, LLM, Embeddings, KnowledgeBase.
        - Apenas recebe IntelligenceRequest e produz IntelligenceRecommendation.
    """

    def __init__(
        self,
        policy: IntelligencePolicy | None = None,
        coordinator: IntelligenceCoordinator | None = None,
    ) -> None:
        self._policy = policy or IntelligencePolicy()
        self._coordinator = coordinator or IntelligenceCoordinator(self._policy)

    @property
    def policy(self) -> IntelligencePolicy:
        return self._policy

    @property
    def coordinator(self) -> IntelligenceCoordinator:
        return self._coordinator

    # ------------------------------------------------------------------
    # Recomendação
    # ------------------------------------------------------------------

    def recommend(
        self, request: IntelligenceRequest
    ) -> IntelligenceRecommendation:
        """Produz recomendação de ordenação para a requisição.

        Args:
            request: IntelligenceRequest com query, contexto, candidatos,
                feedback e estatísticas.

        Returns:
            IntelligenceRecommendation com scores ordenados e explicação.
        """
        # Coletar scores de todos os candidatos
        scores = self._coordinator.coordinate(request)

        if not scores:
            return IntelligenceRecommendation(
                query=request.query,
                scores=(),
                best_candidate_id="",
                confidence_level=ConfidenceLevel.LOW,
                explanation=f"Consulta '{request.query}': sem candidatos.",
                has_candidates=False,
            )

        # Ordenar por final_score decrescente
        sorted_scores = tuple(sorted(scores, key=lambda s: s.final_score, reverse=True))

        # Melhor candidato
        best = sorted_scores[0]

        # Confiança da recomendação = confiança do melhor candidato
        confidence = best.confidence_level

        # Explicação
        explanation = self._build_explanation(request, sorted_scores, confidence)

        return IntelligenceRecommendation(
            query=request.query,
            scores=sorted_scores,
            best_candidate_id=best.candidate_id,
            confidence_level=confidence,
            explanation=explanation,
            has_candidates=True,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_explanation(
        self,
        request: IntelligenceRequest,
        scores: tuple[IntelligenceScore, ...],
        confidence: ConfidenceLevel,
    ) -> str:
        """Constrói explicação textual da recomendação."""
        lines = [
            f"Consulta '{request.query}': "
            f"recomendação ({confidence.value})"
        ]
        for s in scores:
            lines.append(f"  {s.explain()}")
        return "\n".join(lines)


__all__ = ["SermonIntelligenceEngine"]
