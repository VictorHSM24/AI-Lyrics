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

    Sprint 17.2 — Event Stream Optimization:
    A propriedade `category` distingue OperationalEvent de TelemetryEvent.
    O EventBus armazena apenas OperationalEvents no EventStore.
    TelemetryEvents são dispatchados aos handlers mas não persistidos.
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

    @property
    def category(self) -> str:
        """Categoria do evento: 'operational' ou 'telemetry'.

        Operational: eventos de negócio que aparecem na Timeline e
        são persistidos no EventStore.

        Telemetry: eventos de alta frequência (audio.level, cpu.usage,
        etc.) que NÃO são persistidos nem exibidos na Timeline.
        """
        if isinstance(self, TelemetryEvent):
            return "telemetry"
        return "operational"

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
# Sprint 17.2 — Categorias de evento (Operational vs Telemetry)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OperationalEvent(PipelineEvent):
    """Evento operacional — representa um acontecimento de negócio.

    Examples: PipelineStarted, SpeechTranscribed, ReferenceDetected.

    Características:
      - Vai para o EventBus e EventStore.
      - Aparece na Timeline.
      - Pode ser persistido e gerar histórico.
    """

    pass


@dataclass(frozen=True)
class TelemetryEvent(PipelineEvent):
    """Evento de telemetria — atualização contínua de métricas.

    Examples: AudioLevel, CpuUsage, GpuUsage, LatencyUpdate.

    Características:
      - NÃO é persistido no EventStore.
      - NÃO aparece na Timeline.
      - Atualiza apenas componentes visuais específicos (VU Meter, gráficos).
      - É transmitido via WebSocket normalmente.
    """

    pass


# ---------------------------------------------------------------------------
# Eventos do fluxo principal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpeechSegmentReceived(OperationalEvent):
    """Segmento de fala recebido do STT/captura.

    Inicia um novo correlation_id. Este é o ponto de entrada do fluxo.
    """

    audio: bytes = b""
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: int = 0
    chunk_count: int = 1


@dataclass(frozen=True)
class SpeechRecognized(OperationalEvent):
    """Texto reconhecido do segmento de fala."""

    text: str = ""
    language: str = ""
    confidence: float = 0.0
    processing_ms: int = 0


@dataclass(frozen=True)
class SearchRequested(OperationalEvent):
    """Pedido de busca emitido (texto reconhecido → query)."""

    query: str = ""
    intent_action: str = ""
    intent_book: str | None = None
    intent_chapter: int | None = None
    intent_verse: int | None = None


@dataclass(frozen=True)
class SearchCompleted(OperationalEvent):
    """Busca completada com resultados."""

    query: str = ""
    results: tuple = field(default_factory=tuple)  # tuple de SearchResult
    result_count: int = 0
    search_ms: int = 0


@dataclass(frozen=True)
class RankingCompleted(OperationalEvent):
    """Ranking dos resultados completado."""

    query: str = ""
    ranked_candidates: tuple = field(default_factory=tuple)  # tuple de CandidateInfo
    candidate_count: int = 0


@dataclass(frozen=True)
class IntelligenceCompleted(OperationalEvent):
    """Sermon Intelligence produziu recomendação."""

    query: str = ""
    recommendation: Any = None  # IntelligenceRecommendation
    best_candidate_id: str = ""
    confidence_level: str = ""


@dataclass(frozen=True)
class PresentationRequested(OperationalEvent):
    """Pedido de apresentação enviado ao Holyrics."""

    candidate_id: str = ""
    book_id: int = 0
    chapter: int = 0
    verse: int | None = None
    version: str = "ACF"


@dataclass(frozen=True)
class PresentationCompleted(OperationalEvent):
    """Apresentação executada no Holyrics."""

    candidate_id: str = ""
    status: str = ""
    verse_id: str = ""
    presented: bool = False


@dataclass(frozen=True)
class FeedbackRecorded(OperationalEvent):
    """Feedback registrado no Feedback Learning."""

    candidate_id: str = ""
    feedback_type: str = ""  # "accepted" | "rejected"
    scope: str = "GLOBAL"
    query: str = ""


