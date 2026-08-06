/**
 * useCommandPalette (Sprint 26 D12) — lógica da Command Palette.
 *
 * Hook que encapsula toda a lógica da Command Palette Bíblica:
 * - ReferenceResolver (heurística numérica, ambiguidades)
 * - AutoCompleteEngine (autocomplete IDE-style de livros)
 * - SearchHistoryController (histórico terminal-style ↑↓)
 * - Enter inteligente (D7): apresenta direto se alta confiança
 * - Fluxo Zero Mouse (D8): clear + refocus após apresentação
 *
 * O hook é agnóstico à UI. O componente CommandPalette.tsx consome
 * este hook e renderiza o estado.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import { useServices } from "@/hooks";
import {
  buildBookIndex,
  autoCompleteBook,
  resolveReference,
  type BookAliasIndex,
  type AutoCompleteResult,
  type ResolutionResult,
  type ReferenceInterpretation,
} from "@/utils";
import type { OperatorBookDTO } from "@/types";
import {
  SelectByReferenceCommand,
  PresentVerseCommand,
  type WorkspaceContext,
} from "./WorkspaceCommands";
import { SearchHistoryController } from "./SearchHistoryController";

// ============================================================
// Tipos
// ============================================================

export interface CommandPaletteState {
  /** Query atual do input. */
  query: string;
  /** Resultado da resolução (interpretado da query). */
  resolution: ResolutionResult | null;
  /** Sugestão de autocomplete do livro (ou null). */
  autoComplete: AutoCompleteResult | null;
  /** Índice da interpretação selecionada (para medium confidence). */
  selectedInterpretation: number;
  /** True se está validando/apresentando. */
  isBusy: boolean;
  /** Erro da última operação. */
  error: string | null;
  /** True se a última apresentação foi bem-sucedida (para feedback). */
  lastPresentedRef: string | null;
}

export interface UseCommandPaletteResult extends CommandPaletteState {
  /** Atualiza a query (dispara resolução + autocomplete). */
  setQuery: (q: string) => void;
  /** Move seleção para próxima interpretação (↓). */
  selectNextInterpretation: () => void;
  /** Move seleção para interpretação anterior (↑). */
  selectPrevInterpretation: () => void;
  /** Navega histórico anterior (↑ com campo vazio). */
  historyPrevious: () => string | null;
  /** Navega histórico seguinte (↓). */
  historyNext: () => string;
  /** Aceita sugestão de autocomplete (Tab). */
  acceptAutoComplete: () => void;
  /**
   * Confirma: se alta confiança, apresenta direto.
   * Se média confiança, apresenta a interpretação selecionada.
   */
  confirm: () => Promise<ConfirmOutcome>;
  /** Limpa tudo (Esc). */
  clear: () => void;
}

export interface ConfirmOutcome {
  ok: boolean;
  /** Referência apresentada (se ok). */
  reference: string | null;
  /** Razão da falha (se !ok). */
  reason: string | null;
}

// ============================================================
// Hook
// ============================================================

