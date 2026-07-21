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
import { devLog } from "@/utils";

// Re-export useServices for components that need to call services directly.
export { useServices } from "@/contexts/InfraContext";
import type { Snapshot, TranscriptEntry, ReferenceEntry, VersePresentationEntry, SemanticInferenceEntry, SemanticResolutionEntry, SermonContextEntry, SermonChangeEvent } from "@/stores";
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
// useTranscript (Sprint 16) — transcrições em tempo real.
// ============================================================

export interface UseTranscriptResult {
  entries: TranscriptEntry[];
  listening: boolean;
  transcribing: boolean;
  partialText: string;
  loading: boolean;
}

export function useTranscript(): UseTranscriptResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.transcript);
  const data = snap?.data;
  return {
    entries: data?.entries ?? [],
    listening: data?.listening ?? false,
    transcribing: data?.transcribing ?? false,
    partialText: data?.partialText ?? "",
    loading: !snap,
  };
}

// ============================================================
// useReference (Sprint 17) — referências bíblicas detectadas.
// ============================================================

export interface UseReferenceResult {
  current: ReferenceEntry | null;
  entries: ReferenceEntry[];
  invalid: { book: string; reason: string; rawText: string; timestamp: number } | null;
  loading: boolean;
}

export function useReference(): UseReferenceResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.reference);
  const data = snap?.data;
  return {
    current: data?.current ?? null,
    entries: data?.entries ?? [],
    invalid: data?.invalid ?? null,
    loading: !snap,
  };
}

// ============================================================
// useVersePresentation (Sprint 18) — apresentação automática
// de versículos no Holyrics.
// ============================================================

export interface UseVersePresentationResult {
  current: VersePresentationEntry | null;
  entries: VersePresentationEntry[];
  loading: boolean;
}

export function useVersePresentation(): UseVersePresentationResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.versePresentation);
  const data = snap?.data;
  return {
    current: data?.current ?? null,
    entries: data?.entries ?? [],
    loading: !snap,
  };
}

// ============================================================
// useSemantic (Sprint 20) — camada de compreensão semântica.
// Mostra inferências do SemanticEngine e resoluções do
// ReferenceResolver para depuração.
// ============================================================

export interface UseSemanticResult {
  currentInference: SemanticInferenceEntry | null;
  currentResolution: SemanticResolutionEntry | null;
  inferenceHistory: SemanticInferenceEntry[];
  resolutionHistory: SemanticResolutionEntry[];
  loading: boolean;
}

export function useSemantic(): UseSemanticResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.semantic);
  const data = snap?.data;
  return {
    currentInference: data?.currentInference ?? null,
    currentResolution: data?.currentResolution ?? null,
    inferenceHistory: data?.inferenceHistory ?? [],
    resolutionHistory: data?.resolutionHistory ?? [],
    loading: !snap,
  };
}

// ============================================================
// useSermon (Sprint 21) — memória contínua da pregação.
// Mostra o SermonContext vivo (livro, capítulo, tema, entidades,
// referências recentes) e eventos de mudança.
// ============================================================

export interface UseSermonResult {
  current: SermonContextEntry | null;
  changes: SermonChangeEvent[];
  metrics: {
    totalUpdates: number;
    updatesPerMinute: number;
    bookChanges: number;
    chapterChanges: number;
    topicChanges: number;
    entityExpirations: number;
    topicExpirations: number;
    referenceExpirations: number;
    uptimeSeconds: number;
    contextAgeSeconds: number;
    sermonDurationSeconds: number;
    confidence: number;
  } | null;
  loading: boolean;
}

