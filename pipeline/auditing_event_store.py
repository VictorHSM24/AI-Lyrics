"""AuditingEventStore — EventStore que persiste cada evento em JSONL.

Propósito: auditoria pós-sessão. O MemoryEventStore guarda eventos apenas
em memória — ao fechar o processo, a atividade some. Este decorator
embrulha qualquer EventStore e, a cada append(), registra o evento no
TelemetryRecorder (categoria "events" → arquivo events.jsonl da sessão
de telemetria).

O que vai para o log:
  - Todos os OperationalEvents (tudo que o EventStore persistiria).
  - TelemetryEvents NÃO passam por aqui — o EventBus os filtra antes
    do store (por design, telemetria volumosa não é "atividade").

Falhas de gravação nunca propagam — auditoria não pode derrubar o
pipeline (mesmo contrato do TelemetryRecorder.record).

Serialização: dataclasses.asdict() para eventos dataclass (meta +
payload completos), fallback para to_dict()/repr.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from pipeline.event_store import EventStore
from telemetry.recorder import is_enabled, record

logger = logging.getLogger(__name__)

__all__ = ["AuditingEventStore"]


class AuditingEventStore(EventStore):
    """Decorator de EventStore que audita cada append() em disco.

    Args:
        inner: EventStore real (ex.: MemoryEventStore) que recebe a
            delegação de todos os métodos.

    Uso:
        store = AuditingEventStore(MemoryEventStore())
        bus = PipelineEventBus(store=store)
    """

    def __init__(self, inner: EventStore) -> None:
        self._inner = inner

    # ------------------------------------------------------------------
    # Escrita — delega e audita
    # ------------------------------------------------------------------

    def append(self, event: Any) -> None:
        """Delega ao store interno e registra o evento na telemetria."""
        self._inner.append(event)
        if not is_enabled():
            return
        try:
            record("events", self._serialize(event))
        except Exception as e:
            logger.debug("AuditingEventStore: falha ao auditar evento: %s", e)

    def append_many(self, events: Any) -> None:
        """Audita cada evento individualmente."""
        for event in events:
            self.append(event)

    # ------------------------------------------------------------------
    # Consultas — delegação pura
    # ------------------------------------------------------------------

    def all(self) -> tuple:
        return self._inner.all()

    def clear(self) -> None:
        self._inner.clear()

    def count(self) -> int:
        return self._inner.count()

    def last(self) -> Any:
        return self._inner.last()

    def by_event(self, event_type: type) -> tuple:
        return self._inner.by_event(event_type)

    def by_correlation(self, correlation_id: str) -> tuple:
        return self._inner.by_correlation(correlation_id)

    def by_session(self, session_id: str) -> tuple:
        return self._inner.by_session(session_id)

    def by_origin(self, origin: str) -> tuple:
        return self._inner.by_origin(origin)

    def between(self, start_ts: float, end_ts: float) -> tuple:
        return self._inner.between(start_ts, end_ts)

    # ------------------------------------------------------------------
    # Delegação de extras (policy, statistics, to_dict, etc.)
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        # Atributos não declarados delegam ao store interno
        # (ex.: policy, statistics, to_dict de implementações concretas).
        inner = self.__dict__.get("_inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)

    # ------------------------------------------------------------------
    # Serialização
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize(event: Any) -> dict[str, Any]:
        """Serializa um evento para uma linha de auditoria.

        Layout da linha:
            {"event": "<Tipo>", "timestamp": ..., "event_id": ...,
             "correlation_id": ..., "causation_id": ..., "session_id": ...,
             "origin": ..., "payload": {...campos do evento...}}
        """
        if dataclasses.is_dataclass(event) and not isinstance(event, type):
            data = dataclasses.asdict(event)
        elif hasattr(event, "to_dict"):
            data = event.to_dict()
        else:
            data = {"repr": repr(event)}

        meta = data.pop("meta", {}) if isinstance(data, dict) else {}
        if not isinstance(meta, dict):
            meta = {}
        payload = data if isinstance(data, dict) else {"value": data}

        return {
            "event": type(event).__name__,
            "timestamp": meta.get("timestamp"),
            "event_id": meta.get("event_id"),
            "correlation_id": meta.get("correlation_id"),
            "causation_id": meta.get("causation_id"),
            "session_id": meta.get("session_id"),
            "origin": meta.get("origin"),
            "payload": payload,
        }
