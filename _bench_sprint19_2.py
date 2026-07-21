"""Sprint 19.2 — Benchmark real CPU × DirectML (Etapa 2).

Regras:
  - Mesmo áudio (sintético 10s, 30s; ou arquivo real via --audio-path).
  - Mesmo modelo (default: small — equilíbrio entre tamanho e relevância).
  - Mesmo idioma (pt).
  - Mesmo beam_size (1 = greedy, recomendado para DirectML).
  - Sem otimização específica de nenhum backend.
  - 5 iterações + 1 warmup.

Mede:
  - load_ms (tempo de carregamento do modelo)
  - first_inference_ms (1ª inferência após load, sem warmup)
  - mean_ms, p95_ms (depois do warmup)
  - RTF (mean_ms / 1000 / audio_duration_s)
  - RAM (rss do processo)
  - VRAM (aproximação — DirectML não expõe API)

Uso:
    python _bench_sprint19_2.py --model small --iterations 5
    python _bench_sprint19_2.py --model tiny --audio-path audio.wav

Sprint 19.2 — Avaliação de Backends STT para GPU AMD.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _ram_mb() -> float:
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0.0


def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f) if f != c else s[f]


def _generate_audio(duration_s: float, sr: int = 16000) -> Any:
    """Áudio sintético — senoide modulada + ruído + envelope."""
    import numpy as np
    n = int(duration_s * sr)
    t = np.linspace(0, duration_s, n, endpoint=False)
    freq = 200 + 100 * np.sin(2 * np.pi * 2 * t)
    audio = 0.3 * np.sin(2 * np.pi * freq * t) + 0.05 * np.random.randn(n)
    envelope = np.where((t * 4) % 1.0 < 0.7, 1.0, 0.1)
    audio = audio * envelope
    return (audio / max(abs(audio).max(), 1.0)).astype(np.float32)


def _load_audio(path: str, sr: int = 16000) -> Any:
    try:
        import librosa
        audio, _ = librosa.load(path, sr=sr, mono=True)
        return audio.astype(np.float32)
    except ImportError:
        pass
    try:
        import soundfile as sf
        audio, _ = sf.read(path, dtype="float32")
        return audio
    except ImportError:
        raise RuntimeError("Install librosa or soundfile to load audio files.")


# ---------------------------------------------------------------------------
# Benchmark Faster-Whisper CPU
# ---------------------------------------------------------------------------


def bench_faster_whisper_cpu(
    model: str, audio: Any, language: str, iterations: int
) -> dict[str, Any]:
    """Benchmark FasterWhisperBackend (ctranslate2) em CPU."""
    print(f"\n[CPU] FasterWhisperBackend (model={model}, int8)")
    from config.models import STTConfig, VadConfig
    from transcricao.stt import FasterWhisperBackend

    cfg = STTConfig(
        model=model, device="cpu", compute_type="int8",
        language=language, chunk_length_s=30,
        vad=VadConfig(mode="silero", min_speech_ms=250, pause_threshold_ms=600),
        backend="faster-whisper",
    )
    backend = FasterWhisperBackend(cfg)

    ram_before = _ram_mb()
    print(f"[CPU] RAM antes do load: {ram_before:.0f} MB")

    # Load.
    t0 = time.monotonic()
    try:
        backend.load()
    except Exception as e:
        print(f"[CPU] LOAD FALHOU: {e}")
        return {"label": "cpu", "error": f"load: {e}"}
    load_ms = (time.monotonic() - t0) * 1000
    ram_after_load = _ram_mb()
    print(f"[CPU] Load: {load_ms:.0f}ms, RAM após load: {ram_after_load:.0f}MB")

    # Primeira inferência (sem warmup).
    audio_dur = len(audio) / 16000
    t0 = time.monotonic()
    try:
        text_first, _, _, _ = backend.transcribe(audio, language, 1, False, 30)
    except Exception as e:
        print(f"[CPU] 1ª inferência falhou: {e}")
        backend.close()
        return {"label": "cpu", "error": f"first infer: {e}", "load_ms": load_ms}
    first_ms = (time.monotonic() - t0) * 1000
    print(f"[CPU] 1ª inferência: {first_ms:.0f}ms (texto len={len(text_first)})")

    # Warmup (descartar).
    backend.transcribe(audio, language, 1, False, 30)

    # Iterações medidas.
    times = []
    texts = []
    ram_samples = []
    for i in range(iterations):
        ram_samples.append(_ram_mb())
        t0 = time.monotonic()
        text, _, _, _ = backend.transcribe(audio, language, 1, False, 30)
        elapsed = (time.monotonic() - t0) * 1000
        times.append(elapsed)
        texts.append(text)
        print(f"[CPU] iter {i+1}/{iterations}: {elapsed:.0f}ms")

    ram_final = _ram_mb()
    backend.close()
    gc.collect()

    mean_ms = statistics.mean(times)
    p95_ms = _percentile(times, 95)
    rtf = mean_ms / 1000 / audio_dur

    print(f"[CPU] mean={mean_ms:.0f}ms p95={p95_ms:.0f}ms RTF={rtf:.3f}")
    print(f"[CPU] RAM final: {ram_final:.0f}MB (delta: {ram_final-ram_before:+.0f}MB)")

    return {
        "label": "cpu-faster-whisper",
        "model": model,
        "compute_type": "int8",
        "device": "cpu",
        "load_ms": load_ms,
        "first_inference_ms": first_ms,
        "text_first": text_first,
        "iterations": iterations,
        "times_ms": times,
        "mean_ms": mean_ms,
        "p95_ms": p95_ms,
        "rtf": rtf,
        "ram_before_mb": ram_before,
        "ram_after_load_mb": ram_after_load,
        "ram_final_mb": ram_final,
        "ram_max_mb": max(ram_samples) if ram_samples else ram_final,
        "ram_delta_mb": ram_final - ram_before,
        "text_sample": texts[-1] if texts else "",
    }


# ---------------------------------------------------------------------------
# Benchmark DirectML
# ---------------------------------------------------------------------------


def bench_directml(
    model: str, audio: Any, language: str, iterations: int
) -> dict[str, Any]:
    """Benchmark DirectMLBackend (ONNX Runtime + DirectML)."""
    print(f"\n[DirectML] DirectMLBackend (model={model}, float32)")
    from transcricao.directml_backend import DirectMLBackend

    backend = DirectMLBackend(model_name=model, compute_type="float32", device_id=0)

    ram_before = _ram_mb()
    print(f"[DirectML] RAM antes do load: {ram_before:.0f} MB")

    # Load.
    t0 = time.monotonic()
    try:
        backend.load()
    except Exception as e:
        print(f"[DirectML] LOAD FALHOU: {e}")
        return {"label": "directml", "error": f"load: {e}"}
    load_ms = (time.monotonic() - t0) * 1000
    ram_after_load = _ram_mb()
    print(f"[DirectML] Load: {load_ms:.0f}ms, RAM após load: {ram_after_load:.0f}MB")

    # Primeira inferência (sem warmup).
    audio_dur = len(audio) / 16000
    t0 = time.monotonic()
    try:
        text_first, _, _, _ = backend.transcribe(audio, language, 1, False, 30)
    except Exception as e:
        print(f"[DirectML] 1ª inferência falhou: {e}")
        backend.unload()
        return {"label": "directml", "error": f"first infer: {e}", "load_ms": load_ms}
    first_ms = (time.monotonic() - t0) * 1000
    print(f"[DirectML] 1ª inferência: {first_ms:.0f}ms (texto len={len(text_first)})")

    # Warmup.
    backend.transcribe(audio, language, 1, False, 30)

    # Iterações medidas.
    times = []
    texts = []
    ram_samples = []
    for i in range(iterations):
        ram_samples.append(_ram_mb())
        t0 = time.monotonic()
        try:
            text, _, _, _ = backend.transcribe(audio, language, 1, False, 30)
        except Exception as e:
            print(f"[DirectML] iter {i+1} falhou: {e}")
            backend.unload()
            return {
                "label": "directml", "load_ms": load_ms,
                "first_inference_ms": first_ms,
                "error": f"iter {i+1}: {e}",
                "iterations_completed": i,
            }
        elapsed = (time.monotonic() - t0) * 1000
        times.append(elapsed)
        texts.append(text)
        print(f"[DirectML] iter {i+1}/{iterations}: {elapsed:.0f}ms")

    ram_final = _ram_mb()
    backend.unload()
    gc.collect()

    mean_ms = statistics.mean(times)
    p95_ms = _percentile(times, 95)
    rtf = mean_ms / 1000 / audio_dur

    print(f"[DirectML] mean={mean_ms:.0f}ms p95={p95_ms:.0f}ms RTF={rtf:.3f}")
    print(f"[DirectML] RAM final: {ram_final:.0f}MB (delta: {ram_final-ram_before:+.0f}MB)")

    return {
        "label": "directml-onnx",
        "model": model,
        "compute_type": "float32",
        "device": "directml",
        "load_ms": load_ms,
        "first_inference_ms": first_ms,
        "text_first": text_first,
        "iterations": iterations,
        "times_ms": times,
        "mean_ms": mean_ms,
        "p95_ms": p95_ms,
        "rtf": rtf,
        "ram_before_mb": ram_before,
        "ram_after_load_mb": ram_after_load,
        "ram_final_mb": ram_final,
        "ram_max_mb": max(ram_samples) if ram_samples else ram_final,
        "ram_delta_mb": ram_final - ram_before,
        "text_sample": texts[-1] if texts else "",
        "vram_note": "DirectML não expõe API para VRAM — usar Gerenciador de Tarefas",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sprint 19.2 — Benchmark CPU × DirectML"
    )
    parser.add_argument("--model", type=str, default="small",
                        help="Modelo (default: small)")
    parser.add_argument("--iterations", type=int, default=5,
                        help="Iterações medidas por backend (default: 5)")
    parser.add_argument("--audio-path", type=str, default="",
                        help="Arquivo de áudio (default: sintético)")
    parser.add_argument("--duration", type=float, default=10.0,
                        help="Duração do áudio sintético (default: 10s)")
    parser.add_argument("--language", type=str, default="pt")
    parser.add_argument("--output", type=str, default="bench_sprint19_2_results.json")
    parser.add_argument("--skip-cpu", action="store_true")
    parser.add_argument("--skip-directml", action="store_true")
    args = parser.parse_args()

    print("=" * 70)
    print("Sprint 19.2 — Benchmark CPU × DirectML")
    print("=" * 70)
    print(f"Model: {args.model}")
    print(f"Language: {args.language}")
    print(f"Iterations: {args.iterations}")

    if args.audio_path:
        print(f"Audio: {args.audio_path}")
        audio = _load_audio(args.audio_path)
    else:
        print(f"Audio: synthetic ({args.duration}s)")
        audio = _generate_audio(args.duration)

    audio_dur = len(audio) / 16000
    print(f"Audio duration: {audio_dur:.1f}s")

    results = {
        "model": args.model,
        "language": args.language,
        "iterations": args.iterations,
        "audio_duration_s": audio_dur,
        "audio_source": args.audio_path or "synthetic",
        "timestamp": time.time(),
    }

    if not args.skip_cpu:
        results["cpu"] = bench_faster_whisper_cpu(
            args.model, audio, args.language, args.iterations
        )
        gc.collect()

    if not args.skip_directml:
        results["directml"] = bench_directml(
            args.model, audio, args.language, args.iterations
        )
        gc.collect()

    # Comparação.
    if "cpu" in results and "directml" in results:
        cpu = results["cpu"]
        dml = results["directml"]
        if "error" not in cpu and "error" not in dml:
            speedup = cpu["mean_ms"] / dml["mean_ms"] if dml["mean_ms"] > 0 else 0
            print("\n" + "=" * 70)
            print("COMPARAÇÃO")
            print("=" * 70)
            print(f"  {'Métrica':<25s} {'CPU':>15s} {'DirectML':>15s}")
            print(f"  {'-'*55}")
            print(f"  {'Load (ms)':<25s} {cpu['load_ms']:>15.0f} {dml['load_ms']:>15.0f}")
            print(f"  {'1ª inferência (ms)':<25s} {cpu['first_inference_ms']:>15.0f} {dml['first_inference_ms']:>15.0f}")
            print(f"  {'Mean (ms)':<25s} {cpu['mean_ms']:>15.0f} {dml['mean_ms']:>15.0f}")
            print(f"  {'p95 (ms)':<25s} {cpu['p95_ms']:>15.0f} {dml['p95_ms']:>15.0f}")
            print(f"  {'RTF':<25s} {cpu['rtf']:>15.3f} {dml['rtf']:>15.3f}")
            print(f"  {'RAM max (MB)':<25s} {cpu['ram_max_mb']:>15.0f} {dml['ram_max_mb']:>15.0f}")
            print(f"  {'RAM delta (MB)':<25s} {cpu['ram_delta_mb']:>+15.0f} {dml['ram_delta_mb']:>+15.0f}")
            print(f"  {'Texto CPU (len)':<25s} {len(cpu['text_first']):>15d} {len(dml['text_first']):>15d}")
            print()
            print(f"  Speedup (CPU/DirectML): {speedup:.2f}x")
            if speedup > 1.0:
                print(f"  → DirectML é {speedup:.2f}x mais rápido")
            else:
                print(f"  → CPU é {1/speedup:.2f}x mais rápido que DirectML")
            results["comparison"] = {
                "speedup_cpu_over_directml": 1/speedup if speedup > 0 else 0,
                "speedup_directml_over_cpu": speedup,
                "winner": "directml" if speedup > 1.0 else "cpu",
            }

    output = Path(args.output)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str, ensure_ascii=False)
    print(f"\nResultados salvos em {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
