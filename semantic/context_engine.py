"""semantic/context_engine.py — Construção de contexto (Sprint 20 + Sprint 28).

Responsabilidade:
  - Construir SemanticContext a partir de contexto incremental.
  - Incluir últimos 30-60s de fala.
  - Incluir última referência encontrada (livro/capítulo atual).
  - Incluir histórico recente.
  - Sprint 21 — incluir SermonContext (memória contínua da pregação).
  - Não consultar LLM, não publicar eventos, não acessar Holyrics.

Implementação:
  Sprint 28 — Cache incremental (Fase 4):
    - Mantém buffer circular próprio de últimos N SpeechCommittedWords.
    - Mantém último ReferenceDetected.
    - Atualizado por inscrição no EventBus (não varre bus.history()).
    - Fallback best-effort: se bus não disponível, usa history_fn.
  Sprint 20 — original consultava bus.history() O(n) a cada inferência.

Sprint 20 — Semantic Understanding Engine.
Sprint 21 — Sermon Memory Engine (integração).
Sprint 28 — ContextEngine Incremental (Fase 4).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

from pipeline.events import (
    ReferenceDetected,
    SpeechCommittedWords,
)
from semantic.types import SemanticContext

logger = logging.getLogger(__name__)

__all__ = ["ContextEngine"]

# Sprint 28 — número máximo de committed words no buffer circular.
_DEFAULT_MAX_COMMITTED = 20


class ContextEngine:
    """Constrói SemanticContext a partir de contexto incremental.

    Sprint 28 (Fase 4) — mantém cache próprio atualizado por inscrição
    no EventBus, em vez de varrer bus.history() a cada build().

    Args:
        history_fn: callable que retorna lista de eventos (bus.history()).
            Usado como fallback best-effort se bus não estiver disponível.
            Pode ser None se bus for fornecido.
        window_seconds: janela de fala recente em segundos (default 45).
        max_recent_chars: máximo de caracteres de fala recente (default 500).
        sermon_context_fn: callable opcional (Sprint 21) que retorna
            SermonContext atual, ou None se a memória de sermão não
            estiver ativa. Se fornecido, enriquece o SemanticContext
            com livro/capítulo/tema/entidades do sermão.
        bus: EventBus opcional (Sprint 28). Se fornecido, inscreve em
            SpeechCommittedWords e ReferenceDetected para manter cache
            interno. Quando bus está disponível, build() usa o cache
            interno (O(1)) em vez de history_fn (O(n)).
        max_committed: máximo de committed words no buffer circular
            (default 20).
    """

    def __init__(
        self,
        history_fn: Optional[Callable[[], Any]] = None,
        window_seconds: float = 45.0,
        max_recent_chars: int = 500,
        sermon_context_fn: Optional[Callable[[], Any]] = None,
        # Sprint 28 — cache incremental.
        bus: Any = None,
        max_committed: int = _DEFAULT_MAX_COMMITTED,
    ) -> None:
        self._history_fn = history_fn
        self._window_seconds = window_seconds
        self._max_recent_chars = max_recent_chars
        self._sermon_context_fn = sermon_context_fn
        # Sprint 28 — cache incremental.
        self._bus = bus
        self._max_committed = max_committed
        self._committed_buffer: deque[tuple[float, str]] = deque(
            maxlen=max_committed,
        )
        self._last_reference: Optional[ReferenceDetected] = None
        self._lock = threading.Lock()
        self._subscribed = False

        # Sprint 28 — inscrever no bus se disponível.
        if bus is not None:
            self._subscribe()

    def _subscribe(self) -> None:
        """Inscreve em SpeechCommittedWords e ReferenceDetected."""
        if self._bus is None or self._subscribed:
            return
        self._bus.subscribe(SpeechCommittedWords, self._on_committed_words)
        self._bus.subscribe(ReferenceDetected, self._on_reference_detected)
        self._subscribed = True
        logger.info(
            "ContextEngine: subscribed to SpeechCommittedWords + "
            "ReferenceDetected (incremental cache, max_committed=%d)",
            self._max_committed,
        )

    def _unsubscribe(self) -> None:
        """Desinscreve do EventBus."""
        if self._bus is None or not self._subscribed:
            return
        try:
            self._bus.unsubscribe(SpeechCommittedWords, self._on_committed_words)
            self._bus.unsubscribe(ReferenceDetected, self._on_reference_detected)
        except Exception:
            pass
        self._subscribed = False

    # ------------------------------------------------------------------
    # Handlers de eventos (Sprint 28 — cache incremental)
    # ------------------------------------------------------------------

    def _on_committed_words(self, event: SpeechCommittedWords) -> None:
        """Recebe SpeechCommittedWords — adiciona ao buffer circular."""
        with self._lock:
            self._committed_buffer.append(
                (event.meta.timestamp, event.full_committed_text),
            )

    def _on_reference_detected(self, event: ReferenceDetected) -> None:
        """Recebe ReferenceDetected — atualiza última referência."""
        with self._lock:
            self._last_reference = event

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def set_sermon_context_fn(self, fn: Callable[[], Any]) -> None:
        """Define ou atualiza o callable de SermonContext (Sprint 21)."""
        self._sermon_context_fn = fn

    def build(
        self,
        current_text: str,
        session_id: str = "",
        correlation_id: str = "",
    ) -> SemanticContext:
        """Constrói o contexto para o texto atual.

        Sprint 28 — usa cache incremental se inscrito no bus;
        fallback para history_fn se não inscrito.
        """
        now = time.time()
        cutoff = now - self._window_seconds

        recent_texts: list[str] = []
        last_book = ""
        last_chapter = 0
        last_reference = ""

        if self._subscribed:
            # Sprint 28 — usar cache incremental (O(1)).
            with self._lock:
                committed_snapshot = list(self._committed_buffer)
                ref = self._last_reference

            # Committed words carregam full_committed_text (texto acumulado).
            # Cada evento successivo contém TODO o texto até aquele ponto,
            # não apenas o trecho novo. Para evitar redundância no
            # recent_text, usamos apenas o evento mais recente dentro da
            # janela que NÃO seja o current_text (o current_text já é
            # passado separadamente).
            for ts, text in reversed(committed_snapshot):
                if ts >= cutoff and text and text != current_text:
                    recent_texts.append(text)
                    break  # apenas o mais recente

            if ref is not None:
                last_book = ref.book
                last_chapter = ref.chapter
                if ref.verse_start > 0:
                    last_reference = f"{ref.book} {ref.chapter}:{ref.verse_start}"
                else:
                    last_reference = f"{ref.book} {ref.chapter}"
        else:
            # Fallback — varrer history_fn (compatibilidade, testes legados).
            try:
                events = self._history_fn() if self._history_fn else []
            except Exception as e:
                logger.warning("ContextEngine: failed to read history: %s", e)
                events = []

            for event in events:
                if isinstance(event, ReferenceDetected):
                    last_book = event.book
                    last_chapter = event.chapter
                    if event.verse_start > 0:
                        last_reference = f"{event.book} {event.chapter}:{event.verse_start}"
                    else:
                        last_reference = f"{event.book} {event.chapter}"

                # Fallback aceita SpeechCommittedWords OU SpeechPartial
                # (compatibilidade com testes legados que ainda publicam
                # SpeechPartial diretamente no bus).
                text = getattr(event, "text", None) or getattr(
                    event, "full_committed_text", None,
                )
                if text and event.meta.timestamp >= cutoff:
                    if text != current_text:
                        recent_texts.append(text)

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
        sermon_book_confidence = 0.0  # Sprint 22.2

        if self._sermon_context_fn is not None:
            try:
                sermon_ctx = self._sermon_context_fn()
                if sermon_ctx is not None:
                    sermon_book = sermon_ctx.current_book or ""
                    sermon_chapter = sermon_ctx.current_chapter or 0
                    sermon_theme = sermon_ctx.probable_theme or ""
                    sermon_entities = tuple(e.name for e in sermon_ctx.entities[:8])
                    sermon_confidence = sermon_ctx.confidence
                    # Sprint 22.2 — confiança específica do current_book.
                    sermon_book_confidence = getattr(
                        sermon_ctx, "current_book_confidence", 0.0
                    )
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
            sermon_book_confidence=sermon_book_confidence,
        )
