"""Services — camada de serviço somente leitura.

Services são a única porta de entrada para futuras interfaces
(REST, WebSocket, CLI, Dashboard, Replay). Eles consultam o Core
e retornam DTOs/Snapshots.

Regras:
  - Services NUNCA modificam estado do Core.
  - Services NUNCA executam regra de negócio.
  - Services NUNCA publicam eventos.
  - Services apenas consultam e adaptam via Mappers.

Services:
  - PipelinePresentationService: estado do pipeline.
  - SessionPresentationService: sessão ativa.
  - MetricsPresentationService: métricas.
  - ConfigurationPresentationService: configuração.
  - HealthPresentationService: saúde dos componentes.
  - DiagnosticPresentationService: diagnósticos.
  - EventPresentationService: eventos e histórico.
"""

from __future__ import annotations

import time
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
from presentation.mappers import (
    ConfigurationMapper,
    DiagnosticMapper,
    EventMapper,
    HealthMapper,
    LogMapper,
    MetricsMapper,
    PipelineMapper,
    SessionMapper,
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
# PipelinePresentationService
# ---------------------------------------------------------------------------


class PipelinePresentationService:
    """Service para consultar estado do pipeline.

    Recebe referências a PipelineState, PipelineSession e
    PipelineMetrics (apenas leitura).
    """

    def __init__(
        self,
        state: Any,
        session: Any,
        metrics: Any,
        bus: Any | None = None,
    ) -> None:
        self._state = state
        self._session = session
        self._metrics = metrics
        self._bus = bus

    def get_status(self) -> PipelineStatusDTO:
        """Retorna DTO do estado atual do pipeline."""
        return PipelineMapper.to_status_dto(self._state)

    def get_session(self) -> SessionDTO:
        """Retorna DTO da sessão atual."""
        return SessionMapper.to_dto(self._session)

    def get_metrics(self) -> MetricsDTO:
        """Retorna DTO das métricas atuais."""
        return MetricsMapper.to_dto(self._metrics)

    def get_snapshot(self) -> PipelineSnapshot:
        """Retorna snapshot completo do pipeline."""
        last_event = None
        if self._bus is not None:
            history = self._bus.history()
            if history:
                last_event = history[-1]
        return PipelineSnapshot(
            timestamp=time.time(),
            status=self.get_status(),
            session=self.get_session(),
            metrics=self.get_metrics(),
            last_event=EventMapper.to_dto(last_event) if last_event else None,
        )

    def is_running(self) -> bool:
        """True se o pipeline está rodando."""
        return bool(self._state.running)

    def is_paused(self) -> bool:
        """True se o pipeline está pausado."""
        return bool(self._state.paused)

    def is_active(self) -> bool:
        """True se o pipeline está ativo (rodando e não pausado)."""
        return self.is_running() and not self.is_paused()


# ---------------------------------------------------------------------------
# SessionPresentationService
# ---------------------------------------------------------------------------


class SessionPresentationService:
    """Service para consultar sessões."""

    def __init__(self, session: Any) -> None:
        self._session = session

    def get_session(self) -> SessionDTO:
        """Retorna DTO da sessão."""
        return SessionMapper.to_dto(self._session)

    def get_snapshot(self) -> SessionSnapshot:
        """Retorna snapshot da sessão."""
        return SessionSnapshot(
            timestamp=time.time(),
            session=self.get_session(),
        )

    @property
    def session_id(self) -> str:
        return self._session.session_id

    @property
    def is_active(self) -> bool:
        return self._session.is_active

    @property
    def duration_s(self) -> float:
        return self._session.duration_s

    @property
    def processed_segments(self) -> int:
        return self._session.processed_segments

    @property
    def processed_queries(self) -> int:
        return self._session.processed_queries

    @property
    def presentations(self) -> int:
        return self._session.presentations

    @property
    def errors(self) -> int:
        return self._session.errors

    def has_correlation(self, correlation_id: str) -> bool:
        return self._session.has_correlation(correlation_id)


# ---------------------------------------------------------------------------
# MetricsPresentationService
# ---------------------------------------------------------------------------


class MetricsPresentationService:
    """Service para consultar métricas."""

    def __init__(self, metrics: Any) -> None:
        self._metrics = metrics

    def get_metrics(self) -> MetricsDTO:
        """Retorna DTO das métricas."""
        return MetricsMapper.to_dto(self._metrics)

    def get_snapshot(self) -> MetricsSnapshot:
        """Retorna snapshot das métricas."""
        return MetricsSnapshot(
            timestamp=time.time(),
            metrics=self.get_metrics(),
        )

    @property
    def segments_received(self) -> int:
        return self._metrics.segments_received

    @property
    def segments_processed(self) -> int:
        return self._metrics.segments_processed

    @property
    def avg_latency_ms(self) -> float:
        return self._metrics.avg_latency_ms

    @property
    def throughput_segments_per_min(self) -> float:
        return self._metrics.throughput_segments_per_min

    @property
    def error_rate(self) -> float:
        return self._metrics.error_rate


# ---------------------------------------------------------------------------
# ConfigurationPresentationService
# ---------------------------------------------------------------------------


class ConfigurationPresentationService:
    """Service para consultar e atualizar configuração.

    Sprint 14: adiciona update_configuration() que persiste
    overrides em disco e atualiza a config em memória.
    """

    def __init__(
        self,
        config: Any,
        pipeline_policy: Any | None = None,
        overrides_path: str = "config/config.overrides.json",
    ) -> None:
        self._config = config
        self._pipeline_policy = pipeline_policy
        self._overrides_path = overrides_path
        self._overrides: dict = {}

    def get_configuration(self) -> ConfigurationDTO:
        """Retorna DTO da configuração."""
        return ConfigurationMapper.to_dto(self._config, self._pipeline_policy)

    def get_snapshot(self) -> ConfigurationSnapshot:
        """Retorna snapshot da configuração."""
        return ConfigurationSnapshot(
            timestamp=time.time(),
            configuration=self.get_configuration(),
        )

    def update_configuration(self, overrides: dict) -> ConfigurationDTO:
        """Aplica overrides na configuração e persiste em disco.

        Args:
            overrides: dict com chaves válidas (holyrics, stt, llm, etc.).

        Returns:
            ConfigurationDTO atualizada.

        Raises:
            ValueError: se overrides contiver chaves inválidas.
        """
        from config.persistence import (
            save_overrides,
            validate_overrides,
            merge_overrides,
        )

        errors = validate_overrides(overrides)
        if errors:
            raise ValueError("; ".join(errors))

        # Mescla overrides acumulados.
        self._overrides = merge_overrides(self._overrides, overrides)

        # Persistir em disco.
        save_overrides(self._overrides, self._overrides_path)

        # Aplicar overrides na config em memória (criar nova SimpleNamespace).
        self._config = _apply_overrides(self._config, overrides)

        return self.get_configuration()

    @property
    def mode(self) -> str:
        return getattr(self._config, "mode", "")

    @property
    def stt_model(self) -> str:
        stt = getattr(self._config, "stt", None)
        return getattr(stt, "model", "") if stt else ""

    @property
    def llm_model(self) -> str:
        llm = getattr(self._config, "llm", None)
        return getattr(llm, "model", "") if llm else ""


def _apply_overrides(config: Any, overrides: dict) -> Any:
    """Aplica overrides a uma config (SimpleNamespace ou dataclass).

    Cria uma nova SimpleNamespace com os valores mesclados.
    Não modifica a config original.
    """
    from types import SimpleNamespace
    from dataclasses import asdict, is_dataclass

    # Converter config para dict.
    if is_dataclass(config):
        base = asdict(config)
    elif isinstance(config, SimpleNamespace):
        base = vars(config).copy()
    elif isinstance(config, dict):
        base = dict(config)
    else:
        base = {}

    # Mesclar overrides (deep merge).
    from config.persistence import merge_overrides
    merged = merge_overrides(base, overrides)

    # Converter dicts aninhados de volta para SimpleNamespace.
    def to_namespace(d: Any) -> Any:
        if isinstance(d, dict):
            return SimpleNamespace(**{k: to_namespace(v) for k, v in d.items()})
        return d

    return to_namespace(merged)


# ---------------------------------------------------------------------------
# HealthPresentationService
# ---------------------------------------------------------------------------


class HealthPresentationService:
    """Service para consultar saúde dos componentes.

    Constrói HealthDTOs a partir do estado observado.
    Verificações reais (Sprint 14 + Sprint 15.2) para todos os componentes:
    Backend, WebSocket, EventStream, Pipeline, Microfone, STT, Searcher,
    Ranking, Intelligence e Holyrics.
    """

    def __init__(
        self,
        pipeline_state: Any | None = None,
        bus: Any | None = None,
        store: Any | None = None,
        stt: Any | None = None,
        searcher: Any | None = None,
        stt_config: Any | None = None,
        search_config: Any | None = None,
        llm_config: Any | None = None,
        holyrics_config: Any | None = None,
        holyrics_client: Any | None = None,
        audio_capture: Any | None = None,
        audio_config: Any | None = None,
        ws_server: Any | None = None,
        ws_client_count: int = 0,
    ) -> None:
        self._pipeline_state = pipeline_state
        self._bus = bus
        self._store = store
        self._stt = stt
        self._searcher = searcher
        self._stt_config = stt_config
        self._search_config = search_config
        self._llm_config = llm_config
        self._holyrics_config = holyrics_config
        self._holyrics_client = holyrics_client
        self._audio_capture = audio_capture
        self._audio_config = audio_config
        self._ws_server = ws_server
        self._ws_client_count = ws_client_count

    def backend_health(self) -> HealthDTO:
        """Saúde do backend (sempre saudável se o endpoint responde)."""
        from presentation.health_checks import check_backend_health
        return check_backend_health()

    def websocket_health(self) -> HealthDTO:
        """Saúde do WebSocket (verificação real)."""
        from presentation.health_checks import check_websocket_health
        return check_websocket_health(
            ws_server=self._ws_server,
            connected_clients=self._ws_client_count,
        )

    def eventstream_health(self) -> HealthDTO:
        """Saúde do EventStream (verificação real)."""
        from presentation.health_checks import check_eventstream_health
        return check_eventstream_health(bus=self._bus)

    def pipeline_health(self) -> HealthDTO:
        """Saúde do pipeline."""
        if self._pipeline_state is None:
            return HealthMapper.unknown("pipeline", "state not available")
        if self._pipeline_state.is_active:
            return HealthMapper.healthy("pipeline", "Pipeline em execução")
        if self._pipeline_state.paused:
            return HealthMapper.degraded("pipeline", "Pipeline pausado")
        return HealthMapper.unhealthy("pipeline", "Pipeline parado")

    def microphone_health(self) -> HealthDTO:
        """Saúde do Microfone (verificação real)."""
        from presentation.health_checks import check_microphone_health
        return check_microphone_health(
            capture_service=self._audio_capture,
            audio_config=self._audio_config,
        )

    def event_bus_health(self) -> HealthDTO:
        """Saúde do EventBus."""
        if self._bus is None:
            return HealthMapper.unknown("event_bus", "bus not available")
        return HealthMapper.healthy(
            "event_bus", "EventBus operational",
            {"event_count": self._bus.event_count()},
        )

    def event_store_health(self) -> HealthDTO:
        """Saúde do EventStore."""
        if self._store is None:
            return HealthMapper.unknown("event_store", "store not available")
        return HealthMapper.healthy(
            "event_store", "EventStore operational",
            {"count": self._store.count()},
        )

    def speech_recognition_health(self) -> HealthDTO:
        """Saúde do Speech Recognition (verificação real)."""
        from presentation.health_checks import check_stt_health
        return check_stt_health(stt=self._stt, config=self._stt_config)

    def searcher_health(self) -> HealthDTO:
        """Saúde do Searcher (verificação real)."""
        from presentation.health_checks import check_searcher_health
        return check_searcher_health(searcher=self._searcher, config=self._search_config)

    def ranking_health(self) -> HealthDTO:
        """Saúde do Ranking (verificação real)."""
        from presentation.health_checks import check_ranking_health
        return check_ranking_health(config=self._search_config)

    def intelligence_health(self) -> HealthDTO:
        """Saúde do Intelligence (verificação real)."""
        from presentation.health_checks import check_intelligence_health
        return check_intelligence_health(config=self._llm_config)

    def holyrics_health(self) -> HealthDTO:
        """Saúde do Holyrics (verificação real)."""
        from presentation.health_checks import check_holyrics_health
        return check_holyrics_health(client=self._holyrics_client, config=self._holyrics_config)

    def all_components(self) -> tuple:
        """Retorna tuple com HealthDTO de todos os componentes.

        Ordem alinhada com o frontend HealthPanel:
        backend, presentation, websocket, eventstream, pipeline,
        microphone, stt, bible, holyrics.
        Componentes extras (event_bus, event_store, ranking, intelligence)
        são incluídos para completude.
        """
        return (
            self.backend_health(),
            self.websocket_health(),
            self.eventstream_health(),
            self.pipeline_health(),
            self.microphone_health(),
            self.speech_recognition_health(),
            self.searcher_health(),
            self.holyrics_health(),
            # Componentes extras (não exibidos no HealthPanel mas úteis).
            self.event_bus_health(),
            self.event_store_health(),
            self.ranking_health(),
            self.intelligence_health(),
        )

    def get_snapshot(self) -> HealthSnapshot:
        """Retorna snapshot de saúde de todos os componentes."""
        return HealthSnapshot(
            timestamp=time.time(),
            components=self.all_components(),
        )

    def component(self, name: str) -> HealthDTO | None:
        """Retorna HealthDTO de um componente pelo nome."""
        for c in self.all_components():
            if c.component == name:
                return c
        return None


# ---------------------------------------------------------------------------
# DiagnosticPresentationService
# ---------------------------------------------------------------------------


class DiagnosticPresentationService:
    """Service para diagnósticos.

    Prepara estrutura para diagnósticos futuros (microfone, gpu,
    cpu, holyrics, pipeline, event store, event bus).
    Não executa diagnósticos — apenas retorna arquitetura.
    """

    def __init__(
        self,
        pipeline_state: Any | None = None,
        bus: Any | None = None,
        store: Any | None = None,
    ) -> None:
        self._pipeline_state = pipeline_state
        self._bus = bus
        self._store = store

    def microphone_diagnostic(self) -> DiagnosticDTO:
        """Diagnóstico do microfone (placeholder)."""
        return DiagnosticMapper.to_dto(
            component="microphone", category="hardware",
            available=False, info={},
            warnings=("Not verified (architecture only)",),
        )

    def gpu_diagnostic(self) -> DiagnosticDTO:
        """Diagnóstico de GPU (placeholder)."""
        return DiagnosticMapper.to_dto(
            component="gpu", category="hardware",
            available=False, info={},
            warnings=("Not verified (architecture only)",),
        )

    def cpu_diagnostic(self) -> DiagnosticDTO:
        """Diagnóstico de CPU (placeholder)."""
        return DiagnosticMapper.to_dto(
            component="cpu", category="hardware",
            available=False, info={},
            warnings=("Not verified (architecture only)",),
        )

    def holyrics_diagnostic(self) -> DiagnosticDTO:
        """Diagnóstico do Holyrics (placeholder)."""
        return DiagnosticMapper.to_dto(
            component="holyrics", category="service",
            available=False, info={},
            warnings=("Not verified (architecture only)",),
        )

    def pipeline_diagnostic(self) -> DiagnosticDTO:
        """Diagnóstico do pipeline."""
        if self._pipeline_state is None:
            return DiagnosticMapper.to_dto(
                component="pipeline", category="pipeline",
                available=False, errors=("state not available",),
            )
        return DiagnosticMapper.to_dto(
            component="pipeline", category="pipeline",
            available=self._pipeline_state.running,
            info={
                "running": self._pipeline_state.running,
                "paused": self._pipeline_state.paused,
                "last_event_type": self._pipeline_state.last_event_type,
            },
        )

    def event_store_diagnostic(self) -> DiagnosticDTO:
        """Diagnóstico do EventStore."""
        if self._store is None:
            return DiagnosticMapper.to_dto(
                component="event_store", category="pipeline",
                available=False, errors=("store not available",),
            )
        return DiagnosticMapper.to_dto(
            component="event_store", category="pipeline",
            available=True,
            info={
                "count": self._store.count(),
                "policy": getattr(self._store.policy, "retention_strategy", ""),
            },
        )

    def event_bus_diagnostic(self) -> DiagnosticDTO:
        """Diagnóstico do EventBus."""
        if self._bus is None:
            return DiagnosticMapper.to_dto(
                component="event_bus", category="pipeline",
                available=False, errors=("bus not available",),
            )
        return DiagnosticMapper.to_dto(
            component="event_bus", category="pipeline",
            available=True,
            info={
                "event_count": self._bus.event_count(),
                "subscribed_types": len(self._bus.subscribed_types()),
            },
        )

    def all_diagnostics(self) -> tuple:
        """Retorna tuple com DiagnosticDTO de todos os componentes."""
        return (
            self.microphone_diagnostic(),
            self.gpu_diagnostic(),
            self.cpu_diagnostic(),
            self.holyrics_diagnostic(),
            self.pipeline_diagnostic(),
            self.event_store_diagnostic(),
            self.event_bus_diagnostic(),
        )

    def component(self, name: str) -> DiagnosticDTO | None:
        """Retorna DiagnosticDTO de um componente pelo nome."""
        for d in self.all_diagnostics():
            if d.component == name:
                return d
        return None


# ---------------------------------------------------------------------------
# EventPresentationService
# ---------------------------------------------------------------------------


class EventPresentationService:
    """Service para consultar eventos.

    Usa EventStore (via bus.store) para consultas.
    Nunca acessa EventBus diretamente para leitura de histórico.
    """

    def __init__(self, bus: Any) -> None:
        self._bus = bus
        self._store = bus.store

    def get_all_events(self) -> tuple:
        """Retorna tuple de EventDTO com todos os eventos."""
        return EventMapper.to_dto_many(self._store.all())

    def get_event_count(self) -> int:
        """Total de eventos armazenados."""
        return self._store.count()

    def get_last_event(self) -> EventDTO | None:
        """Último evento (ou None)."""
        last = self._store.last()
        return EventMapper.to_dto(last) if last else None

    def get_events_by_correlation(self, correlation_id: str) -> tuple:
        """Eventos de um correlation_id (para Replay)."""
        events = self._store.by_correlation(correlation_id)
        return EventMapper.to_dto_many(events)

    def get_events_by_session(self, session_id: str) -> tuple:
        """Eventos de um session_id (para Dashboard)."""
        events = self._store.by_session(session_id)
        return EventMapper.to_dto_many(events)

    def get_events_by_type(self, event_type: type) -> tuple:
        """Eventos de um tipo específico."""
        events = self._store.by_event(event_type)
        return EventMapper.to_dto_many(events)

    def get_events_between(self, start_ts: float, end_ts: float) -> tuple:
        """Eventos em intervalo temporal."""
        events = self._store.between(start_ts, end_ts)
        return EventMapper.to_dto_many(events)

    def get_snapshot(self, correlation_id: str = "") -> EventSnapshot:
        """Retorna snapshot de eventos."""
        if correlation_id:
            events = self.get_events_by_correlation(correlation_id)
        else:
            events = self.get_all_events()
        return EventSnapshot(
            timestamp=time.time(),
            events=events,
            correlation_id=correlation_id,
        )

    def get_logs(self, level: str = "INFO") -> tuple:
        """Converte eventos em LogDTOs."""
        events = self._store.all()
        return tuple(
            LogMapper.from_event(e, level=level) for e in events
        )


__all__ = [
    "PipelinePresentationService",
    "SessionPresentationService",
    "MetricsPresentationService",
    "ConfigurationPresentationService",
    "HealthPresentationService",
    "DiagnosticPresentationService",
    "EventPresentationService",
]
