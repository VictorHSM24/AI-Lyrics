"""StateOrchestrator — máquina de estados do sistema (CAP-01 + Sprint 28).

Responsabilidade:
  - Centralizar a decisão de estado do sistema (WAIT, PREPARE, PRESENT, IGNORE).
  - Consumir eventos do PipelineEventBus e publicar StateChanged.
  - Manter contexto interno (active_book, active_chapter, pending_reference, etc.).

Atribuições (ADR-001):
  - Único componente autorizado a produzir transições de estado.
  - Ponto único de verdade para estado do sistema.
  - Puramente aditivo: nenhum componente existente precisa mudar.

Estados (ADR-002):
  - WAIT: sistema aguardando. Nenhuma referência ativa.
  - PREPARE: referência parcial detectada. Sistema acumulando informação.
  - PRESENT: referência completa detectada. Versículo deve ser apresentado.
  - IGNORE: segmento sem conteúdo bíblico. Sistema descarta sem processamento.

Thread Safety:
  - O orquestrador é chamado via EventBus (síncrono) por múltiplas threads
    (SlidingWindow, SpeechWorker, SemanticEngine Timer).
  - Contexto interno protegido por threading.Lock.
  - Publicação de StateChanged ocorre FORA do lock.

Sprint 28 (Fase 5) — Implementação completa:
  - Transições WAIT/PREPARE/PRESENT/IGNORE implementadas.
  - StateChanged publicado em toda transição.
  - Inscrição em ReferenceAntecipada + SpeechCommittedWords.
  - Dedup por last_presented_reference.
  - Correção de antecipada (ReferenceAntecipada → ReferenceDetected).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    IntentCandidate,
    IntentUnknown,
    ReferenceAntecipada,
    ReferenceCandidate,
    ReferenceDetected,
    SpeechCommittedWords,
    StateChanged,
    SpeechTranscribed,
)
from pipeline.metadata import EventMetadata

logger = logging.getLogger(__name__)

__all__ = ["State", "OrchestratorContext", "StateOrchestrator"]


# ---------------------------------------------------------------------------
# Enum de estados (ADR-002)
# ---------------------------------------------------------------------------


class State(str, Enum):
    """Estados da máquina de estados do StateOrchestrator.

    Herda de str para compatibilidade com serialização JSON,
    EventStore, Event Contracts e Benchmark (que usam strings).
    """

    WAIT = "WAIT"
    PREPARE = "PREPARE"
    PRESENT = "PRESENT"
    IGNORE = "IGNORE"


# ---------------------------------------------------------------------------
# Contexto interno
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorContext:
    """Contexto interno mutável do StateOrchestrator.

    Protegido por threading.Lock. O snapshot exposto publicamente
    via property `context` é uma cópia defensiva.

    Campos:
        current_state: estado atual da máquina (State enum).
        active_book: nome do livro ativo em PREPARE (None se não em PREPARE).
        active_book_id: ID do livro ativo (0 se None).
        active_chapter: capítulo ativo em PREPARE (None se não definido).
        pending_reference: referência pendente em PREPARE (ex.: "João ?:?").
        last_presented_reference: (book_id, chapter, verse_start) da última
            referência apresentada, ou None se nenhuma.
        segment_count_since_last_state_change: segmentos processados desde
            a última transição de estado.
        has_biblical_content: True se o último segmento continha pista bíblica.
        _state_entered_at: timestamp (monotonic) de entrada no estado atual.
    """

    current_state: State = State.WAIT
    active_book: str | None = None
    active_book_id: int = 0
    active_chapter: int | None = None
    pending_reference: str | None = None
    last_presented_reference: tuple[int, int, int] | None = None
    segment_count_since_last_state_change: int = 0
    has_biblical_content: bool = False
    _state_entered_at: float = field(default_factory=time.monotonic)
    # Sprint 28 (Fase 5) — rastrear se a última apresentação foi antecipada.
    # Usado para correção de antecipada (§13.5).
    last_was_anticipation: bool = False


# ---------------------------------------------------------------------------
# StateOrchestrator
# ---------------------------------------------------------------------------


class StateOrchestrator:
    """Máquina de estados do sistema AI Lyrics (CAP-01).

    Consome eventos do PipelineEventBus, decide transições de estado
    baseadas no tipo do evento e contexto interno, e publica StateChanged.

    Args:
        bus: PipelineEventBus para assinar e publicar eventos.
        session_id: ID da sessão atual (para EventMetadata).
        book_names: conjunto opcional de nomes de livros para inspeção
            de texto em SpeechTranscribed. Se None, _has_biblical_content
            usa apenas heurística de dígitos.

    Lifecycle:
        start() — inscreve handlers no EventBus.
        stop()  — desinscreve handlers do EventBus.
    """

    def __init__(
        self,
        bus: PipelineEventBus,
        session_id: str,
        book_names: set[str] | None = None,
    ) -> None:
        self._bus = bus
        self._session_id = session_id
        self._book_names = book_names
        self._subscribed = False

        # Contexto interno protegido por lock.
        self._lock = threading.Lock()
        self._ctx = OrchestratorContext()

        logger.info("StateOrchestrator initialized (session_id=%s).", session_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inscreve handlers no EventBus para receber eventos do pipeline.

        Sprint 28 (Fase 5) — adiciona ReferenceAntecipada e SpeechCommittedWords.
        """
        if self._subscribed:
            return
        self._bus.subscribe(ReferenceCandidate, self._handle_reference_candidate)
        self._bus.subscribe(ReferenceDetected, self._handle_reference_detected)
        self._bus.subscribe(ReferenceAntecipada, self._handle_reference_antecipada)
        self._bus.subscribe(IntentUnknown, self._handle_intent_unknown)
        self._bus.subscribe(SpeechTranscribed, self._handle_speech_transcribed)
        self._bus.subscribe(SpeechCommittedWords, self._handle_committed_words)
        self._bus.subscribe(IntentCandidate, self._handle_intent_candidate)
        self._subscribed = True
        logger.info(
            "StateOrchestrator started — subscribed to "
            "ReferenceCandidate, ReferenceDetected, ReferenceAntecipada, "
            "IntentUnknown, SpeechTranscribed, SpeechCommittedWords, "
            "IntentCandidate."
        )

    def stop(self) -> None:
        """Desinscreve handlers do EventBus."""
        if not self._subscribed:
            return
        self._bus.unsubscribe(ReferenceCandidate, self._handle_reference_candidate)
        self._bus.unsubscribe(ReferenceDetected, self._handle_reference_detected)
        self._bus.unsubscribe(ReferenceAntecipada, self._handle_reference_antecipada)
        self._bus.unsubscribe(IntentUnknown, self._handle_intent_unknown)
        self._bus.unsubscribe(SpeechTranscribed, self._handle_speech_transcribed)
        self._bus.unsubscribe(SpeechCommittedWords, self._handle_committed_words)
        self._bus.unsubscribe(IntentCandidate, self._handle_intent_candidate)
        self._subscribed = False
        logger.info("StateOrchestrator stopped.")

    # ------------------------------------------------------------------
    # Properties (read-only, retornam snapshots)
    # ------------------------------------------------------------------

    @property
    def current_state(self) -> State:
        """Retorna o estado atual da máquina (snapshot imutável)."""
        with self._lock:
            return self._ctx.current_state

    @property
    def context(self) -> OrchestratorContext:
        """Retorna uma cópia defensiva do contexto atual.

        Permite que consumidores externos inspecionem o estado sem
        risco de mutação concorrente.
        """
        with self._lock:
            return OrchestratorContext(
                current_state=self._ctx.current_state,
                active_book=self._ctx.active_book,
                active_book_id=self._ctx.active_book_id,
                active_chapter=self._ctx.active_chapter,
                pending_reference=self._ctx.pending_reference,
                last_presented_reference=self._ctx.last_presented_reference,
                segment_count_since_last_state_change=self._ctx.segment_count_since_last_state_change,
                has_biblical_content=self._ctx.has_biblical_content,
                _state_entered_at=self._ctx._state_entered_at,
                last_was_anticipation=self._ctx.last_was_anticipation,
            )

    # ------------------------------------------------------------------
    # Handlers — Sprint 28 (Fase 5) implementação completa
    # ------------------------------------------------------------------

    def _handle_reference_candidate(self, event: ReferenceCandidate) -> None:
        """Processa ReferenceCandidate do IncrementalBiblicalParser.

        Transições:
          - WAIT/IGNORE → PREPARE (book_detected ou chapter_detected)
          - PREPARE → PREPARE (chapter_detected, se capítulo novo)
          - PRESENT → PREPARE (nova referência)
        """
        transition = None
        with self._lock:
            ctx = self._ctx
            old_state = ctx.current_state
            old_book = ctx.active_book
            old_chapter = ctx.active_chapter

            if old_state in (State.WAIT, State.IGNORE, State.PRESENT):
                # Transitar para PREPARE.
                ctx.current_state = State.PREPARE
                ctx.active_book = event.book or None
                ctx.active_book_id = event.book_id
                ctx.active_chapter = event.chapter or None
                ctx.pending_reference = self._build_pending_ref(
                    event.book, event.chapter, 0,
                )
                ctx._state_entered_at = time.monotonic()
                ctx.segment_count_since_last_state_change = 0
                reason = "book_detected" if event.completeness == "book" else \
                         "chapter_detected" if event.completeness == "chapter" else \
                         "candidate"
                transition = (old_state, State.PREPARE, reason)
            elif old_state == State.PREPARE:
                # Já em PREPARE — atualizar capítulo se mudou.
                if event.chapter and event.chapter != old_chapter:
                    ctx.active_chapter = event.chapter
                    ctx.pending_reference = self._build_pending_ref(
                        event.book or old_book, event.chapter, 0,
                    )
                    transition = (State.PREPARE, State.PREPARE, "chapter_detected")
                elif event.book and event.book != old_book:
                    # Livro mudou — nova referência em PREPARE.
                    ctx.active_book = event.book
                    ctx.active_book_id = event.book_id
                    ctx.active_chapter = event.chapter or None
                    ctx.pending_reference = self._build_pending_ref(
                        event.book, event.chapter, 0,
                    )
                    transition = (State.PREPARE, State.PREPARE, "book_changed")

        if transition is not None:
            self._publish_state_changed(event.meta, *transition)

    def _handle_reference_detected(self, event: ReferenceDetected) -> None:
        """Processa ReferenceDetected do parser ou resolver.

        Transições:
          - WAIT/PREPARE/IGNORE → PRESENT (first)
          - PRESENT → PRESENT (repeat, se mesma referência = noop)
          - PRESENT → PRESENT (new_reference, se nova referência)
          - PRESENT → PRESENT (corrected, se corrige antecipada — §13.5)
        """
        transition = None
        detail = ""
        with self._lock:
            ctx = self._ctx
            old_state = ctx.current_state
            ref_key = (event.book_id, event.chapter, event.verse_start)
            is_repeat = ctx.last_presented_reference == ref_key

            if old_state != State.PRESENT:
                # Primeira apresentação.
                ctx.current_state = State.PRESENT
                ctx.active_book = event.book
                ctx.active_book_id = event.book_id
                ctx.active_chapter = event.chapter
                ctx.pending_reference = None
                ctx.last_presented_reference = ref_key
                ctx.last_was_anticipation = False
                ctx._state_entered_at = time.monotonic()
                ctx.segment_count_since_last_state_change = 0
                transition = (old_state, State.PRESENT, "reference_detected")
            elif is_repeat:
                # Mesma referência — noop (dedup).
                # §13.5: se foi antecipada e agora é confirmada (mesma ref),
                # marcar detail="confirmed".
                if ctx.last_was_anticipation:
                    detail = "confirmed"
                ctx.last_was_anticipation = False
                transition = (State.PRESENT, State.PRESENT, "repeat")
            else:
                # Nova referência enquanto em PRESENT.
                # §13.5: se a última foi antecipada e (book, chapter) é igual
                # mas verse difere, é correção de antecipada.
                last_ref = ctx.last_presented_reference
                if (ctx.last_was_anticipation and last_ref is not None
                        and last_ref[0] == event.book_id
                        and last_ref[1] == event.chapter
                        and last_ref[2] != event.verse_start):
                    detail = "corrected"
                    transition = (State.PRESENT, State.PRESENT, "new_reference")
                else:
                    transition = (State.PRESENT, State.PRESENT, "new_reference")
                ctx.active_book = event.book
                ctx.active_book_id = event.book_id
                ctx.active_chapter = event.chapter
                ctx.last_presented_reference = ref_key
                ctx.last_was_anticipation = False
                ctx._state_entered_at = time.monotonic()
                ctx.segment_count_since_last_state_change = 0

        if transition is not None:
            self._publish_state_changed(event.meta, *transition, detail=detail)

    def _handle_reference_antecipada(self, event: ReferenceAntecipada) -> None:
        """Processa ReferenceAntecipada do IncrementalBiblicalParser.

        Transições:
          - PREPARE → PRESENT (antecipada); marca last_was_anticipation=True
          - WAIT/IGNORE → PRESENT (antecipada direta)
        """
        transition = None
        with self._lock:
            ctx = self._ctx
            old_state = ctx.current_state
            ref_key = (event.book_id, event.chapter, event.verse_start)
            is_repeat = ctx.last_presented_reference == ref_key

            if not is_repeat:
                ctx.current_state = State.PRESENT
                ctx.active_book = event.book
                ctx.active_book_id = event.book_id
                ctx.active_chapter = event.chapter
                ctx.pending_reference = None
                ctx.last_presented_reference = ref_key
                ctx.last_was_anticipation = True
                ctx._state_entered_at = time.monotonic()
                ctx.segment_count_since_last_state_change = 0
                transition = (old_state, State.PRESENT, "anticipation")
            else:
                transition = (State.PRESENT, State.PRESENT, "repeat")

        if transition is not None:
            self._publish_state_changed(event.meta, *transition)

    def _handle_intent_unknown(self, event: IntentUnknown) -> None:
        """Processa IntentUnknown do BiblicalNLUService.

        Transições:
          - PRESENT → WAIT (no_reference)
          - PREPARE → WAIT (se sem pista)
        """
        transition = None
        with self._lock:
            ctx = self._ctx
            old_state = ctx.current_state

            if old_state == State.PRESENT:
                ctx.current_state = State.WAIT
                ctx.active_book = None
                ctx.active_book_id = 0
                ctx.active_chapter = None
                ctx.pending_reference = None
                ctx._state_entered_at = time.monotonic()
                ctx.segment_count_since_last_state_change = 0
                transition = (old_state, State.WAIT, "no_reference")
            elif old_state == State.PREPARE:
                ctx.current_state = State.WAIT
                ctx.active_book = None
                ctx.active_book_id = 0
                ctx.active_chapter = None
                ctx.pending_reference = None
                ctx._state_entered_at = time.monotonic()
                ctx.segment_count_since_last_state_change = 0
                transition = (old_state, State.WAIT, "no_reference")

        if transition is not None:
            self._publish_state_changed(event.meta, *transition)

    def _handle_speech_transcribed(self, event: SpeechTranscribed) -> None:
        """Processa SpeechTranscribed do STT (finalização do fluxo).

        Transições:
          - PRESENT → WAIT (no_reference, se sem pista bíblica)
          - WAIT → IGNORE (segment_ignored, se sem pista bíblica)
          - PREPARE → WAIT/IGNORE (se sem ref detectada)
          - Outros: incrementar segment_count, sem transição
        """
        transition = None
        with self._lock:
            ctx = self._ctx
            old_state = ctx.current_state
            ctx.segment_count_since_last_state_change += 1
            has_biblical = self._has_biblical_content(event.text)

            if old_state == State.PRESENT and not has_biblical:
                ctx.current_state = State.WAIT
                ctx.active_book = None
                ctx.active_book_id = 0
                ctx.active_chapter = None
                ctx.pending_reference = None
                ctx._state_entered_at = time.monotonic()
                ctx.segment_count_since_last_state_change = 0
                transition = (old_state, State.WAIT, "no_reference")
            elif old_state == State.WAIT and not has_biblical:
                ctx.current_state = State.IGNORE
                ctx._state_entered_at = time.monotonic()
                ctx.segment_count_since_last_state_change = 0
                transition = (old_state, State.IGNORE, "segment_ignored")
            elif old_state == State.PREPARE and not has_biblical:
                ctx.current_state = State.WAIT
                ctx.active_book = None
                ctx.active_book_id = 0
                ctx.active_chapter = None
                ctx.pending_reference = None
                ctx._state_entered_at = time.monotonic()
                ctx.segment_count_since_last_state_change = 0
                transition = (old_state, State.WAIT, "no_reference")

        if transition is not None:
            self._publish_state_changed(event.meta, *transition)

    def _handle_committed_words(self, event: SpeechCommittedWords) -> None:
        """Processa SpeechCommittedWords (Sprint 28).

        Atualiza has_biblical_content (heurística) para preparar
        classificação WAIT vs IGNORE em SpeechTranscribed.
        """
        with self._lock:
            self._ctx.has_biblical_content = self._has_biblical_content(
                event.full_committed_text,
            )

    def _handle_intent_candidate(self, event: IntentCandidate) -> None:
        """Processa IntentCandidate do SemanticEngine.

        Noop — o ReferenceResolver converte IntentCandidate em
        ReferenceDetected, que o orquestrador então processa.
        """
        pass

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _build_pending_ref(
        self, book: str | None, chapter: int | None, verse: int,
    ) -> str | None:
        """Constrói string de referência pendente (ex.: 'João 3:?')."""
        if not book:
            return None
        if chapter and chapter > 0:
            if verse and verse > 0:
                return f"{book} {chapter}:{verse}"
            return f"{book} {chapter}:?"
        return f"{book} ?:?"

    def _has_biblical_content(self, text: str) -> bool:
        """Heurística: verifica se o texto contém pista bíblica.

        Verifica nomes de livros conhecidos ou padrões de referência
        (ex.: "capítulo 3", "versículo 16", dígitos isolados).
        """
        if not text:
            return False
        text_lower = text.lower()
        # Verificar nomes de livros.
        if self._book_names:
            for name in self._book_names:
                if name.lower() in text_lower:
                    return True
        # Heurística de padrões de referência.
        biblical_markers = [
            "capitulo", "capítulo", "versiculo", "versículo",
            "vers ", "cap ", "evangelho", "salmos", "salmo",
        ]
        for marker in biblical_markers:
            if marker in text_lower:
                return True
        return False

    def _publish_state_changed(
        self,
        source_meta: EventMetadata,
        from_state: State,
        to_state: State,
        reason: str,
        detail: str = "",
    ) -> None:
        """Publica StateChanged no EventBus (FORA do lock)."""
        with self._lock:
            ctx = self._ctx
            active_book = ctx.active_book or ""
            active_chapter = ctx.active_chapter or 0
            pending_ref = ctx.pending_reference or ""
            repeat = reason == "repeat"

        meta = EventMetadata.for_next(
            previous=source_meta,
            origin="StateOrchestrator",
        )
        event = StateChanged(
            meta=meta,
            from_state=from_state.value,
            to_state=to_state.value,
            reason=reason,
            repeat=repeat,
            detail=detail,
            active_book=active_book,
            active_chapter=active_chapter,
            pending_reference=pending_ref,
        )
        self._bus.publish(event)
        logger.info(
            "StateOrchestrator: %s → %s (reason=%s, book=%s, chapter=%d)",
            from_state.value, to_state.value, reason,
            active_book, active_chapter,
        )
