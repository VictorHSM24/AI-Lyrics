"""EmbeddingIndex — persistência e indexação de vetores de embeddings.

Responsabilidade:
  - Armazenar embeddings de todos os versículos indexados.
  - Persistir em disco (numpy memmap ou arquivo .npy).
  - Carregar índice existente sem regenerar embeddings.
  - Fornecer busca por nearest neighbors (cosine similarity).

Design:
  - EmbeddingIndex é a abstração de armazenamento.
  - Implementação atual: NumpyEmbeddingIndex (numpy + cosine similarity).
  - Futuramente pode ser trocada por:
    * FAISSEmbeddingIndex (Facebook FAISS)
    * QdrantEmbeddingIndex (Qdrant)
    * SQLiteVecEmbeddingIndex (sqlite-vec)
    * PgVectorEmbeddingIndex (PostgreSQL pgvector)
  - O restante do sistema não sabe qual implementação está em uso.

Arquitetura:
  EmbeddingProvider (gera vetores)
      ↓
  EmbeddingIndex (armazena + busca)
      ↓
  EmbeddingSearcher (interface de busca para o Searcher)

Persistência:
  - Vetores: arquivo .npy (numpy array de shape (N, dim))
  - Metadados: arquivo .json com mapeamento uid → índice no array
  - Se ambos existem, o índice é carregado sem regenerar embeddings.
  - Se não existem, build() gera embeddings via EmbeddingProvider e persiste.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from busca.embedding_provider import EmbeddingProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SemanticResult:
    """Resultado de busca semântica.

    Atributos:
        uid: identificador único do versículo (id_versão).
        score: similaridade cosine [0.0, 1.0] (1.0 = idêntico).
        rank: posição no ranking (0-based).
    """

    uid: str
    score: float
    rank: int


# ---------------------------------------------------------------------------
# EmbeddingIndex (interface abstrata)
# ---------------------------------------------------------------------------


class EmbeddingIndex:
    """Armazena e busca embeddings de versículos.

    Implementação atual usa numpy + cosine similarity (brute force).
    Para ~31k versículos × 384 dim, a busca leva <50ms em CPU.

    Futuramente pode ser substituída por FAISS, Qdrant, etc.
    """

    def __init__(
        self,
        vectors_path: str,
        meta_path: str,
    ) -> None:
        self._vectors_path = vectors_path
        self._meta_path = meta_path

        # Estado interno
        self._vectors: np.ndarray | None = None  # shape (N, dim)
        self._uid_to_idx: dict[str, int] = {}
        self._idx_to_uid: list[str] = []
        self._dim: int = 0
        self._is_loaded = False

    @property
    def is_loaded(self) -> bool:
        """True se o índice foi carregado do disco."""
        return self._is_loaded

    @property
    def size(self) -> int:
        """Número de versículos indexados."""
        return len(self._idx_to_uid)

    @property
    def dim(self) -> int:
        """Dimensão dos vetores."""
        return self._dim

    # ------------------------------------------------------------------
    # Carregamento / persistência
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """Carrega índice do disco se existir.

        Returns:
            True se carregou com sucesso, False se arquivos não existem.
        """
        if not os.path.isfile(self._vectors_path):
            return False
        if not os.path.isfile(self._meta_path):
            return False

        try:
            self._vectors = np.load(self._vectors_path, mmap_mode="r")
            with open(self._meta_path, encoding="utf-8") as f:
                meta = json.load(f)

            self._dim = meta.get("dim", 0)
            self._idx_to_uid = meta.get("uids", [])
            self._uid_to_idx = {uid: i for i, uid in enumerate(self._idx_to_uid)}
            self._is_loaded = True

            logger.info(
                "EmbeddingIndex loaded: %d vectors, dim=%d from %s",
                self.size,
                self._dim,
                self._vectors_path,
            )
            return True
        except Exception as e:
            logger.warning("EmbeddingIndex load failed: %s", e)
            self._vectors = None
            self._uid_to_idx = {}
            self._idx_to_uid = []
            self._dim = 0
            self._is_loaded = False
            return False

    def save(self) -> None:
        """Persiste vetores e metadados no disco."""
        if self._vectors is None:
            raise RuntimeError("no vectors to save — call build() first")

        os.makedirs(os.path.dirname(self._vectors_path) or ".", exist_ok=True)
        os.makedirs(os.path.dirname(self._meta_path) or ".", exist_ok=True)

        # Salvar vetores (converter de mmap para array normal)
        np.save(self._vectors_path, np.array(self._vectors))

        # Salvar metadados
        meta = {
            "dim": self._dim,
            "uids": self._idx_to_uid,
            "size": self.size,
        }
        with open(self._meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        logger.info(
            "EmbeddingIndex saved: %d vectors, dim=%d to %s",
            self.size,
            self._dim,
            self._vectors_path,
        )

    # ------------------------------------------------------------------
    # Build (indexação)
    # ------------------------------------------------------------------

    def build(
        self,
        provider: EmbeddingProvider,
        verses: list[dict],
        batch_size: int = 256,
    ) -> None:
        """Gera embeddings para todos os versículos e persiste.

        Args:
            provider: EmbeddingProvider para gerar vetores.
            verses: lista de dicts com "uid" e "text" para cada versículo.
                uid é o identificador único (id_versão).
                text é o texto do versículo (será prefixado com "passage:").
            batch_size: tamanho do batch para processamento.

        Note:
            Este método pode levar vários minutos para ~31k versículos.
            Após build(), save() é chamado automaticamente.
        """
        if not verses:
            logger.warning("EmbeddingIndex.build: empty verses list")
            return

        t0 = time.monotonic()
        total = len(verses)
        logger.info(
            "EmbeddingIndex.build: generating embeddings for %d verses "
            "(batch_size=%d, provider=%s)...",
            total,
            batch_size,
            provider.name,
        )

        all_embeddings: list[np.ndarray] = []
        for i in range(0, total, batch_size):
            batch = verses[i : i + batch_size]
            texts = [v["text"] for v in batch]
            embeddings = provider.embed_texts(texts)
            all_embeddings.append(embeddings)

            if (i // batch_size) % 10 == 0:
                elapsed = time.monotonic() - t0
                progress = min(i + batch_size, total)
                rate = progress / elapsed if elapsed > 0 else 0
                eta = (total - progress) / rate if rate > 0 else 0
                logger.info(
                    "EmbeddingIndex.build: %d/%d (%.1f%%) rate=%.0f/s eta=%.0fs",
                    progress,
                    total,
                    100 * progress / total,
                    rate,
                    eta,
                )

        # Concatenar todos os batches
        self._vectors = np.vstack(all_embeddings).astype(np.float32)
        self._dim = self._vectors.shape[1]
        self._idx_to_uid = [v["uid"] for v in verses]
        self._uid_to_idx = {uid: i for i, uid in enumerate(self._idx_to_uid)}
        self._is_loaded = True

        elapsed = time.monotonic() - t0
        logger.info(
            "EmbeddingIndex.build: done! %d vectors, dim=%d, time=%.1fs",
            self.size,
            self._dim,
            elapsed,
        )

        # Persistir
        self.save()

    # ------------------------------------------------------------------
    # Busca (nearest neighbors)
    # ------------------------------------------------------------------

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 20,
    ) -> list[SemanticResult]:
        """Busca os top_k versículos mais similares à query.

        Usa cosine similarity (vetores já são L2-normalizados, então
        cosine = dot product).

        Args:
            query_vector: vetor da query, shape (dim,), L2-normalizado.
            top_k: número máximo de resultados.

        Returns:
            Lista de SemanticResult ordenada por score decrescente.
        """
        if self._vectors is None or not self._is_loaded:
            return []
        if self.size == 0:
            return []

        # Dot product = cosine similarity (vetores normalizados)
        # query_vector: (dim,), vectors: (N, dim) → scores: (N,)
        scores = np.dot(self._vectors, query_vector)

        # Top k índices
        k = min(top_k, self.size)
        # argpartition é mais rápido que argsort para top-k
        if k < self.size:
            top_indices = np.argpartition(scores, -k)[-k:]
            # Ordenar os top_k por score decrescente
            top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
        else:
            top_indices = np.argsort(scores)[::-1]

        results = []
        for rank, idx in enumerate(top_indices):
            uid = self._idx_to_uid[idx]
            score = float(scores[idx])
            # Clamp score to [0, 1] (cosine pode ser negativo)
            score = max(0.0, min(1.0, score))
            results.append(SemanticResult(uid=uid, score=score, rank=rank))

        return results

    def get_vector(self, uid: str) -> np.ndarray | None:
        """Retorna o vetor de um versículo específico, ou None se não existe."""
        if not self._is_loaded or self._vectors is None:
            return None
        idx = self._uid_to_idx.get(uid)
        if idx is None:
            return None
        return self._vectors[idx]
