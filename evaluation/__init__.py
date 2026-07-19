"""Continuous Evaluation — infraestrutura de medição de qualidade.

Módulo responsável por medir continuamente a qualidade das decisões
tomadas pelo sistema. Totalmente observacional — nunca influencia
decisões, nunca altera Ranking, Feedback, Contexto ou qualquer outro
componente.

IMPORTANTE:
  - NÃO modifica o comportamento do sistema.
  - NÃO altera Searcher, Ranking, Context Engine, Feedback, Embeddings,
    Knowledge Graph, Holyrics, Parser, LLM.
  - Apenas observa e mede.

API pública:
  - QueryClassification: classificação do tipo de consulta.
  - TemporalWindow: janela temporal (LAST_24H, LAST_7D, LAST_30D, ALL).
  - EvaluationRecord: registro individual de um evento.
  - EvaluationMetrics: métricas acumuladas.
  - TemporalSlice: fatia temporal das métricas.
  - EvaluationSummary: resumo agregado.
  - EvaluationReport: relatório completo.
  - RegressionAlert: alerta de regressão.
  - EvaluationEvent + 8 eventos tipados.
  - EvaluationPolicy: política centralizada (thresholds, classificações).
  - EvaluationStore: armazenamento puro (JSON).
  - EvaluationRepository: repository com interface para SQLite.
  - EvaluationEngine: engine que registra eventos.
  - MetricsCalculator: calculadora de métricas.
  - ReportGenerator: gerador de relatórios.
  - RegressionDetector: detector de regressões.

Design:
  - DTOs imutáveis (frozen dataclass).
  - Eventos tipados (frozen dataclass).
  - Engine desacoplado (não conhece nenhum outro componente).
  - Persistência JSON (futura troca por SQLite sem alterar Engine).
  - Política centralizada (sem números mágicos).
  - Métricas temporais (24h, 7d, 30d, all).
  - Detecção de regressões (apenas registra, não toma decisões).
  - Relatórios explicáveis e auditáveis.
  - Classificação de consultas extensível.
"""

from evaluation.dtos import (
    EvaluationMetrics,
    EvaluationRecord,
    EvaluationReport,
    EvaluationSummary,
    QueryClassification,
    RegressionAlert,
    TemporalSlice,
    TemporalWindow,
)
from evaluation.engine import EvaluationEngine
from evaluation.events import (
    CandidateAccepted,
    CandidatePresented,
    CandidateRejected,
    EvaluationEvent,
    EvaluationReset,
    EvaluationEventUnion,
    ManualCorrection,
    NoResultFound,
    SearchExecuted,
    SearchFailed,
)
from evaluation.metrics import MetricsCalculator
from evaluation.policy import EvaluationPolicy
from evaluation.regressions import RegressionDetector
from evaluation.repository import EvaluationRepository, EvaluationRepositoryProtocol
from evaluation.reports import ReportGenerator
from evaluation.store import EvaluationStore

__all__ = [
    # DTOs
    "QueryClassification",
    "TemporalWindow",
    "EvaluationRecord",
    "EvaluationMetrics",
    "TemporalSlice",
    "EvaluationSummary",
    "EvaluationReport",
    "RegressionAlert",
    # Eventos
    "EvaluationEvent",
    "SearchExecuted",
    "CandidatePresented",
    "CandidateAccepted",
    "CandidateRejected",
    "ManualCorrection",
    "SearchFailed",
    "NoResultFound",
    "EvaluationReset",
    "EvaluationEventUnion",
    # Policy
    "EvaluationPolicy",
    # Store / Repository
    "EvaluationStore",
    "EvaluationRepository",
    "EvaluationRepositoryProtocol",
    # Engine
    "EvaluationEngine",
    # Metrics / Reports / Regressions
    "MetricsCalculator",
    "ReportGenerator",
    "RegressionDetector",
]
