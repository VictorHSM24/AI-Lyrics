"""Event Store Layer — refinamento arquitetural da Fase 12.

Separa completamente o armazenamento de eventos do PipelineEventBus.

Filosofia:
  - EventBus comunica.
  - EventStore armazena.
  - Replay utiliza EventStore.
  - Dashboard consulta EventStore.
  - Logs consultam EventStore.

Componentes:
  - EventStore: interface abstrata.
  - MemoryEventStore: implementação padrão em memória.
  - EventStorePolicy: política centralizada (limites, retenção).
  - EventStoreStatistics: estatísticas do store.

Compatibilidade:
  - PipelineEventBus passa a delegar armazenamento ao EventStore.
  - API pública do EventBus (history, history_types, event_count)
    continua funcionando, agora delegando ao EventStore.
  - Nenhuma API pública quebra.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# EventStore — interface abstrata
# ---------------------------------------------------------------------------


class EventStore(ABC):
    """Interface abstrata para armazenamento de eventos.

    Responsabilidade única: armazenar e consultar eventos.
    Nenhuma regra de negócio. Nenhuma decisão.

    Métodos:
      - append(event): adiciona um evento.
      - append_many(events): adiciona múltiplos eventos.
      - all(): retorna todos os eventos (cópia).
      - clear(): remove todos os eventos.
      - count(): total de eventos armazenados.
      - last(): último evento adicionado (ou None).
      - by_event(event_type): eventos por tipo.
      - by_correlation(correlation_id): eventos por correlation_id.
      - by_session(session_id): eventos por session_id.
      - by_origin(origin): eventos por origin.
      - between(start_ts, end_ts): eventos em intervalo temporal.
    """

    @abstractmethod
    def append(self, event: Any) -> None:
        """Adiciona um evento ao store."""
        ...

    @abstractmethod
    def append_many(self, events: Any) -> None:
        """Adiciona múltiplos eventos (iterável)."""
        ...

    @abstractmethod
    def all(self) -> tuple:
        """Retorna tuple com todos os eventos (cópia imutável)."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Remove todos os eventos."""
        ...

    @abstractmethod
    def count(self) -> int:
        """Total de eventos armazenados."""
        ...

    @abstractmethod
    def last(self) -> Any:
        """Último evento adicionado (ou None se vazio)."""
        ...

    @abstractmethod
    def by_event(self, event_type: type) -> tuple:
        """Eventos por tipo (classe do evento)."""
        ...

    @abstractmethod
    def by_correlation(self, correlation_id: str) -> tuple:
        """Eventos por correlation_id (preserva ordem)."""
        ...

    @abstractmethod
    def by_session(self, session_id: str) -> tuple:
        """Eventos por session_id (preserva ordem)."""
        ...

    @abstractmethod
    def by_origin(self, origin: str) -> tuple:
        """Eventos por origin (preserva ordem)."""
        ...

    @abstractmethod
    def between(self, start_ts: float, end_ts: float) -> tuple:
        """Eventos em intervalo temporal [start_ts, end_ts]."""
        ...


# ---------------------------------------------------------------------------
# EventStorePolicy — política centralizada
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EventStorePolicy:
    """Política do EventStore.

    Centraliza limites e retenção. Imutável.

    Atributos:
        max_events: máximo de eventos armazenados (0 = ilimitado).
        retention_strategy: estratégia quando atinge o limite.
            "drop_oldest": remove os mais antigos.
            "drop_newest": rejeita novos.
            "reject": levanta erro.
        auto_cleanup: se True, limpeza automática (não implementado).
        cleanup_interval_events: intervalo de limpeza (não implementado).
    """

    max_events: int = 0  # 0 = ilimitado
    retention_strategy: str = "drop_oldest"
    auto_cleanup: bool = False
    cleanup_interval_events: int = 1000

    def is_unlimited(self) -> bool:
        """True se não há limite de eventos."""
        return self.max_events <= 0

    def should_drop_oldest(self) -> bool:
        """True se estratégia é drop_oldest."""
        return self.retention_strategy == "drop_oldest"

    def should_drop_newest(self) -> bool:
        """True se estratégia é drop_newest."""
        return self.retention_strategy == "drop_newest"

    def should_reject(self) -> bool:
        """True se estratégia é reject."""
        return self.retention_strategy == "reject"


