# -*- coding: utf-8 -*-
"""Smoke test rápido do DirectMLBackend com modelo tiny."""
import sys
import time
import traceback
import numpy as np

print("Criando DirectMLBackend(tiny)...")
from transcricao.directml_backend import DirectMLBackend
b = DirectMLBackend("tiny", "float32", 0)

print("Carregando modelo (pode baixar na primeira vez)...")
try:
    t0 = time.monotonic()
    b.load()
    load_ms = (time.monotonic() - t0) * 1000
    print(f"Load OK em {load_ms:.0f}ms")
    print(f"backend_name: {b.backend_name}")
    print(f"actual_device: {b.actual_device}")
except Exception as e:
    print(f"ERRO LOAD: {type(e).__name__}: {e}")
    traceback.print_exc()
    sys.exit(1)

# Gerar áudio sintético de 10s
sr = 16000
n = int(10 * sr)
t = np.linspace(0, 10, n, endpoint=False)
audio = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

print("Transcrevendo 10s...")
try:
    t0 = time.monotonic()
    text, lang, logprob, segs = b.transcribe(audio, "pt", 1, False, 30)
    infer_ms = (time.monotonic() - t0) * 1000
    rtf = infer_ms / 1000 / 10
    print(f"Inferencia: {infer_ms:.0f}ms RTF={rtf:.3f}")
    print(f'Texto: "{text}"')
    print(f"Idioma: {lang}")
except Exception as e:
    print(f"ERRO TRANSCRIBE: {type(e).__name__}: {e}")
    traceback.print_exc()
    sys.exit(1)

b.unload()
print("Unload OK")
