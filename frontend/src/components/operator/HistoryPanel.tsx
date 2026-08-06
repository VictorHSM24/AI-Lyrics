/**
 * HistoryPanel (Sprint 25 Fase C) — histórico inteligente.
 *
 * Recursos:
 * - Busca/filtro por texto (ex.: "rom" → Romanos 8:28, Romanos 12:2)
 * - Filtro por origem (Todos / IA / Operador)
 * - Agrupamento por sessão temporal (Hoje, Ontem, Semana passada)
 * - Cada item: horário, referência, versão, origem (🤖 IA / 👤 Operador)
 * - Clique: seleciona + atualiza preview (SelectByReferenceCommand)
 * - Duplo clique: apresenta imediatamente (PresentVerseCommand)
 *
 * Reusa:
 * - useVersePresentation (entries em tempo real do VersePresentationStore)
 * - SelectByReferenceCommand, PresentVerseCommand (Fase B)
 * - WorkspaceContext (Fase B)
 */

import { Bot, User, Search, History, ChevronRight } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useVersePresentation } from "@/hooks";
import { cn, formatLatency } from "@/utils";
import {
  SelectByReferenceCommand,
  PresentVerseCommand,
  type WorkspaceContext,
} from "./WorkspaceCommands";
import type { VersePresentationEntry } from "@/stores";

type OriginFilter = "all" | "ai" | "operator";

interface HistoryPanelProps {
  ctx: WorkspaceContext;
  className?: string;
}

