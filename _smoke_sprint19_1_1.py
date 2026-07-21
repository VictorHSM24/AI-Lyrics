"""Sprint 19.1.1 — Smoke Test GPU AMD (RX 7600).

Validação rápida (sem testes prolongados):
  Etapa 1: Confirmar backend/provider/device via log.
  Etapa 2: Uma transcrição de ~30s (load time, inferência, RTF, RAM, VRAM).
  Etapa 3: Confirmar GPU Compute + VRAM aumentam (via log, sem screenshot).
  Etapa 4: Mesmo áudio em CPU vs DirectML — comparar.
  Etapa 5: StreamingSTT com 1 min de fala (simulado).
  Etapa 6: Forçar fallback GPU→CPU e confirmar continuidade.

Para minimizar consumo de RAM, usa modelo "tiny" (39MB) em vez de
large-v3-turbo (1.5GB). O objetivo é validar o fluxo, não a precisão.

Uso:
    python _smoke_sprint19_1_1.py
"""

from __future__ import annotations

import gc
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ram_mb() -> float:
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0.0


def _generate_audio(duration_s: float = 30.0, sr: int = 16000) -> Any:
    """Gera áudio sintético de ~30s (senoide modulada + ruído)."""
    import numpy as np
    n = int(duration_s * sr)
    t = np.linspace(0, duration_s, n, endpoint=False)
    # Senoide modulada em frequência (simula fala com variação).
    freq = 200 + 100 * np.sin(2 * np.pi * 2 * t)
    audio = 0.3 * np.sin(2 * np.pi * freq * t) + 0.05 * np.random.randn(n)
    # Envelope (simula pausas).
    envelope = np.where(
        (t * 4) % 1.0 < 0.7,  # 70% on, 30% off
        1.0, 0.1
    )
    audio = audio * envelope
    return (audio / max(abs(audio).max(), 1.0)).astype(np.float32)


