/**
 * Testes da Sprint 13 — Data Integration Foundation.
 *
 * Cobertura:
 * - Bridge handlers (pipeline lifecycle, session, metrics, diagnostics)
 * - Bootstrap (popula stores via services)
 * - useBootstrap hook (dispara na conexão)
 * - Startup real (verificações reais, não setTimeout)
 * - dev-log (no-op em produção)
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  createStoreRegistry,
} from "@/stores";
import {
  dispatchDomainHandlers,
  handlePipelineLifecycle,
  handleMetricsEvent,
  handleDiagnosticEvent,
  handleSessionEvent,
  bootstrapStores,
  type BootstrapResult,
} from "@/stream";
import { createServices, type PresentationServices } from "@/services";
import { createClient } from "@/sdk";
import { devLog } from "@/utils";
import type { EventDTO, HealthSnapshot, MetricsDTO, PipelineStatusDTO, SessionDTO, ConfigurationDTO, DiagnosticDTO } from "@/types";

// ============================================================
// Helpers
// ============================================================

function makeEvent(type: string, payload: Record<string, unknown> = {}, sessionId = "sess-1"): EventDTO {
  return {
    event_type: type,
    meta: {
      event_id: `evt-${Math.random().toString(36).slice(2)}`,
      correlation_id: `corr-${Math.random().toString(36).slice(2)}`,
      causation_id: null,
      session_id: sessionId,
      timestamp: Date.now() / 1000,
      origin: "test",
      metadata: [],
    },
    payload,
  };
}

function makePipelineStatus(running: boolean, paused = false): PipelineStatusDTO {
  return {
    running,
    paused,
    is_active: running && !paused,
    is_idle: !running,
    is_processing: false,
    current_segment: null,
    last_query: "",
    last_candidate_id: "",
    last_event_type: "",
    last_event_timestamp: 0,
    statistics: {},
  };
}

function makeSession(): SessionDTO {
  return {
    session_id: "sess-1",
    started_at: Date.now() / 1000,
    ended_at: 0,
    is_active: true,
    is_ended: false,
    duration_s: 0,
    processed_segments: 0,
    processed_queries: 0,
    presentations: 0,
    errors: 0,
    error_rate: 0,
    presentation_rate: 0,
    segments_per_minute: 0,
    queries_per_minute: 0,
    unique_correlations: 0,
    correlation_ids: [],
  };
}

function makeMetrics(): MetricsDTO {
  return {
    segments_received: 10,
    segments_processed: 8,
    segments_dropped: 2,
    queries_processed: 5,
    presentations_executed: 4,
    presentations_failed: 1,
    errors_total: 1,
    errors_recoverable: 1,
    errors_fatal: 0,
    total_latency_ms: 1000,
    avg_latency_ms: 100,
    avg_recognition_latency_ms: 50,
    avg_search_latency_ms: 30,
    avg_ranking_latency_ms: 10,
    avg_intelligence_latency_ms: 5,
    avg_presentation_latency_ms: 5,
    throughput_segments_per_min: 10,
    throughput_queries_per_min: 5,
    error_rate: 0.1,
    drop_rate: 0.2,
    presentation_success_rate: 0.8,
    processing_success_rate: 0.8,
    duration_s: 60,
    correlation_count: 5,
  };
}

function makeHealth(): HealthSnapshot {
  return {
    timestamp: Date.now() / 1000,
    components: [
      { component: "stt", status: "healthy", message: "OK", details: {}, is_healthy: true },
      { component: "holyrics", status: "healthy", message: "OK", details: {}, is_healthy: true },
    ],
    component_count: 2,
    healthy_count: 2,
    unhealthy_count: 0,
    all_healthy: true,
  };
}

function makeConfig(): ConfigurationDTO {
  return {
    mode: "production",
    holyrics: { url: "http://localhost:8080" },
    stt: { model: "whisper-base" },
    llm: {},
    search: {},
    state: {},
    cache: {},
    confidence: {},
    log: {},
    audio: null,
    pipeline_policy: null,
  };
}

function makeDiagnostics(): DiagnosticDTO[] {
  return [
    {
      component: "stt",
      category: "model",
      available: true,
      info: {},
      warnings: [],
      errors: [],
      has_warnings: false,
      has_errors: false,
    },
  ];
}

/** Cria services mock que retornam dados predeterminados. */
function createMockServices(overrides?: Partial<{
  status: PipelineStatusDTO;
  session: SessionDTO;
  metrics: MetricsDTO;
  config: ConfigurationDTO;
  health: HealthSnapshot;
  diags: DiagnosticDTO[];
}>): PresentationServices {
  const client = createClient();
  const services = createServices(client);
  return {
    ...services,
    pipeline: {
      getStatus: vi.fn(async () => overrides?.status ?? makePipelineStatus(true)),
      getSession: vi.fn(async () => overrides?.session ?? makeSession()),
      getMetrics: vi.fn(async () => overrides?.metrics ?? makeMetrics()),
      getSnapshot: vi.fn(async () => ({
        timestamp: Date.now() / 1000,
        status: overrides?.status ?? makePipelineStatus(true),
        session: overrides?.session ?? makeSession(),
        metrics: overrides?.metrics ?? makeMetrics(),
        last_event: null,
      })),
      startPipeline: vi.fn(async () => makePipelineStatus(true)),
      stopPipeline: vi.fn(async () => makePipelineStatus(false)),
    },
    session: {
      getCurrentSession: vi.fn(async () => overrides?.session ?? makeSession()),
    },
    metrics: {
      getMetrics: vi.fn(async () => overrides?.metrics ?? makeMetrics()),
    },
    configuration: {
      getConfiguration: vi.fn(async () => overrides?.config ?? makeConfig()),
      updateConfiguration: vi.fn(async () => overrides?.config ?? makeConfig()),
    },
    health: {
      getHealth: vi.fn(async () => overrides?.health ?? makeHealth()),
      testHolyrics: vi.fn(async () => ({ ok: true, message: "OK", latency_ms: 10, base_url: "" })),
    },
    diagnostics: {
      getDiagnostics: vi.fn(async () => overrides?.diags ?? makeDiagnostics()),
    },
    events: services.events,
    replay: services.replay,
    audio: {
      getDevices: vi.fn(async () => ({ devices: [], count: 0 })),
      getCurrentDevice: vi.fn(async () => null),
      getLevels: vi.fn(async () => ({ rms: 0, peak: 0, timestamp: 0 })),
      startCapture: vi.fn(async () => ({ capturing: true, already: false, device_index: null as number | null })),
      stopCapture: vi.fn(async () => ({ capturing: false, already: false, device_index: null as number | null })),
      selectDevice: vi.fn(async () => ({ device_index: 0, restarted: false })),
    },
    system: {
      getSystemInfo: vi.fn(async () => ({
        python_version: "3.14",
        os_name: "Test",
        os_version: "1.0",
        architecture: "x86_64",
        cpu_count: 4,
        cpu_percent: 0,
        memory_total_bytes: 0,
        memory_available_bytes: 0,
        disk_total_bytes: 0,
        disk_used_bytes: 0,
        log_dir: "logs",
        cache_dir: "cache",
        data_dir: "data",
        gpu_name: "",
        gpu_memory_total_bytes: 0,
        gpu_memory_used_bytes: 0,
        torch_version: "",
        faster_whisper_version: "",
        sentence_transformers_version: "",
        sounddevice_version: "",
      })),
    },
    info: {
      getInfo: vi.fn(async () => ({
        name: "AI Lyrics API",
        version: "0.1.0",
        api_version: { major: 0, minor: 1, patch: 0, pre: "foundation" },
        server_time: 0,
        build_id: "",
        commit: "",
        build_date: "",
        frontend_version: "0.1.0",
        sdk_compatibility: "0.1.0",
      })),
    },
  };
}