export function HistoryPanel({ ctx, className }: HistoryPanelProps) {
  const { entries } = useVersePresentation();
  const [filter, setFilter] = useState("");
  const [originFilter, setOriginFilter] = useState<OriginFilter>("all");

  // Filtrar entries por texto e origem.
  const filtered = useMemo(() => {
    const sorted = [...entries].sort((a, b) => b.timestamp - a.timestamp);
    return sorted.filter((entry) => {
      // Filtro por texto (referência ou livro).
      if (filter.trim()) {
        const q = filter.trim().toLowerCase();
        if (!entry.reference.toLowerCase().includes(q) &&
            !entry.book.toLowerCase().includes(q)) {
          return false;
        }
      }
      // Filtro por origem.
      if (originFilter !== "all") {
        const isOperator = entry.origin === "OperatorPanel";
        if (originFilter === "operator" && !isOperator) return false;
        if (originFilter === "ai" && isOperator) return false;
      }
      // Só mostrar apresentações concluídas ou falhas (não "presenting").
      return entry.status === "presented" || entry.status === "failed";
    });
  }, [entries, filter, originFilter]);

  // Agrupar por sessão temporal.
  const grouped = useMemo(() => groupByTimeSession(filtered), [filtered]);

  const onSelectEntry = useCallback(
    async (entry: VersePresentationEntry) => {
      // Clique: seleciona + atualiza preview.
      await SelectByReferenceCommand(ctx, {
        bookId: entry.bookId,
        chapter: entry.chapter,
        verse: entry.verse,
      });
    },
    [ctx],
  );

  const onPresentEntry = useCallback(
    async (entry: VersePresentationEntry) => {
      // Duplo clique: seleciona + apresenta.
      await SelectByReferenceCommand(ctx, {
        bookId: entry.bookId,
        chapter: entry.chapter,
        verse: entry.verse,
      });
      await PresentVerseCommand(ctx);
    },
    [ctx],
  );

  return (
    <div
      className={cn("flex flex-col gap-2 rounded-lg border border-border bg-surface p-4", className)}
      data-testid="history-panel"
    >
      <div className="flex items-center gap-2">
        <History className="h-4 w-4 text-text-muted" />
        <h3 className="text-sm font-semibold text-text">Histórico</h3>
        <span className="ml-auto text-[10px] text-text-subtle">
          {filtered.length} {filtered.length === 1 ? "item" : "itens"}
        </span>
      </div>

      {/* Busca no histórico */}
      <div className="flex items-center gap-2 rounded-md border border-border bg-surface-elevated px-2.5 py-1.5">
        <Search className="h-3 w-3 text-text-muted shrink-0" />
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filtrar histórico..."
          className="flex-1 bg-transparent text-xs text-text placeholder:text-text-muted outline-none min-w-0"
          aria-label="Filtrar histórico"
          data-testid="history-filter"
        />
      </div>

      {/* Filtro por origem */}
      <div className="flex items-center gap-1 text-[10px]">
        <FilterButton
          active={originFilter === "all"}
          onClick={() => setOriginFilter("all")}
          label="Todos"
        />
        <FilterButton
          active={originFilter === "ai"}
          onClick={() => setOriginFilter("ai")}
          label="🤖 IA"
        />
        <FilterButton
          active={originFilter === "operator"}
          onClick={() => setOriginFilter("operator")}
          label="👤 Operador"
        />
      </div>

      {/* Lista agrupada */}
      {filtered.length === 0 ? (
        <p className="text-xs text-text-muted italic py-4 text-center">
          {entries.length === 0 ? "Nenhuma apresentação ainda." : "Nenhum item corresponde ao filtro."}
        </p>
      ) : (
        <div className="flex flex-col gap-3 max-h-96 overflow-y-auto">
          {grouped.map((group) => (
            <HistoryGroup
              key={group.label}
              label={group.label}
              entries={group.entries}
              onSelect={onSelectEntry}
              onPresent={onPresentEntry}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================
// HistoryGroup — grupo temporal (Hoje, Ontem, etc.)
// ============================================================

interface HistoryGroupProps {
  label: string;
  entries: VersePresentationEntry[];
  onSelect: (entry: VersePresentationEntry) => void;
  onPresent: (entry: VersePresentationEntry) => void;
}

function HistoryGroup({ label, entries, onSelect, onPresent }: HistoryGroupProps) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wide px-1">
        {label}
      </span>
      {entries.map((entry) => (
        <HistoryItem
          key={entry.id}
          entry={entry}
          onSelect={() => onSelect(entry)}
          onPresent={() => onPresent(entry)}
        />
      ))}
    </div>
  );
}

// ============================================================
// HistoryItem — item individual
// ============================================================

interface HistoryItemProps {
  entry: VersePresentationEntry;
  onSelect: () => void;
  onPresent: () => void;
}

function HistoryItem({ entry, onSelect, onPresent }: HistoryItemProps) {
  const isOperator = entry.origin === "OperatorPanel";
  const time = formatTime(entry.timestamp);

  return (
    <div
      onClick={onSelect}
      onDoubleClick={onPresent}
      className={cn(
        "flex items-center gap-2 rounded-md border border-border-subtle bg-surface-elevated px-2.5 py-2 cursor-pointer transition-colors hover:bg-surface-hover min-h-[40px]",
        entry.status === "failed" && "border-status-error/30",
      )}
      data-testid="history-item"
      title="Clique para selecionar · Duplo clique para apresentar"
    >
      {/* Horário */}
      <span className="text-[10px] text-text-subtle tabular-nums w-10 shrink-0">
        {time}
      </span>

      {/* Origem */}
      <span className="shrink-0" title={isOperator ? "Operador" : "IA"}>
        {isOperator ? (
          <User className="h-3 w-3 text-primary" />
        ) : (
          <Bot className="h-3 w-3 text-status-success" />
        )}
      </span>

      {/* Referência */}
      <span className="text-xs font-medium text-text flex-1 truncate">
        {entry.reference}
      </span>

      {/* Versão */}
      <span className="text-[10px] text-text-subtle shrink-0">
        {entry.version}
      </span>

      {/* Status/latência */}
      {entry.status === "presented" && (
        <span className="text-[10px] text-text-subtle tabular-nums shrink-0">
          {formatLatency(entry.totalLatencyMs)}
        </span>
      )}
      {entry.status === "failed" && (
        <span className="text-[10px] text-status-error shrink-0">falha</span>
      )}

      <ChevronRight className="h-3 w-3 text-text-subtle shrink-0" />
    </div>
  );
}

// ============================================================
// FilterButton — botão de filtro por origem
// ============================================================

interface FilterButtonProps {
  active: boolean;
  onClick: () => void;
  label: string;
}

function FilterButton({ active, onClick, label }: FilterButtonProps) {
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

// ============================================================
// Helpers
// ============================================================

interface TimeGroup {
  label: string;
  entries: VersePresentationEntry[];
}

/**
 * Agrupa entries por sessão temporal: Hoje, Ontem, Semana passada, Mais antigo.
 */
function groupByTimeSession(entries: VersePresentationEntry[]): TimeGroup[] {
  const now = Date.now();
  const startOfToday = new Date(now);
  startOfToday.setHours(0, 0, 0, 0);
  const startOfYesterday = new Date(startOfToday.getTime() - 86400000);
  const startOfWeek = new Date(startOfToday.getTime() - 7 * 86400000);

  const groups: TimeGroup[] = [
    { label: "Hoje", entries: [] },
    { label: "Ontem", entries: [] },
    { label: "Semana passada", entries: [] },
    { label: "Mais antigo", entries: [] },
  ];

  for (const entry of entries) {
    const ts = entry.timestamp * 1000; // timestamp é em segundos
    if (ts >= startOfToday.getTime()) {
      groups[0].entries.push(entry);
    } else if (ts >= startOfYesterday.getTime()) {
      groups[1].entries.push(entry);
    } else if (ts >= startOfWeek.getTime()) {
      groups[2].entries.push(entry);
    } else {
      groups[3].entries.push(entry);
    }
  }

  // Remover grupos vazios.
  return groups.filter((g) => g.entries.length > 0);
}

/**
 * Formata timestamp (segundos) para HH:MM.
 */
function formatTime(timestampSec: number): string {
  const d = new Date(timestampSec * 1000);
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}
