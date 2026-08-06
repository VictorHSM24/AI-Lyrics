/**
 * Parser de referências bíblicas no frontend (Sprint 25).
 *
 * Parser puramente textual (sem LLM) que converte strings como
 * "João 3:16", "Jo 3:16", "Rm 8:28", "Salmo 91" em referências
 * normalizadas {bookId, chapter, verse?}.
 *
 * Usa a lista de livros com aliases de GET /operator/books (que
 * espelha config/books.json do backend). Matching é feito por
 * normalização (lowercase, sem acentos) + busca no índice de aliases.
 *
 * Não valida se o capítulo/versículo existe na Bíblia (essa validação
 * é feita pelo backend no endpoint GET /operator/parse, que confirma
 * se o versículo realmente existe na versão solicitada).
 *
 * Espelha a lógica de busca/bible_reference.py do backend.
 */

import type { OperatorBookDTO } from "@/types";

// ============================================================
// Tipos
// ============================================================

export interface ParsedBibleReference {
  /** ID do livro (1..66). */
  bookId: number;
  /** Nome canônico do livro (ex.: "João"). */
  bookName: string;
  /** Capítulo (sempre presente). */
  chapter: number;
  /** Versículo (opcional, ex.: "João 3" não tem verse). */
  verse: number | null;
  /** Referência formatada (ex.: "João 3:16"). */
  reference: string;
  /** Score de confiança [0..1] (1.0 = match exato, <1 = fuzzy). */
  confidence: number;
}

export interface ParseError {
  /** Query original. */
  query: string;
  /** Razão da falha. */
  reason: "empty" | "no_chapter" | "book_not_found" | "invalid_number";
}

export type ParseResult =
  | { ok: true; ref: ParsedBibleReference }
  | { ok: false; error: ParseError };

// ============================================================
// Normalização (espelha _normalize_text do backend)
// ============================================================

/**
 * Normaliza texto: lowercase, sem diacritics, whitespace colapsado.
 * Ex.: "São João" → "sao joao", "João 3:16" → "joao 3:16".
 */
export function normalizeText(text: string): string {
  if (!text) return "";
  // NFD decomposition + remove combining marks (diacritics).
  const nfkd = text.normalize("NFKD");
  const withoutDiacritics = nfkd.replace(/[\u0300-\u036f]/g, "");
  // Colapsar whitespace múltiplo em espaço único.
  const collapsed = withoutDiacritics.replace(/\s+/g, " ");
  return collapsed.trim().toLowerCase();
}

// ============================================================
// Conversão de numerais romanos (espelha _convert_roman_to_arabic)
// ============================================================

const ROMAN_MAP: Array<[string, string]> = [
  ["i corintios", "1 corintios"],
  ["ii corintios", "2 corintios"],
  ["i samuel", "1 samuel"],
  ["ii samuel", "2 samuel"],
  ["i reis", "1 reis"],
  ["ii reis", "2 reis"],
  ["i cronicas", "1 cronicas"],
  ["ii cronicas", "2 cronicas"],
  ["i tessalonicenses", "1 tessalonicenses"],
  ["ii tessalonicenses", "2 tessalonicenses"],
  ["i timoteo", "1 timoteo"],
  ["ii timoteo", "2 timoteo"],
  ["i pedro", "1 pedro"],
  ["ii pedro", "2 pedro"],
  ["i joao", "1 joao"],
  ["ii joao", "2 joao"],
  ["iii joao", "3 joao"],
  ["i ", "1 "],
  ["ii ", "2 "],
  ["iii ", "3 "],
];

export function convertRomanToArabic(text: string): string {
  for (const [roman, arabic] of ROMAN_MAP) {
    if (text.startsWith(roman)) {
      return arabic + text.slice(roman.length);
    }
  }
  return text;
}

// ============================================================
// Índice de aliases (construído a partir de OperatorBookDTO[])
// ============================================================

export interface BookAliasIndex {
  /** alias normalizada → { bookId, bookName, aliasLength } */
  aliases: Map<string, { bookId: number; bookName: string; aliasLength: number }>;
  /** Lista de livros para fallback fuzzy. */
  books: Array<{ id: number; canonical: string; aliases: string[]; normalizedAliases: string[] }>;
}

/**
 * Constrói índice de aliases a partir da lista de livros.
 * Cada alias é normalizada (lowercase, sem acentos) e mapeada para o livro.
 * Se múltiplos livros compartilham a mesma alias, o de alias mais curta
 * vence (ex.: "jo" → João, não "Jó" que tem alias "jo" mas também "jó").
 */
