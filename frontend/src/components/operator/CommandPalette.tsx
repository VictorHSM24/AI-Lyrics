/**
 * CommandPalette (Sprint 26 D1) — Command Palette Bíblica Zero Mouse.
 *
 * Transforma a QuickSearch em uma Command Palette especializada em
 * referências bíblicas. Todo o fluxo é projetado para uso exclusivo
 * pelo teclado.
 *
 * Fluxo ideal:
 *   Ctrl+F → "rm 828" → Enter → Holyrics apresenta → campo limpa →
 *   foco volta automaticamente → pronto para próxima.
 *
 * Features:
 * - D2: Reconhecimento de abreviações (rm, rom, roma, roman, romanos)
 * - D3: Autocomplete IDE-style do livro (Tab para aceitar)
 * - D4: Sintaxe flexível (8:28, 8 28, 828)
 * - D5: Resolução inteligente de números compactos
 * - D6: Algoritmo de confiança (high/medium/low)
 * - D7: Enter inteligente (apresenta direto se alta confiança)
 * - D8: Fluxo Zero Mouse (clear + refocus após apresentação)
 * - D9: Histórico terminal-style (↑↓ com campo vazio)
 * - D10: Navegação totalmente por teclado
 * - D11: Feedback visual discreto (preview + indicador de ambiguidade)
 */

import { Search, X, Loader2, CornerDownLeft, ChevronUp, ChevronDown } from "lucide-react";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useRef,
  useEffect,
} from "react";
import { useOperatorNavigation } from "@/hooks";
import { cn } from "@/utils";
import { useCommandPalette } from "./useCommandPalette";
import type { WorkspaceContext } from "./WorkspaceCommands";

// ============================================================
// Tipos
// ============================================================

interface CommandPaletteProps {
  ctx: WorkspaceContext;
  className?: string;
}

export interface CommandPaletteHandle {
  focus: () => void;
  clear: () => void;
}

// ============================================================
// Componente
// ============================================================

