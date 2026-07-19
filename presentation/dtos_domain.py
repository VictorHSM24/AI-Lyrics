"""DTOs de domínio da Presentation Layer.

DTOs que representam entidades do domínio (Candidate, Signal,
Evidence, Recommendation, Presentation) adaptadas para apresentação.

Todos frozen dataclass, serializáveis, independentes do Core.
Nenhum DTO expõe objetos internos do domínio.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# CandidateDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateDTO:
    """DTO de um candidato (versículo candidato)."""

    candidate_id: str
    base_score: float
    book: str = ""
    chapter: int | None = None
    verse: int | None = None
    display: str = ""

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "base_score": self.base_score,
            "book": self.book,
            "chapter": self.chapter,
            "verse": self.verse,
            "display": self.display,
        }


# ---------------------------------------------------------------------------
# EvidenceDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceDTO:
    """DTO de uma evidência que sustenta um sinal."""

    id: str
    type: str
    description: str
    value: float = 0.0
    weight: float = 0.0
    confidence: float = 0.0
    contribution: float = 0.0
    metadata: tuple = field(default_factory=tuple)
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "description": self.description,
            "value": self.value,
            "weight": self.weight,
            "confidence": self.confidence,
            "contribution": self.contribution,
            "metadata": list(self.metadata),
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# SignalDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignalDTO:
    """DTO de um sinal individual de Intelligence."""

    signal_type: str
    value: float
    weight: float
    contribution: float
    explanation: str
    evidences: tuple = field(default_factory=tuple)

    @property
    def has_evidences(self) -> bool:
        return len(self.evidences) > 0

    @property
    def evidence_count(self) -> int:
        return len(self.evidences)

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type,
            "value": self.value,
            "weight": self.weight,
            "contribution": self.contribution,
            "explanation": self.explanation,
            "evidences": [e.to_dict() for e in self.evidences],
            "evidence_count": self.evidence_count,
        }


# ---------------------------------------------------------------------------
# ScoreDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreDTO:
    """DTO de um score final de um candidato."""

    candidate_id: str
    base_score: float
    final_score: float
    context_contribution: float = 0.0
    feedback_contribution: float = 0.0
    continuity_contribution: float = 0.0
    reference_contribution: float = 0.0
    theme_contribution: float = 0.0
    book_contribution: float = 0.0
    confidence_contribution: float = 0.0
    evaluation_contribution: float = 0.0
    confidence_level: str = "LOW"
    signals: tuple = field(default_factory=tuple)
    explanation: str = ""

    @property
    def total_contribution(self) -> float:
        return (
            self.context_contribution
            + self.feedback_contribution
            + self.continuity_contribution
            + self.reference_contribution
            + self.theme_contribution
            + self.book_contribution
            + self.confidence_contribution
            + self.evaluation_contribution
        )

    @property
    def signal_count(self) -> int:
        return len(self.signals)

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "base_score": self.base_score,
            "final_score": self.final_score,
            "context_contribution": self.context_contribution,
            "feedback_contribution": self.feedback_contribution,
            "continuity_contribution": self.continuity_contribution,
            "reference_contribution": self.reference_contribution,
            "theme_contribution": self.theme_contribution,
            "book_contribution": self.book_contribution,
            "confidence_contribution": self.confidence_contribution,
            "evaluation_contribution": self.evaluation_contribution,
            "total_contribution": self.total_contribution,
            "confidence_level": self.confidence_level,
            "signals": [s.to_dict() for s in self.signals],
            "signal_count": self.signal_count,
            "explanation": self.explanation,
        }


# ---------------------------------------------------------------------------
# RecommendationDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecommendationDTO:
    """DTO de uma recomendação do Sermon Intelligence."""

    query: str
    best_candidate_id: str
    confidence_level: str
    explanation: str
    has_candidates: bool
    scores: tuple = field(default_factory=tuple)
    ranking: tuple = field(default_factory=tuple)

    @property
    def best_score(self) -> ScoreDTO | None:
        return self.scores[0] if self.scores else None

    @property
    def candidate_count(self) -> int:
        return len(self.scores)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "best_candidate_id": self.best_candidate_id,
            "confidence_level": self.confidence_level,
            "explanation": self.explanation,
            "has_candidates": self.has_candidates,
            "scores": [s.to_dict() for s in self.scores],
            "ranking": list(self.ranking),
            "candidate_count": self.candidate_count,
        }


# ---------------------------------------------------------------------------
# PresentationDTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PresentationDTO:
    """DTO de uma apresentação no Holyrics."""

    candidate_id: str
    book_id: int
    chapter: int
    verse: int | None
    version: str
    status: str = ""
    verse_id: str = ""
    presented: bool = False

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "book_id": self.book_id,
            "chapter": self.chapter,
            "verse": self.verse,
            "version": self.version,
            "status": self.status,
            "verse_id": self.verse_id,
            "presented": self.presented,
        }


__all__ = [
    "CandidateDTO",
    "EvidenceDTO",
    "SignalDTO",
    "ScoreDTO",
    "RecommendationDTO",
    "PresentationDTO",
]