export function useSermon(): UseSermonResult {
  const stores = useStores();
  const snap = useStoreSnapshot(stores.sermon);
  const data = snap?.data;
  return {
    current: data?.current ?? null,
    changes: data?.changes ?? [],
    metrics: data?.metrics ?? null,
    loading: !snap,
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
// useBootstrap — dispara BootstrapCoordinator quando a conexão é
// estabelecida. Popula todos os Stores com dados reais do backend.
// ============================================================

import {
  createBootstrapCoordinator,
  type BootstrapCoordinator,
  type ResourceStatus,
} from "@/stream";

export interface UseBootstrapResult {
  /** True se TODOS os recursos foram carregados com sucesso. */
  bootstrapped: boolean;
  /** True se o bootstrap está em andamento (algum recurso carregando). */
  loading: boolean;
  /** Estado por recurso (idle/loading/loaded/failed + timestamps). */
  resources: Record<string, ResourceStatus>;
  /** True se ALGUM recurso falhou após esgotar tentativas. */
  hasFailures: boolean;
}

/**
 * Dispara o BootstrapCoordinator automaticamente quando a conexão
 * com o backend é estabelecida. Popula todos os Stores com dados reais.
 *
 * Sprint 17.5.1 — Substitui o bootstrapStores one-shot por um
 * coordinator com:
 * - Estado por recurso (idle/loading/loaded/failed).
 * - Retry exponencial para recursos que falharam.
 * - Re-disparo quando a conexão transiciona de qualquer estado
 *   não-conectado para "connected" (não apenas de "disconnected").
 * - Recursos falhados NÃO impedem os demais.
 *
 * Deve ser usado uma única vez, no topo da árvore de componentes
 * (ex: dentro de ConnectionProvider ou App).
 */
export function useBootstrap(): UseBootstrapResult {
  const services = useServices();
  const stores = useStores();
  const { status } = useConnection();
  const [loading, setLoading] = useState(false);
  const [resources, setResources] = useState<Record<string, ResourceStatus>>({});
  const coordinatorRef = useRef<BootstrapCoordinator | null>(null);
  const lastStatusRef = useRef<string>("");
  // Ref para evitar que a promise de um round anterior atualize estado
  // após o componente desmontar (StrictMode).
  const cancelledRef = useRef(false);

  // Cria o coordinator uma única vez por par (services, stores).
  // Se services/stores mudam (raro), recria.
  useEffect(() => {
    cancelledRef.current = false;
    const coordinator = createBootstrapCoordinator(services, stores);
    coordinatorRef.current = coordinator;
    setResources(coordinator.snapshot());

    return () => {
      cancelledRef.current = true;
      coordinator.dispose();
      coordinatorRef.current = null;
    };
  }, [services, stores]);

  // Dispara loadAll quando transiciona para "connected" a partir de
  // qualquer estado não-conectado (incluindo "connecting" e "reconnecting").
  useEffect(() => {
    if (status !== "connected") {
      lastStatusRef.current = status;
      return;
    }
    // Já estava conectado — não re-dispara.
    if (lastStatusRef.current === "connected") return;
    lastStatusRef.current = status;

    const coordinator = coordinatorRef.current;
    if (!coordinator) return;
    if (cancelledRef.current) return;

    setLoading(true);
    devLog.bootstrap(`useBootstrap: disparando loadAll (status=${status})`);

    coordinator.loadAll()
      .then((snapshot) => {
        if (cancelledRef.current) return;
        setResources(snapshot);
        setLoading(false);
        devLog.bootstrap(`useBootstrap: loadAll concluído — allLoaded=${coordinator.allLoaded}`);
      })
      .catch(() => {
        if (cancelledRef.current) return;
        setLoading(false);
      });
  }, [status]);

  // Atualiza snapshot periodicamente para refletir retries que
  // terminaram (carregados ou falhados). Isso permite que a UI
  // veja quando um recurso que estava "loading" passa para "loaded"
  // via retry automático.
  useEffect(() => {
    if (status !== "connected") return;
    const timer = setInterval(() => {
      const coordinator = coordinatorRef.current;
      if (!coordinator) return;
      setResources(coordinator.snapshot());
    }, 2000);
    return () => clearInterval(timer);
  }, [status]);

  const coordinator = coordinatorRef.current;
  const bootstrapped = coordinator ? coordinator.allLoaded : false;
  const hasFailures = coordinator ? coordinator.hasFailures : false;

  return { bootstrapped, loading, resources, hasFailures };
}

// Import local para evitar conflito de nome com devLog do módulo.
// (devLog já é importado no topo do arquivo via @/utils, mas usamos
// um alias aqui para clareza dentro do hook.)
// Sprint 17.5.1 — devLog importado no topo do arquivo (import { devLog }).


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

// ============================================================
// useAutoStartPipeline (Sprint 17.1) — auto-iniciar pipeline.
// ============================================================

/**
 * Auto-inicia o pipeline quando:
 * 1. O backend está conectado.
 * 2. O startup sequence foi concluído com sucesso.
 * 3. A configuração autoStart está ativada.
 * 4. O pipeline ainda não está rodando.
 *
 * Este hook NÃO substitui o controle manual — apenas aciona
 * automaticamente o mesmo ciclo de Iniciar Pipeline na inicialização.
 */
export function useAutoStartPipeline(autoStart: boolean): void {
  const services = useServices();
  const { status } = useConnection();
  const { status: pipelineStatus } = usePipeline();
  const startedRef = useRef(false);

  useEffect(() => {
    if (!autoStart) return;
    if (status !== "connected") return;
    if (startedRef.current) return;
    if (pipelineStatus?.running) {
      startedRef.current = true;
      return;
    }

    // Pequeno delay para garantir que o startup concluiu.
    const timer = setTimeout(() => {
      if (startedRef.current) return;
      startedRef.current = true;
      services.pipeline.startPipeline().catch(() => {
        // Silently ignore — usuário pode iniciar manualmente.
      });
    }, 2000);

    return () => clearTimeout(timer);
  }, [autoStart, status, pipelineStatus?.running, services]);
}
