/**
 * OperatorWorkspace (Sprint 25 Fase C) — orquestra todos os componentes.
 *
 * Arquitetura:
 *   Keyboard → Command → Workspace → UI
 *
 * Layout:
 *   ┌─────────────────────────────────────────────────┐
 *   │ QuickSearch (sempre disponível, Ctrl+F foca)     │
 *   ├──────────────────────┬──────────────────────────┤
 *   │ Coluna esquerda:      │ Coluna direita:           │
 *   │  QuickNavigator       │  PresentationCards        │
 *   │  QuickPresentation    │   (Selecionado +          │
 *   │  FavoritesPanel       │    Apresentado)           │
 *   │  MostUsedPanel        │  HistoryPanel             │
 *   └──────────────────────┴──────────────────────────┘
 *
 * Integração C5:
 * - Ctrl+F foca QuickSearch (via ref handle)
 * - Ctrl+H foca filtro do HistoryPanel (via ref handle)
 * - Todos os painéis disparam comandos da Fase B
 * - Sincronização automática via useAutoSyncSelected
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useOperator, useStores, useWorkspaceSnapshot } from "@/hooks";
import { cn } from "@/utils";
import { QuickNavigator } from "./QuickNavigator";
import { PresentationCards } from "./PresentationCards";
import { HistoryPanel } from "./HistoryPanel";
import { FavoritesPanel } from "./FavoritesPanel";
import { MostUsedPanel } from "./MostUsedPanel";
import { CommandPalette, type CommandPaletteHandle } from "./CommandPalette";
import { useWorkspaceContext } from "./useWorkspaceContext";
import { useAutoSyncSelected } from "./useAutoSyncSelected";
import { useKeyboardController } from "./KeyboardController";
import type { OperatorPresentResultDTO } from "@/types";

interface OperatorWorkspaceProps {
  className?: string;
}

export function OperatorWorkspace({ className }: OperatorWorkspaceProps) {
  const ctx = useWorkspaceContext();
  const op = useOperator();
  const workspaceStore = useStores().workspace;
  const workspaceSnap = useWorkspaceSnapshot();

  // Ativar sincronização automática (selected = presented após apresentação).
  useAutoSyncSelected();

  // Refs para callbacks do KeyboardController.
  const commandPaletteRef = useRef<CommandPaletteHandle>(null);
  const historyFilterRef = useRef<HTMLDivElement>(null);

  // Ativar controlador de teclado com callbacks reais (C5).
  useKeyboardController(ctx, {
    onFocusSearch: () => {
      // Sprint 26: CommandPalette substitui QuickSearch.
      commandPaletteRef.current?.focus();
    },
    onToggleHistory: () => {
      // Focar o filtro do histórico (scrollIntoView + focus no input).
      const input = historyFilterRef.current?.querySelector("input");
      if (input) {
        (input as HTMLInputElement).focus();
        historyFilterRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    },
  });

  // Carregar books na montagem (necessário para QuickSearch e navegação).
  useEffect(() => {
    if (op.books.length === 0) {
      void op.loadBooks();
    }
  }, [op]);

  // Track do último resultado de apresentação para feedback discreto.
  const [lastPresentResult, setLastPresentResult] = useState<OperatorPresentResultDTO | null>(op.lastPresentResult);
  useEffect(() => {
    setLastPresentResult(op.lastPresentResult);
  }, [op.lastPresentResult]);

  const quickPresentation = workspaceSnap?.data.quickPresentation ?? false;
  const setQuickPresentation = useCallback(
    (value: boolean) => workspaceStore.setQuickPresentation(value),
    [workspaceStore],
  );

  return (
    <div
      className={cn("flex flex-col gap-4", className)}
      data-testid="operator-workspace"
    >
      {/* Erro global */}
      {op.error && (
        <div
          className="flex items-start gap-2 rounded-md border border-status-error/30 bg-status-error/10 px-3 py-2"
          data-testid="operator-error"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-status-error mt-0.5" />
          <p className="text-xs text-status-error">{op.error}</p>
        </div>
      )}

      {/* Linha 1: CommandPalette (Sprint 26, substitui QuickSearch) */}
      <CommandPalette ref={commandPaletteRef} ctx={ctx} />

      {/* Grid: navegação + cards + painéis */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Coluna esquerda: QuickNavigator + toggle + favoritos + mais usados */}
        <div className="flex flex-col gap-4">
          <QuickNavigator ctx={ctx} />
          <QuickPresentationToggle
            value={quickPresentation}
            onChange={setQuickPresentation}
          />
          <FavoritesPanel ctx={ctx} />
          <MostUsedPanel ctx={ctx} />
        </div>

        {/* Coluna direita: cards + histórico */}
        <div className="flex flex-col gap-4">
          <PresentationCards
            ctx={ctx}
            lastPresentResult={lastPresentResult}
            presenting={op.presenting}
          />
          <div ref={historyFilterRef}>
            <HistoryPanel ctx={ctx} />
          </div>
        </div>
      </div>

      {/* Dica de atalhos (discreto, pode ser removido depois) */}
      <div className="text-[10px] text-text-subtle text-center pt-2 border-t border-border-subtle">
        Atalhos: Ctrl+F buscar · Enter apresenta direto · ↑↓ navega interpretações/histórico · Tab aceita autocomplete · Esc limpa · Ctrl+H histórico
      </div>
    </div>
  );
}

// Import inline para evitar arquivo separado para um ícone.
import { AlertCircle } from "lucide-react";
import { QuickPresentationToggle } from "./QuickPresentationToggle";
