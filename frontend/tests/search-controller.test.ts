/**
 * Sprint 25 Fase C — Testes do SearchController.
 *
 * Valida:
 * 1. Sugestões instantâneas (parser frontend, 0ms backend).
 * 2. Navegação por teclado (↑ ↓).
 * 3. clear() limpa query e sugestões.
 * 4. highlightedParts divide query corretamente.
 * 5. confirmSelection valida com backend (mock).
 * 6. confirmSelection dispara SelectByReferenceCommand.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSearchController } from "@/components/operator/SearchController";
import type { OperatorBookDTO, OperatorParseResultDTO } from "@/types";
import type { WorkspaceContext } from "@/components/operator/WorkspaceCommands";
import type { OperatorRef } from "@/stores";

// Mock books
const MOCK_BOOKS: OperatorBookDTO[] = [
  { id: 1, canonical: "Gênesis", aliases: ["gn", "gen"] },
  { id: 43, canonical: "João", aliases: ["jo", "joao"] },
  { id: 45, canonical: "Romanos", aliases: ["rm", "ro", "rom"] },
  { id: 66, canonical: "Apocalipse", aliases: ["ap", "apo", "apoc"] },
];

// Mock context
function makeMockContext(): WorkspaceContext & {
  _setSelectedCalls: OperatorRef[];
  _presentCalls: Array<{ book_id: number; chapter: number; verse: number; quick?: boolean }>;
} {
  const _setSelectedCalls: OperatorRef[] = [];
  const _presentCalls: Array<{ book_id: number; chapter: number; verse: number; quick?: boolean }> = [];
  let _selected: OperatorRef | null = null;

  return {
    get selected() { return _selected; },
    get presented() { return null; },
    get quickPresentation() { return false; },
    get books() { return MOCK_BOOKS; },
    getChapters: async () => [1, 2, 3],
    getVerses: async () => [1, 2, 3],
    getVerse: async (bookId: number, chapter: number, verse: number) => ({
      book_id: bookId, book: `Book${bookId}`, chapter, verse,
      reference: `Book${bookId} ${chapter}:${verse}`,
      text: "Texto", version: "ACF",
    }),
    presentVerse: async (req: { book_id: number; chapter: number; verse: number; quick?: boolean }) => {
      _presentCalls.push(req);
      return {
        ok: true, message: "OK", reference: "ref",
        book_id: req.book_id, chapter: req.chapter, verse: req.verse,
        version: "ACF", holyrics_status: "ok", latency_ms: 50,
      };
    },
    setSelected: (ref: OperatorRef | null) => {
      _setSelectedCalls.push(ref as OperatorRef);
      _selected = ref;
    },
    recordUsage: () => {},
    _setSelectedCalls,
    _presentCalls,
  } as any;
}

// Mock services
vi.mock("@/hooks", () => ({
  useServices: () => ({
    operator: {
      parseReference: vi.fn(async (query: string): Promise<OperatorParseResultDTO> => {
        // Simular validação: se contém "João 3:16", retorna ok.
        if (query.includes("João 3:16")) {
          return {
            ok: true, query, book_id: 43, book: "João",
            chapter: 3, verse: 16, reference: "João 3:16",
            text: "Porque Deus amou o mundo...", version: "ACF",
            reason: null,
          };
        }
        return { ok: false, query, reason: "parse_failed", book_id: null, book: null, chapter: null, verse: null, reference: null, text: null, version: null };
      }),
    },
  }),
}));

describe("useSearchController", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("inicia com query vazia e sem sugestões", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useSearchController(ctx, MOCK_BOOKS));
    expect(result.current.query).toBe("");
    expect(result.current.suggestions).toEqual([]);
    expect(result.current.selectedIndex).toBe(-1);
  });

  it("setQuery dispara sugestões instantâneas", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useSearchController(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("jo");
    });
    // Deve ter sugestões (Jó/João começam com "jo")
    expect(result.current.suggestions.length).toBeGreaterThan(0);
  });

  it("selectNext/selectPrev navega sugestões", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useSearchController(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("jo");
    });
    const count = result.current.suggestions.length;
    expect(count).toBeGreaterThan(0);

    act(() => {
      result.current.selectNext();
    });
    expect(result.current.selectedIndex).toBe(0);

    if (count > 1) {
      act(() => {
        result.current.selectNext();
      });
      expect(result.current.selectedIndex).toBe(1);

      act(() => {
        result.current.selectPrev();
      });
      expect(result.current.selectedIndex).toBe(0);
    }
  });

  it("selectPrev não vai abaixo de -1", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useSearchController(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("jo");
      result.current.selectPrev();
    });
    expect(result.current.selectedIndex).toBe(-1);
  });

  it("clear limpa query e sugestões", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useSearchController(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("joão 3:16");
      result.current.selectNext();
    });
    expect(result.current.query).not.toBe("");
    act(() => {
      result.current.clear();
    });
    expect(result.current.query).toBe("");
    expect(result.current.suggestions).toEqual([]);
    expect(result.current.selectedIndex).toBe(-1);
  });

  it("highlightedParts divide 'Romanos 8:28' corretamente", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useSearchController(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("Romanos 8:28");
    });
    expect(result.current.highlightedParts.book).toBe("Romanos");
    expect(result.current.highlightedParts.chapter).toBe("8");
    expect(result.current.highlightedParts.verse).toBe("28");
  });

  it("highlightedParts divide 'João 3' (sem versículo)", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useSearchController(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("João 3");
    });
    expect(result.current.highlightedParts.book).toBe("João");
    expect(result.current.highlightedParts.chapter).toBe("3");
    expect(result.current.highlightedParts.verse).toBe("");
  });

  it("highlightedParts para query parcial 'jo' (só book)", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useSearchController(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("jo");
    });
    expect(result.current.highlightedParts.book).toBe("jo");
    expect(result.current.highlightedParts.chapter).toBe("");
  });

  it("confirmSelection com query vazia retorna erro", async () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useSearchController(ctx, MOCK_BOOKS));
    let confirmResult: any;
    await act(async () => {
      confirmResult = await result.current.confirmSelection();
    });
    expect(confirmResult.ok).toBe(false);
    expect(confirmResult.reason).toBe("empty");
  });

  it("confirmSelection valida com backend e dispara SelectByReferenceCommand", async () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useSearchController(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("João 3:16");
    });
    let confirmResult: any;
    await act(async () => {
      confirmResult = await result.current.confirmSelection();
    });
    expect(confirmResult.ok).toBe(true);
    // Deve ter chamado setSelected (SelectByReferenceCommand).
    expect((ctx as any)._setSelectedCalls.length).toBeGreaterThan(0);
    expect((ctx as any)._setSelectedCalls[0]).toEqual({
      bookId: 43, chapter: 3, verse: 16,
    });
  });

  it("confirmSelection com referência inválida retorna erro", async () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useSearchController(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("xyz");
    });
    let confirmResult: any;
    await act(async () => {
      confirmResult = await result.current.confirmSelection();
    });
    expect(confirmResult.ok).toBe(false);
  });

  it("não consulta backend durante digitação (sugestões são locais)", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useSearchController(ctx, MOCK_BOOKS));
    // Digitar vários caracteres não deve chamar parseReference.
    // (apenas confirmSelection chama backend)
    act(() => {
      result.current.setQuery("j");
      result.current.setQuery("jo");
      result.current.setQuery("joã");
      result.current.setQuery("joão");
      result.current.setQuery("joão 3");
      result.current.setQuery("joão 3:16");
    });
    // Sugestões devem existir (do parser frontend).
    expect(result.current.suggestions.length).toBeGreaterThan(0);
    // isValidating deve ser false (não chamou backend).
    expect(result.current.isValidating).toBe(false);
  });
});
