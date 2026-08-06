/**
 * Sprint 25 — Testes dos stores do operator (Fase A).
 *
 * Valida:
 * 1. OperatorWorkspaceStore: setSelected, clearSelected, setMode, etc.
 * 2. OperatorFavoritesStore: addFavorite, removeFavorite, isFavorite.
 * 3. OperatorRecentsStore: recordUsage, getByFrequency.
 * 4. createOperatorStores retorna os 3 stores.
 */

import { describe, it, expect } from "vitest";
import {
  createOperatorWorkspaceStore,
  createOperatorFavoritesStore,
  createOperatorRecentsStore,
  createOperatorStores,
  type OperatorRef,
} from "@/stores";

const REF_1: OperatorRef = { bookId: 43, chapter: 3, verse: 16 };
const REF_2: OperatorRef = { bookId: 45, chapter: 8, verse: 28 };
const REF_3: OperatorRef = { bookId: 1, chapter: 1, verse: 1 };

describe("OperatorWorkspaceStore", () => {
  it("inicia com estado default", () => {
    const store = createOperatorWorkspaceStore();
    expect(store.current).not.toBeNull();
    expect(store.current!.data.selected).toBeNull();
    expect(store.current!.data.mode).toBe("normal");
    expect(store.current!.data.quickPresentation).toBe(false);
    expect(store.current!.data.searchQuery).toBe("");
  });

  it("setSelected atualiza selected", () => {
    const store = createOperatorWorkspaceStore();
    store.setSelected(REF_1);
    expect(store.current!.data.selected).toEqual(REF_1);
  });

  it("clearSelected limpa selected", () => {
    const store = createOperatorWorkspaceStore();
    store.setSelected(REF_1);
    store.clearSelected();
    expect(store.current!.data.selected).toBeNull();
  });

  it("setMode atualiza mode", () => {
    const store = createOperatorWorkspaceStore();
    store.setMode("live");
    expect(store.current!.data.mode).toBe("live");
  });

  it("setQuickPresentation atualiza quickPresentation", () => {
    const store = createOperatorWorkspaceStore();
    store.setQuickPresentation(true);
    expect(store.current!.data.quickPresentation).toBe(true);
  });

  it("setSearchQuery atualiza searchQuery", () => {
    const store = createOperatorWorkspaceStore();
    store.setSearchQuery("joão 3:16");
    expect(store.current!.data.searchQuery).toBe("joão 3:16");
  });

  it("incrementa versão a cada update", () => {
    const store = createOperatorWorkspaceStore();
    const v0 = store.current!.version;
    store.setSelected(REF_1);
    expect(store.current!.version).toBe(v0 + 1);
    store.setMode("live");
    expect(store.current!.version).toBe(v0 + 2);
  });
});

describe("OperatorFavoritesStore", () => {
  it("inicia com lista vazia", () => {
    const store = createOperatorFavoritesStore();
    expect(store.current!.data.favorites).toEqual([]);
  });

  it("addFavorite adiciona favorito", () => {
    const store = createOperatorFavoritesStore();
    store.addFavorite(REF_1, "João 3:16");
    expect(store.current!.data.favorites).toHaveLength(1);
    expect(store.current!.data.favorites[0].ref).toEqual(REF_1);
    expect(store.current!.data.favorites[0].label).toBe("João 3:16");
  });

  it("addFavorite não duplica mesma referência", () => {
    const store = createOperatorFavoritesStore();
    store.addFavorite(REF_1, "João 3:16");
    store.addFavorite(REF_1, "João 3:16 (outra label)");
    expect(store.current!.data.favorites).toHaveLength(1);
  });

  it("isFavorite verifica se referência é favorita", () => {
    const store = createOperatorFavoritesStore();
    store.addFavorite(REF_1, "João 3:16");
    expect(store.isFavorite(REF_1)).toBe(true);
    expect(store.isFavorite(REF_2)).toBe(false);
  });

  it("removeFavorite remove por id", () => {
    const store = createOperatorFavoritesStore();
    store.addFavorite(REF_1, "João 3:16");
    const id = store.current!.data.favorites[0].id;
    store.removeFavorite(id);
    expect(store.current!.data.favorites).toEqual([]);
  });

  it("removeByRef remove por referência", () => {
    const store = createOperatorFavoritesStore();
    store.addFavorite(REF_1, "João 3:16");
    store.addFavorite(REF_2, "Romanos 8:28");
    store.removeByRef(REF_1);
    expect(store.current!.data.favorites).toHaveLength(1);
    expect(store.current!.data.favorites[0].ref).toEqual(REF_2);
  });

  it("setFavorites substitui lista", () => {
    const store = createOperatorFavoritesStore();
    store.addFavorite(REF_1, "João 3:16");
    store.setFavorites([
      { id: "fav_1", ref: REF_2, label: "Romanos 8:28", createdAt: Date.now() },
    ]);
    expect(store.current!.data.favorites).toHaveLength(1);
    expect(store.current!.data.favorites[0].ref).toEqual(REF_2);
  });
});

