"""DTOs imutáveis do Feedback Learning.

Todos os DTOs são frozen dataclass (imutáveis, hashable, fortemente tipados).

DTOs:
  - FeedbackKey: chave de identificação de uma preferência
      (scope, query, context_signature, candidate_id).
  - FeedbackRecord: registro individual de um evento de feedback.
  - FeedbackStatistics: estatísticas acumuladas para uma FeedbackKey.
  - FeedbackSummary: resumo agregado para explicabilidade.
  - ScoreBreakdown: decomposição do score final para auditoria.

Design:
  - Todos frozen dataclass.
  - Coleções são tuples (imutáveis).
  - Nenhum estado mutável.
  - Hashable (para uso em sets e dicts).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


# ---------------------------------------------------------------------------
# FeedbackScope — escopo da preferência
# ---------------------------------------------------------------------------


class FeedbackScope(str, Enum):
    """Escopo de uma preferência aprendida.

    Nesta fase apenas GLOBAL é utilizado. Os demais estão preparados
    para uso futuro (sem lógica adicional).

    Valores:
        GLOBAL: preferência global do operador (independente de sessão).
        SESSION: preferência da sessão atual (futuro).
        SERMON: preferência do sermão atual (futuro).
        USER: preferência por usuário (futuro, multi-usuário).
    """

    GLOBAL = "GLOBAL"
    SESSION = "SESSION"
    SERMON = "SERMON"
    USER = "USER"


# ---------------------------------------------------------------------------
# FeedbackKey — chave única de uma preferência
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackKey:
    """Chave que identifica unicamente uma preferência aprendida.

    A chave é composta por:
      - scope: escopo da preferência (GLOBAL, SESSION, etc.).
      - query: consulta normalizada do operador (lowercase, sem acento).
      - context_signature: assinatura do contexto do sermão
          (ex.: "João" ou "João:3" ou "" para sem contexto).
      - candidate_id: ID canônico do candidato
          (ex.: "43:3:16" para João 3:16, ou ID do versículo).

    A combinação (scope, query, context_signature, candidate_id) identifica
    uma preferência única. Duas preferências para a mesma query mas contextos
    diferentes são chaves diferentes.

    Imutável e hashable.
    """

    scope: FeedbackScope
    query: str
    context_signature: str
    candidate_id: str

    def to_dict(self) -> dict:
        """Serializa para dict (para persistência JSON)."""
        return {
            "scope": self.scope.value,
            "query": self.query,
            "context_signature": self.context_signature,
            "candidate_id": self.candidate_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FeedbackKey:
        """Desserializa de dict."""
        return cls(
            scope=FeedbackScope(d["scope"]),
            query=d["query"],
            context_signature=d.get("context_signature", ""),
            candidate_id=d["candidate_id"],
        )


# ---------------------------------------------------------------------------
# FeedbackRecord — registro individual de um evento
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackRecord:
    """Registro individual de um evento de feedback.

    Cada vez que o operador toma uma decisão (aceitar, rejeitar, ignorar),
    um FeedbackRecord é criado e armazenado.

    Atributos:
        key: FeedbackKey (scope + query + context + candidate).
        event_type: tipo do evento ("accepted", "rejected",
            "manual_reference", "suggestion_ignored").
        weight: peso aplicado pelo LearningPolicy (ex.: +3, -1, +5, -2).
        timestamp: timestamp do evento (segundos desde epoch).
        decay_count: contador de decaimento (incrementado a cada uso
            sem reutilização). Inicia em 0.

    Imutável e hashable.
    """

    key: FeedbackKey
    event_type: str
    weight: float
    timestamp: float
    decay_count: int = 0

    def to_dict(self) -> dict:
        """Serializa para dict."""
        return {
            "key": self.key.to_dict(),
            "event_type": self.event_type,
            "weight": self.weight,
            "timestamp": self.timestamp,
            "decay_count": self.decay_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FeedbackRecord:
        """Desserializa de dict."""
        return cls(
            key=FeedbackKey.from_dict(d["key"]),
            event_type=d["event_type"],
            weight=d["weight"],
            timestamp=d["timestamp"],
            decay_count=d.get("decay_count", 0),
        )


# ---------------------------------------------------------------------------
# FeedbackStatistics — estatísticas acumuladas por chave
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackStatistics:
    """Estatísticas acumuladas para uma FeedbackKey.

    Mantém contadores e peso acumulado para uma preferência. É usada
    pelo RankingFeedbackAdapter para calcular o bônus de feedback.

    Atributos:
        key: FeedbackKey da preferência.
        acceptances: quantidade de CandidateAccepted.
        rejections: quantidade de CandidateRejected.
        manual_selections: quantidade de ManualReferenceSelected.
        ignored: quantidade de SuggestionIgnored.
        total_weight: soma acumulada de pesos (com decaimento aplicado).
        last_used: timestamp do último evento.
        first_used: timestamp do primeiro evento.
        decay_count: contador de decaimento atual.

    Imutável. Atualizações retornam nova FeedbackStatistics.
    """

    key: FeedbackKey
    acceptances: int = 0
    rejections: int = 0
    manual_selections: int = 0
    ignored: int = 0
    total_weight: float = 0.0
    last_used: float = 0.0
    first_used: float = 0.0
    decay_count: int = 0

    @property
    def total_events(self) -> int:
        """Total de eventos registrados."""
        return (
            self.acceptances
            + self.rejections
            + self.manual_selections
            + self.ignored
        )

    @property
    def frequency(self) -> float:
        """Frequência relativa de uso (eventos por unidade de tempo).

        Retorna 0.0 se não há eventos ou se o intervalo é zero.
        """
        if self.total_events == 0 or self.last_used <= self.first_used:
            return 0.0
        return self.total_events / (self.last_used - self.first_used)

    def to_dict(self) -> dict:
        """Serializa para dict."""
        return {
            "key": self.key.to_dict(),
            "acceptances": self.acceptances,
            "rejections": self.rejections,
            "manual_selections": self.manual_selections,
            "ignored": self.ignored,
            "total_weight": self.total_weight,
            "last_used": self.last_used,
            "first_used": self.first_used,
            "decay_count": self.decay_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FeedbackStatistics:
        """Desserializa de dict."""
        return cls(
            key=FeedbackKey.from_dict(d["key"]),
            acceptances=d.get("acceptances", 0),
            rejections=d.get("rejections", 0),
            manual_selections=d.get("manual_selections", 0),
            ignored=d.get("ignored", 0),
            total_weight=d.get("total_weight", 0.0),
            last_used=d.get("last_used", 0.0),
            first_used=d.get("first_used", 0.0),
            decay_count=d.get("decay_count", 0),
        )


# ---------------------------------------------------------------------------
# FeedbackSummary — resumo para explicabilidade
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackSummary:
    """Resumo agregado de feedback para uma preferência.

    Usado para explicabilidade: mostra ao operador (ou log) qual é o
    estado da preferência para uma dada chave.

    Atributos:
        key: FeedbackKey.
        total_events: total de eventos.
        total_weight: peso acumulado (com decaimento).
        acceptances: aceitações.
        rejections: rejeições.
        manual_selections: seleções manuais.
        ignored: sugestões ignoradas.
        decay_count: contador de decaimento.
        last_used: timestamp do último uso.
        has_feedback: True se há qualquer feedback registrado.
    """

    key: FeedbackKey
    total_events: int
    total_weight: float
    acceptances: int
    rejections: int
    manual_selections: int
    ignored: int
    decay_count: int
    last_used: float
    has_feedback: bool

    def to_dict(self) -> dict:
        """Serializa para dict."""
        return {
            "key": self.key.to_dict(),
            "total_events": self.total_events,
            "total_weight": self.total_weight,
            "acceptances": self.acceptances,
            "rejections": self.rejections,
            "manual_selections": self.manual_selections,
            "ignored": self.ignored,
            "decay_count": self.decay_count,
            "last_used": self.last_used,
            "has_feedback": self.has_feedback,
        }


# ---------------------------------------------------------------------------
# ScoreBreakdown — decomposição do score para auditoria
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreBreakdown:
    """Decomposição do score final de um candidato para explicabilidade.

    Permite auditar por que um candidato recebeu determinado score,
    mostrando a contribuição de cada sinal.

    Atributos:
        candidate_id: ID do candidato.
        base_score: score original do Ranking (similaridade).
        feedback_bonus: bônus aplicado pelo feedback.
        context_bonus: bônus aplicado pelo contexto (reservado, 0 hoje).
        final_score: score final após ajustes.
        feedback_summary: FeedbackSummary usado (ou None se sem feedback).
        has_feedback: True se feedback foi aplicado.
        feedback_capped: True se o bônus foi limitado pelo teto.

    Exemplo de explicação:
        "Lucas 15: +0.83 Similaridade, +0.09 Feedback, +0.05 Contexto"
    """

    candidate_id: str
    base_score: float
    feedback_bonus: float
    context_bonus: float
    final_score: float
    feedback_summary: FeedbackSummary | None = None
    has_feedback: bool = False
    feedback_capped: bool = False

    def to_dict(self) -> dict:
        """Serializa para dict."""
        return {
            "candidate_id": self.candidate_id,
            "base_score": self.base_score,
            "feedback_bonus": self.feedback_bonus,
            "context_bonus": self.context_bonus,
            "final_score": self.final_score,
            "feedback_summary": self.feedback_summary.to_dict() if self.feedback_summary else None,
            "has_feedback": self.has_feedback,
            "feedback_capped": self.feedback_capped,
        }

    def explain(self) -> str:
        """Gera explicação legível do score.

        Exemplo:
            "Lucas 15: +0.83 Similaridade, +0.09 Feedback, +0.05 Contexto"
        """
        parts = [f"+{self.base_score:.2f} Similaridade"]
        if self.feedback_bonus > 0:
            cap = " (limitado)" if self.feedback_capped else ""
            parts.append(f"+{self.feedback_bonus:.2f} Feedback{cap}")
        elif self.feedback_bonus < 0:
            parts.append(f"{self.feedback_bonus:.2f} Feedback")
        if self.context_bonus > 0:
            parts.append(f"+{self.context_bonus:.2f} Contexto")
        return ", ".join(parts)


__all__ = [
    "FeedbackScope",
    "FeedbackKey",
    "FeedbackRecord",
    "FeedbackStatistics",
    "FeedbackSummary",
    "ScoreBreakdown",
]
