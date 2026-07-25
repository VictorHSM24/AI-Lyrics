"""Sprint 22.2 — Política de Contexto do Sermão para o pipeline RAG.

Princípio arquitetural: BibleRetriever > Texto Atual > Contexto do
Sermão. Quando há candidato dominante recuperado da Bíblia local
(top1 com score alto e gap grande vs top2), o contexto do sermão é
OMITIDO do prompt enviado ao LLM. O contexto só é incluído para
desambiguação entre candidatos próximos.

Três níveis de confiança da recuperação:

1. alta_confianca  — top1 dominante (score >= dominant_score AND
   gap >= dominant_gap). Contexto OMITIDO. O LLM escolhe apenas
   pela lista de candidatos.

2. ambiguidade_moderada — gap entre dominant_gap e ambiguity_gap.
   Contexto RESUMIDO (apenas current_book, sem capítulo/tema).

3. alta_ambiguidade — gap < ambiguity_gap OU top1 < dominant_score.
   Contexto COMPLETO incluído para desambiguação.

Adicionalmente, se a confiança do SermonMemory (current_book_confidence)
for menor que min_confidence, o contexto é sempre OMITIDO
independentemente do nível, pois o SermonMemory não tem evidência
suficiente para influenciar a decisão.

Esta classe é puramente funcional (sem IO, sem estado). Recebe os
metadados da recuperação e do SermonMemory, retorna uma decisão.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.models import RagPolicyConfig, SermonContextPolicyConfig
from knowledge.types import RetrievalMeta


# Níveis de confiança da recuperação (strings estáveis para telemetria).
LEVEL_ALTA_CONFIANCA = "alta_confianca"
LEVEL_AMBIGUIDADE_MODERADA = "ambiguidade_moderada"
LEVEL_ALTA_AMBIGUIDADE = "alta_ambiguidade"

# Modos de inclusão do contexto no prompt.
CONTEXT_OMIT = "omit"
CONTEXT_SUMMARY = "summary"  # apenas current_book
CONTEXT_FULL = "full"  # current_book + capítulo + tema + entidades


@dataclass(frozen=True)
class ContextDecision:
    """Sprint 22.2 — Decisão da ContextPolicy para uma inferência.

    Atributos:
        level: nível de confiança da recuperação (uma das LEVEL_*
            constantes acima).
        include_context: modo de inclusão do contexto (CONTEXT_OMIT,
            CONTEXT_SUMMARY ou CONTEXT_FULL).
        reason: motivo curto e human-readable da decisão (para
            telemetria e debug).
        top1_score: score do top1 (echo do RetrievalMeta, para
            telemetria).
        top2_score: score do top2.
        gap: diferença top1 - top2.
        sermon_confidence: confiança do SermonMemory considerada.
        sermon_book: livro do sermão considerado (ou "" se nenhum).
        num_candidates: total de candidatos recuperados.
    """

    level: str
    include_context: str
    reason: str
    top1_score: float
    top2_score: float
    gap: float
    sermon_confidence: float
    sermon_book: str
    num_candidates: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "include_context": self.include_context,
            "reason": self.reason,
            "top1_score": round(self.top1_score, 4),
            "top2_score": round(self.top2_score, 4),
            "gap": round(self.gap, 4),
            "sermon_confidence": round(self.sermon_confidence, 4),
            "sermon_book": self.sermon_book,
            "num_candidates": self.num_candidates,
        }


class ContextPolicy:
    """Sprint 22.2 — Decide quanto do contexto do sermão incluir.

    Instanciada uma vez no composition root com a config e reutilizada
    em cada inferência. Não tem estado mutável entre chamadas.
    """

    def __init__(
        self,
        rag: RagPolicyConfig | None = None,
        context: SermonContextPolicyConfig | None = None,
    ) -> None:
        self._rag = rag or RagPolicyConfig()
        self._ctx = context or SermonContextPolicyConfig()

    @property
    def rag_config(self) -> RagPolicyConfig:
        return self._rag

    @property
    def context_config(self) -> SermonContextPolicyConfig:
        return self._ctx

    def decide(
        self,
        meta: RetrievalMeta,
        sermon_book: str | None,
        sermon_confidence: float,
    ) -> ContextDecision:
        """Avalia metadados da recuperação + SermonMemory e decide.

        Args:
            meta: RetrievalMeta computado a partir dos candidatos.
            sermon_book: current_book do SermonMemory (ou None/"").
            sermon_confidence: current_book_confidence do SermonMemory
                (ou confidence geral se current_book_confidence não
                estiver disponível).

        Returns:
            ContextDecision com level, include_context e reason.
        """
        book = sermon_book or ""
        # Sem contexto do sermão disponível: sempre omitir.
        if not book:
            level = self._classify_level(meta)
            return ContextDecision(
                level=level,
                include_context=CONTEXT_OMIT,
                reason="no_sermon_book",
                top1_score=meta.top1_score,
                top2_score=meta.top2_score,
                gap=meta.gap,
                sermon_confidence=sermon_confidence,
                sermon_book="",
                num_candidates=meta.num_candidates,
            )

        # Confiança do SermonMemory abaixo do mínimo: omitir contexto
        # independentemente do nível da recuperação.
        if sermon_confidence < self._ctx.min_confidence:
            level = self._classify_level(meta)
            return ContextDecision(
                level=level,
                include_context=CONTEXT_OMIT,
                reason=(
                    f"sermon_confidence_below_min "
                    f"({sermon_confidence:.2f} < {self._ctx.min_confidence:.2f})"
                ),
                top1_score=meta.top1_score,
                top2_score=meta.top2_score,
                gap=meta.gap,
                sermon_confidence=sermon_confidence,
                sermon_book=book,
                num_candidates=meta.num_candidates,
            )

        # Classificar nível da recuperação.
        level = self._classify_level(meta)

        # Decidir inclusão conforme nível.
        if level == LEVEL_ALTA_CONFIANCA:
            # Candidato dominante: contexto omitido.
            return ContextDecision(
                level=level,
                include_context=CONTEXT_OMIT,
                reason=(
                    f"dominant_candidate "
                    f"(top1={meta.top1_score:.2f}, gap={meta.gap:.2f})"
                ),
                top1_score=meta.top1_score,
                top2_score=meta.top2_score,
                gap=meta.gap,
                sermon_confidence=sermon_confidence,
                sermon_book=book,
                num_candidates=meta.num_candidates,
            )
        if level == LEVEL_AMBIGUIDADE_MODERADA:
            # Gap moderado: contexto resumido (apenas livro).
            return ContextDecision(
                level=level,
                include_context=CONTEXT_SUMMARY,
                reason=(
                    f"moderate_ambiguity "
                    f"(gap={meta.gap:.2f} in "
                    f"[{self._rag.ambiguity_gap:.2f}, "
                    f"{self._rag.dominant_gap:.2f})"
                ),
                top1_score=meta.top1_score,
                top2_score=meta.top2_score,
                gap=meta.gap,
                sermon_confidence=sermon_confidence,
                sermon_book=book,
                num_candidates=meta.num_candidates,
            )
        # alta_ambiguidade: contexto completo para desambiguação.
        return ContextDecision(
            level=level,
            include_context=CONTEXT_FULL,
            reason=(
                f"high_ambiguity "
                f"(gap={meta.gap:.2f} < {self._rag.ambiguity_gap:.2f} "
                f"or top1={meta.top1_score:.2f} < "
                f"{self._rag.dominant_score:.2f})"
            ),
            top1_score=meta.top1_score,
            top2_score=meta.top2_score,
            gap=meta.gap,
            sermon_confidence=sermon_confidence,
            sermon_book=book,
            num_candidates=meta.num_candidates,
        )

    def _classify_level(self, meta: RetrievalMeta) -> str:
        """Classifica a recuperação em um dos três níveis.

        Lógica:
        - Se num_candidates == 0: alta_ambiguidade (sem evidência).
        - Se top1 >= dominant_score AND gap >= dominant_gap:
          alta_confianca.
        - Se gap < ambiguity_gap: alta_ambiguidade.
        - Caso contrário: ambiguidade_moderada.

        Arredonda gap para 6 casas para evitar erros de floating point
        em comparações de limiar (ex.: 0.98 - 0.90 = 0.0799...).
        """
        if meta.num_candidates == 0:
            return LEVEL_ALTA_AMBIGUIDADE
        gap = round(meta.gap, 6)
        if (
            meta.top1_score >= self._rag.dominant_score
            and gap >= self._rag.dominant_gap
        ):
            return LEVEL_ALTA_CONFIANCA
        if gap < self._rag.ambiguity_gap:
            return LEVEL_ALTA_AMBIGUIDADE
        return LEVEL_AMBIGUIDADE_MODERADA
