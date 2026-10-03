/**
 * PresentationCards (Sprint 25 Fase B) — card "Apresentado" (ao vivo).
 *
 * Antes continha também o SelectedCard (preview do versículo
 * selecionado + botão "Apresentar"). Após a fusão com QuickNavigator,
 * o preview do versículo selecionado agora vive dentro do próprio
 * QuickNavigator, e a navegação pelas setas apresenta automaticamente.
 *
 * Restou apenas o PresentedCard — aquilo que está no Holyrics agora,
 * atualizado em tempo real via VersePresentationStore.
 */

import { useState } from "react";
import { Loader2, CheckCircle2, Radio, XCircle, MonitorX } from "lucide-react";
import { useServices, useVersePresentation } from "@/hooks";
import { cn, formatLatency, formatVersionKey } from "@/utils";
import type { OperatorPresentResultDTO } from "@/types";

interface PresentationCardsProps {
  /** Último resultado de apresentação (para feedback discreto). */
  lastPresentResult: OperatorPresentResultDTO | null;
  className?: string;
}

export function PresentationCards({
  lastPresentResult,
  className,
}: PresentationCardsProps) {
  const { current: presentedEntry } = useVersePresentation();

  return (
    <div className={cn("flex flex-col gap-3", className)} data-testid="presentation-cards">
      {/* Card: Apresentado (ao vivo) */}
      <PresentedCard entry={presentedEntry} />

      {/* Feedback discreto do último resultado */}
      {lastPresentResult && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-md border px-2.5 py-1.5",
            lastPresentResult.ok
              ? "border-status-success/30 bg-status-success/10"
              : "border-status-error/30 bg-status-error/10",
          )}
          data-testid="operator-last-result"
        >
          {lastPresentResult.ok ? (
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-status-success" />
          ) : (
            <XCircle className="h-3.5 w-3.5 shrink-0 text-status-error" />
          )}
          <span className="text-xs font-medium text-text">
            {lastPresentResult.reference} · {formatLatency(lastPresentResult.latency_ms)}
          </span>
          {!lastPresentResult.ok && (
            <span className="text-[10px] text-text-muted truncate">{lastPresentResult.message}</span>
          )}
        </div>
      )}
    </div>
  );
}

// ============================================================
// PresentedCard — versículo no Holyrics (ao vivo)
// ============================================================

interface PresentedCardProps {
  entry: ReturnType<typeof useVersePresentation>["current"];
}

function PresentedCard({ entry }: PresentedCardProps) {
  const services = useServices();
  const [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState<string | null>(null);

  // Encerrar apresentação no Holyrics — equivalente ao ESC, libera o
  // telão. O card limpa sozinho via evento VersePresentationClosed.
  const handleClose = async () => {
    setClosing(true);
    setCloseError(null);
    try {
      const res = await services.operator.closePresentation();
      if (!res.ok) setCloseError(res.message);
    } catch (e) {
      setCloseError(e instanceof Error ? e.message : String(e));
    } finally {
      setClosing(false);
    }
  };

  return (
    <div
      className="flex flex-col gap-2 rounded-lg border-2 border-status-success/40 bg-surface p-4"
      data-testid="presented-card"
    >
      <div className="flex items-center gap-2">
        <CheckCircle2 className="h-4 w-4 text-status-success" />
        <h3 className="text-sm font-semibold text-text">Apresentado</h3>
        {entry && entry.status === "presented" && (
          <span className="ml-auto flex items-center gap-2">
            <span className="flex items-center gap-1 text-[10px] text-status-success">
              <Radio className="h-3 w-3 animate-pulse" />
              ao vivo
            </span>
            <button
              type="button"
              onClick={handleClose}
              disabled={closing}
              title="Encerrar a apresentação no Holyrics (ESC) — libera o telão"
              className={cn(
                "flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-medium",
                "border-status-error/40 text-status-error hover:bg-status-error/10",
                "disabled:cursor-not-allowed disabled:opacity-50",
              )}
              data-testid="close-presentation-btn"
            >
              {closing ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <MonitorX className="h-3 w-3" />
              )}
              Encerrar
            </button>
          </span>
        )}
        {entry && entry.status === "presenting" && (
          <span className="ml-auto flex items-center gap-1 text-[10px] text-status-warning">
            <Loader2 className="h-3 w-3 animate-spin" />
            apresentando
          </span>
        )}
      </div>
      {closeError && (
        <p className="text-[10px] text-status-error" role="alert">
          {closeError}
        </p>
      )}

      {entry ? (
        <div className="flex flex-col gap-1.5">
          <span className="text-lg font-bold text-text">{entry.reference}</span>
          {entry.verseText && (
            <p className="text-sm text-text italic border-l-2 border-status-success/30 pl-3 leading-relaxed">
              "{entry.verseText}"
            </p>
          )}
          <div className="flex items-center gap-3 text-[10px] text-text-subtle">
            <span className="font-medium text-text-muted">{formatVersionKey(entry.version)}</span>
            <span>·</span>
            <span>{formatLatency(entry.totalLatencyMs)}</span>
            <span>·</span>
            <span className={cn(
              "px-1.5 py-0.5 rounded",
              entry.quickPresentation
                ? "bg-status-warning/20 text-status-warning"
                : "bg-surface-hover text-text-muted",
            )}>
              {entry.quickPresentation ? "Quick" : "Normal"}
            </span>
            {entry.status === "failed" && (
              <>
                <span>·</span>
                <span className="text-status-error">{entry.errorMessage}</span>
              </>
            )}
          </div>
        </div>
      ) : (
        <p className="text-xs text-text-muted italic py-2 text-center">
          Nenhum versículo apresentado ainda.
        </p>
      )}
    </div>
  );
}
