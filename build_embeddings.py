"""Build embedding index for all verses in the FTS5 database.

Gera embeddings para todos os versículos e persiste em disco.
Após executar este script, o EmbeddingSearcher carregará o índice
automaticamente na próxima inicialização do pipeline.

Uso:
    python build_embeddings.py
    python build_embeddings.py --version ACF  # apenas uma versão
    python build_embeddings.py --batch-size 128

Tempo estimado (CPU, multilingual-e5-small):
    - 31k versículos (1 versão): ~3-5 minutos
    - 155k versículos (5 versões): ~15-25 minutos
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("build_embeddings")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build embedding index")
    parser.add_argument(
        "--config", default="config/config.yaml",
        help="caminho para config.yaml (default: config/config.yaml)",
    )
    parser.add_argument(
        "--version", default=None,
        help="gerar embeddings apenas para esta versão (default: todas)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=256,
        help="tamanho do batch (default: 256)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="forçar rebuild mesmo se índice já existe",
    )
    args = parser.parse_args()

    # Carregar config
    sys.path.insert(0, ".")
    from config import load_config

    cfg = load_config(args.config)

    # Verificar se índice já existe
    import os
    vectors_path = cfg.search.embeddings_path
    meta_path = os.path.splitext(vectors_path)[0] + ".json"

    if not args.force and os.path.isfile(vectors_path) and os.path.isfile(meta_path):
        logger.info("Embedding index already exists at %s", vectors_path)
        logger.info("Use --force to rebuild.")
        return 0

    # Carregar versículos do banco FTS5
    logger.info("Loading verses from %s", cfg.search.fts5_db)
    db = sqlite3.connect(cfg.search.fts5_db)
    db.row_factory = sqlite3.Row

    if args.version:
        rows = db.execute(
            "SELECT id, book, chapter, verse, text, version "
            "FROM verses WHERE version = ? ORDER BY id",
            (args.version,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, book, chapter, verse, text, version "
            "FROM verses ORDER BY id",
        ).fetchall()

    db.close()

    logger.info("Loaded %d verses", len(rows))
    if not rows:
        logger.error("No verses found — aborting")
        return 1

    # Construir lista de versículos para embeddar
    # UID = id (que já é único por versículo+versão)
    verses = [
        {
            "uid": row["id"],
            "text": row["text"],
            "book": row["book"],
            "chapter": row["chapter"],
            "verse": row["verse"],
            "version": row["version"],
        }
        for row in rows
    ]

    # Criar provider e index
    from busca.embedding_provider import SentenceTransformerProvider
    from busca.embedding_index import EmbeddingIndex

    logger.info(
        "Loading embedding model: %s (device: %s)",
        cfg.search.embedding_model,
        cfg.search.embedding_device,
    )
    provider = SentenceTransformerProvider(
        model_name=cfg.search.embedding_model,
        device=cfg.search.embedding_device,
    )
    logger.info("Model loaded: dim=%d", provider.dim)

    index = EmbeddingIndex(vectors_path, meta_path)

    # Build
    t0 = time.monotonic()
    index.build(provider, verses, batch_size=args.batch_size)
    elapsed = time.monotonic() - t0

    logger.info(
        "Embedding index built: %d vectors, dim=%d, time=%.1fs",
        index.size, index.dim, elapsed,
    )
    logger.info("Vectors saved to: %s", vectors_path)
    logger.info("Metadata saved to: %s", meta_path)

    # Verificar tamanho dos arquivos
    vsize = os.path.getsize(vectors_path) / (1024 * 1024)
    msize = os.path.getsize(meta_path) / (1024 * 1024)
    logger.info("File sizes: vectors=%.1fMB, metadata=%.1fMB", vsize, msize)

    return 0


if __name__ == "__main__":
    sys.exit(main())
