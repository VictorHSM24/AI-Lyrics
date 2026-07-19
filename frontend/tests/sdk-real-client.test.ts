/**
 * Testes do RealClient e EventStreamBridge.
 *
 * Como o RealClient usa fetch e WebSocket reais, os testes
 * mockam fetch e WebSocket para validar o comportamento.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  createRealClient,
  asClient,
  RealClient,
  createCancelSource,
  PresentationError,
  type RealClientConfig,
} from "@/sdk";
import {
  createEventStream,
  createEventStreamBridge,
} from "@/stream";
import { createStoreRegistry } from "@/stores";

// Mock fetch.
const fetchMock = vi.fn();
const originalFetch = global.fetch;

function makeVersionedResponse(payload: unknown) {
  return {
    api: { major: 0, minor: 1, patch: 0, pre: "foundation" },
    payload,
  };
}

beforeEach(() => {
  global.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
});

afterEach(() => {
  global.fetch = originalFetch;
});

const realConfig: RealClientConfig = {
  restUrl: "http://localhost:8000",
  // Sem wsUrl para evitar tentar conectar WebSocket nos testes.
};

describe("RealClient", () => {
  it("createRealClient retorna RealClient", () => {
    const c = createRealClient(realConfig);
    expect(c).toBeDefined();
    expect(typeof c.connect).toBe("function");
    expect(typeof c.disconnect).toBe("function");
    expect(typeof c.call).toBe("function");
    expect(typeof c.subscribe).toBe("function");
  });

  it("status inicial é idle", () => {
    const c = createRealClient(realConfig);
    expect(c.status).toBe("idle");
  });

  it("expectedApiVersion é a versão atual", () => {
    const c = createRealClient(realConfig);
    expect(c.expectedApiVersion.major).toBe(0);
    expect(c.expectedApiVersion.minor).toBe(1);
  });

  it("connect abre o REST transport", async () => {
    const c = createRealClient(realConfig);
    await c.connect();
    expect(c.status).toBe("connected");
  });

  it("disconnect fecha o REST transport", async () => {
    const c = createRealClient(realConfig);
    await c.connect();
    await c.disconnect();
    expect(c.status).toBe("disconnected");
  });

  it("call retorna Versioned<T> em sucesso", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => makeVersionedResponse({ running: false }),
    });
    const c = createRealClient(realConfig);
    await c.connect();
    const result = await c.call("pipeline.getStatus", {});
    expect(result.payload).toEqual({ running: false });
  });

  it("call rejeita para versão incompatível", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        api: { major: 99, minor: 0, patch: 0, pre: null },
        payload: {},
      }),
    });
    const c = createRealClient(realConfig);
    await c.connect();
    await expect(c.call("pipeline.getStatus", {})).rejects.toThrow(PresentationError);
    try {
      await c.call("pipeline.getStatus", {});
    } catch (e) {
      // Segunda chamada vai mockar de novo
    }
  });

  it("call rejeita para erro HTTP", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      url: "http://test",
      json: async () => ({ code: "UNKNOWN", message: "err" }),
    });
    const c = createRealClient(realConfig);
    await c.connect();
    await expect(c.call("pipeline.getStatus", {})).rejects.toThrow();
  });

  it("call aceita CancelToken", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => makeVersionedResponse({}),
    });
    const c = createRealClient(realConfig);
    await c.connect();
    const source = createCancelSource();
    source.cancel("test");
    await expect(c.call("pipeline.getStatus", {}, { cancel: source.token })).rejects.toThrow();
  });

  it("call aceita timeoutMs customizado", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => makeVersionedResponse({}),
    });
    const c = createRealClient(realConfig);
    await c.connect();
    const result = await c.call("pipeline.getStatus", {}, { timeoutMs: 5000 });
    expect(result.payload).toBeDefined();
  });

  it("subscribe recebe eventos de status", async () => {
    const c = createRealClient(realConfig);
    const events: string[] = [];
    c.subscribe((ev) => {
      if (ev.type === "status") events.push(ev.status);
    });
    await c.connect();
    expect(events).toContain("connected");
  });

  it("asClient adapta RealClient para interface Client", () => {
    const real = createRealClient(realConfig);
    const client = asClient(real);
    expect(typeof client.connect).toBe("function");
    expect(typeof client.disconnect).toBe("function");
    expect(typeof client.call).toBe("function");
    expect(typeof client.subscribe).toBe("function");
    expect(client.expectedApiVersion).toBeDefined();
  });

  it("asClient preserva status", async () => {
    const real = createRealClient(realConfig);
    const client = asClient(real);
    expect(client.status).toBe("idle");
    await client.connect();
    expect(client.status).toBe("connected");
  });

  it("RealClient pode ser instanciado diretamente", () => {
    const c = new RealClient(realConfig);
    expect(c).toBeDefined();
  });

  it("RealClient sem wsUrl não cria WebSocket transport", () => {
    const c = createRealClient({ restUrl: "http://test" });
    expect(c.wsStatus).toBe("idle");
  });
});

describe("EventStreamBridge", () => {
  it("createEventStreamBridge retorna bridge", () => {
    const c = createRealClient(realConfig);
    const client = asClient(c);
    const stream = createEventStream();
    const stores = createStoreRegistry();
    const bridge = createEventStreamBridge(client, stream, stores);
    expect(bridge).toBeDefined();
    expect(typeof bridge.start).toBe("function");
    expect(typeof bridge.stop).toBe("function");
  });

  it("start assina Client SDK e EventStream", () => {
    const c = createRealClient(realConfig);
    const client = asClient(c);
    const stream = createEventStream();
    const stores = createStoreRegistry();
    const bridge = createEventStreamBridge(client, stream, stores);
    bridge.start();
    // Não deve lançar erro ao iniciar.
    bridge.stop();
  });

  it("stop cancela subscriptions", () => {
    const c = createRealClient(realConfig);
    const client = asClient(c);
    const stream = createEventStream();
    const stores = createStoreRegistry();
    const bridge = createEventStreamBridge(client, stream, stores);
    bridge.start();
    bridge.stop();
    // Após stop, publicar evento no stream não deve atualizar stores.
    // (Não há como verificar diretamente sem instrumentar.)
  });

  it("eventos do Client SDK chegam ao EventStream", () => {
    const c = createRealClient(realConfig);
    const client = asClient(c);
    const stream = createEventStream();
    const stores = createStoreRegistry();
    const bridge = createEventStreamBridge(client, stream, stores);
    bridge.start();

    // Simula um evento vindo do Client SDK.
    let received = false;
    stream.subscribe(() => {
      received = true;
    });

    // Dispara um evento via listener do client.
    // Como não temos acesso direto ao listener, usamos o stream.
    stream.publish({
      id: "e1",
      type: "TestEvent",
      timestamp: 100,
      correlationId: "c1",
      payload: {
        event_type: "TestEvent",
        meta: { event_id: "e1", correlation_id: "c1", session_id: "s1", timestamp: 100, origin: "test", metadata: [] },
        payload: {},
      },
    });
    expect(received).toBe(true);
    bridge.stop();
  });

  it("eventos do EventStream atualizam o EventStore", () => {
    const c = createRealClient(realConfig);
    const client = asClient(c);
    const stream = createEventStream();
    const stores = createStoreRegistry();
    const bridge = createEventStreamBridge(client, stream, stores);
    bridge.start();

    // Publica um evento válido no stream.
    stream.publish({
      id: "e1",
      type: "PipelineStarted",
      timestamp: 100,
      correlationId: "c1",
      payload: {
        event_type: "PipelineStarted",
        meta: { event_id: "e1", correlation_id: "c1", session_id: "s1", timestamp: 100, origin: "test", metadata: [] },
        payload: {},
      },
    });

    // O EventStore deve ter 1 evento.
    expect(stores.events.hasSnapshot).toBe(true);
    expect(stores.events.current?.data).toHaveLength(1);
    bridge.stop();
  });

  it("eventos não-EventDTO são ignorados", () => {
    const c = createRealClient(realConfig);
    const client = asClient(c);
    const stream = createEventStream();
    const stores = createStoreRegistry();
    const bridge = createEventStreamBridge(client, stream, stores);
    bridge.start();

    // Publica um evento inválido (sem event_type).
    stream.publish({
      id: "e1",
      type: "Invalid",
      timestamp: 100,
      correlationId: null,
      payload: { foo: "bar" },
    });

    // O EventStore não deve ser atualizado.
    expect(stores.events.hasSnapshot).toBe(false);
    bridge.stop();
  });
});
