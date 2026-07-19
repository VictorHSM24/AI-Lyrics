import { describe, it, expect } from "vitest";
import {
  VISUAL_STATUSES,
  STATUS_CONFIG,
  healthToVisualStatus,
} from "@/shared/status";
import {
  formatTimestamp,
  formatDuration,
  formatNumber,
  formatPercent,
  formatLatency,
  truncate,
  generateId,
  cn,
} from "@/utils";

describe("status.ts", () => {
  it("VISUAL_STATUSES contém todos os 10 status", () => {
    expect(VISUAL_STATUSES).toHaveLength(10);
    expect(VISUAL_STATUSES).toContain("healthy");
    expect(VISUAL_STATUSES).toContain("warning");
    expect(VISUAL_STATUSES).toContain("error");
    expect(VISUAL_STATUSES).toContain("offline");
    expect(VISUAL_STATUSES).toContain("unknown");
    expect(VISUAL_STATUSES).toContain("processing");
    expect(VISUAL_STATUSES).toContain("paused");
    expect(VISUAL_STATUSES).toContain("running");
    expect(VISUAL_STATUSES).toContain("success");
    expect(VISUAL_STATUSES).toContain("info");
  });

  it("STATUS_CONFIG tem config para todos os status", () => {
    for (const status of VISUAL_STATUSES) {
      expect(STATUS_CONFIG[status]).toBeDefined();
      expect(STATUS_CONFIG[status].label).toBeTruthy();
      expect(STATUS_CONFIG[status].colorClass).toBeTruthy();
      expect(STATUS_CONFIG[status].dotClass).toBeTruthy();
      expect(STATUS_CONFIG[status].bgClass).toBeTruthy();
      expect(STATUS_CONFIG[status].borderClass).toBeTruthy();
    }
  });

  it("healthToVisualStatus converte corretamente", () => {
    expect(healthToVisualStatus("healthy")).toBe("healthy");
    expect(healthToVisualStatus("degraded")).toBe("warning");
    expect(healthToVisualStatus("unhealthy")).toBe("error");
    expect(healthToVisualStatus("unknown")).toBe("unknown");
  });
});

describe("utils.ts", () => {
  it("formatTimestamp formata timestamp válido", () => {
    const result = formatTimestamp(1700000000);
    expect(result).not.toBe("—");
    expect(result.length).toBeGreaterThan(0);
  });

  it("formatTimestamp retorna traço para timestamp inválido", () => {
    expect(formatTimestamp(0)).toBe("—");
    expect(formatTimestamp(-1)).toBe("—");
  });

  it("formatDuration formata segundos", () => {
    expect(formatDuration(0)).toBe("0s");
    expect(formatDuration(30)).toBe("30s");
    expect(formatDuration(60)).toBe("1m");
    expect(formatDuration(3600)).toBe("1h");
    expect(formatDuration(3661)).toBe("1h 1m 1s");
  });

  it("formatNumber formata com separadores", () => {
    expect(formatNumber(1000)).toBe("1.000");
    expect(formatNumber(1000000)).toBe("1.000.000");
  });

  it("formatPercent formata percentual", () => {
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(0.5)).toBe("50.0%");
    expect(formatPercent(0.853, 2)).toBe("85.30%");
  });

  it("formatLatency formata latência", () => {
    expect(formatLatency(0)).toBe("—");
    expect(formatLatency(500)).toBe("500ms");
    expect(formatLatency(1500)).toBe("1.50s");
  });

  it("truncate trunca strings longas", () => {
    expect(truncate("hello world", 5)).toBe("hell…");
    expect(truncate("short", 10)).toBe("short");
  });

  it("generateId gera IDs únicos", () => {
    const id1 = generateId("test");
    const id2 = generateId("test");
    expect(id1).not.toBe(id2);
    expect(id1).toContain("test-");
  });

  it("cn junta classes condicionalmente", () => {
    expect(cn("a", "b", "c")).toBe("a b c");
    expect(cn("a", false, null, undefined, "b")).toBe("a b");
  });
});