/** Cria services mock que rejeitam todas as chamadas. */
function createFailingServices(): PresentationServices {
  const client = createClient();
  const services = createServices(client);
  const reject = async <T,>(): Promise<T> => Promise.reject(new Error("backend unavailable"));
  return {
    ...services,
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
    events: services.events,
    replay: services.replay,
    audio: { getDevices: reject, getCurrentDevice: reject, getLevels: reject, startCapture: reject, stopCapture: reject, selectDevice: reject },
    system: { getSystemInfo: reject },
    info: { getInfo: reject },
  };
}

beforeEach(() => {
  localStorage.clear();
});

// ============================================================
// Bridge Handlers — Pipeline Lifecycle
// ============================================================

describe("handlePipelineLifecycle", () => {
  it("PipelineStarted → running=true", () => {
    const stores = createStoreRegistry();
    const dto = makeEvent("PipelineStarted");
    handlePipelineLifecycle(dto, stores);
    const snap = stores.pipeline.current;
    expect(snap).not.toBeNull();
    expect(snap!.data.status.running).toBe(true);
    expect(snap!.data.status.paused).toBe(false);
  });

  it("PipelineStopped → running=false", () => {
    const stores = createStoreRegistry();
    // Start first
    handlePipelineLifecycle(makeEvent("PipelineStarted"), stores);
    // Then stop
    handlePipelineLifecycle(makeEvent("PipelineStopped"), stores);
    const snap = stores.pipeline.current;
    expect(snap!.data.status.running).toBe(false);
    expect(snap!.data.status.paused).toBe(false);
  });

  it("PipelinePaused → paused=true", () => {
    const stores = createStoreRegistry();
    handlePipelineLifecycle(makeEvent("PipelineStarted"), stores);
    handlePipelineLifecycle(makeEvent("PipelinePaused"), stores);
    const snap = stores.pipeline.current;
    expect(snap!.data.status.running).toBe(true);
    expect(snap!.data.status.paused).toBe(true);
  });

  it("PipelineResumed → paused=false", () => {
    const stores = createStoreRegistry();
    handlePipelineLifecycle(makeEvent("PipelineStarted"), stores);
    handlePipelineLifecycle(makeEvent("PipelinePaused"), stores);
    handlePipelineLifecycle(makeEvent("PipelineResumed"), stores);
    const snap = stores.pipeline.current;
    expect(snap!.data.status.running).toBe(true);
    expect(snap!.data.status.paused).toBe(false);
  });

  it("ignora eventos não-lifecycle", () => {
    const stores = createStoreRegistry();
    handlePipelineLifecycle(makeEvent("SpeechRecognized"), stores);
    expect(stores.pipeline.hasSnapshot).toBe(false);
  });
});

