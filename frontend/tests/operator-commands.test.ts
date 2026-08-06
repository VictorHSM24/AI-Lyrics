/**
 * Sprint 25 Fase B — Testes da camada de comandos (WorkspaceCommands).
 *
 * Valida:
 * 1. NextVerseCommand atravessa capítulos (João 3:36 → João 4:1).
 * 2. NextVerseCommand atravessa livros (Malaquias 4:6 → Mateus 1:1).
 * 3. PreviousVerseCommand atravessa capítulos no sentido inverso.
 * 4. PreviousVerseCommand atravessa livros no sentido inverso.
 * 5. NextChapterCommand atravessa livros.
 * 6. PreviousChapterCommand atravessa livros.
 * 7. PresentVerseCommand dispara presentVerse e recordUsage.
 * 8. ReplayVerseCommand usa presented (ou selected como fallback).
 * 9. ClearSelectionCommand limpa selected.
 * 10. SelectByReferenceCommand seleciona referência específica.
 * 11. executeCommand por nome funciona para todos os comandos.
 * 12. Comandos retornam erro quando não há seleção.
 */

import { describe, it, expect } from "vitest";
import {
  NextVerseCommand,
  PreviousVerseCommand,
  NextChapterCommand,
  PreviousChapterCommand,
  PresentVerseCommand,
  ReplayVerseCommand,
  ClearSelectionCommand,
  SelectByReferenceCommand,
  executeCommand,
  COMMAND_NAMES,
  type WorkspaceContext,
} from "@/components/operator/WorkspaceCommands";
import type { OperatorRef } from "@/stores";
import type { OperatorVerseDTO, OperatorPresentResultDTO } from "@/types";

// ============================================================
// Mock context builder
// ============================================================

interface MockData {
  books: Array<{ id: number; canonical: string }>;
  chapters: Record<number, number[]>;
  verses: Record<string, number[]>;
  versesData: Record<string, OperatorVerseDTO>;
}

function makeVerseDTO(bookId: number, chapter: number, verse: number): OperatorVerseDTO {
  return {
    book_id: bookId,
    book: `Book${bookId}`,
    chapter,
    verse,
    reference: `Book${bookId} ${chapter}:${verse}`,
    text: `Texto de ${bookId}:${chapter}:${verse}`,
    version: "ACF",
  };
}

function makeContext(
  data: MockData,
  options: {
    selected?: OperatorRef | null;
    presented?: OperatorRef | null;
    quickPresentation?: boolean;
  } = {},
): WorkspaceContext & { _setSelectedCalls: OperatorRef[]; _presentCalls: Array<{ book_id: number; chapter: number; verse: number; quick?: boolean }>; _recordUsageCalls: Array<{ ref: OperatorRef; label: string }> } {
  const _setSelectedCalls: OperatorRef[] = [];
  const _presentCalls: Array<{ book_id: number; chapter: number; verse: number; quick?: boolean }> = [];
  const _recordUsageCalls: Array<{ ref: OperatorRef; label: string }> = [];

  let _selected = options.selected ?? null;

  return {
    get selected() { return _selected; },
    get presented() { return options.presented ?? null; },
    get quickPresentation() { return options.quickPresentation ?? false; },
    get books() { return data.books; },
    getChapters: async (bookId: number) => data.chapters[bookId] ?? [],
    getVerses: async (bookId: number, chapter: number) => data.verses[`${bookId}:${chapter}`] ?? [],
    getVerse: async (bookId: number, chapter: number, verse: number) => {
      const key = `${bookId}:${chapter}:${verse}`;
      return data.versesData[key] ?? makeVerseDTO(bookId, chapter, verse);
    },
    presentVerse: async (req) => {
      _presentCalls.push(req);
      const result: OperatorPresentResultDTO = {
        ok: true,
        message: "OK",
        reference: `Book${req.book_id} ${req.chapter}:${req.verse}`,
        book_id: req.book_id,
        chapter: req.chapter,
        verse: req.verse,
        version: "ACF",
        holyrics_status: "ok",
        latency_ms: 50,
      };
      return result;
    },
    setSelected: (ref: OperatorRef | null) => {
      _setSelectedCalls.push(ref as OperatorRef);
      _selected = ref;
    },
    recordUsage: (ref: OperatorRef, label: string) => {
      _recordUsageCalls.push({ ref, label });
    },
    _setSelectedCalls,
    _presentCalls,
    _recordUsageCalls,
  } as WorkspaceContext & { _setSelectedCalls: OperatorRef[]; _presentCalls: Array<{ book_id: number; chapter: number; verse: number; quick?: boolean }>; _recordUsageCalls: Array<{ ref: OperatorRef; label: string }> };
}

