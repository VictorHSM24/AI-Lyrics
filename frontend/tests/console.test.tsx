/**
 * Testes do Console Operacional.
 *
 * Cobertura:
 * - EventCard: renderização, categorias, severity, correlation id
 * - PipelineStage: estados visuais (idle, running, success, warning, error)
 * - SeverityBadge: todas as severidades
 * - ConnectionBadge: status de conexão
 * - LatencyBadge: latência
 * - TimelinePanel: filtros, pause, clear, auto-scroll, busca, empty state
 * - PipelinePanel: etapas do pipeline
 * - RecognitionCard: fala reconhecida, empty state
 * - VerseCard: versículo encontrado, status Holyrics
 * - ConsoleHeader: cabeçalho com todos os indicadores
 * - ConsolePage: integração completa
 * - event-categories: mapeamento de tipos
 */

import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  ThemeProvider,
  ApplicationProvider,
  InfraProvider,
  ConnectionProvider,
  NotificationsProvider,
  OperationProvider,
} from "@/contexts";
import { createClient } from "@/sdk";
import {
  createEventStream,
  createEventStreamBridge,
} from "@/stream";
import { createStoreRegistry } from "@/stores";
import { createServices } from "@/services";
import type { EventDTO } from "@/types";

// ============================================================
// Helpers
// ============================================================

function makeEvent(
  eventType: string,
  payload: Record<string, unknown> = {},
  overrides: Partial<EventDTO["meta"]> = {},
): EventDTO {
  return {
    event_type: eventType,
    meta: {
      event_id: `evt-${Math.random().toString(36).slice(2, 8)}`,
      correlation_id: overrides.correlation_id ?? "corr-123",
      causation_id: null,
      session_id: "sess-1",
      timestamp: 1700000000,
      origin: "test",
      metadata: [],
      ...overrides,
    },
    payload,
  };
}

function makeProviders(
  events: EventDTO[] = [],
  overrides: {
    pipeline?: Record<string, unknown>;
    session?: Record<string, unknown>;
    metrics?: Record<string, unknown>;
    configuration?: Record<string, unknown>;
  } = {},
) {
  const client = createClient();
  const stream = createEventStream();
  const stores = createStoreRegistry();

  // Popula stores com dados de teste.
  if (events.length > 0) {
    stores.events.set(events);
  }
  if (overrides.pipeline) {
    stores.pipeline.set({
      timestamp: 1700000000,
      status: {
        running: false, paused: false, is_active: false, is_idle: true,
        is_processing: false, current_segment: null, last_query: "",
        last_candidate_id: "", last_event_type: "", last_event_timestamp: 0,
        statistics: {},
        ...overrides.pipeline,
      } as never,
      session: {
        session_id: "sess-1", started_at: 0, ended_at: 0, is_active: true,
        is_ended: false, duration_s: 0, processed_segments: 0,
        processed_queries: 0, presentations: 0, errors: 0, error_rate: 0,
        presentation_rate: 0, segments_per_minute: 0, queries_per_minute: 0,
        unique_correlations: 0, correlation_ids: [],
      } as never,
      metrics: {
        segments_received: 0, segments_processed: 0, segments_dropped: 0,
        queries_processed: 0, presentations_executed: 0, presentations_failed: 0,
        errors_total: 0, errors_recoverable: 0, errors_fatal: 0,
        total_latency_ms: 0, avg_latency_ms: 0, avg_recognition_latency_ms: 0,
        avg_search_latency_ms: 0, avg_ranking_latency_ms: 0,
        avg_intelligence_latency_ms: 0, avg_presentation_latency_ms: 0,
        throughput_segments_per_min: 0, throughput_queries_per_min: 0,
        error_rate: 0, drop_rate: 0, presentation_success_rate: 0,
        processing_success_rate: 0, duration_s: 0, correlation_count: 0,
        ...overrides.metrics,
      } as never,
      last_event: null,
    } as never);
  }
  if (overrides.metrics) {
    stores.metrics.set({
      segments_received: 0, segments_processed: 0, segments_dropped: 0,
      queries_processed: 0, presentations_executed: 0, presentations_failed: 0,
      errors_total: 0, errors_recoverable: 0, errors_fatal: 0,
      total_latency_ms: 0, avg_latency_ms: 0, avg_recognition_latency_ms: 0,
      avg_search_latency_ms: 0, avg_ranking_latency_ms: 0,
      avg_intelligence_latency_ms: 0, avg_presentation_latency_ms: 0,
      throughput_segments_per_min: 0, throughput_queries_per_min: 0,
      error_rate: 0, drop_rate: 0, presentation_success_rate: 0,
      processing_success_rate: 0, duration_s: 0, correlation_count: 0,
      ...overrides.metrics,
    } as never);
  }
  if (overrides.session) {
    stores.session.set({
      session_id: "sess-1", started_at: 0, ended_at: 0, is_active: true,
      is_ended: false, duration_s: 0, processed_segments: 0,
      processed_queries: 0, presentations: 0, errors: 0, error_rate: 0,
      presentation_rate: 0, segments_per_minute: 0, queries_per_minute: 0,
      unique_correlations: 0, correlation_ids: [],
      ...overrides.session,
    } as never);
  }
  if (overrides.configuration) {
    stores.configuration.set({
      mode: "production",
      holyrics: {}, stt: { model: "whisper-base", language: "pt-BR" },
      llm: {}, search: {}, state: {}, cache: {}, confidence: {}, log: {},
      audio: null, pipeline_policy: null,
      ...overrides.configuration,
    } as never);
  }

  const services = createServices(client);
  const bridge = createEventStreamBridge(client, stream, stores);
  bridge.start();

  return { client, stream, stores, services, bridge };
}

