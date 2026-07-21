"""semantic/context_engine.py — Construção de contexto (Sprint 20, Etapa 6).

Responsabilidade:
  - Construir SemanticContext a partir do histórico de eventos.
  - Incluir últimos 30-60s de fala.
  - Incluir última referência encontrada (livro/capítulo atual).
  - Incluir histórico recente.
  - Sprint 21 — incluir SermonContext (memória contínua da pregação).
  - Não consultar LLM, não publicar eventos, não acessar Holyrics.

Implementação:
  - Consulta bus.history() para encontrar SpeechPartial/Updated recentes.
  - Consulta bus.history() para encontrar último ReferenceDetected.
  - Sprint 21: consulta sermon_context_fn() para obter SermonContext vivo.
  - Janela configurável (default 45s).

Sprint 20 — Semantic Understanding Engine.
Sprint 21 — Sermon Memory Engine (integração).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from pipeline.events import (
    ReferenceDetected,
    SpeechPartial,
    SpeechPartialUpdated,
)
from semantic.types import SemanticContext

logger = logging.getLogger(__name__)

__all__ = ["ContextEngine"]


class ContextEngine:
    """Constrói SemanticContext a partir do histórico de eventos.

    Args:
        history_fn: callable que retorna lista de eventos (bus.history()).
        window_seconds: janela de fala recente em segundos (default 45).
        max_recent_chars: máximo de caracteres de fala recente (default 500).
        sermon_context_fn: callable opcional (Sprint 21) que retorna
            SermonContext atual, ou None se a memória de sermão não
            estiver ativa. Se fornecido, enriquece o SemanticContext
            com livro/capítulo/tema/entidades do sermão.
    """

    def __init__(
        self,
        history_fn: Any,
        window_seconds: float = 45.0,
        max_recent_chars: int = 500,
        sermon_context_fn: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._history_fn = history_fn
        self._window_seconds = window_seconds
        self._max_recent_chars = max_recent_chars
        self._sermon_context_fn = sermon_context_fn

    def set_sermon_context_fn(self, fn: Callable[[], Any]) -> None:
        """Define ou atualiza o callable de SermonContext (Sprint 21)."""
        self._sermon_context_fn = fn

    def build(
        self,
        current_text: str,
        session_id: str = "",
        correlation_id: str = "",
    ) -> SemanticContext:
        """Constrói o contexto para o texto atual."""
        now = time.time()
        cutoff = now - self._window_seconds

        # Coletar eventos relevantes do histórico.
        recent_texts: list[str] = []
        last_book = ""
        last_chapter = 0
        last_reference = ""

        try:
            events = self._history_fn()
        except Exception as e:
            logger.warning("ContextEngine: failed to read history: %s", e)
            events = []

        for event in events:
            # Última referência detectada (de qualquer origem — parser ou resolver).
            if isinstance(event, ReferenceDetected):
                last_book = event.book
                last_chapter = event.chapter
                if event.verse_start > 0:
                    last_reference = f"{event.book} {event.chapter}:{event.verse_start}"
                else:
                    last_reference = f"{event.book} {event.chapter}"

            # Fala recente dentro da janela.
            if isinstance(event, (SpeechPartial, SpeechPartialUpdated)):
                if event.meta.timestamp >= cutoff and event.text:
                    # Evitar duplicar o current_text.
                    if event.text != current_text:
                        recent_texts.append(event.text)

        # Concatenar fala recente (mais recente primeiro), limitar tamanho.
        recent_text = " ".join(recent_texts[-5:])  # últimos 5 eventos
        if len(recent_text) > self._max_recent_chars:
            recent_text = recent_text[-self._max_recent_chars:]

        # Sprint 21 — enriquecer com SermonContext se disponível.
        sermon_book = ""
        sermon_chapter = 0
        sermon_theme = ""
        sermon_entities: tuple[str, ...] = ()
        sermon_confidence = 0.0

        if self._sermon_context_fn is not None:
            try:
                sermon_ctx = self._sermon_context_fn()
                if sermon_ctx is not None:
                    sermon_book = sermon_ctx.current_book or ""
                    sermon_chapter = sermon_ctx.current_chapter or 0
                    sermon_theme = sermon_ctx.probable_theme or ""
                    sermon_entities = tuple(e.name for e in sermon_ctx.entities[:8])
                    sermon_confidence = sermon_ctx.confidence
            except Exception as e:
                logger.warning("ContextEngine: failed to read sermon context: %s", e)

        return SemanticContext(
            current_text=current_text,
            recent_text=recent_text,
            last_book=last_book,
            last_chapter=last_chapter,
            last_reference=last_reference,
            session_id=session_id,
            timestamp=now,
            sermon_book=sermon_book,
            sermon_chapter=sermon_chapter,
            sermon_theme=sermon_theme,
            sermon_entities=sermon_entities,
            sermon_confidence=sermon_confidence,
        )
