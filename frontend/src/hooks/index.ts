/**
 * Hooks — ponte entre React e a camada de infraestrutura reativa.
 *
 * Hooks consomem EXCLUSIVAMENTE:
 * - Stores (estado)
 * - Services (consultas)
 * - EventStream (eventos)
 *
 * Hooks NUNCA conhecem transporte.
 * Hooks NUNCA conhecem WebSocket.
 * Hooks NUNCA conhecem REST.
 * Hooks NUNCA conhecem Client SDK diretamente.
 *
 * Atualização é orientada a eventos — NUNCA por polling.
 */

import { useEffect, useState } from "react";
import { useConnection } from "@/contexts/ConnectionContext";
import {
  useEventStream,
  useServices,
  useStores,
} from "@/contexts/InfraContext";
import type { Snapshot } from "@/stores";
import type {
  ConfigurationDTO,
  DiagnosticDTO,
  EventDTO,
  HealthSnapshot,
  MetricsDTO,
  PipelineSnapshot,
  PipelineStatusDTO,
  SessionDTO,
} from "@/types";
import type { StreamEvent } from "@/stream";

// ============================================================
// Helper — assina um SnapshotStore e re-renderiza em mudanças.
// ============================================================

function useStoreSnapshot<T>(store: { current: Snapshot<T> | null; subscribe(cb: (s: Snapshot<T>) => void): { unsubscribe(): void } }): Snapshot<T> | null {
  const [snapshot, setSnapshot] = useState<Snapshot<T> | null>(store.current);
  useEffect(() => {
    setSnapshot(store.current);
    const sub = store.subscribe((s) => setSnapshot(s));
    return () => sub.unsubscribe();
  }, [store]);
  return snapshot;
}

// ============================================================
// useConnectionStatus
// ============================================================

export function useConnectionStatus() {
  const { status, lastConnectedAt } = useConnection();
  return { status, lastConnectedAt };
}

// ============================================================
// usePipeline
// ============================================================

export interface UsePipelineResult {
  status: PipelineStatusDTO | null;
  snapshot: PipelineSnapshot | null;
  loading: boolean;
  error: string | null;
}

export function usePipeline(): UsePipelineResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.pipeline);
  return {
    status: snap?.data.status ?? null,
    snapshot: snap?.data ?? null,
    loading: !snap,
    error: null,
  };
}

// ============================================================
// useMetrics
// ============================================================

export interface UseMetricsResult {
  metrics: MetricsDTO | null;
  loading: boolean;
  error: string | null;
}

export function useMetrics(): UseMetricsResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.metrics);
  return {
    metrics: snap?.data ?? null,
    loading: !snap,
    error: null,
  };
}

// ============================================================
// useHealth
// ============================================================

export interface UseHealthResult {
  health: HealthSnapshot | null;
  loading: boolean;
  error: string | null;
}

export function useHealth(): UseHealthResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.health);
  return {
    health: snap?.data ?? null,
    loading: !snap,
    error: null,
  };
}

// ============================================================
// useSession
// ============================================================

export interface UseSessionResult {
  session: SessionDTO | null;
  loading: boolean;
  error: string | null;
}

export function useSession(): UseSessionResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.session);
  return {
    session: snap?.data ?? null,
    loading: !snap,
    error: null,
  };
}

// ============================================================
// useReplay
// ============================================================

export interface UseReplayResult {
  events: EventDTO[];
  sessionIds: string[];
  loading: boolean;
  error: string | null;
}

export function useReplay(): UseReplayResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.replay);
  return {
    events: snap?.data.events ?? [],
    sessionIds: snap?.data.sessionIds ?? [],
    loading: !snap,
    error: null,
  };
}

// ============================================================
// useConfiguration
// ============================================================

export interface UseConfigurationResult {
  configuration: ConfigurationDTO | null;
  loading: boolean;
  error: string | null;
}

export function useConfiguration(): UseConfigurationResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.configuration);
  return {
    configuration: snap?.data ?? null,
    loading: !snap,
    error: null,
  };
}

// ============================================================
// useDiagnostics
// ============================================================

export interface UseDiagnosticsResult {
  diagnostics: DiagnosticDTO[];
  loading: boolean;
  error: string | null;
}

export function useDiagnostics(): UseDiagnosticsResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.diagnostics);
  return {
    diagnostics: snap?.data ?? [],
    loading: !snap,
    error: null,
  };
}

// ============================================================
// useEvents
// ============================================================

export interface UseEventsResult {
  events: EventDTO[];
  loading: boolean;
  error: string | null;
}

export function useEvents(): UseEventsResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.events);
  return {
    events: snap?.data ?? [],
    loading: !snap,
    error: null,
  };
}

// ============================================================
// useStreamSnapshot — expõe o snapshot do EventStream.
// ============================================================

import type { StreamSnapshot } from "@/stream";

export function useStreamSnapshot(): StreamSnapshot {
  const stream = useEventStream();
  const [snap, setSnap] = useState<StreamSnapshot>(stream.snapshot());
  useEffect(() => {
    const sub = stream.subscribe(() => setSnap(stream.snapshot()));
    return () => sub.unsubscribe();
  }, [stream]);
  return snap;
}

// ============================================================
// useStreamEvents — assina eventos do stream e retorna array.
// ============================================================

export function useStreamEvents(limit = 100): StreamEvent[] {
  const stream = useEventStream();
  const [events, setEvents] = useState<readonly StreamEvent[]>(stream.history(limit));
  useEffect(() => {
    const sub = stream.subscribe(() => setEvents(stream.history(limit)));
    return () => sub.unsubscribe();
  }, [stream, limit]);
  return Array.from(events);
}

// ============================================================
// useServicesHook — expõe services para uso em hooks customizados.
// ============================================================

export function useServicesHook() {
  return useServices();
}
