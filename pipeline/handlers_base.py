"""Handlers do Pipeline — base e handlers de fluxo principal.

Cada Handler:
  - recebe um evento
  - executa apenas sua responsabilidade
  - publica novo evento (com EventMetadata.for_next preservando
    correlation_id, session_id e encadeando causation_id)

Nenhum Handler chama outro Handler diretamente. Toda comunicação
via EventBus.

Handlers de fluxo principal (este arquivo):
  - RecognitionHandler: SpeechSegmentReceived → SpeechRecognized
  - SearchHandler: SpeechRecognized → SearchRequested → SearchCompleted
  - RankingHandler: SearchCompleted → RankingCompleted
  - IntelligenceHandler: RankingCompleted → IntelligenceCompleted

Handlers auxiliares (handlers_aux.py):
  - PresentationHandler: IntelligenceCompleted → PresentationRequested → PresentationCompleted
  - FeedbackHandler: PresentationCompleted → FeedbackRecorded
  - EvaluationHandler: FeedbackRecorded → EvaluationRecorded
  - ContextHandler: SpeechRecognized → (atualiza contexto, sem evento próprio)
"""

from __future__ import annotations

import time
from typing import Any, Callable

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    IntelligenceCompleted,
    PipelineError,
    RankingCompleted,
    SearchCompleted,
    SearchRequested,
    SpeechRecognized,
    SpeechSegmentReceived,
)
from pipeline.metadata import EventMetadata
from pipeline.policy import PipelinePolicy


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class BaseHandler:
    """Base comum para todos os Handlers.

    Fornece:
      - acesso ao bus, policy, session_id
      - helper para criar EventMetadata do próximo evento
      - helper para publicar erros
    """

    name: str = "BaseHandler"

    def __init__(
        self,
        bus: PipelineEventBus,
        policy: PipelinePolicy,
        session_id: str,
    ) -> None:
        self._bus = bus
        self._policy = policy
        self._session_id = session_id

    @property
    def bus(self) -> PipelineEventBus:
        return self._bus

    @property
    def policy(self) -> PipelinePolicy:
        return self._policy

    @property
    def session_id(self) -> str:
        return self._session_id

    def _next_meta(
        self, previous_meta: EventMetadata, metadata: tuple = (),
    ) -> EventMetadata:
        """Cria EventMetadata para o próximo evento do fluxo."""
        return EventMetadata.for_next(
            previous=previous_meta,
            origin=self.name,
            metadata=metadata,
        )

    def _publish_error(
        self,
        previous_meta: EventMetadata,
        error: Exception,
        recoverable: bool = True,
    ) -> None:
        """Publica PipelineError preservando correlation_id."""
        meta = EventMetadata.for_next(
            previous=previous_meta,
            origin=self.name,
        )
        self._bus.publish(PipelineError(
            meta=meta,
            error_type=type(error).__name__,
            error_message=str(error),
            handler_name=self.name,
            recoverable=recoverable,
        ))


# ---------------------------------------------------------------------------
# RecognitionHandler
# ---------------------------------------------------------------------------


class RecognitionHandler(BaseHandler):
    """Handler de reconhecimento de fala.

    Recebe SpeechSegmentReceived → produz SpeechRecognized.

    Não implementa STT. Apenas delega para o STT injetado e
    publica o resultado. Se não há STT, usa o texto do segmento
    (para teste/integração).
    """

    name = "RecognitionHandler"

    def __init__(
        self,
        bus: PipelineEventBus,
        policy: PipelinePolicy,
        session_id: str,
        stt: Any = None,  # STT instance (opcional)
    ) -> None:
        super().__init__(bus, policy, session_id)
        self._stt = stt

    def handle(self, event: SpeechSegmentReceived) -> None:
        """Processa SpeechSegmentReceived → publica SpeechRecognized."""
        try:
            start = time.time()
            text = ""
            language = ""
            confidence = 0.0

            if self._stt is not None:
                # Delegar para STT real (duck-typing)
                # STT.transcribe(segment) → STTResult
                result = self._stt.transcribe(event)
                text = getattr(result, "text", "")
                language = getattr(result, "language", "")
                confidence = getattr(result, "confidence", 0.0)
            else:
                # Sem STT — usar metadata do evento (para testes)
                text = dict(event.meta.metadata).get("text", "")
                confidence = float(dict(event.meta.metadata).get("confidence", 0.0))

            processing_ms = int((time.time() - start) * 1000)
            meta = self._next_meta(event.meta)
            self._bus.publish(SpeechRecognized(
                meta=meta,
                text=text,
                language=language,
                confidence=confidence,
                processing_ms=processing_ms,
            ))
        except Exception as exc:
            self._publish_error(event.meta, exc, recoverable=True)


# ---------------------------------------------------------------------------
# SearchHandler
# ---------------------------------------------------------------------------


