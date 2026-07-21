"""Estabilidade — inferência contínua por 1 hora (Sprint 19.1).

Responsabilidade:
  - Executar inferência contínua por 1 hora (ou tempo configurável).
  - Monitorar vazamento de VRAM/RAM.
  - Detectar falhas de inferência.
  - Detectar travamentos.
  - Detectar queda de desempenamento (latência crescente).
  - Salvar relatório em JSON.

Uso:
    python _stability_sprint19_1.py [--duration-minutes N] [--model MODEL]

Sprint 19.1 — GPU Runtime & Hardware Acceleration.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _get_ram_mb() -> float:
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        return proc.memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0.0


def _generate_audio(duration_s: float = 6.0, sr: int = 16000) -> Any:
    import numpy as np
    n = int(duration_s * sr)
    t = np.linspace(0, duration_s, n, endpoint=False)
    audio = 0.3 * np.sin(2 * np.pi * 440 * t) + 0.1 * np.random.randn(n)
    return (audio / max(abs(audio).max(), 1.0)).astype(np.float32)


def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    if f == c:
        return sorted_data[f]
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stability test — Sprint 19.1"
    )
    parser.add_argument(
        "--duration-minutes", type=int, default=60,
        help="Duração em minutos (default: 60 = 1 hora)"
    )
    parser.add_argument(
        "--model", type=str, default="small",
        help="Modelo Whisper (default: small)"
    )
    parser.add_argument(
        "--language", type=str, default="pt",
    )
    parser.add_argument(
        "--backend", type=str, default="auto",
        choices=["auto", "cpu", "directml", "cuda"],
    )
    parser.add_argument(
        "--audio-duration", type=float, default=6.0,
        help="Duração do áudio sintético (default: 6s)"
    )
    parser.add_argument(
        "--output", type=str, default="stability_sprint19_1_results.json",
    )
    parser.add_argument(
        "--sample-interval", type=int, default=30,
        help="Intervalo entre amostras de RAM (segundos, default: 30)"
    )
    args = parser.parse_args()

    duration_s = args.duration_minutes * 60
    print("=" * 70)
    print(f"Sprint 19.1 — Stability Test ({args.duration_minutes} min)")
    print("=" * 70)
    print(f"Backend: {args.backend}")
    print(f"Model: {args.model}")
    print(f"Audio: synthetic {args.audio_duration}s")

    # Carregar backend.
    from config.models import STTConfig, VadConfig
    from transcricao.stt import STT

    cfg = STTConfig(
        model=args.model,
        device=args.backend,
        compute_type="auto",
        language=args.language,
        chunk_length_s=30,
        vad=VadConfig(mode="silero", min_speech_ms=250, pause_threshold_ms=600),
        backend=args.backend,
    )

    print("\nLoading backend...")
    t0 = time.monotonic()
    try:
        stt = STT(cfg)
    except Exception as e:
        print(f"Failed to load STT: {e}")
        return 1
    load_ms = (time.monotonic() - t0) * 1000
    print(f"Backend loaded in {load_ms:.0f}ms")

    # Gerar áudio de teste.
    audio = _generate_audio(args.audio_duration)

    # Estado do teste.
    latencies: list[float] = []
    ram_samples: list[float] = []
    ram_timestamps: list[float] = []
    failure_count = 0
    stall_count = 0  # transcrições que demoraram > 30s (travamento).
    start_time = time.monotonic()
    last_sample_time = start_time

    # Flag para parar.
    stop_flag = threading.Event()

    def monitor_thread() -> None:
        """Thread que coleta RAM periodicamente."""
        nonlocal last_sample_time
        while not stop_flag.is_set():
            current_time = time.monotonic()
            if current_time - last_sample_time >= args.sample_interval:
                ram_samples.append(_get_ram_mb())
                ram_timestamps.append(current_time - start_time)
                last_sample_time = current_time
            time.sleep(1)

    monitor = threading.Thread(target=monitor_thread, daemon=True)
    monitor.start()

    # Loop principal.
    iteration = 0
    print(f"\nStarting stability run ({args.duration_minutes} min)...\n")

    try:
        while time.monotonic() - start_time < duration_s:
            iteration += 1
            elapsed_total = time.monotonic() - start_time
            remaining = duration_s - elapsed_total

            t0 = time.monotonic()
            try:
                # Usar _backend.transcribe diretamente para evitar
                # a conversão SpeechSegment do STT.transcribe.
                if hasattr(stt._backend, "transcribe"):
                    stt._backend.transcribe(
                        audio, args.language, 1, False, 30
                    )
                else:
                    # Fallback: usar STT.transcribe com SpeechSegment.
                    from transcricao.types import SpeechSegment
                    seg = SpeechSegment(
                        pcm_bytes=(audio * 32767).astype("<i2").tobytes(),
                        sample_rate=16000,
                        duration_ms=int(args.audio_duration * 1000),
                        timestamp=time.time(),
                    )
                    stt.transcribe(seg)
            except Exception as e:
                failure_count += 1
                print(
                    f"[{elapsed_total/60:.1f}min] iter {iteration}: "
                    f"FAILED: {e}"
                )
                # Forçar GC após falha.
                gc.collect()
                continue

            latency_ms = (time.monotonic() - t0) * 1000
            latencies.append(latency_ms)

            # Detectar travamento.
            if latency_ms > 30000:
                stall_count += 1
                print(
                    f"[{elapsed_total/60:.1f}min] iter {iteration}: "
                    f"STALL ({latency_ms:.0f}ms)"
                )

            # Log periódico.
            if iteration % 10 == 0:
                ram = _get_ram_mb()
                recent = latencies[-10:]
                recent_mean = statistics.mean(recent)
                print(
                    f"[{elapsed_total/60:.1f}min] iter {iteration}: "
                    f"latency={latency_ms:.0f}ms "
                    f"recent_mean={recent_mean:.0f}ms "
                    f"RAM={ram:.0f}MB "
                    f"failures={failure_count} "
                    f"remaining={remaining/60:.1f}min"
                )

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        stop_flag.set()
        monitor.join(timeout=5)

    # Relatório.
    total_time = time.monotonic() - start_time
    print("\n" + "=" * 70)
    print("STABILITY TEST RESULTS")
    print("=" * 70)
    print(f"Duration:        {total_time/60:.1f} min ({total_time:.0f}s)")
    print(f"Iterations:      {iteration}")
    print(f"Failures:        {failure_count}")
    print(f"Stalls (>30s):   {stall_count}")
    print(f"Success rate:    {(iteration - failure_count) / max(iteration, 1) * 100:.1f}%")

    if latencies:
        print(f"\nLatency (ms):")
        print(f"  Mean:   {statistics.mean(latencies):.0f}")
        print(f"  Median: {statistics.median(latencies):.0f}")
        print(f"  p50:    {_percentile(latencies, 50):.0f}")
        print(f"  p95:    {_percentile(latencies, 95):.0f}")
        print(f"  p99:    {_percentile(latencies, 99):.0f}")
        print(f"  Min:    {min(latencies):.0f}")
        print(f"  Max:    {max(latencies):.0f}")

        # Detectar degradação: comparar primeiros 20% vs últimos 20%.
        n = len(latencies)
        if n >= 10:
            first_quartile = latencies[: max(n // 5, 1)]
            last_quartile = latencies[-max(n // 5, 1):]
            first_mean = statistics.mean(first_quartile)
            last_mean = statistics.mean(last_quartile)
            degradation_pct = (
                (last_mean - first_mean) / first_mean * 100
                if first_mean > 0 else 0
            )
            print(f"\nDegradation analysis:")
            print(f"  First 20% mean:  {first_mean:.0f}ms")
            print(f"  Last 20% mean:   {last_mean:.0f}ms")
            print(f"  Degradation:     {degradation_pct:+.1f}%")

    if ram_samples:
        print(f"\nRAM (MB):")
        print(f"  Initial:  {ram_samples[0]:.0f}")
        print(f"  Final:    {ram_samples[-1]:.0f}")
        print(f"  Delta:    {ram_samples[-1] - ram_samples[0]:+.0f}")
        print(f"  Max:      {max(ram_samples):.0f}")
        print(f"  Min:      {min(ram_samples):.0f}")
        # Vazamento: se delta > 100MB, suspeito.
        ram_delta = ram_samples[-1] - ram_samples[0]
        if ram_delta > 100:
            print(f"  ⚠️  POSSIBLE LEAK: {ram_delta:+.0f}MB growth")
        else:
            print(f"  ✓ No significant leak")

    # Salvar resultados.
    results = {
        "duration_minutes": total_time / 60,
        "iterations": iteration,
        "failures": failure_count,
        "stalls": stall_count,
        "success_rate": (iteration - failure_count) / max(iteration, 1),
        "latencies_ms": latencies,
        "ram_samples_mb": ram_samples,
        "ram_timestamps_s": ram_timestamps,
        "model": args.model,
        "backend": args.backend,
    }
    if latencies:
        results["latency_stats"] = {
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "p99": _percentile(latencies, 99),
            "min": min(latencies),
            "max": max(latencies),
        }
    if ram_samples:
        results["ram_stats"] = {
            "initial": ram_samples[0],
            "final": ram_samples[-1],
            "delta": ram_samples[-1] - ram_samples[0],
            "max": max(ram_samples),
        }

    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")

    # Cleanup.
    try:
        stt.close()
    except Exception:
        pass

    return 0 if failure_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
