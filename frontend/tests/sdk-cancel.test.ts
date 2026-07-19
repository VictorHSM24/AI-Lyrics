import { describe, it, expect } from "vitest";
import {
  createCancelSource,
  canceledToken,
  raceCancel,
  NEVER_CANCEL,
} from "@/sdk";
import { PresentationError } from "@/sdk";

describe("CancelToken", () => {
  it("inicia não cancelado", () => {
    const source = createCancelSource();
    expect(source.token.canceled).toBe(false);
    expect(source.token.reason).toBeNull();
  });

  it("cancela com razão", () => {
    const source = createCancelSource();
    source.cancel("motivo");
    expect(source.token.canceled).toBe(true);
    expect(source.token.reason).toBe("motivo");
  });

  it("cancela sem razão", () => {
    const source = createCancelSource();
    source.cancel();
    expect(source.token.canceled).toBe(true);
    expect(source.token.reason).toBeNull();
  });

  it("onCancel executa callback", () => {
    const source = createCancelSource();
    let called = false;
    let reason: string | null = null;
    source.token.onCancel((r) => {
      called = true;
      reason = r;
    });
    source.cancel("test");
    expect(called).toBe(true);
    expect(reason).toBe("test");
  });

  it("onCancel executa imediatamente se já cancelado", () => {
    const source = createCancelSource();
    source.cancel("already");
    let called = false;
    let reason: string | null = null;
    source.token.onCancel((r) => {
      called = true;
      reason = r;
    });
    expect(called).toBe(true);
    expect(reason).toBe("already");
  });

  it("onCancel retorna função de dispose", () => {
    const source = createCancelSource();
    let called = false;
    const dispose = source.token.onCancel(() => {
      called = true;
    });
    dispose();
    source.cancel("test");
    expect(called).toBe(false);
  });

  it("throwIfCanceled não lança se não cancelado", () => {
    const source = createCancelSource();
    expect(() => source.token.throwIfCanceled()).not.toThrow();
  });

  it("throwIfCanceled lança PresentationError se cancelado", () => {
    const source = createCancelSource();
    source.cancel("test");
    expect(() => source.token.throwIfCanceled()).toThrow(PresentationError);
    try {
      source.token.throwIfCanceled();
    } catch (e) {
      expect(e).toBeInstanceOf(PresentationError);
      expect((e as PresentationError).code).toBe("SDK_CANCELED");
    }
  });

  it("cancelamento é idempotente", () => {
    const source = createCancelSource();
    let count = 0;
    source.token.onCancel(() => {
      count++;
    });
    source.cancel("first");
    source.cancel("second");
    expect(count).toBe(1);
  });
});

describe("NEVER_CANCEL", () => {
  it("nunca está cancelado", () => {
    expect(NEVER_CANCEL.canceled).toBe(false);
    expect(NEVER_CANCEL.reason).toBeNull();
  });

  it("throwIfCanceled não lança", () => {
    expect(() => NEVER_CANCEL.throwIfCanceled()).not.toThrow();
  });

  it("onCancel retorna noop dispose", () => {
    const dispose = NEVER_CANCEL.onCancel(() => {});
    expect(typeof dispose).toBe("function");
    expect(() => dispose()).not.toThrow();
  });
});

describe("canceledToken", () => {
  it("cria token já cancelado", () => {
    const t = canceledToken("razão");
    expect(t.canceled).toBe(true);
    expect(t.reason).toBe("razão");
  });
});

describe("raceCancel", () => {
  it("cancela quando qualquer token cancelar", () => {
    const s1 = createCancelSource();
    const s2 = createCancelSource();
    const raced = raceCancel(s1.token, s2.token);
    expect(raced.canceled).toBe(false);
    s2.cancel("s2");
    expect(raced.canceled).toBe(true);
    expect(raced.reason).toBe("s2");
  });

  it("cancela imediatamente se um já está cancelado", () => {
    const s1 = createCancelSource();
    s1.cancel("already");
    const s2 = createCancelSource();
    const raced = raceCancel(s1.token, s2.token);
    expect(raced.canceled).toBe(true);
  });
});
