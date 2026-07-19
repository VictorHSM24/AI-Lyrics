"""Mappers — convertem objetos do Core em DTOs de apresentação.

Regra fundamental: NUNCA converter no sentido inverso.
Estes mappers são one-way: Core → Presentation DTO.

Cada Mapper possui responsabilidade única. Nenhum Mapper altera
estado. Nenhum Mapper implementa regra de negócio.

Mappers:
  - PipelineMapper: PipelineState → PipelineStatusDTO.
  - SessionMapper: PipelineSession → SessionDTO.
  - MetricsMapper: PipelineMetrics → MetricsDTO.
  - EventMapper: PipelineEvent → EventDTO.
  - EvidenceMapper: Evidence → EvidenceDTO.
  - SignalMapper: IntelligenceSignal → SignalDTO.
  - RecommendationMapper: IntelligenceRecommendation → RecommendationDTO.
  - CandidateMapper: CandidateInfo → CandidateDTO.
  - ConfigurationMapper: Config → ConfigurationDTO.
  - HealthMapper: constrói HealthDTO.
  - DiagnosticMapper: constrói DiagnosticDTO.
"""

from __future__ import annotations

from typing import Any

from presentation.dtos import (
    ConfigurationDTO,
    DiagnosticDTO,
    EventDTO,
    EventMetadataDTO,
    HealthDTO,
    LogDTO,
    MetricsDTO,
    PipelineStatusDTO,
    SessionDTO,
)
from presentation.dtos_domain import (
    CandidateDTO,
    EvidenceDTO,
    PresentationDTO,
    RecommendationDTO,
    ScoreDTO,
    SignalDTO,
)


# ---------------------------------------------------------------------------
# PipelineMapper
# ---------------------------------------------------------------------------


class PipelineMapper:
    """Mapeia PipelineState → PipelineStatusDTO."""

    @staticmethod
    def to_status_dto(state: Any) -> PipelineStatusDTO:
        """Converte PipelineState em PipelineStatusDTO."""
        current_segment_dict = None
        if state.current_segment is not None:
            cs = state.current_segment
            if hasattr(cs, "to_dict"):
                current_segment_dict = cs.to_dict()
            else:
                current_segment_dict = {"value": str(cs)}
        return PipelineStatusDTO(
            running=state.running,
            paused=state.paused,
            is_active=state.is_active,
            is_idle=state.is_idle,
            is_processing=state.is_processing,
            current_segment=current_segment_dict,
            last_query=state.last_query,
            last_candidate_id=state.last_candidate_id,
            last_event_type=state.last_event_type,
            last_event_timestamp=state.last_event_timestamp,
            statistics=dict(state.statistics) if state.statistics else {},
        )


# ---------------------------------------------------------------------------
# SessionMapper
# ---------------------------------------------------------------------------


class SessionMapper:
    """Mapeia PipelineSession → SessionDTO."""

    @staticmethod
    def to_dto(session: Any) -> SessionDTO:
        return SessionDTO(
            session_id=session.session_id,
            started_at=session.started_at,
            ended_at=session.ended_at,
            is_active=session.is_active,
            is_ended=session.is_ended,
            duration_s=session.duration_s,
            processed_segments=session.processed_segments,
            processed_queries=session.processed_queries,
            presentations=session.presentations,
            errors=session.errors,
            error_rate=session.error_rate,
            presentation_rate=session.presentation_rate,
            segments_per_minute=session.segments_per_minute,
            queries_per_minute=session.queries_per_minute,
            unique_correlations=session.unique_correlations,
            correlation_ids=tuple(session.correlation_ids),
        )


# ---------------------------------------------------------------------------
# MetricsMapper
# ---------------------------------------------------------------------------


