/**
 * PresentationCards (Sprint 25 Fase B) — separação visual entre
 * "Selecionado" e "Apresentado".
 *
 * Dois cards distintos, nunca um único card misturando os dois estados:
 *
 * 1. SelectedCard — aquilo que o operador está navegando (preview).
 *    Cor de destaque azul (primary). Exibe texto do versículo
 *    carregado via cache LRU. Botão "Apresentar" integrado.
 *
 * 2. PresentedCard — aquilo que está no Holyrics agora.
 *    Cor de destaque verde (success). Vem do VersePresentationStore
 *    em tempo real. Indicador "ao vivo" quando atualizado pela IA.
 *
 * A separação visual garante que o operador nunca confunda o que
 * está navegando com o que está sendo exibido no Holyrics.
 */

import { BookOpen, Send, Loader2, CheckCircle2, Radio, Zap, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useVersePresentation, useWorkspaceSnapshot } from "@/hooks";
import type { OperatorVerseDTO, OperatorPresentResultDTO } from "@/types";
import { cn, formatLatency } from "@/utils";
import { PresentVerseCommand, type WorkspaceContext } from "./WorkspaceCommands";

interface PresentationCardsProps {
  ctx: WorkspaceContext;
  /** Último resultado de apresentação (para feedback discreto). */
  lastPresentResult: OperatorPresentResultDTO | null;
  /** Se está apresentando agora (loading state). */
  presenting: boolean;
  className?: string;
}

export function PresentationCards({
  ctx,
  lastPresentResult,
  presenting,
  className,
}: PresentationCardsProps) {
  // Assinar workspace store reativamente para re-renderizar quando
  // selected muda via comandos de navegação.
  const workspaceSnap = useWorkspaceSnapshot();
  const selected = workspaceSnap?.data.selected ?? null;
  const quickPresentation = workspaceSnap?.data.quickPresentation ?? false;
  const { current: presentedEntry } = useVersePresentation();

  // Preview: versículo selecionado carregado via cache LRU.
  const [preview, setPreview] = useState<OperatorVerseDTO | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  useEffect(() => {
    if (!selected) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    void ctx
      .getVerse(selected.bookId, selected.chapter, selected.verse)
      .then((verse) => {
        if (!cancelled) setPreview(verse);
      })
      .catch(() => {
        if (!cancelled) setPreview(null);
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected, ctx]);

  const onPresent = useCallback(() => void PresentVerseCommand(ctx), [ctx]);

  return (
    <div className={cn("flex flex-col gap-3", className)} data-testid="presentation-cards">
      {/* Card 1: Selecionado (preview) */}
      <SelectedCard
        preview={preview}
        loading={previewLoading}
        onPresent={onPresent}
        presenting={presenting}
        canPresent={selected !== null}
        quickPresentation={quickPresentation}
        lastResult={lastPresentResult}
      />

      {/* Card 2: Apresentado (ao vivo) */}
      <PresentedCard entry={presentedEntry} />
    </div>
  );
}

// ============================================================
// SelectedCard — versículo sendo navegado (preview)
// ============================================================

interface SelectedCardProps {
  preview: OperatorVerseDTO | null;
  loading: boolean;
  onPresent: () => void;
  presenting: boolean;
  canPresent: boolean;
  quickPresentation: boolean;
  lastResult: OperatorPresentResultDTO | null;
}

function SelectedCard({
  preview,
  loading,
  onPresent,
  presenting,
  canPresent,
  quickPresentation,
  lastResult,
}: SelectedCardProps) {
  return (
    <div
      className="flex flex-col gap-3 rounded-lg border-2 border-primary/40 bg-surface p-4"
      data-testid="selected-card"
    >
      <div className="flex items-center gap-2">
        <BookOpen className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold text-text">Selecionado</h3>
        <span className="ml-auto text-[10px] text-text-muted uppercase tracking-wide">
          Preview
        </span>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-4 text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span className="text-xs">Carregando versículo...</span>
        </div>
      ) : preview ? (
        <div className="flex flex-col gap-2">
          <span className="text-lg font-bold text-text">{preview.reference}</span>
          <p className="text-sm text-text italic border-l-2 border-primary/30 pl-3 leading-relaxed">
            "{preview.text}"
          </p>
          <span className="text-[10px] text-text-subtle">{preview.version}</span>
        </div>
      ) : (
        <p className="text-xs text-text-muted italic py-4 text-center">
          Nenhum versículo selecionado. Use ◀ ▶ ou os atalhos de teclado.
        </p>
      )}

      {/* Botão Apresentar */}
      <button
        onClick={onPresent}
        disabled={!canPresent || presenting}
        className={cn(
          "flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm font-medium transition-colors min-h-[44px]",
          canPresent && !presenting
            ? "bg-primary text-white hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
            : "bg-surface-hover text-text-muted cursor-not-allowed",
        )}
        data-testid="operator-present-btn"
        aria-label="Apresentar versículo selecionado no Holyrics"
      >
        {presenting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Apresentando...
          </>
        ) : (
          <>
            <Send className="h-4 w-4" />
            Apresentar no Holyrics
            {quickPresentation && (
              <span className="flex items-center gap-1 text-[10px] text-status-warning">
                <Zap className="h-3 w-3" />
                Quick
              </span>
            )}
          </>
        )}
      </button>

      {/* Feedback discreto do último resultado */}
      {lastResult && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-md border px-2.5 py-1.5",
            lastResult.ok
              ? "border-status-success/30 bg-status-success/10"
              : "border-status-error/30 bg-status-error/10",
          )}
          data-testid="operator-last-result"
        >
          {lastResult.ok ? (
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-status-success" />
          ) : (
            <XCircle className="h-3.5 w-3.5 shrink-0 text-status-error" />
          )}
          <span className="text-xs font-medium text-text">
            {lastResult.reference} · {formatLatency(lastResult.latency_ms)}
          </span>
          {!lastResult.ok && (
            <span className="text-[10px] text-text-muted truncate">{lastResult.message}</span>
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
  return (
    <div
      className="flex flex-col gap-2 rounded-lg border-2 border-status-success/40 bg-surface p-4"
      data-testid="presented-card"
    >
      <div className="flex items-center gap-2">
        <CheckCircle2 className="h-4 w-4 text-status-success" />
        <h3 className="text-sm font-semibold text-text">Apresentado</h3>
        {entry && entry.status === "presented" && (
          <span className="ml-auto flex items-center gap-1 text-[10px] text-status-success">
            <Radio className="h-3 w-3 animate-pulse" />
            ao vivo
          </span>
        )}
        {entry && entry.status === "presenting" && (
          <span className="ml-auto flex items-center gap-1 text-[10px] text-status-warning">
            <Loader2 className="h-3 w-3 animate-spin" />
            apresentando
          </span>
        )}
      </div>

      {entry ? (
        <div className="flex flex-col gap-1.5">
          <span className="text-lg font-bold text-text">{entry.reference}</span>
          {entry.verseText && (
            <p className="text-sm text-text italic border-l-2 border-status-success/30 pl-3 leading-relaxed">
              "{entry.verseText}"
            </p>
          )}
          <div className="flex items-center gap-3 text-[10px] text-text-subtle">
            <span>{entry.version}</span>
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
