"""PipelineCoordinator — registra Handlers no EventBus.

Responsabilidade única: registrar Handlers para seus eventos.
Nada além disso. Nenhuma regra de negócio. Nenhuma decisão.

O Coordinator conhece:
  - quais Handlers respondem a quais eventos
  - como inscrever cada Handler no EventBus

O Coordinator NÃO conhece:
  - lógica de negócio
  - fluxo de execução
  - estado do pipeline
  - dependências externas (STT, Searcher, etc.)
"""

from __future__ import annotations

from typing import Any

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    EvaluationRecorded,
    FeedbackRecorded,
    IntelligenceCompleted,
    PresentationCompleted,
    RankingCompleted,
    SearchCompleted,
    SearchRequested,
    SpeechRecognized,
    SpeechSegmentReceived,
)
from pipeline.handlers import (
    ContextHandler,
    EvaluationHandler,
    FeedbackHandler,
    IntelligenceHandler,
    PresentationHandler,
    RankingHandler,
    RecognitionHandler,
    SearchHandler,
)


class PipelineCoordinator:
    """Coordenador de Handlers.

    Registra cada Handler para seu evento de entrada no EventBus.
    Retorna a lista de handlers registrados para inspeção/teste.
    """

    def __init__(self, bus: PipelineEventBus) -> None:
        self._bus = bus
        self._registered: list = []

    @property
    def bus(self) -> PipelineEventBus:
        return self._bus

    @property
    def registered_handlers(self) -> tuple:
        """Retorna tuple com handlers registrados."""
        return tuple(self._registered)

    @property
    def handler_count(self) -> int:
        """Número de handlers registrados."""
        return len(self._registered)

    def register(self, handler: Any, event_type: type) -> None:
        """Registra um handler para um tipo de evento.

        Args:
            handler: instância do handler (deve ter método handle).
            event_type: classe do evento que o handler processa.
        """
        if not hasattr(handler, "handle"):
            raise TypeError("handler deve ter método handle(event)")
        if not isinstance(event_type, type):
            raise TypeError("event_type deve ser uma classe")
        self._bus.subscribe(event_type, handler.handle)
        self._registered.append((handler, event_type))

    def unregister(self, handler: Any, event_type: type) -> bool:
        """Remove registro de um handler."""
        if not hasattr(handler, "handle"):
            return False
        result = self._bus.unsubscribe(event_type, handler.handle)
        if result:
            for i, (h, et) in enumerate(self._registered):
                if h is handler and et is event_type:
                    self._registered.pop(i)
                    break
        return result

    def unregister_all(self) -> int:
        """Remove todos os registros. Retorna quantos foram removidos."""
        count = len(self._registered)
        for handler, event_type in list(self._registered):
            self._bus.unsubscribe(event_type, handler.handle)
        self._registered.clear()
        return count

    def is_registered(self, handler: Any, event_type: type) -> bool:
        """True se o handler está registrado para o evento."""
        for h, et in self._registered:
            if h is handler and et is event_type:
                return True
        return False

    def register_default_flow(self, handlers: dict) -> None:
        """Registra o fluxo padrão do Pipeline.

        Args:
            handlers: dict com chaves:
                "recognition": RecognitionHandler
                "search": SearchHandler
                "ranking": RankingHandler
                "intelligence": IntelligenceHandler
                "presentation": PresentationHandler
                "feedback": FeedbackHandler
                "evaluation": EvaluationHandler
                "context": ContextHandler (opcional)
        """
        mapping = {
            "recognition": (SpeechSegmentReceived, RecognitionHandler),
            "search": (SpeechRecognized, SearchHandler),
            "ranking": (SearchCompleted, RankingHandler),
            "intelligence": (RankingCompleted, IntelligenceHandler),
            "presentation": (IntelligenceCompleted, PresentationHandler),
            "feedback": (PresentationCompleted, FeedbackHandler),
            "evaluation": (FeedbackRecorded, EvaluationHandler),
            "context": (SpeechRecognized, ContextHandler),
        }
        for key, (event_type, expected_cls) in mapping.items():
            handler = handlers.get(key)
            if handler is None:
                continue
            self.register(handler, event_type)


__all__ = [
    "PipelineCoordinator",
]