export const CommandPalette = forwardRef<CommandPaletteHandle, CommandPaletteProps>(
  function CommandPalette({ ctx, className }, ref) {
    const nav = useOperatorNavigation();
    const palette = useCommandPalette(ctx, nav.books);
    const inputRef = useRef<HTMLInputElement>(null);

    // Expor focus/clear via ref (para Ctrl+F do KeyboardController).
    useImperativeHandle(ref, () => ({
      focus: () => {
        inputRef.current?.focus();
        inputRef.current?.select();
      },
      clear: () => {
        palette.clear();
        inputRef.current?.blur();
      },
    }));

    // Auto-refocus após apresentação bem-sucedida (D8).
    useEffect(() => {
      if (palette.lastPresentedRef) {
        inputRef.current?.focus();
      }
    }, [palette.lastPresentedRef]);

    const onKeyDown = useCallback(
      (e: React.KeyboardEvent<HTMLInputElement>) => {
        // Tab: aceitar autocomplete (D3).
        if (e.key === "Tab" && palette.autoComplete) {
          e.preventDefault();
          palette.acceptAutoComplete();
          return;
        }

        switch (e.key) {
          case "ArrowDown":
            e.preventDefault();
            // Se há múltiplas interpretações, navega entre elas.
            if (palette.resolution?.confidence === "medium") {
              palette.selectNextInterpretation();
            } else if (!palette.query.trim()) {
              // Campo vazio: navega histórico (próxima, mais recente → não faz sentido ↓).
              // ↓ no histórico vai para o presente (vazio).
              const histNext = palette.historyNext();
              palette.setQuery(histNext);
            }
            break;
          case "ArrowUp":
            e.preventDefault();
            if (palette.resolution?.confidence === "medium") {
              palette.selectPrevInterpretation();
            } else {
              // Navega histórico anterior (mais antiga).
              const histPrev = palette.historyPrevious();
              if (histPrev) palette.setQuery(histPrev);
            }
            break;
          case "Enter":
            e.preventDefault();
            void palette.confirm();
            break;
          case "Escape":
            e.preventDefault();
            palette.clear();
            inputRef.current?.blur();
            break;
        }
      },
      [palette],
    );

    const hasQuery = palette.query.trim().length > 0;
    const resolution = palette.resolution;
    const isMedium = resolution?.confidence === "medium";
    const isHigh = resolution?.confidence === "high";
    const isLow = resolution?.confidence === "low";

    // Preview discreto da interpretação principal (D11).
    const previewText = resolution?.interpretations[0]?.display ?? null;
    const ambiguityCount = resolution?.interpretations.length ?? 0;

    return (
      <div className={cn("relative", className)} data-testid="command-palette">
        {/* Input principal */}
        <div
          className={cn(
            "flex items-center gap-2 rounded-lg border bg-surface px-3 py-2.5 transition-colors min-h-[44px]",
            palette.isBusy
              ? "border-primary/50"
              : isLow
                ? "border-status-error/40"
                : isMedium
                  ? "border-warning/40"
                  : "border-border focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20",
          )}
        >
          {palette.isBusy ? (
            <Loader2 className="h-4 w-4 text-primary animate-spin shrink-0" />
          ) : (
            <Search className="h-4 w-4 text-text-muted shrink-0" />
          )}
          <div className="flex-1 relative">
            <input
              ref={inputRef}
              type="text"
              value={palette.query}
              onChange={(e) => palette.setQuery(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Buscar referência... (ex.: Rm 8:28, João 316, Lucas 248)"
              className="w-full bg-transparent text-sm text-text placeholder:text-text-muted outline-none"
              role="combobox"
              aria-expanded={isMedium}
              aria-autocomplete="list"
              aria-label="Command Palette bíblica"
              data-testid="command-palette-input"
              spellCheck={false}
              autoComplete="off"
            />
            {/* Ghost text de autocomplete (D3) */}
            {palette.autoComplete?.completion && (
              <span
                className="absolute left-0 top-0 text-sm text-text-subtle pointer-events-none select-none"
                aria-hidden="true"
                data-testid="autocomplete-ghost"
              >
                <span className="opacity-0">{palette.query}</span>
                <span className="opacity-60">{palette.autoComplete.completion}</span>
              </span>
            )}
          </div>
          {/* Indicador de autocomplete (Tab) */}
          {palette.autoComplete?.completion && (
            <div className="flex items-center gap-1 text-[10px] text-text-subtle shrink-0">
              <kbd className="px-1 py-0.5 rounded border border-border bg-surface-hover">Tab</kbd>
            </div>
          )}
          {hasQuery && (
            <button
              onClick={() => palette.clear()}
              className="text-text-muted hover:text-text transition-colors p-1 rounded shrink-0"
              aria-label="Limpar"
              data-testid="command-palette-clear"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Preview discreto (D11) */}
        {hasQuery && previewText && (
          <div className="mt-1 px-3 flex items-center gap-2 text-[11px] min-h-[16px]">
            {isHigh && (
              <span className="text-text-muted flex items-center gap-1.5">
                <CornerDownLeft className="h-3 w-3" />
                <span className="text-primary font-medium">{previewText}</span>
              </span>
            )}
            {isMedium && (
              <span className="text-warning flex items-center gap-1.5">
                <ChevronUp className="h-3 w-3" />
                <ChevronDown className="h-3 w-3 -ml-1.5" />
                <span className="font-medium">{ambiguityCount} interpretações</span>
                <span className="text-text-muted">· use ↑↓</span>
              </span>
            )}
            {isLow && (
              <span className="text-status-error">
                {humanizeResolutionError(resolution?.error)}
              </span>
            )}
          </div>
        )}

        {/* Erro de validação (backend) */}
        {palette.error && (
          <div
            className="mt-1 px-3 py-1.5 text-xs text-status-error bg-status-error/10 rounded-md border border-status-error/30"
            data-testid="command-palette-error"
          >
            {palette.error}
          </div>
        )}

        {/* Feedback de apresentação bem-sucedida (discreto, some em 2s) */}
        {palette.lastPresentedRef && (
          <PresentedFeedback reference={palette.lastPresentedRef} />
        )}

        {/* Lista de interpretações (medium confidence) */}
        {isMedium && resolution && resolution.interpretations.length > 1 && (
          <InterpretationList
            interpretations={resolution.interpretations}
            selectedIndex={palette.selectedInterpretation}
            onSelect={(i) => {
              palette.setQuery(resolution.interpretations[i]?.display ?? palette.query);
            }}
            onConfirm={(i) => {
              // Selecionar interpretação e confirmar.
              const interp = resolution.interpretations[i];
              if (interp) {
                palette.setQuery(interp.display);
                void palette.confirm();
              }
            }}
          />
        )}
      </div>
    );
  },
);

// ============================================================
// InterpretationList — lista de interpreções para ambiguidades
// ============================================================

interface InterpretationListProps {
  interpretations: Array<{ ref: { bookId: number; bookName: string; chapter: number; verse: number | null }; display: string }>;
  selectedIndex: number;
  onSelect: (index: number) => void;
  onConfirm: (index: number) => void;
}

function InterpretationList({
  interpretations,
  selectedIndex,
  onSelect,
  onConfirm,
}: InterpretationListProps) {
  return (
    <div
      className="absolute top-full left-0 right-0 z-50 mt-1 rounded-md border border-warning/30 bg-surface shadow-lg max-h-72 overflow-y-auto"
      role="listbox"
      aria-label="Interpretações possíveis"
      data-testid="interpretation-list"
    >
      <div className="px-3 py-1.5 text-[10px] text-text-subtle border-b border-border-subtle bg-surface-hover">
        Múltiplas interpretações · ↑↓ navegar · Enter confirmar
      </div>
      {interpretations.map((interp, index) => {
        const isActive = index === selectedIndex;
        const parts = splitDisplayParts(interp.display);
        return (
          <div
            key={`${interp.ref.bookId}-${interp.ref.chapter}-${interp.ref.verse ?? "null"}-${index}`}
            role="option"
            aria-selected={isActive}
            id={`interpretation-${index}`}
            className={cn(
              "flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors min-h-[40px]",
              isActive
                ? "bg-primary/10 text-text"
                : "text-text hover:bg-surface-hover",
            )}
            onClick={() => onSelect(index)}
            onDoubleClick={() => onConfirm(index)}
            data-testid={`interpretation-row-${index}`}
          >
            <Search className="h-3 w-3 shrink-0 text-text-muted" />
            <span className="text-sm flex-1">
              <span className="font-semibold">{parts.book}</span>
              {" "}
              <span className="text-primary font-medium">{parts.chapter}</span>
              {parts.verse && (
                <>
                  <span className="text-primary">:</span>
                  <span className="text-primary font-medium">{parts.verse}</span>
                </>
              )}
            </span>
            {isActive && (
              <CornerDownLeft className="h-3 w-3 text-text-muted shrink-0" />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ============================================================
// PresentedFeedback — feedback discreto de apresentação
// ============================================================

function PresentedFeedback({ reference }: { reference: string }) {
  return (
    <div
      className="mt-1 px-3 py-1 text-[11px] text-status-success bg-status-success/10 rounded-md border border-status-success/20 flex items-center gap-1.5"
      data-testid="presented-feedback"
    >
      <span className="font-medium">{reference}</span>
      <span className="text-text-muted">apresentado · pronto para a próxima</span>
    </div>
  );
}

// ============================================================
// Helpers
// ============================================================

function splitDisplayParts(display: string): { book: string; chapter: string; verse: string } {
  const match = /^(.*?)\s+(\d+)(?::(\d+))?\s*$/.exec(display);
  if (match) {
    return { book: match[1], chapter: match[2], verse: match[3] ?? "" };
  }
  return { book: display, chapter: "", verse: "" };
}

function humanizeResolutionError(reason: string | null | undefined): string {
  switch (reason) {
    case "empty":
      return "Digite uma referência.";
    case "book_not_found":
      return "Livro não reconhecido.";
    case "invalid_number":
      return "Capítulo/versículo inválido.";
    default:
      return reason ?? "Referência inválida.";
  }
}
