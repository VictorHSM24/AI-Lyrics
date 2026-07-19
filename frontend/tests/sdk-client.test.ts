import { describe, it, expect } from "vitest";
import {
  createClient,
  getDefaultClient,
  setDefaultClient,
  ClientImpl,
  createStubTransport,
  CURRENT_API_VERSION,
} from "@/sdk";
import { createCancelSource } from "@/sdk";

describe("Client SDK", () => {
  it("createClient retorna Client", () => {
    const c = createClient();
    expect(c).toBeDefined();
    expect(typeof c.connect).toBe("function");
    expect(typeof c.disconnect).toBe("function");
    expect(typeof c.subscribe).toBe("function");
    expect(typeof c.call).toBe("function");
  });

  it("status inicial é idle (stub transport)", () => {
    const c = createClient();
    // stub transport começa em idle
    expect(c.status).toBe("idle");
  });

  it("expectedApiVersion é CURRENT_API_VERSION", () => {
    const c = createClient();
    expect(c.expectedApiVersion).toEqual(CURRENT_API_VERSION);
  });

  it("connect não lança (stub)", async () => {
    const c = createClient();
    await expect(c.connect()).resolves.toBeUndefined();
  });

  it("disconnect não lança (stub)", async () => {
    const c = createClient();
    await c.connect();
    await expect(c.disconnect()).resolves.toBeUndefined();
  });

  it("call rejeita com notConfigured (stub transport)", async () => {
    const c = createClient();
    await expect(c.call("test", {})).rejects.toThrow();
    try {
      await c.call("test", {});
    } catch (e) {
      expect(e).toBeInstanceOf(Error);
      expect((e as Error).message).toContain("não configurado");
    }
  });

  it("call aceita CancelToken", async () => {
    const c = createClient();
    const source = createCancelSource();
    source.cancel("test");
    await expect(c.call("test", {}, { cancel: source.token })).rejects.toThrow();
  });

  it("call aceita timeoutMs customizado", async () => {
    const c = createClient();
    // stub rejeita com notConfigured antes do timeout
    await expect(c.call("test", {}, { timeoutMs: 100 })).rejects.toThrow();
  });

  it("subscribe registra listener", () => {
    const c = createClient();
    let events = 0;
    const unsub = c.subscribe(() => {
      events++;
    });
    expect(typeof unsub).toBe("function");
    unsub();
  });
});

describe("StubTransport", () => {
  it("createStubTransport retorna transporte", () => {
    const t = createStubTransport();
    expect(t).toBeDefined();
    expect(typeof t.open).toBe("function");
    expect(typeof t.close).toBe("function");
    expect(typeof t.subscribe).toBe("function");
    expect(typeof t.request).toBe("function");
  });

  it("status inicial é idle", () => {
    const t = createStubTransport();
    expect(t.status).toBe("idle");
  });

  it("open muda status para disconnected", async () => {
    const t = createStubTransport();
    await t.open();
    expect(t.status).toBe("disconnected");
  });

  it("request retorna erro notConfigured", async () => {
    const t = createStubTransport();
    const result = await t.request({
      id: "r1",
      method: "test",
      params: {},
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("SDK_NOT_CONFIGURED");
    }
  });

  it("subscribe retorna função de dispose", () => {
    const t = createStubTransport();
    const unsub = t.subscribe(() => {});
    expect(typeof unsub).toBe("function");
    expect(() => unsub()).not.toThrow();
  });
});

describe("Default client", () => {
  it("getDefaultClient retorna singleton", () => {
    const c1 = getDefaultClient();
    const c2 = getDefaultClient();
    expect(c1).toBe(c2);
  });

  it("setDefaultClient substitui singleton", () => {
    const original = getDefaultClient();
    const custom = createClient();
    setDefaultClient(custom);
    expect(getDefaultClient()).toBe(custom);
    setDefaultClient(original);
  });
});

describe("ClientImpl", () => {
  it("pode ser instanciado diretamente", () => {
    const c = new ClientImpl();
    expect(c).toBeDefined();
    expect(c.status).toBe("idle");
  });

  it("pode ser instanciado com config customizado", () => {
    const c = new ClientImpl(createStubTransport(), {
      defaultTimeoutMs: 5000,
    });
    expect(c).toBeDefined();
  });
});