@dataclass(frozen=True)
class EvaluationRecorded(OperationalEvent):
    """Métrica registrada no Continuous Evaluation."""

    query: str = ""
    classification: str = ""
    candidate_id: str = ""
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Eventos de ciclo de vida do Pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineStarted(OperationalEvent):
    """Pipeline iniciado."""

    pass


@dataclass(frozen=True)
class PipelineStopped(OperationalEvent):
    """Pipeline parado."""

    reason: str = ""


@dataclass(frozen=True)
class PipelinePaused(OperationalEvent):
    """Pipeline pausado."""

    reason: str = ""


@dataclass(frozen=True)
class PipelineResumed(OperationalEvent):
    """Pipeline retomado."""

    reason: str = ""


@dataclass(frozen=True)
class PipelineError(OperationalEvent):
    """Erro durante processamento do Pipeline.

    Não interrompe o Pipeline (erro é tratado pelo handler/engine).
    Carrega informações para diagnóstico.
    """

    error_type: str = ""
    error_message: str = ""
    handler_name: str = ""
    recoverable: bool = True


# ---------------------------------------------------------------------------
# Sprint 16 — Eventos do Continuous Speech Pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpeechStarted(OperationalEvent):
    """VAD detectou início de fala.

    Emitido quando o VAD transiciona de silêncio para fala.
    Inicia um novo correlation_id para o segmento.
    """

    timestamp_start: float = 0.0


@dataclass(frozen=True)
class SpeechEnded(OperationalEvent):
    """VAD detectou fim da fala.

    Emitido quando o silêncio após fala excede max_silence_ms.
    """

    timestamp_end: float = 0.0
    duration_ms: int = 0


@dataclass(frozen=True)
class SpeechSegmentCreated(OperationalEvent):
    """SpeechSegment criado e enfileirado para transcrição.

    Contém metadados do segmento (sem o áudio raw — apenas duração e timestamps).
    """

    duration_ms: int = 0
    chunk_count: int = 0
    sample_rate: int = 16000
    channels: int = 1


@dataclass(frozen=True)
class SpeechTranscribing(OperationalEvent):
    """SpeechWorker começou a transcrever o segmento."""

    duration_ms: int = 0


@dataclass(frozen=True)
class SpeechTranscribed(OperationalEvent):
    """Transcrição completada com texto reconhecido."""

    text: str = ""
    language: str = ""
    confidence: float = 0.0
    latency_ms: int = 0
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Sprint 17 — Biblical Intent & Reference Extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceDetected(OperationalEvent):
    """Referência bíblica detectada e validada pelo parser determinístico.

    Emitido quando o BiblicalNLUService processa um SpeechTranscribed e
    o Parser identifica uma referência válida (action="show").
    """

    intent: str = "OPEN_REFERENCE"
    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse_start: int = 0
    verse_end: int = 0
    confidence: float = 0.0
    raw_text: str = ""
    normalized_text: str = ""


@dataclass(frozen=True)
class ReferenceInvalid(OperationalEvent):
    """Referência bíblica inválida detectada pelo parser.

    Emitido quando o Parser encontra um livro mas capítulo/versículo
    são inválidos (ex.: "João capítulo 300", "Mateus capítulo zero").
    """

    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse_start: int = 0
    reason: str = ""  # "invalid_chapter", "invalid_verse", "zero_chapter"
    raw_text: str = ""


@dataclass(frozen=True)
class IntentUnknown(OperationalEvent):
    """Intenção não reconhecida pelo parser.

    Emitido quando o Parser não identifica nem referência nem navegação
    nem gatilhos bíblicos (action="none"). O texto transcrito não é
    um comando bíblico.
    """

    raw_text: str = ""
    reason: str = ""  # "no_book", "no_pattern", "empty_text"


