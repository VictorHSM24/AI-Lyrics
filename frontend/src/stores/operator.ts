/**
 * Operator Stores (Sprint 25) — estado compartilhado do Painel do Operador.
 *
 * Três stores independentes:
 *
 * 1. OperatorWorkspaceStore — estado de UI da sessão atual (selecionado,
 *    modo operação, quick presentation). NÃO persistido (reset ao recarregar).
 *
 * 2. OperatorFavoritesStore — lista de favoritos persistida em localStorage.
 *    Cada favorito é uma referência (bookId, chapter, verse) com label.
 *
 * 3. OperatorRecentsStore — referências mais utilizadas, ordenadas por
 *    frequência. Atualizado a cada apresentação (manual ou automática).
 *    Persistido em localStorage.
 *
 * Stores NÃO conhecem React.
 * Stores NÃO conhecem transporte.
 * Persistência em localStorage é fevia via hook useLocalStorage nos
 * componentes, NÃO no store (store é puro estado em memória).
 */

import {
  createSnapshotStore,
  type StoreListener,
  type StoreSubscription,
} from "./SnapshotStore";
import type { DomainStore } from "./domain";

// ============================================================
// Tipos compartilhados
// ============================================================

/** Referência bíblica normalizada (IDs numéricos). */
export interface OperatorRef {
  bookId: number;
  chapter: number;
  verse: number;
}

/** Favorito: referência + label amigável + timestamp de criação. */
export interface OperatorFavorite {
  id: string;
  ref: OperatorRef;
  label: string;
  createdAt: number;
}

/** Entrada de "recentes" com contagem de uso. */
export interface OperatorRecentEntry {
  ref: OperatorRef;
  label: string;
  count: number;
  lastUsed: number;
}

// ============================================================
// Base helper (mesmo padrão de domain.ts)
// ============================================================

function wrap<T>(store: ReturnType<typeof createSnapshotStore<T>>): DomainStore<T> {
  return store as unknown as DomainStore<T>;
}

// ============================================================
// OperatorWorkspaceStore — estado de UI da sessão
// ============================================================

export type OperatorMode = "normal" | "live";

export interface OperatorWorkspaceState {
  /** Versículo selecionado pelo operador (navegação). */
  selected: OperatorRef | null;
  /** Modo de operação: "normal" (com sidebar) ou "live" (layout expandido). */
  mode: OperatorMode;
  /** Quick presentation ativo (popup sem encerrar atual). */
  quickPresentation: boolean;
  /** Query de busca atual (para QuickSearch compartilhado). */
  searchQuery: string;
}

const DEFAULT_WORKSPACE: OperatorWorkspaceState = {
  selected: null,
  mode: "normal",
  quickPresentation: false,
  searchQuery: "",
};

export interface OperatorWorkspaceStore extends DomainStore<OperatorWorkspaceState> {
  setSelected(ref: OperatorRef | null): void;
  clearSelected(): void;
  setMode(mode: OperatorMode): void;
  setQuickPresentation(value: boolean): void;
  setSearchQuery(query: string): void;
}

export function createOperatorWorkspaceStore(): OperatorWorkspaceStore {
  const store = createSnapshotStore<OperatorWorkspaceState>();
  const base = wrap(store);
  const workspaceStore: OperatorWorkspaceStore = {
    get current() { return base.current; },
    get version() { return base.version; },
    get hasSnapshot() { return base.hasSnapshot; },
    subscribe: (l: StoreListener<OperatorWorkspaceState>): StoreSubscription => base.subscribe(l),
    set: (d: OperatorWorkspaceState) => base.set(d),
    update: (u) => base.update(u),
    clear: () => base.clear(),
    setSelected(ref) {
      store.update((prev) => ({ ...(prev ?? DEFAULT_WORKSPACE), selected: ref }));
    },
    clearSelected() {
      store.update((prev) => ({ ...(prev ?? DEFAULT_WORKSPACE), selected: null }));
    },
    setMode(mode) {
      store.update((prev) => ({ ...(prev ?? DEFAULT_WORKSPACE), mode }));
    },
    setQuickPresentation(value) {
      store.update((prev) => ({ ...(prev ?? DEFAULT_WORKSPACE), quickPresentation: value }));
    },
    setSearchQuery(query) {
      store.update((prev) => ({ ...(prev ?? DEFAULT_WORKSPACE), searchQuery: query }));
    },
  };
  // Estado inicial.
  base.set({
    selected: null,
    mode: "normal",
    quickPresentation: false,
    searchQuery: "",
  });
  return workspaceStore;
}

// ============================================================
// OperatorFavoritesStore — favoritos persistidos
// ============================================================

export interface OperatorFavoritesState {
  favorites: OperatorFavorite[];
}