export function useCommandPalette(
  ctx: WorkspaceContext,
  books: OperatorBookDTO[],
): UseCommandPaletteResult {
  const services = useServices();
  const [query, setQueryState] = useState("");
  const [selectedInterpretation, setSelectedInterpretation] = useState(0);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastPresentedRef, setLastPresentedRef] = useState<string | null>(null);

  const index: BookAliasIndex = useMemo(() => buildBookIndex(books), [books]);
  const historyRef = useRef(new SearchHistoryController());

  // Resolução da query (instantânea, sem backend).
  const resolution: ResolutionResult | null = useMemo(() => {
    if (!query.trim()) return null;
    return resolveReference(query, index);
  }, [query, index]);

  // Autocomplete do livro (só quando não há números na query).
  const autoComplete: AutoCompleteResult | null = useMemo(() => {
    const trimmed = query.trim();
    if (!trimmed) return null;
    // Só tenta autocomplete se não há dígitos (ainda digitando o livro).
    if (/\d/.test(trimmed)) return null;
    const result = autoCompleteBook(trimmed, index);
    return result.completion ? result : null;
  }, [query, index]);

  // Resetar seleção quando resolução muda.
  useMemo(() => {
    setSelectedInterpretation(0);
  }, [resolution]);

  const setQuery = useCallback((q: string) => {
    setQueryState(q);
    setError(null);
    historyRef.current.resetCursor();
  }, []);

  const clear = useCallback(() => {
    setQueryState("");
    setSelectedInterpretation(0);
    setError(null);
    historyRef.current.resetCursor();
  }, []);

  const selectNextInterpretation = useCallback(() => {
    if (!resolution || resolution.interpretations.length === 0) return;
    setSelectedInterpretation((prev) =>
      Math.min(prev + 1, resolution.interpretations.length - 1),
    );
  }, [resolution]);

  const selectPrevInterpretation = useCallback(() => {
    setSelectedInterpretation((prev) => Math.max(prev - 1, 0));
  }, []);

  const historyPrevious = useCallback((): string | null => {
    return historyRef.current.previous(query);
  }, [query]);

  const historyNext = useCallback((): string => {
    return historyRef.current.next();
  }, []);

  const acceptAutoComplete = useCallback(() => {
    if (autoComplete?.fullText) {
      setQueryState(autoComplete.fullText + " ");
      setError(null);
    }
  }, [autoComplete]);

  // Enter inteligente (D7).
  const confirm = useCallback(async (): Promise<ConfirmOutcome> => {
    const q = query.trim();
    if (!q) {
      return { ok: false, reference: null, reason: "empty" };
    }
    if (!resolution) {
      return { ok: false, reference: null, reason: "no_resolution" };
    }

    let interp: ReferenceInterpretation | null = null;
    if (resolution.confidence === "high" && resolution.interpretations.length === 1) {
      interp = resolution.interpretations[0];
    } else if (resolution.confidence === "medium" && resolution.interpretations.length > 0) {
      interp = resolution.interpretations[selectedInterpretation] ?? resolution.interpretations[0];
    } else if (resolution.confidence === "low") {
      setError(humanizeError(resolution.error));
      return { ok: false, reference: null, reason: resolution.error };
    }

    if (!interp) {
      return { ok: false, reference: null, reason: "no_interpretation" };
    }

    const ref = interp.ref;
    // Se não há versículo (apenas capítulo), usar versículo 1.
    const verse = ref.verse ?? 1;

    setIsBusy(true);
    setError(null);
    try {
      // Validar com backend (parser oficial).
      const parseQuery = `${ref.bookName} ${ref.chapter}:${verse}`;
      const result = await services.operator.parseReference(parseQuery);
      if (!result.ok) {
        const errMsg = humanizeParseError(result.reason);
        setError(errMsg);
        return { ok: false, reference: null, reason: result.reason };
      }

      // Selecionar + apresentar.
      await SelectByReferenceCommand(ctx, {
        bookId: ref.bookId,
        chapter: ref.chapter,
        verse,
      });
      await PresentVerseCommand(ctx);

      // Registrar no histórico de busca.
      historyRef.current.push(q);

      // Feedback + limpar para próxima referência (D8).
      setLastPresentedRef(ref.reference);
      clear();

      return { ok: true, reference: ref.reference, reason: null };
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      setError(errMsg);
      return { ok: false, reference: null, reason: errMsg };
    } finally {
      setIsBusy(false);
    }
  }, [query, resolution, selectedInterpretation, services, ctx, clear]);

  return {
    query,
    resolution,
    autoComplete,
    selectedInterpretation,
    isBusy,
    error,
    lastPresentedRef,
    setQuery,
    selectNextInterpretation,
    selectPrevInterpretation,
    historyPrevious,
    historyNext,
    acceptAutoComplete,
    confirm,
    clear,
  };
}

// ============================================================
// Helpers
// ============================================================

function humanizeError(reason: string | null): string {
  switch (reason) {
    case "empty":
      return "Digite uma referência (ex.: João 3:16, Rm 8:28).";
    case "book_not_found":
      return "Livro não encontrado. Verifique o nome ou abreviação.";
    case "invalid_number":
      return "Capítulo ou versículo inválido para este livro.";
    default:
      return reason ?? "Referência inválida.";
  }
}

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
