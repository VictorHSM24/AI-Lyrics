/**
 * WorkspaceCommands (Sprint 25 Fase B) — camada de comandos reutilizável.
 *
 * Arquitetura obrigatória:
 *   Keyboard → Command → Workspace → UI
 *
 * Os comandos encapsulam TODA a regra de negócio de navegação e
 * apresentação. Eles são a única forma de alterar `selected` e
 * disparar apresentações.
 *
 * Comandos são reutilizáveis por:
 * - KeyboardController (B2)
 * - QuickNavigator botões (B1)
 * - QuickSearch (Fase C, futura)
 * - FavoritesPanel (Fase C, futura)
 * - HistoryPanel (Fase C, futura)
 * - Stream Deck / MIDI / API externa (futuro)
 *
 * Nenhum componente React contém lógica de negócio. Eles apenas
 * disparam comandos e reagem ao Workspace.
 */

import type { OperatorRef } from "@/stores";
import type { OperatorVerseDTO, OperatorPresentResultDTO } from "@/types";

// ============================================================
// WorkspaceContext — dependências injetadas nos comandos.
// ============================================================

/**
 * Contexto que os comandos recebem para executar. Inclui acesso a:
 * - workspace store (alterar selected)
 * - navigation (cache LRU de chapters/verses/verse)
 * - operator service (apresentar versículo)
 * - versePresentation entry (para reapresentar)
 *
 * Esta interface é o "contrato" dos comandos. Qualquer fonte
 * (keyboard, botão, API externa) pode construir um contexto e
 * disparar comandos.
 */
export interface WorkspaceContext {
  /** Referência atualmente selecionada (ou null). */
  selected: OperatorRef | null;
  /** Referência atualmente apresentada (ou null). */
  presented: OperatorRef | null;
  /** Quick presentation ativo. */
  quickPresentation: boolean;
  /** Lista de livros (para navegação entre livros). */
  books: Array<{ id: number; canonical: string }>;
  /** Carrega capítulos de um livro (com cache LRU). */
  getChapters(bookId: number): Promise<number[]>;
  /** Carrega versículos de um capítulo (com cache LRU). */
  getVerses(bookId: number, chapter: number): Promise<number[]>;
  /** Carrega versículo específico (com cache LRU). */
  getVerse(bookId: number, chapter: number, verse: number): Promise<OperatorVerseDTO>;
  /** Apresenta versículo no Holyrics. */
  presentVerse(req: { book_id: number; chapter: number; verse: number; quick?: boolean }): Promise<OperatorPresentResultDTO>;
  /** Atualiza selected no workspace store. */
  setSelected(ref: OperatorRef | null): void;
  /** Registra uso no recents store (para Fase C). */
  recordUsage(ref: OperatorRef, label: string): void;
}

// ============================================================
// Tipos de retorno
// ============================================================

export interface CommandResult {
  /** True se o comando executou com sucesso. */
  ok: boolean;
  /** Referência resultante (ou null se selecionado foi limpo). */
  ref: OperatorRef | null;
  /** Versículo carregado (para preview), se aplicável. */
  verse: OperatorVerseDTO | null;
  /** Mensagem de erro (se ok=false). */
  error?: string;
}

// ============================================================
// Helpers de navegação contínua
// ============================================================

/**
 * Ordena livros por ID (1..66) para navegação sequencial.
 */
function sortedBookIds(books: Array<{ id: number }>): number[] {
  return books.map((b) => b.id).sort((a, b) => a - b);
}

/**
 * Encontra o próximo livro após bookId (por ID). Se bookId é o último,
 * retorna null (não há wrap-around entre Malaquias e Mateus na navegação
 * contínua; o operador pode navegar manualmente se quiser).
 *
 * Na prática, a Bíblia tem 66 livros sequenciais (1..66), então
 * próximo = bookId + 1 se existir.
 */
