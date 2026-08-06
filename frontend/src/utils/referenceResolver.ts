/**
 * ReferenceResolver (Sprint 26) — resolve queries em interpretações.
 *
 * Diferente do parseBibleReference (que retorna uma única referência),
 * o ReferenceResolver pode retornar MÚLTIPLAS interpretações para
 * entradas ambíguas como "Lucas 248" (2:48 ou 24:8).
 *
 * Níveis de confiança (D6):
 * - high:   exatamente uma interpretação válida → Enter apresenta direto
 * - medium: múltiplas interpretações válidas → mostrar lista, ↑↓ Enter
 * - low:    nenhuma interpretação válida → erro amigável
 *
 * Sintaxe aceita (D4):
 * - "Romanos 8:28"   (tradicional com dois pontos)
 * - "Romanos 8 28"   (sem dois pontos, espaço separa chapter/verse)
 * - "Rm 828"         (compacto, sem separador)
 * - "Romanos 828"    (nome completo compacto)
 * - "Romanos 32"     (compacto, resolve por heurística)
 * - "Romanos 8"      (apenas capítulo, verse=1 default)
 *
 * Algoritmo heurístico (D5):
 * 1. Identifica o livro (prefixo não-numérico).
 * 2. Extrai a sequência numérica restante.
 * 3. Se há separador (':' ou espaço), usa direto.
 * 4. Se é compacto (sem separador), gera todas as splits (c, v)
 *    onde c <= max_chapter e v <= max_verse_heuristic.
 * 5. Filtra splits inválidas e classifica confiança.
 */

import {
  type BookAliasIndex,
  type ParsedBibleReference,
  normalizeText,
  convertRomanToArabic,
} from "./parseBibleReference";
import { getMaxChapters, getMaxVerseHeuristic } from "./bibleStructure";

// ============================================================
// Tipos
// ============================================================

export type ConfidenceLevel = "high" | "medium" | "low";

export interface ReferenceInterpretation {
  /** Referência parseada. */
  ref: ParsedBibleReference;
  /** Display string (ex.: "Romanos 8:28"). */
  display: string;
}

export interface ResolutionResult {
  /** Nível de confiança. */
  confidence: ConfidenceLevel;
  /** Interpretações válidas (1+ se high/medium, 0 se low). */
  interpretations: ReferenceInterpretation[];
  /** Mensagem de erro (se confidence=low). */
  error: string | null;
  /** Query original. */
  query: string;
}

// ============================================================
// Resolver
// ============================================================

/**
 * Resolve uma query em interpretações de referências bíblicas.
 *
 * @param query  Query do operador (ex.: "Rm 828", "Lucas 248").
 * @param index  Índice de aliases de livros.
 * @returns Resultado com nível de confiança e interpretações.
 */
