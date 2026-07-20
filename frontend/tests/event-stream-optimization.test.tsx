/**
 * Testes do Sprint 17.2 — Event Stream Optimization (Frontend).
 *
 * Valida que:
 * - Eventos de telemetria (audio.level) NÃO entram no EventStore (Timeline).
 * - Eventos operacionais (PipelineStarted, etc.) entram no EventStore.
 * - Ambos são dispatchados aos handlers de domínio.
 * - isTelemetryEvent / isOperationalEvent funcionam corretamente.
 * - O VU Meter continua recebendo audio.level via AudioStore.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import {
  ThemeProvider,
  ApplicationProvider,
  InfraProvider,
  ConnectionProvider,
  NotificationsProvider,
  OperationProvider,
} from "@/contexts";
import { createClient } from "@/sdk";
import { createEventStream, createEventStreamBridge } from "@/stream";
import { createStoreRegistry } from "@/stores";
import { createServices } from "@/services";
import type { EventDTO } from "@/types";
import {
  isTelemetryEvent,
  isOperationalEvent,
  isTelemetryType,
  TELEMETRY_EVENT_TYPES,
} from "@/components/console/event-categories";
import { EventStreamBridge } from "@/stream/bridge";
import { ReferencePanel } from "@/components/operational";

// ============================================================
// Helpers
// ============================================================

function makeEvent(
  eventType: string,
  payload: Record<string, unknown> = {},
  category: "operational" | "telemetry" = "operational",
): EventDTO {
  return {
    event_type: eventType,
    meta: {
      event_id: `evt-${Math.random().toString(36).slice(2, 8)}`,
      correlation_id: "corr-123",
      causation_id: null,
      session_id: "sess-1",
      timestamp: Date.now() / 1000,
      origin: "test",
      metadata: [],
    },
    payload,
    category,
  };
}

function makeInfra() {
  const client = createClient();
  const stream = createEventStream();
  const stores = createStoreRegistry();
  const services = createServices(client);
  const bridge = createEventStreamBridge(client, stream, stores);
  bridge.start();
  return { client, stream, stores, services, bridge };
}

function renderWithProviders() {
  const infra = makeInfra();
  const result = render(
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
                <div data-testid="test-container" />
              </OperationProvider>
            </NotificationsProvider>
          </ConnectionProvider>
        </InfraProvider>
      </ApplicationProvider>
    </ThemeProvider>,
  );
  return { ...result, infra };
}

// ============================================================
// Testes — event-categories helpers
// ============================================================

describe("Sprint 17.2 — Event Categories", () => {
  describe("isTelemetryEvent", () => {
    it("retorna true para evento com category='telemetry'", () => {
      const dto = makeEvent("audio.level", { rms: 0.5 }, "telemetry");
      expect(isTelemetryEvent(dto)).toBe(true);
    });

    it("retorna false para evento com category='operational'", () => {
      const dto = makeEvent("PipelineStarted", {}, "operational");
      expect(isTelemetryEvent(dto)).toBe(false);
    });

    it("retorna false para evento sem category (legacy)", () => {
      const dto: EventDTO = {
        event_type: "PipelineStarted",
        meta: {
          event_id: "e1",
          correlation_id: "c1",
          causation_id: null,
          session_id: "s1",
          timestamp: 0,
          origin: "test",
          metadata: [],
        },
        payload: {},
      };
      expect(isTelemetryEvent(dto)).toBe(false);
    });
  });

  describe("isOperationalEvent", () => {
    it("retorna true para evento com category='operational'", () => {
      const dto = makeEvent("PipelineStarted", {}, "operational");
      expect(isOperationalEvent(dto)).toBe(true);
    });

    it("retorna false para evento com category='telemetry'", () => {
      const dto = makeEvent("audio.level", { rms: 0.5 }, "telemetry");
      expect(isOperationalEvent(dto)).toBe(false);
    });
  });

  describe("isTelemetryType", () => {
    it("retorna true para tipos conhecidos de telemetria", () => {
      expect(isTelemetryType("audio.level")).toBe(true);
      expect(isTelemetryType("cpu.usage")).toBe(true);
      expect(isTelemetryType("gpu.usage")).toBe(true);
      expect(isTelemetryType("ram.usage")).toBe(true);
    });

    it("retorna false para tipos operacionais", () => {
      expect(isTelemetryType("PipelineStarted")).toBe(false);
      expect(isTelemetryType("SpeechTranscribed")).toBe(false);
    });

    it("retorna true quando category='telemetry' mesmo para tipo desconhecido", () => {
      expect(isTelemetryType("UnknownType", "telemetry")).toBe(true);
    });
  });

  describe("TELEMETRY_EVENT_TYPES", () => {
    it("contém audio.level", () => {
      expect(TELEMETRY_EVENT_TYPES.has("audio.level")).toBe(true);
    });

    it("contém futuros tipos de telemetria", () => {
      expect(TELEMETRY_EVENT_TYPES.has("cpu.usage")).toBe(true);
      expect(TELEMETRY_EVENT_TYPES.has("gpu.usage")).toBe(true);
      expect(TELEMETRY_EVENT_TYPES.has("ram.usage")).toBe(true);
      expect(TELEMETRY_EVENT_TYPES.has("latency")).toBe(true);
      expect(TELEMETRY_EVENT_TYPES.has("fps")).toBe(true);
    });
  });
});

// ============================================================
// Testes — EventStreamBridge filtering
// ============================================================

describe("Sprint 17.2 — EventStreamBridge Telemetry Filtering", () => {
  let bridge: EventStreamBridge;

  beforeEach(() => {
    cleanup();
    const client = createClient();
    const stream = createEventStream();
    const stores = createStoreRegistry();
    bridge = createEventStreamBridge(client, stream, stores);
    bridge.start();
  });

  afterEach(() => {
    bridge.stop();
    cleanup();
  });

  it("eventos operacionais entram no EventStore", () => {
    const opEvent = makeEvent("PipelineStarted", {}, "operational");
    // Usa o stream diretamente.
    const streamPrivate = (bridge as unknown as { stream: { publish: (e: unknown) => void } }).stream;
    // Publica via stream — o bridge consome.
    streamPrivate.publish({ type: "event", payload: opEvent, id: "1" });

    // Aguarda processamento síncrono.
    const stores = (bridge as unknown as { stores: { events: { current: { data: EventDTO[] } | null } } }).stores;
    const events = stores.events.current?.data ?? [];
    expect(events.some((e) => e.event_type === "PipelineStarted")).toBe(true);
  });

  it("eventos de telemetria NÃO entram no EventStore", () => {
    const telEvent = makeEvent("audio.level", { rms: 0.5 }, "telemetry");
    const streamPrivate = (bridge as unknown as { stream: { publish: (e: unknown) => void } }).stream;
    streamPrivate.publish({ type: "event", payload: telEvent, id: "1" });

    const stores = (bridge as unknown as { stores: { events: { current: { data: EventDTO[] } | null } } }).stores;
    const events = stores.events.current?.data ?? [];
    expect(events.some((e) => e.event_type === "audio.level")).toBe(false);
    expect(events.length).toBe(0);
  });

  it("mix de eventos — apenas operacionais no EventStore", () => {
    const streamPrivate = (bridge as unknown as { stream: { publish: (e: unknown) => void } }).stream;
    // Publica 3 operational + 5 telemetry.
    const opEvents = [
      makeEvent("PipelineStarted", {}, "operational"),
      makeEvent("SpeechTranscribed", { text: "hello" }, "operational"),
      makeEvent("PipelineStopped", {}, "operational"),
    ];
    const telEvents = Array.from({ length: 5 }, (_, i) =>
      makeEvent("audio.level", { rms: i * 0.1 }, "telemetry"),
    );
    [...opEvents, ...telEvents].forEach((e, i) => {
      streamPrivate.publish({ type: "event", payload: e, id: String(i) });
    });

    const stores = (bridge as unknown as { stores: { events: { current: { data: EventDTO[] } | null } } }).stores;
    const events = stores.events.current?.data ?? [];
    // Apenas 3 operational events.
    expect(events.length).toBe(3);
    expect(events.every((e) => e.category !== "telemetry")).toBe(true);
    // Nenhum audio.level.
    expect(events.every((e) => e.event_type !== "audio.level")).toBe(true);
  });

  it("eventos de telemetria ainda atualizam AudioStore (VU Meter)", () => {
    const streamPrivate = (bridge as unknown as { stream: { publish: (e: unknown) => void } }).stream;
    const telEvent = makeEvent("audio.level", { rms: 0.75, peak: 0.9 }, "telemetry");
    streamPrivate.publish({ type: "event", payload: telEvent, id: "1" });

    const stores = (bridge as unknown as { stores: { audio: { current: { data: { rms: number; peak: number } | null } } } }).stores;
    const audio = stores.audio.current?.data;
    // O VU Meter deve ter recebido o rms/peak.
    expect(audio).toBeTruthy();
    expect(audio?.rms).toBe(0.75);
    expect(audio?.peak).toBe(0.9);
  });
});

// ============================================================
// Testes — Render smoke test
// ============================================================

describe("Sprint 17.2 — Render smoke", () => {
  beforeEach(() => cleanup());
  afterEach(() => cleanup());

  it("renderiza sem erros com providers", () => {
    const { getByTestId } = renderWithProviders();
    expect(getByTestId("test-container")).toBeTruthy();
  });
});

// ============================================================
// Testes — WebSocket contract (formato real do backend)
// ============================================================

/**
 * Estes testes simulam o formato REAL que o backend transmite via WebSocket.
 *
 * O backend usa EventModel.from_dto() → WsEventModel → JSON.
 * O JSON inclui: type, event: { event_type, meta, payload, category }
 *
 * O frontend recebe via WebSocketTransport → Client → Bridge → EventStream → Stores.
 *
 * Sprint 17.2 bug fix: EventModel.from_dto() agora inclui `category`.
 * Antes do fix, `category` era descartado e audio.level aparecia na Timeline.
 */
