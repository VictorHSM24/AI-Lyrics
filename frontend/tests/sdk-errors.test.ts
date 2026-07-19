import { describe, it, expect } from "vitest";
import {
  PresentationError,
  canceled,
  timeout,
  notConfigured,
  ok,
  err,
  isOk,
  isErr,
  ERROR_SEVERITIES,
  type Result,
} from "@/sdk";

describe("PresentationError", () => {
  it("cria com parâmetros mínimos", () => {
    const e = new PresentationError({
      code: "UNKNOWN",
      message: "Teste",
    });
    expect(e.code).toBe("UNKNOWN");
    expect(e.message).toBe("Teste");
    expect(e.recoverable).toBe(false);
    expect(e.severity).toBe("medium");
    expect(e.correlationId).toBeNull();
    expect(e.details).toEqual({});
    expect(e.cause).toBeNull();
    expect(e.timestamp).toBeGreaterThan(0);
  });

  it("cria com parâmetros completos", () => {
    const cause = new PresentationError({ code: "UNKNOWN", message: "causa" });
    const e = new PresentationError({
      code: "TRANSPORT_TIMEOUT",
      message: "Timeout",
      details: { ms: 5000 },
      recoverable: true,
      severity: "high",
      correlationId: "c1",
      timestamp: 100.0,
      cause,
    });
    expect(e.code).toBe("TRANSPORT_TIMEOUT");
    expect(e.details).toEqual({ ms: 5000 });
    expect(e.recoverable).toBe(true);
    expect(e.severity).toBe("high");
    expect(e.correlationId).toBe("c1");
    expect(e.timestamp).toBe(100.0);
    expect(e.cause).toBe(cause);
  });

  it("é uma instância de Error", () => {
    const e = new PresentationError({ code: "UNKNOWN", message: "x" });
    expect(e).toBeInstanceOf(Error);
    expect(e.name).toBe("PresentationError");
  });

  it("toDTO retorna objeto serializável", () => {
    const e = new PresentationError({
      code: "SDK_NOT_CONFIGURED",
      message: "Não configurado",
      correlationId: "c1",
    });
    const dto = e.toDTO();
    expect(dto.code).toBe("SDK_NOT_CONFIGURED");
    expect(dto.message).toBe("Não configurado");
    expect(dto.correlationId).toBe("c1");
    expect(dto.cause).toBeNull();
  });

  it("toDTO preserva causa", () => {
    const cause = new PresentationError({ code: "UNKNOWN", message: "causa" });
    const e = new PresentationError({
      code: "TRANSPORT_DISCONNECTED",
      message: "Disconectado",
      cause,
    });
    const dto = e.toDTO();
    expect(dto.cause).not.toBeNull();
    expect(dto.cause!.code).toBe("UNKNOWN");
  });

  it("fromUnknown preserva PresentationError", () => {
    const original = new PresentationError({ code: "UNKNOWN", message: "original" });
    const result = PresentationError.fromUnknown(original);
    expect(result).toBe(original);
  });

  it("fromUnknown converte Error genérico", () => {
    const original = new Error("genérico");
    const result = PresentationError.fromUnknown(original);
    expect(result).toBeInstanceOf(PresentationError);
    expect(result.code).toBe("UNKNOWN");
    expect(result.message).toBe("genérico");
  });

  it("fromUnknown converte string", () => {
    const result = PresentationError.fromUnknown("string error");
    expect(result.message).toBe("string error");
    expect(result.code).toBe("UNKNOWN");
  });

  it("fromUnknown aceita overrides", () => {
    const result = PresentationError.fromUnknown("x", {
      code: "TRANSPORT_TIMEOUT",
      severity: "high",
    });
    expect(result.code).toBe("TRANSPORT_TIMEOUT");
    expect(result.severity).toBe("high");
  });

  it("fromEvent usa metadados do evento", () => {
    const meta = {
      event_id: "e1",
      correlation_id: "corr-1",
      causation_id: null,
      session_id: "s1",
      timestamp: 200.0,
      origin: "test",
      metadata: [],
    };
    const e = PresentationError.fromEvent(meta, {
      code: "SERVICE_UNAVAILABLE",
      message: "Service down",
    });
    expect(e.correlationId).toBe("corr-1");
    expect(e.timestamp).toBe(200.0);
    expect(e.code).toBe("SERVICE_UNAVAILABLE");
  });
});

describe("Error helpers", () => {
  it("canceled cria erro de cancelamento", () => {
    const e = canceled("c1");
    expect(e.code).toBe("SDK_CANCELED");
    expect(e.recoverable).toBe(true);
    expect(e.severity).toBe("info");
    expect(e.correlationId).toBe("c1");
  });

  it("timeout cria erro de timeout", () => {
    const e = timeout(5000, "c1");
    expect(e.code).toBe("TRANSPORT_TIMEOUT");
    expect(e.recoverable).toBe(true);
    expect(e.details).toEqual({ timeout_ms: 5000 });
    expect(e.correlationId).toBe("c1");
  });

  it("notConfigured cria erro de SDK não configurado", () => {
    const e = notConfigured();
    expect(e.code).toBe("SDK_NOT_CONFIGURED");
    expect(e.recoverable).toBe(false);
    expect(e.severity).toBe("low");
  });
});

describe("Result", () => {
  it("ok cria Result de sucesso", () => {
    const r = ok(42);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value).toBe(42);
  });

  it("err cria Result de erro", () => {
    const e = new PresentationError({ code: "UNKNOWN", message: "x" });
    const r = err(e);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe(e);
  });

  it("isOk identifica sucesso", () => {
    const r: Result<number> = ok(1);
    expect(isOk(r)).toBe(true);
    expect(isErr(r)).toBe(false);
  });

  it("isErr identifica erro", () => {
    const r: Result<number> = err(new PresentationError({ code: "UNKNOWN", message: "x" }));
    expect(isErr(r)).toBe(true);
    expect(isOk(r)).toBe(false);
  });
});

describe("ERROR_SEVERITIES", () => {
  it("contém 5 severidades", () => {
    expect(ERROR_SEVERITIES).toHaveLength(5);
    expect(ERROR_SEVERITIES).toContain("info");
    expect(ERROR_SEVERITIES).toContain("low");
    expect(ERROR_SEVERITIES).toContain("medium");
    expect(ERROR_SEVERITIES).toContain("high");
    expect(ERROR_SEVERITIES).toContain("critical");
  });
});
