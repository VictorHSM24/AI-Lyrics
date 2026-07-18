"""Módulo de busca híbrida (FTS5 + embeddings + RRF).

API pública:
    BibleIndexer — build do índice FTS5.
    Searcher — mecanismo de busca de versículos.
    SearchResult — resultado de busca.
    SearchMetrics — métricas acumuladas.
    VerseRow, IndexStats — modelos do indexador.
    SearchError, IndexerError — exceções.
    QueryPlanner, QueryPlan — planejamento de busca estruturado.
    RankingPolicy — política de ranking composto.
    LLMReranker — reranking de candidatos via LLM.
    EmbeddingProvider — interface para geração de embeddings.
    SentenceTransformerProvider — implementação ST.
    EmbeddingIndex — persistência e busca de vetores.
    EmbeddingSearcher — busca semântica integrada.
    SemanticResult — resultado de busca semântica.
    KnowledgeBase — base de conhecimento bíblico estruturado.
    KnowledgeEnricher — enriquecimento de Intent com conhecimento.
    KnowledgeMatch — DTO de resultado de enriquecimento.
    BiblicalEntity — entidade do grafo de conhecimento bíblico.
    BiblicalEntityType — enum de tipos de entidade bíblica.
    BibleBook — identificador canônico para livros da Bíblia (1..66).
    BibleReference — referência bíblica canônica (DTO imutável).
    parse_bible_reference — parser de string → BibleReference.
"""

from busca.biblical_entity import BiblicalEntity, BiblicalEntityType
from busca.bible_reference import BibleBook, BibleReference, parse_bible_reference
from busca.exceptions import IndexerError, SearchError
from busca.indexer import BibleIndexer
from busca.knowledge_enricher import KnowledgeBase, KnowledgeEnricher, KnowledgeMatch
from busca.models import IndexStats, VerseRow
from busca.query_planner import QueryPlan, QueryPlanner
from busca.ranking import RankingPolicy
from busca.reranker import LLMReranker
from busca.searcher import SearchMetrics, SearchResult, Searcher

__all__ = [
    "BibleIndexer",
    "Searcher",
    "SearchResult",
    "SearchMetrics",
    "VerseRow",
    "IndexStats",
    "SearchError",
    "IndexerError",
    "QueryPlanner",
    "QueryPlan",
    "RankingPolicy",
    "LLMReranker",
    "KnowledgeBase",
    "KnowledgeEnricher",
    "KnowledgeMatch",
    "BiblicalEntity",
    "BiblicalEntityType",
    "BibleBook",
    "BibleReference",
    "parse_bible_reference",
]

# Embeddings — import lazy para evitar carregar torch/sentence-transformers
# quando embeddings não são usados.
def __getattr__(name: str):
    if name in (
        "EmbeddingProvider",
        "SentenceTransformerProvider",
        "EmbeddingIndex",
        "EmbeddingSearcher",
        "SemanticResult",
    ):
        from busca import embedding_provider, embedding_index, embedding_searcher
        if name == "EmbeddingProvider":
            return embedding_provider.EmbeddingProvider
        if name == "SentenceTransformerProvider":
            return embedding_provider.SentenceTransformerProvider
        if name == "EmbeddingIndex":
            return embedding_index.EmbeddingIndex
        if name == "SemanticResult":
            return embedding_index.SemanticResult
        if name == "EmbeddingSearcher":
            return embedding_searcher.EmbeddingSearcher
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
