/**
 * Domain Stores — um store por domínio do sistema.
 *
 * Cada Store encapsula um SnapshotStore tipado e expõe
 * métodos específicos do domínio para atualização.
 *
 * Stores NÃO conhecem React.
 * Stores NÃO conhecem transporte.
 * Stores NÃO executam lógica de negócio — apenas armazenam estado.
 */

import type {
  ConfigurationDTO,
  DiagnosticDTO,
  EventDTO,
  HealthSnapshot,
  LogDTO,
  MetricsDTO,
  PipelineSnapshot,
  PipelineStatusDTO,
  SessionDTO,
} from "@/types";
import {
  createSnapshotStore,
  type Snapshot,
  type SnapshotStore,
  type StoreSubscription,
  type StoreListener,
} from "./SnapshotStore";

// ============================================================
// Base helper — expõe uma interface comum.
// ============================================================

export interface DomainStore<T> {
  readonly current: Snapshot<T> | null;
  readonly version: number;
  readonly hasSnapshot: boolean;
  subscribe(listener: StoreListener<T>): StoreSubscription;
  set(data: T): void;
  update(updater: (prev: T | null) => T): void;
  clear(): void;
}

/**
 * Cria um DomainStore a partir de um SnapshotStore.
 * Usa herança prototipal para preservar todas as propriedades
 * (incluindo getters como `hasSnapshot`).
 */
function wrap<T>(store: SnapshotStore<T>): DomainStore<T> {
  // O SnapshotStore já implementa todos os métodos de DomainStore.
  // Apenas retornamos com o tipo correto.
  return store as unknown as DomainStore<T>;
}

// ============================================================
// PipelineStore
// ============================================================

export interface PipelineStore extends DomainStore<PipelineSnapshot> {
  setStatus(status: PipelineStatusDTO): void;
}

export function createPipelineStore(): PipelineStore {
  const store = createSnapshotStore<PipelineSnapshot>();
  const base = wrap(store);
  const pipelineStore: PipelineStore = {
    get current() { return base.current; },
    get version() { return base.version; },
    get hasSnapshot() { return base.hasSnapshot; },
    subscribe: (l) => base.subscribe(l),
    set: (d) => base.set(d),
    update: (u) => base.update(u),
    clear: () => base.clear(),
    setStatus(status: PipelineStatusDTO) {
      store.update((prev) => ({
        timestamp: Date.now() / 1000,
        status,
        session: prev?.session ?? null as never,
        metrics: prev?.metrics ?? null as never,
        last_event: prev?.last_event ?? null,
      }));
    },
  };
  return pipelineStore;
}

// ============================================================
// HealthStore
// ============================================================

export type HealthStore = DomainStore<HealthSnapshot>;
export function createHealthStore(): HealthStore {
  return wrap(createSnapshotStore<HealthSnapshot>());
}

// ============================================================
// MetricsStore
// ============================================================

export type MetricsStore = DomainStore<MetricsDTO>;
export function createMetricsStore(): MetricsStore {
  return wrap(createSnapshotStore<MetricsDTO>());
}

// ============================================================
// SessionStore
// ============================================================

export type SessionStore = DomainStore<SessionDTO>;
export function createSessionStore(): SessionStore {
  return wrap(createSnapshotStore<SessionDTO>());
}

// ============================================================
// ConfigurationStore
// ============================================================

export type ConfigurationStore = DomainStore<ConfigurationDTO>;
export function createConfigurationStore(): ConfigurationStore {
  return wrap(createSnapshotStore<ConfigurationDTO>());
}

// ============================================================
// DiagnosticsStore
// ============================================================

export type DiagnosticsStore = DomainStore<DiagnosticDTO[]>;
export function createDiagnosticsStore(): DiagnosticsStore {
  return wrap(createSnapshotStore<DiagnosticDTO[]>());
}

// ============================================================
// LogStore
// ============================================================

export type LogStore = DomainStore<LogDTO[]>;
export function createLogStore(): LogStore {
  return wrap(createSnapshotStore<LogDTO[]>());
}

// ============================================================
// ReplayStore
// ============================================================

export interface ReplayState {
  events: EventDTO[];
  sessionIds: string[];
  correlations: string[];
}

export type ReplayStore = DomainStore<ReplayState>;
export function createReplayStore(): ReplayStore {
  return wrap(createSnapshotStore<ReplayState>());
}

// ============================================================
// EventStore (frontend) — histórico de eventos recebidos.
// ============================================================

export type EventStore = DomainStore<EventDTO[]>;
export function createEventStore(): EventStore {
  return wrap(createSnapshotStore<EventDTO[]>());
}

// ============================================================
// Registry — agregador de todos os stores.
// ============================================================

export interface StoreRegistry {
  readonly pipeline: PipelineStore;
  readonly health: HealthStore;
  readonly metrics: MetricsStore;
  readonly session: SessionStore;
  readonly configuration: ConfigurationStore;
  readonly diagnostics: DiagnosticsStore;
  readonly logs: LogStore;
  readonly replay: ReplayStore;
  readonly events: EventStore;
}

export function createStoreRegistry(): StoreRegistry {
  return {
    pipeline: createPipelineStore(),
    health: createHealthStore(),
    metrics: createMetricsStore(),
    session: createSessionStore(),
    configuration: createConfigurationStore(),
    diagnostics: createDiagnosticsStore(),
    logs: createLogStore(),
    replay: createReplayStore(),
    events: createEventStore(),
  };
}
