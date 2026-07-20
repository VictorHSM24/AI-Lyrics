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
  AudioDeviceDTO,
  AudioDevicesResponse,
  AudioLevelsDTO,
  ConfigurationDTO,
  DiagnosticDTO,
  EventDTO,
  EventSnapshot,
  HealthSnapshot,
  InfoDTO,
  MetricsDTO,
  PipelineSnapshot,
  PipelineStatusDTO,
  SessionDTO,
  SystemInfoDTO,
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
  startPipeline(options?: CallOptions): Promise<PipelineStatusDTO>;
  stopPipeline(options?: CallOptions): Promise<PipelineStatusDTO>;
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
  updateConfiguration(overrides: Partial<ConfigurationDTO>, options?: CallOptions): Promise<ConfigurationDTO>;
}

// ============================================================
// HealthService
// ============================================================

export interface HealthService {
  getHealth(options?: CallOptions): Promise<HealthSnapshot>;
  testHolyrics(params: { base_url: string; token: string }, options?: CallOptions): Promise<{
    ok: boolean;
    message: string;
    latency_ms: number;
    base_url: string;
  }>;
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
// AudioService (Sprint 14)
// ============================================================

export interface AudioService {
  getDevices(options?: CallOptions): Promise<AudioDevicesResponse>;
  getCurrentDevice(options?: CallOptions): Promise<AudioDeviceDTO | null>;
  getLevels(options?: CallOptions): Promise<AudioLevelsDTO>;
  startCapture(options?: CallOptions): Promise<AudioCaptureStatus>;
  stopCapture(options?: CallOptions): Promise<AudioCaptureStatus>;
  selectDevice(deviceIndex: number, options?: CallOptions): Promise<AudioSelectResult>;
}

export interface AudioCaptureStatus {
  capturing: boolean;
  already: boolean;
  device_index: number | null;
  sample_rate?: number;
  channels?: number;
}

export interface AudioSelectResult {
  device_index: number;
  restarted: boolean;
}

// ============================================================
// SystemService (Sprint 14)
// ============================================================

export interface SystemService {
  getSystemInfo(options?: CallOptions): Promise<SystemInfoDTO>;
}

// ============================================================
// InfoService (Sprint 14)
// ============================================================

export interface InfoService {
  getInfo(options?: CallOptions): Promise<InfoDTO>;
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
  audio: AudioService;
  system: SystemService;
  info: InfoService;
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
      startPipeline: (o) => call<PipelineStatusDTO>("pipeline.start", {}, o),
      stopPipeline: (o) => call<PipelineStatusDTO>("pipeline.stop", {}, o),
    },
    session: {
      getCurrentSession: (o) => call<SessionDTO>("session.getCurrent", {}, o),
    },
    metrics: {
      getMetrics: (o) => call<MetricsDTO>("metrics.get", {}, o),
    },
    configuration: {
      getConfiguration: (o) => call<ConfigurationDTO>("configuration.get", {}, o),
      updateConfiguration: (overrides, o) => call<ConfigurationDTO>("configuration.update", overrides as unknown as Record<string, unknown>, o),
    },
    health: {
      getHealth: (o?) => call<HealthSnapshot>("health.get", {}, o),
      testHolyrics: (params: { base_url: string; token: string }, o?) =>
        call<{ ok: boolean; message: string; latency_ms: number; base_url: string }>(
          "health.testHolyrics", params as unknown as Record<string, unknown>, o,
        ),
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
    audio: {
      getDevices: (o) => call<AudioDevicesResponse>("audio.getDevices", {}, o),
      getCurrentDevice: (o) => call<AudioDeviceDTO | null>("audio.getCurrent", {}, o),
      getLevels: (o) => call<AudioLevelsDTO>("audio.getLevels", {}, o),
      startCapture: (o) => call<AudioCaptureStatus>("audio.start", {}, o),
      stopCapture: (o) => call<AudioCaptureStatus>("audio.stop", {}, o),
      selectDevice: (deviceIndex, o) => call<AudioSelectResult>("audio.select", { device_index: deviceIndex }, o),
    },
    system: {
      getSystemInfo: (o) => call<SystemInfoDTO>("system.get", {}, o),
    },
    info: {
      getInfo: (o) => call<InfoDTO>("info.get", {}, o),
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
      startPipeline: reject,
      stopPipeline: reject,
    },
    session: { getCurrentSession: reject },
    metrics: { getMetrics: reject },
    configuration: { getConfiguration: reject, updateConfiguration: reject },
    health: { getHealth: reject, testHolyrics: reject },
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
    audio: { getDevices: reject, getCurrentDevice: reject, getLevels: reject, startCapture: reject, stopCapture: reject, selectDevice: reject },
    system: { getSystemInfo: reject },
    info: { getInfo: reject },
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