function nextBookId(books: Array<{ id: number }>, bookId: number): number | null {
  const ids = sortedBookIds(books);
  const idx = ids.indexOf(bookId);
  if (idx < 0) return null;
  if (idx + 1 >= ids.length) return null;
  return ids[idx + 1];
}

function previousBookId(books: Array<{ id: number }>, bookId: number): number | null {
  const ids = sortedBookIds(books);
  const idx = ids.indexOf(bookId);
  if (idx < 0) return null;
  if (idx === 0) return null;
  return ids[idx - 1];
}

// ============================================================
// Comandos de navegação
// ============================================================

/**
 * Próximo versículo. Atravessa capítulos e livros:
 * - Se verse < max verse do capítulo: verse + 1
 * - Se verse = max: próximo capítulo, verse 1
 * - Se capítulo = max: próximo livro, capítulo 1, verse 1
 */
export async function NextVerseCommand(ctx: WorkspaceContext): Promise<CommandResult> {
  if (!ctx.selected) {
    return { ok: false, ref: null, verse: null, error: "Nenhum versículo selecionado." };
  }
  const { bookId, chapter, verse } = ctx.selected;

  try {
    const verses = await ctx.getVerses(bookId, chapter);
    const maxVerse = verses.length > 0 ? Math.max(...verses) : 0;

    if (verse < maxVerse) {
      // Próximo versículo no mesmo capítulo.
      return await selectAndLoad(ctx, { bookId, chapter, verse: verse + 1 });
    }

    // Fim do capítulo: próximo capítulo.
    const chapters = await ctx.getChapters(bookId);
    const maxChapter = chapters.length > 0 ? Math.max(...chapters) : 0;

    if (chapter < maxChapter) {
      // Próximo capítulo no mesmo livro.
      return await selectAndLoad(ctx, { bookId, chapter: chapter + 1, verse: 1 });
    }

    // Fim do livro: próximo livro.
    const nextBook = nextBookId(ctx.books, bookId);
    if (nextBook === null) {
      // Fim da Bíblia (Malaquias 4:6 ou Apocalipse 22:21).
      return { ok: false, ref: ctx.selected, verse: null, error: "Fim da Bíblia." };
    }
    return await selectAndLoad(ctx, { bookId: nextBook, chapter: 1, verse: 1 });
  } catch (e) {
    return { ok: false, ref: ctx.selected, verse: null, error: errorMessage(e) };
  }
}

/**
 * Versículo anterior. Atravessa capítulos e livros no sentido inverso.
 */
export async function PreviousVerseCommand(ctx: WorkspaceContext): Promise<CommandResult> {
  if (!ctx.selected) {
    return { ok: false, ref: null, verse: null, error: "Nenhum versículo selecionado." };
  }
  const { bookId, chapter, verse } = ctx.selected;

  try {
    if (verse > 1) {
      // Versículo anterior no mesmo capítulo.
      return await selectAndLoad(ctx, { bookId, chapter, verse: verse - 1 });
    }

    // Início do capítulo: capítulo anterior.
    if (chapter > 1) {
      // Capítulo anterior no mesmo livro.
      const prevChapter = chapter - 1;
      const verses = await ctx.getVerses(bookId, prevChapter);
      const maxVerse = verses.length > 0 ? Math.max(...verses) : 1;
      return await selectAndLoad(ctx, { bookId, chapter: prevChapter, verse: maxVerse });
    }

    // Início do livro: livro anterior.
    const prevBook = previousBookId(ctx.books, bookId);
    if (prevBook === null) {
      // Início da Bíblia (Gênesis 1:1).
      return { ok: false, ref: ctx.selected, verse: null, error: "Início da Bíblia." };
    }
    const prevBookChapters = await ctx.getChapters(prevBook);
    const maxChapter = prevBookChapters.length > 0 ? Math.max(...prevBookChapters) : 1;
    const verses = await ctx.getVerses(prevBook, maxChapter);
    const maxVerse = verses.length > 0 ? Math.max(...verses) : 1;
    return await selectAndLoad(ctx, { bookId: prevBook, chapter: maxChapter, verse: maxVerse });
  } catch (e) {
    return { ok: false, ref: ctx.selected, verse: null, error: errorMessage(e) };
  }
}

