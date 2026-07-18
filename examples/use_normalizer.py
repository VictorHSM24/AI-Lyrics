"""Exemplo de uso do normalizador PT-BR.

Executa: python examples/use_normalizer.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser.normalizer import Normalizer


def main() -> None:
    norm = Normalizer()

    examples = [
        # Exemplos do enunciado
        "João capítulo três versículo dezesseis",
        "Primeira carta aos Coríntios capítulo treze",
        "Romanos VIII vinte e oito",
        "João   3 : 16",

        # Variações adicionais
        "Segunda Pedro capítulo um versículo cinco",
        "Salmos cento e cinquenta",
        "I Coríntios treze",
        "III João versículo quatro",
        "cap. 3 vers. 16",
        "Romanos 8:28",
        "primeira carta aos coríntios capítulo treze",
        "Salmos XXIII versículo um",
        "vinte e oito Romanos oito",
    ]

    print("=== Normalizador PT-BR ===\n")
    for text in examples:
        result = norm.normalize(text)
        print(f"  {text!r}")
        print(f"  → {result!r}")
        print()

    # Demonstrar métodos individuais
    print("=== Métodos individuais ===\n")

    print("extenso_to_digit:")
    for token in ["treze", "vinte e oito", "cento e cinquenta", "catorze", "joao"]:
        val = norm.extenso_to_digit(token)
        print(f"  {token!r:30s} → {val}")

    print("\nordinal_to_int:")
    for token in ["primeiro", "primeira", "segundo", "terceira", "quarto", "joao"]:
        val = norm.ordinal_to_int(token)
        print(f"  {token!r:30s} → {val}")

    print("\nroman_to_int:")
    for token in ["i", "ii", "iii", "v", "viii", "x", "xii", "c", "cl", "joao"]:
        val = norm.roman_to_int(token)
        print(f"  {token!r:30s} → {val}")

    print("\n=== Concluído ===")


if __name__ == "__main__":
    main()
