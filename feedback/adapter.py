"""Adapter de integração entre Feedback Learning e Ranking.

Responsabilidade única:
  - Receber uma consulta (query, context, candidate_id, base_score).
  - Consultar FeedbackEngine/Repository.
  - Retornar um ajuste de score (feedback_bonus).
  - Garantir que o feedback nunca vence sozinho o Ranking.

Nenhuma outra responsabilidade. O Ranking pergunta:
  "Existe feedback para este candidato?"
O Adapter responde apenas um ajuste de score.

Design:
  - RankingFeedbackAdapter é stateless (consulta engine sob demanda).
  - Aplica LearningPolicy (cap, min_base_score, decaimento).
  - Retorna ScoreBreakdown para explicabilidade.

Limites:
  - max_feedback_bonus: teto absoluto do bônus.
  - min_base_score_for_feedback: score mínimo para aplicar feedback.
  - Se base_score < min_base_score_for_feedback, bônus = 0 (feedback não ajuda).

Integração com Context Engine:
  - O Adapter recebe a assinatura do contexto (string) e usa como parte
    da FeedbackKey. Isso permite aprender preferências contextuais:
      Consulta: "Pedro" + Contexto: "João" → João 21
      Consulta: "Pedro" + Contexto: "Atos" → Atos 2
"""

from __future__ import annotations

from feedback.dtos import (
    FeedbackKey,
    FeedbackScope,
    FeedbackStatistics,
    FeedbackSummary,
    ScoreBreakdown,
)
from feedback.engine import FeedbackEngine
from feedback.policy import LearningPolicy


# ---------------------------------------------------------------------------
# Helpers de assinatura de contexto
# ---------------------------------------------------------------------------


def context_signature_from_sermon_context(ctx) -> str:
    """Extrai assinatura do SermonContext para uso em FeedbackKey.

    A assinatura identifica o contexto do sermão de forma estável:
      - Se há livro ativo: "<book>" (ex.: "João")
      - Se há livro + capítulo: "<book>:<chapter>" (ex.: "João:3")
      - Sem contexto: ""

    Isso permite aprender preferências contextuais:
      Consulta "Pedro" + Contexto "João" → João 21
      Consulta "Pedro" + Contexto "Atos" → Atos 2

    Args:
        ctx: SermonContext (do módulo context) ou None.

    Returns:
        String de assinatura (ou "" se sem contexto).
    """
    if ctx is None:
        return ""
    book = getattr(ctx, "book", None)
    chapter = getattr(ctx, "chapter", None)
    if book and chapter is not None:
        return f"{book}:{chapter}"
    if book:
        return book
    return ""


# ---------------------------------------------------------------------------
# RankingFeedbackAdapter
# ---------------------------------------------------------------------------


