"""StateOrchestrator — máquina de estados do sistema (CAP-01).

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

Estado atual: ESQUELETO (Passo 1).
  - Handlers existem mas não contêm lógica de negócio.
  - Nenhuma transição é implementada.
  - Nenhum StateChanged é publicado.
  - TODOs marcam onde a lógica será implementada nos Passos 2-6.
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
    ReferenceCandidate,
    ReferenceDetected,
    SpeechTranscribed,
)

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
        """Inscreve handlers no EventBus para receber eventos do pipeline."""
        if self._subscribed:
            return
        self._bus.subscribe(ReferenceCandidate, self._handle_reference_candidate)
        self._bus.subscribe(ReferenceDetected, self._handle_reference_detected)
        self._bus.subscribe(IntentUnknown, self._handle_intent_unknown)
        self._bus.subscribe(SpeechTranscribed, self._handle_speech_transcribed)
        self._bus.subscribe(IntentCandidate, self._handle_intent_candidate)
        self._subscribed = True
        logger.info(
            "StateOrchestrator started — subscribed to "
            "ReferenceCandidate, ReferenceDetected, IntentUnknown, "
            "SpeechTranscribed, IntentCandidate."
        )

    def stop(self) -> None:
        """Desinscreve handlers do EventBus."""
        if not self._subscribed:
            return
        self._bus.unsubscribe(ReferenceCandidate, self._handle_reference_candidate)
        self._bus.unsubscribe(ReferenceDetected, self._handle_reference_detected)
        self._bus.unsubscribe(IntentUnknown, self._handle_intent_unknown)
        self._bus.unsubscribe(SpeechTranscribed, self._handle_speech_transcribed)
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
            )

    # ------------------------------------------------------------------
    # Handlers — esqueleto (Passo 1)
    #
    # Cada handler possui a assinatura correta e documentação.
    # Nenhuma lógica de negócio é implementada nesta etapa.
    # TODOs marcam onde a lógica será implementada nos Passos 2-6.
    # ------------------------------------------------------------------

    def _handle_reference_candidate(self, event: ReferenceCandidate) -> None:
        """Processa ReferenceCandidate do IncrementalBiblicalParser.

        Transições esperadas (a implementar):
          - WAIT → PREPARE (book_detected ou chapter_detected)
          - PREPARE → PREPARE (chapter_detected, se capítulo novo)
          - PREPARE → PREPARE (book_changed, se livro diferente)
          - PRESENT → PREPARE (nova referência)
          - IGNORE → PREPARE (nova referência)

        Args:
            event: ReferenceCandidate com book, book_id, chapter, confidence.
        """
        # TODO Passo 3: implementar transições de ReferenceCandidate.
        pass

    def _handle_reference_detected(self, event: ReferenceDetected) -> None:
        """Processa ReferenceDetected do parser ou resolver.

        Transições esperadas (a implementar):
          - WAIT → PRESENT (first)
          - PREPARE → PRESENT (first)
          - IGNORE → PRESENT (first)
          - PRESENT → PRESENT (repeat, se mesma referência)
          - PRESENT → PRESENT (first, se nova referência)

        Args:
            event: ReferenceDetected com book_id, chapter, verse_start.
        """
        # TODO Passo 4: implementar transições de ReferenceDetected.
        pass

    def _handle_intent_unknown(self, event: IntentUnknown) -> None:
        """Processa IntentUnknown do BiblicalNLUService.

        Transições esperadas (a implementar):
          - PRESENT → WAIT (no_reference)
          - Outros estados: permanecer (no-op)

        Args:
            event: IntentUnknown com raw_text e reason.
        """
        # TODO Passo 5: implementar transição de IntentUnknown.
        pass

    def _handle_speech_transcribed(self, event: SpeechTranscribed) -> None:
        """Processa SpeechTranscribed do STT.

        Transições esperadas (a implementar):
          - PRESENT → WAIT (no_reference, se sem pista bíblica)
          - WAIT → IGNORE (segment_ignored, se sem pista bíblica)
          - Outros: incrementar segment_count, sem transição

        Args:
            event: SpeechTranscribed com text, language, confidence.
        """
        # TODO Passo 6: implementar classificação IGNORE vs WAIT.
        pass

    def _handle_intent_candidate(self, event: IntentCandidate) -> None:
        """Processa IntentCandidate do SemanticEngine.

        O orquestrador não age diretamente sobre IntentCandidate.
        O ReferenceResolver converte IntentCandidate em ReferenceDetected,
        que o orquestrador então processa.

        Args:
            event: IntentCandidate com candidates_json, intent, inference_ms.
        """
        # TODO Passo 6: confirmar noop (resolver converte em ReferenceDetected).
        pass