describe("Sprint 17.2 — WebSocket Contract (formato real)", () => {
  /**
   * Simula o JSON exato que o backend envia via WebSocket.
   * Este é o formato após o fix do EventModel.from_dto().
   */
  function makeWsEvent(
    eventType: string,
    payload: Record<string, unknown>,
    category: "operational" | "telemetry" = "operational",
  ): EventDTO {
    return {
      event_type: eventType,
      meta: {
        event_id: `evt-${Math.random().toString(36).slice(2, 8)}`,
        correlation_id: `corr-${Math.random().toString(36).slice(2, 8)}`,
        causation_id: null,
        session_id: "sess-1",
        timestamp: Date.now() / 1000,
        origin: "test",
        metadata: [],
      },
      payload,
      category,
    };
  }

  let bridge: EventStreamBridge;

  beforeEach(() => {
    cleanup();
    const client = createClient();
    const stream = createEventStream();
    const stores = createStoreRegistry();
    bridge = createEventStreamBridge(client, stream, stores);
    bridge.start();
  });

  afterEach(() => {
    bridge.stop();
    cleanup();
  });

  it("audio.level com category=telemetry NÃO entra no EventStore (formato real)", () => {
    const streamPrivate = (bridge as unknown as { stream: { publish: (e: unknown) => void } }).stream;
    const audioEvent = makeWsEvent(
      "audio.level",
      { rms: 0.5, peak: 0.8, timestamp: 1.0 },
      "telemetry",
    );
    streamPrivate.publish({ type: "event", payload: audioEvent, id: "1" });

    const stores = (bridge as unknown as { stores: { events: { current: { data: EventDTO[] } | null } } }).stores;
    const events = stores.events.current?.data ?? [];
    expect(events.length).toBe(0);
  });

  it("ReferenceDetected com category=operational entra no EventStore (formato real)", () => {
    const streamPrivate = (bridge as unknown as { stream: { publish: (e: unknown) => void } }).stream;
    const refEvent = makeWsEvent(
      "ReferenceDetected",
      {
        intent: "OPEN_REFERENCE",
        book: "João",
        book_id: 43,
        chapter: 15,
        verse_start: 2,
        verse_end: 2,
        confidence: 0.95,
        raw_text: "joão capítulo quinze versículo dois",
        normalized_text: "joao 15:2",
      },
      "operational",
    );
    streamPrivate.publish({ type: "event", payload: refEvent, id: "1" });

    const stores = (bridge as unknown as { stores: { events: { current: { data: EventDTO[] } | null } } }).stores;
    const events = stores.events.current?.data ?? [];
    expect(events.length).toBe(1);
    expect(events[0].event_type).toBe("ReferenceDetected");
    expect(events[0].category).toBe("operational");
  });

  it("ReferenceDetected atualiza ReferenceStore com confidence (formato real)", () => {
    const streamPrivate = (bridge as unknown as { stream: { publish: (e: unknown) => void } }).stream;
    const refEvent = makeWsEvent(
      "ReferenceDetected",
      {
        intent: "OPEN_REFERENCE",
        book: "João",
        book_id: 43,
        chapter: 15,
        verse_start: 2,
        verse_end: 2,
        confidence: 0.95,
        raw_text: "joão capítulo quinze versículo dois",
        normalized_text: "joao 15:2",
      },
      "operational",
    );
    streamPrivate.publish({ type: "event", payload: refEvent, id: "1" });

    const stores = (bridge as unknown as {
      stores: {
        reference: {
          current: { data: { current: { confidence: number; book: string; chapter: number } | null } } | null;
        };
      };
    }).stores;
    const ref = stores.reference.current?.data?.current;
    expect(ref).toBeTruthy();
    expect(ref?.confidence).toBe(0.95);
    expect(ref?.book).toBe("João");
    expect(ref?.chapter).toBe(15);
  });

  it("fluxo completo: PipelineStarted → SpeechTranscribed → ReferenceDetected sem erros", () => {
    const streamPrivate = (bridge as unknown as { stream: { publish: (e: unknown) => void } }).stream;

    // Simula o fluxo completo do Sprint 17.
    const events: EventDTO[] = [
      makeWsEvent("PipelineStarted", {}, "operational"),
      makeWsEvent("SpeechStarted", {}, "operational"),
      makeWsEvent("SpeechEnded", {}, "operational"),
      makeWsEvent("SpeechSegmentCreated", { duration_ms: 2000 }, "operational"),
      makeWsEvent("SpeechTranscribing", {}, "operational"),
      makeWsEvent(
        "SpeechTranscribed",
        {
          text: "joão capítulo quinze versículo dois",
          language: "pt",
          confidence: 0.87,
          latency_ms: 120,
          duration_ms: 2000,
        },
        "operational",
      ),
      makeWsEvent(
        "ReferenceDetected",
        {
          intent: "OPEN_REFERENCE",
          book: "João",
          book_id: 43,
          chapter: 15,
          verse_start: 2,
          verse_end: 2,
          confidence: 0.95,
          raw_text: "joão capítulo quinze versículo dois",
          normalized_text: "joao 15:2",
        },
        "operational",
      ),
      // audio.level misturado no fluxo — não deve entrar no EventStore.
      makeWsEvent("audio.level", { rms: 0.3, peak: 0.5, timestamp: 1.0 }, "telemetry"),
    ];

    events.forEach((e, i) => {
      streamPrivate.publish({ type: "event", payload: e, id: String(i) });
    });

    const stores = (bridge as unknown as {
      stores: {
        events: { current: { data: EventDTO[] } | null };
        reference: {
          current: { data: { current: { confidence: number; book: string; chapter: number } | null } } | null;
        };
        transcript: {
          current: { data: { entries: { confidence: number; text: string }[] } } | null;
        };
      };
    }).stores;

    // EventStore: 7 operational events (sem audio.level).
    const eventStoreEvents = stores.events.current?.data ?? [];
    expect(eventStoreEvents.length).toBe(7);
    expect(eventStoreEvents.every((e) => e.event_type !== "audio.level")).toBe(true);

    // ReferenceStore: current com confidence.
    const ref = stores.reference.current?.data?.current;
    expect(ref).toBeTruthy();
    expect(ref?.confidence).toBe(0.95);
    expect(ref?.book).toBe("João");
    expect(ref?.chapter).toBe(15);

    // TranscriptStore: entry com confidence.
    const transcriptEntries = stores.transcript.current?.data?.entries ?? [];
    expect(transcriptEntries.length).toBe(1);
    expect(transcriptEntries[0].confidence).toBe(0.87);
    expect(transcriptEntries[0].text).toBe("joão capítulo quinze versículo dois");
  });
});

