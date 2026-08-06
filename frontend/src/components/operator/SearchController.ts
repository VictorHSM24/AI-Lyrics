/**
 * SearchController (Sprint 25 Fase C) — lógica de busca desacoplada da UI.
 *
 * Princípios:
 * - Parser frontend (Fase A) sugere enquanto digita (0ms backend).
 * - Backend só é consultado no Enter (validação oficial).
 * - Navegação por teclado: ↑ ↓ Enter Esc.
 * - Destaque visual: divide query em (bookPart, chapterPart, versePart).
 *
 * O SearchController é um hook que retorna:
 * - query, setQuery (estado do input)
 * - suggestions (lista de SearchSuggestion do parser)
 * - selectedIndex (índice ativo para navegação por teclado)
 * - selectNext, selectPrev, clearSelection (navegação)
 * - confirmSelection (valida com backend e dispara comando)
 * - highlightedParts (para destaque visual no input)
 *
 * Integração com Workspace:
 * - confirmSelection dispara SelectByReferenceCommand (Fase B)
 * - Opcionalmente pode apresentar automaticamente (configurável)
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useServices } from "@/hooks";
import {
  buildBookIndex,
  parseBibleReference,
  suggestReferences,
  type BookAliasIndex,
  type ParsedBibleReference,
  type SearchSuggestion,
} from "@/utils";
import type { OperatorBookDTO } from "@/types";
import { SelectByReferenceCommand, PresentVerseCommand, type WorkspaceContext } from "./WorkspaceCommands";

// ============================================================
// Tipos
// ============================================================

export interface HighlightedParts {
  /** Parte do livro (ex.: "Romanos"). */
  book: string;
  /** Parte do capítulo (ex.: "8"). */
  chapter: string;
  /** Parte do versículo (ex.: "28"). */
  verse: string;
  /** Resto da query não reconhecido. */
  remainder: string;
}

export interface ConfirmResult {
  ok: boolean;
  ref: ParsedBibleReference | null;
  /** Texto do versículo (se backend confirmou). */
  text: string | null;
  /** Razão da falha (se ok=false). */
  reason: string | null;
}

export interface UseSearchControllerResult {
  /** Query atual do input. */
  query: string;
  /** Atualiza query (dispara sugestões instantâneas). */
  setQuery: (q: string) => void;
  /** Lista de sugestões (instantâneo, do parser frontend). */
  suggestions: SearchSuggestion[];
  /** Índice da sugestão ativa (-1 = nenhuma, 0 = primeira). */
  selectedIndex: number;
  /** Sugestão ativa (ou null). */
  selectedSuggestion: SearchSuggestion | null;
  /** Move seleção para próxima sugestão. */
  selectNext: () => void;
  /** Move seleção para sugestão anterior. */
  selectPrev: () => void;
  /** Limpa query e sugestões. */
  clear: () => void;
  /**
   * Confirma a seleção: valida com backend e dispara
   * SelectByReferenceCommand no Workspace.
   */
  confirmSelection: (opts?: { present?: boolean }) => Promise<ConfirmResult>;
  /** Partes destacadas para renderização visual. */
  highlightedParts: HighlightedParts;
  /** True se está validando com backend. */
  isValidating: boolean;
  /** Erro da última validação. */
  validationError: string | null;
}

// ============================================================
// Hook
// ============================================================