class MetricsMapper:
    """Mapeia PipelineMetrics → MetricsDTO."""

    @staticmethod
    def to_dto(metrics: Any) -> MetricsDTO:
        return MetricsDTO(
            segments_received=metrics.segments_received,
            segments_processed=metrics.segments_processed,
            segments_dropped=metrics.segments_dropped,
            queries_processed=metrics.queries_processed,
            presentations_executed=metrics.presentations_executed,
            presentations_failed=metrics.presentations_failed,
            errors_total=metrics.errors_total,
            errors_recoverable=metrics.errors_recoverable,
            errors_fatal=metrics.errors_fatal,
            total_latency_ms=metrics.total_latency_ms,
            avg_latency_ms=metrics.avg_latency_ms,
            avg_recognition_latency_ms=metrics.avg_recognition_latency_ms,
            avg_search_latency_ms=metrics.avg_search_latency_ms,
            avg_ranking_latency_ms=metrics.avg_ranking_latency_ms,
            avg_intelligence_latency_ms=metrics.avg_intelligence_latency_ms,
            avg_presentation_latency_ms=metrics.avg_presentation_latency_ms,
            throughput_segments_per_min=metrics.throughput_segments_per_min,
            throughput_queries_per_min=metrics.throughput_queries_per_min,
            error_rate=metrics.error_rate,
            drop_rate=metrics.drop_rate,
            presentation_success_rate=metrics.presentation_success_rate,
            processing_success_rate=metrics.processing_success_rate,
            duration_s=metrics.duration_s,
            correlation_count=metrics.correlation_count,
        )


# ---------------------------------------------------------------------------
# EventMapper
# ---------------------------------------------------------------------------


class EventMapper:
    """Mapeia PipelineEvent → EventDTO."""

    @staticmethod
    def to_metadata_dto(meta: Any) -> EventMetadataDTO:
        return EventMetadataDTO(
            event_id=meta.event_id,
            correlation_id=meta.correlation_id,
            causation_id=meta.causation_id,
            session_id=meta.session_id,
            timestamp=meta.timestamp,
            origin=meta.origin,
            metadata=tuple(meta.metadata) if meta.metadata else (),
        )

    @staticmethod
    def to_dto(event: Any) -> EventDTO:
        meta_dto = EventMapper.to_metadata_dto(event.meta)
        # Extrair payload (campos específicos, exceto meta)
        payload = {}
        if hasattr(event, "__dataclass_fields__"):
            for fname in event.__dataclass_fields__:
                if fname == "meta":
                    continue
                val = getattr(event, fname)
                if hasattr(val, "to_dict"):
                    payload[fname] = val.to_dict()
                elif isinstance(val, (list, tuple)):
                    payload[fname] = [
                        v.to_dict() if hasattr(v, "to_dict") else v
                        for v in val
                    ]
                else:
                    payload[fname] = val
        return EventDTO(
            event_type=event.event_type,
            meta=meta_dto,
            payload=payload,
        )

    @staticmethod
    def to_dto_many(events: Any) -> tuple:
        """Converte iterável de eventos em tuple de EventDTO."""
        return tuple(EventMapper.to_dto(e) for e in events)


# ---------------------------------------------------------------------------
# EvidenceMapper
# ---------------------------------------------------------------------------


class EvidenceMapper:
    """Mapeia Evidence → EvidenceDTO."""

    @staticmethod
    def to_dto(evidence: Any) -> EvidenceDTO:
        ev_type = evidence.type
        type_str = ev_type.value if hasattr(ev_type, "value") else str(ev_type)
        return EvidenceDTO(
            id=evidence.id,
            type=type_str,
            description=evidence.description,
            value=evidence.value,
            weight=evidence.weight,
            confidence=evidence.confidence,
            contribution=evidence.contribution,
            metadata=tuple(evidence.metadata) if evidence.metadata else (),
            timestamp=evidence.timestamp,
        )

    @staticmethod
    def to_dto_many(evidences: Any) -> tuple:
        return tuple(EvidenceMapper.to_dto(e) for e in evidences)


# ---------------------------------------------------------------------------
# SignalMapper
# ---------------------------------------------------------------------------


class SignalMapper:
    """Mapeia IntelligenceSignal → SignalDTO."""

    @staticmethod
    def to_dto(signal: Any) -> SignalDTO:
        return SignalDTO(
            signal_type=signal.signal_type,
            value=signal.value,
            weight=signal.weight,
            contribution=signal.contribution,
            explanation=signal.explanation,
            evidences=EvidenceMapper.to_dto_many(signal.evidences),
        )

    @staticmethod
    def to_dto_many(signals: Any) -> tuple:
        return tuple(SignalMapper.to_dto(s) for s in signals)