/**
 * Próximo capítulo (verse=1). Atravessa livros.
 */
export async function NextChapterCommand(ctx: WorkspaceContext): Promise<CommandResult> {
  if (!ctx.selected) {
    return { ok: false, ref: null, verse: null, error: "Nenhum versículo selecionado." };
  }
  const { bookId, chapter } = ctx.selected;

  try {
    const chapters = await ctx.getChapters(bookId);
    const maxChapter = chapters.length > 0 ? Math.max(...chapters) : 0;

    if (chapter < maxChapter) {
      return await selectAndLoad(ctx, { bookId, chapter: chapter + 1, verse: 1 });
    }

    // Fim do livro: próximo livro, capítulo 1.
    const nextBook = nextBookId(ctx.books, bookId);
    if (nextBook === null) {
      return { ok: false, ref: ctx.selected, verse: null, error: "Fim da Bíblia." };
    }
    return await selectAndLoad(ctx, { bookId: nextBook, chapter: 1, verse: 1 });
  } catch (e) {
    return { ok: false, ref: ctx.selected, verse: null, error: errorMessage(e) };
  }
}

/**
 * Capítulo anterior (último versículo). Atravessa livros.
 */
export async function PreviousChapterCommand(ctx: WorkspaceContext): Promise<CommandResult> {
  if (!ctx.selected) {
    return { ok: false, ref: null, verse: null, error: "Nenhum versículo selecionado." };
  }
  const { bookId, chapter } = ctx.selected;

  try {
    if (chapter > 1) {
      const prevChapter = chapter - 1;
      const verses = await ctx.getVerses(bookId, prevChapter);
      const maxVerse = verses.length > 0 ? Math.max(...verses) : 1;
      return await selectAndLoad(ctx, { bookId, chapter: prevChapter, verse: maxVerse });
    }

    // Início do livro: livro anterior, último capítulo, último versículo.
    const prevBook = previousBookId(ctx.books, bookId);
    if (prevBook === null) {
      return { ok: false, ref: ctx.selected, verse: null, error: "Início da Bíblia." };
    }
    const prevBookChapters = await ctx.getChapters(prevBook);
    const maxChapter = prevBookChapters.length > 0 ? Math.max(...prevBookChapters) : 1;
    const verses = await ctx.getVerses(prevBook, maxChapter);
    const maxVerse = verses.length > 0 ? Math.max(...verses) : 1;
    return await selectAndLoad(ctx, { bookId: prevBook, chapter: maxChapter, verse: maxVerse });
  } catch (e) {
    return { ok: false, ref: ctx.selected, verse: null, error: errorMessage(e) };
  }
}

// ============================================================
// Comandos de apresentação
// ============================================================

/**
 * Apresenta o versículo selecionado no Holyrics.
 * Publica VersePresented via EventBus (backend).
 */
export async function PresentVerseCommand(ctx: WorkspaceContext): Promise<CommandResult> {
  if (!ctx.selected) {
    return { ok: false, ref: null, verse: null, error: "Nenhum versículo selecionado." };
  }
  const { bookId, chapter, verse } = ctx.selected;

  try {
    const result = await ctx.presentVerse({
      book_id: bookId,
      chapter,
      verse,
      quick: ctx.quickPresentation,
    });
    if (!result.ok) {
      return { ok: false, ref: ctx.selected, verse: null, error: result.message };
    }
    // Registrar uso para Fase C (recentes por frequência).
    ctx.recordUsage(ctx.selected, result.reference);
    // selected sincroniza com presented após apresentação bem-sucedida.
    // A sincronização visual acontece via VersePresentationStore (evento).
    return { ok: true, ref: ctx.selected, verse: null };
  } catch (e) {
    return { ok: false, ref: ctx.selected, verse: null, error: errorMessage(e) };
  }
}

