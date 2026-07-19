"""Schemas — modelos Pydantic para serialização JSON.

Estes schemas espelham os DTOs da Presentation Layer, mas são
independentes — não importam dos DTOs. A conversão DTO → schema
acontece nos routers via `from_dto()`.

Todos os schemas são imutáveis (model_config = ConfigDict(frozen=True)).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Versioning — envelope Versioned<T>.
# ---------------------------------------------------------------------------


class ApiVersionModel(BaseModel):
    """Versão da API (semver-like)."""

    model_config = ConfigDict(frozen=True)

    major: int
    minor: int
    patch: int
    pre: str | None = None


# Versão atual da API (deve espelhar frontend CURRENT_API_VERSION).
CURRENT_API_VERSION = ApiVersionModel(major=0, minor=1, patch=0, pre="foundation")


def versioned(payload: BaseModel | dict) -> dict:
    """Envolve payload em Versioned<T> (dict JSON serializável)."""
    if isinstance(payload, BaseModel):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    return {
        "api": CURRENT_API_VERSION.model_dump(mode="json"),
        "payload": data,
    }


# ---------------------------------------------------------------------------
# DTOs de apresentação (espelham presentation/dtos.py).
# ---------------------------------------------------------------------------


class EventMetadataModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    correlation_id: str
    causation_id: str | None = None
    session_id: str
    timestamp: float
    origin: str
    metadata: tuple = ()


class EventModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: str
    meta: EventMetadataModel
    payload: dict

    @classmethod
    def from_dto(cls, dto: Any) -> "EventModel":
        return cls(
            event_type=dto.event_type,
            meta=EventMetadataModel(
                event_id=dto.meta.event_id,
                correlation_id=dto.meta.correlation_id,
                causation_id=dto.meta.causation_id,
                session_id=dto.meta.session_id,
                timestamp=dto.meta.timestamp,
                origin=dto.meta.origin,
                metadata=tuple(dto.meta.metadata),
            ),
            payload=dict(dto.payload),
        )


class PipelineStatusModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    running: bool
    paused: bool
    is_active: bool
    is_idle: bool
    is_processing: bool
    current_segment: dict | None = None
    last_query: str = ""
    last_candidate_id: str = ""
    last_event_type: str = ""
    last_event_timestamp: float = 0.0
    statistics: dict = {}

    @classmethod
    def from_dto(cls, dto: Any) -> "PipelineStatusModel":
        seg = dto.current_segment
        seg_dict = None
        if seg is not None:
            if hasattr(seg, "to_dict"):
                seg_dict = seg.to_dict()
            elif isinstance(seg, dict):
                seg_dict = seg
            else:
                seg_dict = {"value": str(seg)}
        return cls(
            running=dto.running,
            paused=dto.paused,
            is_active=dto.is_active,
            is_idle=dto.is_idle,
            is_processing=dto.is_processing,
            current_segment=seg_dict,
            last_query=dto.last_query,
            last_candidate_id=dto.last_candidate_id,
            last_event_type=dto.last_event_type,
            last_event_timestamp=dto.last_event_timestamp,
            statistics=dict(dto.statistics),
        )


class SessionModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    started_at: float
    ended_at: float
    is_active: bool
    is_ended: bool
    duration_s: float
    processed_segments: int
    processed_queries: int
    presentations: int
    errors: int
    error_rate: float
    presentation_rate: float
    segments_per_minute: float
    queries_per_minute: float
    unique_correlations: int
    correlation_ids: tuple = ()

    @classmethod
    def from_dto(cls, dto: Any) -> "SessionModel":
        return cls(
            session_id=dto.session_id,
            started_at=dto.started_at,
            ended_at=dto.ended_at,
            is_active=dto.is_active,
            is_ended=dto.is_ended,
            duration_s=dto.duration_s,
            processed_segments=dto.processed_segments,
            processed_queries=dto.processed_queries,
            presentations=dto.presentations,
            errors=dto.errors,
            error_rate=dto.error_rate,
            presentation_rate=dto.presentation_rate,
            segments_per_minute=dto.segments_per_minute,
            queries_per_minute=dto.queries_per_minute,
            unique_correlations=dto.unique_correlations,
            correlation_ids=tuple(dto.correlation_ids),
        )


class MetricsModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    segments_received: int
    segments_processed: int
    segments_dropped: int
    queries_processed: int
    presentations_executed: int
    presentations_failed: int
    errors_total: int
    errors_recoverable: int
    errors_fatal: int
    total_latency_ms: float
    avg_latency_ms: float
    avg_recognition_latency_ms: float
    avg_search_latency_ms: float
    avg_ranking_latency_ms: float
    avg_intelligence_latency_ms: float
    avg_presentation_latency_ms: float
    throughput_segments_per_min: float
    throughput_queries_per_min: float
    error_rate: float
    drop_rate: float
    presentation_success_rate: float
    processing_success_rate: float
    duration_s: float
    correlation_count: int

    @classmethod
    def from_dto(cls, dto: Any) -> "MetricsModel":
        return cls(
            segments_received=dto.segments_received,
            segments_processed=dto.segments_processed,
            segments_dropped=dto.segments_dropped,
            queries_processed=dto.queries_processed,
            presentations_executed=dto.presentations_executed,
            presentations_failed=dto.presentations_failed,
            errors_total=dto.errors_total,
            errors_recoverable=dto.errors_recoverable,
            errors_fatal=dto.errors_fatal,
            total_latency_ms=dto.total_latency_ms,
            avg_latency_ms=dto.avg_latency_ms,
            avg_recognition_latency_ms=dto.avg_recognition_latency_ms,
            avg_search_latency_ms=dto.avg_search_latency_ms,
            avg_ranking_latency_ms=dto.avg_ranking_latency_ms,
            avg_intelligence_latency_ms=dto.avg_intelligence_latency_ms,
            avg_presentation_latency_ms=dto.avg_presentation_latency_ms,
            throughput_segments_per_min=dto.throughput_segments_per_min,
            throughput_queries_per_min=dto.throughput_queries_per_min,
            error_rate=dto.error_rate,
            drop_rate=dto.drop_rate,
            presentation_success_rate=dto.presentation_success_rate,
            processing_success_rate=dto.processing_success_rate,
            duration_s=dto.duration_s,
            correlation_count=dto.correlation_count,
        )


class ConfigurationModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: str
    holyrics: dict
    stt: dict
    llm: dict
    search: dict
    state: dict
    cache: dict
    confidence: dict
    log: dict
    audio: dict | None = None
    pipeline_policy: dict | None = None

    @classmethod
    def from_dto(cls, dto: Any) -> "ConfigurationModel":
        return cls(
            mode=dto.mode,
            holyrics=dict(dto.holyrics),
            stt=dict(dto.stt),
            llm=dict(dto.llm),
            search=dict(dto.search),
            state=dict(dto.state),
            cache=dict(dto.cache),
            confidence=dict(dto.confidence),
            log=dict(dto.log),
            audio=dict(dto.audio) if dto.audio is not None else None,
            pipeline_policy=dict(dto.pipeline_policy) if dto.pipeline_policy is not None else None,
        )


class HealthComponentModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    component: str
    status: Literal["healthy", "degraded", "unhealthy", "unknown"]
    message: str
    details: dict

    @classmethod
    def from_dto(cls, dto: Any) -> "HealthComponentModel":
        return cls(
            component=dto.component,
            status=dto.status,
            message=dto.message,
            details=dict(dto.details),
        )


class HealthSnapshotModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: float
    components: tuple[HealthComponentModel, ...]
    component_count: int
    healthy_count: int
    unhealthy_count: int
    all_healthy: bool

    @classmethod
    def from_dto(cls, dto: Any) -> "HealthSnapshotModel":
        return cls(
            timestamp=dto.timestamp,
            components=tuple(HealthComponentModel.from_dto(c) for c in dto.components),
            component_count=dto.component_count,
            healthy_count=dto.healthy_count,
            unhealthy_count=dto.unhealthy_count,
            all_healthy=dto.all_healthy,
        )


class DiagnosticModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    component: str
    category: str
    available: bool
    info: dict
    warnings: tuple = ()
    errors: tuple = ()

    @classmethod
    def from_dto(cls, dto: Any) -> "DiagnosticModel":
        return cls(
            component=dto.component,
            category=dto.category,
            available=dto.available,
            info=dict(dto.info),
            warnings=tuple(dto.warnings),
            errors=tuple(dto.errors),
        )


class PipelineSnapshotModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: float
    status: PipelineStatusModel
    session: SessionModel
    metrics: MetricsModel
    last_event: EventModel | None = None

    @classmethod
    def from_dto(cls, dto: Any) -> "PipelineSnapshotModel":
        last = None
        if dto.last_event is not None:
            last = EventModel.from_dto(dto.last_event)
        return cls(
            timestamp=dto.timestamp,
            status=PipelineStatusModel.from_dto(dto.status),
            session=SessionModel.from_dto(dto.session),
            metrics=MetricsModel.from_dto(dto.metrics),
            last_event=last,
        )


class EventSnapshotModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: float
    events: tuple[EventModel, ...]
    correlation_id: str
    event_count: int
    event_types: tuple[str, ...]

    @classmethod
    def from_dto(cls, dto: Any) -> "EventSnapshotModel":
        return cls(
            timestamp=dto.timestamp,
            events=tuple(EventModel.from_dto(e) for e in dto.events),
            correlation_id=dto.correlation_id,
            event_count=dto.event_count,
            event_types=tuple(dto.event_types),
        )


# ---------------------------------------------------------------------------
# Erro — modelo único de erro (espelha frontend PresentationError).
# ---------------------------------------------------------------------------


class PresentationErrorModel(BaseModel):
    """Erro canônico da API (espelha frontend PresentationError)."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    details: dict = {}
    recoverable: bool = False
    severity: Literal["info", "low", "medium", "high", "critical"] = "medium"
    correlation_id: str | None = None
    timestamp: float = Field(default_factory=lambda: __import__("time").time())


# ---------------------------------------------------------------------------
# WebSocket — mensagens trocadas no WS.
# ---------------------------------------------------------------------------


class WsHelloModel(BaseModel):
    """Mensagem inicial enviada pelo servidor ao conectar."""

    model_config = ConfigDict(frozen=True)

    type: Literal["hello"] = "hello"
    api: ApiVersionModel
    server_time: float


class WsEventModel(BaseModel):
    """Mensagem com um evento transmitido."""

    model_config = ConfigDict(frozen=True)

    type: Literal["event"] = "event"
    event: EventModel


class WsHeartbeatAckModel(BaseModel):
    """Confirmação de heartbeat."""

    model_config = ConfigDict(frozen=True)

    type: Literal["heartbeat_ack"] = "heartbeat_ack"
    server_time: float


class WsErrorModel(BaseModel):
    """Erro enviado via WebSocket."""

    model_config = ConfigDict(frozen=True)

    type: Literal["error"] = "error"
    error: PresentationErrorModel