// Dados de teste: 3 livros (1, 2, 3), cada um com 2 capítulos,
// capítulos com versículos variados.
const MOCK_DATA: MockData = {
  books: [
    { id: 1, canonical: "Gênesis" },
    { id: 2, canonical: "Êxodo" },
    { id: 3, canonical: "Levítico" },
  ],
  chapters: {
    1: [1, 2],
    2: [1, 2],
    3: [1, 2],
  },
  verses: {
    "1:1": [1, 2, 3],
    "1:2": [1, 2],        // capítulo final do livro 1, só 2 versículos
    "2:1": [1, 2, 3, 4],
    "2:2": [1, 2, 3],
    "3:1": [1, 2],
    "3:2": [1, 2, 3, 4],  // último capítulo do último livro
  },
  versesData: {},
};

// ============================================================
// Testes
// ============================================================

describe("WorkspaceCommands — navegação contínua", () => {
  it("NextVerseCommand: próximo versículo no mesmo capítulo", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 1, chapter: 1, verse: 1 } });
    const result = await NextVerseCommand(ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 1, chapter: 1, verse: 2 });
    expect((ctx as any)._setSelectedCalls).toEqual([{ bookId: 1, chapter: 1, verse: 2 }]);
  });

  it("NextVerseCommand: atravessa capítulos (1:1:3 → 1:2:1)", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 1, chapter: 1, verse: 3 } });
    const result = await NextVerseCommand(ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 1, chapter: 2, verse: 1 });
  });

  it("NextVerseCommand: atravessa livros (1:2:2 → 2:1:1)", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 1, chapter: 2, verse: 2 } });
    const result = await NextVerseCommand(ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 2, chapter: 1, verse: 1 });
  });

  it("NextVerseCommand: fim da Bíblia retorna erro (3:2:4)", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 3, chapter: 2, verse: 4 } });
    const result = await NextVerseCommand(ctx);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("Fim da Bíblia");
  });

  it("PreviousVerseCommand: versículo anterior no mesmo capítulo", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 1, chapter: 1, verse: 3 } });
    const result = await PreviousVerseCommand(ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 1, chapter: 1, verse: 2 });
  });

  it("PreviousVerseCommand: atravessa capítulos no sentido inverso (1:2:1 → 1:1:3)", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 1, chapter: 2, verse: 1 } });
    const result = await PreviousVerseCommand(ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 1, chapter: 1, verse: 3 });
  });

  it("PreviousVerseCommand: atravessa livros no sentido inverso (2:1:1 → 1:2:2)", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 2, chapter: 1, verse: 1 } });
    const result = await PreviousVerseCommand(ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 1, chapter: 2, verse: 2 });
  });

  it("PreviousVerseCommand: início da Bíblia retorna erro (1:1:1)", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 1, chapter: 1, verse: 1 } });
    const result = await PreviousVerseCommand(ctx);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("Início da Bíblia");
  });

  it("NextChapterCommand: próximo capítulo no mesmo livro", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 1, chapter: 1, verse: 2 } });
    const result = await NextChapterCommand(ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 1, chapter: 2, verse: 1 });
  });

  it("NextChapterCommand: atravessa livros (1:2 → 2:1:1)", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 1, chapter: 2, verse: 1 } });
    const result = await NextChapterCommand(ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 2, chapter: 1, verse: 1 });
  });

  it("PreviousChapterCommand: capítulo anterior no mesmo livro (último versículo)", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 1, chapter: 2, verse: 1 } });
    const result = await PreviousChapterCommand(ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 1, chapter: 1, verse: 3 }); // último versículo do cap 1
  });

  it("PreviousChapterCommand: atravessa livros (2:1 → 1:2:2)", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 2, chapter: 1, verse: 1 } });
    const result = await PreviousChapterCommand(ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 1, chapter: 2, verse: 2 });
  });
});

