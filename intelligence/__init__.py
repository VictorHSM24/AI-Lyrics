"""Sermon Intelligence — camada de orquestração inteligente.

Módulo responsável por coordenar todos os sinais produzidos pelas fases
anteriores (Context Engine, Feedback Learning, Continuous Evaluation) e
produzir uma recomendação única, totalmente explicável, auditável e
desacoplada.

IMPORTANTE:
  - NÃO executa busca.
  - NÃO calcula embeddings.
  - NÃO interpreta áudio.
  - NÃO consulta Holyrics.
  - NÃO modifica Feedback, Context, Evaluation, Ranking.
  - Apenas coordena sinais e produz recomendação.

API pública:
  - ConfidenceLevel: enum (LOW, MEDIUM, HIGH).
  - CandidateInfo: informação de um candidato.
  - IntelligenceRequest: requisição completa.
  - IntelligenceSignal: sinal individual (base).
  - IntelligenceScore: score final com decomposição.
  - IntelligenceRecommendation: recomendação de ordenação.
  - 8 sinais tipados (Context, Feedback, Continuity, Reference, Theme,
    Book, Confidence, Evaluation).
  - 6 sinais futuros preparados (Semantic, Operator, ChurchProfile,
    Language, Temporal, Emotion).
  - IntelligencePolicy: política centralizada (pesos, limites, thresholds).
  - 8 estratégias (Context, Feedback, Continuity, Reference, Theme, Book,
    Confidence, Evaluation).
  - SignalCombiner: combinador de sinais.
  - IntelligenceCoordinator: coordenador de estratégias.
  - SermonIntelligenceEngine: engine principal (ponto de entrada).

Design:
  - DTOs imutáveis (frozen dataclass).
  - Sinais independentes (cada um retorna value, weight, explanation).
  - Estratégias stateless e desacopladas.
  - Política centralizada (sem números mágicos).
  - Explicabilidade total (toda decisão é justificada).
  - Confiança não-binária (LOW, MEDIUM, HIGH).
  - Preparação para sinais futuros sem quebrar compatibilidade.
"""

from intelligence.combiner import SignalCombiner
from intelligence.coordinator import IntelligenceCoordinator
from intelligence.dtos import (
    CandidateInfo,
    ConfidenceLevel,
    IntelligenceRecommendation,
    IntelligenceRequest,
    IntelligenceScore,
    IntelligenceSignal,
)
from intelligence.engine import SermonIntelligenceEngine
from intelligence.evidence import (
    Evidence,
    EvidenceFactory,
    EvidencePolicy,
    EvidenceType,
    SignalBuilder,
)
from intelligence.policy import IntelligencePolicy
from intelligence.signals import (
    ACTIVE_SIGNAL_TYPES,
    ALL_SIGNAL_TYPES,
    BookSignal,
    ChurchProfileSignal,
    ConfidenceSignal,
    ContextSignal,
    ContinuitySignal,
    EmotionSignal,
    EvaluationSignal,
    FeedbackSignal,
    FUTURE_SIGNAL_TYPES,
    LanguageSignal,
    OperatorSignal,
    ReferenceSignal,
    SemanticSignal,
    TemporalSignal,
    ThemeSignal,
)
from intelligence.strategies import (
    BookStrategy,
    ConfidenceStrategy,
    ContextStrategy,
    ContinuityStrategy,
    EvaluationStrategy,
    FeedbackStrategy,
    ReferenceStrategy,
    ThemeStrategy,
    all_strategies,
)

__all__ = [
    # DTOs
    "ConfidenceLevel",
    "CandidateInfo",
    "IntelligenceRequest",
    "IntelligenceSignal",
    "IntelligenceScore",
    "IntelligenceRecommendation",
    # Sinais ativos
    "ContextSignal",
    "FeedbackSignal",
    "ContinuitySignal",
    "ReferenceSignal",
    "ThemeSignal",
    "BookSignal",
    "ConfidenceSignal",
    "EvaluationSignal",
    # Sinais futuros
    "SemanticSignal",
    "OperatorSignal",
    "ChurchProfileSignal",
    "LanguageSignal",
    "TemporalSignal",
    "EmotionSignal",
    # Registry
    "ACTIVE_SIGNAL_TYPES",
    "FUTURE_SIGNAL_TYPES",
    "ALL_SIGNAL_TYPES",
    # Policy
    "IntelligencePolicy",
    # Evidence Layer
    "EvidenceType",
    "Evidence",
    "EvidencePolicy",
    "EvidenceFactory",
    "SignalBuilder",
    # Estratégias
    "ContextStrategy",
    "FeedbackStrategy",
    "ContinuityStrategy",
    "ReferenceStrategy",
    "ThemeStrategy",
    "BookStrategy",
    "ConfidenceStrategy",
    "EvaluationStrategy",
    "all_strategies",
    # Combiner / Coordinator / Engine
    "SignalCombiner",
    "IntelligenceCoordinator",
    "SermonIntelligenceEngine",
]