class SearchHandler(BaseHandler):
    """Handler de busca.

    Recebe SpeechRecognized → produz SearchRequested → SearchCompleted.

    Não implementa busca. Delega para o Searcher injetado.
    Se não há Searcher, produz resultados vazios (para teste).
    """

    name = "SearchHandler"

    def __init__(
        self,
        bus: PipelineEventBus,
        policy: PipelinePolicy,
        session_id: str,
        searcher: Any = None,
        parser: Any = None,
    ) -> None:
        super().__init__(bus, policy, session_id)
        self._searcher = searcher
        self._parser = parser

    def handle(self, event: SpeechRecognized) -> None:
        """Processa SpeechRecognized → SearchRequested → SearchCompleted."""
        try:
            query = event.text.strip()
            if not query:
                # Query vazia — publicar SearchCompleted vazio
                meta_req = self._next_meta(event.meta)
                self._bus.publish(SearchRequested(
                    meta=meta_req, query="",
                ))
                meta_comp = self._next_meta(meta_req)
                self._bus.publish(SearchCompleted(
                    meta=meta_comp, query="",
                ))
                return

            # Parsear intent (se parser disponível)
            intent_action = "search"
            intent_book = None
            intent_chapter = None
            intent_verse = None
            if self._parser is not None:
                try:
                    intent = self._parser.parse(query)
                    intent_action = getattr(intent, "action", "search")
                    intent_book = getattr(intent, "book", None)
                    intent_chapter = getattr(intent, "chapter", None)
                    intent_verse = getattr(intent, "verse", None)
                except Exception:
                    pass  # Parser falhou — usar defaults

            # Publicar SearchRequested
            meta_req = self._next_meta(event.meta)
            self._bus.publish(SearchRequested(
                meta=meta_req,
                query=query,
                intent_action=intent_action,
                intent_book=intent_book,
                intent_chapter=intent_chapter,
                intent_verse=intent_verse,
            ))

            # Executar busca
            start = time.time()
            results = ()
            if self._searcher is not None:
                raw_results = self._searcher.search(query)
                results = tuple(raw_results)
            search_ms = int((time.time() - start) * 1000)

            # Publicar SearchCompleted
            meta_comp = self._next_meta(meta_req)
            self._bus.publish(SearchCompleted(
                meta=meta_comp,
                query=query,
                results=results,
                result_count=len(results),
                search_ms=search_ms,
            ))
        except Exception as exc:
            self._publish_error(event.meta, exc, recoverable=True)


# ---------------------------------------------------------------------------
# RankingHandler
# ---------------------------------------------------------------------------


class RankingHandler(BaseHandler):
    """Handler de ranking.

    Recebe SearchCompleted → produz RankingCompleted.

    Não implementa ranking. Transforma SearchResults em CandidateInfos.
    Delega cálculo de score para RankingPolicy se disponível.
    """

    name = "RankingHandler"

    def __init__(
        self,
        bus: PipelineEventBus,
        policy: PipelinePolicy,
        session_id: str,
        ranking_policy: Any = None,
    ) -> None:
        super().__init__(bus, policy, session_id)
        self._ranking_policy = ranking_policy

    def handle(self, event: SearchCompleted) -> None:
        """Processa SearchCompleted → RankingCompleted."""
        try:
            candidates = []
            for r in event.results:
                # Duck-typing: SearchResult → CandidateInfo
                candidate_id = getattr(r, "reference", "") or getattr(r, "candidate_id", "")
                base_score = getattr(r, "score", 0.0)
                book = getattr(r, "book", None) or ""
                chapter = getattr(r, "chapter", 0) or 0
                verse = getattr(r, "verse", 0) or 0
                display = getattr(r, "reference", "") or f"{book} {chapter}:{verse}"
                # CandidateInfo é frozen dataclass do intelligence
                from intelligence.dtos import CandidateInfo
                candidates.append(CandidateInfo(
                    candidate_id=candidate_id,
                    base_score=base_score,
                    book=book,
                    chapter=chapter,
                    verse=verse,
                    display=display,
                ))

            # Limitar candidatos
            max_cand = self._policy.max_candidates_per_ranking
            candidates = candidates[:max_cand]

            meta = self._next_meta(event.meta)
            self._bus.publish(RankingCompleted(
                meta=meta,
                query=event.query,
                ranked_candidates=tuple(candidates),
                candidate_count=len(candidates),
            ))
        except Exception as exc:
            self._publish_error(event.meta, exc, recoverable=True)


# ---------------------------------------------------------------------------
# IntelligenceHandler
# ---------------------------------------------------------------------------


class IntelligenceHandler(BaseHandler):
    """Handler de Sermon Intelligence.

    Recebe RankingCompleted → produz IntelligenceCompleted.

    Não implementa inteligência. Delega para SermonIntelligenceEngine.
    Preserva Evidences produzidas pelo Intelligence (não as modifica).
    """

    name = "IntelligenceHandler"

    def __init__(
        self,
        bus: PipelineEventBus,
        policy: PipelinePolicy,
        session_id: str,
        intelligence_engine: Any = None,
        context: Any = None,
        feedback_summaries: dict | None = None,
        evaluation_metrics: Any = None,
    ) -> None:
        super().__init__(bus, policy, session_id)
        self._intelligence = intelligence_engine
        self._context = context
        self._feedback_summaries = feedback_summaries or {}
        self._evaluation_metrics = evaluation_metrics

    def handle(self, event: RankingCompleted) -> None:
        """Processa RankingCompleted → IntelligenceCompleted."""
        try:
            from intelligence.dtos import IntelligenceRequest

            recommendation = None
            best_candidate_id = ""
            confidence_level = ""

            if self._intelligence is not None and event.ranked_candidates:
                request = IntelligenceRequest(
                    query=event.query,
                    context=self._context,
                    candidates=event.ranked_candidates,
                    feedback_summaries=self._feedback_summaries,
                    evaluation_metrics=self._evaluation_metrics,
                )
                recommendation = self._intelligence.recommend(request)
                best_candidate_id = getattr(recommendation, "best_candidate_id", "")
                conf = getattr(recommendation, "confidence_level", "")
                confidence_level = str(conf) if conf else ""

            meta = self._next_meta(event.meta)
            self._bus.publish(IntelligenceCompleted(
                meta=meta,
                query=event.query,
                recommendation=recommendation,
                best_candidate_id=best_candidate_id,
                confidence_level=confidence_level,
            ))
        except Exception as exc:
            self._publish_error(event.meta, exc, recoverable=True)


__all__ = [
    "BaseHandler",
    "RecognitionHandler",
    "SearchHandler",
    "RankingHandler",
    "IntelligenceHandler",
]
