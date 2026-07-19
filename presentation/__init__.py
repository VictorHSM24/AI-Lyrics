"""Presentation Layer — camada de apresentação do AI Lyrics.

A Presentation Layer é a única responsável por expor informações
do sistema para futuras interfaces (REST, WebSocket, CLI, Dashboard,
Replay, ferramentas de diagnóstico).

Filosofia:
  - O Core conhece apenas domínio.
  - A Presentation Layer conhece apenas apresentação.
  - Ela nunca implementa regra de negócio.
  - Nunca altera estado interno.
  - Nunca decide.
  - Nunca executa Search, Ranking, interpreta Evidence, modifica
    Sessions ou altera Pipeline.
  - Ela apenas adapta informações.

Arquitetura:
  - DTOs: imutáveis, serializáveis, independentes do Core.
  - Mappers: Core → DTO (one-way, nunca inverso).
  - Services: somente leitura, consultam Core via Mappers.
  - Snapshots: estado do sistema em determinado momento.
  - Observers: observam EventBus, atualizam snapshots.
  - Adapters: contratos para futuras interfaces (REST, WS, CLI,
    Dashboard, Replay).

Compatibilidade:
  - Nenhum componente existente depende da Presentation Layer.
  - Ela depende do Core. Nunca o contrário.
  - Se a Presentation Layer não existir, todo o restante funciona.
"""

from __future__ import annotations

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
from presentation.mappers import (
    CandidateMapper,
    ConfigurationMapper,
    DiagnosticMapper,
    EventMapper,
    EvidenceMapper,
    HealthMapper,
    LogMapper,
    MetricsMapper,
    PipelineMapper,
    PresentationMapper,
    RecommendationMapper,
    ScoreMapper,
    SessionMapper,
    SignalMapper,
)
from presentation.observers import (
    BaseObserver,
    EventObserver,
    MetricsObserver,
    PipelineObserver,
    SessionObserver,
)
from presentation.services import (
    ConfigurationPresentationService,
    DiagnosticPresentationService,
    EventPresentationService,
    HealthPresentationService,
    MetricsPresentationService,
    PipelinePresentationService,
    SessionPresentationService,
)
from presentation.snapshots import (
    ConfigurationSnapshot,
    EventSnapshot,
    HealthSnapshot,
    MetricsSnapshot,
    PipelineSnapshot,
    SessionSnapshot,
    SnapshotFactory,
)
from presentation.adapters import (
    BaseAdapter,
    CliAdapter,
    DashboardAdapter,
    ReplayAdapter,
    RestAdapter,
    WebSocketAdapter,
)


__all__ = [
    # DTOs (apresentação)
    "EventMetadataDTO",
    "EventDTO",
    "PipelineStatusDTO",
    "SessionDTO",
    "MetricsDTO",
    "ConfigurationDTO",
    "HealthDTO",
    "DiagnosticDTO",
    "LogDTO",
    # DTOs (domínio)
    "CandidateDTO",
    "EvidenceDTO",
    "SignalDTO",
    "ScoreDTO",
    "RecommendationDTO",
    "PresentationDTO",
    # Mappers
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
    # Snapshots
    "PipelineSnapshot",
    "SessionSnapshot",
    "MetricsSnapshot",
    "HealthSnapshot",
    "ConfigurationSnapshot",
    "EventSnapshot",
    "SnapshotFactory",
    # Observers
    "BaseObserver",
    "EventObserver",
    "PipelineObserver",
    "MetricsObserver",
    "SessionObserver",
    # Services
    "PipelinePresentationService",
    "SessionPresentationService",
    "MetricsPresentationService",
    "ConfigurationPresentationService",
    "HealthPresentationService",
    "DiagnosticPresentationService",
    "EventPresentationService",
    # Adapters
    "BaseAdapter",
    "RestAdapter",
    "WebSocketAdapter",
    "CliAdapter",
    "DashboardAdapter",
    "ReplayAdapter",
]
