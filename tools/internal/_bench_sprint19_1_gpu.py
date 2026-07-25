"""Benchmark CPU × GPU (DirectML) para Sprint 19.1.

Responsabilidade:
  - Medir latência e RTF do mesmo áudio nos backends CPU e DirectML.
  - Coletar p50, p95, p99, tempo médio.
  - Medir uso de RAM e VRAM.
  - Salvar resultados em JSON para comparação.

Uso:
    python _bench_sprint19_1_gpu.py [--iterations N] [--audio-path PATH]

Sprint 19.1 — GPU Runtime & Hardware Acceleration.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

# Garantir encoding UTF-8 no Windows.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _percentile(data: list[float], pct: float) -> float:
    """Calcula percentil (p50, p95, p99)."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    if f == c:
        return sorted_data[f]
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)


def _get_ram_mb() -> float:
    """RAM usada pelo processo em MB."""
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        return proc.memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0.0


def _get_vram_mb() -> float:
    """VRAM usada (aproximação via GPU vendor).

    Para AMD no Windows, não há API simples para ler VRAM usada.
    Retorna 0 se não disponível.
    """
    # Para DirectML, não há API direta para ler VRAM usada.
    # Em produção, usar AMD Adrenalin Performance Monitor ou
    # Windows Performance Toolkit.
    return 0.0


def _generate_test_audio(duration_s: float = 6.0, sr: int = 16000) -> Any:
    """Gera áudio de teste (senoide + ruído) se nenhum arquivo for fornecido.

    Nota: áudio sintético não testa o Whisper de forma realista, mas
    mede a latência de inferência (encoder + decoder) sem depender
    de áudio real. Para benchmark realista, usar --audio-path.
    """
    import numpy as np
    n = int(duration_s * sr)
    t = np.linspace(0, duration_s, n, endpoint=False)
    # Senoide 440Hz + ruído branco (simula fala com ruído).
    audio = 0.3 * np.sin(2 * np.pi * 440 * t) + 0.1 * np.random.randn(n)
    # Normalizar para [-1.0, 1.0].
    audio = audio / max(abs(audio).max(), 1.0)
    return audio.astype(np.float32)


def _load_audio(path: str, sr: int = 16000) -> Any:
    """Carrega áudio de um arquivo (wav, mp3) via librosa ou soundfile."""
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
        raise RuntimeError(
            "Install librosa or soundfile to load audio files: "
            "pip install librosa"
        )