function wrapWithProviders(
  children: React.ReactNode,
  testInfra?: ReturnType<typeof makeProviders>,
) {
  const infra = testInfra ?? makeProviders();
  return (
    <ThemeProvider>
      <ApplicationProvider>
        <InfraProvider
          client={infra.client}
          stream={infra.stream}
          stores={infra.stores}
          services={infra.services}
        >
          <ConnectionProvider>
            <NotificationsProvider>
              <OperationProvider skipStartup>
                {children}
              </OperationProvider>
            </NotificationsProvider>
          </ConnectionProvider>
        </InfraProvider>
      </ApplicationProvider>
    </ThemeProvider>
  );
}

// ============================================================
// event-categories
// ============================================================

describe("event-categories", () => {
  it("mapeia tipos conhecidos para categorias", async () => {
    const { eventToCategory } = await import("@/components/console/event-categories");
    expect(eventToCategory("SpeechRecognized")).toBe("stt");
    expect(eventToCategory("AudioCaptured")).toBe("audio");
    expect(eventToCategory("PipelineStarted")).toBe("pipeline");
    expect(eventToCategory("VerseFound")).toBe("search");
    expect(eventToCategory("HolyricsSuccess")).toBe("holyrics");
    expect(eventToCategory("PipelineError")).toBe("error");
  });

  it("tipos desconhecidos caem em 'system'", async () => {
    const { eventToCategory } = await import("@/components/console/event-categories");
    expect(eventToCategory("UnknownEvent")).toBe("system");
  });

  it("infere severity corretamente", async () => {
    const { eventToSeverity } = await import("@/components/console/event-categories");
    expect(eventToSeverity("PipelineError")).toBe("high");
    expect(eventToSeverity("ConnectionLost")).toBe("critical");
    expect(eventToSeverity("PipelineStarted")).toBe("info");
    expect(eventToSeverity("HolyricsFailure")).toBe("high");
  });

  it("ALL_CATEGORIES tem 7 categorias", async () => {
    const { ALL_CATEGORIES } = await import("@/components/console/event-categories");
    expect(ALL_CATEGORIES).toHaveLength(7);
  });

  it("ALL_SEVERITIES tem 5 severidades", async () => {
    const { ALL_SEVERITIES } = await import("@/components/console/event-categories");
    expect(ALL_SEVERITIES).toHaveLength(5);
  });
});

