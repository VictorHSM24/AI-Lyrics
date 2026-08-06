/**
 * Sprint 26 — Testes do ReferenceResolver.
 *
 * Valida:
 * D2: Abreviações (rm, rom, roma, roman, romanos)
 * D4: Sintaxe flexível (8:28, 8 28, 828)
 * D5: Heurística numérica (Romanos 32, 122, 1111, João 316, Lucas 248)
 * D6: Algoritmo de confiança (high/medium/low)
 */

import { describe, it, expect } from "vitest";
import { buildBookIndex, resolveReference } from "@/utils";
import type { OperatorBookDTO } from "@/types";

// Mock books com aliases reais do config/books.json (subconjunto).
const MOCK_BOOKS: OperatorBookDTO[] = [
  { id: 1, canonical: "Gênesis", aliases: ["gn", "gen", "genesis"] },
  { id: 6, canonical: "Josué", aliases: ["js", "jo", "josue"] },
  { id: 8, canonical: "Rute", aliases: ["rt", "ru", "rute"] },
  { id: 11, canonical: "1 Reis", aliases: ["1 reis", "i reis", "1rs", "1 re"] },
  { id: 12, canonical: "2 Reis", aliases: ["2 reis", "ii reis", "2rs", "2 re"] },
  { id: 18, canonical: "Jó", aliases: ["jo", "job"] },
  { id: 19, canonical: "Salmos", aliases: ["sl", "sal", "salmo", "salmos", "psalm"] },
  { id: 42, canonical: "Lucas", aliases: ["lc", "lu", "luk", "lucas"] },
  { id: 43, canonical: "João", aliases: ["jo", "joao", "joão"] },
  { id: 45, canonical: "Romanos", aliases: ["rm", "ro", "rom", "romanos"] },
  { id: 46, canonical: "1 Coríntios", aliases: ["1co", "1cor", "1 cor", "1 coríntios"] },
  { id: 55, canonical: "2 Timóteo", aliases: ["2tm", "2 tim", "2 timóteo"] },
  { id: 66, canonical: "Apocalipse", aliases: ["ap", "apo", "apoc", "apocalipse"] },
];

const index = buildBookIndex(MOCK_BOOKS);

describe("ReferenceResolver — D2: Abreviações", () => {
  it("rm → Romanos 8:28", () => {
    const r = resolveReference("rm 8:28", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations[0].ref.bookName).toBe("Romanos");
    expect(r.interpretations[0].ref.chapter).toBe(8);
    expect(r.interpretations[0].ref.verse).toBe(28);
  });

  it("rom → Romanos 8:28", () => {
    const r = resolveReference("rom 8:28", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations[0].ref.bookName).toBe("Romanos");
  });

  it("roma → Romanos 8:28", () => {
    const r = resolveReference("roma 8:28", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations[0].ref.bookName).toBe("Romanos");
  });

  it("roman → Romanos 8:28", () => {
    const r = resolveReference("roman 8:28", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations[0].ref.bookName).toBe("Romanos");
  });

  it("romanos → Romanos 8:28", () => {
    const r = resolveReference("romanos 8:28", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations[0].ref.bookName).toBe("Romanos");
  });

  it("1co → 1 Coríntios 13:1", () => {
    const r = resolveReference("1co 13:1", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations[0].ref.bookName).toBe("1 Coríntios");
  });

  it("2tm → 2 Timóteo 4:7", () => {
    const r = resolveReference("2tm 4:7", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations[0].ref.bookName).toBe("2 Timóteo");
  });

  it("II Reis 2 → 2 Reis 2 (numeral romano)", () => {
    const r = resolveReference("II Reis 2", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations[0].ref.bookName).toBe("2 Reis");
    expect(r.interpretations[0].ref.chapter).toBe(2);
  });
});