export function resolveReference(
  query: string,
  index: BookAliasIndex,
): ResolutionResult {
  const q = query.trim();
  if (!q) {
    return { confidence: "low", interpretations: [], error: "empty", query };
  }

  const normalized = convertRomanToArabic(normalizeText(q));
  if (!normalized) {
    return { confidence: "low", interpretations: [], error: "empty", query };
  }

  // Extrair parte do livro e parte numérica.
  // O livro pode começar com dígitos (ex.: "1 Reis", "2 Timóteo", "2tm").
  // A parte numérica (chapter:verse) está no final.
  // Tentar padrões do mais específico para o menos específico.
  let bookPart: string | null = null;
  let numericPart: string | null = null;

  // 1. chapter:verse (ex.: "2tm 4:7", "2 reis 2:11")
  let m = /^(.+)\s+(\d+:\d+)\s*$/.exec(normalized);
  if (m) {
    bookPart = m[1].trim();
    numericPart = m[2].trim();
  }

  // 2. chapter verse com espaço (ex.: "Romanos 8 28", "2 reis 2 11")
  if (!bookPart) {
    m = /^(.+)\s+(\d+\s+\d+)\s*$/.exec(normalized);
    if (m) {
      bookPart = m[1].trim();
      numericPart = m[2].trim();
    }
  }

  // 3. Apenas dígitos no final (ex.: "Romanos 8", "Romanos 828", "2 reis 2")
  if (!bookPart) {
    m = /^(.+)\s+(\d+)\s*$/.exec(normalized);
    if (m) {
      bookPart = m[1].trim();
      numericPart = m[2].trim();
    }
  }

  if (!bookPart || !numericPart) {
    return { confidence: "low", interpretations: [], error: "book_not_found", query };
  }

  // Resolver o livro.
  const resolvedBook = resolveBook(bookPart, index);
  if (!resolvedBook) {
    return { confidence: "low", interpretations: [], error: "book_not_found", query };
  }

  const { bookId, bookName } = resolvedBook;
  const maxChapter = getMaxChapters(bookId);
  if (maxChapter === 0) {
    return { confidence: "low", interpretations: [], error: "book_not_found", query };
  }

  // Parsear a parte numérica em (chapter, verse) candidates.
  const candidates = parseNumericPart(numericPart, bookId, maxChapter);

  if (candidates.length === 0) {
    return { confidence: "low", interpretations: [], error: "invalid_number", query };
  }

  // Construir interpretações.
  const interpretations: ReferenceInterpretation[] = candidates.map(({ chapter, verse }) => {
    const reference = verse !== null
      ? `${bookName} ${chapter}:${verse}`
      : `${bookName} ${chapter}`;
    return {
      ref: {
        bookId,
        bookName,
        chapter,
        verse,
        reference,
        confidence: 1.0,
      },
      display: reference,
    };
  });

  // Deduplicar (ex.: "8:28" pode aparecer via split e via separador explícito).
  const unique = deduplicateInterpretations(interpretations);

  if (unique.length === 1) {
    return { confidence: "high", interpretations: unique, error: null, query };
  }

  // Múltiplas interpretações: ordenar por chapter descendente
  // (preferir chapter mais específico como default).
  unique.sort((a, b) => b.ref.chapter - a.ref.chapter);
  return { confidence: "medium", interpretations: unique, error: null, query };
}

// ============================================================
// Helpers — resolução de livro
// ============================================================

function resolveBook(
  bookPart: string,
  index: BookAliasIndex,
): { bookId: number; bookName: string } | null {
  // Match exato no índice de aliases.
  const exact = index.aliases.get(bookPart);
  if (exact) return { bookId: exact.bookId, bookName: exact.bookName };

  // Fuzzy: alias que começa com bookPart ou vice-versa.
  let best: { bookId: number; bookName: string; score: number } | null = null;
  for (const book of index.books) {
    for (const alias of book.normalizedAliases) {
      if (alias.startsWith(bookPart) || bookPart.startsWith(alias)) {
        const score = Math.min(bookPart.length, alias.length) /
          Math.max(bookPart.length, alias.length);
        if (!best || score > best.score) {
          best = { bookId: book.id, bookName: book.canonical, score };
        }
      }
    }
  }

  if (best && best.score >= 0.6) {
    return { bookId: best.bookId, bookName: best.bookName };
  }
  return null;
}

// ============================================================
// Helpers — parse numérico
// ============================================================

interface ChapterVerseCandidate {
  chapter: number;
  verse: number | null;
}

/**
 * Parsea a parte numérica em candidates de (chapter, verse).
 *
 * Aceita:
 * - "8:28"  → [(8, 28)]
 * - "8 28"  → [(8, 28)]
 * - "828"   → [(8, 28), (82, 8)]  (todas as splits válidas)
 * - "8"     → [(8, null)]
 * - "8-10"  → [(8, null)]  (intervalo não suportado ainda, usa chapter)
 */
