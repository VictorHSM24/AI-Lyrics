"""Handlers auxiliares do Pipeline.

Handlers de apresentação, feedback, evaluation e contexto.

  - PresentationHandler: IntelligenceCompleted → PresentationRequested → PresentationCompleted
  - FeedbackHandler: PresentationCompleted → FeedbackRecorded
  - EvaluationHandler: FeedbackRecorded → EvaluationRecorded
  - ContextHandler: SpeechRecognized → (atualiza contexto, publica evento de contexto se necessário)
"""

from __future__ import annotations

import time
from typing import Any

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    EvaluationRecorded,
    FeedbackRecorded,
    IntelligenceCompleted,
    PresentationCompleted,
    PresentationRequested,
    SpeechRecognized,
)
from pipeline.handlers_base import BaseHandler
from pipeline.metadata import EventMetadata
from pipeline.policy import PipelinePolicy


# ---------------------------------------------------------------------------
# PresentationHandler
# ---------------------------------------------------------------------------


class PresentationHandler(BaseHandler):
    """Handler de apresentação (Holyrics).

    Recebe IntelligenceCompleted → produz PresentationRequested →
    PresentationCompleted.

    Não implementa apresentação. Delega para HolyricsClient injetado.
    Se não há Holyrics, simula apresentação (para teste).
    """

    name = "PresentationHandler"

    def __init__(
        self,
        bus: PipelineEventBus,
        policy: PipelinePolicy,
        session_id: str,
        holyrics: Any = None,
    ) -> None:
        super().__init__(bus, policy, session_id)
        self._holyrics = holyrics

    def handle(self, event: IntelligenceCompleted) -> None:
        """Processa IntelligenceCompleted → PresentationRequested → PresentationCompleted."""
        try:
            if not event.best_candidate_id:
                # Sem candidato — não apresentar
                return

            # Extrair book_id, chapter, verse do recommendation
            book_id = 0
            chapter = 0
            verse = None
            version = "ACF"
            if event.recommendation is not None:
                scores = getattr(event.recommendation, "scores", ()) or ()
                if scores:
                    best = scores[0]
                    book_id = getattr(best, "book_id", 0) or 0
                    chapter = getattr(best, "chapter", 0) or 0
                    verse = getattr(best, "verse", None)

            # Publicar PresentationRequested
            meta_req = self._next_meta(event.meta)
            self._bus.publish(PresentationRequested(
                meta=meta_req,
                candidate_id=event.best_candidate_id,
                book_id=book_id,
                chapter=chapter,
                verse=verse,
                version=version,
            ))

            # Executar apresentação
            start = time.time()
            status = "ok"
            verse_id = ""
            presented = True
            if self._holyrics is not None:
                try:
                    result = self._holyrics.show_verse(
                        book_id=book_id, chapter=chapter,
                        verse=verse, version=version,
                    )
                    status = getattr(result, "status", "ok")
                    verse_id = getattr(result, "verse_id", "")
                    presented = bool(status == "ok" or status)
                except Exception as exc:
                    status = "error"
                    presented = False

            # Publicar PresentationCompleted
            meta_comp = self._next_meta(meta_req)
            self._bus.publish(PresentationCompleted(
                meta=meta_comp,
                candidate_id=event.best_candidate_id,
                status=status,
                verse_id=verse_id,
                presented=presented,
            ))
        except Exception as exc:
            self._publish_error(event.meta, exc, recoverable=True)


# ---------------------------------------------------------------------------
# FeedbackHandler
# ---------------------------------------------------------------------------


