"""Teste com servidor real — verifica se eventos WebSocket chegam via uvicorn."""

import asyncio
import json
import urllib.request
import websockets


async def test_real_ws():
    # Verificar se o servidor esta rodando.
    try:
        resp = urllib.request.urlopen("http://localhost:8000/audio/devices", timeout=2)
        print(f"[CHECK] Backend respondendo: {resp.status}")
    except Exception as e:
        print(f"[FAIL] Backend nao responde: {e}")
        return

    # Conectar via WebSocket real.
    try:
        async with websockets.connect("ws://localhost:8000/ws/events") as ws:
            print("[CHECK] WebSocket conectado")

            # Receber hello.
            hello_raw = await asyncio.wait_for(ws.recv(), timeout=2)
            hello = json.loads(hello_raw)
            print(f"[CHECK] Hello: type={hello.get('type')}")

            # POST /audio/start via HTTP.
            req = urllib.request.Request("http://localhost:8000/audio/start", method="POST")
            resp = urllib.request.urlopen(req, timeout=5)
            print(f"[CHECK] POST /audio/start: {resp.status}")

            # Receber eventos WebSocket.
            events = []
            try:
                for i in range(10):
                    msg_raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    msg = json.loads(msg_raw)
                    et = msg.get("event", {}).get("event_type", "?")
                    events.append(et)
                    print(f"  [WS] Evento {i+1}: {et}")
            except asyncio.TimeoutError:
                print(f"  [WS] Timeout apos {len(events)} eventos")

            print(f"\n[RESULT] Eventos recebidos: {len(events)}")

            # POST /audio/stop.
            req2 = urllib.request.Request("http://localhost:8000/audio/stop", method="POST")
            urllib.request.urlopen(req2, timeout=5)
            print("[CHECK] POST /audio/stop OK")

    except Exception as e:
        print(f"[FAIL] WebSocket error: {type(e).__name__}: {e}")


asyncio.run(test_real_ws())
