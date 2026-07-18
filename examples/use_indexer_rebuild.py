"""Exemplo de rebuild completo do índice FTS5.

Executa: python examples/use_indexer_rebuild.py

Demonstra:
  1. Importação inicial.
  2. Corrupção simulada (importação incremental duplicada).
  3. Rebuild completo (drop + create + import).
  4. Verificação de consistência.
  5. Adição de nova versão.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from busca import BibleIndexer


def main() -> None:
    source = "data/bible_source.json"
    db = "data/bible.pt-br.sqlite"

    indexer = BibleIndexer(db)

    print("=== Rebuild completo do índice ===\n")

    # 1. Importação inicial.
    print("[1] Importação inicial:")
    stats = indexer.build(source)
    print(f"    Total: {stats.total_verses}, Versões: {stats.versions}")

    # 2. Simular corrupção (importação incremental duplicada).
    print("\n[2] Simulando corrupção (importação duplicada):")
    indexer.build(source)
    stats_dup = indexer.get_stats()
    print(f"    Total: {stats_dup.total_verses} (esperado: o dobro do inicial)")

    # 3. Rebuild completo.
    print("\n[3] Rebuild completo (drop + create + import):")
    stats_rb = indexer.rebuild(source)
    print(f"    Total: {stats_rb.total_verses}")
    print(f"    Versões: {stats_rb.versions}")
    print(f"    Por versão: {stats_rb.verses_per_version}")
    print(f"    Rebuilt: {stats_rb.rebuilt}")
    print(f"    Duração: {stats_rb.duration_ms:.1f} ms")

    # 4. Verificação de consistência.
    print("\n[4] Verificação de consistência:")
    final_stats = indexer.get_stats()
    assert final_stats.total_verses == stats_rb.total_verses
    assert final_stats.versions == stats_rb.versions
    print(f"    OK — {final_stats.total_verses} versículos, versões={final_stats.versions}")

    # 5. Adicionar versão NVI (já existe no source, mas demonstra add_version).
    print("\n[5] Adicionar versão NVI (filtrada da fonte):")
    stats_add = indexer.add_version(source, version="NVI")
    print(f"    Total após add: {stats_add.total_verses}")
    print(f"    NVI: {stats_add.verses_per_version.get('NVI', 0)} versículos")

    # 6. Rebuild final para estado limpo.
    print("\n[6] Rebuild final para estado limpo:")
    stats_final = indexer.rebuild(source)
    print(f"    Total: {stats_final.total_verses}")
    print(f"    Versões: {stats_final.versions}")

    print("\n=== Concluído ===")


if __name__ == "__main__":
    main()
