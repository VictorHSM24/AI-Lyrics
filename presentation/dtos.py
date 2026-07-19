"""DTOs imutáveis da Presentation Layer.

Todos os DTOs são frozen dataclass (imutáveis, serializáveis).
Nenhum DTO expõe objetos internos do domínio — apenas tipos
primitivos (str, int, float, bool, tuple, dict).

A Presentation Layer usa estes DTOs para comunicar-se com
futuras interfaces (REST, WebSocket, CLI, Dashboard, Replay).

DTOs:
  - EventMetadataDTO: rastreabilidade de evento.
  - EventDTO: evento do pipeline.
  - PipelineStatusDTO: estado atual do pipeline.
  - SessionDTO: sessão (sermão).
  - MetricsDTO: métricas do pipeline.
  - ConfigurationDTO: configuração do sistema.
  - HealthDTO: saúde de um componente.
  - DiagnosticDTO: diagnóstico de um componente.
  - LogDTO: entrada de log.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# EventMetadataDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EventMetadataDTO:
    """DTO de rastreabilidade de evento."""

    event_id: str
    correlation_id: str
    causation_id: str | None
    session_id: str
    timestamp: float
    origin: str
    metadata: tuple = field(default_factory=tuple)

    @property
    def is_initial(self) -> bool:
        return self.causation_id is None

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "origin": self.origin,
            "metadata": list(self.metadata),
        }


# ---------------------------------------------------------------------------
# EventDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EventDTO:
    """DTO de um evento do pipeline."""

    event_type: str
    meta: EventMetadataDTO
    payload: dict = field(default_factory=dict)

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
        return {
            "event_type": self.event_type,
            "meta": self.meta.to_dict(),
            "payload": dict(self.payload),
        }


# ---------------------------------------------------------------------------
# PipelineStatusDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineStatusDTO:
    """DTO do estado atual do pipeline."""

    running: bool
    paused: bool
    is_active: bool
    is_idle: bool
    is_processing: bool
    current_segment: dict | None
    last_query: str
    last_candidate_id: str
    last_event_type: str
    last_event_timestamp: float
    statistics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "paused": self.paused,
            "is_active": self.is_active,
            "is_idle": self.is_idle,
            "is_processing": self.is_processing,
            "current_segment": self.current_segment,
            "last_query": self.last_query,
            "last_candidate_id": self.last_candidate_id,
            "last_event_type": self.last_event_type,
            "last_event_timestamp": self.last_event_timestamp,
            "statistics": dict(self.statistics),
        }


# ---------------------------------------------------------------------------
# SessionDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionDTO:
    """DTO de uma sessão (sermão)."""

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
    correlation_ids: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "is_active": self.is_active,
            "is_ended": self.is_ended,
            "duration_s": self.duration_s,
            "processed_segments": self.processed_segments,
            "processed_queries": self.processed_queries,
            "presentations": self.presentations,
            "errors": self.errors,
            "error_rate": self.error_rate,
            "presentation_rate": self.presentation_rate,
            "segments_per_minute": self.segments_per_minute,
            "queries_per_minute": self.queries_per_minute,
            "unique_correlations": self.unique_correlations,
            "correlation_ids": list(self.correlation_ids),
        }


# ---------------------------------------------------------------------------
# MetricsDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricsDTO:
    """DTO de métricas do pipeline."""

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

    def to_dict(self) -> dict:
        return {
            "segments_received": self.segments_received,
            "segments_processed": self.segments_processed,
            "segments_dropped": self.segments_dropped,
            "queries_processed": self.queries_processed,
            "presentations_executed": self.presentations_executed,
            "presentations_failed": self.presentations_failed,
            "errors_total": self.errors_total,
            "errors_recoverable": self.errors_recoverable,
            "errors_fatal": self.errors_fatal,
            "total_latency_ms": self.total_latency_ms,
            "avg_latency_ms": self.avg_latency_ms,
            "avg_recognition_latency_ms": self.avg_recognition_latency_ms,
            "avg_search_latency_ms": self.avg_search_latency_ms,
            "avg_ranking_latency_ms": self.avg_ranking_latency_ms,
            "avg_intelligence_latency_ms": self.avg_intelligence_latency_ms,
            "avg_presentation_latency_ms": self.avg_presentation_latency_ms,
            "throughput_segments_per_min": self.throughput_segments_per_min,
            "throughput_queries_per_min": self.throughput_queries_per_min,
            "error_rate": self.error_rate,
            "drop_rate": self.drop_rate,
            "presentation_success_rate": self.presentation_success_rate,
            "processing_success_rate": self.processing_success_rate,
            "duration_s": self.duration_s,
            "correlation_count": self.correlation_count,
        }


# ---------------------------------------------------------------------------
# ConfigurationDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigurationDTO:
    """DTO de configuração do sistema."""

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

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "holyrics": dict(self.holyrics),
            "stt": dict(self.stt),
            "llm": dict(self.llm),
            "search": dict(self.search),
            "state": dict(self.state),
            "cache": dict(self.cache),
            "confidence": dict(self.confidence),
            "log": dict(self.log),
            "audio": dict(self.audio) if self.audio else None,
            "pipeline_policy": dict(self.pipeline_policy) if self.pipeline_policy else None,
        }


# ---------------------------------------------------------------------------
# HealthDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthDTO:
    """DTO de saúde de um componente.

    Atributos:
        component: nome do componente (ex.: "pipeline", "event_bus").
        status: "healthy" | "degraded" | "unhealthy" | "unknown".
        message: mensagem descritiva (ou "").
        details: dict com detalhes extras.
    """

    component: str
    status: str
    message: str = ""
    details: dict = field(default_factory=dict)

    @property
    def is_healthy(self) -> bool:
        return self.status == "healthy"

    @property
    def is_degraded(self) -> bool:
        return self.status == "degraded"

    @property
    def is_unhealthy(self) -> bool:
        return self.status == "unhealthy"

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "status": self.status,
            "message": self.message,
            "details": dict(self.details),
            "is_healthy": self.is_healthy,
        }


# ---------------------------------------------------------------------------
# DiagnosticDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiagnosticDTO:
    """DTO de diagnóstico de um componente.

    Atributos:
        component: nome do componente (ex.: "microphone", "gpu").
        category: categoria (ex.: "hardware", "service", "pipeline").
        available: se o componente está disponível/pronto.
        info: dict com informações de diagnóstico.
        warnings: tuple de avisos.
        errors: tuple de erros.
    """

    component: str
    category: str
    available: bool
    info: dict = field(default_factory=dict)
    warnings: tuple = field(default_factory=tuple)
    errors: tuple = field(default_factory=tuple)

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "category": self.category,
            "available": self.available,
            "info": dict(self.info),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "has_warnings": self.has_warnings,
            "has_errors": self.has_errors,
        }


# ---------------------------------------------------------------------------
# LogDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LogDTO:
    """DTO de entrada de log.

    Atributos:
        timestamp: momento do log.
        level: nível ("DEBUG", "INFO", "WARNING", "ERROR").
        component: componente que gerou o log.
        message: mensagem.
        correlation_id: correlation_id relacionado (ou "").
        session_id: session_id relacionado (ou "").
    """

    timestamp: float
    level: str
    component: str
    message: str
    correlation_id: str = ""
    session_id: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "component": self.component,
            "message": self.message,
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
        }


__all__ = [
    "EventMetadataDTO",
    "EventDTO",
    "PipelineStatusDTO",
    "SessionDTO",
    "MetricsDTO",
    "ConfigurationDTO",
    "HealthDTO",
    "DiagnosticDTO",
    "LogDTO",
]
