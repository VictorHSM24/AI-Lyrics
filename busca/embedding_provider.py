"""EmbeddingProvider — interface abstrata para geração de embeddings.

Responsabilidade:
  - Converter texto em vetor numérico (embedding).
  - Ser uma abstração que pode ter múltiplas implementações:
    * SentenceTransformerProvider (sentence-transformers)
    * OllamaEmbeddingProvider (Ollama /api/embeddings)
    * ONNXEmbeddingProvider (onnxruntime + tokenizers)
    * (futuro) OpenAI, Cohere, etc.

Design:
  - Interface abstrata (ABC) com dois métodos:
    * embed_texts(texts) → batch de vetores
    * embed_query(text) → vetor único para query
  - dim (propriedade) retorna a dimensão dos vetores.
  - Implementações concretas são injetadas no EmbeddingIndex/EmbeddingSearcher.
  - O restante do sistema não sabe qual implementação está em uso.

Extensibilidade futura:
  - Para trocar o modelo, basta criar uma nova implementação de
    EmbeddingProvider e injetá-la no EmbeddingIndex/EmbeddingSearcher.
  - Nenhum outro componente precisa ser modificado.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Interface abstrata para geração de embeddings.

    Implementações concretas:
      - SentenceTransformerProvider (busca/embedding_provider_st.py)
      - (futuro) OllamaEmbeddingProvider
      - (futuro) ONNXEmbeddingProvider
    """

    @property
    @abstractmethod
    def dim(self) -> int:
        """Dimensão dos vetores de embedding."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome identificador do provider (para logs e métricas)."""
        ...

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """Gera embeddings para uma lista de textos.

        Args:
            texts: lista de textos para embeddar.

        Returns:
            Array numpy de shape (len(texts), dim) com vetores L2-normalizados.
        """
        ...

    @abstractmethod
    def embed_query(self, text: str) -> np.ndarray:
        """Gera embedding para uma query única.

        Args:
            text: texto da query.

        Returns:
            Array numpy de shape (dim,) com vetor L2-normalizado.
        """
        ...


# ---------------------------------------------------------------------------
# Implementação: SentenceTransformerProvider
# ---------------------------------------------------------------------------


class SentenceTransformerProvider(EmbeddingProvider):
    """Provider baseado em sentence-transformers (HuggingFace models).

    Suporta modelos da família E5 (intfloat/multilingual-e5-*) que
    requerem prefixos "query:" e "passage:" para separar consultas
    de documentos.

    Args:
        model_name: nome do modelo no HuggingFace Hub
            (default: "intfloat/multilingual-e5-small").
        device: "cpu" ou "cuda" (default: "cpu").
        cache_folder: pasta de cache para o modelo (opcional).

    Example:
        >>> provider = SentenceTransformerProvider()
        >>> vec = provider.embed_query("amor de Deus")
        >>> print(vec.shape)  # (384,)
    """

    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-small",
        device: str = "cpu",
        cache_folder: str | None = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        self._model_name = model_name
        self._device = device
        logger.info(
            "SentenceTransformerProvider: loading model %s on %s...",
            model_name,
            device,
        )
        self._model = SentenceTransformer(
            model_name,
            device=device,
            cache_folder=cache_folder,
        )
        self._dim = self._model.get_embedding_dimension()
        logger.info(
            "SentenceTransformerProvider: model loaded, dim=%d", self._dim
        )

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return f"st:{self._model_name}"

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """Gera embeddings para documentos (passage).

        Para modelos E5, adiciona o prefixo "passage: " a cada texto.
        """
        if not texts:
            return np.array([], dtype=np.float32).reshape(0, self._dim)
        # E5 requer prefixo "passage: " para documentos
        prefixed = [f"passage: {t}" for t in texts]
        embeddings = self._model.encode(
            prefixed,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embeddings.astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        """Gera embedding para query.

        Para modelos E5, adiciona o prefixo "query: ".
        """
        # E5 requer prefixo "query: " para consultas
        prefixed = f"query: {text}"
        embedding = self._model.encode(
            prefixed,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embedding.astype(np.float32)
