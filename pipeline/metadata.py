"""EventMetadata — DTO imutável de rastreabilidade.

Todo evento do Pipeline carrega exatamente um EventMetadata. Nenhum
campo de rastreabilidade é duplicado em cada evento.

Campos:
  - event_id: identificador único do evento (nunca reutilizado).
  - correlation_id: identificador do fluxo (compartilhado entre todos
    os eventos do mesmo processamento).
  - causation_id: event_id do evento imediatamente anterior (cadeia
    causal). None para o primeiro evento do fluxo.
  - session_id: identificador da PipelineSession atual.
  - timestamp: momento de criação (segundos desde epoch).
  - origin: nome do componente que criou o evento (ex.: "RecognitionHandler").
  - metadata: tuple de pares (chave, valor) para dados extras.

Regras:
  - Somente SpeechSegmentReceived inicia um novo correlation_id.
  - Nunca reutilizar event_id.
  - Nunca criar novo correlation_id durante o fluxo.
  - Cada evento aponta para seu causation_id.

Imutável, hashable, serializável.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Geradores de ID (injetáveis para testes)
# ---------------------------------------------------------------------------


def _default_event_id_generator() -> str:
    """Gera um event_id único usando uuid4."""
    return str(uuid.uuid4())


def _default_correlation_id_generator() -> str:
    """Gera um correlation_id único usando uuid4."""
    return str(uuid.uuid4())


def _default_session_id_generator() -> str:
    """Gera um session_id único usando uuid4."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# EventMetadata — DTO imutável
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EventMetadata:
    """Metadados de rastreabilidade anexados a todo evento do Pipeline.

    Imutável, hashable, serializável.

    Atributos:
        event_id: identificador único do evento.
        correlation_id: identificador do fluxo de processamento.
        causation_id: event_id do evento anterior (None se inicial).
        session_id: identificador da sessão atual.
        timestamp: momento de criação (segundos desde epoch).
        origin: componente que criou o evento.
        metadata: tuple de pares (chave, valor) extras.
    """

    event_id: str
    correlation_id: str
    causation_id: str | None
    session_id: str
    timestamp: float
    origin: str
    metadata: tuple = field(default_factory=tuple)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_initial(self) -> bool:
        """True se este é o primeiro evento do fluxo (causation_id is None)."""
        return self.causation_id is None

    @property
    def has_metadata(self) -> bool:
        """True se há metadata extra anexada."""
        return len(self.metadata) > 0

    # ------------------------------------------------------------------
    # Serialização
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "origin": self.origin,
            "metadata": list(self.metadata),
        }

    # ------------------------------------------------------------------
    # Fábricas
    # ------------------------------------------------------------------

    @staticmethod
    def for_initial(
        session_id: str,
        origin: str,
        correlation_id: str | None = None,
        event_id: str | None = None,
        timestamp: float | None = None,
        metadata: tuple = (),
        event_id_generator: Callable[[], str] = _default_event_id_generator,
        correlation_id_generator: Callable[[], str] = _default_correlation_id_generator,
    ) -> "EventMetadata":
        """Cria metadados para o primeiro evento de um novo fluxo.

        Gera novo correlation_id (se não fornecido) e novo event_id.
        causation_id é None (sem predecessor).
        """
        return EventMetadata(
            event_id=event_id or event_id_generator(),
            correlation_id=correlation_id or correlation_id_generator(),
            causation_id=None,
            session_id=session_id,
            timestamp=timestamp if timestamp is not None else time.time(),
            origin=origin,
            metadata=metadata,
        )

    @staticmethod
    def for_next(
        previous: "EventMetadata",
        origin: str,
        event_id: str | None = None,
        timestamp: float | None = None,
        metadata: tuple = (),
        event_id_generator: Callable[[], str] = _default_event_id_generator,
    ) -> "EventMetadata":
        """Cria metadados para um evento subsequente no mesmo fluxo.

        Preserva correlation_id e session_id do evento anterior.
        causation_id = event_id do evento anterior.
        Gera novo event_id.
        """
        return EventMetadata(
            event_id=event_id or event_id_generator(),
            correlation_id=previous.correlation_id,
            causation_id=previous.event_id,
            session_id=previous.session_id,
            timestamp=timestamp if timestamp is not None else time.time(),
            origin=origin,
            metadata=metadata,
        )

    @staticmethod
    def for_session_event(
        session_id: str,
        origin: str,
        correlation_id: str | None = None,
        event_id: str | None = None,
        timestamp: float | None = None,
        metadata: tuple = (),
        event_id_generator: Callable[[], str] = _default_event_id_generator,
        correlation_id_generator: Callable[[], str] = _default_correlation_id_generator,
    ) -> "EventMetadata":
        """Cria metadados para eventos de ciclo de vida do pipeline
        (PipelineStarted, PipelineStopped, PipelinePaused, etc.).

        Esses eventos podem iniciar seu próprio correlation_id pois
        não pertencem ao fluxo de processamento de um segmento.
        """
        return EventMetadata(
            event_id=event_id or event_id_generator(),
            correlation_id=correlation_id or correlation_id_generator(),
            causation_id=None,
            session_id=session_id,
            timestamp=timestamp if timestamp is not None else time.time(),
            origin=origin,
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Geradores exportados
# ---------------------------------------------------------------------------


__all__ = [
    "EventMetadata",
    "_default_event_id_generator",
    "_default_correlation_id_generator",
    "_default_session_id_generator",
]
