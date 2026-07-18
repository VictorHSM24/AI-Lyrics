"""EmbeddingSearcher — interface de busca semântica para o Searcher.

Responsabilidade:
  - Coordena EmbeddingProvider (gerar vetores) e EmbeddingIndex (buscar).
  - Fornece uma interface simples para o Searcher: search(query, top_k).
  - Retorna candidatos no mesmo formato que FTS (uid → dict com metadados).
  - Carrega/builda o índice automaticamente (lazy).

Design:
  - EmbeddingSearcher é a única classe que o Searcher conhece.
  - O Searcher não sabe sobre EmbeddingProvider ou EmbeddingIndex.
  - Se o índice não existe, EmbeddingSearcher pode buildá-lo (build()).
  - Se o índice existe, carrega do disco (load()).
  - Se embeddings não estão disponíveis (provider offline), retorna [].

Extensibilidade futura:
  - Para trocar a implementação de busca (FAISS, Qdrant, etc.),
    basta substituir EmbeddingIndex. EmbeddingSearcher não muda.
  - Para trocar o modelo de embeddings, basta substituir
    EmbeddingProvider. EmbeddingSearcher não muda.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import numpy as np

from busca.embedding_index import EmbeddingIndex, SemanticResult

if TYPE_CHECKING:
    from busca.embedding_provider import EmbeddingProvider

logger = logging.getLogger(__name__)


class EmbeddingSearcher:
    """Busca semântica via embeddings.

    Coordena EmbeddingProvider e EmbeddingIndex para fornecer
    busca por similaridade semântica.

    Args:
        provider: EmbeddingProvider para gerar vetores.
        index: EmbeddingIndex para armazenar e buscar vetores.

    Example:
        >>> provider = SentenceTransformerProvider()
        >>> index = EmbeddingIndex("data/emb.npy", "data/emb.json")
        >>> searcher = EmbeddingSearcher(provider, index)
        >>> searcher.load_or_build(verses)
        >>> results = searcher.search("amor de Deus", top_k=10)
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        index: EmbeddingIndex,
    ) -> None:
        self._provider = provider
        self._index = index
        self._initialized = False

    @property
    def is_available(self) -> bool:
        """True se o índice está carregado e pronto para busca."""
        return self._index.is_loaded

    @property
    def size(self) -> int:
        """Número de versículos indexados."""
        return self._index.size

    @property
    def dim(self) -> int:
        """Dimensão dos vetores."""
        return self._index.dim

    # ------------------------------------------------------------------
    # Inicialização
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """Tenta carregar o índice do disco.

        Returns:
            True se carregou com sucesso, False caso contrário.
        """
        if self._index.load():
            self._initialized = True
            logger.info(
                "EmbeddingSearcher: index loaded (%d vectors, dim=%d)",
                self._index.size,
                self._index.dim,
            )
            return True
        logger.info("EmbeddingSearcher: index not found on disk")
        return False

    def build(self, verses: list[dict], batch_size: int = 256) -> None:
        """Gera embeddings para todos os versículos e persiste.

        Args:
            verses: lista de dicts com "uid" e "text".
            batch_size: tamanho do batch.
        """
        t0 = time.monotonic()
        self._index.build(self._provider, verses, batch_size=batch_size)
        self._initialized = True
        elapsed = time.monotonic() - t0
        logger.info(
            "EmbeddingSearcher: build complete in %.1fs (%d vectors)",
            elapsed,
            self._index.size,
        )

    def load_or_build(
        self,
        verses: list[dict],
        batch_size: int = 256,
    ) -> bool:
        """Carrega o índice do disco, ou builda se não existir.

        Args:
            verses: lista de dicts com "uid" e "text" (usado apenas se
                build for necessário).
            batch_size: tamanho do batch (usado apenas se build).

        Returns:
            True se o índice está pronto para busca.
        """
        if self.load():
            return True
        logger.info("EmbeddingSearcher: building index from scratch...")
        self.build(verses, batch_size=batch_size)
        return True

    def warmup(self) -> None:
        """Aquece o modelo fazendo uma query de teste.

        A primeira chamada a embed_query pode ser lenta (compilação de
        grafos, alocação de memória). Chamar warmup() durante inicialização
        evita que a primeira busca do usuário seja lenta.
        """
        if not self._initialized or not self._index.is_loaded:
            return
        t0 = time.monotonic()
        _ = self._provider.embed_query("warmup")
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "EmbeddingSearcher warmup: %.1fms (model ready)", elapsed_ms,
        )

    # ------------------------------------------------------------------
    # Busca
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 20,
    ) -> list[SemanticResult]:
        """Busca os top_k versículos mais semanticamente similares à query.

        Args:
            query: texto da consulta.
            top_k: número máximo de resultados.

        Returns:
            Lista de SemanticResult ordenada por score decrescente.
            Lista vazia se índice não está carregado.
        """
        if not self._initialized or not self._index.is_loaded:
            logger.warning("EmbeddingSearcher: index not loaded — returning []")
            return []

        if not query or not query.strip():
            return []

        t0 = time.monotonic()

        # Gerar embedding da query
        query_vector = self._provider.embed_query(query)

        # Buscar nearest neighbors
        results = self._index.search(query_vector, top_k=top_k)

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "EmbeddingSearcher.search: query=%r results=%d time=%.1fms",
            query[:80],
            len(results),
            elapsed_ms,
        )

        return results

    def search_with_scores(
        self,
        query: str,
        top_k: int = 20,
    ) -> dict[str, float]:
        """Busca e retorna dict {uid: score} para integração com RRF.

        Args:
            query: texto da consulta.
            top_k: número máximo de resultados.

        Returns:
            Dicionário {uid: semantic_score} para os top_k resultados.
        """
        results = self.search(query, top_k=top_k)
        return {r.uid: r.score for r in results}