class FeedbackHandler(BaseHandler):
    """Handler de feedback.

    Recebe PresentationCompleted → produz FeedbackRecorded.

    Não implementa feedback. Delega para FeedbackEngine injetado.
    Registra aceitação automática quando apresentação é bem-sucedida
    (apenas se policy.auto_record_feedback = True).
    """

    name = "FeedbackHandler"

    def __init__(
        self,
        bus: PipelineEventBus,
        policy: PipelinePolicy,
        session_id: str,
        feedback_engine: Any = None,
    ) -> None:
        super().__init__(bus, policy, session_id)
        self._feedback = feedback_engine

    def handle(self, event: PresentationCompleted) -> None:
        """Processa PresentationCompleted → FeedbackRecorded."""
        try:
            feedback_type = "accepted" if event.presented else "rejected"
            scope = "GLOBAL"
            query = ""

            if self._feedback is not None and self._policy.auto_record_feedback:
                # Delegar para FeedbackEngine (duck-typing)
                # Não acopla com tipos específicos — apenas tenta
                try:
                    # FeedbackEngine.process(event) — interface genérica
                    self._feedback.process(event)
                except Exception:
                    pass  # Feedback falhou — não quebra o pipeline

            meta = self._next_meta(event.meta)
            self._bus.publish(FeedbackRecorded(
                meta=meta,
                candidate_id=event.candidate_id,
                feedback_type=feedback_type,
                scope=scope,
                query=query,
            ))
        except Exception as exc:
            self._publish_error(event.meta, exc, recoverable=True)


# ---------------------------------------------------------------------------
# EvaluationHandler
# ---------------------------------------------------------------------------


class EvaluationHandler(BaseHandler):
    """Handler de avaliação contínua.

    Recebe FeedbackRecorded → produz EvaluationRecorded.

    Não implementa avaliação. Delega para EvaluationEngine injetado.
    Registra métricas apenas se policy.auto_record_evaluation = True.
    """

    name = "EvaluationHandler"

    def __init__(
        self,
        bus: PipelineEventBus,
        policy: PipelinePolicy,
        session_id: str,
        evaluation_engine: Any = None,
    ) -> None:
        super().__init__(bus, policy, session_id)
        self._evaluation = evaluation_engine

    def handle(self, event: FeedbackRecorded) -> None:
        """Processa FeedbackRecorded → EvaluationRecorded."""
        try:
            query = event.query
            classification = "UNKNOWN"
            candidate_id = event.candidate_id
            duration_ms = 0

            if self._evaluation is not None and self._policy.auto_record_evaluation:
                # Delegar para EvaluationEngine (duck-typing)
                try:
                    self._evaluation.record(event)
                except Exception:
                    pass  # Evaluation falhou — não quebra o pipeline

            meta = self._next_meta(event.meta)
            self._bus.publish(EvaluationRecorded(
                meta=meta,
                query=query,
                classification=classification,
                candidate_id=candidate_id,
                duration_ms=duration_ms,
            ))
        except Exception as exc:
            self._publish_error(event.meta, exc, recoverable=True)


# ---------------------------------------------------------------------------
# ContextHandler
# ---------------------------------------------------------------------------


class ContextHandler(BaseHandler):
    """Handler de contexto do sermão.

    Recebe SpeechRecognized → atualiza contexto via SermonContextEngine.

    Não publica evento próprio (contexto é estado, não evento).
    Apenas atualiza o contexto interno para uso pelo IntelligenceHandler.
    """

    name = "ContextHandler"

    def __init__(
        self,
        bus: PipelineEventBus,
        policy: PipelinePolicy,
        session_id: str,
        context_engine: Any = None,
        context: Any = None,
    ) -> None:
        super().__init__(bus, policy, session_id)
        self._context_engine = context_engine
        self._context = context

    @property
    def context(self) -> Any:
        """Retorna o contexto atual (atualizado pelo handler)."""
        return self._context

    def handle(self, event: SpeechRecognized) -> None:
        """Atualiza contexto com base no texto reconhecido.

        Não publica evento — contexto é estado interno.
        """
        try:
            if self._context_engine is not None and self._context is not None:
                # Delegar para SermonContextEngine (duck-typing)
                # engine.process(context, event) → novo contexto
                try:
                    self._context = self._context_engine.process(
                        self._context, event)
                except Exception:
                    pass  # Context falhou — não quebra o pipeline
        except Exception:
            pass  # ContextHandler nunca quebra o pipeline


__all__ = [
    "PresentationHandler",
    "FeedbackHandler",
    "EvaluationHandler",
    "ContextHandler",
]