export function buildBookIndex(books: OperatorBookDTO[]): BookAliasIndex {
  const aliases = new Map<string, { bookId: number; bookName: string; aliasLength: number }>();
  const normalizedBooks: BookAliasIndex["books"] = [];

  for (const book of books) {
    const normAliases: string[] = [];
    // Nome canônico como alias implícita.
    const canonicalNorm = normalizeText(book.canonical);
    if (canonicalNorm) {
      normAliases.push(canonicalNorm);
      const existing = aliases.get(canonicalNorm);
      if (!existing || existing.aliasLength > canonicalNorm.length) {
        aliases.set(canonicalNorm, {
          bookId: book.id,
          bookName: book.canonical,
          aliasLength: canonicalNorm.length,
        });
      }
    }
    // Aliases explícitas.
    for (const alias of book.aliases) {
      const norm = normalizeText(alias);
      if (!norm) continue;
      normAliases.push(norm);
      const existing = aliases.get(norm);
      // Alias mais curta vence (mais específica).
      if (!existing || existing.aliasLength > norm.length) {
        aliases.set(norm, {
          bookId: book.id,
          bookName: book.canonical,
          aliasLength: norm.length,
        });
      }
    }
    normalizedBooks.push({
      id: book.id,
      canonical: book.canonical,
      aliases: book.aliases,
      normalizedAliases: normAliases,
    });
  }

  return { aliases, books: normalizedBooks };
}

// ============================================================
// Regex para extrair capítulo e versículo(s) no final da string
// Espelha _REF_PATTERN do backend.
// ============================================================

const REF_PATTERN = /(\d+)(?::(\d+))?(?:-(\d+))?\s*$/;

// ============================================================
// Parser principal
// ============================================================

/**
 * Faz parse de uma string de referência bíblica.
 *
 * Aceita formatos:
 *   "João 3:16"     → { bookId:43, chapter:3, verse:16 }
 *   "Jo 3:16"       → { bookId:43, chapter:3, verse:16 }
 *   "Jó 19"         → { bookId:18, chapter:19, verse:null }
 *   "Romanos 8"     → { bookId:45, chapter:8, verse:null }
 *   "Rm 8:28"       → { bookId:45, chapter:8, verse:28 }
 *   "Salmo 91"      → { bookId:19, chapter:91, verse:null }
 *   "Sl 91"         → { bookId:19, chapter:91, verse:null }
 *   "1 Coríntios 13 → { bookId:46, chapter:13, verse:null }
 *   "II Reis 2:11"  → { bookId:12, chapter:2, verse:11 }
 *
 * Não lança exceções. Retorna { ok: false, error } se inválido.
 */
export function parseBibleReference(
  query: string,
  index: BookAliasIndex,
): ParseResult {
  if (!query || !query.trim()) {
    return { ok: false, error: { query, reason: "empty" } };
  }

  let normalized = normalizeText(query);
  if (!normalized) {
    return { ok: false, error: { query, reason: "empty" } };
  }

  // Converter numerais romanos no início.
  normalized = convertRomanToArabic(normalized);

  // Encontrar padrão capítulo:versículo no final.
  const match = REF_PATTERN.exec(normalized);
  if (!match) {
    return { ok: false, error: { query, reason: "no_chapter" } };
  }

  const chapterStr = match[1];
  const verseStr = match[2];

  const chapter = parseInt(chapterStr, 10);
  if (chapter <= 0 || isNaN(chapter)) {
    return { ok: false, error: { query, reason: "invalid_number" } };
  }

  let verse: number | null = null;
  if (verseStr) {
    verse = parseInt(verseStr, 10);
    if (verse <= 0 || isNaN(verse)) {
      return { ok: false, error: { query, reason: "invalid_number" } };
    }
  }

  // Extrair nome do livro (tudo antes do capítulo).
  const bookPart = normalized.slice(0, match.index).trim();
  if (!bookPart) {
    return { ok: false, error: { query, reason: "book_not_found" } };
  }

  // Resolver livro pelo índice de aliases.
  const resolved = index.aliases.get(bookPart);
  if (resolved) {
    const reference = formatReference(resolved.bookName, chapter, verse);
    return {
      ok: true,
      ref: {
        bookId: resolved.bookId,
        bookName: resolved.bookName,
        chapter,
        verse,
        reference,
        confidence: 1.0,
      },
    };
  }

  // Fallback fuzzy: buscar alias que contém o bookPart ou vice-versa.
  // Ex.: "joao" sem acento já foi normalizado, mas se o usuário digita
  // "joa" (incompleto), fazemos fuzzy match.
  let bestFuzzy: { bookId: number; bookName: string; score: number } | null = null;
  for (const book of index.books) {
    for (const alias of book.normalizedAliases) {
      // Match se bookPart é prefixo da alias ou alias é prefixo de bookPart.
      if (alias.startsWith(bookPart) || bookPart.startsWith(alias)) {
        const score = Math.min(bookPart.length, alias.length) / Math.max(bookPart.length, alias.length);
        if (!bestFuzzy || score > bestFuzzy.score) {
          bestFuzzy = { bookId: book.id, bookName: book.canonical, score };
        }
      }
    }
  }

  if (bestFuzzy && bestFuzzy.score >= 0.6) {
    const reference = formatReference(bestFuzzy.bookName, chapter, verse);
    return {
      ok: true,
      ref: {
        bookId: bestFuzzy.bookId,
        bookName: bestFuzzy.bookName,
        chapter,
        verse,
        reference,
        confidence: bestFuzzy.score,
      },
    };
  }

  return { ok: false, error: { query, reason: "book_not_found" } };
}

