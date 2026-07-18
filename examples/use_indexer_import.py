"""Exemplo de importação incremental do índice FTS5.

Executa: python examples/use_indexer_import.py
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

    print("=== Importação incremental ===")
    print(f"  Fonte: {source}")
    print(f"  DB:    {db}")

    # Primeira importação (cria a tabela).
    stats = indexer.build(source)
    print(f"\n  Após 1ª importação:")
    print(f"    Total de versículos: {stats.total_verses}")
    print(f"    Versões:             {stats.versions}")
    print(f"    Por versão:          {stats.verses_per_version}")
    print(f"    Pulados (inválidos): {stats.skipped_invalid}")
    print(f"    Duração:             {stats.duration_ms:.1f} ms")
    print(f"    Rebuilt:             {stats.rebuilt}")

    # Segunda importação incremental (dobra as linhas).
    stats2 = indexer.build(source)
    print(f"\n  Após 2ª importação (incremental):")
    print(f"    Total de versículos: {stats2.total_verses}")

    print("\n=== Concluído ===")


if __name__ == "__main__":
    main()