def _benchmark_backend(
    backend: Any,
    audio: Any,
    language: str,
    iterations: int,
    label: str,
) -> dict[str, Any]:
    """Executa benchmark de um backend.

    Returns:
        Dict com latências, RTF, RAM, VRAM.
    """
    print(f"\n[{label}] Running {iterations} iterations...")
    print(f"[{label}] Audio length: {len(audio) / 16000:.1f}s")

    latencies_ms: list[float] = []
    rtf_values: list[float] = []
    ram_samples: list[float] = []
    vram_samples: list[float] = []
    audio_duration_s = len(audio) / 16000

    # Warmup (1ª inferência é mais lenta — JIT, cache).
    print(f"[{label}] Warmup...")
    try:
        backend.transcribe(audio, language, 1, False, 30)
    except Exception as e:
        print(f"[{label}] Warmup failed: {e}")
        return {
            "label": label,
            "error": str(e),
            "iterations": 0,
        }

    ram_before = _get_ram_mb()
    vram_before = _get_vram_mb()

    for i in range(iterations):
        t0 = time.monotonic()
        try:
            text, lang, logprob, segs = backend.transcribe(
                audio, language, 1, False, 30
            )
        except Exception as e:
            print(f"[{label}] Iteration {i+1} failed: {e}")
            return {
                "label": label,
                "error": f"iteration {i+1}: {e}",
                "iterations_completed": i,
            }
        elapsed_ms = (time.monotonic() - t0) * 1000
        rtf = elapsed_ms / 1000 / audio_duration_s

        latencies_ms.append(elapsed_ms)
        rtf_values.append(rtf)
        ram_samples.append(_get_ram_mb())
        vram_samples.append(_get_vram_mb())

        if (i + 1) % 5 == 0 or i == 0:
            print(
                f"[{label}] iter {i+1}/{iterations}: "
                f"{elapsed_ms:.0f}ms RTF={rtf:.2f} "
                f"RAM={ram_samples[-1]:.0f}MB"
            )

    ram_after = _get_ram_mb()
    vram_after = _get_vram_mb()

    result = {
        "label": label,
        "iterations": iterations,
        "audio_duration_s": audio_duration_s,
        "latency_ms": {
            "mean": statistics.mean(latencies_ms),
            "median": statistics.median(latencies_ms),
            "p50": _percentile(latencies_ms, 50),
            "p95": _percentile(latencies_ms, 95),
            "p99": _percentile(latencies_ms, 99),
            "min": min(latencies_ms),
            "max": max(latencies_ms),
            "stdev": statistics.stdev(latencies_ms) if len(latencies_ms) > 1 else 0,
        },
        "rtf": {
            "mean": statistics.mean(rtf_values),
            "median": statistics.median(rtf_values),
            "p50": _percentile(rtf_values, 50),
            "p95": _percentile(rtf_values, 95),
            "p99": _percentile(rtf_values, 99),
        },
        "ram_mb": {
            "before": ram_before,
            "after": ram_after,
            "delta": ram_after - ram_before,
            "mean_during": statistics.mean(ram_samples),
            "max": max(ram_samples),
        },
        "vram_mb": {
            "before": vram_before,
            "after": vram_after,
            "delta": vram_after - vram_before,
            "mean_during": statistics.mean(vram_samples),
            "max": max(vram_samples),
        },
        "raw_latencies_ms": latencies_ms,
    }

    print(f"\n[{label}] Results:")
    print(f"  Latency mean: {result['latency_ms']['mean']:.0f}ms")
    print(f"  Latency p50:  {result['latency_ms']['p50']:.0f}ms")
    print(f"  Latency p95:  {result['latency_ms']['p95']:.0f}ms")
    print(f"  Latency p99:  {result['latency_ms']['p99']:.0f}ms")
    print(f"  RTF mean:     {result['rtf']['mean']:.2f}")
    print(f"  RAM delta:    {result['ram_mb']['delta']:.0f}MB")
    print(f"  RAM max:      {result['ram_mb']['max']:.0f}MB")

    return result


def _benchmark_cpu(
    model_name: str, audio: Any, language: str, iterations: int
) -> dict[str, Any]:
    """Benchmark CPU (FasterWhisperBackend com int8)."""
    from config.models import STTConfig, VadConfig
    from transcricao.stt import FasterWhisperBackend

    cfg = STTConfig(
        model=model_name,
        device="cpu",
        compute_type="int8",
        language=language,
        chunk_length_s=30,
        vad=VadConfig(mode="silero", min_speech_ms=250, pause_threshold_ms=600),
        backend="faster-whisper",
    )
    backend = FasterWhisperBackend(cfg)
    print(f"\nLoading CPU backend (model={model_name}, int8)...")
    t0 = time.monotonic()
    backend.load()
    load_ms = (time.monotonic() - t0) * 1000
    print(f"CPU backend loaded in {load_ms:.0f}ms")

    try:
        result = _benchmark_backend(
            backend, audio, language, iterations, "CPU"
        )
        result["load_ms"] = load_ms
        result["backend_name"] = backend.backend_name if hasattr(backend, "backend_name") else "faster-whisper-cpu"
        return result
    finally:
        backend.close()


