"""Política de ranking composto para resultados de busca.

Responsabilidade:
  - Centralizar todos os pesos e fatores de scoring em um único lugar.
  - Combinar múltiplos sinais em um score final [0.0, 1.0]:
    * score FTS/RRF base
    * quantidade de keywords encontradas
    * boost de versão preferida
    * boost de livro sugerido
    * boost de termo (sinônimos/conceitos)
  - Ser facilmente extensível para futuros sinais (embedding_score,
    rerank_score, llm_confidence) sem alterar o restante do pipeline.

Limites explícitos:
  - Não faz busca.
  - Não chama LLM.
  - Não modifica SearchResult.
  - Não inventa dados.

Design:
  - RankingPolicy é stateless.
  - Todos os pesos são constantes nomeadas (sem valores mágicos).
  - score() recebe todos os sinais como parâmetros nomeados opcionais.
  - Parâmetros futuros são aceitos mas ignorados nesta versão.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pesos centralizados (fácilmente ajustáveis)
# ---------------------------------------------------------------------------

# Peso base do score FTS/RRF (sempre presente)
_WEIGHT_BASE: float = 0.40

# Peso por keyword match (proporcional ao número de keywords encontradas)
_WEIGHT_KEYWORD_MATCH: float = 0.15

# Peso por boost de versão preferida
_WEIGHT_VERSION_BONUS: float = 0.05

# Peso por boost de livro sugerido
_WEIGHT_BOOK_BONUS: float = 0.12

# Peso por boost de termo (sinônimos/conceitos)
_WEIGHT_TERM_BONUS: float = 0.08

# Peso por phrase match (query original aparece como substring no texto)
_WEIGHT_PHRASE_MATCH: float = 0.15

# Bônus por todas as keywords estarem presentes (AND match)
_WEIGHT_ALL_KEYWORDS: float = 0.10

# Peso por similaridade semântica (embedding_score) — opcional
# Mantido baixo para que embeddings complementem FTS sem dominar.
_WEIGHT_EMBEDDING: float = 0.03

# Bônus por livro sugerido (fixo quando o livro match)
_BOOK_MATCH_BONUS: float = 0.15

# Bônus máximo por keyword match (clamp)
_MAX_KEYWORD_BONUS: float = 0.20


# ---------------------------------------------------------------------------
# RankingPolicy
# ---------------------------------------------------------------------------


class RankingPolicy:
    """Política de ranking composto para resultados de busca.

    Combina múltiplos sinais em um score final [0.0, 1.0].
    Hoje utiliza: score base (FTS/RRF), keyword match, version bonus,
    book bonus, term bonus.

    Futuramente pode incorporar: embedding_score, rerank_score,
    llm_confidence — sem alterar o restante do pipeline.

    Design:
        - Stateless — pode ser instanciada uma vez e reutilizada.
        - score() tem assinatura extensível com parâmetros nomeados.
        - Parâmetros futuros são aceitos mas ignorados nesta versão.
        - Nenhum valor mágico espalhado pelo código.
    """

    def score(
        self,
        base_score: float,
        *,
        keyword_hits: int = 0,
        total_keywords: int = 0,
        version: str | None = None,
        preferred_versions: tuple[str, ...] = (),
        book_id: int | None = None,
        suggested_book_ids: tuple[int, ...] = (),
        boost_term_hits: int = 0,
        total_boost_terms: int = 0,
        phrase_match: bool = False,
        # Parâmetros futuros (reservados, ignorados hoje)
        embedding_score: float | None = None,
        rerank_score: float | None = None,
        llm_confidence: float | None = None,
    ) -> float:
        """Calcula score composto [0.0, 1.0].

        Args:
            base_score: score base do FTS/RRF [0.0, 1.0].
            keyword_hits: quantas keywords do plano estão no texto.
            total_keywords: total de keywords do plano.
            version: versão do versículo.
            preferred_versions: versões preferidas do plano.
            book_id: ID do livro do versículo.
            suggested_book_ids: IDs dos livros sugeridos pelo plano.
                O primeiro ID recebe bonus maior (livro mais provável).
            boost_term_hits: quantos boost terms estão no texto.
            total_boost_terms: total de boost terms do plano.
            phrase_match: True se a query normalizada aparece como substring
                no texto do versículo (bonus por match exato de frase).
            embedding_score: score de embedding (reservado).
            rerank_score: score de reranking (reservado).
            llm_confidence: confiança do LLM (reservado).

        Returns:
            Score composto [0.0, 1.0].
        """
        # 1. Base score (sempre presente)
        result = _WEIGHT_BASE * max(0.0, min(1.0, base_score))

        # 2. Keyword match bonus (proporcional)
        if total_keywords > 0:
            ratio = min(1.0, keyword_hits / total_keywords)
            keyword_bonus = min(
                _MAX_KEYWORD_BONUS,
                ratio * _WEIGHT_KEYWORD_MATCH,
            )
            result += keyword_bonus
            # Bônus extra quando TODAS as keywords estão presentes (AND match)
            if keyword_hits >= total_keywords and total_keywords >= 2:
                result += _WEIGHT_ALL_KEYWORDS

        # 3. Version bonus
        if version and preferred_versions and version in preferred_versions:
            result += _WEIGHT_VERSION_BONUS

        # 4. Book bonus — primeiro livro sugerido recebe bonus maior
        if book_id is not None and suggested_book_ids:
            if book_id == suggested_book_ids[0]:
                result += _WEIGHT_BOOK_BONUS + 0.10  # bonus extra para o 1º
            elif book_id in suggested_book_ids:
                result += _WEIGHT_BOOK_BONUS

        # 5. Boost term bonus
        if total_boost_terms > 0:
            term_ratio = min(1.0, boost_term_hits / total_boost_terms)
            result += term_ratio * _WEIGHT_TERM_BONUS

        # 6. Phrase match bonus — query original aparece no texto
        if phrase_match:
            result += _WEIGHT_PHRASE_MATCH

        # 7. Embedding similarity bonus (opcional — embeddings)
        # embedding_score é cosine similarity [0.0, 1.0] do semantic search.
        # Só aplicado quando embeddings estão disponíveis.
        if embedding_score is not None and embedding_score > 0:
            result += _WEIGHT_EMBEDDING * max(0.0, min(1.0, embedding_score))

        # Clamp final
        return max(0.0, min(1.0, result))

    @property
    def book_match_bonus(self) -> float:
        """Bônus fixo quando o livro do versículo está nos sugeridos."""
        return _BOOK_MATCH_BONUS
