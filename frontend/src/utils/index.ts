/**
 * Utilitários gerais do frontend.
 */

/**
 * Formata timestamp (segundos desde epoch) para string legível.
 */
export function formatTimestamp(ts: number): string {
  if (ts <= 0) return "—";
  return new Date(ts * 1000).toLocaleString("pt-BR");
}

/**
 * Formata duração em segundos para string legível.
 */
export function formatDuration(seconds: number): string {
  if (seconds <= 0) return "0s";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const parts: string[] = [];
  if (h > 0) parts.push(`${h}h`);
  if (m > 0) parts.push(`${m}m`);
  if (s > 0 || parts.length === 0) parts.push(`${s}s`);
  return parts.join(" ");
}

/**
 * Formata número com separadores de milhar.
 */
export function formatNumber(n: number): string {
  return n.toLocaleString("pt-BR");
}

/**
 * Formata percentual (0.0–1.0) como string.
 */
export function formatPercent(value: number, decimals = 1): string {
  if (value <= 0) return "0%";
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * Formata latência em ms.
 */
export function formatLatency(ms: number): string {
  if (ms <= 0) return "—";
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

/**
 * Trunca string com reticências.
 */
export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 1) + "…";
}

/**
 * Gera ID único para uso em DOM (para aria, etc.).
 */
let _idCounter = 0;
export function generateId(prefix = "id"): string {
  _idCounter += 1;
  return `${prefix}-${_idCounter}`;
}

/**
 * Classes condicionais (cn utility).
 */
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

// ============================================================
// Dev Log — telemetria de desenvolvimento.
// ============================================================

export { devLog, type DevLog } from "./dev-log";

// ============================================================
// Sprint 25 — LruCache para navegação bíblica do OperatorPanel.
// ============================================================

export { LruCache, cacheKey, type LruCacheEntry } from "./lruCache";

// ============================================================
// Sprint 25 — Parser de referências bíblicas (sem LLM).
// ============================================================

export {
  normalizeText,
  buildBookIndex,
  parseBibleReference,
  suggestReferences,
  type ParsedBibleReference,
  type ParseError,
  type ParseResult,
  type SearchSuggestion,
  type BookAliasIndex,
} from "./parseBibleReference";

// ============================================================
// Sprint 26 — Estrutura estática da Bíblia (max chapters/verses).
// ============================================================

export {
  BOOK_MAX_CHAPTERS,
  getMaxChapters,
  getMaxVerseHeuristic,
} from "./bibleStructure";

// ============================================================
// Sprint 26 — ReferenceResolver (heurística numérica, ambiguidades).
// ============================================================

export {
  resolveReference,
  type ConfidenceLevel,
  type ReferenceInterpretation,
  type ResolutionResult,
} from "./referenceResolver";

// ============================================================
// Sprint 26 — AutoCompleteEngine (autocomplete IDE-style de livros).
// ============================================================

export {
  autoCompleteBook,
  type AutoCompleteResult,
} from "./autoCompleteEngine";

// ============================================================
// Version name formatting
// ============================================================

/**
 * Formata chave de versão bíblica para exibição curta.
 * "pt_acf" → "ACF", "pt_ra" → "ARA", "en_kjv" → "KJV"
 */
export function formatVersionKey(key: string): string {
  // Remove prefixo de idioma (pt_, en_, es_, uk_)
  const short = key.replace(/^[a-z]{2,3}_/i, "");
  return short.toUpperCase();
}

/**
 * Retorna o título completo da versão a partir da chave.
 * "pt_acf" → "Almeida Corrigida Fiel"
 */
export function versionTitle(key: string): string {
  const map: Record<string, string> = {
    pt_acf: "Almeida Corrigida Fiel",
    pt_ra: "Almeida Revista e Atualizada",
    pt_arc: "Almeida Revista e Corrigida",
    pt_a21: "Almeida Século 21",
    pt_bkj1611: "BKJ Bíblia King James Fiel 1611",
    pt_kja: "King James Atualizada",
    pt_naa: "Nova Almeida Atualizada",
    pt_nbv: "Nova Bíblia Viva",
    pt_ntlh: "Nova Tradução na Linguagem de Hoje",
    pt_nvi: "Nova Versão Internacional",
    pt_nvt: "Nova Versão Transformadora",
    en_akjv: "American King James Version",
    en_kjv: "King James Version",
    en_niv: "New International Version",
    es_lbla: "La Biblia de las Américas",
    es_nbla: "Nueva Biblia de las Américas",
    es_ntv: "Nueva Traducción Viviente",
    es_nvi: "Nueva Versión Internacional",
    es_rv: "Reina Valera 1909",
    uk_ukr1996: "Ukranian Bible, BJU 1996",
  };
  return map[key] ?? key;
}
