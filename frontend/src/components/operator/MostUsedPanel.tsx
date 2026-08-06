/**
 * MostUsedPanel (Sprint 25 Fase C) — referências mais utilizadas.
 *
 * Derivado automaticamente do OperatorRecentsStore (Fase A).
 * NÃO armazena dados separadamente — apenas projeta o RecentsStore
 * ordenado por frequência.
 *
 * Recursos:
 * - Lista ordenada por count (desc)
 * - Clique: seleciona + preview
 * - Duplo clique: apresenta
 * - Atualiza automaticamente quando recents mudam
 * - Mostra contagem de uso ao lado
 *
 * Reusa:
 * - OperatorRecentsStore.getByFrequency() (Fase A)
 * - SelectByReferenceCommand, PresentVerseCommand (Fase B)
 * - WorkspaceContext (Fase B)
 */

import { Flame, ChevronRight } from "lucide-react";
import { useCallback, useMemo } from "react";
import { useRecentsSnapshot, useStores } from "@/hooks";
import { cn } from "@/utils";
import {
  SelectByReferenceCommand,
  PresentVerseCommand,
  type WorkspaceContext,
} from "./WorkspaceCommands";
import type { OperatorRecentEntry } from "@/stores";

interface MostUsedPanelProps {
  ctx: WorkspaceContext;
  className?: string;
  /** Número máximo de itens a exibir. */
  limit?: number;
}

export function MostUsedPanel({ ctx, className, limit = 10 }: MostUsedPanelProps) {
  const recentsStore = useStores().recents;
  // Assinar o recents store reativamente para re-renderizar quando
  // novas apresentações incrementam o contador de uso.
  const recentsSnap = useRecentsSnapshot();

  // Derivar lista por frequência (não armazena, apenas projeta).
  // Depende de recentsSnap para recompute quando o store muda.
  const entries: OperatorRecentEntry[] = useMemo(() => {
    void recentsSnap; // re-trigger memo quando snapshot muda
    return recentsStore.getByFrequency(limit);
  }, [recentsStore, limit, recentsSnap]);

  const onSelect = useCallback(
    async (entry: OperatorRecentEntry) => {
      await SelectByReferenceCommand(ctx, entry.ref);
    },
    [ctx],
  );

  const onPresent = useCallback(
    async (entry: OperatorRecentEntry) => {
      await SelectByReferenceCommand(ctx, entry.ref);
      await PresentVerseCommand(ctx);
    },
    [ctx],
  );

  return (
    <div
      className={cn("flex flex-col gap-2 rounded-lg border border-border bg-surface p-4", className)}
      data-testid="most-used-panel"
    >
      <div className="flex items-center gap-2">
        <Flame className="h-4 w-4 text-status-warning" />
        <h3 className="text-sm font-semibold text-text">Mais Utilizados</h3>
        <span className="ml-auto text-[10px] text-text-subtle">
          {entries.length} {entries.length === 1 ? "item" : "itens"}
        </span>
      </div>

      {entries.length === 0 ? (
        <p className="text-xs text-text-muted italic py-4 text-center">
          Nenhum uso registrado ainda.
        </p>
      ) : (
        <div className="flex flex-col gap-1 max-h-64 overflow-y-auto">
          {entries.map((entry, index) => (
            <MostUsedItem
              key={`${entry.ref.bookId}-${entry.ref.chapter}-${entry.ref.verse}`}
              entry={entry}
              rank={index + 1}
              onSelect={() => onSelect(entry)}
              onPresent={() => onPresent(entry)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================
// MostUsedItem — item individual
// ============================================================

interface MostUsedItemProps {
  entry: OperatorRecentEntry;
  rank: number;
  onSelect: () => void;
  onPresent: () => void;
}

function MostUsedItem({ entry, rank, onSelect, onPresent }: MostUsedItemProps) {
  return (
    <div
      onClick={onSelect}
      onDoubleClick={onPresent}
      className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-elevated px-2.5 py-2 cursor-pointer transition-colors hover:bg-surface-hover min-h-[40px]"
      data-testid="most-used-item"
      title="Clique para selecionar · Duplo clique para apresentar"
    >
      {/* Rank (posição no ranking) */}
      <span
        className={cn(
          "text-[10px] font-bold tabular-nums w-5 text-center shrink-0",
          rank === 1 ? "text-status-warning" : "text-text-subtle",
        )}
      >
        {rank}
      </span>

      {/* Referência */}
      <span className="text-xs font-medium text-text flex-1 truncate">
        {entry.label}
      </span>

      {/* Contagem de uso */}
      <span className="flex items-center gap-1 text-[10px] text-text-subtle shrink-0">
        <Flame className="h-2.5 w-2.5" />
        {entry.count}×
      </span>

      <ChevronRight className="h-3 w-3 text-text-subtle shrink-0" />
    </div>
  );
}
