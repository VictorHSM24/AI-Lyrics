"""Snapshots — estado do sistema em determinado momento.

Snapshots são imutáveis (frozen dataclass). Representam o estado
do sistema no momento em que foram criados. São a base para
consultas de Dashboard e Replay.

Snapshots:
  - PipelineSnapshot: estado do pipeline + métricas + sessão.
  - SessionSnapshot: sessão ativa.
  - MetricsSnapshot: métricas no momento.
  - HealthSnapshot: saúde de todos os componentes.
  - ConfigurationSnapshot: configuração do sistema.
  - EventSnapshot: eventos em um momento.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from presentation.dtos import (
    ConfigurationDTO,
    EventDTO,
    HealthDTO,
    MetricsDTO,
    PipelineStatusDTO,
    SessionDTO,
)


# ---------------------------------------------------------------------------
# PipelineSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineSnapshot:
    """Snapshot completo do pipeline em um momento.

    Combina status + session + metrics + último evento.
    Imutável. Representa o estado no momento da criação.
    """

    timestamp: float
    status: PipelineStatusDTO
    session: SessionDTO
    metrics: MetricsDTO
    last_event: EventDTO | None = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "status": self.status.to_dict(),
            "session": self.session.to_dict(),
            "metrics": self.metrics.to_dict(),
            "last_event": self.last_event.to_dict() if self.last_event else None,
        }


# ---------------------------------------------------------------------------
# SessionSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionSnapshot:
    """Snapshot de uma sessão em um momento."""

    timestamp: float
    session: SessionDTO

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "session": self.session.to_dict(),
        }


# ---------------------------------------------------------------------------
# MetricsSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricsSnapshot:
    """Snapshot de métricas em um momento."""

    timestamp: float
    metrics: MetricsDTO

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "metrics": self.metrics.to_dict(),
        }


# ---------------------------------------------------------------------------
# HealthSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthSnapshot:
    """Snapshot de saúde de todos os componentes."""

    timestamp: float
    components: tuple  # tuple de HealthDTO

    @property
    def component_count(self) -> int:
        return len(self.components)

    @property
    def healthy_count(self) -> int:
        return sum(1 for c in self.components if c.is_healthy)

    @property
    def unhealthy_count(self) -> int:
        return sum(1 for c in self.components if c.is_unhealthy)

    @property
    def all_healthy(self) -> bool:
        return self.component_count > 0 and self.healthy_count == self.component_count

    def component(self, name: str) -> HealthDTO | None:
        """Retorna HealthDTO de um componente pelo nome (ou None)."""
        for c in self.components:
            if c.component == name:
                return c
        return None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "components": [c.to_dict() for c in self.components],
            "component_count": self.component_count,
            "healthy_count": self.healthy_count,
            "unhealthy_count": self.unhealthy_count,
            "all_healthy": self.all_healthy,
        }


# ---------------------------------------------------------------------------
# ConfigurationSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigurationSnapshot:
    """Snapshot da configuração do sistema."""

    timestamp: float
    configuration: ConfigurationDTO

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "configuration": self.configuration.to_dict(),
        }


# ---------------------------------------------------------------------------
# EventSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EventSnapshot:
    """Snapshot de eventos em um momento.

    Pode conter todos os eventos ou apenas eventos de um
    correlation_id específico (para Replay).
    """

    timestamp: float
    events: tuple  # tuple de EventDTO
    correlation_id: str = ""  # se filtrado por correlation

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def event_types(self) -> tuple:
        return tuple(e.event_type for e in self.events)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "events": [e.to_dict() for e in self.events],
            "event_count": self.event_count,
            "event_types": list(self.event_types),
            "correlation_id": self.correlation_id,
        }


# ---------------------------------------------------------------------------
# SnapshotFactory — helpers para criar snapshots
# ---------------------------------------------------------------------------


class SnapshotFactory:
    """Fábrica de snapshots.

    Métodos estáticos que criam snapshots a partir de objetos do Core.
    Usa Mappers internamente.
    """

    @staticmethod
    def pipeline_snapshot(
        state: object,
        session: object,
        metrics: object,
        last_event: object | None = None,
        timestamp: float | None = None,
    ) -> PipelineSnapshot:
        """Cria PipelineSnapshot a partir de objetos do Core."""
        from presentation.mappers import (
            PipelineMapper, SessionMapper, MetricsMapper, EventMapper,
        )
        return PipelineSnapshot(
            timestamp=timestamp if timestamp is not None else time.time(),
            status=PipelineMapper.to_status_dto(state),
            session=SessionMapper.to_dto(session),
            metrics=MetricsMapper.to_dto(metrics),
            last_event=EventMapper.to_dto(last_event) if last_event else None,
        )

    @staticmethod
    def session_snapshot(
        session: object, timestamp: float | None = None,
    ) -> SessionSnapshot:
        from presentation.mappers import SessionMapper
        return SessionSnapshot(
            timestamp=timestamp if timestamp is not None else time.time(),
            session=SessionMapper.to_dto(session),
        )

    @staticmethod
    def metrics_snapshot(
        metrics: object, timestamp: float | None = None,
    ) -> MetricsSnapshot:
        from presentation.mappers import MetricsMapper
        return MetricsSnapshot(
            timestamp=timestamp if timestamp is not None else time.time(),
            metrics=MetricsMapper.to_dto(metrics),
        )

    @staticmethod
    def health_snapshot(
        health_dtos: tuple, timestamp: float | None = None,
    ) -> HealthSnapshot:
        return HealthSnapshot(
            timestamp=timestamp if timestamp is not None else time.time(),
            components=tuple(health_dtos),
        )

    @staticmethod
    def configuration_snapshot(
        config: object,
        pipeline_policy: object | None = None,
        timestamp: float | None = None,
    ) -> ConfigurationSnapshot:
        from presentation.mappers import ConfigurationMapper
        return ConfigurationSnapshot(
            timestamp=timestamp if timestamp is not None else time.time(),
            configuration=ConfigurationMapper.to_dto(config, pipeline_policy),
        )

    @staticmethod
    def event_snapshot(
        events: tuple,
        correlation_id: str = "",
        timestamp: float | None = None,
    ) -> EventSnapshot:
        """Cria EventSnapshot a partir de tuple de EventDTO."""
        return EventSnapshot(
            timestamp=timestamp if timestamp is not None else time.time(),
            events=tuple(events),
            correlation_id=correlation_id,
        )


__all__ = [
    "PipelineSnapshot",
    "SessionSnapshot",
    "MetricsSnapshot",
    "HealthSnapshot",
    "ConfigurationSnapshot",
    "EventSnapshot",
    "SnapshotFactory",
]