# ---------------------------------------------------------------------------
# Sprint 18 — Automatic Verse Presentation
#
# Fluxo:
#   ReferenceDetected
#       ↓
#   VerseResolving        (VersePresentationService iniciou busca no Searcher)
#       ↓
#   VerseResolved         (Searcher retornou SearchResult com texto)
#       ↓
#   VersePresented        (HolyricsClient.show_verse() executou com sucesso)
#
# Em caso de erro em qualquer etapa após ReferenceDetected:
#   VersePresentationFailed (motivo detalhado, sem alterar Health)
#
# Todos derivados de OperationalEvent — aparecem na Timeline e são
# persistidos no EventStore. NÃO são telemetria.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerseResolving(OperationalEvent):
    """VersePresentationService iniciou resolução da referência no Searcher.

    Emitido quando o serviço recebe ReferenceDetected e começa a buscar
    o versículo na base bíblica.
    """

    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse_start: int = 0
    verse_end: int = 0
    normalized_text: str = ""


@dataclass(frozen=True)
class VerseResolved(OperationalEvent):
    """Searcher retornou o versículo resolvido.

    Emitido quando Searcher.search_by_reference() encontra o versículo
    com texto e versão. Próxima etapa: chamar HolyricsClient.show_verse().
    """

    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse: int = 0
    version: str = ""
    verse_text: str = ""
    reference: str = ""
    search_ms: int = 0


@dataclass(frozen=True)
class VersePresented(OperationalEvent):
    """HolyricsClient.show_verse() executou com sucesso.

    Emitido após o Holyrics confirmar a apresentação do versículo.
    Carrega a latência total (ReferenceDetected → ShowVerse) e a
    latência específica da chamada ao Holyrics.
    """

    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse: int = 0
    version: str = ""
    reference: str = ""
    quick_presentation: bool = False
    holyrics_status: str = ""
    holyrics_latency_ms: int = 0
    total_latency_ms: int = 0


@dataclass(frozen=True)
class VersePresentationFailed(OperationalEvent):
    """Falha em qualquer etapa da apresentação do versículo.

    Emitido quando:
    - Searcher não encontra o versículo (book_not_found, verse_not_found).
    - HolyricsClient levanta exceção (connection, timeout, auth, api).
    - Qualquer erro inesperado no VersePresentationService.

    NÃO altera o Health do componente Holyrics — falhas pontuais de
    apresentação não significam que o Holyrics está indisponível.
    Health só muda via health_check periódico do HealthService.
    """

    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse: int = 0
    reference: str = ""
    failure_stage: str = ""  # "search" | "holyrics" | "internal"
    error_type: str = ""     # "book_not_found", "verse_not_found",
                             # "connection", "timeout", "auth", "api",
                             # "internal_error"
    error_message: str = ""
    latency_ms: int = 0


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
    # Sprint 16 — Continuous Speech Pipeline
    SpeechStarted,
    SpeechEnded,
    SpeechSegmentCreated,
    SpeechTranscribing,
    SpeechTranscribed,
    # Sprint 17 — Biblical Intent & Reference Extraction
    ReferenceDetected,
    ReferenceInvalid,
    IntentUnknown,
    # Sprint 18 — Automatic Verse Presentation
    VerseResolving,
    VerseResolved,
    VersePresented,
    VersePresentationFailed,
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


def is_operational_event(obj: Any) -> bool:
    """True se obj é uma instância de OperationalEvent."""
    return isinstance(obj, OperationalEvent)


def is_telemetry_event(obj: Any) -> bool:
    """True se obj é uma instância de TelemetryEvent."""
    return isinstance(obj, TelemetryEvent)


__all__ = [
    "PipelineEvent",
    "OperationalEvent",
    "TelemetryEvent",
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
    # Sprint 16 — Continuous Speech Pipeline
    "SpeechStarted",
    "SpeechEnded",
    "SpeechSegmentCreated",
    "SpeechTranscribing",
    "SpeechTranscribed",
    # Sprint 17 — Biblical Intent & Reference Extraction
    "ReferenceDetected",
    "ReferenceInvalid",
    "IntentUnknown",
    # Sprint 18 — Automatic Verse Presentation
    "VerseResolving",
    "VerseResolved",
    "VersePresented",
    "VersePresentationFailed",
    "all_event_types",
    "all_event_type_names",
    "is_pipeline_event",
    "is_operational_event",
    "is_telemetry_event",
]