class RankingFeedbackAdapter:
    """Adapter que ajusta scores do Ranking com base em feedback aprendido.

    Uso:
        adapter = RankingFeedbackAdapter(engine)
        breakdown = adapter.adjust(
            query="pedro",
            candidate_id="43:21:15",
            base_score=0.83,
            context_signature="João",
        )
        final_score = breakdown.final_score

    Desacoplamento:
        - Não conhece Searcher, Ranking, Holyrics, Parser, LLM,
          Embeddings, KnowledgeBase, Context Engine.
        - Apenas consulta FeedbackEngine e calcula ajuste.
    """

    def __init__(
        self,
        engine: FeedbackEngine,
        policy: LearningPolicy | None = None,
        scope: FeedbackScope = FeedbackScope.GLOBAL,
    ) -> None:
        """Inicializa adapter.

        Args:
            engine: FeedbackEngine para consultar estatísticas.
            policy: política de pesos (se None, usa a do engine).
            scope: escopo do feedback (default: GLOBAL).
        """
        self._engine = engine
        self._policy = policy or engine.policy
        self._scope = scope

    @property
    def engine(self) -> FeedbackEngine:
        """Engine de feedback."""
        return self._engine

    @property
    def policy(self) -> LearningPolicy:
        """Política de pesos."""
        return self._policy

    @property
    def scope(self) -> FeedbackScope:
        """Escopo do feedback."""
        return self._scope

    # ------------------------------------------------------------------
    # Ajuste de score
    # ------------------------------------------------------------------

    def adjust(
        self,
        query: str,
        candidate_id: str,
        base_score: float,
        context_signature: str = "",
    ) -> ScoreBreakdown:
        """Calcula score ajustado para um candidato.

        Args:
            query: consulta normalizada do operador.
            candidate_id: ID canônico do candidato (ex.: "43:3:16").
            base_score: score original do Ranking (similaridade) [0.0, 1.0].
            context_signature: assinatura do contexto do sermão (ou "").

        Returns:
            ScoreBreakdown com score final e decomposição para explicabilidade.
        """
        # Se a similaridade é muito baixa, feedback não ajuda
        if not self._policy.should_apply_feedback(base_score):
            return ScoreBreakdown(
                candidate_id=candidate_id,
                base_score=base_score,
                feedback_bonus=0.0,
                context_bonus=0.0,
                final_score=base_score,
                feedback_summary=None,
                has_feedback=False,
                feedback_capped=False,
            )

        # Construir chave de feedback
        key = FeedbackKey(
            scope=self._scope,
            query=query,
            context_signature=context_signature,
            candidate_id=candidate_id,
        )

        # Consultar estatísticas
        stats = self._engine.get_statistics(key)
        if stats is None or stats.total_weight == 0.0:
            # Sem feedback — score inalterado
            return ScoreBreakdown(
                candidate_id=candidate_id,
                base_score=base_score,
                feedback_bonus=0.0,
                context_bonus=0.0,
                final_score=base_score,
                feedback_summary=None,
                has_feedback=False,
                feedback_capped=False,
            )

        # Aplicar decaimento ao peso acumulado
        decayed_weight = self._policy.apply_decay(
            stats.total_weight, stats.decay_count
        )

        # Converter peso em bônus
        raw_bonus = self._policy.weight_to_bonus(decayed_weight)

        # Limitar bônus ao teto/floor
        capped_bonus = self._policy.cap_bonus(raw_bonus)
        was_capped = capped_bonus != raw_bonus

        # Calcular score final
        final_score = base_score + capped_bonus
        # Clamp final [0.0, 1.0]
        final_score = max(0.0, min(1.0, final_score))

        # Construir summary para explicabilidade
        summary = FeedbackSummary(
            key=key,
            total_events=stats.total_events,
            total_weight=stats.total_weight,
            acceptances=stats.acceptances,
            rejections=stats.rejections,
            manual_selections=stats.manual_selections,
            ignored=stats.ignored,
            decay_count=stats.decay_count,
            last_used=stats.last_used,
            has_feedback=True,
        )

        return ScoreBreakdown(
            candidate_id=candidate_id,
            base_score=base_score,
            feedback_bonus=capped_bonus,
            context_bonus=0.0,  # reservado para futuro
            final_score=final_score,
            feedback_summary=summary,
            has_feedback=True,
            feedback_capped=was_capped,
        )

    def adjust_batch(
        self,
        query: str,
        candidates: tuple[tuple[str, float], ...],
        context_signature: str = "",
    ) -> tuple[ScoreBreakdown, ...]:
        """Calcula scores ajustados para múltiplos candidatos.

        Args:
            query: consulta normalizada.
            candidates: tuple de (candidate_id, base_score).
            context_signature: assinatura do contexto.

        Returns:
            Tuple de ScoreBreakdown (na mesma ordem dos candidatos).
        """
        return tuple(
            self.adjust(
                query=query,
                candidate_id=cid,
                base_score=score,
                context_signature=context_signature,
            )
            for cid, score in candidates
        )

    # ------------------------------------------------------------------
    # Consulta direta (sem ajuste)
    # ------------------------------------------------------------------

    def get_feedback_summary(
        self,
        query: str,
        candidate_id: str,
        context_signature: str = "",
    ) -> FeedbackSummary:
        """Retorna resumo de feedback para explicabilidade.

        Não calcula bônus — apenas retorna as estatísticas.

        Args:
            query: consulta normalizada.
            candidate_id: ID do candidato.
            context_signature: assinatura do contexto.

        Returns:
            FeedbackSummary (com has_feedback=False se não existe).
        """
        key = FeedbackKey(
            scope=self._scope,
            query=query,
            context_signature=context_signature,
            candidate_id=candidate_id,
        )
        return self._engine.get_summary(key)


__all__ = [
    "RankingFeedbackAdapter",
    "context_signature_from_sermon_context",
]
