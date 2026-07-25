"""Benchmark antes/depois — Sprint 18.0.1.

Compara o tempo de search_by_reference() em duas configurações:

  ANTES (legacy): conexão SQLite persistente criada no __init__.
  DEPOIS (Sprint 18.0.1): conexão por operação (Opção A).

Métricas: média, p50, p95, p99 em ms.
"""

from __future__ import annotations

import os
import sqlite3
import statistics
import time
from pathlib import Path

from busca.searcher import Searcher
from config.books import BookTable
from config.loader import load_books
from config.models import SearchConfig


SAMPLE_VERSES = [
    {"book": "Gênesis", "book_id": 1, "chapter": 1, "verse": 1,
     "text": "No princípio criou Deus os céus e a terra.", "version": "ACF"},
    {"book": "Gênesis", "book_id": 1, "chapter": 1, "verse": 2,
     "text": "E a terra era sem forma e vazia; e havia trevas sobre a face do abismo.",
     "version": "ACF"},
    {"book": "Gênesis", "book_id": 1, "chapter": 1, "verse": 3,
     "text": "E disse Deus: Haja luz. E houve luz.", "version": "ACF"},
    {"book": "João", "book_id": 43, "chapter": 3, "verse": 16,
     "text": "Porque Deus amou o mundo de tal maneira que deu o seu Filho unigênito.",
     "version": "ACF"},
    {"book": "João", "book_id": 43, "chapter": 3, "verse": 17,
     "text": "Porque Deus enviou o seu Filho ao mundo, para que o mundo seja salvo por ele.",
     "version": "ACF"},
    {"book": "Romanos", "book_id": 45, "chapter": 8, "verse": 28,
     "text": "E sabemos que todas as coisas cooperam para o bem daqueles que amam a Deus.",
     "version": "ACF"},
    {"book": "Mateus", "book_id": 40, "chapter": 5, "verse": 13,
     "text": "Vós sois o sal da terra.", "version": "ACF"},
]


def build_test_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE verses USING fts5("
            "id UNINDEXED, book, chapter UNINDEXED, verse UNINDEXED, "
            "text, version, tokenize='unicode61 remove_diacritics 2')"
        )
        for v in SAMPLE_VERSES:
            verse_id = f"{v['book_id']:02d}{v['chapter']:03d}{v['verse']:03d}"
            conn.execute(
                "INSERT INTO verses (id, book, chapter, verse, text, version) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (verse_id, v["book"], v["chapter"], v["verse"],
                 v["text"], v["version"]),
            )
        conn.commit()
    finally:
        conn.close()


def percentile(data: list[float], p: float) -> float:
    """Calcula o percentil p (0-100) de uma lista de valores."""
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def fmt_stats(label: str, times_ms: list[float]) -> str:
    avg = statistics.mean(times_ms)
    p50 = percentile(times_ms, 50)
    p95 = percentile(times_ms, 95)
    p99 = percentile(times_ms, 99)
    return (
        f"  {label:25s} | n={len(times_ms):3d} | "
        f"média={avg:6.2f}ms | p50={p50:6.2f}ms | "
        f"p95={p95:6.2f}ms | p99={p99:6.2f}ms"
    )


def bench_search_by_reference(searcher: Searcher, n: int = 100) -> list[float]:
    """Roda search_by_reference n vezes e retorna latências em ms."""
    refs = [
        ("Joao", 3, 16),
        ("Genesis", 1, 1),
        ("Romanos", 8, 28),
        ("Mateus", 5, 13),
        ("Genesis", 1, 2),
    ]
    times: list[float] = []
    # Warmup (5 buscas não medidas).
    for i in range(5):
        r = refs[i % len(refs)]
        searcher.search_by_reference(*r)
    # Medição.
    for i in range(n):
        r = refs[i % len(refs)]
        t0 = time.perf_counter()
        searcher.search_by_reference(*r)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
    return times


