"""Diagnóstico Sprint 15.1 — teste com WebSocket real via TestClient.

Verifica se eventos audio.started e audio.level chegam ao cliente WebSocket.
"""

import asyncio
import logging
import time

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

from fastapi.testclient import TestClient
from api.app import create_app
from api.startup import reset_root, get_root
from api.websocket.events import reset_ws_manager
from api.websocket.audio_events import get_audio_event_publisher, reset_audio_event_publisher

print("=== TESTE WebSocket Real ===\n")

# Reset singletons.
reset_root()
reset_ws_manager()
reset_audio_event_publisher()

app = create_app()

with TestClient(app) as client:
    # Verificar estado do publisher apos startup.
    pub = get_audio_event_publisher()
    print(f"[CHECK] publisher._started = {pub._started}")
    print(f"[CHECK] publisher._drain_task = {pub._drain_task}")
    print(f"[CHECK] publisher._drain_task done? {pub._drain_task.done() if pub._drain_task else 'N/A'}")

    root = get_root()
    cap = root.audio_capture
    print(f"[CHECK] cap._on_frame definido? {cap._on_frame is not None}")

    # Verificar ConnectionManager.
    from api.websocket.events import get_ws_manager
    mgr = get_ws_manager()
    print(f"[CHECK] manager._connections = {len(mgr._connections)}")

    # Conectar WebSocket.
    print("\n[STEP] Conectando WebSocket...")
    with client.websocket_connect("/ws/events") as ws:
        # Receber hello.
        hello = ws.receive_json()
        print(f"[STEP] Hello recebido: type={hello.get('type')}")

        print(f"[CHECK] manager._connections = {len(mgr._connections)}")

        # Iniciar captura via POST.
        print("\n[STEP] POST /audio/start...")
        resp = client.post("/audio/start")
        print(f"[STEP] POST retornou: {resp.status_code} {resp.json()}")

        # Aguardar eventos WebSocket.
        print("\n[STEP] Aguardando eventos WebSocket (3s)...")
        events_received = []
        deadline = time.time() + 3.0
        while time.time() < deadline:
            try:
                # Non-blocking receive com timeout curto.
                msg = ws.receive_json(timeout=0.5)
                events_received.append(msg)
                et = msg.get("event", {}).get("event_type", "?")
                print(f"  [WS] Evento recebido: type={msg.get('type')} event_type={et}")
            except Exception as e:
                # Timeout ou sem mensagem.
                pass

        print(f"\n[RESULT] Eventos recebidos: {len(events_received)}")
        for e in events_received[:5]:
            et = e.get("event", {}).get("event_type", "?")
            print(f"  - {et}")

        # Parar captura.
        print("\n[STEP] POST /audio/stop...")
        resp = client.post("/audio/stop")
        print(f"[STEP] POST retornou: {resp.status_code}")

    cap.shutdown()
    pub.stop()
    print("\n=== FIM ===")