export function useSearchController(
  ctx: WorkspaceContext,
  books: OperatorBookDTO[],
): UseSearchControllerResult {
  const services = useServices();
  const [query, setQueryState] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [isValidating, setIsValidating] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  // Índice de aliases (memoizado, só reconstrói se books mudar).
  const index: BookAliasIndex = useMemo(() => buildBookIndex(books), [books]);

  // Sugestões instantâneas (parser frontend, 0ms backend).
  const suggestions: SearchSuggestion[] = useMemo(() => {
    if (!query.trim()) return [];
    return suggestReferences(query, index, 8);
  }, [query, index]);

  // Resetar selectedIndex quando sugestões mudam.
  useEffect(() => {
    setSelectedIndex(-1);
  }, [suggestions]);

  const selectedSuggestion: SearchSuggestion | null = useMemo(() => {
    if (selectedIndex < 0 || selectedIndex >= suggestions.length) return null;
    return suggestions[selectedIndex] ?? null;
  }, [selectedIndex, suggestions]);

  const setQuery = useCallback((q: string) => {
    setQueryState(q);
    setValidationError(null);
  }, []);

  const selectNext = useCallback(() => {
    setSelectedIndex((prev) => {
      if (suggestions.length === 0) return -1;
      return Math.min(prev + 1, suggestions.length - 1);
    });
  }, [suggestions.length]);

  const selectPrev = useCallback(() => {
    setSelectedIndex((prev) => Math.max(prev - 1, -1));
  }, []);

  const clear = useCallback(() => {
    setQueryState("");
    setSelectedIndex(-1);
    setValidationError(null);
  }, []);

  // Partes destacadas para renderização visual.
  const highlightedParts: HighlightedParts = useMemo(() => {
    return highlightParts(query);
  }, [query]);

  // Confirmar seleção: valida com backend e dispara comando.
  const confirmSelection = useCallback(
    async (opts: { present?: boolean } = {}): Promise<ConfirmResult> => {
      const queryToConfirm = query.trim();
      if (!queryToConfirm) {
        return { ok: false, ref: null, text: null, reason: "empty" };
      }

      // Se há sugestão ativa, usar a referência dela (já parseada).
      // Senão, tentar parsear a query diretamente.
      let refToConfirm: ParsedBibleReference | null = null;
      if (selectedSuggestion) {
        refToConfirm = selectedSuggestion.ref;
      } else {
        const parsed = parseBibleReference(queryToConfirm, index);
        if (parsed.ok) {
          refToConfirm = parsed.ref;
        }
      }

      if (!refToConfirm) {
        return { ok: false, ref: null, text: null, reason: "parse_failed" };
      }

      // Validar com backend (parser oficial).
      setIsValidating(true);
      setValidationError(null);
      try {
        const result = await services.operator.parseReference(
          `${refToConfirm.bookName} ${refToConfirm.chapter}${refToConfirm.verse !== null ? `:${refToConfirm.verse}` : ""}`,
        );
        if (!result.ok) {
          const errMsg = humanizeParseError(result.reason);
          setValidationError(errMsg);
          return { ok: false, ref: refToConfirm, text: null, reason: result.reason };
        }
        // Backend confirmou: disparar SelectByReferenceCommand no Workspace.
        if (refToConfirm.verse !== null) {
          await SelectByReferenceCommand(ctx, {
            bookId: refToConfirm.bookId,
            chapter: refToConfirm.chapter,
            verse: refToConfirm.verse,
          });
        } else if (result.book_id !== null && result.chapter !== null) {
          // Sem versículo: selecionar capítulo, versículo 1 (ou o primeiro
          // versículo que o backend confirmou).
          await SelectByReferenceCommand(ctx, {
            bookId: result.book_id,
            chapter: result.chapter,
            verse: 1,
          });
        }
        // Opcionalmente apresentar (configurável futuramente).
        if (opts.present) {
          await PresentVerseCommand(ctx);
        }
        return { ok: true, ref: refToConfirm, text: result.text, reason: null };
      } catch (e) {
        const errMsg = e instanceof Error ? e.message : String(e);
        setValidationError(errMsg);
        return { ok: false, ref: refToConfirm, text: null, reason: errMsg };
      } finally {
        setIsValidating(false);
      }
    },
    [query, selectedSuggestion, index, services, ctx],
  );

  return {
    query,
    setQuery,
    suggestions,
    selectedIndex,
    selectedSuggestion,
    selectNext,
    selectPrev,
    clear,
    confirmSelection,
    highlightedParts,
    isValidating,
    validationError,
  };
}

// ============================================================
// Helpers
// ============================================================

/**
 * Divide a query em partes (book, chapter, verse) para destaque visual.
 * Ex.: "Romanos 8:28" → { book: "Romanos", chapter: "8", verse: "28" }
 * Ex.: "João 3" → { book: "João", chapter: "3", verse: "" }
 * Ex.: "jo" → { book: "jo", chapter: "", verse: "" }
 */
function highlightParts(query: string): HighlightedParts {
  const trimmed = query.trim();
  if (!trimmed) {
    return { book: "", chapter: "", verse: "", remainder: "" };
  }

  // Regex: livro (não-dígitos) + capítulo (dígitos) + :versículo (dígitos)
  const match = /^(.*?)\s+(\d+)(?::(\d+))?\s*$/.exec(trimmed);
  if (match) {
    return {
      book: match[1],
      chapter: match[2],
      verse: match[3] ?? "",
      remainder: "",
    };
  }

  // Não reconheceu padrão: tudo é "book" (parcial).
  return {
    book: trimmed,
    chapter: "",
    verse: "",
    remainder: "",
  };
}

/**
 * Converte reason técnico do backend em mensagem amigável (pt-BR).
 */
function humanizeParseError(reason: string | null): string {
  switch (reason) {
    case "parse_failed":
      return "Referência não reconhecida. Tente: 'João 3:16', 'Rm 8:28'.";
    case "verse_not_found":
      return "Versículo não encontrado nesta versão.";
    case "chapter_not_found":
      return "Capítulo não encontrado neste livro.";
    case "search_error":
      return "Erro ao buscar versículo. Tente novamente.";
    default:
      return reason ?? "Referência inválida.";
  }
}
