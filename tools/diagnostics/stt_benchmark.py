"""Sprint 17.3 — Benchmark do STT (threads + modelos + runtime audit).

Ferramenta de diagnóstico que produz evidências concretas sobre o
runtime do STT. NÃO modifica código de produção.

Partes implementadas:
  1. Auditoria de runtime (config solicitada vs efetivamente carregada).
  2. Benchmark de threads (2, 4, 6, 8, 10, 12, 16).
  3. Benchmark de modelos (Tiny, Base, Small, Medium, Large-v3-turbo).
  4. Recomendação automática de threads para o hardware atual.

Uso:
    python tools/diagnostics/stt_benchmark.py --audit
    python tools/diagnostics/stt_benchmark.py --audit --threads 2,4,6,8,12
    python tools/diagnostics/stt_benchmark.py --audit --models tiny,base,small
    python tools/diagnostics/stt_benchmark.py --audit --threads 2,4,8 --models base,small

Requer:
    - faster-whisper instalado.
    - Áudio de teste em data/stt_benchmark_sample.wav (gerado se ausente).
    - Modelos Whisper baixados (cache HuggingFace local).

Saída:
    - Bloco STT RUNTIME no log.
    - Tabela de benchmark de threads.
    - Tabela de benchmark de modelos.
    - Recomendação automática.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
import time
import wave
from pathlib import Path
from typing import Any

# Forçar UTF-8 no Windows.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("stt_benchmark")

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

SAMPLE_PATH = _PROJECT_ROOT / "data" / "stt_benchmark_sample.wav"


def _try_import_psutil() -> Any:
    """Tenta importar psutil. Retorna None se não estiver instalado."""
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def _cpu_percent(psutil_mod: Any) -> float:
    """Lê CPU percent de forma segura. Retorna 0.0 se psutil indisponível."""
    if psutil_mod is None:
        return 0.0
    try:
        return float(psutil_mod.cpu_percent(interval=None))
    except Exception:
        return 0.0

MODEL_ALIASES = {
    "tiny": "tiny",
    "base": "base",
    "small": "small",
    "medium": "medium",
    "large-v3-turbo": "large-v3-turbo",
    "large": "large-v3",
    "turbo": "large-v3-turbo",
}

DEFAULT_THREADS = [2, 4, 6, 8, 10, 12, 16]
DEFAULT_MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo"]


# ---------------------------------------------------------------------------
# Áudio de teste
# ---------------------------------------------------------------------------


def ensure_test_audio(duration_s: float = 3.0) -> Path:
    """Garante que existe um áudio de teste. Gera um tom senoidal se ausente.

    Para benchmark real de RTF, usamos um áudio de 3 segundos.
    Idealmente o usuário deve substituir por um áudio real do pregador.
    """
    if SAMPLE_PATH.exists():
        logger.info("Test audio found: %s", SAMPLE_PATH)
        return SAMPLE_PATH

    SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        import numpy as np
    except ImportError:
        logger.error("numpy not installed — cannot generate test audio")
        raise

    sample_rate = 16000
    n_samples = int(duration_s * sample_rate)
    # Tom senoidal 440Hz + ruído leve (simula áudio com conteúdo).
    t = np.linspace(0, duration_s, n_samples, endpoint=False, dtype=np.float32)
    audio = 0.3 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    # Adicionar amplitude variável para simular fala.
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 2 * t).astype(np.float32)
    audio = audio * envelope

    # Converter para PCM 16-bit.
    pcm = (audio * 32767).astype(np.int16).tobytes()

    with wave.open(str(SAMPLE_PATH), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)

    logger.info("Test audio generated: %s (%.1fs)", SAMPLE_PATH, duration_s)
    return SAMPLE_PATH


def load_audio_pcm(path: Path) -> tuple[bytes, int, int]:
    """Carrega áudio WAV e retorna (pcm_bytes, sample_rate, duration_ms)."""
    with wave.open(str(path), "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())

    if channels != 1 or sampwidth != 2:
        logger.error(
            "Test audio must be mono 16-bit (got channels=%d, sampwidth=%d)",
            channels, sampwidth,
        )
        raise ValueError("invalid test audio format")

    duration_ms = int(len(frames) / (2 * sample_rate) * 1000)
    return frames, sample_rate, duration_ms


# ---------------------------------------------------------------------------
# Auditoria de runtime
# ---------------------------------------------------------------------------


def audit_runtime(config: Any, stt: Any) -> None:
    """Imprime bloco STT RUNTIME com configuração solicitada vs usada."""
    from transcricao.stt import FasterWhisperBackend

    backend = stt.backend
    actual_device = getattr(config, "device", "?")
    actual_compute = getattr(config, "compute_type", "?")
    actual_threads = getattr(config, "cpu_threads", 0)
    fallback_reason = ""

    if isinstance(backend, FasterWhisperBackend):
        actual_device = backend.actual_device
        actual_compute = backend.actual_compute_type
        actual_threads = backend.actual_cpu_threads
        fallback_reason = backend.fallback_reason

    threads_display = (
        str(actual_threads) if actual_threads and actual_threads > 0
        else "default (os.cpu_count)"
    )

    divergences: list[str] = []
    if str(actual_device) != str(getattr(config, "device", "")):
        divergences.append(
            f"device: solicitado={config.device} usado={actual_device}"
        )
    if str(actual_compute) != str(getattr(config, "compute_type", "")):
        divergences.append(
            f"compute_type: solicitado={config.compute_type} usado={actual_compute}"
        )

    print()
    print("========== STT RUNTIME ==========")
    print(f"Backend............. faster-whisper")
    print(f"Modelo solicitado... {getattr(config, 'model', '?')}")
    print(f"Modelo carregado.... {getattr(config, 'model', '?')}")
    print(f"Device solicitado... {getattr(config, 'device', '?')}")
    print(f"Device usado........ {actual_device}")
    print(f"Compute solicitado.. {getattr(config, 'compute_type', '?')}")
    print(f"Compute usado....... {actual_compute}")
    print(f"Threads solicitadas. {getattr(config, 'cpu_threads', 0) or 'default'}")
    print(f"Threads usadas...... {threads_display}")
    print(f"Sample rate......... 16000")
    print(f"Beam size........... {getattr(config, 'beam_size', '?')}")
    print(f"VAD filter.......... {getattr(config, 'vad_filter', '?')}")
    print(f"Language............ {getattr(config, 'language', '?')}")
    print(f"Model load ms....... {stt.metrics.model_load_ms}")
    if fallback_reason:
        print(f"Fallback reason..... {fallback_reason}")
    if divergences:
        print("DIVERGÊNCIAS detectadas:")
        for d in divergences:
            print(f"  - {d}")
    else:
        print("Divergências........ nenhuma")
    print("=================================")


# ---------------------------------------------------------------------------
# Benchmark de threads
# ---------------------------------------------------------------------------


def benchmark_threads(
    model: str,
    device: str,
    compute_type: str,
    threads_list: list[int],
    pcm: bytes,
    sample_rate: int,
    audio_duration_ms: int,
    language: str = "pt",
) -> list[dict[str, Any]]:
    """Executa benchmark variando o número de threads.

    Para cada valor de threads, carrega o modelo, transcreve o mesmo
    áudio N vezes e registra tempo, RTF e CPU.

    Returns:
        Lista de dicts com: threads, load_ms, processing_ms, rtf, cpu_percent.
    """
    from config.models import STTConfig, VadConfig
    from transcricao.stt import STT
    from microfone.capture import SpeechSegment

    psutil_mod = _try_import_psutil()
    results: list[dict[str, Any]] = []
    vad = VadConfig(mode="silero", min_speech_ms=250, pause_threshold_ms=600)

    print()
    print(f"--- Benchmark de Threads (model={model}, device={device}) ---")
    cpu_header = " | {'CPU %':>6}" if psutil_mod else ""
    print(f"{'Threads':>8} | {'Load ms':>8} | {'Proc ms':>8} | {'RTF':>6}{cpu_header}")
    print("-" * (55 if psutil_mod else 45))

    for threads in threads_list:
        config = STTConfig(
            model=model,
            device=device,
            compute_type=compute_type,
            language=language,
            chunk_length_s=30,
            vad=vad,
            backend="faster-whisper",
            beam_size=1,
            vad_filter=False,
            cpu_threads=threads,
        )

        try:
            load_start = time.monotonic()
            stt = STT(config=config)
            load_ms = int((time.monotonic() - load_start) * 1000)
        except Exception as e:
            print(f"{threads:>8} | ERROR: {e}")
            results.append({
                "threads": threads, "load_ms": 0, "processing_ms": 0,
                "rtf": 0, "cpu_percent": 0, "error": str(e),
            })
            continue

        # Aquecimento (1 transcrição descartada).
        seg = SpeechSegment(
            audio=pcm, start_time=time.time(), end_time=time.time(),
            duration_ms=audio_duration_ms, chunk_count=0,
        )
        try:
            stt.transcribe(seg)
        except Exception:
            pass

        # Medir 3 transcrições e tirar média.
        proc_times: list[int] = []
        cpu_percents: list[float] = []

        for _ in range(3):
            seg = SpeechSegment(
                audio=pcm, start_time=time.time(), end_time=time.time(),
                duration_ms=audio_duration_ms, chunk_count=0,
            )
            _cpu_percent(psutil_mod)  # inicializa medição
            t0 = time.monotonic()
            try:
                result = stt.transcribe(seg)
                proc_ms = int((time.monotonic() - t0) * 1000)
                cpu_after = _cpu_percent(psutil_mod)
                proc_times.append(proc_ms)
                cpu_percents.append(cpu_after)
            except Exception as e:
                print(f"{threads:>8} | transcribe error: {e}")
                proc_times.append(0)
                cpu_percents.append(0)

        avg_proc = sum(proc_times) / len(proc_times) if proc_times else 0
        avg_cpu = sum(cpu_percents) / len(cpu_percents) if cpu_percents else 0
        rtf = avg_proc / audio_duration_ms if audio_duration_ms > 0 else 0

        if psutil_mod:
            print(f"{threads:>8} | {load_ms:>8} | {avg_proc:>8.0f} | {rtf:>6.2f} | {avg_cpu:>6.1f}")
        else:
            print(f"{threads:>8} | {load_ms:>8} | {avg_proc:>8.0f} | {rtf:>6.2f}")

        results.append({
            "threads": threads,
            "load_ms": load_ms,
            "processing_ms": avg_proc,
            "rtf": rtf,
            "cpu_percent": avg_cpu,
            "error": None,
        })

        # Descarregar modelo antes de carregar o próximo.
        try:
            stt.close()
        except Exception:
            pass

        # Pequeno intervalo para estabilizar.
        time.sleep(1.0)

    return results


def recommend_threads(results: list[dict[str, Any]]) -> int | None:
    """Recomenda o melhor número de threads baseado no menor RTF."""
    valid = [r for r in results if r.get("error") is None and r["rtf"] > 0]
    if not valid:
        return None
    best = min(valid, key=lambda r: r["rtf"])
    return best["threads"]


# ---------------------------------------------------------------------------
# Benchmark de modelos
# ---------------------------------------------------------------------------


def benchmark_models(
    models: list[str],
    device: str,
    compute_type: str,
    cpu_threads: int,
    pcm: bytes,
    sample_rate: int,
    audio_duration_ms: int,
    language: str = "pt",
) -> list[dict[str, Any]]:
    """Executa benchmark comparando diferentes modelos.

    Returns:
        Lista de dicts com: model, load_ms, processing_ms, rtf, confidence.
    """
    from config.models import STTConfig, VadConfig
    from transcricao.stt import STT
    from microfone.capture import SpeechSegment

    results: list[dict[str, Any]] = []
    vad = VadConfig(mode="silero", min_speech_ms=250, pause_threshold_ms=600)

    print()
    print(f"--- Benchmark de Modelos (device={device}, threads={cpu_threads}) ---")
    print(f"{'Model':>18} | {'Load ms':>8} | {'Proc ms':>8} | {'RTF':>6} | {'Conf':>6}")
    print("-" * 65)

    for model_alias in models:
        model = MODEL_ALIASES.get(model_alias, model_alias)
        config = STTConfig(
            model=model,
            device=device,
            compute_type=compute_type,
            language=language,
            chunk_length_s=30,
            vad=vad,
            backend="faster-whisper",
            beam_size=1,
            vad_filter=False,
            cpu_threads=cpu_threads,
        )

        try:
            load_start = time.monotonic()
            stt = STT(config=config)
            load_ms = int((time.monotonic() - load_start) * 1000)
        except Exception as e:
            print(f"{model_alias:>18} | ERROR: {e}")
            results.append({
                "model": model_alias, "load_ms": 0, "processing_ms": 0,
                "rtf": 0, "confidence": 0, "error": str(e),
            })
            continue

        # Medir 3 transcrições.
        proc_times: list[int] = []
        confidences: list[float] = []

        for _ in range(3):
            seg = SpeechSegment(
                audio=pcm, start_time=time.time(), end_time=time.time(),
                duration_ms=audio_duration_ms, chunk_count=0,
            )
            try:
                result = stt.transcribe(seg)
                proc_times.append(result.processing_ms)
                confidences.append(result.confidence)
            except Exception as e:
                print(f"{model_alias:>18} | transcribe error: {e}")
                proc_times.append(0)
                confidences.append(0)

        avg_proc = sum(proc_times) / len(proc_times) if proc_times else 0
        avg_conf = sum(confidences) / len(confidences) if confidences else 0
        rtf = avg_proc / audio_duration_ms if audio_duration_ms > 0 else 0

        print(f"{model_alias:>18} | {load_ms:>8} | {avg_proc:>8.0f} | {rtf:>6.2f} | {avg_conf:>6.2f}")

        results.append({
            "model": model_alias,
            "load_ms": load_ms,
            "processing_ms": avg_proc,
            "rtf": rtf,
            "confidence": avg_conf,
            "error": None,
        })

        try:
            stt.close()
        except Exception:
            pass

        time.sleep(1.0)

    return results


# ---------------------------------------------------------------------------
# CPU info
# ---------------------------------------------------------------------------


def print_cpu_info() -> None:
    """Imprime informações da CPU para contexto do benchmark."""
    psutil_mod = _try_import_psutil()
    name = _detect_cpu_name()
    print()
    print(f"CPU: {name}")
    if psutil_mod is not None:
        physical = psutil_mod.cpu_count(logical=False) or 0
        logical = psutil_mod.cpu_count(logical=True) or 0
        print(f"  Cores físicos: {physical}")
        print(f"  Threads lógicos: {logical}")
    else:
        import os as _os
        logical = _os.cpu_count() or 0
        print(f"  Threads lógicos: {logical} (psutil não instalado)")
        print(f"  Cores físicos: indisponível (instale psutil)")


def _detect_cpu_name() -> str:
    try:
        import psutil
        # psutil não expõe nome da CPU diretamente em todas as plataformas.
        import platform
        return platform.processor() or "unknown"
    except Exception:
        import platform
        return platform.processor() or "unknown"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sprint 17.3 — STT Benchmark & Runtime Audit"
    )
    parser.add_argument(
        "--audit", action="store_true",
        help="Executa auditoria de runtime (config vs efetivo)",
    )
    parser.add_argument(
        "--threads", type=str, default="",
        help="Lista de threads para testar (ex: 2,4,6,8,12,16)",
    )
    parser.add_argument(
        "--models", type=str, default="",
        help="Lista de modelos para testar (ex: tiny,base,small)",
    )
    parser.add_argument(
        "--model", type=str, default="base",
        help="Modelo para benchmark de threads (default: base)",
    )
    parser.add_argument(
        "--device", type=str, default="cpu",
        help="Device (cpu ou cuda)",
    )
    parser.add_argument(
        "--compute-type", type=str, default="int8",
        help="Compute type (int8, int8_float16, float16)",
    )
    parser.add_argument(
        "--language", type=str, default="pt",
        help="Idioma do áudio",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Log detalhado",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print_cpu_info()

    # Garantir áudio de teste.
    audio_path = ensure_test_audio(duration_s=3.0)
    pcm, sample_rate, audio_duration_ms = load_audio_pcm(audio_path)
    print(f"Áudio de teste: {audio_path} ({audio_duration_ms} ms)")

    # Auditoria de runtime.
    if args.audit:
        from config.models import STTConfig, VadConfig
        from transcricao.stt import STT

        vad = VadConfig(mode="silero", min_speech_ms=250, pause_threshold_ms=600)
        config = STTConfig(
            model=args.model,
            device=args.device,
            compute_type=args.compute_type,
            language=args.language,
            chunk_length_s=30,
            vad=vad,
            backend="faster-whisper",
            beam_size=1,
            vad_filter=False,
            cpu_threads=0,
        )

        print()
        print("Carregando STT para auditoria...")
        stt = STT(config=config)
        audit_runtime(config, stt)
        stt.close()

    # Benchmark de threads.
    if args.threads:
        threads_list = [int(t.strip()) for t in args.threads.split(",") if t.strip()]
        results = benchmark_threads(
            model=args.model,
            device=args.device,
            compute_type=args.compute_type,
            threads_list=threads_list,
            pcm=pcm,
            sample_rate=sample_rate,
            audio_duration_ms=audio_duration_ms,
            language=args.language,
        )
        best = recommend_threads(results)
        if best is not None:
            print()
            print(f">>> Recomendação: threads={best} (menor RTF)")
        else:
            print()
            print(">>> Não foi possível recomendar threads (todos falharam)")

    # Benchmark de modelos.
    if args.models:
        models_list = [m.strip() for m in args.models.split(",") if m.strip()]
        # Usar o melhor threads se disponível, senão default.
        cpu_threads = 0
        if args.threads:
            threads_list = [int(t.strip()) for t in args.threads.split(",") if t.strip()]
            results_t = benchmark_threads(
                model=args.model,
                device=args.device,
                compute_type=args.compute_type,
                threads_list=threads_list,
                pcm=pcm,
                sample_rate=sample_rate,
                audio_duration_ms=audio_duration_ms,
                language=args.language,
            )
            best = recommend_threads(results_t)
            cpu_threads = best if best else 0

        benchmark_models(
            models=models_list,
            device=args.device,
            compute_type=args.compute_type,
            cpu_threads=cpu_threads,
            pcm=pcm,
            sample_rate=sample_rate,
            audio_duration_ms=audio_duration_ms,
            language=args.language,
        )

    if not args.audit and not args.threads and not args.models:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