# ---------------------------------------------------------------------------
# ScoreMapper (interno)
# ---------------------------------------------------------------------------


class ScoreMapper:
    """Mapeia IntelligenceScore → ScoreDTO."""

    @staticmethod
    def to_dto(score: Any) -> ScoreDTO:
        conf = score.confidence_level
        conf_str = conf.value if hasattr(conf, "value") else str(conf)
        return ScoreDTO(
            candidate_id=score.candidate_id,
            base_score=score.base_score,
            final_score=score.final_score,
            context_contribution=score.context_contribution,
            feedback_contribution=score.feedback_contribution,
            continuity_contribution=score.continuity_contribution,
            reference_contribution=score.reference_contribution,
            theme_contribution=score.theme_contribution,
            book_contribution=score.book_contribution,
            confidence_contribution=score.confidence_contribution,
            evaluation_contribution=score.evaluation_contribution,
            confidence_level=conf_str,
            signals=SignalMapper.to_dto_many(score.signals),
            explanation=score.explanation,
        )

    @staticmethod
    def to_dto_many(scores: Any) -> tuple:
        return tuple(ScoreMapper.to_dto(s) for s in scores)


# ---------------------------------------------------------------------------
# RecommendationMapper
# ---------------------------------------------------------------------------


class RecommendationMapper:
    """Mapeia IntelligenceRecommendation → RecommendationDTO."""

    @staticmethod
    def to_dto(rec: Any) -> RecommendationDTO:
        conf = rec.confidence_level
        conf_str = conf.value if hasattr(conf, "value") else str(conf)
        return RecommendationDTO(
            query=rec.query,
            best_candidate_id=rec.best_candidate_id,
            confidence_level=conf_str,
            explanation=rec.explanation,
            has_candidates=rec.has_candidates,
            scores=ScoreMapper.to_dto_many(rec.scores),
            ranking=tuple(rec.ranking),
        )


# ---------------------------------------------------------------------------
# CandidateMapper
# ---------------------------------------------------------------------------


class CandidateMapper:
    """Mapeia CandidateInfo → CandidateDTO."""

    @staticmethod
    def to_dto(candidate: Any) -> CandidateDTO:
        return CandidateDTO(
            candidate_id=candidate.candidate_id,
            base_score=candidate.base_score,
            book=candidate.book,
            chapter=candidate.chapter,
            verse=candidate.verse,
            display=candidate.display,
        )

    @staticmethod
    def to_dto_many(candidates: Any) -> tuple:
        return tuple(CandidateMapper.to_dto(c) for c in candidates)


# ---------------------------------------------------------------------------
# PresentationMapper
# ---------------------------------------------------------------------------


class PresentationMapper:
    """Mapeia PresentationRequested/PresentationCompleted → PresentationDTO."""

    @staticmethod
    def from_requested(event: Any) -> PresentationDTO:
        return PresentationDTO(
            candidate_id=event.candidate_id,
            book_id=event.book_id,
            chapter=event.chapter,
            verse=event.verse,
            version=event.version,
        )

    @staticmethod
    def from_completed(event: Any) -> PresentationDTO:
        return PresentationDTO(
            candidate_id=event.candidate_id,
            book_id=0,
            chapter=0,
            verse=None,
            version="",
            status=getattr(event, "status", ""),
            verse_id=getattr(event, "verse_id", ""),
            presented=getattr(event, "presented", False),
        )


# ---------------------------------------------------------------------------
# ConfigurationMapper
# ---------------------------------------------------------------------------


