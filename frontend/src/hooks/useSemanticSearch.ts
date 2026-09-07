/**
 * useSemanticSearch (Sprint 28 Fase 9) — Busca semântica de versículos.
 *
 * Hook que encapsula a busca semântica no painel do operador:
 * - Operador digita texto livre (palavras-chave, paráfrases, temas).
 * - BibleRetriever busca no FTS5 em todas as versões locais.
 * - Ollama re-ranqueia os candidatos por relevância semântica.
 * - Resultados mostrados no SemanticSearchPanel.
 *
 * Estado:
 * - query: texto do input.
 * - results: candidatos re-ranqueados.
 * - searching: busca em andamento.
 * - fallback: Ollama indisponível (resultados do FTS5 sem re-ranqueio).
 * - selectedIndex: índice do candidato selecionado (navegação por teclado).
 */

import { useCallback, useRef, useState } from "react";
import { useServices } from "@/contexts/InfraContext";
import type {
  SemanticSearchRequestDTO,
  SemanticSearchResponseDTO,
  SemanticSearchResultDTO,
} from "@/types";

export interface UseSemanticSearchResult {
  /** Texto atual do input. */
  query: string;
  setQuery: (q: string) => void;
  /** Resultados da última busca. */
  results: SemanticSearchResultDTO[];
  /** True se uma busca está em andamento. */
  searching: boolean;
  /** True se o Ollama não foi usado (fallback para FTS5 puro). */
  fallback: boolean;
  /** Mensagem de erro (null se OK). */
  error: string | null;
  /** Latência da última busca em ms. */
  latencyMs: number;
  /** Índice do candidato selecionado (para navegação por teclado). */
  selectedIndex: number;
  setSelectedIndex: (i: number) => void;
  /** Seleciona próximo candidato (wrap-around). */
  selectNext: () => void;
  /** Seleciona candidato anterior (wrap-around). */
  selectPrev: () => void;
  /** Candidato atualmente selecionado (null se nenhum). */
  selectedResult: SemanticSearchResultDTO | null;
  /** Query que produziu os resultados atuais ("" se nenhuma busca). */
  lastSearchedQuery: string;
  /** True se a query atual difere da última buscada (resultados stale). */
  queryChanged: boolean;
  /** Se o re-ranqueamento Ollama está ativado pelo operador. */
  useOllama: boolean;
  /** Liga/desliga o re-ranqueamento Ollama. */
  setUseOllama: (v: boolean) => void;
  /** Executa a busca com a query atual. */
  search: (topK?: number) => Promise<void>;
  /** Limpa resultados e input. */
  clear: () => void;
}

export function useSemanticSearch(): UseSemanticSearchResult {
  const services = useServices();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SemanticSearchResultDTO[]>([]);
  const [searching, setSearching] = useState(false);
  const [fallback, setFallback] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [latencyMs, setLatencyMs] = useState(0);
  const [selectedIndex, setSelectedIndex] = useState(0);
  /** Query que produziu os resultados atuais ("" se nenhuma busca fez). */
  const [lastSearchedQuery, setLastSearchedQuery] = useState("");
  /** Toggle do operador: se true, usa Ollama para re-ranqueamento (quando disponível). */
  const [useOllama, setUseOllama] = useState(true);

  // Ref para cancelar buscas stale (se o operador digitar rápido).
  const searchSeqRef = useRef(0);

  const search = useCallback(async (topK: number = 20) => {
    const q = query.trim();
    if (!q) {
      setResults([]);
      setFallback(false);
      setError(null);
      return;
    }

    const seq = ++searchSeqRef.current;
    setSearching(true);
    setError(null);

    try {
      const req: SemanticSearchRequestDTO = {
        query: q,
        top_k: topK,
        use_ollama: useOllama,
      };
      const res: SemanticSearchResponseDTO = await services.operator.semanticSearch(req, {
        timeoutMs: useOllama ? 90_000 : 15_000,
      });

      // Ignorar resposta stale (busca mais recente já chegou).
      if (seq !== searchSeqRef.current) return;

      if (!res.ok) {
        setResults([]);
        setFallback(false);
        setLastSearchedQuery("");
        setError("Busca não retornou resultados.");
        return;
      }

      setResults(res.results);
      setFallback(res.fallback);
      setLatencyMs(res.latency_ms);
      setSelectedIndex(0);
      setLastSearchedQuery(q);
    } catch (e) {
      if (seq !== searchSeqRef.current) return;
      const msg = e instanceof Error ? e.message : String(e);
      setError(`Erro na busca semântica: ${msg}`);
      setResults([]);
      setFallback(false);
      setLastSearchedQuery("");
    } finally {
      if (seq === searchSeqRef.current) {
        setSearching(false);
      }
    }
  }, [query, services.operator, useOllama]);

  const clear = useCallback(() => {
    ++searchSeqRef.current;
    setQuery("");
    setResults([]);
    setSearching(false);
    setFallback(false);
    setError(null);
    setLatencyMs(0);
    setSelectedIndex(0);
    setLastSearchedQuery("");
  }, []);

  const selectNext = useCallback(() => {
    setSelectedIndex((prev) => {
      if (results.length === 0) return 0;
      return (prev + 1) % results.length;
    });
  }, [results.length]);

  const selectPrev = useCallback(() => {
    setSelectedIndex((prev) => {
      if (results.length === 0) return 0;
      return (prev - 1 + results.length) % results.length;
    });
  }, [results.length]);

  const selectedResult = results.length > 0 ? results[selectedIndex] ?? null : null;
  const queryChanged = query.trim() !== lastSearchedQuery && query.trim().length > 0;

  return {
    query,
    setQuery,
    results,
    searching,
    fallback,
    error,
    latencyMs,
    selectedIndex,
    setSelectedIndex,
    selectNext,
    selectPrev,
    selectedResult,
    lastSearchedQuery,
    queryChanged,
    useOllama,
    setUseOllama,
    search,
    clear,
  };
}
