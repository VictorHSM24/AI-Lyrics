"""Feedback Learning — camada de aprendizado de preferências operacionais.

Módulo responsável por aprender preferências de uso do operador e
utilizá-las para influenciar o Ranking de forma controlada, explicável
e determinística.

IMPORTANTE:
  - NÃO implementa Machine Learning.
  - NÃO treina modelos.
  - NÃO utiliza IA.
  - NÃO altera banco bíblico, embeddings, Knowledge Graph, Parser, LLM.
  - Apenas registra preferências operacionais e as aplica ao Ranking.

API pública:
  - FeedbackScope: escopo da preferência (GLOBAL, SESSION, SERMON, USER).
  - FeedbackKey: chave única de uma preferência.
  - FeedbackRecord: registro individual de um evento.
  - FeedbackStatistics: estatísticas acumuladas por chave.
  - FeedbackSummary: resumo para explicabilidade.
  - ScoreBreakdown: decomposição do score final para auditoria.
  - FeedbackEvent + 5 eventos tipados.
  - LearningPolicy: política de pesos e decaimento (centralizada).
  - FeedbackStore: armazenamento puro (JSON).
  - FeedbackRepository: repository com interface para futura troca por SQLite.
  - FeedbackEngine: engine que processa eventos e atualiza estatísticas.
  - RankingFeedbackAdapter: adapter de integração com Ranking.
  - context_signature_from_sermon_context: helper de assinatura de contexto.

Design:
  - DTOs imutáveis (frozen dataclass).
  - Eventos tipados (frozen dataclass).
  - Engine desacoplado (não conhece Searcher, Ranking, etc.).
  - Único ponto de integração: RankingFeedbackAdapter.
  - Persistência JSON (futura troca por SQLite sem alterar Engine).
  - Política de pesos centralizada (sem números mágicos).
  - Política de decaimento determinística e configurável.
  - Limite máximo de influência (feedback nunca vence sozinho).
  - Explicabilidade total (ScoreBreakdown).
  - Contexto do sermão considerado (SermonContext).
  - Escopos preparados para futuro (GLOBAL hoje, SESSION/SERMON/USER depois).
"""

from feedback.adapter import (
    RankingFeedbackAdapter,
    context_signature_from_sermon_context,
)
from feedback.dtos import (
    FeedbackKey,
    FeedbackRecord,
    FeedbackScope,
    FeedbackStatistics,
    FeedbackSummary,
    ScoreBreakdown,
)
from feedback.engine import FeedbackEngine
from feedback.events import (
    CandidateAccepted,
    CandidateRejected,
    FeedbackEvent,
    ManualReferenceSelected,
    ManualSearch,
    SuggestionIgnored,
)
from feedback.policy import LearningPolicy
from feedback.repository import FeedbackRepository, FeedbackRepositoryProtocol
from feedback.store import FeedbackStore

__all__ = [
    # DTOs
    "FeedbackScope",
    "FeedbackKey",
    "FeedbackRecord",
    "FeedbackStatistics",
    "FeedbackSummary",
    "ScoreBreakdown",
    # Eventos
    "FeedbackEvent",
    "CandidateAccepted",
    "CandidateRejected",
    "ManualReferenceSelected",
    "ManualSearch",
    "SuggestionIgnored",
    # Policy
    "LearningPolicy",
    # Store / Repository
    "FeedbackStore",
    "FeedbackRepository",
    "FeedbackRepositoryProtocol",
    # Engine
    "FeedbackEngine",
    # Adapter
    "RankingFeedbackAdapter",
    "context_signature_from_sermon_context",
]