describe("WorkspaceCommands — apresentação", () => {
  it("PresentVerseCommand: dispara presentVerse e recordUsage", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 43, chapter: 3, verse: 16 } });
    const result = await PresentVerseCommand(ctx);
    expect(result.ok).toBe(true);
    expect((ctx as any)._presentCalls).toHaveLength(1);
    expect((ctx as any)._presentCalls[0]).toEqual({
      book_id: 43,
      chapter: 3,
      verse: 16,
      quick: false,
    });
    expect((ctx as any)._recordUsageCalls).toHaveLength(1);
    expect((ctx as any)._recordUsageCalls[0].ref).toEqual({ bookId: 43, chapter: 3, verse: 16 });
  });

  it("PresentVerseCommand: erro quando não há seleção", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: null });
    const result = await PresentVerseCommand(ctx);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("selecionado");
  });

  it("ReplayVerseCommand: usa presented quando disponível", async () => {
    const ctx = makeContext(MOCK_DATA, {
      selected: { bookId: 1, chapter: 1, verse: 1 },
      presented: { bookId: 2, chapter: 2, verse: 2 },
    });
    const result = await ReplayVerseCommand(ctx);
    expect(result.ok).toBe(true);
    expect((ctx as any)._presentCalls[0]).toEqual({
      book_id: 2,
      chapter: 2,
      verse: 2,
      quick: false,
    });
  });

  it("ReplayVerseCommand: usa selected como fallback quando não há presented", async () => {
    const ctx = makeContext(MOCK_DATA, {
      selected: { bookId: 1, chapter: 1, verse: 1 },
      presented: null,
    });
    const result = await ReplayVerseCommand(ctx);
    expect(result.ok).toBe(true);
    expect((ctx as any)._presentCalls[0]).toEqual({
      book_id: 1,
      chapter: 1,
      verse: 1,
      quick: false,
    });
  });

  it("ReplayVerseCommand: erro quando não há selected nem presented", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: null, presented: null });
    const result = await ReplayVerseCommand(ctx);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("reapresentar");
  });
});

describe("WorkspaceCommands — seleção", () => {
  it("ClearSelectionCommand: limpa selected", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 1, chapter: 1, verse: 1 } });
    const result = await ClearSelectionCommand(ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toBeNull();
    expect((ctx as any)._setSelectedCalls).toEqual([null]);
  });

  it("SelectByReferenceCommand: seleciona referência específica", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: null });
    const ref: OperatorRef = { bookId: 2, chapter: 3, verse: 4 };
    const result = await SelectByReferenceCommand(ctx, ref);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual(ref);
    expect((ctx as any)._setSelectedCalls).toEqual([ref]);
  });
});

describe("WorkspaceCommands — executeCommand por nome", () => {
  it("executeCommand executa todos os comandos por nome", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: { bookId: 1, chapter: 1, verse: 1 } });

    // nextVerse
    let result = await executeCommand("nextVerse", ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 1, chapter: 1, verse: 2 });

    // previousVerse
    result = await executeCommand("previousVerse", ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 1, chapter: 1, verse: 1 });

    // nextChapter
    result = await executeCommand("nextChapter", ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 1, chapter: 2, verse: 1 });

    // previousChapter
    result = await executeCommand("previousChapter", ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toEqual({ bookId: 1, chapter: 1, verse: 3 });

    // clearSelection
    result = await executeCommand("clearSelection", ctx);
    expect(result.ok).toBe(true);
    expect(result.ref).toBeNull();
  });

  it("COMMAND_NAMES lista todos os comandos", () => {
    expect(COMMAND_NAMES).toContain("nextVerse");
    expect(COMMAND_NAMES).toContain("previousVerse");
    expect(COMMAND_NAMES).toContain("nextChapter");
    expect(COMMAND_NAMES).toContain("previousChapter");
    expect(COMMAND_NAMES).toContain("presentVerse");
    expect(COMMAND_NAMES).toContain("replayVerse");
    expect(COMMAND_NAMES).toContain("clearSelection");
    expect(COMMAND_NAMES).toHaveLength(7);
  });
});

describe("WorkspaceCommands — casos extremos", () => {
  it("NextVerseCommand: erro quando não há seleção", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: null });
    const result = await NextVerseCommand(ctx);
    expect(result.ok).toBe(false);
    expect(result.error).toContain("selecionado");
  });

  it("PreviousVerseCommand: erro quando não há seleção", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: null });
    const result = await PreviousVerseCommand(ctx);
    expect(result.ok).toBe(false);
  });

  it("NextChapterCommand: erro quando não há seleção", async () => {
    const ctx = makeContext(MOCK_DATA, { selected: null });
    const result = await NextChapterCommand(ctx);
    expect(result.ok).toBe(false);
  });

  it("NextVerseCommand: quickPresentation é repassado para presentVerse", async () => {
    const ctx = makeContext(MOCK_DATA, {
      selected: { bookId: 1, chapter: 1, verse: 1 },
      quickPresentation: true,
    });
    await PresentVerseCommand(ctx);
    expect((ctx as any)._presentCalls[0].quick).toBe(true);
  });
});
