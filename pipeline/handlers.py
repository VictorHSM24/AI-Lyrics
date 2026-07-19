"""Handlers do Pipeline — reexporta todos os handlers.

Este módulo apenas reexporta os handlers de handlers_base.py e
handlers_aux.py para conveniência de importação.
"""

from __future__ import annotations

from pipeline.handlers_aux import (
    ContextHandler,
    EvaluationHandler,
    FeedbackHandler,
    PresentationHandler,
)
from pipeline.handlers_base import (
    BaseHandler,
    IntelligenceHandler,
    RankingHandler,
    RecognitionHandler,
    SearchHandler,
)


__all__ = [
    "BaseHandler",
    "RecognitionHandler",
    "SearchHandler",
    "RankingHandler",
    "IntelligenceHandler",
    "PresentationHandler",
    "FeedbackHandler",
    "EvaluationHandler",
    "ContextHandler",
]
