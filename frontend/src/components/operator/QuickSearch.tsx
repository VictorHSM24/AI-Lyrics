/**
 * QuickSearch (Sprint 25 Fase C) — campo permanente de busca.
 *
 * Características:
 * - Sempre disponível no modo Operador
 * - Autocomplete instantâneo (parser frontend, 0ms backend)
 * - Enter valida com backend e dispara SelectByReferenceCommand
 * - ↑ ↓ navega sugestões, Enter confirma, Esc limpa
 * - Destaque visual: book em negrito, chapter:verse em cor primária
 * - Reusa SearchController (lógica) + SuggestionList (visual)
 *
 * Integração com Workspace:
 * - confirmSelection dispara SelectByReferenceCommand (Fase B)
 * - O Workspace reage automaticamente (QuickNavigator, PreviewCard)
 *
 * Acessibilidade:
 * - role=combobox, aria-expanded, aria-activedescendant
 * - Foco visível, navegação completa por teclado
 */

import { Search, X, Loader2 } from "lucide-react";
import { forwardRef, useCallback, useImperativeHandle, useRef } from "react";
import { useOperatorNavigation } from "@/hooks";
import { cn } from "@/utils";
import { useSearchController } from "./SearchController";
import { SuggestionList } from "./SuggestionList";
import type { WorkspaceContext } from "./WorkspaceCommands";

interface QuickSearchProps {
  ctx: WorkspaceContext;
  className?: string;
}

/**
 * Ref handle para permitir focar o campo externamente (Ctrl+F).
 */
export interface QuickSearchHandle {
  focus: () => void;
  clear: () => void;
}

export const QuickSearch = forwardRef<QuickSearchHandle, QuickSearchProps>(
  function QuickSearch({ ctx, className }, ref) {
    const nav = useOperatorNavigation();
    const search = useSearchController(ctx, nav.books);
    const inputRef = useRef<HTMLInputElement>(null);

    // Expor focus/clear via ref (para Ctrl+F do KeyboardController).
    useImperativeHandle(ref, () => ({
      focus: () => {
        inputRef.current?.focus();
        inputRef.current?.select();
      },
      clear: () => {
        search.clear();
        inputRef.current?.blur();
      },
    }));

    const onKeyDown = useCallback(
      (e: React.KeyboardEvent<HTMLInputElement>) => {
        switch (e.key) {
          case "ArrowDown":
            e.preventDefault();
            search.selectNext();
            break;
          case "ArrowUp":
            e.preventDefault();
            search.selectPrev();
            break;
          case "Enter":
            e.preventDefault();
            void search.confirmSelection();
            break;
          case "Escape":
            e.preventDefault();
            search.clear();
            inputRef.current?.blur();
            break;
        }
      },
      [search],
    );

    const onSelectSuggestion = useCallback(
      (index: number) => {
        // Click: apenas seleciona visualmente (não confirma).
        // O operador pode revisar e pressionar Enter.
        search.setQuery(search.suggestions[index]?.display ?? search.query);
      },
      [search],
    );

    const onConfirmSuggestion = useCallback(
      (index: number) => {
        // Duplo click: confirma imediatamente.
        const suggestion = search.suggestions[index];
        if (suggestion) {
          search.setQuery(suggestion.display);
          void search.confirmSelection();
        }
      },
      [search],
    );

    const hasQuery = search.query.trim().length > 0;
    const showSuggestions = hasQuery && search.suggestions.length > 0;

    return (
      <div className={cn("relative", className)} data-testid="quick-search">
        <div
          className={cn(
            "flex items-center gap-2 rounded-lg border bg-surface px-3 py-2.5 transition-colors min-h-[44px]",
            search.isValidating
              ? "border-primary/50"
              : "border-border focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20",
          )}
        >
          {search.isValidating ? (
            <Loader2 className="h-4 w-4 text-primary animate-spin shrink-0" />
          ) : (
            <Search className="h-4 w-4 text-text-muted shrink-0" />
          )}
          <input
            ref={inputRef}
            type="text"
            value={search.query}
            onChange={(e) => search.setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Buscar referência... (ex.: João 3:16, Rm 8:28)"
            className="flex-1 bg-transparent text-sm text-text placeholder:text-text-muted outline-none"
            role="combobox"
            aria-expanded={showSuggestions}
            aria-autocomplete="list"
            aria-controls="suggestion-list"
            aria-activedescendant={
              search.selectedIndex >= 0 ? `suggestion-${search.selectedIndex}` : undefined
            }
            aria-label="Buscar referência bíblica"
            data-testid="quick-search-input"
            spellCheck={false}
            autoComplete="off"
          />
          {hasQuery && (
            <button
              onClick={() => search.clear()}
              className="text-text-muted hover:text-text transition-colors p-1 rounded"
              aria-label="Limpar busca"
              data-testid="quick-search-clear"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Destaque visual das partes (abaixo do input, discreto) */}
        {hasQuery && search.highlightedParts.book && (
          <div className="mt-1 px-3 text-[10px] text-text-subtle flex items-center gap-1.5">
            <span className="font-semibold text-text-muted">
              {search.highlightedParts.book}
            </span>
            {search.highlightedParts.chapter && (
              <>
                <span>·</span>
                <span className="text-primary">{search.highlightedParts.chapter}</span>
                {search.highlightedParts.verse && (
                  <>
                    <span className="text-primary">:</span>
                    <span className="text-primary">{search.highlightedParts.verse}</span>
                  </>
                )}
              </>
            )}
          </div>
        )}

        {/* Erro de validação */}
        {search.validationError && (
          <div
            className="mt-1 px-3 py-1.5 text-xs text-status-error bg-status-error/10 rounded-md border border-status-error/30"
            data-testid="quick-search-error"
          >
            {search.validationError}
          </div>
        )}

        {/* Lista de sugestões */}
        {showSuggestions && (
          <SuggestionList
            suggestions={search.suggestions}
            selectedIndex={search.selectedIndex}
            onSelect={onSelectSuggestion}
            onConfirm={onConfirmSuggestion}
            isValidating={search.isValidating}
          />
        )}
      </div>
    );
  },
);
