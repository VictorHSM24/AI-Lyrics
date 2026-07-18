"""Exemplo de uso do reconhecedor de livros bíblicos.

Executa: python examples/use_books.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser.books import ParserBookTable, load_parser_books


def main() -> None:
    table = load_parser_books("config/books.json")

    print("=== Reconhecedor de Livros Bíblicos ===\n")

    # Exemplos do enunciado
    examples = [
        "joao",
        "jo",
        "1 corintios",
        "primeira corintios",
        "i corintios",
        "ii corintios",
        "primeira carta aos corintios",
        "canticos",
        "apocalipse",
    ]

    print("--- Exemplos do enunciado ---\n")
    for text in examples:
        r = table.resolve(text)
        if r:
            amb = " [AMBÍGUO]" if r.ambiguous else ""
            print(f"  {text!r:40s} → {r.book.canonical!r:20s} "
                  f"(id={r.book.id}, conf={r.confidence:.1f}){amb}")
        else:
            print(f"  {text!r:40s} → NÃO ENCONTRADO")

    # Longest-match
    print("\n--- Longest-match (1 João vs João) ---\n")
    for text in ["joao", "1 joao", "primeiro joao", "ii joao", "terceiro joao"]:
        r = table.resolve(text)
        if r:
            print(f"  {text!r:30s} → {r.book.canonical!r:15s} (id={r.book.id})")

    # Ambiguidades
    print("\n--- Ambiguidades e prioridade ---\n")
    for text in ["jo", "hb", "ez"]:
        r = table.resolve(text)
        if r:
            print(f"  {text!r:10s} → {r.book.canonical!r:15s} (id={r.book.id}, "
                  f"conf={r.confidence:.1f}, ambiguous={r.ambiguous})")

    print(f"\n  Aliases ambíguas: {table.ambiguous_aliases()}")

    # Abreviações
    print("\n--- Abreviações comuns ---\n")
    for text in ["gn", "ex", "sl", "mt", "mc", "lc", "rm", "1co", "2co", "ap"]:
        r = table.resolve(text)
        if r:
            print(f"  {text!r:10s} → {r.book.canonical!r:20s} (id={r.book.id})")

    # Romanos e ordinais
    print("\n--- Romanos e ordinais (via Normalizer) ---\n")
    for text in ["I Coríntios", "II Pedro", "III João", "primeira pedro", "segundo reis"]:
        r = table.resolve(text)
        if r:
            print(f"  {text!r:25s} → {r.book.canonical!r:15s} (id={r.book.id})")

    # Em contexto (frases completas)
    print("\n--- Em contexto (frases) ---\n")
    for text in [
        "joao capitulo 3 versiculo 16",
        "primeira carta aos corintios capitulo 13",
        "romanos 8 28",
        "mostrar salmos 23",
    ]:
        r = table.resolve(text)
        if r:
            print(f"  {text!r:50s} → {r.book.canonical!r:15s} "
                  f"(id={r.book.id}, start={r.start}, end={r.end})")

    print("\n=== Concluído ===")


if __name__ == "__main__":
    main()
