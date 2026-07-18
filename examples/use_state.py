"""Exemplo de uso do gerenciador de estado da Bíblia.

Executa: python examples/use_state.py

Demonstra:
  1. Navegação básica (next/previous).
  2. Salto relativo (jump com amount).
  3. Jump de capítulo inteiro.
  4. Transição entre capítulos.
  5. Transição entre livros.
  6. Histórico de navegação.
  7. Persistência (save/load).
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.types import Intent, VerseRef
from estado.state import BibleState, BibleStructure, BibleStateManager


# Estrutura de exemplo (subset real).
STRUCTURE = BibleStructure(
    chapter_counts={1: 50, 43: 21, 44: 28, 45: 16, 66: 22},
    verse_counts={
        (1, 1): 31,
        (43, 3): 36,
        (43, 21): 25,
        (44, 1): 26,
        (45, 8): 39,
        (66, 22): 21,
    },
)

BOOK_NAMES = {1: "Gênesis", 43: "João", 44: "Atos", 45: "Romanos", 66: "Apocalipse"}


def main() -> None:
    print("=== Gerenciador de Estado da Bíblia ===\n")

    manager = BibleStateManager(
        structure=STRUCTURE,
        book_names=BOOK_NAMES,
        default_version="ACF",
    )

    # 1. Navegação básica
    print("--- Navegação básica ---\n")
    ref = manager.apply(Intent(action="show", book_id=43, book="João", chapter=3, verse=16))
    print(f"  show(João 3:16)   → {ref.reference}")

    ref = manager.apply(Intent(action="next", amount=1))
    print(f"  next(1)           → {ref.reference}")

    ref = manager.apply(Intent(action="previous", amount=1))
    print(f"  previous(1)       → {ref.reference}")

    ref = manager.apply(Intent(action="previous", amount=5))
    print(f"  previous(5)       → {ref.reference}")

    # 2. Salto relativo
    print("\n--- Salto relativo (jump com amount) ---\n")
    manager.set(VerseRef(book_id=43, book="João", chapter=3, verse=16))
    print(f"  set(João 3:16)")
    ref = manager.apply(Intent(action="jump", amount=3))
    print(f"  jump(+3)          → {ref.reference}")

    ref = manager.apply(Intent(action="jump", amount=-3))
    print(f"  jump(-3)          → {ref.reference}")

    # 3. Jump de capítulo inteiro
    print("\n--- Jump de capítulo inteiro ---\n")
    ref = manager.apply(Intent(action="jump"))
    print(f"  jump()            → {ref.reference} (verse={ref.verse})")

    # 4. Transição entre capítulos
    print("\n--- Transição entre capítulos ---\n")
    manager.set(VerseRef(book_id=43, book="João", chapter=3, verse=36))
    print(f"  set(João 3:36)    → último verso do cap. 3")
    # João 4 não está na estrutura de exemplo, então next() deve falhar.
    try:
        ref = manager.apply(Intent(action="next", amount=1))
        print(f"  next(1)           → {ref.reference}")
    except Exception as e:
        print(f"  next(1)           → StateError (esperado: {e})")

    # 5. Transição entre livros
    print("\n--- Transição entre livros ---\n")
    manager.set(VerseRef(book_id=43, book="João", chapter=21, verse=25))
    print(f"  set(João 21:25)   → último verso de João")
    ref = manager.apply(Intent(action="next", amount=1))
    print(f"  next(1)           → {ref.reference} (transição de livro!)")

    # 6. Histórico
    print("\n--- Histórico de navegação ---\n")
    hist = manager.history()
    for i, entry in enumerate(hist):
        print(f"  [{i}] {entry.action:10s} → {entry.ref.reference}")

    # 7. Persistência
    print("\n--- Persistência ---\n")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "state.json")
        m1 = BibleStateManager(
            structure=STRUCTURE, book_names=BOOK_NAMES, persist_path=path,
        )
        m1.set(VerseRef(book_id=45, book="Romanos", chapter=8, verse=28))
        m1.set_search("todas as coisas cooperam")
        print(f"  m1.set(Romanos 8:28) + search")
        print(f"  Arquivo: {path}")

        m2 = BibleStateManager(
            structure=STRUCTURE, book_names=BOOK_NAMES, persist_path=path,
        )
        m2.load()
        state = m2.current()
        print(f"  m2.load() → book_id={state.book_id}, ch={state.chapter}, v={state.verse}")
        print(f"  m2.last_search() = {m2.last_search()!r}")

    # 8. Limites
    print("\n--- Limites ---\n")
    manager.set(VerseRef(book_id=1, book="Gênesis", chapter=1, verse=1))
    print(f"  set(Gênesis 1:1)  → início da Bíblia")
    try:
        manager.apply(Intent(action="previous", amount=1))
    except Exception as e:
        print(f"  previous(1)       → StateError: {e}")

    manager.set(VerseRef(book_id=66, book="Apocalipse", chapter=22, verse=21))
    print(f"  set(Apoc 22:21)   → fim da Bíblia")
    try:
        manager.apply(Intent(action="next", amount=1))
    except Exception as e:
        print(f"  next(1)           → StateError: {e}")

    print("\n=== Concluído ===")


if __name__ == "__main__":
    main()