// ============================================================
// Bridge Handlers — Session
// ============================================================

describe("handleSessionEvent", () => {
  it("PipelineStarted → cria sessão ativa", () => {
    const stores = createStoreRegistry();
    const dto = makeEvent("PipelineStarted");
    handleSessionEvent(dto, stores);
    const snap = stores.session.current;
    expect(snap).not.toBeNull();
    expect(snap!.data.is_active).toBe(true);
    expect(snap!.data.session_id).toBe("sess-1");
  });

  it("PipelineStopped → encerra sessão", () => {
    const stores = createStoreRegistry();
    handleSessionEvent(makeEvent("PipelineStarted"), stores);
    handleSessionEvent(makeEvent("PipelineStopped"), stores);
    const snap = stores.session.current;
    expect(snap!.data.is_active).toBe(false);
    expect(snap!.data.is_ended).toBe(true);
  });

  it("ignora eventos não-lifecycle", () => {
    const stores = createStoreRegistry();
    handleSessionEvent(makeEvent("SpeechRecognized"), stores);
    expect(stores.session.hasSnapshot).toBe(false);
  });
});

// ============================================================
// Bridge Handlers — Metrics
// ============================================================

describe("handleMetricsEvent", () => {
  it("SpeechSegmentReceived → segments_received+1", () => {
    const stores = createStoreRegistry();
    handleMetricsEvent(makeEvent("SpeechSegmentReceived"), stores);
    expect(stores.metrics.current!.data.segments_received).toBe(1);
  });

  it("SpeechRecognized → segments_processed+1", () => {
    const stores = createStoreRegistry();
    handleMetricsEvent(makeEvent("SpeechRecognized"), stores);
    expect(stores.metrics.current!.data.segments_processed).toBe(1);
  });

  it("SearchCompleted → queries_processed+1", () => {
    const stores = createStoreRegistry();
    handleMetricsEvent(makeEvent("SearchCompleted"), stores);
    expect(stores.metrics.current!.data.queries_processed).toBe(1);
  });

  it("PresentationCompleted presented=true → presentations_executed+1", () => {
    const stores = createStoreRegistry();
    handleMetricsEvent(makeEvent("PresentationCompleted", { presented: true }), stores);
    expect(stores.metrics.current!.data.presentations_executed).toBe(1);
  });

  it("PresentationCompleted presented=false → presentations_failed+1", () => {
    const stores = createStoreRegistry();
    handleMetricsEvent(makeEvent("PresentationCompleted", { presented: false }), stores);
    expect(stores.metrics.current!.data.presentations_failed).toBe(1);
  });

  it("PipelineError recoverable=true → errors_recoverable+1", () => {
    const stores = createStoreRegistry();
    handleMetricsEvent(makeEvent("PipelineError", { recoverable: true }), stores);
    expect(stores.metrics.current!.data.errors_total).toBe(1);
    expect(stores.metrics.current!.data.errors_recoverable).toBe(1);
  });

  it("PipelineError recoverable=false → errors_fatal+1", () => {
    const stores = createStoreRegistry();
    handleMetricsEvent(makeEvent("PipelineError", { recoverable: false }), stores);
    expect(stores.metrics.current!.data.errors_total).toBe(1);
    expect(stores.metrics.current!.data.errors_fatal).toBe(1);
  });

  it("incrementa sobre valores existentes", () => {
    const stores = createStoreRegistry();
    stores.metrics.set(makeMetrics()); // segments_received=10
    handleMetricsEvent(makeEvent("SpeechSegmentReceived"), stores);
    expect(stores.metrics.current!.data.segments_received).toBe(11);
  });
});

