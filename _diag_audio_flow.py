"""Diagnóstico Sprint 15.1 — rastreia cada etapa do fluxo de captura.

Instrumenta:
  1. AudioCaptureService.start() — stream aberto?
  2. _audio_callback — callback dispara?
  3. AudioFrame criado?
  4. _on_frame definido? (publisher conectado?)
  5. AudioEventPublisher.on_frame() — chamado?
  6. _pending enfileirado?
  7. _drain_loop rodando? broadcast_event chamado?
  8. ConnectionManager — conexões ativas?
"""

import asyncio
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

# Patch com logs de diagnóstico.
from microfone.audio_capture_service import AudioCaptureService, AudioFrame
from api.websocket.audio_events import AudioEventPublisher, _make_audio_event
from api.websocket.events import ConnectionManager

# --- Patch AudioCaptureService._audio_callback ---
_orig_callback = AudioCaptureService._audio_callback
_diag = {"callback_count": 0, "on_frame_count": 0, "frames": []}

def _patched_callback(self, indata, frames, time_info, status):
    _diag["callback_count"] += 1
    if _diag["callback_count"] <= 3:
        print(f"  [DIAG 2] callback disparou #{_diag['callback_count']} frames={frames}")
    _orig_callback(self, indata, frames, time_info, status)
    if _diag["callback_count"] <= 3:
        latest = self.get_latest_frame()
        print(f"  [DIAG 3] AudioFrame criado: rms={latest.rms:.6f} peak={latest.peak:.6f}")
        print(f"  [DIAG 4] _on_frame definido? {self._on_frame is not None}")

AudioCaptureService._audio_callback = _patched_callback

# --- Patch AudioEventPublisher.on_frame ---
_orig_on_frame = AudioEventPublisher.on_frame

def _patched_on_frame(self, frame):
    _diag["on_frame_count"] += 1
    if _diag["on_frame_count"] <= 3:
        print(f"  [DIAG 5] on_frame chamado #{_diag['on_frame_count']} rms={frame.rms:.6f}")
    _orig_on_frame(self, frame)
    if _diag["on_frame_count"] <= 3:
        print(f"  [DIAG 6] _pending size={len(self._pending)} drain_task={self._drain_task}")

AudioEventPublisher.on_frame = _patched_on_frame

# --- Patch ConnectionManager.broadcast_event ---
_orig_broadcast = ConnectionManager.broadcast_event

async def _patched_broadcast(self, event_dto):
    et = getattr(event_dto, "event_type", "?")
    if et == "audio.level":
        print(f"  [DIAG 7] broadcast_event audio.level connections={len(self._connections)}")
    await _orig_broadcast(self, event_dto)

ConnectionManager.broadcast_event = _patched_broadcast


async def main():
    print("\n=== DIAGNÓSTICO Sprint 15.1 ===\n")

    # 1. Criar CompositionRoot real
    from api.startup import get_root, reset_root
    reset_root()
    root = get_root()
    cap = root.audio_capture
    print(f"[DIAG 0] AudioCaptureService criado: sr={cap.sample_rate} ch={cap.channels}")

    # 2. Conectar publisher (simula on_startup)
    from api.websocket.audio_events import connect_audio_capture_to_publisher
    print("[DIAG 1] Conectando AudioCaptureService -> AudioEventPublisher...")
    connect_audio_capture_to_publisher(cap)
    print(f"  _on_frame definido? {cap._on_frame is not None}")

    # Verificar drain task
    from api.websocket.audio_events import get_audio_event_publisher
    pub = get_audio_event_publisher()
    print(f"  publisher._drain_task = {pub._drain_task}")
    print(f"  publisher._started = {pub._started}")

    # 3. Iniciar captura
    print("\n[DIAG] Iniciando captura...")
    result = cap.start()
    print(f"  start() retornou: {result}")

    # 4. Aguardar callbacks
    print("\n[DIAG] Aguardando 2 segundos de captura...")
    await asyncio.sleep(2.0)

    # 5. Verificar estado
    print(f"\n[DIAG RESULTADOS]")
    print(f"  callback_count: {_diag['callback_count']}")
    print(f"  on_frame_count: {_diag['on_frame_count']}")
    print(f"  frames no buffer: {len(cap._frames)}")
    print(f"  pending no publisher: {len(pub._pending)}")
    print(f"  drain_task ativo: {pub._drain_task is not None and not pub._drain_task.done()}")

    # 6. Parar
    cap.stop()
    pub.stop()
    cap.shutdown()
    print("\n[DIAG] Captura parada.")

if __name__ == "__main__":
    asyncio.run(main())