// ============================================================
// Sugestões para autocomplete (QuickSearch)
// ============================================================

export interface SearchSuggestion {
  /** Referência parseada. */
  ref: ParsedBibleReference;
  /** String de sugestão para exibir (ex.: "João 3:16"). */
  display: string;
}

/**
 * Gera sugestões de referências a partir de uma query parcial.
 *
 * Diferente de parseBibleReference (que exige capítulo), esta função
 * sugere mesmo para queries incompletas como "jo", "joão 3", "rm".
 *
 * Estratégia:
 * 1. Se a query parseia completamente, retorna essa referência.
 * 2. Senão, busca livros cujo nome/alias começa com a query
 *    e sugere "Livro 1" (primeiro capítulo).
 * 3. Se a query tem formato "Livro N" (sem versículo), sugere
 *    "Livro N:1" (primeiro versículo).
 */
export function suggestReferences(
  query: string,
  index: BookAliasIndex,
  limit = 8,
): SearchSuggestion[] {
  const q = query.trim();
  if (!q) return [];

  // Tentar parse completo primeiro.
  const parsed = parseBibleReference(q, index);
  if (parsed.ok) {
    return [
      {
        ref: parsed.ref,
        display: parsed.ref.reference,
      },
    ];
  }

  const normalized = convertRomanToArabic(normalizeText(q));
  const suggestions: SearchSuggestion[] = [];
  const seen = new Set<number>();

  // Caso 1: query é apenas nome de livro (ou prefixo), sem capítulo.
  // Sugere "Livro 1" (primeiro capítulo).
  if (!REF_PATTERN.exec(normalized)) {
    for (const book of index.books) {
      if (suggestions.length >= limit) break;
      for (const alias of book.normalizedAliases) {
        if (alias.startsWith(normalized) || normalized.startsWith(alias)) {
          if (!seen.has(book.id)) {
            seen.add(book.id);
            const ref: ParsedBibleReference = {
              bookId: book.id,
              bookName: book.canonical,
              chapter: 1,
              verse: 1,
              reference: formatReference(book.canonical, 1, 1),
              confidence: Math.min(normalized.length, alias.length) / Math.max(normalized.length, alias.length),
            };
            suggestions.push({ ref, display: `${book.canonical} 1:1` });
          }
          break;
        }
      }
    }
  }

  // Caso 2: query tem formato "Livro N" (capítulo sem versículo).
  // Sugere "Livro N:1".
  const chapMatch = /^(\D+)\s+(\d+)\s*$/.exec(normalized);
  if (chapMatch) {
    const bookPart = chapMatch[1].trim();
    const chapter = parseInt(chapMatch[2], 10);
    const resolved = index.aliases.get(bookPart);
    if (resolved && chapter > 0) {
      const ref: ParsedBibleReference = {
        bookId: resolved.bookId,
        bookName: resolved.bookName,
        chapter,
        verse: 1,
        reference: formatReference(resolved.bookName, chapter, 1),
        confidence: 1.0,
      };
      // Verificar se já não está na lista.
      if (!suggestions.some((s) => s.ref.bookId === ref.bookId && s.ref.chapter === ref.chapter)) {
        suggestions.unshift({ ref, display: ref.reference });
      }
    }
  }

  return suggestions.slice(0, limit);
}

// ============================================================
// Helpers
// ============================================================

function formatReference(book: string, chapter: number, verse: number | null): string {
  return verse !== null ? `${book} ${chapter}:${verse}` : `${book} ${chapter}`;
}