// ============================================================
// Testes — ReferencePanel com ReferenceDetected (Problema 2)
// ============================================================

/**
 * Sprint 17.2 — Bug fix: ReferencePanel usava `ref` como prop name.
 *
 * Em React 18, `ref` é uma prop especial interceptada pelo React.
 * Function components NÃO recebem `ref` como prop regular.
 * O componente CurrentReference recebia `entry = undefined`, causando:
 *   "Cannot read properties of undefined (reading 'confidence')"
 *
 * Fix: renomear `ref` para `entry`.
 */

// Mock do useReference para retornar uma referência detectada.
const mockReferenceEntry = {
  id: "corr-123",
  intent: "OPEN_REFERENCE",
  book: "João",
  bookId: 43,
  chapter: 15,
  verseStart: 2,
  verseEnd: 2,
  confidence: 0.95,
  rawText: "joão capítulo quinze versículo dois",
  normalizedText: "joao 15:2",
  timestamp: 1700000000,
};

vi.mock("@/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks")>();
  return {
    ...actual,
    useReference: () => ({
      current: mockReferenceEntry,
      entries: [mockReferenceEntry],
      invalid: null,
      loading: false,
    }),
  };
});

describe("Sprint 17.2 — ReferencePanel com ReferenceDetected (Problema 2)", () => {
  beforeEach(() => cleanup());
  afterEach(() => cleanup());

  it("ReferencePanel renderiza referência sem erro de confidence", () => {
    // Se o bug `ref` existisse, o render lançaria:
    //   "Cannot read properties of undefined (reading 'confidence')"
    // Após o fix, o componente renderiza corretamente.
    const { getByTestId, getByText } = render(
      <ThemeProvider>
        <ApplicationProvider>
          <InfraProvider>
            <ConnectionProvider>
              <NotificationsProvider>
                <OperationProvider skipStartup>
                  <ReferencePanel />
                </OperationProvider>
              </NotificationsProvider>
            </ConnectionProvider>
          </InfraProvider>
        </ApplicationProvider>
      </ThemeProvider>,
    );

    expect(getByTestId("reference-current")).toBeTruthy();
    // "joao 15:2" aparece tanto na referência atual quanto no histórico.
    const normalized = screen.getAllByText("joao 15:2");
    expect(normalized.length).toBeGreaterThanOrEqual(1);
    expect(getByText("João")).toBeTruthy();
  });
});
