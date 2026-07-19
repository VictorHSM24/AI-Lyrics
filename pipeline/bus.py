"""PipelineEventBus — barramento de eventos genérico.

Responsabilidade única: rotear eventos para handlers inscritos.

Nenhuma regra de negócio. Nenhuma decisão. Nenhum estado de negócio.

O armazenamento de eventos é delegado a um EventStore injetado.
O EventBus NÃO armazena histórico — apenas publica.

Métodos:
  - subscribe(event_type, handler): inscreve handler para um tipo.
  - unsubscribe(event_type, handler): remove inscrição.
  - publish(event): notifica handlers + delega ao EventStore.
  - dispatch(event): alias semântico para publish.
  - handlers(event_type): retorna handlers inscritos (cópia).
  - clear(): remove todas as inscrições.
  - event_count(): total de eventos publicados (delega ao store).
  - has_subscribers(event_type): True se há handlers inscritos.

Compatibilidade:
  - history(), history_types(), event_count(), clear_history()
    continuam funcionando, agora delegando ao EventStore.
  - Se nenhum EventStore é injetado, um MemoryEventStore padrão é criado.
  - Nenhuma API pública quebra.

Características:
  - Síncrono: handlers executam na mesma thread do publish.
  - Genérico: não conhece tipos específicos de evento.
  - Múltiplos handlers podem ser inscritos para o mesmo tipo.
  - Um handler pode ser inscrito para múltiplos tipos.
  - Ordem de execução: ordem de inscrição.
"""

from __future__ import annotations

from typing import Any, Callable

from pipeline.event_store import EventStore, MemoryEventStore


# Tipo do handler: função que recebe um evento e retorna None ou evento.
EventHandler = Callable[[Any], Any]


class PipelineEventBus:
    """Barramento de eventos síncrono e genérico.

    Não conhece tipos específicos de evento. Apenas roteia.
    Armazenamento é delegado ao EventStore.
    """

    def __init__(self, store: EventStore | None = None) -> None:
        # Mapeia tipo de evento → lista de handlers (ordem de inscrição).
        self._subscriptions: dict[type, list[EventHandler]] = {}
        # EventStore para armazenamento (injetável).
        # Se não fornecido, usa MemoryEventStore padrão.
        self._store: EventStore = store if store is not None else MemoryEventStore()

    @property
    def store(self) -> EventStore:
        """EventStore usado pelo bus (apenas leitura)."""
        return self._store

    # ------------------------------------------------------------------
    # Inscrição
    # ------------------------------------------------------------------

    def subscribe(self, event_type: type, handler: EventHandler) -> None:
        """Inscreve handler para receber eventos do tipo event_type.

        Args:
            event_type: classe do evento (ex.: SpeechSegmentReceived).
            handler: callable que recebe o evento.

        Raises:
            TypeError: se handler não é callable.
        """
        if not callable(handler):
            raise TypeError("handler deve ser callable")
        if not isinstance(event_type, type):
            raise TypeError("event_type deve ser uma classe")
        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []
        # Evitar duplicação exata
        if handler not in self._subscriptions[event_type]:
            self._subscriptions[event_type].append(handler)

    def unsubscribe(self, event_type: type, handler: EventHandler) -> bool:
        """Remove inscrição de handler para event_type.

        Returns:
            True se removido, False se não estava inscrito.
        """
        if event_type not in self._subscriptions:
            return False
        handlers = self._subscriptions[event_type]
        if handler in handlers:
            handlers.remove(handler)
            if not handlers:
                del self._subscriptions[event_type]
            return True
        return False

    def unsubscribe_all(self, event_type: type) -> int:
        """Remove todas as inscrições de um tipo.

        Returns:
            Número de handlers removidos.
        """
        if event_type not in self._subscriptions:
            return 0
        count = len(self._subscriptions[event_type])
        del self._subscriptions[event_type]
        return count

    # ------------------------------------------------------------------
    # Publicação
    # ------------------------------------------------------------------

    def publish(self, event: Any) -> None:
        """Notifica todos os handlers inscritos no tipo do evento.

        Síncrono. Handlers executam na ordem de inscrição.
        O evento é armazenado no EventStore ANTES de notificar handlers.

        Erros em handlers NÃO são capturados aqui — o Engine trata
        erros via try/except ao redor do publish. O bus é puro.

        Args:
            event: evento a ser publicado.
        """
        # 1. Armazenar no EventStore
        self._store.append(event)
        # 2. Notificar handlers
        event_type = type(event)
        handlers = self._subscriptions.get(event_type, [])
        for handler in handlers:
            handler(event)

    def dispatch(self, event: Any) -> None:
        """Alias semântico para publish."""
        self.publish(event)

    # ------------------------------------------------------------------
    # Consulta — delegam ao EventStore
    # ------------------------------------------------------------------

    def handlers(self, event_type: type) -> tuple:
        """Retorna tuple com handlers inscritos para event_type (cópia)."""
        return tuple(self._subscriptions.get(event_type, []))

    def has_subscribers(self, event_type: type) -> bool:
        """True se há pelo menos um handler inscrito para event_type."""
        return bool(self._subscriptions.get(event_type))

    def subscribed_types(self) -> tuple:
        """Retorna tuple com tipos que têm inscrições."""
        return tuple(self._subscriptions.keys())

    def event_count(self) -> int:
        """Total de eventos publicados (delega ao EventStore)."""
        return self._store.count()

    def history(self) -> tuple:
        """Retorna tuple com todos os eventos publicados (delega ao store)."""
        return self._store.all()

    def history_types(self) -> tuple:
        """Retorna tuple com os tipos (str) dos eventos publicados."""
        return tuple(type(e).__name__ for e in self._store.all())

    def clear_history(self) -> None:
        """Limpa o histórico de eventos (delega ao store, não afeta inscrições)."""
        self._store.clear()

    def clear(self) -> None:
        """Remove todas as inscrições e limpa o EventStore."""
        self._subscriptions.clear()
        self._store.clear()

    def reset(self) -> None:
        """Alias para clear."""
        self.clear()


__all__ = [
    "PipelineEventBus",
    "EventHandler",
]