function parseNumericPart(
  numericPart: string,
  bookId: number,
  maxChapter: number,
): ChapterVerseCandidate[] {
  // Formato "chapter:verse" (com dois pontos).
  const colonMatch = /^(\d+):(\d+)$/.exec(numericPart);
  if (colonMatch) {
    const chapter = parseInt(colonMatch[1], 10);
    const verse = parseInt(colonMatch[2], 10);
    if (isValidSplit(bookId, chapter, verse, maxChapter)) {
      return [{ chapter, verse }];
    }
    return [];
  }

  // Formato "chapter verse" (com espaço).
  const spaceMatch = /^(\d+)\s+(\d+)$/.exec(numericPart);
  if (spaceMatch) {
    const chapter = parseInt(spaceMatch[1], 10);
    const verse = parseInt(spaceMatch[2], 10);
    if (isValidSplit(bookId, chapter, verse, maxChapter)) {
      return [{ chapter, verse }];
    }
    return [];
  }

  // Formato "chapter" (apenas capítulo, sem versículo).
  // Só retorna early se for um chapter válido. Se o número for maior
  // que maxChapter, cai para o split compacto (ex.: "1111" → 11:11).
  const chapterOnlyMatch = /^(\d+)$/.exec(numericPart);
  if (chapterOnlyMatch) {
    const chapter = parseInt(chapterOnlyMatch[1], 10);
    if (chapter >= 1 && chapter <= maxChapter) {
      return [{ chapter, verse: null }];
    }
    // Número > maxChapter: tentar split compacto (ex.: "1111" → 11:11).
    if (numericPart.length >= 2) {
      return generateCompactSplits(numericPart, bookId, maxChapter);
    }
    return [];
  }

  return [];
}

/**
 * Gera todas as splits válidas de uma string numérica compacta.
 * Ex.: "828" → [(8, 28), (82, 8)] → filtra por maxChapter/maxVerse.
 */
function generateCompactSplits(
  digits: string,
  bookId: number,
  maxChapter: number,
): ChapterVerseCandidate[] {
  const candidates: ChapterVerseCandidate[] = [];

  for (let splitPos = 1; splitPos < digits.length; splitPos++) {
    const chapterStr = digits.slice(0, splitPos);
    const verseStr = digits.slice(splitPos);

    const chapter = parseInt(chapterStr, 10);
    const verse = parseInt(verseStr, 10);

    // Chapter não pode ter leading zero (ex.: "0828" → chapter=08 inválido).
    if (chapterStr.length > 1 && chapterStr[0] === "0") continue;
    // Verse não pode ter leading zero.
    if (verseStr.length > 1 && verseStr[0] === "0") continue;

    if (isValidSplit(bookId, chapter, verse, maxChapter)) {
      candidates.push({ chapter, verse });
    }
  }

  // Se nenhuma split com versículo for válida, tentar como chapter apenas.
  if (candidates.length === 0) {
    const chapter = parseInt(digits, 10);
    if (chapter >= 1 && chapter <= maxChapter) {
      return [{ chapter, verse: null }];
    }
  }

  return candidates;
}

/**
 * Valida se uma split (chapter, verse) é viável.
 * Usa maxChapter (exato) e maxVerseHeuristic (aproximado).
 */
function isValidSplit(
  bookId: number,
  chapter: number,
  verse: number,
  maxChapter: number,
): boolean {
  if (chapter < 1 || chapter > maxChapter) return false;
  if (verse < 1) return false;
  const maxVerse = getMaxVerseHeuristic(bookId, chapter);
  if (verse > maxVerse) return false;
  return true;
}

// ============================================================
// Helpers — deduplicação
// ============================================================

function deduplicateInterpretations(
  interpretations: ReferenceInterpretation[],
): ReferenceInterpretation[] {
  const seen = new Set<string>();
  const result: ReferenceInterpretation[] = [];
  for (const interp of interpretations) {
    const key = `${interp.ref.bookId}:${interp.ref.chapter}:${interp.ref.verse ?? "null"}`;
    if (!seen.has(key)) {
      seen.add(key);
      result.push(interp);
    }
  }
  return result;
}