def _benchmark_directml(
    model_name: str, audio: Any, language: str, iterations: int
) -> dict[str, Any]:
    """Benchmark DirectML (DirectMLBackend com float32)."""
    from transcricao.directml_backend import DirectMLBackend

    backend = DirectMLBackend(
        model_name=model_name,
        compute_type="float32",
        device_id=0,
    )
    print(f"\nLoading DirectML backend (model={model_name}, float32)...")
    t0 = time.monotonic()
    try:
        backend.load()
    except Exception as e:
        print(f"DirectML load failed: {e}")
        return {
            "label": "DirectML",
            "error": f"load failed: {e}",
            "iterations": 0,
        }
    load_ms = (time.monotonic() - t0) * 1000
    print(f"DirectML backend loaded in {load_ms:.0f}ms")

    try:
        result = _benchmark_backend(
            backend, audio, language, iterations, "DirectML"
        )
        result["load_ms"] = load_ms
        result["backend_name"] = backend.backend_name
        return result
    finally:
        backend.unload()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark CPU × GPU (DirectML) — Sprint 19.1"
    )
    parser.add_argument(
        "--iterations", type=int, default=10,
        help="Número de iterações por backend (default: 10)"
    )
    parser.add_argument(
        "--audio-path", type=str, default="",
        help="Caminho para arquivo de áudio (default: senoide sintética)"
    )
    parser.add_argument(
        "--model", type=str, default="small",
        help="Modelo Whisper (default: small — large-v3-turbo é pesado para benchmark)"
    )
    parser.add_argument(
        "--language", type=str, default="pt",
        help="Idioma (default: pt)"
    )
    parser.add_argument(
        "--duration", type=float, default=6.0,
        help="Duração do áudio sintético em segundos (default: 6.0)"
    )
    parser.add_argument(
        "--output", type=str, default="bench_sprint19_1_results.json",
        help="Arquivo de saída JSON (default: bench_sprint19_1_results.json)"
    )
    parser.add_argument(
        "--skip-directml", action="store_true",
        help="Pula benchmark DirectML (apenas CPU)"
    )
    parser.add_argument(
        "--skip-cpu", action="store_true",
        help="Pula benchmark CPU (apenas DirectML)"
    )
    args = parser.parse_args()

    print("=" * 70)
    print("Sprint 19.1 — Benchmark CPU × GPU (DirectML)")
    print("=" * 70)
    print(f"Model: {args.model}")
    print(f"Language: {args.language}")
    print(f"Iterations: {args.iterations}")

    # Carregar ou gerar áudio.
    if args.audio_path:
        print(f"Audio: {args.audio_path}")
        audio = _load_audio(args.audio_path)
    else:
        print(f"Audio: synthetic ({args.duration}s, 16kHz)")
        audio = _generate_test_audio(args.duration)

    print(f"Audio duration: {len(audio) / 16000:.1f}s")

    results: dict[str, Any] = {
        "model": args.model,
        "language": args.language,
        "iterations": args.iterations,
        "audio_duration_s": len(audio) / 16000,
        "audio_source": args.audio_path or "synthetic",
        "timestamp": time.time(),
    }

    # Benchmark CPU.
    if not args.skip_cpu:
        cpu_result = _benchmark_cpu(
            args.model, audio, args.language, args.iterations
        )
        results["cpu"] = cpu_result

    # Benchmark DirectML.
    if not args.skip_directml:
        dml_result = _benchmark_directml(
            args.model, audio, args.language, args.iterations
        )
        results["directml"] = dml_result

    # Comparação.
    if "cpu" in results and "directml" in results:
        cpu = results["cpu"]
        dml = results["directml"]
        if "error" not in cpu and "error" not in dml:
            cpu_mean = cpu["latency_ms"]["mean"]
            dml_mean = dml["latency_ms"]["mean"]
            speedup = cpu_mean / dml_mean if dml_mean > 0 else 0

            print("\n" + "=" * 70)
            print("COMPARISON")
            print("=" * 70)
            print(f"CPU mean latency:      {cpu_mean:.0f}ms")
            print(f"DirectML mean latency: {dml_mean:.0f}ms")
            print(f"Speedup:               {speedup:.2f}x")
            print(f"CPU RTF:               {cpu['rtf']['mean']:.2f}")
            print(f"DirectML RTF:          {dml['rtf']['mean']:.2f}")
            print(f"CPU RAM max:           {cpu['ram_mb']['max']:.0f}MB")
            print(f"DirectML RAM max:      {dml['ram_mb']['max']:.0f}MB")
            results["comparison"] = {
                "speedup": speedup,
                "cpu_mean_ms": cpu_mean,
                "directml_mean_ms": dml_mean,
            }

    # Salvar resultados.
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
