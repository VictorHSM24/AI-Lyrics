"""DTOs imutáveis do Sermon Intelligence.

Todos os DTOs são frozen dataclass (imutáveis, hashable, serializáveis).

DTOs:
  - ConfidenceLevel: enum (LOW, MEDIUM, HIGH).
  - CandidateInfo: informação de um candidato recebido.
  - IntelligenceRequest: requisição completa ao Intelligence.
  - IntelligenceSignal: sinal individual (base).
  - IntelligenceScore: score final de um candidato com decomposição.
  - IntelligenceRecommendation: recomendação de ordenação.

Design:
  - Todos frozen dataclass.
  - Coleções são tuples (imutáveis).
  - Nenhum estado mutável.
  - Serializáveis via to_dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# ConfidenceLevel — nível de confiança
# ---------------------------------------------------------------------------


class ConfidenceLevel(str, Enum):
    """Nível de confiança de uma recomendação.

    A confiança nunca é binária — é calculada a partir da combinação
    de múltiplos sinais.

    Valores:
        LOW: confiança baixa (poucos sinais ou sinais conflitantes).
        MEDIUM: confiança média (alguns sinais consistentes).
        HIGH: confiança alta (muitos sinais consistentes).
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ---------------------------------------------------------------------------
# CandidateInfo — informação de um candidato
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateInfo:
    """Informação sobre um candidato recebido pelo Intelligence.

    Atributos:
        candidate_id: ID canônico (ex.: "43:21:15" para João 21:15).
        base_score: score original do Ranking (similaridade) [0.0, 1.0].
        book: nome do livro (ex.: "João") ou "".
        chapter: capítulo (int) ou None.
        verse: versículo (int) ou None.
        display: string de exibição (ex.: "João 21:15") ou "".
    """

    candidate_id: str
    base_score: float
    book: str = ""
    chapter: int | None = None
    verse: int | None = None
    display: str = ""

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "base_score": self.base_score,
            "book": self.book,
            "chapter": self.chapter,
            "verse": self.verse,
            "display": self.display,
        }


# ---------------------------------------------------------------------------
# IntelligenceRequest — requisição completa
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntelligenceRequest:
    """Requisição completa ao Sermon Intelligence.

    Contém tudo que o Intelligence precisa para produzir uma recomendação:
      - query: consulta normalizada do operador.
      - context: SermonContext atual (ou None).
      - candidates: tuple de CandidateInfo.
      - feedback_summaries: dict {candidate_id: FeedbackSummary-like}.
      - evaluation_metrics: EvaluationMetrics-like (ou None).

    Os tipos feedback_summaries e evaluation_metrics são duck-typed:
    o Intelligence acessa apenas atributos públicos via getattr, mantendo
    desacoplamento total dos módulos feedback e evaluation.

    Atributos:
        query: consulta normalizada.
        context: SermonContext (ou None).
        candidates: tuple de CandidateInfo.
        feedback_summaries: dict {candidate_id: objeto com has_feedback,
            total_weight, acceptances, etc.} (ou {}).
        evaluation_metrics: objeto com precision, total_searches, etc.
            (ou None).
    """

    query: str
    context: object | None = None
    candidates: tuple[CandidateInfo, ...] = field(default_factory=tuple)
    feedback_summaries: dict = field(default_factory=dict)
    evaluation_metrics: object | None = None

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "has_context": self.context is not None,
            "candidates": [c.to_dict() for c in self.candidates],
            "feedback_count": len(self.feedback_summaries),
            "has_evaluation": self.evaluation_metrics is not None,
        }


# ---------------------------------------------------------------------------
# IntelligenceSignal — sinal individual
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntelligenceSignal:
    """Sinal individual produzido por uma estratégia.

    Cada sinal representa um fator analisado (contexto, feedback,
    continuidade, etc.) e retorna apenas:
      - signal_type: tipo do sinal (string identificadora).
      - value: contribuição do sinal [-1.0, 1.0] (pode ser negativa).
      - weight: peso do sinal [0.0, 1.0] (importância relativa).
      - explanation: explicação legível do sinal.
      - evidences: tuple de Evidence que sustentam o sinal (default vazio).

    Nenhum sinal altera outro. Sinais são independentes.

    Imutável e hashable.
    """

    signal_type: str = ""
    value: float = 0.0
    weight: float = 0.0
    explanation: str = ""
    evidences: tuple = field(default_factory=tuple)

    @property
    def contribution(self) -> float:
        """Contribuição ponderada = value * weight."""
        return self.value * self.weight

    @property
    def has_evidences(self) -> bool:
        """True se o sinal possui evidências anexadas."""
        return len(self.evidences) > 0

    @property
    def evidence_count(self) -> int:
        """Número de evidências que sustentam o sinal."""
        return len(self.evidences)

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type,
            "value": self.value,
            "weight": self.weight,
            "contribution": self.contribution,
            "explanation": self.explanation,
            "evidences": [
                e.to_dict() if hasattr(e, "to_dict") else str(e)
                for e in self.evidences
            ],
        }


