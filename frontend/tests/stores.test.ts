import { describe, it, expect } from "vitest";
import {
  createSnapshotStore,
  SnapshotStoreImpl,
  createStoreRegistry,
  createPipelineStore,
  createHealthStore,
  createMetricsStore,
  createSessionStore,
  createConfigurationStore,
  createDiagnosticsStore,
  createLogStore,
  createReplayStore,
  createEventStore,
  type Snapshot,
} from "@/stores";

describe("SnapshotStore", () => {
  it("createSnapshotStore retorna store", () => {
    const s = createSnapshotStore<number>();
    expect(s).toBeDefined();
    expect(s.current).toBeNull();
    expect(s.version).toBe(0);
    expect(s.hasSnapshot).toBe(false);
  });

  it("SnapshotStoreImpl pode ser instanciado diretamente", () => {
    const s = new SnapshotStoreImpl<string>();
    expect(s).toBeDefined();
    expect(s.hasSnapshot).toBe(false);
  });

  it("set define estado e incrementa versão", () => {
    const s = createSnapshotStore<number>();
    s.set(42);
    expect(s.hasSnapshot).toBe(true);
    expect(s.current).not.toBeNull();
    expect(s.current!.data).toBe(42);
    expect(s.current!.version).toBe(1);
    expect(s.current!.timestamp).toBeGreaterThan(0);
    expect(s.version).toBe(1);
  });

  it("set incrementa versão a cada chamada", () => {
    const s = createSnapshotStore<number>();
    s.set(1);
    expect(s.version).toBe(1);
    s.set(2);
    expect(s.version).toBe(2);
    s.set(3);
    expect(s.version).toBe(3);
  });

  it("update aplica função patch", () => {
    const s = createSnapshotStore<number>();
    s.set(10);
    s.update((prev) => (prev ?? 0) + 5);
    expect(s.current!.data).toBe(15);
  });

  it("update com prev null", () => {
    const s = createSnapshotStore<number>();
    s.update((prev) => prev ?? 100);
    expect(s.current!.data).toBe(100);
  });

  it("clear remove estado", () => {
    const s = createSnapshotStore<number>();
    s.set(42);
    s.clear();
    expect(s.hasSnapshot).toBe(false);
    expect(s.current).toBeNull();
  });

  it("subscribe notifica em mudanças", () => {
    const s = createSnapshotStore<number>();
    let notified: Snapshot<number> | null = null;
    s.subscribe((snap) => {
      notified = snap;
    });
    s.set(42);
    expect(notified).not.toBeNull();
    expect(notified!.data).toBe(42);
  });

  it("subscribe retorna função de unsubscribe", () => {
    const s = createSnapshotStore<number>();
    let count = 0;
    const sub = s.subscribe(() => {
      count++;
    });
    s.set(1);
    expect(count).toBe(1);
    sub.unsubscribe();
    s.set(2);
    expect(count).toBe(1);
  });

  it("listener que lança não propaga erro", () => {
    const s = createSnapshotStore<number>();
    s.subscribe(() => {
      throw new Error("listener error");
    });
    let otherNotified = false;
    s.subscribe(() => {
      otherNotified = true;
    });
    expect(() => s.set(42)).not.toThrow();
    expect(otherNotified).toBe(true);
  });
});

describe("StoreRegistry", () => {
  it("createStoreRegistry cria todos os stores", () => {
    const r = createStoreRegistry();
    expect(r.pipeline).toBeDefined();
    expect(r.health).toBeDefined();
    expect(r.metrics).toBeDefined();
    expect(r.session).toBeDefined();
    expect(r.configuration).toBeDefined();
    expect(r.diagnostics).toBeDefined();
    expect(r.logs).toBeDefined();
    expect(r.replay).toBeDefined();
    expect(r.events).toBeDefined();
  });

  it("todos os stores iniciam sem snapshot", () => {
    const r = createStoreRegistry();
    expect(r.pipeline.hasSnapshot).toBe(false);
    expect(r.health.hasSnapshot).toBe(false);
    expect(r.metrics.hasSnapshot).toBe(false);
    expect(r.session.hasSnapshot).toBe(false);
    expect(r.configuration.hasSnapshot).toBe(false);
    expect(r.diagnostics.hasSnapshot).toBe(false);
    expect(r.logs.hasSnapshot).toBe(false);
    expect(r.replay.hasSnapshot).toBe(false);
    expect(r.events.hasSnapshot).toBe(false);
  });
});

describe("Domain Stores", () => {
  it("createPipelineStore tem setStatus", () => {
    const s = createPipelineStore();
    expect(typeof s.setStatus).toBe("function");
  });

  it("createHealthStore funciona como DomainStore", () => {
    const s = createHealthStore();
    s.set({ timestamp: 0, components: [], component_count: 0, healthy_count: 0, unhealthy_count: 0, all_healthy: true });
    expect(s.hasSnapshot).toBe(true);
  });

  it("createMetricsStore funciona como DomainStore", () => {
    const s = createMetricsStore();
    s.set({ segments_received: 0, segments_processed: 0, segments_dropped: 0, queries_processed: 0, presentations_executed: 0, presentations_failed: 0, errors_total: 0, errors_recoverable: 0, errors_fatal: 0, total_latency_ms: 0, avg_latency_ms: 0, avg_recognition_latency_ms: 0, avg_search_latency_ms: 0, avg_ranking_latency_ms: 0, avg_intelligence_latency_ms: 0, avg_presentation_latency_ms: 0, throughput_segments_per_min: 0, throughput_queries_per_min: 0, error_rate: 0, drop_rate: 0, presentation_success_rate: 0, processing_success_rate: 0, duration_s: 0, correlation_count: 0 });
    expect(s.hasSnapshot).toBe(true);
  });

  it("createSessionStore funciona como DomainStore", () => {
    const s = createSessionStore();
    expect(s.hasSnapshot).toBe(false);
  });

  it("createConfigurationStore funciona como DomainStore", () => {
    const s = createConfigurationStore();
    expect(s.hasSnapshot).toBe(false);
  });

  it("createDiagnosticsStore funciona como DomainStore", () => {
    const s = createDiagnosticsStore();
    s.set([]);
    expect(s.current!.data).toEqual([]);
  });

  it("createLogStore funciona como DomainStore", () => {
    const s = createLogStore();
    s.set([]);
    expect(s.current!.data).toEqual([]);
  });

  it("createReplayStore funciona como DomainStore", () => {
    const s = createReplayStore();
    s.set({ events: [], sessionIds: [], correlations: [] });
    expect(s.current!.data.events).toEqual([]);
  });

  it("createEventStore funciona como DomainStore", () => {
    const s = createEventStore();
    s.set([]);
    expect(s.current!.data).toEqual([]);
  });
});
