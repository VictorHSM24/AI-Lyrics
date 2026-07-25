"""Sprint 22.0 — Benchmark de estratégias de query FTS5."""
import sys
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

import sqlite3
from config.loader import load_books
from knowledge import warmup_bible_retriever
from knowledge.bible_retriever import _normalize_text, _bm25_to_score

def main() -> int:
    output_lines = []
    def log(msg: str = "") -> None:
        print(msg)
        output_lines.append(msg)

    book_table = load_books("config/books.json")
    retriever, stats = warmup_bible_retriever(
        sources_dir="data/sources",
        book_table=book_table,
        top_k_default=20,
    )

    queries = [
        "O Senhor te abençoe e te guarde",
        "Porque Deus amou o mundo de tal maneira",
        "O Senhor é meu pastor nada me faltará",
        "Tudo posso naquele que me fortalece",
        "No princípio criou Deus os céus e a terra",
    ]

    conn = retriever._mem_conn

    for query in queries:
        norm = _normalize_text(query)
        terms = norm.split()

        # Estratégia 1: OR (atual)
        fts_or = " OR ".join(f'"{t}"' for t in terms if t)

        # Estratégia 2: AND (padrão FTS5)
        fts_and = " ".join(f'"{t}"' for t in terms if t)

        # Estratégia 3: NEAR (proximidade)
        fts_near = " NEAR ".join(f'"{t}"' for t in terms if t)

        for name, fts_query in [("OR", fts_or), ("AND", fts_and), ("NEAR", fts_near)]:
            t0 = time.monotonic()
            try:
                cur = conn.execute(
                    "SELECT book_ref_id, chapter, verse, version, text, "
                    "bm25(verses) AS bm25, rank FROM verses "
                    "WHERE verses MATCH ? ORDER BY rank LIMIT 80",
                    (fts_query,),
                )
                rows = cur.fetchall()
                elapsed = (time.monotonic() - t0) * 1000.0
                log(f"  {name:6s} | {len(rows):3d} results | {elapsed:6.1f}ms | {query[:40]!r}")
            except Exception as e:
                log(f"  {name:6s} | ERROR: {e}")

    retriever.close()
    out = project_root / "_diag_sprint22_0_bench.txt"
    out.write_text("\n".join(output_lines), encoding="utf-8")
    return 0

if __name__ == "__main__":
    sys.exit(main())
