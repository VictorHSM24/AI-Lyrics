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

import { useEffect, useRef, useState } from "react";
import { useConnection } from "@/contexts/ConnectionContext";
import {
  useEventStream,
  useServices,
  useStores,
} from "@/contexts/InfraContext";
import type { Snapshot } from "@/stores";
import type {
  AudioDeviceDTO,
  AudioLevelsDTO,
  ConfigurationDTO,
  DiagnosticDTO,
  EventDTO,
  HealthSnapshot,
  InfoDTO,
  MetricsDTO,
  PipelineSnapshot,
  PipelineStatusDTO,
  SessionDTO,
  SystemInfoDTO,
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
// useAudio (Sprint 14)
// ============================================================

export interface UseAudioResult {
  devices: AudioDeviceDTO[];
  current: AudioDeviceDTO | null;
  levels: AudioLevelsDTO | null;
  capturing: boolean;
  selectedDeviceIndex: number | null;
  sampleRate: number;
  channels: number;
  rms: number;
  peak: number;
  lastUpdate: number;
  connected: boolean;
  loading: boolean;
  error: string | null;
}

export function useAudio(): UseAudioResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.audio);
  const data = snap?.data;
  return {
    devices: data?.devices ?? [],
    current: data?.current ?? null,
    levels: data?.levels ?? null,
    capturing: data?.capturing ?? false,
    selectedDeviceIndex: data?.selectedDeviceIndex ?? null,
    sampleRate: data?.sampleRate ?? 16000,
    channels: data?.channels ?? 1,
    rms: data?.rms ?? 0,
    peak: data?.peak ?? 0,
    lastUpdate: data?.lastUpdate ?? 0,
    connected: data?.connected ?? false,
    loading: !snap,
    error: null,
  };
}

// ============================================================
// useSystemInfo (Sprint 14)
// ============================================================

export interface UseSystemInfoResult {
  systemInfo: SystemInfoDTO | null;
  loading: boolean;
  error: string | null;
}

export function useSystemInfo(): UseSystemInfoResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.system);
  return {
    systemInfo: snap?.data ?? null,
    loading: !snap,
    error: null,
  };
}

// ============================================================
// useInfo (Sprint 14)
// ============================================================

export interface UseInfoResult {
  info: InfoDTO | null;
  loading: boolean;
  error: string | null;
}

export function useInfo(): UseInfoResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.info);
  return {
    info: snap?.data ?? null,
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

// ============================================================
// useBootstrap — dispara bootstrapStores quando a conexão é
// estabelecida. Popula todos os Stores com dados reais do backend.
// ============================================================

import { bootstrapStores, type BootstrapResult } from "@/stream";

export interface UseBootstrapResult {
  /** True se o bootstrap já foi executado com sucesso. */
  bootstrapped: boolean;
  /** True se o bootstrap está em andamento. */
  loading: boolean;
  /** Resultado do último bootstrap (null se nunca executou). */
  result: BootstrapResult | null;
}

/**
 * Dispara o bootstrap automaticamente quando a conexão com o backend
 * é estabelecida. Popula todos os Stores com dados reais.
 *
 * Deve ser usado uma única vez, no topo da árvore de componentes
 * (ex: dentro de ConnectionProvider ou App).
 */
export function useBootstrap(): UseBootstrapResult {
  const services = useServices();
  const stores = useStores();
  const { status } = useConnection();
  const [bootstrapped, setBootstrapped] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BootstrapResult | null>(null);
  const lastStatusRef = useRef<string>("");

  useEffect(() => {
    // Só dispara quando transiciona para "connected".
    if (status !== "connected" || lastStatusRef.current === "connected") return;
    lastStatusRef.current = status;

    if (loading || bootstrapped) return;
    setLoading(true);

    bootstrapStores(services, stores)
      .then((res) => {
        setResult(res);
        setBootstrapped(true);
        setLoading(false);
      })
      .catch(() => {
        // bootstrapStores nunca rejeita, mas por segurança.
        setLoading(false);
      });
  }, [status, services, stores, loading, bootstrapped]);

  // Reset quando desconecta (para re-bootstrar na próxima conexão).
  useEffect(() => {
    if (status === "disconnected") {
      lastStatusRef.current = status;
      setBootstrapped(false);
      setResult(null);
    }
  }, [status]);

  return { bootstrapped, loading, result };
}

// ============================================================
// useHealthPolling — atualiza o HealthStore periodicamente.
// ============================================================

/**
 * Polls the backend /health endpoint at a fixed interval and updates
 * the HealthStore with fresh data. This ensures the HealthPanel always
 * reflects the real operational state of each component.
 *
 * @param intervalMs Polling interval in milliseconds (default: 10000).
 */
export function useHealthPolling(intervalMs: number = 10000): void {
  const services = useServices();
  const stores = useStores();
  const { status } = useConnection();

  useEffect(() => {
    if (status !== "connected") return;

    let cancelled = false;

    const poll = async () => {
      try {
        const health = await services.health.getHealth();
        if (!cancelled) {
          stores.health.set(health);
        }
      } catch {
        // Silently ignore — next poll will retry.
      }
    };

    // Poll immediately, then at interval.
    poll();
    const timer = setInterval(poll, intervalMs);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [status, services, stores, intervalMs]);
}