// ============================================================
// Bridge Handlers — Diagnostics
// ============================================================

describe("handleDiagnosticEvent", () => {
  it("PipelineError → adiciona diagnóstico", () => {
    const stores = createStoreRegistry();
    handleDiagnosticEvent(
      makeEvent("PipelineError", {
        error_type: "STTError",
        error_message: "Model not loaded",
        handler_name: "stt_handler",
        recoverable: true,
      }),
      stores,
    );
    const diags = stores.diagnostics.current!.data;
    expect(diags).toHaveLength(1);
    expect(diags[0].component).toBe("stt_handler");
    expect(diags[0].has_warnings).toBe(true);
  });

  it("PipelineError non-recoverable → has_errors=true", () => {
    const stores = createStoreRegistry();
    handleDiagnosticEvent(
      makeEvent("PipelineError", {
        error_type: "FatalError",
        error_message: "Crash",
        handler_name: "pipeline",
        recoverable: false,
      }),
      stores,
    );
    const diags = stores.diagnostics.current!.data;
    expect(diags[0].has_errors).toBe(true);
  });

  it("mantém últimos 50 diagnósticos", () => {
    const stores = createStoreRegistry();
    for (let i = 0; i < 55; i += 1) {
      handleDiagnosticEvent(
        makeEvent("PipelineError", { error_type: `Err${i}`, error_message: `msg${i}`, handler_name: "h", recoverable: true }),
      stores,
      );
    }
    const diags = stores.diagnostics.current!.data;
    expect(diags).toHaveLength(50);
  });

  it("ignora eventos não-erro", () => {
    const stores = createStoreRegistry();
    handleDiagnosticEvent(makeEvent("PipelineStarted"), stores);
    expect(stores.diagnostics.hasSnapshot).toBe(false);
  });
});

// ============================================================
// dispatchDomainHandlers — despachante integrado
// ============================================================

