"""Observers — observam eventos do EventBus e atualizam snapshots.

Observers são consumidores do EventBus. Nunca publicam eventos.
Nunca alteram comportamento do Core. Apenas atualizam snapshots
internos para consulta por Services.

Observers:
  - PipelineObserver: observa eventos de ciclo de vida (Started,
    Stopped, Paused, Resumed, Error) e atualiza snapshot de status.
  - EventObserver: observa todos os eventos e mantém histórico.
  - MetricsObserver: observa eventos e atualiza snapshot de métricas.
  - SessionObserver: observa eventos e atualiza snapshot de sessão.

Regras:
  - Observers NUNCA publicam eventos.
  - Observers NUNCA alteram estado do Core.
  - Observers apenas leem eventos e atualizam snapshots internos.
"""

from __future__ import annotations

import time
from typing import Any

from presentation.dtos import EventDTO, HealthDTO
from presentation.mappers import EventMapper, HealthMapper, LogMapper
from presentation.snapshots import (
    EventSnapshot,
    HealthSnapshot,
    MetricsSnapshot,
    PipelineSnapshot,
    SessionSnapshot,
)


# ---------------------------------------------------------------------------
# BaseObserver
# ---------------------------------------------------------------------------


class BaseObserver:
    """Base para observers.

    Observers se inscrevem no EventBus para tipos específicos de
    evento. Quando um evento ocorre, o callback `on_event` é
    chamado. O observer atualiza seu snapshot interno.
    """

    def __init__(self) -> None:
        self._last_snapshot: Any = None

    @property
    def last_snapshot(self) -> Any:
        """Último snapshot produzido (ou None)."""
        return self._last_snapshot

    def on_event(self, event: Any) -> None:
        """Callback chamado quando um evento é publicado.

        Deve ser sobrescrito por subclasses.
        """
        ...

    def subscribe_to(self, bus: Any) -> None:
        """Inscreve este observer no EventBus para todos os tipos.

        Subclasses podem sobrescrever para inscrever apenas em
        tipos específicos.
        """
        from pipeline.events import all_event_types
        for event_type in all_event_types():
            bus.subscribe(event_type, self.on_event)


# ---------------------------------------------------------------------------
# EventObserver
# ---------------------------------------------------------------------------


class EventObserver(BaseObserver):
    """Observa todos os eventos e mantém histórico de EventDTOs.

    Útil para Replay e Dashboard (histórico de eventos).
    """

    def __init__(self, max_events: int = 10000) -> None:
        super().__init__()
        self._events: list[EventDTO] = []
        self._max_events = max_events

    def on_event(self, event: Any) -> None:
        dto = EventMapper.to_dto(event)
        self._events.append(dto)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
        self._last_snapshot = EventSnapshot(
            timestamp=time.time(),
            events=tuple(self._events),
        )

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def events(self) -> tuple:
        return tuple(self._events)

    def events_by_correlation(self, correlation_id: str) -> tuple:
        """Retorna eventos de um correlation_id específico."""
        return tuple(e for e in self._events if e.correlation_id == correlation_id)

    def events_by_type(self, event_type: str) -> tuple:
        """Retorna eventos de um tipo específico."""
        return tuple(e for e in self._events if e.event_type == event_type)

    def last_event(self) -> EventDTO | None:
        """Último evento recebido (ou None)."""
        return self._events[-1] if self._events else None

    def snapshot(self) -> EventSnapshot:
        """Retorna snapshot atual dos eventos."""
        if self._last_snapshot is None:
            return EventSnapshot(timestamp=time.time(), events=())
        return self._last_snapshot

    def clear(self) -> None:
        """Limpa o histórico de eventos."""
        self._events.clear()
        self._last_snapshot = None


# ---------------------------------------------------------------------------
# PipelineObserver
# ---------------------------------------------------------------------------


