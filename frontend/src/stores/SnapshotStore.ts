/**
 * SnapshotStore — abstração para transformar fluxo de eventos
 * em estado consumível pela interface.
 *
 * Responsabilidades:
 * - Estado atual
 * - Último snapshot
 * - Consulta rápida
 * - Atualização incremental
 * - Sincronização de estado
 * - Emissão de notificações de mudança
 *
 * NÃO conhece React.
 * NÃO conhece componentes.
 * NÃO executa lógica de negócio.
 */

// ============================================================
// Snapshot<T>
// ============================================================

export interface Snapshot<T> {
  readonly data: T;
  readonly version: number;
  readonly timestamp: number;
}

// ============================================================
// StoreListener
// ============================================================

export interface StoreListener<T> {
  (snapshot: Snapshot<T>): void;
}

export interface StoreSubscription {
  unsubscribe(): void;
}

// ============================================================
// SnapshotStore<T>
// ============================================================

export interface SnapshotStore<T> {
  /** Snapshot atual (imutável). */
  readonly current: Snapshot<T> | null;
  /** Versão atual (incrementa a cada atualização). */
  readonly version: number;
  /** True se há um snapshot. */
  readonly hasSnapshot: boolean;
  /** Registra listener de mudanças. */
  subscribe(listener: StoreListener<T>): StoreSubscription;
  /** Atualiza o estado (substitui). */
  set(data: T): void;
  /** Atualiza o estado via função patch. */
  update(updater: (prev: T | null) => T): void;
  /** Limpa o estado. */
  clear(): void;
}

// ============================================================
// SnapshotStoreImpl
// ============================================================

export class SnapshotStoreImpl<T> implements SnapshotStore<T> {
  private _snapshot: Snapshot<T> | null = null;
  private readonly listeners: Set<StoreListener<T>> = new Set();

  get current(): Snapshot<T> | null {
    return this._snapshot;
  }

  get version(): number {
    return this._snapshot?.version ?? 0;
  }

  get hasSnapshot(): boolean {
    return this._snapshot !== null;
  }

  subscribe(listener: StoreListener<T>): StoreSubscription {
    this.listeners.add(listener);
    return { unsubscribe: () => this.listeners.delete(listener) };
  }

  set(data: T): void {
    const prevVersion = this._snapshot?.version ?? 0;
    this._snapshot = {
      data,
      version: prevVersion + 1,
      timestamp: Date.now() / 1000,
    };
    this.notify();
  }

  update(updater: (prev: T | null) => T): void {
    const next = updater(this._snapshot?.data ?? null);
    this.set(next);
  }

  clear(): void {
    this._snapshot = null;
    this.notify();
  }

  private notify(): void {
    if (!this._snapshot) return;
    for (const l of this.listeners) {
      try {
        l(this._snapshot);
      } catch {
        // Listeners não devem propagar erros.
      }
    }
  }
}

// ============================================================
// Factory
// ============================================================

export function createSnapshotStore<T>(): SnapshotStore<T> {
  return new SnapshotStoreImpl<T>();
}
