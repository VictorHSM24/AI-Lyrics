"""Composition root — inicializa Core + Presentation Layer.

Este módulo é o ÚNICO lugar que conhece tanto o Core quanto a
Presentation Layer. Ele constrói as dependências e as injeta nos
Presentation Services.

A API FastAPI cons apenas as Presentation Services — nunca o Core.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline import (
    MemoryEventStore,
    PipelineEventBus,
    PipelineMetrics,
    PipelinePolicy,
    PipelineSession,
    PipelineState,
)
from presentation import (
    ConfigurationPresentationService,
    DiagnosticPresentationService,
    EventPresentationService,
    HealthPresentationService,
    MetricsPresentationService,
    PipelinePresentationService,
    SessionPresentationService,
)


# ---------------------------------------------------------------------------
# CompositionRoot — contêiner de dependências.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompositionRoot:
    """Bundle imutável com todas as dependências inicializadas.

    A API consome apenas este objeto — nunca o Core diretamente.
    """

    # Core (não exposto diretamente à API).
    bus: PipelineEventBus
    store: MemoryEventStore
    state: PipelineState
    session: PipelineSession
    metrics: PipelineMetrics
    policy: PipelinePolicy

    # Presentation Services (expostos à API).
    pipeline_service: PipelinePresentationService
    session_service: SessionPresentationService
    metrics_service: MetricsPresentationService
    configuration_service: ConfigurationPresentationService
    health_service: HealthPresentationService
    diagnostic_service: DiagnosticPresentationService
    event_service: EventPresentationService


# ---------------------------------------------------------------------------
# Factory — cria o CompositionRoot.
# ---------------------------------------------------------------------------


def create_composition_root() -> CompositionRoot:
    """Cria e conecta todas as dependências do sistema.

    Ordem:
      1. Core (EventStore → EventBus → State/Session/Metrics/Policy).
      2. Presentation Services (recebem referências do Core).
    """
    # 1. Core
    store = MemoryEventStore()
    bus = PipelineEventBus(store=store)
    state = PipelineState()
    session = PipelineSession.create(session_id="session-api-default")
    metrics = PipelineMetrics()
    policy = PipelinePolicy()

    # 2. Presentation Services
    pipeline_service = PipelinePresentationService(
        state=state, session=session, metrics=metrics, bus=bus,
    )
    session_service = SessionPresentationService(session=session)
    metrics_service = MetricsPresentationService(metrics=metrics)
    configuration_service = ConfigurationPresentationService(
        config=_minimal_config(), pipeline_policy=policy,
    )
    health_service = HealthPresentationService(
        pipeline_state=state, bus=bus, store=store,
    )
    diagnostic_service = DiagnosticPresentationService(
        pipeline_state=state, bus=bus, store=store,
    )
    event_service = EventPresentationService(bus=bus)

    return CompositionRoot(
        bus=bus,
        store=store,
        state=state,
        session=session,
        metrics=metrics,
        policy=policy,
        pipeline_service=pipeline_service,
        session_service=session_service,
        metrics_service=metrics_service,
        configuration_service=configuration_service,
        health_service=health_service,
        diagnostic_service=diagnostic_service,
        event_service=event_service,
    )


def _minimal_config() -> Any:
    """Configuração mínima para ConfigurationPresentationService.

    A ConfigurationPresentationService espera um objeto com atributos
    mode, holyrics, stt, llm, search, state, cache, confidence, log,
    audio. Como não há config real carregada, fornecemos um stub
    mínimo que satisfaz o mapper (sub-campos como dicts para que
    ConfigurationMapper._to_dict os serialize corretamente).
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        mode="production",
        holyrics={"enabled": False, "host": "localhost", "port": 8080, "version": ""},
        stt={"model": "whisper-base", "language": "pt-BR", "device": "cpu"},
        llm={"model": "gpt-4", "provider": "openai", "api_key": "", "temperature": 0.0},
        search={"max_results": 10, "min_score": 0.5},
        state={"persist_path": "", "auto_save": False},
        cache={"enabled": False, "ttl_seconds": 0},
        confidence={"threshold": 0.5, "levels": {}},
        log={"level": "INFO", "file": ""},
        audio={"sample_rate": 16000, "channels": 1},
    )


# ---------------------------------------------------------------------------
# Singleton — uma única instância por processo.
# ---------------------------------------------------------------------------


_root: CompositionRoot | None = None


def get_root() -> CompositionRoot:
    """Retorna o CompositionRoot singleton."""
    global _root
    if _root is None:
        _root = create_composition_root()
    return _root


def reset_root() -> None:
    """Reseta o singleton (útil para testes)."""
    global _root
    _root = None
