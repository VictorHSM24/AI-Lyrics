"""Exemplo de uso do módulo core/hardware.py.

Executa: python examples/use_hardware.py

Demonstra:
  1. Detecção real de hardware (se psutil/ctranslate2 disponíveis).
  2. Detecção com mocks (cenários sintéticos).
  3. Recomendações para STT, embeddings e LLM.
  4. Cenários reais do enunciado (Ryzen+AMD, RTX 2060/3060/4060, CPU only).

NOTA: A detecção real pode não encontrar GPU se nvidia-smi não estiver
no PATH ou se ctranslate2 não estiver instalado. O exemplo mostra
ambos: detecção real e cenários sintéticos.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.hardware import (
    CpuInfo,
    GpuInfo,
    HardwareDetector,
    HardwareProfile,
    HardwareRecommender,
    Recommendations,
)


def _print_profile(profile: HardwareProfile, label: str = "Hardware") -> None:
    """Imprime um HardwareProfile de forma legível."""
    print(f"\n--- {label} ---\n")
    print(f"  CPU: {profile.cpu.name}")
    print(f"       {profile.cpu.physical_cores} physical / {profile.cpu.logical_cores} logical cores")
    print(f"       arch: {profile.cpu.architecture}")
    print(f"  RAM: {profile.ram_mb} MB")
    print(f"  OS:  {profile.os_name} {profile.os_version}")
    print(f"  Py:  {profile.python_version}")

    if profile.gpus:
        for i, g in enumerate(profile.gpus):
            print(f"  GPU[{i}]: {g.name}")
            print(f"         vendor: {g.vendor}")
            print(f"         VRAM:   {g.vram_mb} MB")
            print(f"         CUDA:   {g.cuda_support}" + (f" ({g.cuda_version})" if g.cuda_version else ""))
    else:
        print("  GPU: (none detected)")

    print(f"\n  has_nvidia_gpu: {profile.has_nvidia_gpu}")
    print(f"  has_cuda:       {profile.has_cuda}")
    if profile.primary_gpu:
        print(f"  primary_gpu:    {profile.primary_gpu.name}")
    print(f"  total_vram_mb:  {profile.total_vram_mb}")


def _print_recommendations(recs: Recommendations) -> None:
    """Imprime recomendações de forma legível."""
    print("\n--- Recomendações ---\n")
    print(f"  STT:")
    print(f"    device:       {recs.stt.suggested_device}")
    print(f"    compute_type: {recs.stt.suggested_compute_type}")
    print(f"    model:        {recs.stt.suggested_model}")
    print(f"    reason:       {recs.stt.reason}")

    print(f"\n  Embedding:")
    print(f"    device: {recs.embedding.suggested_device}")
    print(f"    reason: {recs.embedding.reason}")

    print(f"\n  LLM:")
    print(f"    device:     {recs.llm.suggested_device}")
    print(f"    can_run_8b: {recs.llm.can_run_8b}")
    print(f"    reason:     {recs.llm.reason}")


def _make_profile(
    cpu_name: str = "AMD Ryzen 7 5700G",
    cpu_physical: int = 8,
    cpu_logical: int = 16,
    ram_mb: int = 16000,
    gpus: tuple[GpuInfo, ...] = (),
) -> HardwareProfile:
    return HardwareProfile(
        cpu=CpuInfo(
            name=cpu_name,
            physical_cores=cpu_physical,
            logical_cores=cpu_logical,
            architecture="x86_64",
        ),
        ram_mb=ram_mb,
        gpus=gpus,
        os_name="windows",
        os_version="10",
        python_version="3.14.0",
    )


def main() -> None:
    print("=== Detecção de Hardware e Recomendações ===\n")

    # 1. Detecção real
    print("--- Detecção real ---\n")
    try:
        profile = HardwareDetector.detect()
        _print_profile(profile, "Hardware Real")
        recs = HardwareRecommender.recommend(profile)
        _print_recommendations(recs)
    except Exception as e:
        print(f"  Detecção real falhou (esperado sem psutil/GPU): {e}")

    # 2. Cenários sintéticos do enunciado
    print("\n" + "=" * 60)
    print("--- Cenários sintéticos ---\n")

    # Cenário 1: Ryzen 5700G + RX 7600 (AMD, sem CUDA)
    print("\n[1] Ryzen 5700G + RX 7600 (AMD, sem CUDA)")
    p1 = _make_profile(
        cpu_name="AMD Ryzen 7 5700G",
        ram_mb=16000,
        gpus=(GpuInfo("AMD Radeon RX 7600", "amd", 8000, "none", None),),
    )
    _print_profile(p1, "Ryzen + AMD")
    _print_recommendations(HardwareRecommender.recommend(p1))

    # Cenário 2: RTX 2060 (6GB)
    print("\n[2] RTX 2060 (6GB VRAM)")
    p2 = _make_profile(
        cpu_name="Intel Core i5-12400",
        ram_mb=16000,
        gpus=(GpuInfo("NVIDIA GeForce RTX 2060", "nvidia", 6144, "full", "12"),),
    )
    _print_profile(p2, "RTX 2060")
    _print_recommendations(HardwareRecommender.recommend(p2))

    # Cenário 3: RTX 3060 (12GB)
    print("\n[3] RTX 3060 (12GB VRAM)")
    p3 = _make_profile(
        cpu_name="AMD Ryzen 5 5600",
        ram_mb=32000,
        gpus=(GpuInfo("NVIDIA GeForce RTX 3060", "nvidia", 12288, "full", "12"),),
    )
    _print_profile(p3, "RTX 3060")
    _print_recommendations(HardwareRecommender.recommend(p3))

    # Cenário 4: RTX 4060 (8GB)
    print("\n[4] RTX 4060 (8GB VRAM)")
    p4 = _make_profile(
        cpu_name="AMD Ryzen 7 5700X",
        ram_mb=32000,
        gpus=(GpuInfo("NVIDIA GeForce RTX 4060", "nvidia", 8192, "full", "12"),),
    )
    _print_profile(p4, "RTX 4060")
    _print_recommendations(HardwareRecommender.recommend(p4))

    # Cenário 5: CPU only
    print("\n[5] CPU only (sem GPU)")
    p5 = _make_profile(
        cpu_name="Intel Core i5-10400",
        ram_mb=16000,
        gpus=(),
    )
    _print_profile(p5, "CPU Only")
    _print_recommendations(HardwareRecommender.recommend(p5))

    # Cenário 6: CPU fraco
    print("\n[6] CPU fraco (4GB RAM)")
    p6 = _make_profile(
        cpu_name="Intel Celeron N4500",
        cpu_physical=2,
        cpu_logical=2,
        ram_mb=4000,
        gpus=(),
    )
    _print_profile(p6, "CPU Fraco")
    _print_recommendations(HardwareRecommender.recommend(p6))

    print("\n=== Concluído ===")
    print("\nNOTA: As recomendações são apenas sugestões.")
    print("A config do usuário (config.yaml) sempre tem precedência.")


if __name__ == "__main__":
    main()