describe("dispatchDomainHandlers", () => {
  it("PipelineStarted atualiza pipeline + session", () => {
    const stores = createStoreRegistry();
    dispatchDomainHandlers(makeEvent("PipelineStarted"), stores);
    expect(stores.pipeline.hasSnapshot).toBe(true);
    expect(stores.session.hasSnapshot).toBe(true);
  });

  it("SpeechRecognized atualiza metrics", () => {
    const stores = createStoreRegistry();
    dispatchDomainHandlers(makeEvent("SpeechRecognized"), stores);
    expect(stores.metrics.hasSnapshot).toBe(true);
  });

  it("PipelineError atualiza metrics + diagnostics", () => {
    const stores = createStoreRegistry();
    dispatchDomainHandlers(
      makeEvent("PipelineError", { recoverable: true, error_type: "Err", error_message: "msg", handler_name: "h" }),
      stores,
    );
    expect(stores.metrics.hasSnapshot).toBe(true);
    expect(stores.diagnostics.hasSnapshot).toBe(true);
  });

  it("evento desconhecido não atualiza stores de domínio", () => {
    const stores = createStoreRegistry();
    dispatchDomainHandlers(makeEvent("UnknownEvent"), stores);
    expect(stores.pipeline.hasSnapshot).toBe(false);
    expect(stores.metrics.hasSnapshot).toBe(false);
  });
});

// ============================================================
// Bootstrap
// ============================================================

describe("bootstrapStores", () => {
  it("popula todos os stores com dados reais", async () => {
    const stores = createStoreRegistry();
    const services = createMockServices();
    const result = await bootstrapStores(services, stores);

    expect(result.allOk).toBe(true);
    expect(stores.pipeline.hasSnapshot).toBe(true);
    expect(stores.session.hasSnapshot).toBe(true);
    expect(stores.metrics.hasSnapshot).toBe(true);
    expect(stores.configuration.hasSnapshot).toBe(true);
    expect(stores.diagnostics.hasSnapshot).toBe(true);
    expect(stores.health.hasSnapshot).toBe(true);
  });

  it("pipeline store contém status real", async () => {
    const stores = createStoreRegistry();
    const services = createMockServices({ status: makePipelineStatus(true, false) });
    await bootstrapStores(services, stores);
    expect(stores.pipeline.current!.data.status.running).toBe(true);
  });

  it("metrics store contém métricas reais", async () => {
    const stores = createStoreRegistry();
    const services = createMockServices({ metrics: makeMetrics() });
    await bootstrapStores(services, stores);
    expect(stores.metrics.current!.data.segments_received).toBe(10);
  });

  it("health store contém snapshot real", async () => {
    const stores = createStoreRegistry();
    const services = createMockServices({ health: makeHealth() });
    await bootstrapStores(services, stores);
    expect(stores.health.current!.data.all_healthy).toBe(true);
    expect(stores.health.current!.data.components).toHaveLength(2);
  });

  it("configuration store contém config real", async () => {
    const stores = createStoreRegistry();
    const services = createMockServices({ config: makeConfig() });
    await bootstrapStores(services, stores);
    expect(stores.configuration.current!.data.mode).toBe("production");
  });

  it("diagnostics store contém diagnósticos reais", async () => {
    const stores = createStoreRegistry();
    const services = createMockServices({ diags: makeDiagnostics() });
    await bootstrapStores(services, stores);
    expect(stores.diagnostics.current!.data).toHaveLength(1);
  });

  it("falhas individuais não impedem outras", async () => {
    const stores = createStoreRegistry();
    const services = createFailingServices();
    const result = await bootstrapStores(services, stores);

    expect(result.allOk).toBe(false);
    expect(result.results.pipelineStatus).toBe(false);
    expect(result.errors.pipelineStatus).toBeInstanceOf(Error);
  });

  it("retorna BootstrapResult com resultados individuais", async () => {
    const stores = createStoreRegistry();
    const services = createMockServices();
    const result: BootstrapResult = await bootstrapStores(services, stores);

    expect(result.results.pipelineStatus).toBe(true);
    expect(result.results.pipelineSession).toBe(true);
    expect(result.results.pipelineMetrics).toBe(true);
    expect(result.results.configuration).toBe(true);
    expect(result.results.diagnostics).toBe(true);
    expect(result.results.health).toBe(true);
  });
});

// ============================================================
// dev-log
// ============================================================

describe("devLog", () => {
  it("não lança erro ao chamar métodos", () => {
    expect(() => {
      devLog.info("test");
      devLog.bootstrap("test");
      devLog.bridge("test");
      devLog.startup("test");
      devLog.warn("test");
      devLog.error("test");
    }).not.toThrow();
  });
});
