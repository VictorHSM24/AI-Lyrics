"""VersePresentationService — Sprint 18.

Elo que falta entre ReferenceDetected e HolyricsClient.show_verse().

Responsabilidade única:
    Receber ReferenceDetected
        → executar Searcher.search_by_reference()
        → publicar VerseResolving / VerseResolved
        → executar HolyricsClient.show_verse()
        → publicar VersePresented ou VersePresentationFailed

O que este serviço NÃO faz:
    - NÃO acessa STT.
    - NÃO acessa parser.
    - NÃO acessa frontend.
    - NÃO altera Health do componente Holyrics em caso de falha
      pontual de apresentação (Health só muda via health_check
      periódico do HealthService).
    - NÃO chama Holyrics diretamente do parser.
    - NÃO chama Holyrics do frontend.

Fluxo de eventos:
    ReferenceDetected
        ↓ (bus.subscribe)
    VersePresentationService._on_reference_detected()
        ↓
    publicar VerseResolving
        ↓
    Searcher.search_by_reference()
        ↓
    se falhar → publicar VersePresentationFailed (stage="search")
    se sucesso → publicar VerseResolved
        ↓
    HolyricsClient.show_verse()
        ↓
    se falhar → publicar VersePresentationFailed (stage="holyrics")
    se sucesso → publicar VersePresented

Configuração:
    - version: versão bíblica do config (config.state.default_version
      ou "ACF" como fallback).
    - quick_presentation: do AppSettings do frontend via PUT /configuration
      (não usado aqui — o backend usa o valor padrão do config).
    - token: do config.holyrics.token.
    - base_url: do config.holyrics.base_url.
    - timeout: do config.holyrics.timeout_ms.

Thread Safety:
    - O serviço é stateless após inicialização.
    - EventBus.publish é síncrono e thread-safe (Lock interno).
    - Searcher e HolyricsClient são thread-safe para chamadas
      concorrentes (cada um tem sua própria conexão/session).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from integracao_holyrics.client import HolyricsClient
from integracao_holyrics.exceptions import (
    HolyricsAPIError,
    HolyricsAuthError,
    HolyricsConnectionError,
    HolyricsError,
    HolyricsTimeoutError,
)
from busca.exceptions import SearchError
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    ReferenceAntecipada,
    ReferenceDetected,
    VersePresentationFailed,
    VersePresented,
    VerseResolved,
    VerseResolving,
)
from pipeline.metadata import EventMetadata

logger = logging.getLogger(__name__)

__all__ = ["VersePresentationService", "SearcherProtocol"]


# ---------------------------------------------------------------------------
# Protocol — para tipar o Searcher sem acoplar à classe concreta.
# ---------------------------------------------------------------------------


class SearcherProtocol(Protocol):
    """Interface mínima do Searcher usada por VersePresentationService.

    Permite testes com mocks sem depender da classe Searcher concreta.
    """

    def search_by_reference(
        self,
        book_name: str,
        chapter: int,
        verse: int | None = None,
        *,
        version: str | None = None,
    ) -> Any: ...


# ---------------------------------------------------------------------------
# VersePresentationService
# ---------------------------------------------------------------------------


class VersePresentationService:
    """Consome ReferenceDetected e apresenta o versículo no Holyrics.

    Args:
        searcher: Searcher (ou mock) para resolver a referência.
        holyrics: HolyricsClient (ou mock) para apresentar o versículo.
        bus: PipelineEventBus para assinar e publicar eventos.
        session_id: ID da sessão atual (para EventMetadata).
        version: versão bíblica padrão (ex.: "ACF").
        quick_presentation: se True, usa quick_presentation no Holyrics.
    """

    def __init__(
        self,
        searcher: SearcherProtocol,
        holyrics: HolyricsClient,
        bus: PipelineEventBus,
        session_id: str,
        version: str = "ACF",
        quick_presentation: bool = False,
    ) -> None:
        self._searcher = searcher
        self._holyrics = holyrics
        self._bus = bus
        self._session_id = session_id
        self._version = version
        self._quick = quick_presentation
        self._subscribed = False

        # Métricas internas (não expostas via evento — apenas para logging).
        self._total_detected = 0
        self._total_presented = 0
        self._total_failed = 0
        # Sprint 21.4 — Streaming First.
        # Métricas de antecipação.
        self._total_anticipations = 0
        self._total_confirmations = 0
        self._total_corrections = 0

        # Sprint 21.4 — Streaming First.
        # Track de antecipações pendentes por correlation_id, para dedup
        # com ReferenceDetected posterior. Cada entrada guarda o
        # (book_id, chapter, verse) da referência antecipada que já foi
        # apresentada no Holyrics. Quando o ReferenceDetected chegar:
        #   - se match: apenas confirmar (não reapresentar)
        #   - se não match: corrigir (apresentar a nova)
        # Lock para thread-safety (ReferenceAntecipada vem da thread do
        # StreamingSTT; ReferenceDetected pode vir da thread do
        # SpeechWorker ou da thread do IncrementalParser).
        import threading
        self._anticipation_lock = threading.Lock()
        self._pending_anticipations: dict[str, tuple[int, int, int]] = {}

        logger.info(
            "VersePresentationService initialized: version=%s quick=%s",
            version,
            quick_presentation,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inscreve no EventBus para receber ReferenceDetected e ReferenceAntecipada."""
        if self._subscribed:
            return
        self._bus.subscribe(ReferenceDetected, self._on_reference_detected)
        # Sprint 21.4 — Streaming First.
        # Assinar ReferenceAntecipada para apresentação antecipada durante
        # a fala, antes do silêncio fechar o segmento.
        self._bus.subscribe(ReferenceAntecipada, self._on_reference_anticipada)
        self._subscribed = True
        logger.info(
            "VersePresentationService started — subscribed to "
            "ReferenceDetected and ReferenceAntecipada."
        )

    def stop(self) -> None:
        """Desinscreve do EventBus."""
        if not self._subscribed:
            return
        self._bus.unsubscribe(ReferenceDetected, self._on_reference_detected)
        try:
            self._bus.unsubscribe(ReferenceAntecipada, self._on_reference_anticipada)
        except Exception:
            pass
        self._subscribed = False
        logger.info("VersePresentationService stopped.")

    # ------------------------------------------------------------------
    # Callback do EventBus — ponto de entrada do fluxo.
    # ------------------------------------------------------------------

    def _on_reference_anticipada(self, event: ReferenceAntecipada) -> None:
        """Recebe ReferenceAntecipada e apresenta antecipadamente (Sprint 21.4).

        Diferente de ReferenceDetected (definitivo), este evento é produzido
        DURANTE a fala e dispara a apresentação antecipada no Holyrics. A
        referência pode ser confirmada ou corrigida por um ReferenceDetected
        posterior (mesma correlation_id).

        Fluxo:
          1. Resolver versículo no Searcher (igual ao fluxo definitivo).
          2. Apresentar no Holyrics (show_verse).
          3. Registrar antecipação pendente para dedup com ReferenceDetected.

        Nota: ReferenceAntecipada tem os mesmos campos usados por
        _resolve_verse e _present_verse (.book, .chapter, .verse_start,
        .normalized_text, .meta, .correlation_id), então reusamos os
        métodos existentes via duck-typing.
        """
        self._total_anticipations += 1
        t0 = time.monotonic()

        logger.info(
            "ReferenceAntecipada recebida: %s (confidence=%.2f, completeness=%s, corr=%s)",
            event.normalized_text, event.confidence, event.completeness,
            event.correlation_id,
        )

        # Etapa 1 — Resolver versículo no Searcher.
        # _resolve_verse usa .book, .chapter, .verse_start, .normalized_text
        # — todos presentes em ReferenceAntecipada.
        search_result = self._resolve_verse(event)  # type: ignore[arg-type]
        if search_result is None:
            # _resolve_verse já publicou VersePresentationFailed.
            return

        # Etapa 2 — Apresentar no Holyrics.
        # _present_verse usa .meta, .correlation_id, .normalized_text
        # — todos presentes em ReferenceAntecipada.
        self._present_verse(event, search_result, t0)  # type: ignore[arg-type]

        # Etapa 3 — Registrar antecipação pendente para dedup.
        with self._anticipation_lock:
            self._pending_anticipations[event.correlation_id] = (
                search_result.book_id,
                search_result.chapter,
                search_result.verse or 0,
            )

    def _on_reference_detected(self, event: ReferenceDetected) -> None:
        """Recebe ReferenceDetected e orquestra resolução + apresentação.

        Sprint 21.4 — Streaming First:
        Se houver uma antecipação pendente para a mesma correlation_id:
          - Se a referência for IGUAL: apenas confirmar (não reapresentar).
            O versículo já está na tela do Holyrics; publicar VersePresented
            com holyrics_status="confirmed" para registrar no histórico.
          - Se a referência for DIFERENTE: corrigir (apresentar a nova).
            O pregador disse "Salmos 23" (antecipada) e depois "Salmos 23:4"
            (definitiva) — apresentar a definitiva.

        Este método é síncrono. Erros são capturados e convertidos em
        VersePresentationFailed — nunca propagam para o EventBus.
        """
        self._total_detected += 1
        t0 = time.monotonic()

        # Sprint 21.4 — verificar antecipação pendente.
        pending_record = None
        with self._anticipation_lock:
            pending_record = self._pending_anticipations.pop(
                event.correlation_id, None,
            )

        if pending_record is not None:
            # Há antecipação pendente — resolver para comparar.
            search_result = self._resolve_verse(event)
            if search_result is None:
                return

            anticipated_key = pending_record
            detected_key = (
                search_result.book_id,
                search_result.chapter,
                search_result.verse or 0,
            )

            if anticipated_key == detected_key:
                # Mesma referência — apenas confirmar (não reapresentar).
                self._confirm_anticipation(event, search_result, t0)
                return
            else:
                # Referência diferente — corrigir.
                logger.info(
                    "Sprint 21.4: corrigindo antecipação — "
                    "antecipada=%s vs definitiva=%s (corr=%s)",
                    anticipated_key, detected_key, event.correlation_id,
                )
                self._total_corrections += 1
                # Continuar com o fluxo normal para apresentar a nova.
                self._publish_resolving(event)
                self._publish_resolved(event, search_result)
                self._present_verse(event, search_result, t0)
                return

        # Fluxo normal (sem antecipação prévia).
        # Etapa 1 — Publicar VerseResolving.
        self._publish_resolving(event)

        # Etapa 2 — Resolver versículo no Searcher.
        search_result = self._resolve_verse(event)
        if search_result is None:
            # _resolve_verse já publicou VersePresentationFailed.
            return

        # Etapa 3 — Publicar VerseResolved.
        self._publish_resolved(event, search_result)

        # Etapa 4 — Apresentar no Holyrics.
        self._present_verse(event, search_result, t0)

    def _confirm_anticipation(
        self,
        event: ReferenceDetected,
        search_result: Any,
        t0: float,
    ) -> None:
        """Confirma uma antecipação sem reapresentar no Holyrics (Sprint 21.4).

        Conforme decisão do usuário: quando o ReferenceDetected tem a MESMA
        referência da antecipada, apenas confirmar — não chamar
        HolyricsClient.show_verse() novamente (evita piscar a tela).
        Publica VersePresented com holyrics_status="confirmed" para
        registrar no histórico do frontend.
        """
        self._total_confirmations += 1
        total_latency_ms = int((time.monotonic() - t0) * 1000)

        logger.info(
            "Sprint 21.4: confirmando antecipação — %s (corr=%s, total=%dms, "
            "sem reapresentar no Holyrics)",
            search_result.reference, event.correlation_id, total_latency_ms,
        )

        # Publicar VerseResolved (registra que a referência foi resolvida).
        self._publish_resolved(event, search_result)

        # Publicar VersePresented com status="confirmed" — sem chamar
        # Holyrics. O versículo já está na tela da antecipação.
        meta = EventMetadata.for_next(
            previous=event.meta,
            origin="VersePresentationService",
        )
        presented = VersePresented(
            meta=meta,
            book=search_result.book,
            book_id=search_result.book_id,
            chapter=search_result.chapter,
            verse=search_result.verse,
            version=self._version,
            reference=search_result.reference,
            quick_presentation=self._quick,
            holyrics_status="confirmed",
            holyrics_latency_ms=0,
            total_latency_ms=total_latency_ms,
        )
        self._bus.publish(presented)
        self._total_presented += 1
        logger.info(
            "VersePresented (confirmed): %s (total=%dms, correlation=%s)",
            search_result.reference,
            total_latency_ms,
            event.correlation_id,
        )

    # ------------------------------------------------------------------
    # Etapa 2 — Searcher
    # ------------------------------------------------------------------

    def _resolve_verse(self, event: ReferenceDetected) -> Any | None:
        """Chama Searcher.search_by_reference().

        Returns:
            SearchResult se encontrado, None se não (e publica
            VersePresentationFailed).
        """
        t_search_start = time.monotonic()
        try:
            result = self._searcher.search_by_reference(
                book_name=event.book,
                chapter=event.chapter,
                verse=event.verse_start if event.verse_start > 0 else None,
                version=self._version,
            )
        except SearchError as e:
            latency_ms = int((time.monotonic() - t_search_start) * 1000)
            logger.warning(
                "Searcher failed for %s: %s (%dms)",
                event.normalized_text,
                e,
                latency_ms,
            )
            self._publish_failure(
                event,
                stage="search",
                error_type="book_not_found",
                error_message=str(e),
                latency_ms=latency_ms,
            )
            return None
        except Exception as e:
            latency_ms = int((time.monotonic() - t_search_start) * 1000)
            logger.exception("Unexpected Searcher error for %s", event.normalized_text)
            self._publish_failure(
                event,
                stage="search",
                error_type="internal_error",
                error_message=f"searcher: {e}",
                latency_ms=latency_ms,
            )
            return None

        if result is None:
            latency_ms = int((time.monotonic() - t_search_start) * 1000)
            logger.info(
                "Searcher returned no result for %s (%dms)",
                event.normalized_text,
                latency_ms,
            )
            self._publish_failure(
                event,
                stage="search",
                error_type="verse_not_found",
                error_message=f"verse not found: {event.normalized_text}",
                latency_ms=latency_ms,
            )
            return None

        # Sucesso — log detalhado da latência do Searcher. O evento
        # VerseResolved (publicado a seguir) carrega a referência
        # resolvida; evitamos duplicar a referência no log.
        latency_ms = int((time.monotonic() - t_search_start) * 1000)
        logger.info(
            "Searcher resolved %s (%dms)",
            event.normalized_text,
            latency_ms,
        )
        return result

    # ------------------------------------------------------------------
    # Etapa 4 — Holyrics
    # ------------------------------------------------------------------

    def _present_verse(
        self,
        event: ReferenceDetected,
        search_result: Any,
        t0: float,
    ) -> None:
        """Chama HolyricsClient.show_verse() e publica VersePresented/Failed."""
        t_holyrics_start = time.monotonic()
        try:
            show_result = self._holyrics.show_verse(
                book_id=search_result.book_id,
                chapter=search_result.chapter,
                verse=search_result.verse,
                version=self._version,
                quick=self._quick,
            )
        except HolyricsAuthError as e:
            self._handle_holyrics_failure(
                event, search_result, "auth", str(e), t_holyrics_start, t0,
            )
            return
        except HolyricsTimeoutError as e:
            self._handle_holyrics_failure(
                event, search_result, "timeout", str(e), t_holyrics_start, t0,
            )
            return
        except HolyricsConnectionError as e:
            self._handle_holyrics_failure(
                event, search_result, "connection", str(e), t_holyrics_start, t0,
            )
            return
        except HolyricsAPIError as e:
            self._handle_holyrics_failure(
                event, search_result, "api", str(e), t_holyrics_start, t0,
            )
            return
        except HolyricsError as e:
            self._handle_holyrics_failure(
                event, search_result, "holyrics_error", str(e), t_holyrics_start, t0,
            )
            return
        except Exception as e:
            logger.exception("Unexpected Holyrics error for %s", event.normalized_text)
            self._handle_holyrics_failure(
                event, search_result, "internal_error", f"holyrics: {e}",
                t_holyrics_start, t0,
            )
            return

        holyrics_latency_ms = int((time.monotonic() - t_holyrics_start) * 1000)
        total_latency_ms = int((time.monotonic() - t0) * 1000)
        self._total_presented += 1

        logger.info(
            "Holyrics presented %s (status=%s, holyrics_latency=%dms, total=%dms)",
            search_result.reference,
            show_result.status,
            holyrics_latency_ms,
            total_latency_ms,
        )

        self._publish_presented(
            event=event,
            search_result=search_result,
            show_result=show_result,
            holyrics_latency_ms=holyrics_latency_ms,
            total_latency_ms=total_latency_ms,
        )

    def _handle_holyrics_failure(
        self,
        event: ReferenceDetected,
        search_result: Any,
        error_type: str,
        error_message: str,
        t_holyrics_start: float,
        t0: float,
    ) -> None:
        """Publica VersePresentationFailed para erros do Holyrics."""
        holyrics_latency_ms = int((time.monotonic() - t_holyrics_start) * 1000)
        total_latency_ms = int((time.monotonic() - t0) * 1000)
        self._total_failed += 1
        logger.warning(
            "Holyrics failed for %s: %s=%s (holyrics_latency=%dms, total=%dms)",
            search_result.reference,
            error_type,
            error_message,
            holyrics_latency_ms,
            total_latency_ms,
        )
        self._publish_failure(
            event=event,
            stage="holyrics",
            error_type=error_type,
            error_message=error_message,
            latency_ms=total_latency_ms,
            search_result=search_result,
        )

    # ------------------------------------------------------------------
    # Publicação de eventos
    # ------------------------------------------------------------------

    def _publish_resolving(self, source: ReferenceDetected) -> None:
        """Publica VerseResolving (causation = ReferenceDetected)."""
        meta = EventMetadata.for_next(
            previous=source.meta,
            origin="VersePresentationService",
        )
        event = VerseResolving(
            meta=meta,
            book=source.book,
            book_id=source.book_id,
            chapter=source.chapter,
            verse_start=source.verse_start,
            verse_end=source.verse_end,
            normalized_text=source.normalized_text,
        )
        self._bus.publish(event)
        logger.info(
            "VerseResolving: %s (correlation=%s)",
            source.normalized_text,
            source.correlation_id,
        )

    def _publish_resolved(
        self,
        source: ReferenceDetected,
        search_result: Any,
    ) -> None:
        """Publica VerseResolved (causation = ReferenceDetected)."""
        meta = EventMetadata.for_next(
            previous=source.meta,
            origin="VersePresentationService",
        )
        event = VerseResolved(
            meta=meta,
            book=search_result.book,
            book_id=search_result.book_id,
            chapter=search_result.chapter,
            verse=search_result.verse,
            version=search_result.version,
            verse_text=search_result.text,
            reference=search_result.reference,
            search_ms=0,  # já logado; evento carrega referência textual
        )
        self._bus.publish(event)
        logger.info(
            "VerseResolved: %s = \"%s...\" (correlation=%s)",
            search_result.reference,
            search_result.text[:50],
            source.correlation_id,
        )

    def _publish_presented(
        self,
        event: ReferenceDetected,
        search_result: Any,
        show_result: Any,
        holyrics_latency_ms: int,
        total_latency_ms: int,
    ) -> None:
        """Publica VersePresented (causation = ReferenceDetected)."""
        meta = EventMetadata.for_next(
            previous=event.meta,
            origin="VersePresentationService",
        )
        presented = VersePresented(
            meta=meta,
            book=search_result.book,
            book_id=search_result.book_id,
            chapter=search_result.chapter,
            verse=search_result.verse,
            version=self._version,
            reference=search_result.reference,
            quick_presentation=self._quick,
            holyrics_status=show_result.status,
            holyrics_latency_ms=holyrics_latency_ms,
            total_latency_ms=total_latency_ms,
        )
        self._bus.publish(presented)
        logger.info(
            "VersePresented: %s (status=%s, total=%dms, correlation=%s)",
            search_result.reference,
            show_result.status,
            total_latency_ms,
            event.correlation_id,
        )

    def _publish_failure(
        self,
        event: ReferenceDetected,
        stage: str,
        error_type: str,
        error_message: str,
        latency_ms: int,
        search_result: Any | None = None,
    ) -> None:
        """Publica VersePresentationFailed (causation = ReferenceDetected).

        NÃO altera Health — falhas pontuais de apresentação não indicam
        que o Holyrics está indisponível. Health só muda via health_check
        periódico do HealthService.
        """
        self._total_failed += 1
        meta = EventMetadata.for_next(
            previous=event.meta,
            origin="VersePresentationService",
        )
        reference = (
            search_result.reference if search_result is not None
            else event.normalized_text
        )
        failed = VersePresentationFailed(
            meta=meta,
            book=event.book,
            book_id=event.book_id,
            chapter=event.chapter,
            verse=event.verse_start,
            reference=reference,
            failure_stage=stage,
            error_type=error_type,
            error_message=error_message,
            latency_ms=latency_ms,
        )
        self._bus.publish(failed)
        logger.warning(
            "VersePresentationFailed: %s stage=%s error_type=%s (%dms, correlation=%s)",
            reference,
            stage,
            error_type,
            latency_ms,
            event.correlation_id,
        )