def _section(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _info(msg: str) -> None:
    print(f"  [INFO] {msg}")


# ---------------------------------------------------------------------------
# Etapa 1 — Confirmar backend/provider/device
# ---------------------------------------------------------------------------


def etapa1_hardware_check() -> dict:
    _section("Etapa 1 — Hardware & Backend Check")
    from core.hardware import HardwareDetector
    from transcricao.backend_selector import BackendSelector

    profile = HardwareDetector.detect()
    _info(f"CPU: {profile.cpu.name}")
    _info(f"RAM: {profile.ram_mb} MB")
    _info(f"OS:  {profile.os_name} {profile.os_version}")

    print()
    _info("GPUs detectadas:")
    for g in profile.gpus:
        _info(
            f"  {g.name} | vendor={g.vendor} | vram={g.vram_mb}MB | "
            f"directml={g.directml_support} | cuda={g.cuda_support}"
        )

    # Validar.
    has_amd = profile.has_amd_gpu
    has_dml = profile.has_directml
    rx7600 = any("RX 7600" in g.name for g in profile.gpus)

    if has_amd:
        _ok("GPU AMD detectada")
    else:
        _fail("GPU AMD não detectada")

    if rx7600:
        _ok("RX 7600 detectada")
    else:
        _fail("RX 7600 não detectada")

    if has_dml:
        _ok("DirectML disponível (DmlExecutionProvider)")
    else:
        _fail("DirectML não disponível")

    # Seleção automática.
    info = BackendSelector.select("auto", "auto", profile)
    _info(f"BackendSelector auto → {info.backend_type} (compute={info.compute_type})")
    _info(f"Reason: {info.reason}")

    if info.backend_type == "directml":
        _ok("Seleção automática escolheu DirectML")
    else:
        _fail(f"Seleção automática escolheu {info.backend_type} (esperado: directml)")

    # Confirmar provider via onnxruntime.
    import onnxruntime as ort
    providers = ort.get_available_providers()
    _info(f"onnxruntime providers: {providers}")
    if "DmlExecutionProvider" in providers:
        _ok("DmlExecutionProvider confirmado no onnxruntime")
    else:
        _fail("DmlExecutionProvider não encontrado no onnxruntime")

    return {
        "profile": profile,
        "backend_info": info,
        "providers": providers,
        "rx7600": rx7600,
        "directml": has_dml,
    }


# ---------------------------------------------------------------------------
# Etapa 2 — Transcrição única de ~30s
# ---------------------------------------------------------------------------


def etapa2_single_transcription(audio: Any, model: str = "tiny") -> dict:
    _section(f"Etapa 2 — Transcrição única (~30s, model={model})")
    from transcricao.directml_backend import DirectMLBackend

    ram_before = _ram_mb()
    _info(f"RAM antes do load: {ram_before:.0f} MB")

    backend = DirectMLBackend(
        model_name=model,
        compute_type="float32",
        device_id=0,
    )

    # Carregar.
    _info("Carregando DirectMLBackend...")
    t0 = time.monotonic()
    try:
        backend.load()
    except Exception as e:
        _fail(f"Falha ao carregar DirectMLBackend: {e}")
        _info("Isso pode acontecer se o modelo ONNX não estiver baixado.")
        _info(f"Tente baixar manualmente de https://huggingface.co/onnx-community/whisper-{model}")
        return {"error": str(e), "loaded": False}
    load_ms = (time.monotonic() - t0) * 1000
    ram_after_load = _ram_mb()

    _ok(f"Backend carregado em {load_ms:.0f} ms")
    _info(f"RAM após load: {ram_after_load:.0f} MB (delta: {ram_after_load - ram_before:+.0f} MB)")
    _info(f"backend_name: {backend.backend_name}")
    _info(f"actual_device: {backend.actual_device}")
    _info(f"actual_compute_type: {backend.actual_compute_type}")

    # Inferência.
    audio_duration = len(audio) / 16000
    _info(f"Inferindo áudio de {audio_duration:.1f}s...")
    t0 = time.monotonic()
    try:
        text, lang, logprob, segs = backend.transcribe(
            audio, "pt", 1, False, 30
        )
    except Exception as e:
        _fail(f"Falha na inferência: {e}")
        backend.unload()
        return {"error": str(e), "loaded": True, "load_ms": load_ms}
    infer_ms = (time.monotonic() - t0) * 1000
    rtf = infer_ms / 1000 / audio_duration
    ram_after_infer = _ram_mb()

    _ok(f"Inferência concluída em {infer_ms:.0f} ms")
    _info(f"RTF: {rtf:.3f}")
    _info(f"Texto: '{text[:80]}...' (len={len(text)})")
    _info(f"Idioma: {lang}")
    _info(f"RAM após inferência: {ram_after_infer:.0f} MB")

    # Cleanup.
    backend.unload()
    gc.collect()
    ram_after_unload = _ram_mb()
    _info(f"RAM após unload: {ram_after_unload:.0f} MB")

    return {
        "loaded": True,
        "load_ms": load_ms,
        "infer_ms": infer_ms,
        "rtf": rtf,
        "text": text,
        "language": lang,
        "ram_before_mb": ram_before,
        "ram_after_load_mb": ram_after_load,
        "ram_after_infer_mb": ram_after_infer,
        "ram_after_unload_mb": ram_after_unload,
        "backend_name": backend.backend_name,
        "actual_device": backend.actual_device,
    }


# ---------------------------------------------------------------------------
# Etapa 3 — Confirmar GPU Compute + VRAM (via log)
# ---------------------------------------------------------------------------


def etapa3_gpu_utilization(audio: Any, model: str = "tiny") -> dict:
    _section("Etapa 3 — GPU Compute & VRAM (via log)")
    _info("NOTA: Para confirmar visualmente, abra o Gerenciador de Tarefas")
    _info("ou AMD Adrenalin → Performance → GPU durante a inferência.")
    _info("Executando 3 inferências rápidas para medir RAM/VRAM...")

    from transcricao.directml_backend import DirectMLBackend
    backend = DirectMLBackend(model_name=model, compute_type="float32")
    try:
        backend.load()
    except Exception as e:
        _fail(f"Falha ao carregar: {e}")
        return {"error": str(e)}

    ram_samples = []
    times = []
    for i in range(3):
        ram = _ram_mb()
        ram_samples.append(ram)
        t0 = time.monotonic()
        backend.transcribe(audio, "pt", 1, False, 30)
        elapsed = (time.monotonic() - t0) * 1000
        times.append(elapsed)
        _info(f"  iter {i+1}: {elapsed:.0f}ms, RAM={ram:.0f}MB")

    _ok(f"3 inferências executadas (média: {statistics.mean(times):.0f}ms)")
    _info(f"RAM estável: min={min(ram_samples):.0f} max={max(ram_samples):.0f} delta={max(ram_samples)-min(ram_samples):+.0f}MB")

    # Para VRAM, onnxruntime-directml não expõe API direta.
    _info("VRAM: onnxruntime-directml não expõe API para leitura de VRAM usada.")
    _info("Para confirmar VRAM, verificar Gerenciador de Tarefas → GPU → Memória dedicada.")

    backend.unload()
    gc.collect()

    return {
        "times_ms": times,
        "ram_samples_mb": ram_samples,
        "note": "VRAM requer confirmação visual via Gerenciador de Tarefas",
    }


# ---------------------------------------------------------------------------
# Etapa 4 — CPU vs DirectML (mesmo áudio)
# ---------------------------------------------------------------------------


def etapa4_cpu_vs_gpu(audio: Any, model: str = "tiny") -> dict:
    _section(f"Etapa 4 — CPU vs DirectML (mesmo áudio, model={model})")
    from config.models import STTConfig, VadConfig
    from transcricao.stt import FasterWhisperBackend
    from transcricao.directml_backend import DirectMLBackend

    audio_duration = len(audio) / 16000
    _info(f"Áudio: {audio_duration:.1f}s, modelo: {model}")

    # CPU.
    print()
    _info("--- CPU (FasterWhisperBackend, int8) ---")
    cpu_cfg = STTConfig(
        model=model, device="cpu", compute_type="int8",
        language="pt", chunk_length_s=30,
        vad=VadConfig(mode="silero", min_speech_ms=250, pause_threshold_ms=600),
        backend="faster-whisper",
    )
    cpu = FasterWhisperBackend(cpu_cfg)
    t0 = time.monotonic()
    try:
        cpu.load()
    except Exception as e:
        _fail(f"CPU load falhou: {e}")
        return {"error": f"cpu: {e}"}
    cpu_load_ms = (time.monotonic() - t0) * 1000
    _info(f"CPU load: {cpu_load_ms:.0f}ms")

    # Warmup + 3 iterações.
    cpu.transcribe(audio, "pt", 1, False, 30)
    cpu_times = []
    cpu_text = ""
    for i in range(3):
        t0 = time.monotonic()
        text, lang, _, _ = cpu.transcribe(audio, "pt", 1, False, 30)
        elapsed = (time.monotonic() - t0) * 1000
        cpu_times.append(elapsed)
        cpu_text = text
        _info(f"  CPU iter {i+1}: {elapsed:.0f}ms")
    cpu_mean = statistics.mean(cpu_times)
    cpu_rtf = cpu_mean / 1000 / audio_duration
    cpu_ram = _ram_mb()
    _ok(f"CPU: mean={cpu_mean:.0f}ms RTF={cpu_rtf:.3f} RAM={cpu_ram:.0f}MB")
    cpu.close()
    gc.collect()

    # DirectML.
    print()
    _info("--- DirectML (DirectMLBackend, float32) ---")
    dml = DirectMLBackend(model_name=model, compute_type="float32")
    t0 = time.monotonic()
    try:
        dml.load()
    except Exception as e:
        _fail(f"DirectML load falhou: {e}")
        _info("Etapa 4 parcial: apenas CPU medido.")
        return {
            "cpu_mean_ms": cpu_mean,
            "cpu_rtf": cpu_rtf,
            "cpu_text": cpu_text,
            "cpu_ram_mb": cpu_ram,
            "dml_error": str(e),
        }
    dml_load_ms = (time.monotonic() - t0) * 1000
    _info(f"DirectML load: {dml_load_ms:.0f}ms")

    # Warmup + 3 iterações.
    dml.transcribe(audio, "pt", 1, False, 30)
    dml_times = []
    dml_text = ""
    for i in range(3):
        t0 = time.monotonic()
        text, lang, _, _ = dml.transcribe(audio, "pt", 1, False, 30)
        elapsed = (time.monotonic() - t0) * 1000
        dml_times.append(elapsed)
        dml_text = text
        _info(f"  DirectML iter {i+1}: {elapsed:.0f}ms")
    dml_mean = statistics.mean(dml_times)
    dml_rtf = dml_mean / 1000 / audio_duration
    dml_ram = _ram_mb()
    _ok(f"DirectML: mean={dml_mean:.0f}ms RTF={dml_rtf:.3f} RAM={dml_ram:.0f}MB")
    dml.unload()
    gc.collect()

    # Comparação.
    print()
    _info("COMPARAÇÃO:")
    print(f"  {'Métrica':<20s} {'CPU':>15s} {'DirectML':>15s}")
    print(f"  {'-'*50}")
    print(f"  {'Tempo total (ms)':<20s} {cpu_mean:>15.0f} {dml_mean:>15.0f}")
    print(f"  {'RTF':<20s} {cpu_rtf:>15.3f} {dml_rtf:>15.3f}")
    print(f"  {'RAM (MB)':<20s} {cpu_ram:>15.0f} {dml_ram:>15.0f}")
    print(f"  {'Texto (len)':<20s} {len(cpu_text):>15d} {len(dml_text):>15d}")
    print(f"  {'Texto CPU':<20s} {cpu_text[:40]:>15s}")
    print(f"  {'Texto DML':<20s} {dml_text[:40]:>15s}")

    speedup = cpu_mean / dml_mean if dml_mean > 0 else 0
    if speedup > 1.0:
        _ok(f"DirectML é {speedup:.2f}x mais rápido que CPU")
    else:
        _fail(f"DirectML é {speedup:.2f}x (mais lento que CPU)")
        _info("Isso pode acontecer com modelo tiny (overhead DirectML > ganho).")
        _info("Modelos maiores (medium, large) tendem a mostrar ganho.")

    return {
        "cpu_mean_ms": cpu_mean,
        "cpu_rtf": cpu_rtf,
        "cpu_text": cpu_text,
        "cpu_ram_mb": cpu_ram,
        "cpu_load_ms": cpu_load_ms,
        "dml_mean_ms": dml_mean,
        "dml_rtf": dml_rtf,
        "dml_text": dml_text,
        "dml_ram_mb": dml_ram,
        "dml_load_ms": dml_load_ms,
        "speedup": speedup,
    }


# ---------------------------------------------------------------------------
# Etapa 5 — StreamingSTT (simulado, sem microfone real)
# ---------------------------------------------------------------------------


def etapa5_streaming_simulated(model: str = "tiny") -> dict:
    _section("Etapa 5 — StreamingSTT (simulado)")
    _info("NOTA: Teste real requer microfone + Holyrics conectado.")
    _info("Validando apenas que StreamingSTTService + IncrementalBiblicalParser")
    _info("funcionam com o backend selecionado (sem áudio real).")

    # Verificar imports.
    try:
        from microfone.streaming_stt_service import StreamingSTTService
        from pipeline.incremental_parser import IncrementalBiblicalParser
        from microfone.stt_executor import STTExecutor
        _ok("StreamingSTTService importável")
        _ok("IncrementalBiblicalParser importável")
        _ok("STTExecutor importável")
    except ImportError as e:
        _fail(f"Import falhou: {e}")
        return {"error": str(e)}

    # Verificar eventos Sprint 19.
    from pipeline.events import all_event_types
    names = [t.__name__ for t in all_event_types()]
    required = ["SpeechPartial", "SpeechPartialUpdated", "ReferenceCandidate"]
    for ev in required:
        if ev in names:
            _ok(f"Evento {ev} registrado")
        else:
            _fail(f"Evento {ev} não encontrado")

    _info("Para teste real com microfone:")
    _info("  1. Iniciar backend (python main.py)")
    _info("  2. Falar continuamente por 1 minuto")
    _info("  3. Confirmar SpeechPartial chega no frontend (área Parcial)")
    _info("  4. Confirmar ReferenceCandidate aparece")
    _info("  5. Confirmar ReferenceDetected antes do fim da frase")
    _info("  6. Confirmar Holyrics apresenta o versículo")

    return {
        "imports_ok": True,
        "events_registered": all(ev in names for ev in required),
        "note": "Teste real requer microfone + Holyrics",
    }


# ---------------------------------------------------------------------------
# Etapa 6 — Fallback GPU→CPU
# ---------------------------------------------------------------------------


def etapa6_fallback() -> dict:
    _section("Etapa 6 — Fallback GPU→CPU (forçado)")
    from transcricao.backend_fallback import BackendFallbackManager

    # Mock backend GPU que sempre falha.
    gpu = type("MockGPU", (), {})()
    gpu.backend_name = "directml-mock"
    gpu.actual_device = "directml"
    gpu.actual_compute_type = "float32"
    gpu.is_loaded = True
    gpu.fallback_reason = ""
    gpu.load = lambda: None
    gpu.unload = lambda: None
    gpu.transcribe = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("GPU OOM (simulado)")
    )
    gpu.close = lambda: None

    # Mock backend CPU que funciona.
    cpu = type("MockCPU", (), {})()
    cpu.backend_name = "cpu-mock"
    cpu.actual_device = "cpu"
    cpu.actual_compute_type = "int8"
    cpu.is_loaded = True
    cpu.fallback_reason = ""
    cpu.load = lambda: None
    cpu.unload = lambda: None
    cpu.transcribe = lambda *a, **k: ("texto cpu", "pt", -0.3, ())
    cpu.close = lambda: None

    callback_called = []
    def on_fallback(reason: str) -> None:
        callback_called.append(reason)

    manager = BackendFallbackManager(
        gpu_backend=gpu,
        cpu_backend_factory=lambda: cpu,
        max_consecutive_failures=2,
        on_fallback=on_fallback,
    )

    _info("Configurado: GPU sempre falha, CPU funciona, N=2")

    # Iteração 1: falha (contador=1).
    try:
        manager.transcribe(b"audio", "pt", 1, False, 30)
        _fail("Iteração 1 deveria ter falhado")
    except RuntimeError as e:
        _ok(f"Iteração 1 falhou como esperado: {e}")
        _info(f"  consecutive_failures={manager.consecutive_failures}")

    # Iteração 2: falha (contador=2) → dispara fallback.
    try:
        manager.transcribe(b"audio", "pt", 1, False, 30)
        _fail("Iteração 2 deveria ter falhado")
    except RuntimeError as e:
        _ok(f"Iteração 2 falhou e disparou fallback: {e}")

    # Verificar fallback.
    if manager.is_fallback_active:
        _ok("Fallback ativado após 2 falhas consecutivas")
    else:
        _fail("Fallback não foi ativado")

    if callback_called:
        _ok(f"Callback on_fallback chamado: {callback_called[0]}")
    else:
        _fail("Callback on_fallback não chamado")

    # Iteração 3: usa CPU, deve funcionar.
    result = manager.transcribe(b"audio", "pt", 1, False, 30)
    if result[0] == "texto cpu":
        _ok(f"Iteração 3 usou CPU com sucesso: '{result[0]}'")
    else:
        _fail(f"Iteração 3 falhou: {result}")

    _info(f"backend_name atual: {manager.backend_name}")
    _info(f"actual_device atual: {manager.actual_device}")
    _info(f"total_fallbacks: {manager.total_fallbacks}")
    _info(f"total_failures: {manager.total_failures}")

    if manager.backend_name == "cpu-mock":
        _ok("Backend ativo é CPU após fallback")
    else:
        _fail(f"Backend ativo deveria ser CPU, é {manager.backend_name}")

    return {
        "fallback_triggered": manager.is_fallback_active,
        "callback_called": len(callback_called) > 0,
        "cpu_used_after_fallback": result[0] == "texto cpu",
        "total_fallbacks": manager.total_fallbacks,
        "total_failures": manager.total_failures,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print()
    print("#" * 70)
    print("#  Sprint 19.1.1 — Smoke Test GPU AMD (RX 7600)")
    print("#" * 70)

    model = "tiny"  # minimizar RAM
    results = {}

    # Etapa 1.
    try:
        results["etapa1"] = etapa1_hardware_check()
    except Exception as e:
        _fail(f"Etapa 1 exceção: {e}")
        results["etapa1"] = {"error": str(e)}

    # Gerar áudio de 30s uma vez (reutilizado).
    _info("\nGerando áudio sintético de 30s...")
    audio = _generate_audio(30.0)
    _info(f"Áudio: {len(audio)} samples ({len(audio)/16000:.1f}s)")

    # Etapa 2.
    try:
        results["etapa2"] = etapa2_single_transcription(audio, model)
    except Exception as e:
        _fail(f"Etapa 2 exceção: {e}")
        results["etapa2"] = {"error": str(e)}
    gc.collect()

    # Etapa 3.
    try:
        results["etapa3"] = etapa3_gpu_utilization(audio, model)
    except Exception as e:
        _fail(f"Etapa 3 exceção: {e}")
        results["etapa3"] = {"error": str(e)}
    gc.collect()

    # Etapa 4.
    try:
        results["etapa4"] = etapa4_cpu_vs_gpu(audio, model)
    except Exception as e:
        _fail(f"Etapa 4 exceção: {e}")
        results["etapa4"] = {"error": str(e)}
    gc.collect()

    # Etapa 5.
    try:
        results["etapa5"] = etapa5_streaming_simulated(model)
    except Exception as e:
        _fail(f"Etapa 5 exceção: {e}")
        results["etapa5"] = {"error": str(e)}

    # Etapa 6.
    try:
        results["etapa6"] = etapa6_fallback()
    except Exception as e:
        _fail(f"Etapa 6 exceção: {e}")
        results["etapa6"] = {"error": str(e)}

    # Resumo.
    _section("RESUMO — Critérios de Aprovação")
    criterios = {
        "DirectML utiliza RX 7600": (
            results.get("etapa1", {}).get("rx7600", False)
            and results.get("etapa1", {}).get("directml", False)
        ),
        "GPU mais rápida que CPU": (
            results.get("etapa4", {}).get("speedup", 0) > 1.0
        ),
        "Streaming fluido (imports OK)": (
            results.get("etapa5", {}).get("imports_ok", False)
        ),
        "Holyrics (não testado neste smoke)": None,  # requer teste real
        "Fallback funciona": (
            results.get("etapa6", {}).get("fallback_triggered", False)
            and results.get("etapa6", {}).get("cpu_used_after_fallback", False)
        ),
    }
    for crit, val in criterios.items():
        if val is None:
            print(f"  [SKIP] {crit}")
        elif val:
            print(f"  [PASS] {crit}")
        else:
            print(f"  [FAIL] {crit}")

    # Salvar resultados.
    import json
    output = Path("smoke_sprint19_1_1_results.json")
    with open(output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str, ensure_ascii=False)
    _info(f"Resultados salvos em {output}")

    # Verdict.
    passed = sum(1 for v in criterios.values() if v is True)
    failed = sum(1 for v in criterios.values() if v is False)
    skipped = sum(1 for v in criterios.values() if v is None)
    print()
    print(f"  Total: {passed} pass, {failed} fail, {skipped} skip")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
