"""Sprint 22.0 — Bible Knowledge Base (RAG Local).

Pacote responsável por transformar a Bíblia local (data/sources/*.sqlite)
na fonte primária de conhecimento do AI Lyrics.

Componentes:
- BibleRetriever: recupera candidatos da base bíblica local por texto.
- BibleCandidate / BibleVersionMatch: estruturas de dados dos candidatos.
- warmup_bible_retriever: warm-up separado do warm-up do LLM.

Princípio: a Bíblia local é a única fonte de verdade. O LLM atua apenas
como desambiguador sobre candidatos recuperados, nunca como fonte de
conhecimento paramétrico.
"""
from __future__ import annotations

from .types import (
    BibleCandidate,
    BibleVersionMatch,
    RetrievalMeta,
    compute_retrieval_meta,
)
from .bible_retriever import (
    BibleRetriever,
    BibleRetrieverStats,
    BibleRetrieverError,
    discover_versions,
    warmup_bible_retriever,
)

__all__ = [
    "BibleCandidate",
    "BibleVersionMatch",
    "RetrievalMeta",
    "compute_retrieval_meta",
    "BibleRetriever",
    "BibleRetrieverStats",
    "BibleRetrieverError",
    "discover_versions",
    "warmup_bible_retriever",
]
