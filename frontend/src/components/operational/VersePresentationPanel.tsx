/**
 * VersePresentationPanel — painel de apresentação automática (Sprint 18).
 *
 * Mostra:
 * - Última apresentação: livro, capítulo, versículo, horário, latência, status
 * - Status possíveis: Apresentando | Apresentado | Falhou
 * - Histórico das últimas apresentações
 *
 * Atualização em tempo real via EventStream → VersePresentationStore
 * → useVersePresentation.
 *
 * Eventos que alimentam este painel:
 *   VerseResolving           → status="Apresentando"
 *   VerseResolved            → status="Apresentando" (com texto do versículo)
 *   VersePresented           → status="Apresentado"
 *   VersePresentationFailed  → status="Falhou"
 */

import {
  Send,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  History,
  BookOpen,
} from "lucide-react";
import { useVersePresentation } from "@/hooks";
import type { VersePresentationEntry } from "@/stores";
import { cn } from "@/utils";

interface VersePresentationPanelProps {
  className?: string;
}

export function VersePresentationPanel({ className }: VersePresentationPanelProps) {
  const { current, entries, loading } = useVersePresentation();

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-lg border border-border bg-surface p-4",
        className,
      )}
      data-testid="verse-presentation-panel"
    >
      {/* Header */}
      <div className="flex items-center gap-2">
        <Send className="h-4 w-4 text-emerald-400" />
        <h3 className="text-sm font-semibold text-text">
          Apresentação Automática
        </h3>
      </div>

      {/* Apresentação atual */}
      {loading ? (
        <p className="text-xs text-text-muted">Carregando...</p>
      ) : current ? (
        <CurrentPresentation entry={current} />
      ) : (
        <p className="text-xs text-text-muted italic">
          Nenhuma apresentação iniciada ainda.
        </p>
      )}

      {/* Histórico */}
      {entries.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-1.5 text-[10px] font-medium text-text-muted uppercase tracking-wide">
            <History className="h-3 w-3" />
            Histórico
          </div>
          <div
            className="flex flex-col gap-1.5 max-h-48 overflow-y-auto"
            data-testid="verse-presentation-history"
          >
            {entries.map((entry) => (
              <HistoryRow key={entry.id} entry={entry} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================
// Apresentação atual — card com detalhes completos.
// ============================================================

function CurrentPresentation({ entry }: { entry: VersePresentationEntry }) {
  const status = getStatusInfo(entry.status);

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-md border bg-surface-elevated px-3 py-3",
        status.borderClass,
      )}
      data-testid="verse-presentation-current"
    >
      {/* Referência + Status badge */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-primary" />
          <span className="text-lg font-bold text-text">
            {entry.reference || "—"}
          </span>
        </div>
        <StatusBadge status={entry.status} />
      </div>

      {/* Texto do versículo (se resolvido) */}
      {entry.verseText && (
        <p
          className="text-xs text-text italic border-t border-border-subtle pt-2"
          data-testid="verse-presentation-text"
        >
          "{entry.verseText}"
        </p>
      )}

      {/* Detalhes */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <DetailRow label="Livro" value={entry.book} />
        <DetailRow label="Capítulo" value={String(entry.chapter)} />
        <DetailRow label="Versículo" value={String(entry.verse)} />
        <DetailRow label="Versão" value={entry.version || "—"} />
        <DetailRow
          label="Horário"
          value={formatTimestamp(entry.timestamp)}
        />
        <DetailRow
          label="Latência"
          value={
            entry.totalLatencyMs > 0
              ? `${entry.totalLatencyMs}ms`
              : "—"
          }
        />
      </div>

      {/* Latência do Holyrics (apenas se apresentado) */}
      {entry.status === "presented" && entry.holyricsLatencyMs > 0 && (
        <div className="flex items-center gap-1.5 text-[10px] text-text-subtle">
          <Clock className="h-3 w-3" />
          Holyrics: {entry.holyricsLatencyMs}ms · status: {entry.holyricsStatus}
          {entry.quickPresentation && " · quick"}
        </div>
      )}

      {/* Erro (se falhou) */}
      {entry.status === "failed" && (
        <div
          className="flex items-start gap-2 rounded-md border border-status-error/30 bg-status-error/10 px-2.5 py-1.5"
          data-testid="verse-presentation-error"
        >
          <XCircle className="h-3.5 w-3.5 shrink-0 text-status-error mt-0.5" />
          <div className="flex flex-col gap-0.5">
            <p className="text-xs font-medium text-status-error">
              Falha em: {stageLabel(entry.failureStage)}
            </p>
            <p className="text-[10px] text-text-muted">
              {entry.errorType}: {entry.errorMessage}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================
// Linha do histórico — versão compacta.
// ============================================================

function HistoryRow({ entry }: { entry: VersePresentationEntry }) {
  const status = getStatusInfo(entry.status);
  const Icon = status.icon;

  return (
    <div
      className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-elevated px-2.5 py-1.5"
      data-testid="verse-presentation-history-row"
    >
      <Icon className={cn("h-3 w-3 shrink-0", status.colorClass)} />
      <span className="text-xs font-medium text-text flex-1">
        {entry.reference || "—"}
      </span>
      <span className="text-[10px] text-text-subtle">
        {entry.totalLatencyMs > 0 ? `${entry.totalLatencyMs}ms` : "—"}
      </span>
    </div>
  );
}

// ============================================================
// StatusBadge — badge colorido conforme o status.
// ============================================================

function StatusBadge({ status }: { status: VersePresentationEntry["status"] }) {
  const info = getStatusInfo(status);
  const Icon = info.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
        info.borderClass,
        info.bgClass,
        info.colorClass,
      )}
      data-testid="verse-presentation-status"
      data-status={status}
    >
      <Icon className="h-3 w-3" />
      {info.label}
    </span>
  );
}

// ============================================================
// Helpers
// ============================================================

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-text-muted">{label}:</span>
      <span className="font-medium text-text">{value}</span>
    </div>
  );
}

interface StatusInfo {
  label: string;
  icon: typeof CheckCircle2;
  colorClass: string;
  bgClass: string;
  borderClass: string;
}

function getStatusInfo(status: VersePresentationEntry["status"]): StatusInfo {
  switch (status) {
    case "presenting":
      return {
        label: "Apresentando",
        icon: Loader2,
        colorClass: "text-status-warning",
        bgClass: "bg-status-warning/10",
        borderClass: "border-status-warning/30",
      };
    case "presented":
      return {
        label: "Apresentado",
        icon: CheckCircle2,
        colorClass: "text-status-healthy",
        bgClass: "bg-status-healthy/10",
        borderClass: "border-status-healthy/30",
      };
    case "failed":
      return {
        label: "Falhou",
        icon: XCircle,
        colorClass: "text-status-error",
        bgClass: "bg-status-error/10",
        borderClass: "border-status-error/30",
      };
    case "idle":
    default:
      return {
        label: "Ocioso",
        icon: Clock,
        colorClass: "text-text-muted",
        bgClass: "bg-surface",
        borderClass: "border-border",
      };
  }
}

function stageLabel(stage: string): string {
  switch (stage) {
    case "search":
      return "Busca do versículo";
    case "holyrics":
      return "Apresentação no Holyrics";
    case "internal":
      return "Erro interno";
    default:
      return stage || "Desconhecido";
  }
}

function formatTimestamp(ts: number): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
