/**
 * Services — consultas à Presentation Layer via Client SDK.
 *
 * Services NUNCA armazenam estado.
 * Services NUNCA recebem eventos.
 * Services NUNCA conhecem transporte (REST, WebSocket, SSE).
 * Services NUNCA conhecem React.
 *
 * Fluxo:
 *   Hooks → Services → Client SDK → Transport → Backend
 */

import type {
  ConfigurationDTO,
  DiagnosticDTO,
  EventDTO,
  EventSnapshot,
  HealthSnapshot,
  MetricsDTO,
  PipelineSnapshot,
  PipelineStatusDTO,
  SessionDTO,
} from "@/types";
import {
  notConfigured,
  type CallOptions,
  type Client,
  type Versioned,
} from "@/sdk";

// ============================================================
// PipelineService
// ============================================================

export interface PipelineService {
  getStatus(options?: CallOptions): Promise<PipelineStatusDTO>;
  getSession(options?: CallOptions): Promise<SessionDTO>;
  getMetrics(options?: CallOptions): Promise<MetricsDTO>;
  getSnapshot(options?: CallOptions): Promise<PipelineSnapshot>;
}

// ============================================================
// SessionService
// ============================================================

export interface SessionService {
  getCurrentSession(options?: CallOptions): Promise<SessionDTO>;
}

// ============================================================
// MetricsService
// ============================================================

export interface MetricsService {
  getMetrics(options?: CallOptions): Promise<MetricsDTO>;
}

// ============================================================
// ConfigurationService
// ============================================================

export interface ConfigurationService {
  getConfiguration(options?: CallOptions): Promise<ConfigurationDTO>;
}

// ============================================================
// HealthService
// ============================================================

export interface HealthService {
  getHealth(options?: CallOptions): Promise<HealthSnapshot>;
}

// ============================================================
// DiagnosticsService
// ============================================================

export interface DiagnosticsService {
  getDiagnostics(options?: CallOptions): Promise<DiagnosticDTO[]>;
}

// ============================================================
// EventService
// ============================================================

export interface EventService {
  getAllEvents(options?: CallOptions): Promise<EventDTO[]>;
  getEventsByCorrelation(correlationId: string, options?: CallOptions): Promise<EventDTO[]>;
  getEventsBySession(sessionId: string, options?: CallOptions): Promise<EventDTO[]>;
  getEventSnapshot(correlationId?: string, options?: CallOptions): Promise<EventSnapshot>;
}

// ============================================================
// ReplayService
// ============================================================

export interface ReplayService {
  getReplayEvents(correlationId: string, options?: CallOptions): Promise<EventDTO[]>;
  getReplaySessions(options?: CallOptions): Promise<string[]>;
  getReplayCorrelations(sessionId: string, options?: CallOptions): Promise<string[]>;
}

// ============================================================
// PresentationServices — agregador.
// ============================================================

export interface PresentationServices {
  pipeline: PipelineService;
  session: SessionService;
  metrics: MetricsService;
  configuration: ConfigurationService;
  health: HealthService;
  diagnostics: DiagnosticsService;
  events: EventService;
  replay: ReplayService;
}

// ============================================================
// Implementação baseada em Client SDK.
// ============================================================

function unwrap<T>(v: Versioned<T>): T {
  return v.payload;
}

/**
 * Cria services que delegam chamadas ao Client SDK.
 *
 * Nenhum backend real existe — todas as chamadas falham com
 * `notConfigured()` até que um transporte real seja configurado.
 */
export function createServices(client: Client): PresentationServices {
  const call = <T>(method: string, params: Record<string, unknown> = {}, options?: CallOptions) =>
    client.call<T>(method, params, options).then(unwrap);

  return {
    pipeline: {
      getStatus: (o) => call<PipelineStatusDTO>("pipeline.getStatus", {}, o),
      getSession: (o) => call<SessionDTO>("pipeline.getSession", {}, o),
      getMetrics: (o) => call<MetricsDTO>("pipeline.getMetrics", {}, o),
      getSnapshot: (o) => call<PipelineSnapshot>("pipeline.getSnapshot", {}, o),
    },
    session: {
      getCurrentSession: (o) => call<SessionDTO>("session.getCurrent", {}, o),
    },
    metrics: {
      getMetrics: (o) => call<MetricsDTO>("metrics.get", {}, o),
    },
    configuration: {
      getConfiguration: (o) => call<ConfigurationDTO>("configuration.get", {}, o),
    },
    health: {
      getHealth: (o) => call<HealthSnapshot>("health.get", {}, o),
    },
    diagnostics: {
      getDiagnostics: (o) => call<DiagnosticDTO[]>("diagnostics.get", {}, o),
    },
    events: {
      getAllEvents: (o) => call<EventDTO[]>("events.getAll", {}, o),
      getEventsByCorrelation: (cid, o) => call<EventDTO[]>("events.getByCorrelation", { correlationId: cid }, o),
      getEventsBySession: (sid, o) => call<EventDTO[]>("events.getBySession", { sessionId: sid }, o),
      getEventSnapshot: (cid, o) => call<EventSnapshot>("events.getSnapshot", { correlationId: cid }, o),
    },
    replay: {
      getReplayEvents: (cid, o) => call<EventDTO[]>("replay.getEvents", { correlationId: cid }, o),
      getReplaySessions: (o) => call<string[]>("replay.getSessions", {}, o),
      getReplayCorrelations: (sid, o) => call<string[]>("replay.getCorrelations", { sessionId: sid }, o),
    },
  };
}

/**
 * Services stub — todas as chamadas rejeitam com `notConfigured()`.
 *
 * Útil para testes e para o período antes do backend existir.
 */
export function createStubServices(): PresentationServices {
  const reject = <T>(): Promise<T> => Promise.reject(notConfigured());
  return {
    pipeline: {
      getStatus: reject,
      getSession: reject,
      getMetrics: reject,
      getSnapshot: reject,
    },
    session: { getCurrentSession: reject },
    metrics: { getMetrics: reject },
    configuration: { getConfiguration: reject },
    health: { getHealth: reject },
    diagnostics: { getDiagnostics: reject },
    events: {
      getAllEvents: reject,
      getEventsByCorrelation: reject,
      getEventsBySession: reject,
      getEventSnapshot: reject,
    },
    replay: {
      getReplayEvents: reject,
      getReplaySessions: reject,
      getReplayCorrelations: reject,
    },
  };
}

// ============================================================
// Compatibilidade — interfaces antigas (deprecated).
// ============================================================

/** @deprecated Use PipelineService. */
export type PipelineApi = PipelineService;
/** @deprecated Use SessionService. */
export type SessionApi = SessionService;
/** @deprecated Use MetricsService. */
export type MetricsApi = MetricsService;
/** @deprecated Use ConfigurationService. */
export type ConfigurationApi = ConfigurationService;
/** @deprecated Use HealthService. */
export type HealthApi = HealthService;
/** @deprecated Use DiagnosticsService. */
export type DiagnosticsApi = DiagnosticsService;
/** @deprecated Use EventService. */
export type EventApi = EventService;
/** @deprecated Use ReplayService. */
export type ReplayApi = ReplayService;
/** @deprecated Use PresentationServices. */
export type PresentationApi = PresentationServices;
