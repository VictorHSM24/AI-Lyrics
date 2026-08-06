/**
 * HistoryList (Sprint 25 Fase B) — histórico de apresentações.
 *
 * Extraído do OperatorPanel monolítico para componente próprio.
 * Lista apresentações em tempo real (do VersePresentationStore via
 * useVersePresentation).
 *
 * Fase C adicionará: busca no histórico, horário, versão, origem
 * (Automático/Manual), clique para reapresentar.
 */

import { History, CheckCircle2, XCircle, Loader2, ChevronRight } from "lucide-react";
import { useMemo } from "react";
import { cn, formatLatency } from "@/utils";

export interface HistoryEntry {
  id: string;
  reference: string;
  status: string;
  totalLatencyMs: number;
  timestamp: number;
  book?: string;
  chapter?: number;
  verse?: number;
}

interface HistoryListProps {
  entries: HistoryEntry[];
  liveCurrent: HistoryEntry | null;
  className?: string;
}

export function HistoryList({ entries, liveCurrent, className }: HistoryListProps) {
  const sorted = useMemo(
    () => [...entries].sort((a, b) => b.timestamp - a.timestamp),
    [entries],
  );

  return (
    <div
      className={cn("flex flex-col gap-2 rounded-lg border border-border bg-surface p-4", className)}
      data-testid="operator-history"
    >
      <div className="flex items-center gap-2">
        <History className="h-4 w-4 text-text-muted" />
        <h3 className="text-sm font-semibold text-text">Histórico</h3>
        {liveCurrent && (
          <span className="ml-auto text-[10px] text-status-success flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-status-success animate-pulse" />
            ao vivo
          </span>
        )}
      </div>

      {sorted.length === 0 ? (
        <p className="text-xs text-text-muted italic py-4 text-center">
          Nenhuma apresentação ainda.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5 max-h-72 overflow-y-auto">
          {sorted.map((entry) => (
            <HistoryRow key={entry.id} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}

function HistoryRow({ entry }: { entry: HistoryEntry }) {
  const Icon = entry.status === "presented" ? CheckCircle2 : entry.status === "failed" ? XCircle : Loader2;
  const colorClass =
    entry.status === "presented" ? "text-status-success" :
    entry.status === "failed" ? "text-status-error" :
    "text-status-warning";

  return (
    <div
      className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-elevated px-2.5 py-1.5"
      data-testid="operator-history-row"
    >
      <Icon className={cn("h-3 w-3 shrink-0", colorClass, entry.status === "presenting" && "animate-spin")} />
      <span className="text-xs font-medium text-text flex-1">{entry.reference}</span>
      <ChevronRight className="h-3 w-3 text-text-subtle" />
      <span className="text-[10px] text-text-subtle">
        {entry.totalLatencyMs > 0 ? formatLatency(entry.totalLatencyMs) : "—"}
      </span>
    </div>
  );
}