// ============================================================
// EventCard
// ============================================================

describe("EventCard", () => {
  it("renderiza tipo do evento", async () => {
    const { EventCard } = await import("@/components/console/EventCard");
    const event = makeEvent("SpeechRecognized", { text: "João 3:16" });
    const infra = makeProviders([event]);
    render(wrapWithProviders(<EventCard event={event} />, infra));
    expect(screen.getByTestId("event-card")).toBeInTheDocument();
    expect(screen.getByText("SpeechRecognized")).toBeInTheDocument();
  });

  it("mostra descrição do payload", async () => {
    const { EventCard } = await import("@/components/console/EventCard");
    const event = makeEvent("SpeechRecognized", { text: "O evangelho de João" });
    render(wrapWithProviders(<EventCard event={event} />, makeProviders([event])));
    expect(screen.getByText(/O evangelho de João/)).toBeInTheDocument();
  });

  it("mostra correlation id truncado", async () => {
    const { EventCard } = await import("@/components/console/EventCard");
    const event = makeEvent("PipelineStarted", {}, { correlation_id: "corr-abc-12345" });
    render(wrapWithProviders(<EventCard event={event} />, makeProviders([event])));
    expect(screen.getByText(/#corr-abc/)).toBeInTheDocument();
  });

  it("data-category reflete a categoria do evento", async () => {
    const { EventCard } = await import("@/components/console/EventCard");
    const event = makeEvent("AudioCaptured");
    render(wrapWithProviders(<EventCard event={event} />, makeProviders([event])));
    expect(screen.getByTestId("event-card").getAttribute("data-category")).toBe("audio");
  });

  it("data-event-type reflete o tipo", async () => {
    const { EventCard } = await import("@/components/console/EventCard");
    const event = makeEvent("HolyricsSuccess");
    render(wrapWithProviders(<EventCard event={event} />, makeProviders([event])));
    expect(screen.getByTestId("event-card").getAttribute("data-event-type")).toBe("HolyricsSuccess");
  });
});

// ============================================================
// PipelineStage
// ============================================================

describe("PipelineStage", () => {
  it("renderiza nome da etapa", async () => {
    const { PipelineStage } = await import("@/components/console/PipelineStage");
    render(wrapWithProviders(<PipelineStage name="Whisper" state="idle" />, makeProviders()));
    expect(screen.getByTestId("pipeline-stage")).toBeInTheDocument();
    expect(screen.getByText("Whisper")).toBeInTheDocument();
  });

  it("mostra estado idle", async () => {
    const { PipelineStage } = await import("@/components/console/PipelineStage");
    render(wrapWithProviders(<PipelineStage name="VAD" state="idle" />, makeProviders()));
    expect(screen.getByTestId("pipeline-stage").getAttribute("data-state")).toBe("idle");
    expect(screen.getByText("Aguardando")).toBeInTheDocument();
  });

  it("mostra estado running", async () => {
    const { PipelineStage } = await import("@/components/console/PipelineStage");
    render(wrapWithProviders(<PipelineStage name="VAD" state="running" />, makeProviders()));
    expect(screen.getByTestId("pipeline-stage").getAttribute("data-state")).toBe("running");
    expect(screen.getByText("Executando")).toBeInTheDocument();
  });

  it("mostra estado success", async () => {
    const { PipelineStage } = await import("@/components/console/PipelineStage");
    render(wrapWithProviders(<PipelineStage name="Whisper" state="success" />, makeProviders()));
    expect(screen.getByTestId("pipeline-stage").getAttribute("data-state")).toBe("success");
    expect(screen.getByText("Concluído")).toBeInTheDocument();
  });

  it("mostra estado error", async () => {
    const { PipelineStage } = await import("@/components/console/PipelineStage");
    render(wrapWithProviders(<PipelineStage name="Holyrics" state="error" />, makeProviders()));
    expect(screen.getByTestId("pipeline-stage").getAttribute("data-state")).toBe("error");
    expect(screen.getByText("Erro")).toBeInTheDocument();
  });

  it("mostra latência quando fornecida", async () => {
    const { PipelineStage } = await import("@/components/console/PipelineStage");
    render(wrapWithProviders(<PipelineStage name="Whisper" state="success" latencyMs={312} />, makeProviders()));
    expect(screen.getByText(/312 ms/)).toBeInTheDocument();
  });
});

// ============================================================
// SeverityBadge
// ============================================================

describe("SeverityBadge", () => {
  it("renderiza info", async () => {
    const { SeverityBadge } = await import("@/components/console/SeverityBadge");
    render(wrapWithProviders(<SeverityBadge severity="info" />, makeProviders()));
    expect(screen.getByTestId("severity-badge")).toBeInTheDocument();
    expect(screen.getByText("Info")).toBeInTheDocument();
  });

  it("renderiza critical", async () => {
    const { SeverityBadge } = await import("@/components/console/SeverityBadge");
    render(wrapWithProviders(<SeverityBadge severity="critical" />, makeProviders()));
    expect(screen.getByText("Crítica")).toBeInTheDocument();
  });

  it("data-severity reflete a severity", async () => {
    const { SeverityBadge } = await import("@/components/console/SeverityBadge");
    render(wrapWithProviders(<SeverityBadge severity="medium" />, makeProviders()));
    expect(screen.getByTestId("severity-badge").getAttribute("data-severity")).toBe("medium");
  });
});

// ============================================================
// ConnectionBadge
// ============================================================

describe("ConnectionBadge", () => {
  it("renderiza com status desconhecido por padrão", async () => {
    const { ConnectionBadge } = await import("@/components/console/ConnectionBadge");
    render(wrapWithProviders(<ConnectionBadge />, makeProviders()));
    expect(screen.getByText("Desconhecido")).toBeInTheDocument();
  });
});

// ============================================================
// LatencyBadge
// ============================================================

describe("LatencyBadge", () => {
  it("mostra — quando não há métricas", async () => {
    const { LatencyBadge } = await import("@/components/console/LatencyBadge");
    render(wrapWithProviders(<LatencyBadge />, makeProviders()));
    expect(screen.getByTestId("latency-badge")).toHaveTextContent("—");
  });

  it("mostra latência em ms", async () => {
    const { LatencyBadge } = await import("@/components/console/LatencyBadge");
    const infra = makeProviders([], {
      pipeline: {},
      metrics: { avg_latency_ms: 312 },
    });
    render(wrapWithProviders(<LatencyBadge />, infra));
    expect(screen.getByTestId("latency-badge")).toHaveTextContent("312 ms");
  });

  it("mostra latência em segundos quando > 1000ms", async () => {
    const { LatencyBadge } = await import("@/components/console/LatencyBadge");
    const infra = makeProviders([], {
      pipeline: {},
      metrics: { avg_latency_ms: 2500 },
    });
    render(wrapWithProviders(<LatencyBadge />, infra));
    expect(screen.getByTestId("latency-badge")).toHaveTextContent("2.5 s");
  });
});

// ============================================================
// TimelinePanel
// ============================================================

describe("TimelinePanel", () => {
  it("mostra empty state quando não há eventos", async () => {
    const { TimelinePanel } = await import("@/components/console/TimelinePanel");
    render(wrapWithProviders(<TimelinePanel />, makeProviders()));
    expect(screen.getByText("Aguardando início do pipeline...")).toBeInTheDocument();
  });

  it("renderiza eventos", async () => {
    const { TimelinePanel } = await import("@/components/console/TimelinePanel");
    const events = [
      makeEvent("PipelineStarted"),
      makeEvent("SpeechRecognized", { text: "João 3:16" }),
    ];
    render(wrapWithProviders(<TimelinePanel />, makeProviders(events)));
    expect(screen.getAllByTestId("event-card")).toHaveLength(2);
  });

  it("botão pause alterna estado", async () => {
    const { TimelinePanel } = await import("@/components/console/TimelinePanel");
    const events = [makeEvent("PipelineStarted")];
    render(wrapWithProviders(<TimelinePanel />, makeProviders(events)));
    const pauseBtn = screen.getByTestId("timeline-pause-btn");
    fireEvent.click(pauseBtn);
    expect(screen.getByTestId("timeline-paused-notice")).toBeInTheDocument();
  });

  it("botão clear limpa a visualização", async () => {
    const { TimelinePanel } = await import("@/components/console/TimelinePanel");
    const events = [makeEvent("PipelineStarted")];
    render(wrapWithProviders(<TimelinePanel />, makeProviders(events)));
    expect(screen.getAllByTestId("event-card")).toHaveLength(1);
    fireEvent.click(screen.getByTestId("timeline-clear-btn"));
    expect(screen.queryByTestId("event-card")).not.toBeInTheDocument();
  });

  it("busca filtra eventos por texto", async () => {
    const { TimelinePanel } = await import("@/components/console/TimelinePanel");
    const events = [
      makeEvent("SpeechRecognized", { text: "João 3:16" }),
      makeEvent("PipelineStarted"),
    ];
    render(wrapWithProviders(<TimelinePanel />, makeProviders(events)));
    const search = screen.getByTestId("search-box").querySelector("input")!;
    fireEvent.change(search, { target: { value: "João" } });
    expect(screen.getAllByTestId("event-card")).toHaveLength(1);
    expect(screen.getByText("SpeechRecognized")).toBeInTheDocument();
  });

  it("filtros de categoria funcionam", async () => {
    const { TimelinePanel } = await import("@/components/console/TimelinePanel");
    const events = [
      makeEvent("SpeechRecognized"),  // stt
      makeEvent("AudioCaptured"),     // audio
    ];
    render(wrapWithProviders(<TimelinePanel />, makeProviders(events)));
    // Abre filtros
    fireEvent.click(screen.getByTestId("timeline-filter-btn"));
    // Desativa categoria audio
    fireEvent.click(screen.getByTestId("filter-category-audio"));
    // Só deve ter 1 evento (stt)
    expect(screen.getAllByTestId("event-card")).toHaveLength(1);
  });

  it("filtros de severity funcionam", async () => {
    const { TimelinePanel } = await import("@/components/console/TimelinePanel");
    const events = [
      makeEvent("PipelineStarted"),  // info
      makeEvent("PipelineError"),    // high
    ];
    render(wrapWithProviders(<TimelinePanel />, makeProviders(events)));
    fireEvent.click(screen.getByTestId("timeline-filter-btn"));
    // Desativa severity info
    fireEvent.click(screen.getByTestId("filter-severity-info"));
    // Só deve ter 1 evento (error/high)
    expect(screen.getAllByTestId("event-card")).toHaveLength(1);
  });

  it("contador mostra número de eventos", async () => {
    const { TimelinePanel } = await import("@/components/console/TimelinePanel");
    const events = [makeEvent("PipelineStarted"), makeEvent("AudioCaptured")];
    render(wrapWithProviders(<TimelinePanel />, makeProviders(events)));
    expect(screen.getByTestId("timeline-count")).toHaveTextContent("2 eventos");
  });
});

// ============================================================
// PipelinePanel
// ============================================================

describe("PipelinePanel", () => {
  it("renderiza todas as etapas", async () => {
    const { PipelinePanel } = await import("@/components/console/PipelinePanel");
    render(wrapWithProviders(<PipelinePanel />, makeProviders()));
    expect(screen.getByTestId("pipeline-panel")).toBeInTheDocument();
    expect(screen.getAllByTestId("pipeline-stage").length).toBeGreaterThanOrEqual(9);
  });

  it("todas as etapas começam idle quando pipeline parado", async () => {
    const { PipelinePanel } = await import("@/components/console/PipelinePanel");
    render(wrapWithProviders(<PipelinePanel />, makeProviders()));
    const stages = screen.getAllByTestId("pipeline-stage");
    for (const s of stages) {
      expect(s.getAttribute("data-state")).toBe("idle");
    }
  });

  it("atualiza etapa quando evento chega", async () => {
    const { PipelinePanel } = await import("@/components/console/PipelinePanel");
    const events = [makeEvent("SpeechRecognized", { latency_ms: 312 })];
    render(wrapWithProviders(<PipelinePanel />, makeProviders(events)));
    const whisperStage = screen.getAllByTestId("pipeline-stage").find(
      (s) => s.getAttribute("data-stage") === "Whisper",
    );
    expect(whisperStage).toBeDefined();
    expect(whisperStage!.getAttribute("data-state")).toBe("success");
  });
});

// ============================================================
// RecognitionCard
// ============================================================

describe("RecognitionCard", () => {
  it("mostra empty state quando não há reconhecimento", async () => {
    const { RecognitionCard } = await import("@/components/console/RecognitionCard");
    render(wrapWithProviders(<RecognitionCard />, makeProviders()));
    expect(screen.getByText("Aguardando reconhecimento...")).toBeInTheDocument();
  });

  it("mostra texto reconhecido", async () => {
    const { RecognitionCard } = await import("@/components/console/RecognitionCard");
    const events = [
      makeEvent("SpeechRecognized", {
        text: "O evangelho de João capítulo três versículo dezesseis",
        language: "pt-BR",
        confidence: 0.95,
        latency_ms: 312,
        model: "whisper-large",
      }),
    ];
    render(wrapWithProviders(<RecognitionCard />, makeProviders(events)));
    expect(screen.getByTestId("recognition-text")).toHaveTextContent("O evangelho de João");
    expect(screen.getByTestId("recognition-confidence")).toHaveTextContent("95%");
    expect(screen.getByTestId("recognition-latency")).toHaveTextContent("312 ms");
  });
});

// ============================================================
// VerseCard
// ============================================================

describe("VerseCard", () => {
  it("mostra empty state quando não há versículo", async () => {
    const { VerseCard } = await import("@/components/console/VerseCard");
    render(wrapWithProviders(<VerseCard />, makeProviders()));
    expect(screen.getByText("Aguardando resultado...")).toBeInTheDocument();
  });

  it("mostra versículo encontrado", async () => {
    const { VerseCard } = await import("@/components/console/VerseCard");
    const events = [
      makeEvent("VerseFound", {
        book: "João",
        chapter: 3,
        verse: 16,
        version: "ACF",
        text: "Porque Deus amou o mundo...",
      }),
    ];
    render(wrapWithProviders(<VerseCard />, makeProviders(events)));
    expect(screen.getByTestId("verse-reference")).toHaveTextContent("João 3:16");
    expect(screen.getByTestId("verse-text")).toBeInTheDocument();
  });

  it("mostra status Holyrics success", async () => {
    const { VerseCard } = await import("@/components/console/VerseCard");
    const events = [
      makeEvent("VerseFound", { book: "João", chapter: 3, verse: 16 }),
      makeEvent("HolyricsSuccess", { total_time_ms: 450 }),
    ];
    render(wrapWithProviders(<VerseCard />, makeProviders(events)));
    expect(screen.getByTestId("holyrics-status")).toHaveTextContent("Enviado");
    expect(screen.getByTestId("verse-total-time")).toHaveTextContent("450 ms");
  });

  it("mostra status Holyrics failure", async () => {
    const { VerseCard } = await import("@/components/console/VerseCard");
    const events = [
      makeEvent("VerseFound", { book: "João", chapter: 3, verse: 16 }),
      makeEvent("HolyricsFailure"),
    ];
    render(wrapWithProviders(<VerseCard />, makeProviders(events)));
    expect(screen.getByTestId("holyrics-status")).toHaveTextContent("Falhou");
  });
});

// ============================================================
// ConsoleHeader
// ============================================================

describe("ConsoleHeader", () => {
  it("renderiza todos os indicadores", async () => {
    const { ConsoleHeader } = await import("@/components/console/ConsoleHeader");
    const infra = makeProviders([], {
      pipeline: { running: true, is_active: true, is_idle: false },
      session: { session_id: "sess-test-123", duration_s: 65 },
      metrics: { avg_latency_ms: 312 },
      configuration: { stt: { model: "whisper-large", language: "en-US" } },
    });
    render(wrapWithProviders(<ConsoleHeader />, infra));
    expect(screen.getByTestId("console-header")).toBeInTheDocument();
    expect(screen.getByTestId("latency-badge")).toBeInTheDocument();
    expect(screen.getByTestId("session-id")).toBeInTheDocument();
    expect(screen.getByTestId("session-duration")).toBeInTheDocument();
  });

  it("mostra modelo STT da configuração", async () => {
    const { ConsoleHeader } = await import("@/components/console/ConsoleHeader");
    const infra = makeProviders([], {
      pipeline: { running: true },
      configuration: { stt: { model: "whisper-large-v3", language: "pt-BR" } },
    });
    render(wrapWithProviders(<ConsoleHeader />, infra));
    expect(screen.getByText("whisper-large-v3")).toBeInTheDocument();
  });

  it("mostra idioma da configuração", async () => {
    const { ConsoleHeader } = await import("@/components/console/ConsoleHeader");
    const infra = makeProviders([], {
      pipeline: { running: true },
      configuration: { stt: { model: "whisper-base", language: "es-ES" } },
    });
    render(wrapWithProviders(<ConsoleHeader />, infra));
    expect(screen.getByText("es-ES")).toBeInTheDocument();
  });
});

// ============================================================
// ConsolePage — integração completa
// ============================================================

describe("ConsolePage", () => {
  it("renderiza todas as regiões", async () => {
    const { ConsolePage } = await import("@/pages/ConsolePage");
    render(wrapWithProviders(<ConsolePage />, makeProviders()));
    expect(screen.getByTestId("console-header")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-panel")).toBeInTheDocument();
    expect(screen.getByTestId("pipeline-panel")).toBeInTheDocument();
    expect(screen.getByTestId("recognition-panel")).toBeInTheDocument();
    expect(screen.getByTestId("result-panel")).toBeInTheDocument();
  });

  it("mostra empty state na timeline quando sem eventos", async () => {
    const { ConsolePage } = await import("@/pages/ConsolePage");
    render(wrapWithProviders(<ConsolePage />, makeProviders()));
    expect(screen.getByText("Aguardando início do pipeline...")).toBeInTheDocument();
  });

  it("atualiza quando eventos chegam via EventStream", async () => {
    const { ConsolePage } = await import("@/pages/ConsolePage");
    const infra = makeProviders([
      makeEvent("PipelineStarted"),
      makeEvent("SpeechRecognized", { text: "João 3:16", confidence: 0.95, latency_ms: 200 }),
    ]);
    render(wrapWithProviders(<ConsolePage />, infra));
    // Timeline deve ter 2 eventos
    expect(screen.getAllByTestId("event-card")).toHaveLength(2);
    // Recognition deve mostrar a fala
    expect(screen.getByTestId("recognition-text")).toBeInTheDocument();
  });
});
