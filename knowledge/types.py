"""Sprint 22.0 — Tipos de dados do BibleRetriever.

Estruturas imutáveis que representam candidatos recuperados da base
bíblica local, com agregação multi-versão.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class BibleVersionMatch:
    """Match de um versículo em uma versão específica da Bíblia.

    Atributos:
        version: código da versão ("ACF", "ARA", "NVT", etc.).
        text: texto do versículo nesta versão.
        score: score de similaridade [0.0, 1.0] desta versão
            em relação à consulta.
    """

    version: str
    text: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "text": self.text,
            "score": round(self.score, 4),
        }


@dataclass(frozen=True)
class BibleCandidate:
    """Candidato bíblico agregado de múltiplas versões.

    Representa um único versículo (book_reference_id, chapter, verse)
    com todas as versões encontradas na base local que corresponderam
    à consulta.

    Atributos:
        book: nome canônico do livro ("Números", "João").
        book_reference_id: ID canônico do livro (1..66), usado para
            agregar versões que usam IDs internos diferentes.
        chapter: número do capítulo.
        verse: número do versículo.
        canonical_reference: referência legível ("Números 6:24").
        aggregated_score: score agregado [0.0, 1.0] combinando
            melhor score, média e quantidade de versões.
        versions: lista de BibleVersionMatch, uma por versão que
            correspondeu à consulta.
        best_score: maior score entre as versões.
        mean_score: média dos scores das versões.
        num_versions: quantidade de versões que corresponderam.
        search_rank: posição (1-based) na busca original antes da
            agregação. Menor = melhor.
    """

    book: str
    book_reference_id: int
    chapter: int
    verse: int
    canonical_reference: str
    aggregated_score: float
    versions: tuple[BibleVersionMatch, ...]
    best_score: float
    mean_score: float
    num_versions: int
    search_rank: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "book": self.book,
            "book_reference_id": self.book_reference_id,
            "chapter": self.chapter,
            "verse": self.verse,
            "canonical_reference": self.canonical_reference,
            "aggregated_score": round(self.aggregated_score, 4),
            "versions": [v.to_dict() for v in self.versions],
            "best_score": round(self.best_score, 4),
            "mean_score": round(self.mean_score, 4),
            "num_versions": self.num_versions,
            "search_rank": self.search_rank,
        }

    @property
    def primary_text(self) -> str:
        """Texto do versículo na versão com maior score."""
        if not self.versions:
            return ""
        best = max(self.versions, key=lambda v: v.score)
        return best.text


@dataclass(frozen=True)
class RetrievalMeta:
    """Sprint 22.2 — Metadados de uma recuperação do BibleRetriever.

    Computado a partir de uma lista ordenada de BibleCandidate (top1
    primeiro). Usado pela ContextPolicy para decidir quanto do contexto
    do sermão incluir no prompt.

    Atributos:
        top1_score: aggregated_score do melhor candidato (0.0 se vazio).
        top2_score: aggregated_score do segundo candidato (0.0 se <2).
        gap: diferença top1_score - top2_score (0.0 se <2 candidatos).
        num_candidates: total de candidatos retornados.
        top1_book: livro do top1 ("" se vazio).
        top1_reference: canonical_reference do top1 ("" se vazio).
        top1_num_versions: num_versions do top1 (0 se vazio).
    """

    top1_score: float
    top2_score: float
    gap: float
    num_candidates: int
    top1_book: str
    top1_reference: str
    top1_num_versions: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "top1_score": round(self.top1_score, 4),
            "top2_score": round(self.top2_score, 4),
            "gap": round(self.gap, 4),
            "num_candidates": self.num_candidates,
            "top1_book": self.top1_book,
            "top1_reference": self.top1_reference,
            "top1_num_versions": self.top1_num_versions,
        }


def compute_retrieval_meta(
    candidates: "Sequence[BibleCandidate]",
) -> RetrievalMeta:
    """Sprint 22.2 — Computa RetrievalMeta a partir de candidatos.

    Args:
        candidates: lista de BibleCandidate ordenada por aggregated_score
            (desc), conforme retornado por BibleRetriever.retrieve().

    Returns:
        RetrievalMeta com top1/top2/gap. Para listas vazias, todos os
        scores são 0.0 e strings vazias.
    """
    if not candidates:
        return RetrievalMeta(
            top1_score=0.0, top2_score=0.0, gap=0.0,
            num_candidates=0, top1_book="", top1_reference="",
            top1_num_versions=0,
        )
    top1 = candidates[0]
    if len(candidates) >= 2:
        top2 = candidates[1]
        gap = top1.aggregated_score - top2.aggregated_score
        top2_score = top2.aggregated_score
    else:
        gap = top1.aggregated_score  # gap = top1 - 0 = top1
        top2_score = 0.0
    return RetrievalMeta(
        top1_score=top1.aggregated_score,
        top2_score=top2_score,
        gap=gap,
        num_candidates=len(candidates),
        top1_book=top1.book,
        top1_reference=top1.canonical_reference,
        top1_num_versions=top1.num_versions,
    )
