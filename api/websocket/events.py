"""WebSocket — endpoint para streaming de eventos.

Fluxo:
  Backend (EventBus)
      ↓ EventDTO
  WebSocket endpoint
      ↓ WsEventModel (JSON)
  Frontend (WebSocketTransport)
      ↓ message
  Client SDK
      ↓ ClientEvent
  EventStream
      ↓ StreamEvent
  SnapshotStore + Hooks
      ↓
  Components

O WebSocket NÃO executa lógica de negócio. Apenas transmite eventos
da Presentation Layer para o frontend.

Recursos:
  - Hello handshake com versão da API
  - Heartbeat (ping/pong)
  - Reconexão preparada (cliente controla)
  - Backpressure simples (queue por conexão)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.schemas import (
    CURRENT_API_VERSION,
    EventModel,
    PresentationErrorModel,
    WsErrorModel,
    WsEventModel,
    WsHeartbeatAckModel,
    WsHelloModel,
)
from api.startup import get_root
from presentation import EventMapper

logger = logging.getLogger("api.websocket")

router = APIRouter(tags=["websocket"])

# Intervalo de heartbeat (segundos).
HEARTBEAT_INTERVAL_S = 30.0
# Tamanho máximo da fila por conexão (backpressure simples).
MAX_QUEUE_SIZE = 1000


# ---------------------------------------------------------------------------
# ConnectionManager — gerencia conexões WebSocket ativas.
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Gerencia conexões WebSocket ativas e broadcast de eventos.

    Não executa lógica de negócio. Apenas roteia eventos.
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._queues: dict[WebSocket, asyncio.Queue] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> asyncio.Queue:
        """Aceita conexão e cria fila dedicada."""
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
            queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
            self._queues[ws] = queue
        logger.info("WebSocket conectado. Total: %d", len(self._connections))
        return queue

    async def disconnect(self, ws: WebSocket) -> None:
        """Remove conexão."""
        async with self._lock:
            self._connections.discard(ws)
            self._queues.pop(ws, None)
        logger.info("WebSocket desconectado. Total: %d", len(self._connections))

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def broadcast_event(self, event_dto: Any) -> None:
        """Enfileira evento para todas as conexões ativas.

        Se a fila de uma conexão está cheia, descarta o evento mais antigo
        (backpressure simples). Não bloqueia.
        """
        if not self._connections:
            return
        async with self._lock:
            queues = list(self._queues.values())
        for q in queues:
            try:
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(event_dto)
            except asyncio.QueueFull:
                logger.warning("Fila WebSocket cheia — evento descartado.")

    async def send_to(self, ws: WebSocket, message: str) -> None:
        """Envia mensagem JSON para uma conexão específica."""
        await ws.send_text(message)


# Singleton — uma instância por processo.
_manager: ConnectionManager | None = None


def get_ws_manager() -> ConnectionManager:
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


def reset_ws_manager() -> None:
    """Reseta o singleton (útil para testes)."""
    global _manager
    _manager = None


# ---------------------------------------------------------------------------
# EventPublisher — conecta EventBus ao ConnectionManager.
# ---------------------------------------------------------------------------


class EventPublisher:
    """Bridge entre EventBus (Core) e ConnectionManager (WebSocket).

    Inscreve-se no EventBus e converte eventos core em EventDTO,
    depois broadcasta via ConnectionManager.

    Como o EventBus é síncrono e o WebSocket é assíncrono, usamos
    um loop de drenagem via asyncio.
    """

    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager
        self._pending: list = []
        self._drain_task: asyncio.Task | None = None
        self._subscribed = False

    def start(self) -> None:
        """Inicia o publisher — inscreve no EventBus e começa a drenar."""
        if self._subscribed:
            return
        root = get_root()
        # Inscreve em todos os eventos (event_type="*").
        # O PipelineEventBus suporta wildcard "*".
        try:
            root.bus.subscribe("*", self._on_event)
        except Exception:
            # Fallback: inscreve em tipos específicos conhecidos.
            from pipeline import (
                EvaluationRecorded, FeedbackRecorded, IntelligenceCompleted,
                PipelineError, PipelinePaused, PipelineResumed,
                PipelineStarted, PipelineStopped, PresentationCompleted,
                PresentationRequested, RankingCompleted, SearchCompleted,
                SearchRequested, SpeechRecognized, SpeechSegmentReceived,
                SpeechStarted, SpeechEnded, SpeechSegmentCreated,
                SpeechTranscribing, SpeechTranscribed,
                ReferenceDetected, ReferenceInvalid, IntentUnknown,
            )
            from pipeline.events import (
                SpeechPartial, SpeechPartialUpdated, ReferenceCandidate,
                IntentCandidate, SemanticInferenceCompleted,
                SemanticResolutionCompleted,
                VerseResolving, VerseResolved, VersePresented,
                VersePresentationFailed,
                SermonContextUpdated, SermonBookChanged,
                SermonChapterChanged, SermonTopicChanged,
            )
            for evt in [
                SpeechSegmentReceived, SpeechRecognized, SearchRequested,
                SearchCompleted, RankingCompleted, IntelligenceCompleted,
                PresentationRequested, PresentationCompleted, FeedbackRecorded,
                EvaluationRecorded, PipelineStarted, PipelineStopped,
                PipelinePaused, PipelineResumed, PipelineError,
                # Sprint 16 — Continuous Speech Pipeline
                SpeechStarted, SpeechEnded, SpeechSegmentCreated,
                SpeechTranscribing, SpeechTranscribed,
                # Sprint 17 — Biblical Intent & Reference Extraction
                ReferenceDetected, ReferenceInvalid, IntentUnknown,
                # Sprint 18 — Automatic Verse Presentation
                VerseResolving, VerseResolved, VersePresented,
                VersePresentationFailed,
                # Sprint 19 — Streaming Speech Pipeline
                SpeechPartial, SpeechPartialUpdated, ReferenceCandidate,
                # Sprint 20 — Semantic Understanding Engine
                IntentCandidate, SemanticInferenceCompleted,
                SemanticResolutionCompleted,
                # Sprint 21 — Sermon Memory Engine
                SermonContextUpdated, SermonBookChanged,
                SermonChapterChanged, SermonTopicChanged,
            ]:
                root.bus.subscribe(evt, self._on_event)
        self._subscribed = True
        # Inicia task de drenagem.
        try:
            loop = asyncio.get_event_loop()
            self._drain_task = loop.create_task(self._drain_loop())
        except RuntimeError:
            # Sem loop rodando (testes síncronos) — drenagem manual.
            pass

    def stop(self) -> None:
        """Para o publisher."""
        if self._drain_task is not None:
            self._drain_task.cancel()
            self._drain_task = None
        self._subscribed = False

    def _on_event(self, event: Any) -> None:
        """Callback síncrono do EventBus — enfileira para drenagem."""
        self._pending.append(event)

    async def _drain_loop(self) -> None:
        """Drena eventos pendentes e broadcasta via WebSocket."""
        while True:
            try:
                await asyncio.sleep(0.05)  # 50ms
                if not self._pending:
                    continue
                pending = self._pending[:]
                self._pending.clear()
                for event in pending:
                    dto = EventMapper.to_dto(event)
                    await self._manager.broadcast_event(dto)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Erro no drain loop: %s", exc)

    def drain_now(self) -> None:
        """Drenagem síncrona — útil para testes sem event loop."""
        if not self._pending:
            return
        pending = self._pending[:]
        self._pending.clear()
        for event in pending:
            dto = EventMapper.to_dto(event)
            # Broadcast síncrono: apenas enfileira se houver filas.
            for q in list(self._manager._queues.values()):
                try:
                    if q.full():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    q.put_nowait(dto)
                except asyncio.QueueFull:
                    pass


# Singleton.
_publisher: EventPublisher | None = None


def get_event_publisher() -> EventPublisher:
    global _publisher
    if _publisher is None:
        _publisher = EventPublisher(get_ws_manager())
    return _publisher


# ---------------------------------------------------------------------------
# Endpoint WebSocket.
# ---------------------------------------------------------------------------


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    """Endpoint WebSocket para streaming de eventos.

    Protocolo:
      1. Server envia `hello` com versão da API.
      2. Server envia `event` para cada evento publicado.
      3. Client pode enviar `heartbeat` — server responde `heartbeat_ack`.
      4. Client pode enviar `ping` — server responde `pong`.
    """
    manager = get_ws_manager()
    publisher = get_event_publisher()
    publisher.start()

    queue = await manager.connect(websocket)

    # 1. Hello handshake.
    hello = WsHelloModel(
        api=CURRENT_API_VERSION,
        server_time=time.time(),
    )
    await manager.send_to(websocket, hello.model_dump_json())

    # Tasks concorrentes: receiver + sender + heartbeat.
    async def receiver() -> None:
        """Recebe mensagens do cliente (heartbeat/ping)."""
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                mtype = msg.get("type", "")
                if mtype == "heartbeat" or mtype == "ping":
                    ack = WsHeartbeatAckModel(server_time=time.time())
                    await manager.send_to(websocket, ack.model_dump_json())
                elif mtype == "close":
                    break
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.debug("Receiver encerrado: %s", exc)

    async def sender() -> None:
        """Envia eventos da fila para o cliente."""
        try:
            while True:
                event_dto = await queue.get()
                ws_event = WsEventModel(event=EventModel.from_dto(event_dto))
                await manager.send_to(websocket, ws_event.model_dump_json())
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.debug("Sender encerrado: %s", exc)

    async def heartbeat() -> None:
        """Envia heartbeat periódico para o cliente."""
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_S)
                ack = WsHeartbeatAckModel(server_time=time.time())
                await manager.send_to(websocket, ack.model_dump_json())
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    tasks = [
        asyncio.create_task(receiver()),
        asyncio.create_task(sender()),
        asyncio.create_task(heartbeat()),
    ]
    try:
        # Aguarda qualquer task terminar (em caso de desconexão).
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        await manager.disconnect(websocket)