describe("ReferenceResolver — D4: Sintaxe flexível", () => {
  it("Romanos 8:28 (tradicional)", () => {
    const r = resolveReference("Romanos 8:28", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations[0].ref.chapter).toBe(8);
    expect(r.interpretations[0].ref.verse).toBe(28);
  });

  it("Romanos 8 28 (sem dois pontos)", () => {
    const r = resolveReference("Romanos 8 28", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations[0].ref.chapter).toBe(8);
    expect(r.interpretations[0].ref.verse).toBe(28);
  });

  it("Rm 828 (compacto)", () => {
    const r = resolveReference("Rm 828", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations[0].ref.chapter).toBe(8);
    expect(r.interpretations[0].ref.verse).toBe(28);
  });

  it("Romanos 828 (nome completo compacto)", () => {
    const r = resolveReference("Romanos 828", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations[0].ref.chapter).toBe(8);
    expect(r.interpretations[0].ref.verse).toBe(28);
  });

  it("Romanos 8 (apenas capítulo, verse=null)", () => {
    const r = resolveReference("Romanos 8", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations[0].ref.chapter).toBe(8);
    expect(r.interpretations[0].ref.verse).toBeNull();
  });
});

describe("ReferenceResolver — D5: Heurística numérica", () => {
  it("Caso 1: Romanos 32 → 3:2 (alta confiança, 32 > max_chapter=16)", () => {
    const r = resolveReference("Romanos 32", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations).toHaveLength(1);
    expect(r.interpretations[0].ref.chapter).toBe(3);
    expect(r.interpretations[0].ref.verse).toBe(2);
  });

  it("Caso 3: Romanos 1111 → 11:11 (1:111 filtrado por verse > 99)", () => {
    const r = resolveReference("Romanos 1111", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations).toHaveLength(1);
    expect(r.interpretations[0].ref.chapter).toBe(11);
    expect(r.interpretations[0].ref.verse).toBe(11);
  });

  it("Caso 4: João 316 → 3:16 (31 > max_chapter=21)", () => {
    const r = resolveReference("João 316", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations).toHaveLength(1);
    expect(r.interpretations[0].ref.chapter).toBe(3);
    expect(r.interpretations[0].ref.verse).toBe(16);
  });

  it("Caso 5: Lucas 248 → ambíguo (2:48 e 24:8 ambos válidos)", () => {
    const r = resolveReference("Lucas 248", index);
    expect(r.confidence).toBe("medium");
    expect(r.interpretations.length).toBeGreaterThanOrEqual(2);
    const chapters = r.interpretations.map((i) => i.ref.chapter);
    expect(chapters).toContain(2);
    expect(chapters).toContain(24);
  });
});

describe("ReferenceResolver — D6: Algoritmo de confiança", () => {
  it("Alta confiança: única interpretação válida", () => {
    const r = resolveReference("Rm 8:28", index);
    expect(r.confidence).toBe("high");
    expect(r.interpretations).toHaveLength(1);
    expect(r.error).toBeNull();
  });

  it("Média confiança: múltiplas interpreções válidas", () => {
    const r = resolveReference("Lucas 248", index);
    expect(r.confidence).toBe("medium");
    expect(r.interpretations.length).toBeGreaterThan(1);
    expect(r.error).toBeNull();
  });

  it("Baixa confiança: livro não encontrado", () => {
    const r = resolveReference("xyz 1:1", index);
    expect(r.confidence).toBe("low");
    expect(r.interpretations).toHaveLength(0);
    expect(r.error).toBe("book_not_found");
  });

  it("Baixa confiança: query vazia", () => {
    const r = resolveReference("", index);
    expect(r.confidence).toBe("low");
    expect(r.error).toBe("empty");
  });

  it("Baixa confiança: sem parte numérica", () => {
    const r = resolveReference("Romanos", index);
    expect(r.confidence).toBe("low");
    expect(r.error).toBe("book_not_found");
  });

  it("Interpretações ordenadas por chapter descendente (medium)", () => {
    const r = resolveReference("Lucas 248", index);
    expect(r.confidence).toBe("medium");
    expect(r.interpretations[0].ref.chapter).toBeGreaterThan(
      r.interpretations[1].ref.chapter,
    );
  });
});