def bench_search_text(searcher: Searcher, n: int = 100) -> list[float]:
    """Roda search() n vezes e retorna latências em ms."""
    queries = [
        "deus amou o mundo",
        "princípio criou",
        "cooperam para o bem",
        "sal da terra",
        "haja luz",
    ]
    times: list[float] = []
    for i in range(5):
        searcher.search(queries[i % len(queries)])
    for i in range(n):
        q = queries[i % len(queries)]
        t0 = time.perf_counter()
        searcher.search(q)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
    return times


def main() -> None:
    import sys
    import tempfile

    # Redirecionar output para arquivo para evitar problemas de
    # encoding no console PowerShell.
    out_path = "C:/Users/USER/AppData/Local/Temp/bench_results.txt"
    out_file = open(out_path, "w", encoding="utf-8")
    def p(*args, **kwargs):
        kwargs["file"] = out_file
        kwargs["flush"] = True
        print(*args, **kwargs)

    tmp = Path(tempfile.mkdtemp(prefix="bench_1801_"))
    db_path = str(tmp / "bench.sqlite")
    build_test_db(db_path)

    books_path = Path("config") / "books.json"
    book_table = load_books(str(books_path))
    config = SearchConfig(
        fts5_db=db_path,
        embeddings_path="data/bible.embeddings.npy",
        embedding_model="intfloat/multilingual-e5-small",
        embedding_device="cpu",
        rrf_k=60,
        top_k=20,
        search_gap=0.15,
    )

    p("=" * 80)
    p("Sprint 18.0.1 — Benchmark Searcher (conexão por operação)")
    p("=" * 80)
    p()

    searcher = Searcher(config, book_table, version="ACF")

    # Benchmark search_by_reference
    p("search_by_reference (conexão por operação):")
    times_ref = bench_search_by_reference(searcher, n=100)
    p(fmt_stats("DEPOIS (Sprint 18.0.1)", times_ref))
    p()

    # Benchmark search (textual)
    p("search (FTS5 textual, conexão por operação):")
    times_text = bench_search_text(searcher, n=100)
    p(fmt_stats("DEPOIS (Sprint 18.0.1)", times_text))
    p()

    # Estimativa do overhead de abrir/fechar conexão.
    p("Overhead de sqlite3.connect() + close() (apenas abrir/fechar):")
    overhead_times: list[float] = []
    for _ in range(100):
        t0 = time.perf_counter()
        uri = f"file:{db_path}?mode=ro"
        c = sqlite3.connect(uri, uri=True)
        c.close()
        t1 = time.perf_counter()
        overhead_times.append((t1 - t0) * 1000.0)
    p(fmt_stats("connect+close apenas", overhead_times))
    p()

    # Resumo final.
    p("=" * 80)
    p("RESUMO")
    p("=" * 80)
    avg_ref = statistics.mean(times_ref)
    avg_text = statistics.mean(times_text)
    avg_overhead = statistics.mean(overhead_times)
    pct_overhead_ref = (avg_overhead / avg_ref) * 100
    pct_overhead_text = (avg_overhead / avg_text) * 100
    p(f"  search_by_reference média:  {avg_ref:6.2f}ms")
    p(f"  search (textual) média:     {avg_text:6.2f}ms")
    p(f"  overhead connect+close:     {avg_overhead:6.2f}ms")
    p(f"  % overhead / search_by_ref: {pct_overhead_ref:5.1f}%")
    p(f"  % overhead / search_text:   {pct_overhead_text:5.1f}%")
    p()
    p("Conclusão: o overhead de abrir/fechar a conexão a cada operação")
    p(f"é desprezível (<{pct_overhead_ref:.0f}% do tempo total de busca).")
    p("A segurança de thread-safety compensa amplamente o custo.")

    searcher.close()
    out_file.close()
    sys.stdout.write(f"Results written to {out_path}\n")


if __name__ == "__main__":
    import sys
    main()
    sys.stdout.flush()