# ---------------------------------------------------------------------------
# IntelligenceScore — score final de um candidato
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntelligenceScore:
    """Score final de um candidato com decomposição completa.

    Atributos:
        candidate_id: ID do candidato.
        base_score: score original do Ranking.
        final_score: score final após combinação de sinais.
        context_contribution: contribuição do sinal de contexto.
        feedback_contribution: contribuição do sinal de feedback.
        continuity_contribution: contribuição do sinal de continuidade.
        theme_contribution: contribuição do sinal temático.
        book_contribution: contribuição do sinal de livro.
        confidence_contribution: contribuição do sinal de confiança.
        evaluation_contribution: contribuição do sinal estatístico.
        confidence_level: nível de confiança (LOW, MEDIUM, HIGH).
        signals: tuple de IntelligenceSignal individuais.
        explanation: explicação textual completa.

    Properties:
        total_contribution: soma de todas as contribuições.
    """

    candidate_id: str
    base_score: float
    final_score: float
    context_contribution: float = 0.0
    feedback_contribution: float = 0.0
    continuity_contribution: float = 0.0
    reference_contribution: float = 0.0
    theme_contribution: float = 0.0
    book_contribution: float = 0.0
    confidence_contribution: float = 0.0
    evaluation_contribution: float = 0.0
    confidence_level: ConfidenceLevel = ConfidenceLevel.LOW
    signals: tuple[IntelligenceSignal, ...] = field(default_factory=tuple)
    explanation: str = ""

    @property
    def total_contribution(self) -> float:
        """Soma de todas as contribuições (exceto base_score)."""
        return (
            self.context_contribution
            + self.feedback_contribution
            + self.continuity_contribution
            + self.reference_contribution
            + self.theme_contribution
            + self.book_contribution
            + self.confidence_contribution
            + self.evaluation_contribution
        )

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "base_score": self.base_score,
            "final_score": self.final_score,
            "context_contribution": self.context_contribution,
            "feedback_contribution": self.feedback_contribution,
            "continuity_contribution": self.continuity_contribution,
            "reference_contribution": self.reference_contribution,
            "theme_contribution": self.theme_contribution,
            "book_contribution": self.book_contribution,
            "confidence_contribution": self.confidence_contribution,
            "evaluation_contribution": self.evaluation_contribution,
            "confidence_level": self.confidence_level.value,
            "signals": [s.to_dict() for s in self.signals],
            "explanation": self.explanation,
        }

    def explain(self) -> str:
        """Gera explicação legível do score.

        Exemplo:
            "João 21:15: +0.83 Base, +0.05 Contexto, +0.09 Feedback,
             +0.03 Continuidade → 1.00 (HIGH)"
        """
        parts = [f"+{self.base_score:.2f} Base"]
        if self.context_contribution != 0:
            parts.append(f"{self.context_contribution:+.2f} Contexto")
        if self.feedback_contribution != 0:
            parts.append(f"{self.feedback_contribution:+.2f} Feedback")
        if self.continuity_contribution != 0:
            parts.append(f"{self.continuity_contribution:+.2f} Continuidade")
        if self.reference_contribution != 0:
            parts.append(f"{self.reference_contribution:+.2f} Referência")
        if self.theme_contribution != 0:
            parts.append(f"{self.theme_contribution:+.2f} Tema")
        if self.book_contribution != 0:
            parts.append(f"{self.book_contribution:+.2f} Livro")
        if self.confidence_contribution != 0:
            parts.append(f"{self.confidence_contribution:+.2f} Confiança")
        if self.evaluation_contribution != 0:
            parts.append(f"{self.evaluation_contribution:+.2f} Estatística")
        parts.append(f"→ {self.final_score:.2f}")
        parts.append(f"({self.confidence_level.value})")
        return ", ".join(parts)


# ---------------------------------------------------------------------------
# IntelligenceRecommendation — recomendação de ordenação
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntelligenceRecommendation:
    """Recomendação de ordenação produzida pelo Intelligence.

    Atributos:
        query: consulta original.
        scores: tuple de IntelligenceScore ordenados por final_score desc.
        best_candidate_id: ID do melhor candidato (ou "" se vazio).
        confidence_level: nível de confiança da recomendação.
        explanation: explicação textual da recomendação.
        has_candidates: True se havia candidatos na requisição.

    Properties:
        best_score: IntelligenceScore do melhor candidato (ou None).
        ranking: tuple de candidate_ids na ordem recomendada.
    """

    query: str
    scores: tuple[IntelligenceScore, ...] = field(default_factory=tuple)
    best_candidate_id: str = ""
    confidence_level: ConfidenceLevel = ConfidenceLevel.LOW
    explanation: str = ""
    has_candidates: bool = False

    @property
    def best_score(self) -> IntelligenceScore | None:
        """Score do melhor candidato (ou None se vazio)."""
        return self.scores[0] if self.scores else None

    @property
    def ranking(self) -> tuple[str, ...]:
        """Tuple de candidate_ids na ordem recomendada."""
        return tuple(s.candidate_id for s in self.scores)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "scores": [s.to_dict() for s in self.scores],
            "best_candidate_id": self.best_candidate_id,
            "confidence_level": self.confidence_level.value,
            "explanation": self.explanation,
            "has_candidates": self.has_candidates,
            "ranking": list(self.ranking),
        }

    def explain(self) -> str:
        """Gera explicação legível da recomendação."""
        if not self.has_candidates:
            return f"Consulta '{self.query}': sem candidatos."
        lines = [f"Consulta '{self.query}': recomendação ({self.confidence_level.value})"]
        for s in self.scores:
            lines.append(f"  {s.explain()}")
        return "\n".join(lines)


__all__ = [
    "ConfidenceLevel",
    "CandidateInfo",
    "IntelligenceRequest",
    "IntelligenceSignal",
    "IntelligenceScore",
    "IntelligenceRecommendation",
]