# ---------------------------------------------------------------------------
# EventStoreStatistics — estatísticas do store
# ---------------------------------------------------------------------------


@dataclass
class EventStoreStatistics:
    """Estatísticas do EventStore.

    Mutável (contadores em tempo real). Nenhuma lógica de negócio.

    Atributos:
        events_appended: total de eventos adicionados.
        events_removed: total de eventos removidos (clear/drop).
        by_type: dict com contagem por tipo de evento.
        by_session: dict com contagem por session_id.
        by_origin: dict com contagem por origin.
        by_correlation: dict com contagem por correlation_id.
    """

    events_appended: int = 0
    events_removed: int = 0
    by_type: dict = field(default_factory=dict)
    by_session: dict = field(default_factory=dict)
    by_origin: dict = field(default_factory=dict)
    by_correlation: dict = field(default_factory=dict)

    def record_append(self, event: Any) -> None:
        """Registra adição de um evento."""
        self.events_appended += 1
        type_name = type(event).__name__
        self.by_type[type_name] = self.by_type.get(type_name, 0) + 1
        # Duck-typing: eventos têm meta com session_id, origin, correlation_id
        meta = getattr(event, "meta", None)
        if meta is not None:
            session_id = getattr(meta, "session_id", "")
            if session_id:
                self.by_session[session_id] = self.by_session.get(session_id, 0) + 1
            origin = getattr(meta, "origin", "")
            if origin:
                self.by_origin[origin] = self.by_origin.get(origin, 0) + 1
            correlation_id = getattr(meta, "correlation_id", "")
            if correlation_id:
                self.by_correlation[correlation_id] = self.by_correlation.get(
                    correlation_id, 0) + 1

    def record_remove(self, count: int = 1) -> None:
        """Registra remoção de eventos."""
        self.events_removed += count

    def reset(self) -> None:
        """Zera todas as estatísticas."""
        self.events_appended = 0
        self.events_removed = 0
        self.by_type.clear()
        self.by_session.clear()
        self.by_origin.clear()
        self.by_correlation.clear()

    def to_dict(self) -> dict:
        return {
            "events_appended": self.events_appended,
            "events_removed": self.events_removed,
            "events_current": self.events_appended - self.events_removed,
            "by_type": dict(self.by_type),
            "by_session": dict(self.by_session),
            "by_origin": dict(self.by_origin),
            "by_correlation": dict(self.by_correlation),
            "unique_types": len(self.by_type),
            "unique_sessions": len(self.by_session),
            "unique_origins": len(self.by_origin),
            "unique_correlations": len(self.by_correlation),
        }


# ---------------------------------------------------------------------------
# MemoryEventStore — implementação padrão em memória
# ---------------------------------------------------------------------------


