/**
 * SuggestionList (Sprint 25 Fase C) — lista visual de sugestões.
 *
 * Renderiza as sugestões do SearchController com:
 * - Destaque visual (book em negrito, chapter/verse em cor primária)
 * - Navegação por teclado (↑ ↓) via selectedIndex
 * - Click para selecionar
 * - Duplo click para selecionar e apresentar
 * - Acessibilidade: aria-activedescendant, role=listbox
 */

import { Search, Loader2 } from "lucide-react";
import { cn } from "@/utils";
import type { SearchSuggestion } from "@/utils";

interface SuggestionListProps {
  suggestions: SearchSuggestion[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  onConfirm: (index: number) => void;
  isValidating: boolean;
  className?: string;
}

export function SuggestionList({
  suggestions,
  selectedIndex,
  onSelect,
  onConfirm,
  isValidating,
  className,
}: SuggestionListProps) {
  if (suggestions.length === 0 && !isValidating) return null;

  return (
    <div
      className={cn(
        "absolute top-full left-0 right-0 z-50 mt-1 rounded-md border border-border bg-surface shadow-lg max-h-72 overflow-y-auto",
        className,
      )}
      role="listbox"
      aria-label="Sugestões de referências bíblicas"
      data-testid="suggestion-list"
    >
      {isValidating && (
        <div className="flex items-center gap-2 px-3 py-2 text-xs text-text-muted">
          <Loader2 className="h-3 w-3 animate-spin" />
          Validando com backend...
        </div>
      )}
      {suggestions.map((suggestion, index) => {
        const isActive = index === selectedIndex;
        return (
          <SuggestionRow
            key={`${suggestion.ref.bookId}-${suggestion.ref.chapter}-${suggestion.ref.verse ?? "null"}-${index}`}
            suggestion={suggestion}
            isActive={isActive}
            index={index}
            onSelect={onSelect}
            onConfirm={onConfirm}
          />
        );
      })}
    </div>
  );
}

// ============================================================
// SuggestionRow — linha individual
// ============================================================

interface SuggestionRowProps {
  suggestion: SearchSuggestion;
  isActive: boolean;
  index: number;
  onSelect: (index: number) => void;
  onConfirm: (index: number) => void;
}

function SuggestionRow({
  suggestion,
  isActive,
  index,
  onSelect,
  onConfirm,
}: SuggestionRowProps) {
  // Destacar partes: book (negrito), chapter:verse (cor primária).
  const parts = splitDisplayParts(suggestion.display);

  return (
    <div
      role="option"
      aria-selected={isActive}
      id={`suggestion-${index}`}
      className={cn(
        "flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors min-h-[40px]",
        isActive
          ? "bg-primary/10 text-text"
          : "text-text hover:bg-surface-hover",
      )}
      onClick={() => onSelect(index)}
      onDoubleClick={() => onConfirm(index)}
      data-testid={`suggestion-row-${index}`}
    >
      <Search className="h-3 w-3 shrink-0 text-text-muted" />
      <span className="text-sm flex-1">
        <span className="font-semibold">{parts.book}</span>
        {parts.chapter && (
          <>
            {" "}
            <span className="text-primary font-medium">{parts.chapter}</span>
            {parts.verse && (
              <>
                <span className="text-primary">:</span>
                <span className="text-primary font-medium">{parts.verse}</span>
              </>
            )}
          </>
        )}
      </span>
      {suggestion.ref.confidence < 1.0 && (
        <span className="text-[10px] text-text-subtle" title="Match aproximado">
          ~
        </span>
      )}
    </div>
  );
}

/**
 * Divide o display em (book, chapter, verse) para destaque visual.
 * Ex.: "João 3:16" → { book: "João", chapter: "3", verse: "16" }
 * Ex.: "João 3" → { book: "João", chapter: "3", verse: "" }
 */
function splitDisplayParts(display: string): { book: string; chapter: string; verse: string } {
  const match = /^(.*?)\s+(\d+)(?::(\d+))?\s*$/.exec(display);
  if (match) {
    return { book: match[1], chapter: match[2], verse: match[3] ?? "" };
  }
  return { book: display, chapter: "", verse: "" };
}
