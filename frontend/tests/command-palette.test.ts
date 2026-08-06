/**
 * Sprint 26 — Testes do useCommandPalette.
 *
 * D7: Enter inteligente (apresenta direto se alta confiança)
 * D8: Fluxo Zero Mouse (clear + refocus após apresentação)
 * D9: Histórico da busca (push após confirm)
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useCommandPalette } from "@/components/operator/useCommandPalette";
import type { OperatorBookDTO, OperatorParseResultDTO } from "@/types";
import type { WorkspaceContext } from "@/components/operator/WorkspaceCommands";
import type { OperatorRef } from "@/stores";

const MOCK_BOOKS: OperatorBookDTO[] = [
  { id: 42, canonical: "Lucas", aliases: ["lc", "lu", "lucas"] },
  { id: 43, canonical: "João", aliases: ["jo", "joao", "joão"] },
  { id: 45, canonical: "Romanos", aliases: ["rm", "ro", "rom", "romanos"] },
  { id: 66, canonical: "Apocalipse", aliases: ["ap", "apo", "apoc"] },
];

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

vi.mock("@/hooks", () => ({
  useServices: () => ({
    operator: {
      parseReference: vi.fn(async (query: string): Promise<OperatorParseResultDTO> => {
        // Simular validação backend: aceita qualquer coisa com formato válido.
        const match = /^(.+?)\s+(\d+):(\d+)$/.exec(query);
        if (match) {
          return {
            ok: true, query, book_id: 45, book: match[1],
            chapter: parseInt(match[2], 10), verse: parseInt(match[3], 10),
            reference: query, text: "Texto do versículo", version: "ACF",
            reason: null,
          };
        }
        return { ok: false, query, reason: "parse_failed", book_id: null, book: null, chapter: null, verse: null, reference: null, text: null, version: null };
      }),
    },
  }),
}));

describe("useCommandPalette — D7: Enter inteligente", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("inicia com query vazia e sem resolução", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    expect(result.current.query).toBe("");
    expect(result.current.resolution).toBeNull();
    expect(result.current.isBusy).toBe(false);
  });

  it("setQuery dispara resolução instantânea (sem backend)", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("Rm 8:28");
    });
    expect(result.current.resolution).not.toBeNull();
    expect(result.current.resolution?.confidence).toBe("high");
    expect(result.current.resolution?.interpretations[0].ref.bookName).toBe("Romanos");
  });

  it("alta confiança: confirm apresenta direto (SelectByReference + PresentVerse)", async () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("Rm 8:28");
    });
    expect(result.current.resolution?.confidence).toBe("high");

    let outcome: any;
    await act(async () => {
      outcome = await result.current.confirm();
    });
    expect(outcome.ok).toBe(true);
    expect(outcome.reference).toBe("Romanos 8:28");
    // Deve ter chamado setSelected (SelectByReferenceCommand).
    expect((ctx as any)._setSelectedCalls.length).toBeGreaterThan(0);
    // Deve ter chamado presentVerse (PresentVerseCommand).
    expect((ctx as any)._presentCalls.length).toBeGreaterThan(0);
  });

  it("D8: após confirm, campo limpa (pronto para próxima)", async () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("Rm 8:28");
    });
    await act(async () => {
      await result.current.confirm();
    });
    expect(result.current.query).toBe("");
    expect(result.current.resolution).toBeNull();
  });

  it("D8: após confirm, lastPresentedRef é setado (para refocus)", async () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("Rm 8:28");
    });
    await act(async () => {
      await result.current.confirm();
    });
    expect(result.current.lastPresentedRef).toBe("Romanos 8:28");
  });

  it("média confiança: confirm usa interpretação selecionada", async () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("Lucas 248");
    });
    expect(result.current.resolution?.confidence).toBe("medium");
    expect(result.current.resolution?.interpretations.length).toBeGreaterThan(1);

    // Selecionar segunda interpretação.
    act(() => {
      result.current.selectNextInterpretation();
    });
    expect(result.current.selectedInterpretation).toBe(1);

    let outcome: any;
    await act(async () => {
      outcome = await result.current.confirm();
    });
    expect(outcome.ok).toBe(true);
  });

  it("baixa confiança: confirm retorna erro sem apresentar", async () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("xyz 1:1");
    });
    expect(result.current.resolution?.confidence).toBe("low");

    let outcome: any;
    await act(async () => {
      outcome = await result.current.confirm();
    });
    expect(outcome.ok).toBe(false);
    expect((ctx as any)._presentCalls.length).toBe(0);
  });

  it("confirm com query vazia retorna erro", async () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    let outcome: any;
    await act(async () => {
      outcome = await result.current.confirm();
    });
    expect(outcome.ok).toBe(false);
    expect(outcome.reason).toBe("empty");
  });
});

describe("useCommandPalette — D9: Histórico da busca", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("após confirm, query é adicionada ao histórico", async () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("Rm 8:28");
    });
    await act(async () => {
      await result.current.confirm();
    });
    // Campo vazio + historyPrevious deve retornar "Rm 8:28".
    const prev = result.current.historyPrevious();
    expect(prev).toBe("Rm 8:28");
  });

  it("múltiplas confirms acumulam no histórico", async () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    act(() => result.current.setQuery("Rm 8:28"));
    await act(async () => await result.current.confirm());
    act(() => result.current.setQuery("João 3:16"));
    await act(async () => await result.current.confirm());

    // historyPrevious (campo vazio) → mais recente (João 3:16).
    const prev1 = result.current.historyPrevious();
    expect(prev1).toBe("João 3:16");
    // previous novamente → Rm 8:28.
    const prev2 = result.current.historyPrevious();
    expect(prev2).toBe("Rm 8:28");
  });
});

describe("useCommandPalette — D3: Autocomplete", () => {
  it("autocomplete sugere completion quando livro é único", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("ro");
    });
    expect(result.current.autoComplete).not.toBeNull();
    expect(result.current.autoComplete?.bookName).toBe("Romanos");
    expect(result.current.autoComplete?.completion).toBe("manos");
  });

  it("autocomplete não sugere quando há dígitos", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("Romanos 8");
    });
    expect(result.current.autoComplete).toBeNull();
  });

  it("acceptAutoComplete preenche o nome completo", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("ro");
    });
    act(() => {
      result.current.acceptAutoComplete();
    });
    expect(result.current.query).toBe("Romanos ");
  });
});

describe("useCommandPalette — Navegação de interpretações", () => {
  it("selectNextInterpretation / selectPrevInterpretation", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("Lucas 248");
    });
    expect(result.current.resolution?.confidence).toBe("medium");
    expect(result.current.selectedInterpretation).toBe(0);

    act(() => result.current.selectNextInterpretation());
    expect(result.current.selectedInterpretation).toBe(1);

    act(() => result.current.selectPrevInterpretation());
    expect(result.current.selectedInterpretation).toBe(0);
  });

  it("selectNextInterpretation não excede limite", () => {
    const ctx = makeMockContext();
    const { result } = renderHook(() => useCommandPalette(ctx, MOCK_BOOKS));
    act(() => {
      result.current.setQuery("Lucas 248");
    });
    const max = result.current.resolution?.interpretations.length ?? 0;
    for (let i = 0; i < max + 5; i++) {
      act(() => result.current.selectNextInterpretation());
    }
    expect(result.current.selectedInterpretation).toBe(max - 1);
  });
});