export interface OperatorFavoritesStore extends DomainStore<OperatorFavoritesState> {
  addFavorite(ref: OperatorRef, label: string): void;
  removeFavorite(id: string): void;
  removeByRef(ref: OperatorRef): void;
  isFavorite(ref: OperatorRef): boolean;
  setFavorites(favorites: OperatorFavorite[]): void;
}

export function createOperatorFavoritesStore(): OperatorFavoritesStore {
  const store = createSnapshotStore<OperatorFavoritesState>();
  const base = wrap(store);
  const favStore: OperatorFavoritesStore = {
    get current() { return base.current; },
    get version() { return base.version; },
    get hasSnapshot() { return base.hasSnapshot; },
    subscribe: (l: StoreListener<OperatorFavoritesState>): StoreSubscription => base.subscribe(l),
    set: (d: OperatorFavoritesState) => base.set(d),
    update: (u) => base.update(u),
    clear: () => base.clear(),
    addFavorite(ref, label) {
      store.update((prev) => {
        const base = prev ?? { favorites: [] };
        // Evitar duplicatas exatas (mesmo bookId+chapter+verse).
        const exists = base.favorites.some(
          (f) => f.ref.bookId === ref.bookId && f.ref.chapter === ref.chapter && f.ref.verse === ref.verse,
        );
        if (exists) return base;
        const fav: OperatorFavorite = {
          id: `fav_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
          ref,
          label,
          createdAt: Date.now(),
        };
        return { favorites: [...base.favorites, fav] };
      });
    },
    removeFavorite(id) {
      store.update((prev) => ({
        favorites: (prev ?? { favorites: [] }).favorites.filter((f) => f.id !== id),
      }));
    },
    removeByRef(ref) {
      store.update((prev) => ({
        favorites: (prev ?? { favorites: [] }).favorites.filter(
          (f) => !(f.ref.bookId === ref.bookId && f.ref.chapter === ref.chapter && f.ref.verse === ref.verse),
        ),
      }));
    },
    isFavorite(ref) {
      const snap = store.current;
      if (!snap) return false;
      return snap.data.favorites.some(
        (f) => f.ref.bookId === ref.bookId && f.ref.chapter === ref.chapter && f.ref.verse === ref.verse,
      );
    },
    setFavorites(favorites) {
      store.set({ favorites });
    },
  };
  base.set({ favorites: [] });
  return favStore;
}

// ============================================================
// OperatorRecentsStore — recentes por frequência
// ============================================================

export interface OperatorRecentsState {
  entries: OperatorRecentEntry[];
}

export interface OperatorRecentsStore extends DomainStore<OperatorRecentsState> {
  /** Registra um uso da referência (incrementa contagem, atualiza lastUsed). */
  recordUsage(ref: OperatorRef, label: string): void;
  /** Retorna entries ordenadas por frequência (desc). */
  getByFrequency(limit?: number): OperatorRecentEntry[];
  setEntries(entries: OperatorRecentEntry[]): void;
}

export function createOperatorRecentsStore(): OperatorRecentsStore {
  const store = createSnapshotStore<OperatorRecentsState>();
  const base = wrap(store);
  const recentsStore: OperatorRecentsStore = {
    get current() { return base.current; },
    get version() { return base.version; },
    get hasSnapshot() { return base.hasSnapshot; },
    subscribe: (l: StoreListener<OperatorRecentsState>): StoreSubscription => base.subscribe(l),
    set: (d: OperatorRecentsState) => base.set(d),
    update: (u) => base.update(u),
    clear: () => base.clear(),
    recordUsage(ref, label) {
      store.update((prev) => {
        const base = prev ?? { entries: [] };
        const idx = base.entries.findIndex(
          (e) => e.ref.bookId === ref.bookId && e.ref.chapter === ref.chapter && e.ref.verse === ref.verse,
        );
        if (idx >= 0) {
          const updated = [...base.entries];
          updated[idx] = {
            ...updated[idx],
            count: updated[idx].count + 1,
            lastUsed: Date.now(),
            label,
          };
          return { entries: updated };
        }
        return {
          entries: [
            ...base.entries,
            { ref, label, count: 1, lastUsed: Date.now() },
          ],
        };
      });
    },
    getByFrequency(limit = 10) {
      const snap = store.current;
      if (!snap) return [];
      return [...snap.data.entries]
        .sort((a, b) => b.count - a.count || b.lastUsed - a.lastUsed)
        .slice(0, limit);
    },
    setEntries(entries) {
      store.set({ entries });
    },
  };
  base.set({ entries: [] });
  return recentsStore;
}

// ============================================================
// Registry extension — adicionar stores do operator ao registry
// ============================================================

export interface OperatorStoreRegistry {
  workspace: OperatorWorkspaceStore;
  favorites: OperatorFavoritesStore;
  recents: OperatorRecentsStore;
}

export function createOperatorStores(): OperatorStoreRegistry {
  return {
    workspace: createOperatorWorkspaceStore(),
    favorites: createOperatorFavoritesStore(),
    recents: createOperatorRecentsStore(),
  };
}
