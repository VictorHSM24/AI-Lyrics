/**
 * KeyboardController (Sprint 25 Fase B) — controlador global de teclado.
 *
 * Arquitetura obrigatória:
 *   Keyboard → Command → Workspace → UI
 *
 * O teclado APENAS dispara comandos. Nenhuma lógica de negócio aqui.
 * Os comandos atualizam o Workspace. Os componentes reagem ao Workspace.
 *
 * Atalhos:
 *   ←          → PreviousVerseCommand
 *   →          → NextVerseCommand
 *   ↑          → PreviousChapterCommand
 *   ↓          → NextChapterCommand
 *   Enter      → PresentVerseCommand
 *   Ctrl+Enter → ReplayVerseCommand
 *   Esc        → ClearSelectionCommand
 *   Ctrl+H     → placeholder (abrir histórico — Fase C)
 *   Ctrl+F     → placeholder (focar busca — Fase C)
 *
 * Os atalhos NÃO funcionam quando o foco está em campo de texto
 * (input, textarea, select, contenteditable), para não interferir
 * na digitação. Exceção: Esc sempre funciona (para limpar seleção
 * mesmo com foco em campo).
 *
 * Uso:
 *   function OperatorPage() {
 *     useKeyboardController(ctx);
 *     return <OperatorWorkspace />;
 *   }
 */

import { useEffect } from "react";
import {
  executeCommand,
  type CommandName,
  type WorkspaceContext,
} from "./WorkspaceCommands";

/** Callbacks para atalhos que ainda não têm implementação (Fase C). */
export interface KeyboardControllerCallbacks {
  /** Chamado quando Ctrl+H é pressionado (abrir histórico). Opcional. */
  onToggleHistory?: () => void;
  /** Chamado quando Ctrl+F é pressionado (focar busca). Opcional. */
  onFocusSearch?: () => void;
}

/**
 * Verifica se o foco atual está em um campo de texto editável.
 * Nesses campos, atalhos de navegação não devem funcionar.
 */
function isEditingText(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") {
    return true;
  }
  if (target.isContentEditable) return true;
  return false;
}

export function useKeyboardController(
  ctx: WorkspaceContext,
  callbacks?: KeyboardControllerCallbacks,
): void {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      // Esc sempre funciona (mesmo em campos de texto).
      if (e.key === "Escape") {
        e.preventDefault();
        void executeCommand("clearSelection", ctx);
        return;
      }

      // Ctrl+H e Ctrl+F funcionam mesmo em campos de texto (são atalhos
      // globais do navegador-style). Mas se o callback não estiver
      // definido, ignorar.
      if (e.ctrlKey || e.metaKey) {
        if (e.key === "h" || e.key === "H") {
          if (callbacks?.onToggleHistory) {
            e.preventDefault();
            callbacks.onToggleHistory();
          }
          return;
        }
        if (e.key === "f" || e.key === "F") {
          if (callbacks?.onFocusSearch) {
            e.preventDefault();
            callbacks.onFocusSearch();
          }
          return;
        }
        if (e.key === "Enter") {
          // Ctrl+Enter = reapresentar (funciona em campo de texto? não,
          // porque em textarea Ctrl+Enter pode ser submit de form).
          if (isEditingText(e.target)) return;
          e.preventDefault();
          void executeCommand("replayVerse", ctx);
          return;
        }
        // Outros Ctrl+* não tratados: deixar o navegador lidar.
        return;
      }

      // Atalhos de navegação: não funcionam em campos de texto.
      if (isEditingText(e.target)) return;

      let command: CommandName | null = null;
      switch (e.key) {
        case "ArrowLeft":
          command = "previousVerse";
          break;
        case "ArrowRight":
          command = "nextVerse";
          break;
        case "ArrowUp":
          command = "previousChapter";
          break;
        case "ArrowDown":
          command = "nextChapter";
          break;
        case "Enter":
          command = "presentVerse";
          break;
      }

      if (command) {
        e.preventDefault();
        void executeCommand(command, ctx);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [ctx, callbacks]);
}
