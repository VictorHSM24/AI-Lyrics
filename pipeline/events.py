"""Eventos tipados do Pipeline (Fase 12).

Todos os eventos são frozen dataclass, imutáveis, hashable, serializáveis.
Cada evento carrega exatamente um EventMetadata (rastreabilidade).

Nenhum evento duplica campos de EventMetadata.

Fluxo principal:
    SpeechSegmentReceived
        ↓
    SpeechRecognized
        ↓
    SearchRequested
        ↓
    SearchCompleted
        ↓
    RankingCompleted
        ↓
    IntelligenceCompleted
        ↓
    PresentationRequested
        ↓
    PresentationCompleted
        ↓
    FeedbackRecorded
        ↓
    EvaluationRecorded

Eventos de ciclo de vida:
    PipelineStarted, PipelineStopped, PipelinePaused, PipelineResumed

Evento de erro:
    PipelineError

Design:
  - Cada evento carrega apenas os dados específicos da sua etapa.
  - EventMetadata é sempre o primeiro campo (chamado `meta`).
  - Nenhum evento chama outro handler diretamente.
  - Novos eventos podem ser adicionados sem quebrar existentes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.metadata import EventMetadata


# ---------------------------------------------------------------------------
# Base comum
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineEvent:
    """Base comum para todos os eventos do Pipeline.

    Todo evento tem um campo `meta: EventMetadata` que carrega
    rastreabilidade. Subclasses adicionam apenas dados específicos.
    """

    meta: EventMetadata

    @property
    def event_type(self) -> str:
        """Nome do tipo do evento (string identificadora)."""
        return self.__class__.__name__

    @property
    def event_id(self) -> str:
        return self.meta.event_id

    @property
    def correlation_id(self) -> str:
        return self.meta.correlation_id

    @property
    def causation_id(self) -> str | None:
        return self.meta.causation_id

    @property
    def session_id(self) -> str:
        return self.meta.session_id

    @property
    def timestamp(self) -> float:
        return self.meta.timestamp

    @property
    def origin(self) -> str:
        return self.meta.origin

    def to_dict(self) -> dict:
        """Serializa o evento para dict (inclui meta e campos específicos)."""
        result = {
            "event_type": self.event_type,
            "meta": self.meta.to_dict(),
        }
        # Adicionar campos específicos da subclasse (não-meta)
        for f in self.__dataclass_fields__:
            if f == "meta":
                continue
            val = getattr(self, f)
            if hasattr(val, "to_dict"):
                result[f] = val.to_dict()
            elif isinstance(val, (list, tuple)):
                result[f] = [
                    v.to_dict() if hasattr(v, "to_dict") else v for v in val
                ]
            else:
                result[f] = val
        return result


# ---------------------------------------------------------------------------
# Eventos do fluxo principal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpeechSegmentReceived(PipelineEvent):
    """Segmento de fala recebido do STT/captura.

    Inicia um novo correlation_id. Este é o ponto de entrada do fluxo.
    """

    audio: bytes = b""
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: int = 0
    chunk_count: int = 1


@dataclass(frozen=True)
class SpeechRecognized(PipelineEvent):
    """Texto reconhecido do segmento de fala."""

    text: str = ""
    language: str = ""
    confidence: float = 0.0
    processing_ms: int = 0


@dataclass(frozen=True)
class SearchRequested(PipelineEvent):
    """Pedido de busca emitido (texto reconhecido → query)."""

    query: str = ""
    intent_action: str = ""
    intent_book: str | None = None
    intent_chapter: int | None = None
    intent_verse: int | None = None


@dataclass(frozen=True)
class SearchCompleted(PipelineEvent):
    """Busca completada com resultados."""

    query: str = ""
    results: tuple = field(default_factory=tuple)  # tuple de SearchResult
    result_count: int = 0
    search_ms: int = 0


@dataclass(frozen=True)
class RankingCompleted(PipelineEvent):
    """Ranking dos resultados completado."""

    query: str = ""
    ranked_candidates: tuple = field(default_factory=tuple)  # tuple de CandidateInfo
    candidate_count: int = 0


@dataclass(frozen=True)
class IntelligenceCompleted(PipelineEvent):
    """Sermon Intelligence produziu recomendação."""

    query: str = ""
    recommendation: Any = None  # IntelligenceRecommendation
    best_candidate_id: str = ""
    confidence_level: str = ""


@dataclass(frozen=True)
class PresentationRequested(PipelineEvent):
    """Pedido de apresentação enviado ao Holyrics."""

    candidate_id: str = ""
    book_id: int = 0
    chapter: int = 0
    verse: int | None = None
    version: str = "ACF"


@dataclass(frozen=True)
class PresentationCompleted(PipelineEvent):
    """Apresentação executada no Holyrics."""

    candidate_id: str = ""
    status: str = ""
    verse_id: str = ""
    presented: bool = False


@dataclass(frozen=True)
class FeedbackRecorded(PipelineEvent):
    """Feedback registrado no Feedback Learning."""

    candidate_id: str = ""
    feedback_type: str = ""  # "accepted" | "rejected"
    scope: str = "GLOBAL"
    query: str = ""


@dataclass(frozen=True)
class EvaluationRecorded(PipelineEvent):
    """Métrica registrada no Continuous Evaluation."""

    query: str = ""
    classification: str = ""
    candidate_id: str = ""
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Eventos de ciclo de vida do Pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineStarted(PipelineEvent):
    """Pipeline iniciado."""

    pass


@dataclass(frozen=True)
class PipelineStopped(PipelineEvent):
    """Pipeline parado."""

    reason: str = ""


@dataclass(frozen=True)
class PipelinePaused(PipelineEvent):
    """Pipeline pausado."""

    reason: str = ""


@dataclass(frozen=True)
class PipelineResumed(PipelineEvent):
    """Pipeline retomado."""

    reason: str = ""


@dataclass(frozen=True)
class PipelineError(PipelineEvent):
    """Erro durante processamento do Pipeline.

    Não interrompe o Pipeline (erro é tratado pelo handler/engine).
    Carrega informações para diagnóstico.
    """

    error_type: str = ""
    error_message: str = ""
    handler_name: str = ""
    recoverable: bool = True


# ---------------------------------------------------------------------------
# Registry de tipos de evento
# ---------------------------------------------------------------------------


_ALL_EVENT_TYPES = (
    SpeechSegmentReceived,
    SpeechRecognized,
    SearchRequested,
    SearchCompleted,
    RankingCompleted,
    IntelligenceCompleted,
    PresentationRequested,
    PresentationCompleted,
    FeedbackRecorded,
    EvaluationRecorded,
    PipelineStarted,
    PipelineStopped,
    PipelinePaused,
    PipelineResumed,
    PipelineError,
)

_ALL_EVENT_TYPE_NAMES = tuple(c.__name__ for c in _ALL_EVENT_TYPES)


def all_event_types() -> tuple:
    """Retorna todas as classes de evento do Pipeline."""
    return _ALL_EVENT_TYPES


def all_event_type_names() -> tuple:
    """Retorna os nomes de todos os tipos de evento."""
    return _ALL_EVENT_TYPE_NAMES


def is_pipeline_event(obj: Any) -> bool:
    """True se obj é uma instância de PipelineEvent."""
    return isinstance(obj, PipelineEvent)


__all__ = [
    "PipelineEvent",
    "SpeechSegmentReceived",
    "SpeechRecognized",
    "SearchRequested",
    "SearchCompleted",
    "RankingCompleted",
    "IntelligenceCompleted",
    "PresentationRequested",
    "PresentationCompleted",
    "FeedbackRecorded",
    "EvaluationRecorded",
    "PipelineStarted",
    "PipelineStopped",
    "PipelinePaused",
    "PipelineResumed",
    "PipelineError",
    "all_event_types",
    "all_event_type_names",
    "is_pipeline_event",
]
