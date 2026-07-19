/**
 * Testes do RestTransport — usa fetch mock.
 *
 * Valida:
 * - Serialização JSON
 * - Mapeamento método → endpoint
 * - Timeout via AbortController
 * - Cancelamento via CancelToken
 * - Tratamento de erros HTTP
 * - Versionamento (espera Versioned<T>)
 * - Listeners de status e erro
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  createRestTransport,
  RestTransport,
  createCancelSource,
  type TransportConfig,
} from "@/sdk";

// Mock global fetch.
const fetchMock = vi.fn();
const originalFetch = global.fetch;

function makeVersionedResponse(payload: unknown) {
  return {
    api: { major: 0, minor: 1, patch: 0, pre: "foundation" },
    payload,
  };
}

function mockFetchSuccess(payload: unknown) {
  fetchMock.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => makeVersionedResponse(payload),
  });
}

function mockFetchError(status: number, body: unknown) {
  fetchMock.mockResolvedValueOnce({
    ok: false,
    status,
    url: "http://test/api",
    json: async () => body,
  });
}

beforeEach(() => {
  global.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
});

afterEach(() => {
  global.fetch = originalFetch;
});

const config: TransportConfig = {
  url: "http://localhost:8000",
  defaultTimeoutMs: 5000,
};

describe("RestTransport", () => {
  it("createRestTransport retorna Transport", () => {
    const t = createRestTransport(config);
    expect(t).toBeDefined();
    expect(typeof t.open).toBe("function");
    expect(typeof t.close).toBe("function");
    expect(typeof t.request).toBe("function");
    expect(typeof t.subscribe).toBe("function");
  });

  it("status inicial é idle", () => {
    const t = createRestTransport(config);
    expect(t.status).toBe("idle");
  });

  it("open muda status para connected", async () => {
    const t = createRestTransport(config);
    await t.open();
    expect(t.status).toBe("connected");
  });

  it("close muda status para disconnected", async () => {
    const t = createRestTransport(config);
    await t.open();
    await t.close();
    expect(t.status).toBe("disconnected");
  });

  it("request retorna Versioned<T> em sucesso", async () => {
    mockFetchSuccess({ running: false, paused: false });
    const t = createRestTransport(config);
    await t.open();
    const result = await t.request({ id: "r1", method: "pipeline.getStatus", params: {} });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.result.payload).toEqual({ running: false, paused: false });
    }
  });

  it("request mapeia método para endpoint correto", async () => {
    mockFetchSuccess({});
    const t = createRestTransport(config);
    await t.open();
    await t.request({ id: "r1", method: "pipeline.getStatus", params: {} });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/pipeline/status",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("request adiciona query params", async () => {
    mockFetchSuccess({ events: [] });
    const t = createRestTransport(config);
    await t.open();
    await t.request({
      id: "r1",
      method: "events.getByCorrelation",
      params: { correlation_id: "c1" },
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/events/by-correlation?correlation_id=c1",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("request retorna erro para método desconhecido", async () => {
    const t = createRestTransport(config);
    await t.open();
    const result = await t.request({ id: "r1", method: "unknown.method", params: {} });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("SERVICE_NOT_FOUND");
    }
  });

  it("request retorna erro para HTTP 500", async () => {
    mockFetchError(500, { code: "UNKNOWN", message: "Internal error" });
    const t = createRestTransport(config);
    await t.open();
    const result = await t.request({ id: "r1", method: "pipeline.getStatus", params: {} });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("UNKNOWN");
      expect(result.error.recoverable).toBe(true); // 5xx é recoverable
    }
  });

  it("request retorna erro para HTTP 404", async () => {
    mockFetchError(404, { code: "SERVICE_NOT_FOUND", message: "Not found" });
    const t = createRestTransport(config);
    await t.open();
    const result = await t.request({ id: "r1", method: "pipeline.getStatus", params: {} });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("SERVICE_NOT_FOUND");
      expect(result.error.recoverable).toBe(false); // 4xx não é recoverable
    }
  });

  it("request sem URL retorna notConfigured", async () => {
    const t = createRestTransport({ url: "", defaultTimeoutMs: 5000 });
    await t.open();
    const result = await t.request({ id: "r1", method: "pipeline.getStatus", params: {} });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("SDK_NOT_CONFIGURED");
    }
  });

  it("subscribe recebe eventos de status", async () => {
    const t = createRestTransport(config);
    const events: string[] = [];
    t.subscribe((ev) => {
      if (ev.type === "status") events.push(ev.status);
    });
    await t.open();
    expect(events).toContain("connected");
  });

  it("subscribe recebe eventos de erro", async () => {
    mockFetchError(500, { code: "UNKNOWN", message: "err" });
    const t = createRestTransport(config);
    await t.open();
    let errorReceived = false;
    t.subscribe((ev) => {
      if (ev.type === "error") errorReceived = true;
    });
    await t.request({ id: "r1", method: "pipeline.getStatus", params: {} });
    expect(errorReceived).toBe(true);
  });

  it("subscribe retorna função de dispose", () => {
    const t = createRestTransport(config);
    const unsub = t.subscribe(() => {});
    expect(typeof unsub).toBe("function");
    expect(() => unsub()).not.toThrow();
  });

  it("RestTransport pode ser instanciado diretamente", () => {
    const t = new RestTransport(config);
    expect(t).toBeDefined();
    expect(t.status).toBe("idle");
  });

  it("request com AbortError (timeout) retorna TRANSPORT_TIMEOUT", async () => {
    // Simula fetch que aborta.
    fetchMock.mockImplementationOnce(() => {
      return new Promise((_, reject) => {
        const err = new DOMException("Aborted", "AbortError");
        setTimeout(() => reject(err), 10);
      });
    });
    const t = createRestTransport({ url: "http://test", defaultTimeoutMs: 50 });
    await t.open();
    const result = await t.request({ id: "r1", method: "pipeline.getStatus", params: {}, timeoutMs: 50 });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("TRANSPORT_TIMEOUT");
    }
  });

  it("request com CancelToken cancelado retorna SDK_CANCELED", async () => {
    fetchMock.mockImplementationOnce(() => {
      return new Promise((_, reject) => {
        setTimeout(() => reject(new DOMException("Aborted", "AbortError")), 50);
      });
    });
    const t = createRestTransport(config);
    await t.open();
    const source = createCancelSource();
    source.cancel("test");
    const result = await t.request({
      id: "r1",
      method: "pipeline.getStatus",
      params: {},
      cancel: source.token,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("SDK_CANCELED");
    }
  });
});
