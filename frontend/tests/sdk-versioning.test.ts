import { describe, it, expect } from "vitest";
import {
  CURRENT_API_VERSION,
  apiVersionToString,
  parseApiVersion,
  compareApiVersion,
  versioned,
  isCompatible,
  type ApiVersion,
} from "@/sdk";

describe("ApiVersion", () => {
  it("CURRENT_API_VERSION é 0.1.0-foundation", () => {
    expect(CURRENT_API_VERSION.major).toBe(0);
    expect(CURRENT_API_VERSION.minor).toBe(1);
    expect(CURRENT_API_VERSION.patch).toBe(0);
    expect(CURRENT_API_VERSION.pre).toBe("foundation");
  });

  it("apiVersionToString sem pre", () => {
    const v: ApiVersion = { major: 1, minor: 2, patch: 3, pre: null };
    expect(apiVersionToString(v)).toBe("1.2.3");
  });

  it("apiVersionToString com pre", () => {
    const v: ApiVersion = { major: 1, minor: 2, patch: 3, pre: "beta.1" };
    expect(apiVersionToString(v)).toBe("1.2.3-beta.1");
  });

  it("parseApiVersion parseia versão completa", () => {
    const v = parseApiVersion("1.2.3-beta.1");
    expect(v).not.toBeNull();
    expect(v!.major).toBe(1);
    expect(v!.minor).toBe(2);
    expect(v!.patch).toBe(3);
    expect(v!.pre).toBe("beta.1");
  });

  it("parseApiVersion parseia versão sem pre", () => {
    const v = parseApiVersion("2.0.0");
    expect(v).not.toBeNull();
    expect(v!.pre).toBeNull();
  });

  it("parseApiVersion retorna null para string inválida", () => {
    expect(parseApiVersion("invalid")).toBeNull();
    expect(parseApiVersion("1.2")).toBeNull();
    expect(parseApiVersion("1.2.3.4")).toBeNull();
  });

  it("compareApiVersion: versões iguais", () => {
    const a: ApiVersion = { major: 1, minor: 2, patch: 3, pre: null };
    const b: ApiVersion = { major: 1, minor: 2, patch: 3, pre: null };
    expect(compareApiVersion(a, b)).toBe(0);
  });

  it("compareApiVersion: major diferente", () => {
    const a: ApiVersion = { major: 1, minor: 0, patch: 0, pre: null };
    const b: ApiVersion = { major: 2, minor: 0, patch: 0, pre: null };
    expect(compareApiVersion(a, b)).toBeLessThan(0);
    expect(compareApiVersion(b, a)).toBeGreaterThan(0);
  });

  it("compareApiVersion: minor diferente", () => {
    const a: ApiVersion = { major: 1, minor: 1, patch: 0, pre: null };
    const b: ApiVersion = { major: 1, minor: 2, patch: 0, pre: null };
    expect(compareApiVersion(a, b)).toBeLessThan(0);
  });

  it("compareApiVersion: release > pre-release", () => {
    const release: ApiVersion = { major: 1, minor: 0, patch: 0, pre: null };
    const pre: ApiVersion = { major: 1, minor: 0, patch: 0, pre: "beta.1" };
    expect(compareApiVersion(release, pre)).toBeGreaterThan(0);
    expect(compareApiVersion(pre, release)).toBeLessThan(0);
  });

  it("compareApiVersion: pre-release ordering", () => {
    const a: ApiVersion = { major: 1, minor: 0, patch: 0, pre: "alpha" };
    const b: ApiVersion = { major: 1, minor: 0, patch: 0, pre: "beta" };
    expect(compareApiVersion(a, b)).toBeLessThan(0);
  });
});

describe("Versioned", () => {
  it("versioned cria envelope com versão atual", () => {
    const v = versioned({ name: "test" });
    expect(v.api).toEqual(CURRENT_API_VERSION);
    expect(v.payload).toEqual({ name: "test" });
  });

  it("versioned aceita versão customizada", () => {
    const custom: ApiVersion = { major: 1, minor: 0, patch: 0, pre: null };
    const v = versioned({ x: 1 }, custom);
    expect(v.api).toBe(custom);
  });

  it("isCompatible: mesma major", () => {
    const v = versioned({ x: 1 }, { major: 0, minor: 5, patch: 0, pre: null });
    expect(isCompatible(v, CURRENT_API_VERSION)).toBe(true);
  });

  it("isCompatible: major diferente", () => {
    const v = versioned({ x: 1 }, { major: 1, minor: 0, patch: 0, pre: null });
    expect(isCompatible(v, CURRENT_API_VERSION)).toBe(false);
  });
});
