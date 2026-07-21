"""Pipeline Phase 12 — Streaming Speech Pipeline.

Infraestrutura determinística, orientada a eventos, completamente
rastreável, desacoplada e auditável. Conecta todos os módulos das
fases anteriores (Searcher, Ranking, Context, Feedback, Evaluation,
Sermon Intelligence, Evidence Layer, Parser, STT, LLM, Holyrics) sem
modificar o comportamento de nenhum deles.

Filosofia:
  - O Pipeline NUNCA implementa regra de negócio.
  - O Pipeline NUNCA decide, calcula ranking, interpreta contexto,
    aprende, executa heurísticas, cria Evidence, altera Signals ou
    modifica Intelligence.
  - O Pipeline APENAS coordena via eventos tipados.

Arquitetura:
  - Event-driven: Handlers não se chamam diretamente.
  - Toda comunicação via PipelineEventBus.
  - Cada evento carrega EventMetadata (correlation_id, causation_id,
    session_id, event_id, timestamp, origin, metadata).
  - Rastreabilidade completa: Replay pronto (não implementado).
  - Backpressure preparado (não implementado).
  - Tudo síncrono (sem threads, asyncio, multiprocessing).

Componentes:
  - EventMetadata: DTO imutável de rastreabilidade.
  - Eventos: 16 eventos tipados (frozen dataclass).
  - PipelineEventBus: subscribe/unsubscribe/publish/dispatch.
  - PipelinePolicy: timeouts, buffers, limites, retries.
  - PipelineState: estado do pipeline (running, paused, etc.).
  - PipelineSession: representa um sermão completo.
  - PipelineMetrics: segmentos, consultas, latência, throughput.
  - Handlers: RecognitionHandler, SearchHandler, RankingHandler,
    IntelligenceHandler, PresentationHandler, FeedbackHandler,
    EvaluationHandler, ContextHandler.
  - PipelineCoordinator: registra Handlers.
  - StreamingPipelineEngine: start/stop/pause/resume/process.

Compatibilidade:
  - Nenhuma API pública existente é alterada.
  - Se o Pipeline não existir, todo o restante funciona normalmente.
"""

from __future__ import annotations

from pipeline.bus import PipelineEventBus
from pipeline.coordinator import PipelineCoordinator
from pipeline.engine import StreamingPipelineEngine
from pipeline.event_store import (
    EventStore,
    EventStorePolicy,
    EventStoreStatistics,
    MemoryEventStore,
)
from pipeline.events import (
    EvaluationRecorded,
    FeedbackRecorded,
    IntelligenceCompleted,
    OperationalEvent,
    PipelineError,
    PipelineEvent,
    PipelinePaused,
    PipelineResumed,
    PipelineStarted,
    PipelineStopped,
    PresentationCompleted,
    PresentationRequested,
    RankingCompleted,
    SearchCompleted,
    SearchRequested,
    SpeechRecognized,
    SpeechSegmentReceived,
    TelemetryEvent,
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
    # Sprint 19 — Streaming Speech Pipeline
    SpeechPartial,
    SpeechPartialUpdated,
    ReferenceCandidate,
    is_operational_event,
    is_pipeline_event,
    is_telemetry_event,
)
from pipeline.handlers import (
    ContextHandler,
    EvaluationHandler,
    FeedbackHandler,
    IntelligenceHandler,
    PresentationHandler,
    RankingHandler,
    RecognitionHandler,
    SearchHandler,
)
from pipeline.metadata import EventMetadata
from pipeline.metrics import PipelineMetrics
from pipeline.policy import PipelinePolicy
from pipeline.session import PipelineSession
from pipeline.state import PipelineState


__all__ = [
    # Metadata
    "EventMetadata",
    # Bus
    "PipelineEventBus",
    # Event Store
    "EventStore",
    "MemoryEventStore",
    "EventStorePolicy",
    "EventStoreStatistics",
    # Policy
    "PipelinePolicy",
    # State
    "PipelineState",
    # Session
    "PipelineSession",
    # Metrics
    "PipelineMetrics",
    # Events
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
    # Sprint 19 — Streaming Speech Pipeline
    "SpeechPartial",
    "SpeechPartialUpdated",
    "ReferenceCandidate",
    "is_pipeline_event",
    "is_operational_event",
    "is_telemetry_event",
    # Handlers
    "RecognitionHandler",
    "SearchHandler",
    "RankingHandler",
    "IntelligenceHandler",
    "PresentationHandler",
    "FeedbackHandler",
    "EvaluationHandler",
    "ContextHandler",
    # Coordinator
    "PipelineCoordinator",
    # Engine
    "StreamingPipelineEngine",
]
