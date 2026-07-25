"""Sprint 22.0 — Diagnóstico do BibleRetriever."""
import sys
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from config.loader import load_books
from knowledge import BibleRetriever, warmup_bible_retriever

def main() -> int:
    output_lines = []
    def log(msg: str = "") -> None:
        print(msg)
        output_lines.append(msg)

    # Carregar BookTable para nomes canônicos.
    book_table = load_books("config/books.json")

    # Warm-up.
    log("=== Warm-up BibleRetriever ===")
    t0 = time.monotonic()
    retriever, stats = warmup_bible_retriever(
        sources_dir="data/sources",
        book_table=book_table,
        top_k_default=20,
    )
    log(f"Versions discovered: {stats.versions_discovered}")
    log(f"Total versions: {stats.total_versions}")
    log(f"Total verses indexed: {stats.total_verses}")
    log(f"Unique verses: {stats.unique_verses}")
    log(f"Init time: {stats.init_time_ms:.1f}ms")
    log("")

    # Testes de retrieve.
    test_queries = [
        "O Senhor te abençoe e te guarde",
        "Porque Deus amou o mundo de tal maneira",
        "O Senhor é meu pastor nada me faltará",
        "No princípio criou Deus os céus e a terra",
        "Tudo posso naquele que me fortalece",
    ]

    for query in test_queries:
        log(f"=== Query: {query!r} ===")
        t0 = time.monotonic()
        candidates = retriever.retrieve(query, top_k=5)
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        log(f"Retrieved {len(candidates)} candidates in {elapsed_ms:.1f}ms")
        for i, c in enumerate(candidates, 1):
            log(f"  {i}. {c.canonical_reference} (score={c.aggregated_score:.3f}, "
                f"versions={c.num_versions}, best={c.best_score:.3f})")
            # Mostrar top 2 versões.
            for v in c.versions[:2]:
                log(f"     [{v.version}] score={v.score:.3f} text={v.text[:60]!r}")
        log("")

    # Teste de referência menos frequente (Números 6:24-26).
    log("=== Teste específico: Números 6:24 ===")
    t0 = time.monotonic()
    candidates = retriever.retrieve("O Senhor te abençoe e te guarde", top_k=10)
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    log(f"Retrieved in {elapsed_ms:.1f}ms")
    numeros_found = [c for c in candidates if c.book_reference_id == 4]
    if numeros_found:
        c = numeros_found[0]
        log(f"  Encontrado: {c.canonical_reference} (score={c.aggregated_score:.3f})")
        for v in c.versions:
            log(f"    [{v.version}] score={v.score:.3f} text={v.text!r}")
    else:
        log("  NÃO encontrado na top 10!")
        for c in candidates[:3]:
            log(f"  {c.canonical_reference} (book_ref_id={c.book_reference_id})")

    retriever.close()

    # Escrever saída em arquivo.
    out_path = project_root / "_diag_sprint22_0_output.txt"
    out_path.write_text("\n".join(output_lines), encoding="utf-8")
    log(f"\nSaída escrita em: {out_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