class PipelineObserver(BaseObserver):
    """Observa eventos de ciclo de vida do pipeline.

    Atualiza um snapshot de status baseado em eventos:
      - PipelineStarted → running=True
      - PipelineStopped → running=False
      - PipelinePaused → paused=True
      - PipelineResumed → paused=False
      - PipelineError → registra erro
    """

    def __init__(self) -> None:
        super().__init__()
        self._running: bool = False
        self._paused: bool = False
        self._errors: list[EventDTO] = []
        self._last_event: EventDTO | None = None

    def on_event(self, event: Any) -> None:
        dto = EventMapper.to_dto(event)
        self._last_event = dto
        if dto.event_type == "PipelineStarted":
            self._running = True
            self._paused = False
        elif dto.event_type == "PipelineStopped":
            self._running = False
            self._paused = False
        elif dto.event_type == "PipelinePaused":
            self._paused = True
        elif dto.event_type == "PipelineResumed":
            self._paused = False
        elif dto.event_type == "PipelineError":
            self._errors.append(dto)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def is_active(self) -> bool:
        return self._running and not self._paused

    @property
    def error_count(self) -> int:
        return len(self._errors)

    @property
    def last_event(self) -> EventDTO | None:
        return self._last_event

    @property
    def errors(self) -> tuple:
        return tuple(self._errors)

    def health(self) -> HealthDTO:
        """Retorna HealthDTO do pipeline baseado no estado observado."""
        if self._running and not self._paused:
            return HealthMapper.healthy("pipeline", "Pipeline running")
        if self._paused:
            return HealthMapper.degraded("pipeline", "Pipeline paused")
        return HealthMapper.unhealthy("pipeline", "Pipeline stopped")

    def reset(self) -> None:
        self._running = False
        self._paused = False
        self._errors.clear()
        self._last_event = None
        self._last_snapshot = None


# ---------------------------------------------------------------------------
# MetricsObserver
# ---------------------------------------------------------------------------


class MetricsObserver(BaseObserver):
    """Observa eventos e mantém contadores agregados.

    Conta eventos por tipo. Útil para Dashboard (estatísticas
    em tempo real sem acessar PipelineMetrics diretamente).
    """

    def __init__(self) -> None:
        super().__init__()
        self._counts_by_type: dict[str, int] = {}
        self._total_events: int = 0
        self._started_at: float = time.time()

    def on_event(self, event: Any) -> None:
        dto = EventMapper.to_dto(event)
        self._total_events += 1
        self._counts_by_type[dto.event_type] = (
            self._counts_by_type.get(dto.event_type, 0) + 1
        )

    @property
    def total_events(self) -> int:
        return self._total_events

    @property
    def counts_by_type(self) -> dict:
        return dict(self._counts_by_type)

    @property
    def event_types(self) -> tuple:
        return tuple(self._counts_by_type.keys())

    def count_for(self, event_type: str) -> int:
        return self._counts_by_type.get(event_type, 0)

    @property
    def duration_s(self) -> float:
        return max(0.0, time.time() - self._started_at)

    @property
    def events_per_minute(self) -> float:
        duration = self.duration_s
        if duration <= 0:
            return 0.0
        return (self._total_events / duration) * 60.0

    def reset(self) -> None:
        self._counts_by_type.clear()
        self._total_events = 0
        self._started_at = time.time()
        self._last_snapshot = None


# ---------------------------------------------------------------------------
# SessionObserver
# ---------------------------------------------------------------------------


class SessionObserver(BaseObserver):
    """Observa eventos e mantém estatísticas por sessão.

    Rastreia sessões ativas e suas estatísticas.
    """

    def __init__(self) -> None:
        super().__init__()
        self._session_events: dict[str, list[EventDTO]] = {}
        self._current_session_id: str = ""

    def on_event(self, event: Any) -> None:
        dto = EventMapper.to_dto(event)
        sid = dto.session_id
        if sid not in self._session_events:
            self._session_events[sid] = []
        self._session_events[sid].append(dto)
        self._current_session_id = sid

    @property
    def current_session_id(self) -> str:
        return self._current_session_id

    @property
    def session_ids(self) -> tuple:
        return tuple(self._session_events.keys())

    @property
    def session_count(self) -> int:
        return len(self._session_events)

    def events_for_session(self, session_id: str) -> tuple:
        return tuple(self._session_events.get(session_id, ()))

    def event_count_for_session(self, session_id: str) -> int:
        return len(self._session_events.get(session_id, []))

    def reset(self) -> None:
        self._session_events.clear()
        self._current_session_id = ""
        self._last_snapshot = None


__all__ = [
    "BaseObserver",
    "EventObserver",
    "PipelineObserver",
    "MetricsObserver",
    "SessionObserver",
]
