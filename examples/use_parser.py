"""Exemplo de uso do parser determinístico.

Executa: python examples/use_parser.py

Demonstra:
  1. Referências diretas (com e sem marcadores).
  2. Referências compactas.
  3. Números por extenso.
  4. Ordinais e romanos.
  5. Navegação (próximo, anterior, volta, mais, continua).
  6. Comandos semânticos → uncertain (encaminha ao LLM).
  7. Pregação → none.
  8. Confiança do parser.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from estado.state import BibleState
from parser.books import load_parser_books
from parser.parser import Parser


def main() -> None:
    books = load_parser_books("config/books.json")
    parser = Parser(books=books)

    print("=== Parser Determinístico de Comandos Bíblicos ===\n")

    # 1. Referências diretas com marcadores
    print("--- Referências com marcadores ---\n")
    cases = [
        "joao capitulo 3 versiculo 16",
        "vamos abrir em joao capitulo 3 versiculo 16",
        "joao cap 3 vers 16",
    ]
    for text in cases:
        r = parser.parse(text)
        print(f"  {text!r:55s} → action={r.action}, book={r.book}, "
              f"ch={r.chapter}, v={r.verse}, c={r.confidence:.2f}")

    # 2. Referências compactas
    print("\n--- Referências compactas ---\n")
    cases = ["joao 3 16", "romanos 8 28", "primeira corintios 13", "joao 3"]
    for text in cases:
        r = parser.parse(text)
        print(f"  {text!r:35s} → action={r.action}, book={r.book}, "
              f"ch={r.chapter}, v={r.verse}, c={r.confidence:.2f}")

    # 3. Números por extenso
    print("\n--- Números por extenso ---\n")
    cases = [
        "romanos oito vinte e oito",
        "primeira corintios treze",
        "joao tres dezesseis",
        "salmos cento e cinquenta",
    ]
    for text in cases:
        r = parser.parse(text)
        print(f"  {text!r:40s} → action={r.action}, book={r.book}, "
              f"ch={r.chapter}, v={r.verse}")

    # 4. Ordinais e romanos
    print("\n--- Ordinais e romanos ---\n")
    cases = [
        "primeira corintios 13",
        "i corintios 13",
        "segunda pedro 1",
        "ii pedro 1",
        "terceira joao 1",
        "iii joao 1",
    ]
    for text in cases:
        r = parser.parse(text)
        print(f"  {text!r:30s} → book={r.book}, ch={r.chapter}")

    # 5. Navegação
    print("\n--- Navegação ---\n")
    cases = [
        "proximo",
        "proximo 5",
        "anterior",
        "anterior 3",
        "volta",
        "volta dois",
        "mais tres",
        "pula 2",
        "continua nesse capitulo",
        "ainda nesse texto",
    ]
    for text in cases:
        r = parser.parse(text)
        amt = f", amount={r.amount}" if r.amount is not None else ""
        print(f"  {text!r:35s} → action={r.action}{amt}, c={r.confidence:.2f}")

    # 6. Comandos semânticos → uncertain
    print("\n--- Comandos semânticos (→ uncertain, encaminha ao LLM) ---\n")
    cases = [
        "aquele versiculo da fe",
        "aquele texto que fala que deus amou o mundo",
        "abre aquele texto",
        "mostrar aquele versiculo da fe",
    ]
    for text in cases:
        r = parser.parse(text)
        print(f"  {text!r:55s} → action={r.action}, c={r.confidence:.2f}")

    # 7. Pregação → none
    print("\n--- Pregação (→ none, não é comando) ---\n")
    cases = [
        "e entao jesus disse aos discipulos",
        "o ceu e azul",
        "",
    ]
    for text in cases:
        r = parser.parse(text)
        print(f"  {text!r:45s} → action={r.action}")

    # 8. Uso de BibleState para contexto
    print("\n--- Uso de BibleState (contexto) ---\n")
    state = BibleState(book_id=43, chapter=3, verse=16, version="ACF")
    r = parser.parse("joao versiculo 16", state=state)
    print(f"  state=João 3:16, input='joao versiculo 16'")
    print(f"  → action={r.action}, book={r.book}, ch={r.chapter}, v={r.verse}")
    print(f"  (chapter veio do state)")

    # 9. Sinônimos
    print("\n--- Sinônimos de livros ---\n")
    cases = [
        "sao joao 3 16",
        "evangelho de joao 3 16",
        "primeira carta aos corintios 13",
        "gn 1 1",
        "sl 23",
        "ap 22 21",
    ]
    for text in cases:
        r = parser.parse(text)
        print(f"  {text!r:40s} → book={r.book}, ch={r.chapter}, v={r.verse}")

    # 10. Ambiguidade de livro (confiança reduzida)
    print("\n--- Ambiguidade (confiança reduzida) ---\n")
    r = parser.parse("jo 3 16")
    print(f"  'jo 3 16' → book={r.book}, c={r.confidence:.3f} (0.95 * 0.5 = 0.475)")

    print("\n=== Concluído ===")


if __name__ == "__main__":
    main()