/**
 * Reapresenta o versículo atualmente apresentado (ou selecionado,
 * se nada foi apresentado ainda).
 */
export async function ReplayVerseCommand(ctx: WorkspaceContext): Promise<CommandResult> {
  const ref = ctx.presented ?? ctx.selected;
  if (!ref) {
    return { ok: false, ref: null, verse: null, error: "Nada para reapresentar." };
  }
  try {
    const result = await ctx.presentVerse({
      book_id: ref.bookId,
      chapter: ref.chapter,
      verse: ref.verse,
      quick: ctx.quickPresentation,
    });
    if (!result.ok) {
      return { ok: false, ref, verse: null, error: result.message };
    }
    ctx.recordUsage(ref, result.reference);
    return { ok: true, ref, verse: null };
  } catch (e) {
    return { ok: false, ref, verse: null, error: errorMessage(e) };
  }
}

// ============================================================
// Comandos de seleção
// ============================================================

/**
 * Limpa a seleção (Esc).
 */
export async function ClearSelectionCommand(ctx: WorkspaceContext): Promise<CommandResult> {
  ctx.setSelected(null);
  return { ok: true, ref: null, verse: null };
}

/**
 * Seleciona uma referência específica (usado por busca, favoritos,
 * histórico na Fase C, e por QuickNavigator ao clicar em um versículo
 * da lista).
 */
export async function SelectByReferenceCommand(
  ctx: WorkspaceContext,
  ref: OperatorRef,
): Promise<CommandResult> {
  return await selectAndLoad(ctx, ref);
}

// ============================================================
// Helpers internos
// ============================================================

/**
 * Seleciona uma referência, carrega o versículo (preview) e atualiza
 * o workspace store.
 */
async function selectAndLoad(
  ctx: WorkspaceContext,
  ref: OperatorRef,
): Promise<CommandResult> {
  try {
    const verse = await ctx.getVerse(ref.bookId, ref.chapter, ref.verse);
    ctx.setSelected(ref);
    return { ok: true, ref, verse };
  } catch (e) {
    // Se não conseguir carregar o versículo, ainda assim seleciona
    // a referência (o operador pode tentar apresentar mesmo assim).
    ctx.setSelected(ref);
    return { ok: false, ref, verse: null, error: errorMessage(e) };
  }
}

function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}

// ============================================================
// Registry de comandos — para descoberta e execução por nome.
// ============================================================

export type CommandName =
  | "nextVerse"
  | "previousVerse"
  | "nextChapter"
  | "previousChapter"
  | "presentVerse"
  | "replayVerse"
  | "clearSelection";

export const COMMAND_NAMES: readonly CommandName[] = [
  "nextVerse",
  "previousVerse",
  "nextChapter",
  "previousChapter",
  "presentVerse",
  "replayVerse",
  "clearSelection",
] as const;

/**
 * Executa um comando por nome. Útil para fontes que não conhecem
 * a função diretamente (ex: Stream Deck, MIDI, API externa).
 */
export async function executeCommand(
  name: CommandName,
  ctx: WorkspaceContext,
): Promise<CommandResult> {
  switch (name) {
    case "nextVerse":
      return NextVerseCommand(ctx);
    case "previousVerse":
      return PreviousVerseCommand(ctx);
    case "nextChapter":
      return NextChapterCommand(ctx);
    case "previousChapter":
      return PreviousChapterCommand(ctx);
    case "presentVerse":
      return PresentVerseCommand(ctx);
    case "replayVerse":
      return ReplayVerseCommand(ctx);
    case "clearSelection":
      return ClearSelectionCommand(ctx);
  }
}
