"""BiblicalNLUService — interpretação de linguagem natural bíblica (Sprint 17).

Responsabilidades:
  - Assinar eventos SpeechTranscribed do EventBus.
  - Executar o Parser determinístico (sem LLM) para interpretar o texto.
  - Publicar ReferenceDetected, ReferenceInvalid, ou IntentUnknown.
  - Totalmente stateless — nenhum estado entre invocações.

Fluxo:
  SpeechTranscribed
    → BiblicalNLUService.on_transcribed()
    → Parser.parse(text)
    → Intent(action, book, book_id, chapter, verse, confidence)
    → Se action="show" e válido: ReferenceDetected
    → Se action="show" mas inválido: ReferenceInvalid
    → Se action="none": IntentUnknown

Performance:
  - Objetivo: < 50ms por interpretação.
  - Parser é determinístico (regex + tabela de livros), sem rede nem I/O.

Thread Safety:
  - O serviço é stateless após inicialização.
  - EventBus.publish é thread-safe (Lock interno).
  - Parser é stateless (apenas leitura de tabelas internas).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from core.types import Intent
from parser.parser import Parser
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    IntentUnknown,
    ReferenceDetected,
    ReferenceInvalid,
    SpeechTranscribed,
)
from pipeline.metadata import EventMetadata

logger = logging.getLogger(__name__)

__all__ = ["BiblicalNLUService"]


# ---------------------------------------------------------------------------
# Limites de validação (capítulos/versículos)
# ---------------------------------------------------------------------------

_MAX_CHAPTER = 200  # nenhum livro tem mais de 176 capítulos (Salmos)
_MAX_VERSE = 200    # nenhum capítulo tem mais de 176 versículos


class BiblicalNLUService:
    """Serviço de interpretação bíblica que consome SpeechTranscribed.

    Args:
        parser: instância de Parser (determinístico, stateless).
        bus: PipelineEventBus para assinar e publicar eventos.
        session_id: ID da sessão atual (para EventMetadata).
    """

    def __init__(
        self,
        parser: Parser,
        bus: PipelineEventBus,
        session_id: str,
    ) -> None:
        self._parser = parser
        self._bus = bus
        self._session_id = session_id
        self._subscribed = False

        # Métricas
        self._total_processed = 0
        self._total_detected = 0
        self._total_invalid = 0
        self._total_unknown = 0
        self._total_latency_ms = 0

        logger.info("BiblicalNLUService initialized.")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inscreve no EventBus para receber SpeechTranscribed."""
        if self._subscribed:
            return
        self._bus.subscribe(SpeechTranscribed, self._on_transcribed)
        self._subscribed = True
        logger.info("BiblicalNLUService started — subscribed to SpeechTranscribed.")

    def stop(self) -> None:
        """Desinscreve do EventBus."""
        if not self._subscribed:
            return
        # EventBus não tem unsubscribe, mas marcamos como parado.
        self._subscribed = False
        logger.info("BiblicalNLUService stopped.")

    # ------------------------------------------------------------------
    # Callback do EventBus
    # ------------------------------------------------------------------

    def _on_transcribed(self, event: SpeechTranscribed) -> None:
        """Recebe SpeechTranscribed e processa o texto."""
        text = event.text
        if not text:
            self._publish_unknown(event, text, reason="empty_text")
            return

        t0 = time.monotonic()
        self._total_processed += 1

        try:
            intent = self._parser.parse(text)
        except Exception as e:
            logger.error("Parser error: %s — treating as unknown", e)
            self._publish_unknown(event, text, reason="parser_error")
            return

        latency_ms = int((time.monotonic() - t0) * 1000)
        self._total_latency_ms += latency_ms

        # Processar resultado do parser.
        self._process_intent(intent, event, latency_ms)

    # ------------------------------------------------------------------
    # Processamento do Intent
    # ------------------------------------------------------------------

    def _process_intent(
        self,
        intent: Intent,
        source_event: SpeechTranscribed,
        latency_ms: int,
    ) -> None:
        """Processa o Intent produzido pelo Parser e publica o evento apropriado."""
        if intent.action == "show" and intent.book_id is not None:
            # Referência detectada — validar capítulo/versículo.
            validation = self._validate_reference(intent)
            if validation is None:
                # Referência válida.
                self._publish_detected(intent, source_event, latency_ms)
            else:
                # Referência inválida.
                self._publish_invalid(intent, source_event, validation)
        elif intent.action in ("next", "previous", "jump"):
            # Navegação — não é referência bíblica direta, mas é comando.
            # Para Sprint 17, tratamos como unknown (não implementamos navegação).
            self._publish_unknown(source_event, intent.raw, reason="navigation_not_supported")
        elif intent.action == "uncertain":
            # Parser não tem certeza — encaminharia ao LLM em sprint futura.
            self._publish_unknown(source_event, intent.raw, reason="uncertain")
        else:
            # action="none" — não é comando bíblico.
            self._publish_unknown(source_event, intent.raw, reason="no_pattern")

    # ------------------------------------------------------------------
    # Validação
    # ------------------------------------------------------------------

    def _validate_reference(self, intent: Intent) -> str | None:
        """Valida capítulo e versículo do Intent.

        Returns:
            None se válido, ou string com motivo da invalidade.
        """
        chapter = intent.chapter
        verse = intent.verse

        if chapter is not None and chapter <= 0:
            return "zero_chapter"
        if chapter is not None and chapter > _MAX_CHAPTER:
            return "invalid_chapter"
        if verse is not None and verse <= 0:
            return "zero_verse"
        if verse is not None and verse > _MAX_VERSE:
            return "invalid_verse"
        return None

    # ------------------------------------------------------------------
    # Publicação de eventos
    # ------------------------------------------------------------------

    def _publish_detected(
        self,
        intent: Intent,
        source: SpeechTranscribed,
        latency_ms: int,
    ) -> None:
        """Publica ReferenceDetected."""
        self._total_detected += 1

        meta = EventMetadata.for_initial(
            session_id=self._session_id,
            origin="BiblicalNLUService",
        )

        chapter = intent.chapter or 0
        verse = intent.verse or 0
        normalized = self._normalize_reference(intent.book or "", chapter, verse)

        event = ReferenceDetected(
            meta=meta,
            intent="OPEN_REFERENCE",
            book=intent.book or "",
            book_id=intent.book_id or 0,
            chapter=chapter,
            verse_start=verse,
            verse_end=verse,
            confidence=intent.confidence,
            raw_text=intent.raw,
            normalized_text=normalized,
        )
        self._bus.publish(event)
        logger.info(
            "ReferenceDetected: %s (confidence=%.2f, latency=%dms)",
            normalized,
            intent.confidence,
            latency_ms,
        )

    def _publish_invalid(
        self,
        intent: Intent,
        source: SpeechTranscribed,
        reason: str,
    ) -> None:
        """Publica ReferenceInvalid."""
        self._total_invalid += 1

        meta = EventMetadata.for_initial(
            session_id=self._session_id,
            origin="BiblicalNLUService",
        )

        event = ReferenceInvalid(
            meta=meta,
            book=intent.book or "",
            book_id=intent.book_id or 0,
            chapter=intent.chapter or 0,
            verse_start=intent.verse or 0,
            reason=reason,
            raw_text=intent.raw,
        )
        self._bus.publish(event)
        logger.info(
            "ReferenceInvalid: %s — %s",
            intent.raw[:60],
            reason,
        )

    def _publish_unknown(
        self,
        source: SpeechTranscribed,
        raw_text: str,
        reason: str,
    ) -> None:
        """Publica IntentUnknown."""
        self._total_unknown += 1

        meta = EventMetadata.for_initial(
            session_id=self._session_id,
            origin="BiblicalNLUService",
        )

        event = IntentUnknown(
            meta=meta,
            raw_text=raw_text,
            reason=reason,
        )
        self._bus.publish(event)
        logger.debug("IntentUnknown: %r — %s", raw_text[:60], reason)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_reference(book: str, chapter: int, verse: int) -> str:
        """Gera texto normalizado da referência (ex.: "joao 3:16")."""
        import unicodedata
        import re

        # Normalizar nome do livro: lowercase, sem diacritics.
        nfkd = unicodedata.normalize("NFKD", book)
        without_diacritics = "".join(c for c in nfkd if not unicodedata.combining(c))
        book_norm = without_diacritics.strip().lower()
        book_norm = re.sub(r"\s+", " ", book_norm)

        if verse > 0:
            return f"{book_norm} {chapter}:{verse}"
        return f"{book_norm} {chapter}"

    # ------------------------------------------------------------------
    # Estado e métricas
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._subscribed

    @property
    def total_processed(self) -> int:
        return self._total_processed

    @property
    def total_detected(self) -> int:
        return self._total_detected

    @property
    def total_invalid(self) -> int:
        return self._total_invalid

    @property
    def total_unknown(self) -> int:
        return self._total_unknown

    @property
    def avg_latency_ms(self) -> float:
        if self._total_processed == 0:
            return 0.0
        return self._total_latency_ms / self._total_processed