describe("OperatorRecentsStore", () => {
  it("inicia com lista vazia", () => {
    const store = createOperatorRecentsStore();
    expect(store.current!.data.entries).toEqual([]);
  });

  it("recordUsage adiciona nova entrada", () => {
    const store = createOperatorRecentsStore();
    store.recordUsage(REF_1, "João 3:16");
    expect(store.current!.data.entries).toHaveLength(1);
    expect(store.current!.data.entries[0].ref).toEqual(REF_1);
    expect(store.current!.data.entries[0].count).toBe(1);
  });

  it("recordUsage incrementa contagem para referência existente", () => {
    const store = createOperatorRecentsStore();
    store.recordUsage(REF_1, "João 3:16");
    store.recordUsage(REF_1, "João 3:16");
    store.recordUsage(REF_1, "João 3:16");
    expect(store.current!.data.entries).toHaveLength(1);
    expect(store.current!.data.entries[0].count).toBe(3);
  });

  it("getByFrequency ordena por contagem (desc)", () => {
    const store = createOperatorRecentsStore();
    store.recordUsage(REF_1, "João 3:16");
    store.recordUsage(REF_2, "Romanos 8:28");
    store.recordUsage(REF_2, "Romanos 8:28");
    store.recordUsage(REF_3, "Gênesis 1:1");
    store.recordUsage(REF_3, "Gênesis 1:1");
    store.recordUsage(REF_3, "Gênesis 1:1");

    const byFreq = store.getByFrequency(10);
    expect(byFreq[0].ref).toEqual(REF_3); // count 3
    expect(byFreq[1].ref).toEqual(REF_2); // count 2
    expect(byFreq[2].ref).toEqual(REF_1); // count 1
  });

  it("getByFrequency respeita limit", () => {
    const store = createOperatorRecentsStore();
    store.recordUsage(REF_1, "João 3:16");
    store.recordUsage(REF_2, "Romanos 8:28");
    store.recordUsage(REF_3, "Gênesis 1:1");
    expect(store.getByFrequency(2)).toHaveLength(2);
  });

  it("setEntries substitui lista", () => {
    const store = createOperatorRecentsStore();
    store.recordUsage(REF_1, "João 3:16");
    store.setEntries([
      { ref: REF_2, label: "Romanos 8:28", count: 5, lastUsed: Date.now() },
    ]);
    expect(store.current!.data.entries).toHaveLength(1);
    expect(store.current!.data.entries[0].ref).toEqual(REF_2);
  });
});

describe("createOperatorStores", () => {
  it("retorna os 3 stores", () => {
    const stores = createOperatorStores();
    expect(stores.workspace).toBeDefined();
    expect(stores.favorites).toBeDefined();
    expect(stores.recents).toBeDefined();
    expect(stores.workspace.current!.data.selected).toBeNull();
    expect(stores.favorites.current!.data.favorites).toEqual([]);
    expect(stores.recents.current!.data.entries).toEqual([]);
  });
});
