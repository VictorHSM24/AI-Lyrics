/**
 * FavoritesPanel (Sprint 25 Fase C) — favoritos persistidos.
 *
 * Recursos:
 * - Persistência via useLocalStorage (Fase A)
 * - Sincronização com OperatorFavoritesStore (Fase A)
 * - Clique: seleciona + preview (SelectByReferenceCommand)
 * - Duplo clique: apresenta (PresentVerseCommand)
 * - Botão ⭐ para marcar/desmarcar versículo selecionado atual
 * - Ordenação: manual, alfabética, mais utilizados
 * - Remoção individual
 *
 * Reusa:
 * - useLocalStorage (Fase A)
 * - OperatorFavoritesStore (Fase A)
 * - SelectByReferenceCommand, PresentVerseCommand (Fase B)
 * - WorkspaceContext (Fase B)
 */

import { Star, X, ChevronRight, ArrowDownUp } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocalStorage, useStores, useWorkspaceSnapshot, useFavoritesSnapshot, useRecentsSnapshot } from "@/hooks";
import { cn } from "@/utils";
import {
  SelectByReferenceCommand,
  PresentVerseCommand,
  type WorkspaceContext,
} from "./WorkspaceCommands";
import type { OperatorFavorite } from "@/stores";

type SortMode = "manual" | "alphabetical" | "mostUsed";

const STORAGE_KEY = "ai-lyrics:operator:favorites";

interface FavoritesPanelProps {
  ctx: WorkspaceContext;
  className?: string;
}

