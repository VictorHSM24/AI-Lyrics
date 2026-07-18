"""Exemplo de uso do módulo busca/searcher.py.

Executa: python examples/use_searcher.py

Demonstra:
  1. Busca textual: "deus amou o mundo" → João 3:16.
  2. Busca textual aproximada: "todas as coisas cooperam para o bem" → Romanos 8:28.
  3. Busca por referência: "João 3:16" → versículo exato.
  4. Busca por capítulo: "João 3" → todos os versículos.
  5. Busca contextual: "próximo" com BibleState.
  6. Métricas de busca.

Pré-requisito:
  - Base FTS5 criada por scripts/build_index.py ou busca/indexer.py.
  - Se a base não existir, o exemplo cria uma temporária com versículos de teste.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from busca.searcher import Searcher, SearchResult
from config.books import BookTable
from config.loader import load_books
from config.models import SearchConfig
from estado.state import BibleState


# ---------------------------------------------------------------------------
# Dados de teste (usados se a base real não existir)
# ---------------------------------------------------------------------------

_SAMPLE_VERSES = [
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

_FTS5_SCHEMA = (
    "CREATE VIRTUAL TABLE verses USING fts5("
    "book, chapter UNINDEXED, verse UNINDEXED, text, "
    "version UNINDEXED, id UNINDEXED, "
    "tokenize = 'unicode61 remove_diacritics 2'"
    ")"
)


def _create_temp_db(db_path: str) -> None:
    """Cria uma base FTS5 temporária com versículos de teste."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_FTS5_SCHEMA)
        for v in _SAMPLE_VERSES:
            vid = f"{v['book_id']:02d}{v['chapter']:03d}{v['verse']:03d}"
            conn.execute(
                "INSERT INTO verses (book, chapter, verse, text, version, id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (v["book"], v["chapter"], v["verse"], v["text"], v["version"], vid),
            )
        conn.commit()
    finally:
        conn.close()


def _print_result(result: SearchResult, index: int = 0) -> None:
    """Imprime um SearchResult de forma legível."""
    print(f"  [{index}] {result.reference} ({result.version})")
    print(f"      text:      {result.text[:80]}...")
    print(f"      score:     {result.score:.3f}")
    print(f"      c_search:  {result.c_search:.3f}")
    print(f"      ambiguous: {result.ambiguous}")
    print(f"      type:      {result.match_type}")


def main() -> None:
    print("=== Busca de Versículos — Searcher ===\n")

    # Carregar BookTable
    books_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "books.json"
    )
    book_table = load_books(books_path)

    # Verificar se a base real existe; senão, criar temporária
    real_db = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "bible.pt-br.sqlite"
    )

    if os.path.isfile(real_db):
        db_path = real_db
        print(f"Usando base real: {db_path}\n")
    else:
        tmp_dir = tempfile.mkdtemp(prefix="ai_lyrics_search_")
        db_path = os.path.join(tmp_dir, "test.sqlite")
        _create_temp_db(db_path)
        print(f"Base real não encontrada. Usando base temporária: {db_path}\n")

    config = SearchConfig(
        fts5_db=db_path,
        embeddings_path="data/bible.embeddings.npy",
        embedding_model="intfloat/multilingual-e5-small",
        embedding_device="cpu",
        rrf_k=60,
        top_k=20,
        search_gap=0.15,
    )

    with Searcher(config, book_table, version="ACF") as searcher:
        # 1. Busca textual
        print("--- 1. Busca textual: 'deus amou o mundo' ---\n")
        results = searcher.search("deus amou o mundo")
        for i, r in enumerate(results[:5]):
            _print_result(r, i)

        # 2. Busca textual aproximada
        print("\n--- 2. Busca textual aproximada: 'todas as coisas cooperam para o bem' ---\n")
        results = searcher.search("todas as coisas cooperam para o bem")
        for i, r in enumerate(results[:5]):
            _print_result(r, i)

        # 3. Busca por referência
        print("\n--- 3. Busca por referência: 'João 3:16' ---\n")
        results = searcher.search("João 3:16")
        for i, r in enumerate(results):
            _print_result(r, i)

        # 4. Busca por capítulo
        print("\n--- 4. Busca por capítulo: 'João 3' ---\n")
        results = searcher.search("João 3")
        print(f"  ({len(results)} versículos encontrados)")
        for i, r in enumerate(results[:5]):
            _print_result(r, i)
        if len(results) > 5:
            print(f"  ... e mais {len(results) - 5} versículos")

        # 5. Busca contextual
        print("\n--- 5. Busca contextual: 'próximo' (state=João 3:16) ---\n")
        state = BibleState(book_id=43, chapter=3, verse=16, version="ACF")
        results = searcher.search("próximo", state=state)
        for i, r in enumerate(results):
            _print_result(r, i)

        # 6. Métricas
        print("\n--- 6. Métricas ---\n")
        m = searcher.metrics
        print(f"  total_searches:  {m.total_searches}")
        print(f"  successful:      {m.successful}")
        print(f"  empty_results:   {m.empty_results}")
        print(f"  total_results:   {m.total_results}")
        print(f"  avg_time_ms:     {m.avg_time_ms:.2f}")
        print(f"  avg_results:     {m.avg_results:.2f}")
        print(f"  cache_hits:      {m.cache_hits}")
        print(f"  cache_misses:    {m.cache_misses}")
        print(f"  by_type:         {dict(m.by_type)}")

    print("\n=== Concluído ===")


if __name__ == "__main__":
    main()