class MemoryEventStore(EventStore):
    """Implementação em memória do EventStore.

    Características:
      - Imutável externamente: all() e consultas retornam tuples.
      - Internamente eficiente: lista para preservar ordem.
      - Preserva ordem de inserção.
      - Sem deduplicação automática.
      - Sem persistência (apenas memória).
      - Aplica EventStorePolicy quando atinge limite.
    """

    def __init__(
        self,
        policy: EventStorePolicy | None = None,
        statistics: EventStoreStatistics | None = None,
    ) -> None:
        self._events: list[Any] = []
        self._policy = policy or EventStorePolicy()
        self._statistics = statistics or EventStoreStatistics()

    @property
    def policy(self) -> EventStorePolicy:
        return self._policy

    @property
    def statistics(self) -> EventStoreStatistics:
        return self._statistics

    # ------------------------------------------------------------------
    # Escrita
    # ------------------------------------------------------------------

    def append(self, event: Any) -> None:
        """Adiciona um evento ao store.

        Aplica política de limite se configurada.
        """
        self._enforce_limit_before_append()
        self._events.append(event)
        self._statistics.record_append(event)
        self._enforce_limit_after_append()

    def append_many(self, events: Any) -> None:
        """Adiciona múltiplos eventos (iterável).

        Aplica política de limite a cada inserção.
        """
        for event in events:
            self.append(event)

    def _enforce_limit_before_append(self) -> None:
        """Aplica política de limite antes de adicionar.

        Só faz algo se max_events > 0 e já estiver no limite.
        """
        if self._policy.is_unlimited():
            return
        if len(self._events) < self._policy.max_events:
            return
        # Atingiu o limite
        if self._policy.should_drop_oldest():
            removed = self._events.pop(0)
            self._statistics.record_remove(1)
        elif self._policy.should_reject():
            raise OverflowError(
                f"EventStore cheio ({self._policy.max_events} eventos)"
            )
        # drop_newest: não faz nada aqui (rejeita o novo)

    def _enforce_limit_after_append(self) -> None:
        """Aplica política drop_newest após adicionar (se excedeu)."""
        if self._policy.is_unlimited():
            return
        if self._policy.should_drop_newest():
            while len(self._events) > self._policy.max_events:
                self._events.pop()  # remove o mais recente
                self._statistics.record_remove(1)

    # ------------------------------------------------------------------
    # Limpeza
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove todos os eventos."""
        removed = len(self._events)
        self._events.clear()
        if removed > 0:
            self._statistics.record_remove(removed)

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Total de eventos armazenados."""
        return len(self._events)

    def all(self) -> tuple:
        """Retorna tuple com todos os eventos (cópia imutável)."""
        return tuple(self._events)

    def last(self) -> Any:
        """Último evento adicionado (ou None se vazio)."""
        if not self._events:
            return None
        return self._events[-1]

    def by_event(self, event_type: type) -> tuple:
        """Eventos por tipo (classe do evento). Preserva ordem."""
        return tuple(e for e in self._events if isinstance(e, event_type))

    def by_correlation(self, correlation_id: str) -> tuple:
        """Eventos por correlation_id. Preserva ordem."""
        result = []
        for e in self._events:
            meta = getattr(e, "meta", None)
            if meta is not None and getattr(meta, "correlation_id", "") == correlation_id:
                result.append(e)
        return tuple(result)

    def by_session(self, session_id: str) -> tuple:
        """Eventos por session_id. Preserva ordem."""
        result = []
        for e in self._events:
            meta = getattr(e, "meta", None)
            if meta is not None and getattr(meta, "session_id", "") == session_id:
                result.append(e)
        return tuple(result)

    def by_origin(self, origin: str) -> tuple:
        """Eventos por origin. Preserva ordem."""
        result = []
        for e in self._events:
            meta = getattr(e, "meta", None)
            if meta is not None and getattr(meta, "origin", "") == origin:
                result.append(e)
        return tuple(result)

    def between(self, start_ts: float, end_ts: float) -> tuple:
        """Eventos em intervalo temporal [start_ts, end_ts]. Preserva ordem."""
        result = []
        for e in self._events:
            meta = getattr(e, "meta", None)
            if meta is None:
                continue
            ts = getattr(meta, "timestamp", 0.0)
            if start_ts <= ts <= end_ts:
                result.append(e)
        return tuple(result)

    # ------------------------------------------------------------------
    # Serialização
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serializa o estado do store para dict."""
        return {
            "count": self.count(),
            "policy": {
                "max_events": self._policy.max_events,
                "retention_strategy": self._policy.retention_strategy,
            },
            "statistics": self._statistics.to_dict(),
        }


__all__ = [
    "EventStore",
    "MemoryEventStore",
    "EventStorePolicy",
    "EventStoreStatistics",
]