export function FavoritesPanel({ ctx, className }: FavoritesPanelProps) {
  const stores = useStores();
  const favoritesStore = stores.favorites;
  // Assinar stores reativamente para re-renderizar quando selected,
  // favoritos ou recents mudam via comandos.
  const workspaceSnap = useWorkspaceSnapshot();
  const favoritesSnap = useFavoritesSnapshot();
  const recentsSnap = useRecentsSnapshot();
  const selected = workspaceSnap?.data.selected ?? null;

  // Persistir favoritos em localStorage (Fase A).
  const { value: persistedFavorites, setValue: setPersistedFavorites } = useLocalStorage<OperatorFavorite[]>(
    STORAGE_KEY,
    [],
  );

  // Ref compartilhado para quebrar o loop de sincronização bidirecional.
  // Guarda a última serialização JSON sincronizada entre store e localStorage.
  // Sem isso, os dois effects abaixo se chamam indefinidamente porque cada
  // set cria uma nova referência de array (mesmo com conteúdo igual).
  const lastSyncedRef = useRef<string>("");

  // Sincronizar store com localStorage quando localStorage mudar
  // (ex.: carga inicial, mudança em outra aba via storage event).
  useEffect(() => {
    const serialized = JSON.stringify(persistedFavorites);
    if (serialized === lastSyncedRef.current) return;
    lastSyncedRef.current = serialized;
    favoritesStore.setFavorites(persistedFavorites);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [persistedFavorites]);

  // Sincronizar localStorage quando store mudar (add/remove).
  // Usar snapshot reativo para detectar mudanças no store.
  const favorites = favoritesSnap?.data.favorites ?? [];
  useEffect(() => {
    const serialized = JSON.stringify(favorites);
    if (serialized === lastSyncedRef.current) return;
    lastSyncedRef.current = serialized;
    setPersistedFavorites(favorites);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [favorites]);

  const [sortMode, setSortMode] = useState<SortMode>("manual");

  // Favoritos ordenados conforme modo.
  const sortedFavorites = useMemo(() => {
    const list = [...favorites];
    switch (sortMode) {
      case "alphabetical":
        return list.sort((a, b) => a.label.localeCompare(b.label, "pt-BR"));
      case "mostUsed": {
        // Ordenar por frequência de uso (do RecentsStore).
        const recentsEntries = recentsSnap?.data.entries ?? [];
        const freqMap = new Map<string, number>();
        for (const entry of recentsEntries) {
          const key = `${entry.ref.bookId}:${entry.ref.chapter}:${entry.ref.verse}`;
          freqMap.set(key, entry.count);
        }
        return list.sort((a, b) => {
          const freqA = freqMap.get(`${a.ref.bookId}:${a.ref.chapter}:${a.ref.verse}`) ?? 0;
          const freqB = freqMap.get(`${b.ref.bookId}:${b.ref.chapter}:${b.ref.verse}`) ?? 0;
          if (freqB !== freqA) return freqB - freqA;
          return a.label.localeCompare(b.label, "pt-BR");
        });
      }
      case "manual":
      default:
        // Manter ordem de inserção (createdAt).
        return list.sort((a, b) => a.createdAt - b.createdAt);
    }
  }, [favorites, sortMode, recentsSnap]);

  // Toggle favorito do versículo selecionado.
  const onToggleSelected = useCallback(() => {
    if (!selected) return;
    if (favoritesStore.isFavorite(selected)) {
      favoritesStore.removeByRef(selected);
    } else {
      // Label = referência formatada (aproximada; o backend pode confirmar).
      const label = `${selected.bookId}:${selected.chapter}:${selected.verse}`;
      favoritesStore.addFavorite(selected, label);
    }
  }, [selected, favoritesStore]);

  const isCurrentFavorite = selected ? favoritesStore.isFavorite(selected) : false;

  const onSelectFavorite = useCallback(
    async (fav: OperatorFavorite) => {
      await SelectByReferenceCommand(ctx, fav.ref);
    },
    [ctx],
  );

  const onPresentFavorite = useCallback(
    async (fav: OperatorFavorite) => {
      await SelectByReferenceCommand(ctx, fav.ref);
      await PresentVerseCommand(ctx);
    },
    [ctx],
  );

  const onRemoveFavorite = useCallback(
    (fav: OperatorFavorite) => {
      favoritesStore.removeFavorite(fav.id);
    },
    [favoritesStore],
  );

  return (
    <div
      className={cn("flex flex-col gap-2 rounded-lg border border-border bg-surface p-4", className)}
      data-testid="favorites-panel"
    >
      <div className="flex items-center gap-2">
        <Star className="h-4 w-4 text-status-warning" />
        <h3 className="text-sm font-semibold text-text">Favoritos</h3>
        <span className="ml-auto text-[10px] text-text-subtle">
          {favorites.length} {favorites.length === 1 ? "item" : "itens"}
        </span>
      </div>

      {/* Botão marcar/desmarcar versículo selecionado */}
      <button
        onClick={onToggleSelected}
        disabled={!selected}
        className={cn(
          "flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-xs font-medium transition-colors min-h-[36px]",
          !selected
            ? "border-border bg-surface-hover text-text-muted cursor-not-allowed"
            : isCurrentFavorite
              ? "border-status-warning/40 bg-status-warning/10 text-status-warning hover:bg-status-warning/20"
              : "border-border bg-surface hover:bg-surface-hover text-text",
        )}
        data-testid="favorite-toggle-selected"
        aria-label={isCurrentFavorite ? "Remover dos favoritos" : "Adicionar aos favoritos"}
      >
        <Star className={cn("h-3.5 w-3.5", isCurrentFavorite && "fill-current")} />
        {isCurrentFavorite ? "Remover dos favoritos" : "Adicionar aos favoritos"}
      </button>

      {/* Controle de ordenação */}
      {favorites.length > 0 && (
        <div className="flex items-center gap-1 text-[10px]">
          <ArrowDownUp className="h-3 w-3 text-text-muted" />
          <SortButton active={sortMode === "manual"} onClick={() => setSortMode("manual")} label="Manual" />
          <SortButton active={sortMode === "alphabetical"} onClick={() => setSortMode("alphabetical")} label="A-Z" />
          <SortButton active={sortMode === "mostUsed"} onClick={() => setSortMode("mostUsed")} label="Mais usados" />
        </div>
      )}

      {/* Lista de favoritos */}
      {sortedFavorites.length === 0 ? (
        <p className="text-xs text-text-muted italic py-4 text-center">
          Nenhum favorito ainda. Marque versículos com ⭐.
        </p>
      ) : (
        <div className="flex flex-col gap-1 max-h-72 overflow-y-auto">
          {sortedFavorites.map((fav) => (
            <FavoriteItem
              key={fav.id}
              favorite={fav}
              onSelect={() => onSelectFavorite(fav)}
              onPresent={() => onPresentFavorite(fav)}
              onRemove={() => onRemoveFavorite(fav)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================
// FavoriteItem — item individual
// ============================================================

interface FavoriteItemProps {
  favorite: OperatorFavorite;
  onSelect: () => void;
  onPresent: () => void;
  onRemove: () => void;
}

function FavoriteItem({ favorite, onSelect, onPresent, onRemove }: FavoriteItemProps) {
  return (
    <div
      onClick={onSelect}
      onDoubleClick={onPresent}
      className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-elevated px-2.5 py-2 cursor-pointer transition-colors hover:bg-surface-hover min-h-[40px] group"
      data-testid="favorite-item"
      title="Clique para selecionar · Duplo clique para apresentar"
    >
      <Star className="h-3 w-3 text-status-warning fill-current shrink-0" />
      <span className="text-xs font-medium text-text flex-1 truncate">
        {favorite.label}
      </span>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        className="text-text-subtle hover:text-status-error transition-colors p-1 rounded opacity-0 group-hover:opacity-100"
        aria-label="Remover favorito"
        data-testid="favorite-remove"
      >
        <X className="h-3 w-3" />
      </button>
      <ChevronRight className="h-3 w-3 text-text-subtle shrink-0" />
    </div>
  );
}

// ============================================================
// SortButton — botão de modo de ordenação
// ============================================================

interface SortButtonProps {
  active: boolean;
  onClick: () => void;
  label: string;
}

function SortButton({ active, onClick, label }: SortButtonProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-2 py-1 rounded text-[10px] font-medium transition-colors min-h-[28px]",
        active
          ? "bg-primary/15 text-primary"
          : "bg-surface-hover text-text-muted hover:text-text",
      )}
      aria-pressed={active}
    >
      {label}
    </button>
  );
}
