/**
 * AutoCompleteEngine (Sprint 26 D3) — autocomplete IDE-style de livros.
 *
 * Durante a digitação, se o prefixo digitado corresponder a exatamente
 * um livro, o sistema completa automaticamente o nome do livro,
 * selecionando visualmente apenas a parte completada.
 *
 * Exemplo:
 *   "r"   → Reis, Romanos, Rute → NÃO completa (múltiplos)
 *   "ro"  → Romanos             → completa "Romanos" (seleciona "manos")
 *   "rom" → Romanos             → completa "Romanos" (seleciona "anos")
 *
 * Comportamento:
 * - Só completa quando há exatamente UM match de prefixo.
 * - Se o operador continuar digitando, a autocompletação desaparece
 *   naturalmente (o prefixo deixa de corresponder).
 * - Não completa se o que foi digitado já é um nome completo.
 */

import { type BookAliasIndex, normalizeText } from "./parseBibleReference";

// ============================================================
// Tipos
// ============================================================

export interface AutoCompleteResult {
  /** Livro correspondente (ou null se ambíguo/nenhum). */
  bookId: number | null;
  /** Nome canônico do livro (ou null). */
  bookName: string | null;
  /** Texto que seria completado (ex.: "manos" para "ro" → "Romanos"). */
  completion: string | null;
  /** Texto completo após completar (ex.: "Romanos"). */
  fullText: string | null;
}

// ============================================================
// Engine
// ============================================================

/**
 * Tenta completar o prefixo digitado para um nome único de livro.
 *
 * @param prefix  Texto parcial digitado (ex.: "ro", "rom").
 * @param index   Índice de aliases de livros.
 * @returns Resultado com completion se único, ou nulls se ambíguo.
 */
export function autoCompleteBook(
  prefix: string,
  index: BookAliasIndex,
): AutoCompleteResult {
  const norm = normalizeText(prefix);
  if (!norm) {
    return { bookId: null, bookName: null, completion: null, fullText: null };
  }

  // Buscar livros cujo nome canônico normalizado começa com o prefixo.
  // Apenas nomes canônicos (não aliases) para completar, porque aliases
  // são abreviações que não fazem sentido completar.
  // Mesmo se o prefixo é uma alias exata (ex.: "ro" é alias de Romanos),
  // ainda completamos para o nome canônico completo se for prefixo.
  const matches = new Map<number, string>(); // bookId → canonical
  for (const book of index.books) {
    const canonicalNorm = normalizeText(book.canonical);
    if (canonicalNorm.startsWith(norm) && canonicalNorm.length > norm.length) {
      matches.set(book.id, book.canonical);
    }
  }

  if (matches.size === 1) {
    const [bookId, bookName] = matches.entries().next().value as [number, string];
    // O completion é a parte após o prefixo.
    const completion = bookName.slice(prefix.length);
    return {
      bookId,
      bookName,
      completion,
      fullText: bookName,
    };
  }

  return { bookId: null, bookName: null, completion: null, fullText: null };
}
