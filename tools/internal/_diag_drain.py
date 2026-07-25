"""Diagnóstico Sprint 15.1 — rastreia drain loop e broadcast com WebSocket real."""

import logging
import time

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

from fastapi.testclient import TestClient
from api.app import create_app
from api.startup import reset_root, get_root
from api.websocket.events import reset_ws_manager, get_ws_manager
from api.websocket.audio_events import (
    get_audio_event_publisher, reset_audio_event_publisher,
    AudioEventPublisher,
)

# Patch drain loop com logging.
_orig_drain = AudioEventPublisher._drain_loop
_drain_count = 0

async def _patched_drain(self):
    global _drain_count
    while True:
        try:
            await __import__("asyncio").sleep(0.05)
            _drain_count += 1
            pending_count = len(self._pending)
            conn_count = len(self._manager._connections)
            queue_count = len(self._manager._queues)
            if _drain_count <= 10 or pending_count > 0:
                print(f"  [DRAIN #{_drain_count}] pending={pending_count} conns={conn_count} queues={queue_count}")
            if not self._pending:
                continue
            pending = self._pending[:]
            self._pending.clear()
            print(f"  [DRAIN] Broadcasting {len(pending)} events to {conn_count} connections")
            for event in pending:
                et = getattr(event, "event_type", "?")
                print(f"  [DRAIN] Broadcasting event_type={et}")
                await self._manager.broadcast_event(event)
                # Check queue sizes after broadcast.
                for ws, q in self._manager._queues.items():
                    print(f"  [DRAIN] Queue size after broadcast: {q.qsize()}")
        except __import__("asyncio").CancelledError:
            break
        except Exception as exc:
            print(f"  [DRAIN ERROR] {exc}")

AudioEventPublisher._drain_loop = _patched_drain

print("=== TESTE WebSocket Drain Loop ===\n")

reset_root()
reset_ws_manager()
reset_audio_event_publisher()

app = create_app()

with TestClient(app) as client:
    pub = get_audio_event_publisher()
    print(f"[CHECK] drain_task = {pub._drain_task}")

    root = get_root()
    cap = root.audio_capture
    print(f"[CHECK] on_frame definido? {cap._on_frame is not None}")

    mgr = get_ws_manager()

    with client.websocket_connect("/ws/events") as ws:
        hello = ws.receive_json()
        print(f"[CHECK] Hello: type={hello.get('type')}")
        print(f"[CHECK] connections={len(mgr._connections)} queues={len(mgr._queues)}")

        # POST /audio/start
        print("\n[STEP] POST /audio/start...")
        resp = client.post("/audio/start")
        print(f"[STEP] Status: {resp.status_code}")

        # Aguardar drain loops.
        print("\n[STEP] Aguardando 3s...")
        time.sleep(3.0)

        # Tentar receber mensagens nao bloqueantes.
        print("\n[STEP] Tentando receber mensagens...")
        received = 0
        for i in range(50):
            try:
                msg = ws.receive_text()
                received += 1
                print(f"  [WS RECV] {msg[:120]}...")
                if received >= 5:
                    break
            except Exception as e:
                print(f"  [WS RECV] Sem mensagem: {type(e).__name__}")
                break

        print(f"\n[RESULT] Mensagens recebidas: {received}")
        print(f"[RESULT] Drain loops executados: {_drain_count}")

        # Parar.
        client.post("/audio/stop")

    cap.shutdown()
    pub.stop()
    print("\n=== FIM ===")