class ConfigurationMapper:
    """Mapeia Config → ConfigurationDTO."""

    @staticmethod
    def _to_dict(obj: Any) -> dict:
        if obj is None:
            return {}
        if hasattr(obj, "__dataclass_fields__"):
            return {
                f: getattr(obj, f)
                for f in obj.__dataclass_fields__
            }
        if isinstance(obj, dict):
            return dict(obj)
        return {}

    @staticmethod
    def to_dto(config: Any, pipeline_policy: Any = None) -> ConfigurationDTO:
        audio_dict = None
        if getattr(config, "audio", None) is not None:
            audio_dict = ConfigurationMapper._to_dict(config.audio)
        policy_dict = None
        if pipeline_policy is not None:
            policy_dict = ConfigurationMapper._to_dict(pipeline_policy)
        return ConfigurationDTO(
            mode=getattr(config, "mode", ""),
            holyrics=ConfigurationMapper._to_dict(getattr(config, "holyrics", None)),
            stt=ConfigurationMapper._to_dict(getattr(config, "stt", None)),
            llm=ConfigurationMapper._to_dict(getattr(config, "llm", None)),
            search=ConfigurationMapper._to_dict(getattr(config, "search", None)),
            state=ConfigurationMapper._to_dict(getattr(config, "state", None)),
            cache=ConfigurationMapper._to_dict(getattr(config, "cache", None)),
            confidence=ConfigurationMapper._to_dict(getattr(config, "confidence", None)),
            log=ConfigurationMapper._to_dict(getattr(config, "log", None)),
            audio=audio_dict,
            pipeline_policy=policy_dict,
        )


# ---------------------------------------------------------------------------
# HealthMapper
# ---------------------------------------------------------------------------


class HealthMapper:
    """Constrói HealthDTO para componentes."""

    @staticmethod
    def healthy(component: str, message: str = "", details: dict | None = None) -> HealthDTO:
        return HealthDTO(
            component=component,
            status="healthy",
            message=message,
            details=details or {},
        )

    @staticmethod
    def degraded(component: str, message: str = "", details: dict | None = None) -> HealthDTO:
        return HealthDTO(
            component=component,
            status="degraded",
            message=message,
            details=details or {},
        )

    @staticmethod
    def unhealthy(component: str, message: str = "", details: dict | None = None) -> HealthDTO:
        return HealthDTO(
            component=component,
            status="unhealthy",
            message=message,
            details=details or {},
        )

    @staticmethod
    def unknown(component: str, message: str = "", details: dict | None = None) -> HealthDTO:
        return HealthDTO(
            component=component,
            status="unknown",
            message=message,
            details=details or {},
        )

    @staticmethod
    def from_state(component: str, running: bool, message: str = "") -> HealthDTO:
        """Constrói HealthDTO a partir de estado booleano."""
        if running:
            return HealthMapper.healthy(component, message)
        return HealthMapper.unhealthy(component, message or "not running")


# ---------------------------------------------------------------------------
# DiagnosticMapper
# ---------------------------------------------------------------------------


class DiagnosticMapper:
    """Constrói DiagnosticDTO para componentes."""

    @staticmethod
    def to_dto(
        component: str,
        category: str,
        available: bool,
        info: dict | None = None,
        warnings: tuple = (),
        errors: tuple = (),
    ) -> DiagnosticDTO:
        return DiagnosticDTO(
            component=component,
            category=category,
            available=available,
            info=info or {},
            warnings=warnings,
            errors=errors,
        )


# ---------------------------------------------------------------------------
# LogMapper
# ---------------------------------------------------------------------------


class LogMapper:
    """Constrói LogDTO."""

    @staticmethod
    def to_dto(
        timestamp: float,
        level: str,
        component: str,
        message: str,
        correlation_id: str = "",
        session_id: str = "",
    ) -> LogDTO:
        return LogDTO(
            timestamp=timestamp,
            level=level,
            component=component,
            message=message,
            correlation_id=correlation_id,
            session_id=session_id,
        )

    @staticmethod
    def from_event(event: Any, level: str = "INFO") -> LogDTO:
        """Constrói LogDTO a partir de um evento do pipeline."""
        return LogDTO(
            timestamp=event.timestamp,
            level=level,
            component=event.origin,
            message=f"{event.event_type}",
            correlation_id=event.correlation_id,
            session_id=event.session_id,
        )


__all__ = [
    "PipelineMapper",
    "SessionMapper",
    "MetricsMapper",
    "EventMapper",
    "EvidenceMapper",
    "SignalMapper",
    "ScoreMapper",
    "RecommendationMapper",
    "CandidateMapper",
    "PresentationMapper",
    "ConfigurationMapper",
    "HealthMapper",
    "DiagnosticMapper",
    "LogMapper",
]
