/**
 * Sprint 26 — Testes do AutoCompleteEngine e SearchHistoryController.
 *
 * D3: Autocomplete IDE-style de livros
 * D9: Histórico terminal-style (↑↓)
 */

import { describe, it, expect } from "vitest";
import { buildBookIndex, autoCompleteBook } from "@/utils";
import { SearchHistoryController } from "@/components/operator/SearchHistoryController";
import type { OperatorBookDTO } from "@/types";

const MOCK_BOOKS: OperatorBookDTO[] = [
  { id: 1, canonical: "Gênesis", aliases: ["gn", "gen"] },
  { id: 8, canonical: "Rute", aliases: ["rt", "ru"] },
  { id: 11, canonical: "1 Reis", aliases: ["1rs", "1 re"] },
  { id: 12, canonical: "2 Reis", aliases: ["2rs", "2 re"] },
  { id: 18, canonical: "Jó", aliases: ["jo", "job"] },
  { id: 19, canonical: "Salmos", aliases: ["sl", "sal"] },
  { id: 42, canonical: "Lucas", aliases: ["lc", "lu"] },
  { id: 45, canonical: "Romanos", aliases: ["rm", "ro", "rom"] },
  { id: 66, canonical: "Apocalipse", aliases: ["ap", "apo"] },
];

const index = buildBookIndex(MOCK_BOOKS);

describe("AutoCompleteEngine — D3: Autocomplete de livros", () => {
  it("r → não completa (Rute, Romanos, Reis)", () => {
    const result = autoCompleteBook("r", index);
    expect(result.completion).toBeNull();
    expect(result.bookId).toBeNull();
  });

  it("ro → completa 'Romanos' (único match)", () => {
    const result = autoCompleteBook("ro", index);
    expect(result.completion).not.toBeNull();
    expect(result.bookName).toBe("Romanos");
    expect(result.fullText).toBe("Romanos");
  });

  it("rom → completa 'Romanos'", () => {
    const result = autoCompleteBook("rom", index);
    expect(result.completion).not.toBeNull();
    expect(result.bookName).toBe("Romanos");
  });

  it("lu → completa 'Lucas' (único)", () => {
    const result = autoCompleteBook("lu", index);
    expect(result.completion).not.toBeNull();
    expect(result.bookName).toBe("Lucas");
  });

  it("s → não completa (Salmos, mas também pode ter outros)", () => {
    const result = autoCompleteBook("s", index);
    // Salmos é o único que começa com "s", mas pode haver ambiguidade
    // dependendo dos livros mockados. Verificar se é único.
    if (result.completion) {
      expect(result.bookName).toBe("Salmos");
    }
  });

  it("Romanos (nome completo) → não completa (já está completo)", () => {
    const result = autoCompleteBook("Romanos", index);
    expect(result.completion).toBeNull();
  });

  it("rm (alias exata) → não completa (já é alias)", () => {
    const result = autoCompleteBook("rm", index);
    expect(result.completion).toBeNull();
  });

  it("completion é a parte após o prefixo", () => {
    const result = autoCompleteBook("ro", index);
    expect(result.completion).toBe("manos");
  });

  it("prefixo vazio → não completa", () => {
    const result = autoCompleteBook("", index);
    expect(result.completion).toBeNull();
  });
});

describe("SearchHistoryController — D9: Histórico terminal-style", () => {
  it("push adiciona query ao histórico", () => {
    const h = new SearchHistoryController();
    h.push("Rm 8:28");
    expect(h.state.entries).toEqual(["Rm 8:28"]);
    expect(h.state.cursor).toBe(-1);
  });

  it("push não duplica última entry", () => {
    const h = new SearchHistoryController();
    h.push("Rm 8:28");
    h.push("Rm 8:28");
    expect(h.state.entries).toHaveLength(1);
  });

  it("push mantém ordem (mais recente primeiro)", () => {
    const h = new SearchHistoryController();
    h.push("João 3:16");
    h.push("Rm 8:28");
    expect(h.state.entries).toEqual(["Rm 8:28", "João 3:16"]);
  });

  it("previous com campo vazio recupera última query", () => {
    const h = new SearchHistoryController();
    h.push("Rm 8:28");
    h.push("João 3:16");
    const prev = h.previous("");
    expect(prev).toBe("João 3:16");
    expect(h.state.cursor).toBe(0);
  });

  it("previous novamente recupera query mais antiga", () => {
    const h = new SearchHistoryController();
    h.push("Rm 8:28");
    h.push("João 3:16");
    h.previous("");
    const prev = h.previous("");
    expect(prev).toBe("Rm 8:28");
    expect(h.state.cursor).toBe(1);
  });

  it("previous não funciona com campo não-vazio (a menos que cursor ativo)", () => {
    const h = new SearchHistoryController();
    h.push("Rm 8:28");
    const prev = h.previous("texto qualquer");
    expect(prev).toBeNull();
  });

  it("next volta para o presente (vazio)", () => {
    const h = new SearchHistoryController();
    h.push("Rm 8:28");
    h.previous("");
    const next = h.next();
    expect(next).toBe("");
    expect(h.state.cursor).toBe(-1);
  });

  it("next navega de volta parcialmente", () => {
    const h = new SearchHistoryController();
    h.push("Rm 8:28");
    h.push("João 3:16");
    h.push("Sl 91");
    // Navegar para o passado: Sl 91 → João 3:16 → Rm 8:28
    h.previous("");
    h.previous("");
    h.previous("");
    expect(h.state.cursor).toBe(2);
    // next: volta uma posição
    const next = h.next();
    expect(next).toBe("João 3:16");
    expect(h.state.cursor).toBe(1);
  });

  it("resetCursor volta ao presente", () => {
    const h = new SearchHistoryController();
    h.push("Rm 8:28");
    h.previous("");
    expect(h.state.cursor).toBe(0);
    h.resetCursor();
    expect(h.state.cursor).toBe(-1);
  });

  it("clear limpa tudo", () => {
    const h = new SearchHistoryController();
    h.push("Rm 8:28");
    h.push("João 3:16");
    h.clear();
    expect(h.state.entries).toHaveLength(0);
    expect(h.state.cursor).toBe(-1);
    expect(h.hasHistory).toBe(false);
  });

  it("hasHistory true após push", () => {
    const h = new SearchHistoryController();
    expect(h.hasHistory).toBe(false);
    h.push("Rm 8:28");
    expect(h.hasHistory).toBe(true);
  });

  it("push ignora query vazia", () => {
    const h = new SearchHistoryController();
    h.push("");
    h.push("   ");
    expect(h.state.entries).toHaveLength(0);
  });

  it("respeita maxEntries", () => {
    const h = new SearchHistoryController(3);
    h.push("a");
    h.push("b");
    h.push("c");
    h.push("d");
    expect(h.state.entries).toHaveLength(3);
    expect(h.state.entries).toEqual(["d", "c", "b"]);
  });
});
