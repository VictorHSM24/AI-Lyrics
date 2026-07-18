"""Exemplo de uso do módulo config.

Executa: python examples/use_config.py
"""

from __future__ import annotations

import os
import sys

# Garante que o diretório raiz do projeto está no sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import BookTable, Config, ConfigError, load_books, load_config


def main() -> None:
    # Definir env var necessária para o token do Holyrics.
    os.environ.setdefault("HOLYRICS_TOKEN", "demo-token")

    # Carregar configuração.
    try:
        cfg: Config = load_config("config/config.yaml")
    except ConfigError as e:
        print(f"[ERRO] Falha ao carregar config: {e}")
        sys.exit(1)

    print("=== Config carregada ===")
    print(f"  Holyrics base_url : {cfg.holyrics.base_url}")
    print(f"  Holyrics token    : {cfg.holyrics.token[:4]}***")
    print(f"  STT model         : {cfg.stt.model}")
    print(f"  STT device        : {cfg.stt.device}")
    print(f"  VAD mode          : {cfg.stt.vad.mode}")
    print(f"  LLM model         : {cfg.llm.model}")
    print(f"  LLM lazy_load     : {cfg.llm.lazy_load}")
    print(f"  Search embedding  : {cfg.search.embedding_model}")
    print(f"  Search rrf_k      : {cfg.search.rrf_k}")
    print(f"  State version     : {cfg.state.default_version}")
    print(f"  Cache capacity    : {cfg.cache.recent_capacity}")
    print(f"  Conf min_execute  : {cfg.confidence.min_execute}")
    print(f"  Mode              : {cfg.mode}")
    print(f"  Log path          : {cfg.log.path}")

    # Carregar tabela de livros.
    try:
        table: BookTable = load_books("config/books.json")
    except ConfigError as e:
        print(f"[ERRO] Falha ao carregar books: {e}")
        sys.exit(1)

    print(f"\n=== BookTable carregada ({len(table.all_books())} livros) ===")

    # Resolver alguns livros.
    examples = [
        "joão",
        "primeira coríntios",
        "1 corintios",
        "são joão",
        "primeiro joão",
        "apocalipse",
        "gênesis",
        "livro inexistente",
    ]
    for raw in examples:
        match = table.resolve(raw)
        if match:
            print(f"  resolve({raw!r:30s}) -> id={match.book.id:2d}  canonical={match.book.canonical!r}  alias={match.matched_alias!r}")
        else:
            print(f"  resolve({raw!r:30s}) -> None")

    # by_id.
    print("\n=== by_id ===")
    for bid in (1, 43, 66):
        book = table.by_id(bid)
        print(f"  by_id({bid}) -> {book.canonical}")


if __name__ == "__main__":
    main()
