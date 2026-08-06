/**
 * bibleStructure (Sprint 26) — estrutura estática da Bíblia.
 *
 * Contém o número máximo de capítulos por livro (1..66). Os dados são
 * imutáveis (a Bíblia é fechada) e usados pelo ReferenceResolver para
 * validar splits numéricos sem consultar o backend durante a digitação.
 *
 * Para validação de versículos, usa-se um limite superior heurístico
 * (99 versículos por capítulo, exceto Salmos 119 que tem 176). Isso
 * é suficiente para eliminar splits obviamente inválidos como
 * "Romanos 1111 → 1:111" (Romanos 1 tem 32 versículos, 111 > 99).
 *
 * A validação final do versículo é feita pelo backend no Enter.
 */

/** Max capítulos por livro (index = bookId - 1). */
export const BOOK_MAX_CHAPTERS: readonly number[] = [
  /* 1  Gênesis      */ 50,
  /* 2  Êxodo        */ 40,
  /* 3  Levítico     */ 27,
  /* 4  Números      */ 36,
  /* 5  Deuteronômio */ 34,
  /* 6  Josué        */ 24,
  /* 7  Juízes       */ 21,
  /* 8  Rute         */ 4,
  /* 9  1 Samuel     */ 31,
  /* 10 2 Samuel     */ 24,
  /* 11 1 Reis       */ 22,
  /* 12 2 Reis       */ 25,
  /* 13 1 Crônicas   */ 29,
  /* 14 2 Crônicas   */ 36,
  /* 15 Esdras       */ 10,
  /* 16 Neemias      */ 13,
  /* 17 Ester        */ 10,
  /* 18 Jó           */ 42,
  /* 19 Salmos       */ 150,
  /* 20 Provérbios   */ 31,
  /* 21 Eclesiastes  */ 12,
  /* 22 Cânticos     */ 8,
  /* 23 Isaías       */ 66,
  /* 24 Jeremias     */ 52,
  /* 25 Lamentações  */ 5,
  /* 26 Ezequiel     */ 48,
  /* 27 Daniel       */ 12,
  /* 28 Oséias       */ 14,
  /* 29 Joel         */ 3,
  /* 30 Amós         */ 9,
  /* 31 Obadias      */ 1,
  /* 32 Jonas        */ 4,
  /* 33 Miqueias     */ 7,
  /* 34 Naum         */ 3,
  /* 35 Habacuque    */ 3,
  /* 36 Sofonias     */ 3,
  /* 37 Ageu         */ 2,
  /* 38 Zacarias     */ 14,
  /* 39 Malaquias    */ 4,
  /* 40 Mateus       */ 28,
  /* 41 Marcos       */ 16,
  /* 42 Lucas        */ 24,
  /* 43 João         */ 21,
  /* 44 Atos         */ 28,
  /* 45 Romanos      */ 16,
  /* 46 1 Coríntios  */ 16,
  /* 47 2 Coríntios  */ 13,
  /* 48 Gálatas      */ 6,
  /* 49 Efésios      */ 6,
  /* 50 Filipenses   */ 4,
  /* 51 Colossenses  */ 4,
  /* 52 1 Tessalonicenses */ 5,
  /* 53 2 Tessalonicenses */ 3,
  /* 54 1 Timóteo    */ 6,
  /* 55 2 Timóteo    */ 4,
  /* 56 Tito         */ 3,
  /* 57 Filemom      */ 1,
  /* 58 Hebreus      */ 13,
  /* 59 Tiago        */ 5,
  /* 60 1 Pedro      */ 5,
  /* 61 2 Pedro      */ 3,
  /* 62 1 João       */ 5,
  /* 63 2 João       */ 1,
  /* 64 3 João       */ 1,
  /* 65 Judas        */ 1,
  /* 66 Apocalipse   */ 22,
];

/** Limite heurístico de versículos por capítulo (exceto Sl 119). */
const DEFAULT_MAX_VERSE_HEURISTIC = 99;

/** Exceções: capítulos com > 99 versículos. */
const VERSE_EXCEPTIONS: ReadonlyMap<string, number> = new Map([
  ["19:119", 176], // Salmos 119
]);

/**
 * Retorna o número máximo de capítulos de um livro.
 * @param bookId ID do livro (1..66).
 * @returns Max capítulos, ou 0 se bookId inválido.
 */
export function getMaxChapters(bookId: number): number {
  if (bookId < 1 || bookId > BOOK_MAX_CHAPTERS.length) return 0;
  return BOOK_MAX_CHAPTERS[bookId - 1] ?? 0;
}

/**
 * Retorna o limite heurístico de versículos para um capítulo.
 * Na prática, quase todos os capítulos têm ≤ 99 versículos.
 * A única exceção notável é Salmos 119 (176 versículos).
 *
 * NOTA: Este valor é heurístico, não exato. A validação final
 * é feita pelo backend no Enter.
 */
export function getMaxVerseHeuristic(bookId: number, chapter: number): number {
  const key = `${bookId}:${chapter}`;
  return VERSE_EXCEPTIONS.get(key) ?? DEFAULT_MAX_VERSE_HEURISTIC;
}
