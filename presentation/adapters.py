"""Adapters — contratos para futuras interfaces.

Adapters definem a interface que futuras tecnologias de
apresentação (REST, WebSocket, CLI, Dashboard, Replay) devem
implementar. Nenhum adapter implementa comunicação real —
somente contratos (ABCs).

Regras:
  - Adapters NUNCA acessam o Core diretamente.
  - Adapters usam exclusivamente Services.
  - Adapters NUNCA modificam estado.
  - Adapters NUNCA publicam eventos.

Adapters:
  - RestAdapter: contrato para API REST.
  - WebSocketAdapter: contrato para WebSocket.
  - CliAdapter: contrato para CLI.
  - DashboardAdapter: contrato para Dashboard.
  - ReplayAdapter: contrato para Replay.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from presentation.dtos import (
    ConfigurationDTO,
    DiagnosticDTO,
    EventDTO,
    HealthDTO,
    LogDTO,
    MetricsDTO,
    PipelineStatusDTO,
    SessionDTO,
)
from presentation.snapshots import (
    ConfigurationSnapshot,
    EventSnapshot,
    HealthSnapshot,
    MetricsSnapshot,
    PipelineSnapshot,
    SessionSnapshot,
)


# ---------------------------------------------------------------------------
# BaseAdapter
# ---------------------------------------------------------------------------


class BaseAdapter(ABC):
    """Base para adapters.

    Adapters recebem Services por injeção. Nunca acessam o Core.
    """

    def __init__(
        self,
        pipeline_service: Any | None = None,
        session_service: Any | None = None,
        metrics_service: Any | None = None,
        configuration_service: Any | None = None,
        health_service: Any | None = None,
        diagnostic_service: Any | None = None,
        event_service: Any | None = None,
    ) -> None:
        self._pipeline = pipeline_service
        self._session = session_service
        self._metrics = metrics_service
        self._configuration = configuration_service
        self._health = health_service
        self._diagnostic = diagnostic_service
        self._event = event_service

    @property
    def pipeline_service(self) -> Any:
        return self._pipeline

    @property
    def session_service(self) -> Any:
        return self._session

    @property
    def metrics_service(self) -> Any:
        return self._metrics

    @property
    def configuration_service(self) -> Any:
        return self._configuration

    @property
    def health_service(self) -> Any:
        return self._health

    @property
    def diagnostic_service(self) -> Any:
        return self._diagnostic

    @property
    def event_service(self) -> Any:
        return self._event


# ---------------------------------------------------------------------------
# RestAdapter — contrato para API REST
# ---------------------------------------------------------------------------


class RestAdapter(BaseAdapter):
    """Contrato para adaptador REST.

    Define endpoints que uma futura API REST deve expor.
    Nenhum endpoint é implementado — apenas contratos.
    """

    @abstractmethod
    def get_pipeline_status(self) -> PipelineStatusDTO:
        """GET /api/pipeline/status"""
        ...

    @abstractmethod
    def get_session(self) -> SessionDTO:
        """GET /api/session"""
        ...

    @abstractmethod
    def get_metrics(self) -> MetricsDTO:
        """GET /api/metrics"""
        ...

    @abstractmethod
    def get_configuration(self) -> ConfigurationDTO:
        """GET /api/configuration"""
        ...

    @abstractmethod
    def get_health(self) -> HealthSnapshot:
        """GET /api/health"""
        ...

    @abstractmethod
    def get_events(self, correlation_id: str = "") -> EventSnapshot:
        """GET /api/events?correlation_id=..."""
        ...

    @abstractmethod
    def get_diagnostics(self) -> tuple:
        """GET /api/diagnostics"""
        ...


# ---------------------------------------------------------------------------
# WebSocketAdapter — contrato para WebSocket
# ---------------------------------------------------------------------------


class WebSocketAdapter(BaseAdapter):
    """Contrato para adaptador WebSocket.

    Define mensagens que um futuro servidor WebSocket deve enviar.
    Nenhuma comunicação é implementada — apenas contratos.
    """

    @abstractmethod
    def serialize_snapshot(self, snapshot: PipelineSnapshot) -> str:
        """Serializa snapshot para envio via WebSocket (JSON string)."""
        ...

    @abstractmethod
    def serialize_event(self, event: EventDTO) -> str:
        """Serializa evento para envio via WebSocket (JSON string)."""
        ...

    @abstractmethod
    def serialize_metrics(self, metrics: MetricsDTO) -> str:
        """Serializa métricas para envio via WebSocket."""
        ...

    @abstractmethod
    def serialize_health(self, health: HealthSnapshot) -> str:
        """Serializa health para envio via WebSocket."""
        ...


# ---------------------------------------------------------------------------
# CliAdapter — contrato para CLI
# ---------------------------------------------------------------------------


class CliAdapter(BaseAdapter):
    """Contrato para adaptador CLI.

    Define comandos que uma futura CLI deve expor.
    Nenhum comando é implementado — apenas contratos.
    """

    @abstractmethod
    def format_status(self, status: PipelineStatusDTO) -> str:
        """Formata status para exibição em terminal."""
        ...

    @abstractmethod
    def format_metrics(self, metrics: MetricsDTO) -> str:
        """Formata métricas para exibição em terminal."""
        ...

    @abstractmethod
    def format_session(self, session: SessionDTO) -> str:
        """Formata sessão para exibição em terminal."""
        ...

    @abstractmethod
    def format_events(self, events: tuple) -> str:
        """Formata eventos para exibição em terminal."""
        ...

    @abstractmethod
    def format_health(self, health: HealthSnapshot) -> str:
        """Formata health para exibição em terminal."""
        ...

    @abstractmethod
    def format_configuration(self, config: ConfigurationDTO) -> str:
        """Formata configuração para exibição em terminal."""
        ...


# ---------------------------------------------------------------------------
# DashboardAdapter — contrato para Dashboard
# ---------------------------------------------------------------------------


class DashboardAdapter(BaseAdapter):
    """Contrato para adaptador Dashboard.

    Define dados que um futuro Dashboard precisa.
    Nenhum dado é implementado — apenas contratos.
    """

    @abstractmethod
    def get_dashboard_data(self) -> dict:
        """Retorna todos os dados necessários para o Dashboard."""
        ...

    @abstractmethod
    def get_session_history(self, session_id: str) -> EventSnapshot:
        """Histórico de eventos de uma sessão."""
        ...

    @abstractmethod
    def get_correlation_flow(self, correlation_id: str) -> EventSnapshot:
        """Fluxo de eventos de um correlation_id."""
        ...


# ---------------------------------------------------------------------------
# ReplayAdapter — contrato para Replay
# ---------------------------------------------------------------------------


class ReplayAdapter(BaseAdapter):
    """Contrato para adaptador Replay.

    Define operações que um futuro ReplayEngine precisa.
    Nenhuma operação é implementada — apenas contratos.
    """

    @abstractmethod
    def get_replay_events(self, correlation_id: str) -> EventSnapshot:
        """Eventos para replay de um fluxo específico."""
        ...

    @abstractmethod
    def get_replay_sessions(self) -> tuple:
        """Lista de session_ids disponíveis para replay."""
        ...

    @abstractmethod
    def get_replay_correlations(self, session_id: str) -> tuple:
        """Lista de correlation_ids de uma sessão."""
        ...


__all__ = [
    "BaseAdapter",
    "RestAdapter",
    "WebSocketAdapter",
    "CliAdapter",
    "DashboardAdapter",
    "ReplayAdapter",
]
