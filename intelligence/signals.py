"""Sinais tipados do Sermon Intelligence.

Cada sinal representa um fator analisado independente. Todos herdam de
IntelligenceSignal e são frozen dataclass (imutáveis).

Design:
  - Cada sinal retorna apenas: value, weight, explanation.
  - Nenhum sinal altera outro.
  - Sinais são independentes e podem ser combinados pelo SignalCombiner.
  - Novos sinais podem ser adicionados sem quebrar existentes.

Sinais implementados (Fase 11):
  - ContextSignal: contexto do sermão favorece o candidato?
  - FeedbackSignal: há feedback aprendido para o candidato?
  - ContinuitySignal: o candidato continua a sequência de referências?
  - ReferenceSignal: o candidato é a última referência resolvida?
  - ThemeSignal: o candidato corresponde a temas recentes?
  - BookSignal: o candidato é do livro ativo ou recentemente mencionado?
  - ConfidenceSignal: sinal agregado de confiança.
  - EvaluationSignal: estatísticas de avaliação favorecem o candidato?

Sinais futuros (apenas preparados):
  - SemanticSignal, OperatorSignal, ChurchProfileSignal,
    LanguageSignal, TemporalSignal, EmotionSignal.
"""

from __future__ import annotations

from dataclasses import dataclass

from intelligence.dtos import IntelligenceSignal


# ---------------------------------------------------------------------------
# Sinais implementados (Fase 11)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextSignal(IntelligenceSignal):
    """Sinal de contexto do sermão.

    Indica se o contexto atual (livro/capítulo ativo) favorece o candidato.
    """

    signal_type: str = "context"


@dataclass(frozen=True)
class FeedbackSignal(IntelligenceSignal):
    """Sinal de feedback aprendido.

    Indica se há feedback operacional que favorece ou desfavorece o candidato.
    """

    signal_type: str = "feedback"


@dataclass(frozen=True)
class ContinuitySignal(IntelligenceSignal):
    """Sinal de continuidade de referências.

    Indica se o candidato continua a sequência lógica de referências
    recentes (ex.: João 3 → João 3:17).
    """

    signal_type: str = "continuity"


@dataclass(frozen=True)
class ReferenceSignal(IntelligenceSignal):
    """Sinal de referência resolvida.

    Indica se o candidato é exatamente a última referência resolvida
    (repetição direta).
    """

    signal_type: str = "reference"


@dataclass(frozen=True)
class ThemeSignal(IntelligenceSignal):
    """Sinal temático.

    Indica se o candidato corresponde a temas recentemente mencionados
    no sermão.
    """

    signal_type: str = "theme"


@dataclass(frozen=True)
class BookSignal(IntelligenceSignal):
    """Sinal de livro.

    Indica se o candidato pertence ao livro ativo ou a livros recentemente
    mencionados.
    """

    signal_type: str = "book"


@dataclass(frozen=True)
class ConfidenceSignal(IntelligenceSignal):
    """Sinal de confiança agregada.

    Indica o nível de confiança combinado a partir de outros sinais.
    """

    signal_type: str = "confidence"


@dataclass(frozen=True)
class EvaluationSignal(IntelligenceSignal):
    """Sinal estatístico (Continuous Evaluation).

    Indica se estatísticas de avaliação favorecem o candidato (ex.:
    precisão alta para este tipo de consulta).
    """

    signal_type: str = "evaluation"


# ---------------------------------------------------------------------------
# Sinais futuros (apenas preparados — não implementados)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SemanticSignal(IntelligenceSignal):
    """Sinal semântico (futuro).

    Reservado para futura análise semântica da consulta.
    """

    signal_type: str = "semantic"


@dataclass(frozen=True)
class OperatorSignal(IntelligenceSignal):
    """Sinal do operador (futuro).

    Reservado para futura análise de perfil do operador.
    """

    signal_type: str = "operator"


@dataclass(frozen=True)
class ChurchProfileSignal(IntelligenceSignal):
    """Sinal de perfil da igreja (futuro).

    Reservado para futura análise de perfil da congregação.
    """

    signal_type: str = "church_profile"


@dataclass(frozen=True)
class LanguageSignal(IntelligenceSignal):
    """Sinal de idioma (futuro).

    Reservado para futura análise de idioma/dialeto.
    """

    signal_type: str = "language"


@dataclass(frozen=True)
class TemporalSignal(IntelligenceSignal):
    """Sinal temporal (futuro).

    Reservado para futura análise de padrões temporais.
    """

    signal_type: str = "temporal"


@dataclass(frozen=True)
class EmotionSignal(IntelligenceSignal):
    """Sinal emocional (futuro).

    Reservado para futura análise de tom emocional do sermão.
    """

    signal_type: str = "emotion"


# ---------------------------------------------------------------------------
# Registry de tipos de sinal
# ---------------------------------------------------------------------------

# Sinais ativos (implementados)
ACTIVE_SIGNAL_TYPES: tuple[str, ...] = (
    "context",
    "feedback",
    "continuity",
    "reference",
    "theme",
    "book",
    "confidence",
    "evaluation",
)

# Sinais futuros (preparados)
FUTURE_SIGNAL_TYPES: tuple[str, ...] = (
    "semantic",
    "operator",
    "church_profile",
    "language",
    "temporal",
    "emotion",
)

# Todos os sinais
ALL_SIGNAL_TYPES: tuple[str, ...] = ACTIVE_SIGNAL_TYPES + FUTURE_SIGNAL_TYPES


__all__ = [
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
]
