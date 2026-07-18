"""Detecção de hardware e recomendações de configuração.

Responsabilidade: **apenas detectar e informar**. Não toma decisões.
A decisão final de usar GPU/CPU, qual modelo, qual compute_type
permanece nos módulos consumidores e na configuração do usuário.

Localização arquitetural: ``core/hardware.py`` — código transversal
(Guia §2.2: "core/ é para código transversal"). Não é um módulo de
domínio; é infraestrutura compartilhada como core/types.py e
core/exceptions.py.

Justificativa de extração:
  - ``FasterWhisperBackend._check_cuda()`` fazia detecção inline,
    misturando infraestrutura com lógica de transcrição.
  - Futuros consumidores (LLM local, embeddings, Parakeet) precisarão
    das mesmas informações sem duplicar lógica de detecção.
  - Centralizar permite testar detecção independentemente de cada
    módulo consumidor.

Limites explícitos (o que este módulo NÃO faz):
  - Não toma decisões de configuração automaticamente.
  - Não modifica config.yaml nem Config.
  - Não faz benchmark de performance.
  - Não coleta telemetria nem envia dados para fora.
  - Não implementa lógica de STT, LLM, ou inferência.

Dependências:
  - ``psutil``: detecção de CPU e RAM (wheels pré-compiladas, leve).
  - ``ctranslate2``: detecção de CUDA (já dependência de faster-whisper).
  - Fallback gracioso: se psutil não estiver instalado, usa os stdlib.
  - Fallback gracioso: se ctranslate2 não estiver instalado, CUDA = False.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DTOs (imutáveis)
# ---------------------------------------------------------------------------

GpuVendor = Literal["nvidia", "amd", "intel", "apple", "unknown"]
CudaSupport = Literal["full", "partial", "none"]


@dataclass(frozen=True)
class CpuInfo:
    """Informações da CPU.

    Atributos:
        name: nome do processador (ex.: "AMD Ryzen 7 5700G").
        physical_cores: número de núcleos físicos.
        logical_cores: número de threads lógicas (hyperthreading).
        architecture: arquitetura (ex.: "x86_64", "arm64").
    """

    name: str
    physical_cores: int
    logical_cores: int
    architecture: str


@dataclass(frozen=True)
class GpuInfo:
    """Informações de uma GPU.

    Atributos:
        name: nome da GPU (ex.: "NVIDIA GeForce RTX 4060").
        vendor: fabricante ("nvidia", "amd", "intel", "apple", "unknown").
        vram_mb: VRAM em megabytes (0 se desconhecido).
        cuda_support: suporte a CUDA ("full", "partial", "none").
        cuda_version: versão do CUDA detectada (None se não disponível).
    """

    name: str
    vendor: GpuVendor
    vram_mb: int
    cuda_support: CudaSupport
    cuda_version: str | None = None


@dataclass(frozen=True)
class HardwareProfile:
    """Perfil de hardware imutável do sistema.

    Produto da detecção de hardware. Consumidores consultam este
    objeto para decidir configurações — o perfil não decide nada.

    Atributos:
        cpu: informações da CPU.
        ram_mb: RAM total do sistema em megabytes.
        gpus: lista de GPUs detectadas (pode ser vazia).
        has_nvidia_gpu: True se há ao menos uma GPU NVIDIA.
        has_cuda: True se CUDA está funcionalmente disponível.
        os_name: sistema operacional ("windows", "linux", "darwin").
        os_version: versão do SO.
        python_version: versão do Python em execução.
    """

    cpu: CpuInfo
    ram_mb: int
    gpus: tuple[GpuInfo, ...]
    os_name: str
    os_version: str
    python_version: str

    @property
    def has_nvidia_gpu(self) -> bool:
        """True se há ao menos uma GPU NVIDIA."""
        return any(g.vendor == "nvidia" for g in self.gpus)

    @property
    def has_cuda(self) -> bool:
        """True se CUDA está funcionalmente disponível (GPU NVIDIA + libs)."""
        return any(
            g.vendor == "nvidia" and g.cuda_support in ("full", "partial")
            for g in self.gpus
        )

    @property
    def primary_gpu(self) -> GpuInfo | None:
        """GPU principal (primeira NVIDIA se houver, senão a primeira)."""
        nvidia = [g for g in self.gpus if g.vendor == "nvidia"]
        if nvidia:
            return nvidia[0]
        if self.gpus:
            return self.gpus[0]
        return None

    @property
    def total_vram_mb(self) -> int:
        """VRAM total de todas as GPUs NVIDIA."""
        return sum(g.vram_mb for g in self.gpus if g.vendor == "nvidia")


@dataclass(frozen=True)
class STTRecommendation:
    """Recomendação de configuração para STT.

    Apenas sugestão — o usuário e o módulo consumidor decidem.
    """

    suggested_device: str  # "cuda" | "cpu"
    suggested_compute_type: str  # "float16", "int8_float16", "int8"
    suggested_model: str  # "large-v3-turbo", "medium", "small"
    reason: str  # justificativa humana-legível


@dataclass(frozen=True)
class EmbeddingRecommendation:
    """Recomendação de configuração para embeddings."""

    suggested_device: str  # "cuda" | "cpu"
    reason: str


@dataclass(frozen=True)
class LLMRecommendation:
    """Recomendação de configuração para LLM local.

    Apenas sugestão baseada em VRAM/RAM. Não decide se LLM deve
    ser usado — isso é decisão do pipeline e da config do usuário.
    """

    suggested_device: str  # "cuda" | "cpu"
    can_run_8b: bool  # VRAM/RAM suficiente para Qwen3 8B Q4
    reason: str


@dataclass(frozen=True)
class Recommendations:
    """Recomendações agregadas para todos os módulos consumidores.

    Cada campo é uma recomendação independente. Consumidores podem
    seguir ou ignorar — a config do usuário sempre tem precedência.
    """

    stt: STTRecommendation
    embedding: EmbeddingRecommendation
    llm: LLMRecommendation


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class HardwareDetector:
    """Detector de hardware do sistema.

    Métodos estáticos — não requer instância. Produz HardwareProfile
    imutável. Fallback gracioso quando bibliotecas opcionais não
    estão instaladas.

    Usage:
        profile = HardwareDetector.detect()
        if profile.has_cuda:
            print(f"CUDA disponível: {profile.primary_gpu.name}")
    """

    @staticmethod
    def detect() -> HardwareProfile:
        """Detecta hardware do sistema e retorna HardwareProfile imutável.

        Segura: nunca levanta exceção. Se uma detecção falha, usa
        valor padrão seguro (desconhecido/zero) e loga warning.
        """
        cpu = HardwareDetector._detect_cpu()
        ram_mb = HardwareDetector._detect_ram()
        gpus = HardwareDetector._detect_gpus()
        os_name, os_version = HardwareDetector._detect_os()
        python_version = HardwareDetector._detect_python()

        profile = HardwareProfile(
            cpu=cpu,
            ram_mb=ram_mb,
            gpus=gpus,
            os_name=os_name,
            os_version=os_version,
            python_version=python_version,
        )

        logger.info(
            "Hardware detected: cpu=%s, ram=%dMB, gpus=%d, cuda=%s, os=%s",
            cpu.name,
            ram_mb,
            len(gpus),
            profile.has_cuda,
            os_name,
        )
        return profile

    # ------------------------------------------------------------------
    # CPU
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_cpu() -> CpuInfo:
        """Detecta informações da CPU."""
        name = HardwareDetector._detect_cpu_name()
        physical, logical = HardwareDetector._detect_cpu_cores()
        arch = platform.machine() or "unknown"
        return CpuInfo(
            name=name,
            physical_cores=physical,
            logical_cores=logical,
            architecture=arch,
        )

    @staticmethod
    def _detect_cpu_name() -> str:
        """Detecta nome da CPU."""
        try:
            import psutil

            # psutil não tem nome direto, mas platform geralmente funciona
            pass
        except ImportError:
            pass

        # Windows: platform.processor() retorna o nome
        name = platform.processor() or ""
        if name:
            return name

        # Fallback: ler do /proc/cpuinfo no Linux
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except (FileNotFoundError, PermissionError):
            pass

        # Fallback final
        try:
            import psutil

            return f"Unknown ({psutil.cpu_count() or '?'} cores)"
        except ImportError:
            return "Unknown"

    @staticmethod
    def _detect_cpu_cores() -> tuple[int, int]:
        """Detecta núcleos físicos e lógicos.

        Returns:
            (physical_cores, logical_cores)
        """
        try:
            import psutil

            physical = psutil.cpu_count(logical=False) or 1
            logical = psutil.cpu_count(logical=True) or physical
            return physical, logical
        except ImportError:
            pass

        # Fallback: os.cpu_count() (lógicos)
        logical = os.cpu_count() or 1
        # Sem psutil, não dá para distinguir físico de lógico
        return logical, logical

    # ------------------------------------------------------------------
    # RAM
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_ram() -> int:
        """Detecta RAM total em megabytes. 0 se desconhecido."""
        try:
            import psutil

            return int(psutil.virtual_memory().total / (1024 * 1024))
        except ImportError:
            pass

        # Fallback Windows: WMI via subprocess é pesado; usar 0
        logger.debug("psutil not available — RAM detection skipped")
        return 0

    # ------------------------------------------------------------------
    # GPU
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_gpus() -> tuple[GpuInfo, ...]:
        """Detecta GPUs disponíveis no sistema.

        Ordem de detecção:
        1. NVIDIA via nvidia-smi (mais confiável para VRAM e CUDA)
        2. NVIDIA via ctranslate2 (confirma CUDA funcional)
        3. Fallback: sem GPU detectada
        """
        gpus: list[GpuInfo] = []

        # 1. nvidia-smi (fornece nome + VRAM)
        nvidia_gpus = HardwareDetector._detect_nvidia_via_smi()
        gpus.extend(nvidia_gpus)

        # 2. Se nvidia-smi não encontrou, tentar ctranslate2
        if not gpus:
            nvidia_ct2 = HardwareDetector._detect_nvidia_via_ctranslate2()
            gpus.extend(nvidia_ct2)

        # 3. Detectar AMD/Intel (apenas nome, sem CUDA)
        #    Não crítico para o projeto (STT usa CUDA ou CPU)
        #    Futuramente: ROCm para AMD

        return tuple(gpus)

    @staticmethod
    def _detect_nvidia_via_smi() -> list[GpuInfo]:
        """Detecta GPUs NVIDIA via nvidia-smi.

        nvidia-smi fornece nome, VRAM e versão do CUDA driver.
        """
        smi_path = shutil.which("nvidia-smi")
        if smi_path is None:
            return []

        import subprocess

        try:
            result = subprocess.run(
                [smi_path, "--query-gpu=name,memory.total,driver_version",
                 "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return []

            gpus: list[GpuInfo] = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 2:
                    continue
                name = parts[0]
                vram_mb = int(parts[1]) if parts[1].isdigit() else 0
                driver_version = parts[2] if len(parts) > 2 else None

                # Verificar suporte CUDA via ctranslate2
                cuda_support, cuda_ver = HardwareDetector._check_cuda_support()

                gpus.append(GpuInfo(
                    name=name,
                    vendor="nvidia",
                    vram_mb=vram_mb,
                    cuda_support=cuda_support,
                    cuda_version=cuda_ver,
                ))
            return gpus
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError) as e:
            logger.debug("nvidia-smi detection failed: %s", e)
            return []

    @staticmethod
    def _detect_nvidia_via_ctranslate2() -> list[GpuInfo]:
        """Detecta GPU NVIDIA via ctranslate2 (quando nvidia-smi falha).

        ctranslate2 confirma que CUDA está funcional para inferência,
        mas não fornece nome nem VRAM.
        """
        cuda_support, cuda_ver = HardwareDetector._check_cuda_support()
        if cuda_support == "none":
            return []

        # ctranslate2 confirma CUDA mas não dá nome/VRAM
        return [GpuInfo(
            name="NVIDIA GPU (via ctranslate2)",
            vendor="nvidia",
            vram_mb=0,  # desconhecido sem nvidia-smi
            cuda_support=cuda_support,
            cuda_version=cuda_ver,
        )]

    @staticmethod
    def _check_cuda_support() -> tuple[CudaSupport, str | None]:
        """Verifica se CUDA está funcionalmente disponível via ctranslate2.

        Returns:
            (suporte, versão) — suporte é "full", "partial", ou "none".
        """
        try:
            import ctranslate2

            compute_types = ctranslate2.get_supported_compute_types("cuda")
            if not compute_types:
                return "none", None

            # Verificar versão do CUDA compilada no ctranslate2
            try:
                version = ctranslate2.__version__
                # ctranslate2 4.x suporta CUDA 12
                return "full", f"ctranslate2-{version}"
            except AttributeError:
                return "partial", None
        except ImportError:
            return "none", None
        except Exception as e:
            logger.debug("ctranslate2 CUDA check failed: %s", e)
            return "none", None

    # ------------------------------------------------------------------
    # OS / Python
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_os() -> tuple[str, str]:
        """Detecta sistema operacional.

        Returns:
            (os_name, os_version) — os_name é "windows", "linux", "darwin".
        """
        system = platform.system().lower()
        if system == "windows":
            return "windows", platform.version()
        if system == "linux":
            return "linux", platform.release()
        if system == "darwin":
            return "darwin", platform.mac_ver()[0]
        return system or "unknown", platform.release() or "unknown"

    @staticmethod
    def _detect_python() -> str:
        """Detecta versão do Python."""
        return platform.python_version()


# ---------------------------------------------------------------------------
# Recomendador (sugestões, não decisões)
# ---------------------------------------------------------------------------


class HardwareRecommender:
    """Produz recomendações de configuração baseadas no HardwareProfile.

    **Não toma decisões.** Apenas sugere. A config do usuário e os
    módulos consumidores têm a decisão final.
    """

    # Constantes de referência (não calibradas empiricamente — ajustar)
    MIN_VRAM_TURBO_FP16 = 8000   # large-v3-turbo FP16 precisa ~8GB VRAM
    MIN_VRAM_TURBO_INT8 = 4000   # large-v3-turbo INT8 precisa ~4GB VRAM
    MIN_VRAM_8B_Q4 = 6000        # Qwen3 8B Q4 precisa ~6GB VRAM
    MIN_RAM_8B_Q4_CPU = 16000    # 8B Q4 em CPU precisa ~16GB RAM
    MIN_RAM_MEDIUM = 8000        # modelo medium em CPU
    MIN_RAM_SMALL = 4000         # modelo small em CPU

    @staticmethod
    def recommend(profile: HardwareProfile) -> Recommendations:
        """Produz recomendações agregadas para todos os módulos.

        Args:
            profile: HardwareProfile detectado.

        Returns:
            Recommendations com sugestões para STT, embeddings e LLM.
        """
        return Recommendations(
            stt=HardwareRecommender.recommend_stt(profile),
            embedding=HardwareRecommender.recommend_embedding(profile),
            llm=HardwareRecommender.recommend_llm(profile),
        )

    @staticmethod
    def recommend_stt(profile: HardwareProfile) -> STTRecommendation:
        """Sugere configuração de STT baseada no hardware.

        Lógica:
        - GPU NVIDIA com >= 4GB VRAM → cuda + float16 + large-v3-turbo
        - GPU NVIDIA com >= 2.5GB VRAM → cuda + int8_float16 + large-v3-turbo
        - CPU com >= 8GB RAM → cpu + int8 + medium
        - CPU com >= 4GB RAM → cpu + int8 + small
        - Caso contrário → cpu + int8 + small (mínimo viável)
        """
        gpu = profile.primary_gpu
        vram = gpu.vram_mb if gpu and gpu.vendor == "nvidia" else 0

        if profile.has_cuda and vram >= HardwareRecommender.MIN_VRAM_TURBO_FP16:
            return STTRecommendation(
                suggested_device="cuda",
                suggested_compute_type="float16",
                suggested_model="large-v3-turbo",
                reason=f"GPU NVIDIA com {vram}MB VRAM suporta turbo FP16",
            )

        if profile.has_cuda and vram >= HardwareRecommender.MIN_VRAM_TURBO_INT8:
            return STTRecommendation(
                suggested_device="cuda",
                suggested_compute_type="int8_float16",
                suggested_model="large-v3-turbo",
                reason=f"GPU NVIDIA com {vram}MB VRAM — turbo INT8 recomendado",
            )

        if profile.has_cuda and vram > 0:
            return STTRecommendation(
                suggested_device="cuda",
                suggested_compute_type="int8",
                suggested_model="medium",
                reason=f"GPU NVIDIA com {vram}MB VRAM — medium INT8 (VRAM limitada)",
            )

        # CPU
        ram = profile.ram_mb
        if ram >= HardwareRecommender.MIN_RAM_MEDIUM:
            return STTRecommendation(
                suggested_device="cpu",
                suggested_compute_type="int8",
                suggested_model="medium",
                reason=f"CPU only, {ram}MB RAM — medium INT8",
            )

        if ram >= HardwareRecommender.MIN_RAM_SMALL:
            return STTRecommendation(
                suggested_device="cpu",
                suggested_compute_type="int8",
                suggested_model="small",
                reason=f"CPU only, {ram}MB RAM — small INT8",
            )

        return STTRecommendation(
            suggested_device="cpu",
            suggested_compute_type="int8",
            suggested_model="small",
            reason="Hardware limitado — small INT8 (mínimo viável)",
        )

    @staticmethod
    def recommend_embedding(profile: HardwareProfile) -> EmbeddingRecommendation:
        """Sugere device para embeddings (e5-small é leve).

        Embeddings são leves (~0.5GB VRAM). GPU é preferível mas
        CPU é perfeitamente viável (~10-20ms por query).
        """
        if profile.has_cuda:
            return EmbeddingRecommendation(
                suggested_device="cuda",
                reason="GPU NVIDIA disponível — embeddings na GPU",
            )
        return EmbeddingRecommendation(
            suggested_device="cpu",
            reason="Sem GPU NVIDIA — embeddings na CPU (aceitável para e5-small)",
        )

    @staticmethod
    def recommend_llm(profile: HardwareProfile) -> LLMRecommendation:
        """Sugere configuração para LLM local (Qwen3 8B Q4).

        LLM é o componente mais pesado. 8B Q4 precisa de ~6GB VRAM
        ou ~16GB RAM para CPU.
        """
        vram = profile.total_vram_mb
        ram = profile.ram_mb

        if vram >= HardwareRecommender.MIN_VRAM_8B_Q4:
            return LLMRecommendation(
                suggested_device="cuda",
                can_run_8b=True,
                reason=f"GPU com {vram}MB VRAM — Qwen3 8B Q4 na GPU",
            )

        if ram >= HardwareRecommender.MIN_RAM_8B_Q4_CPU:
            return LLMRecommendation(
                suggested_device="cpu",
                can_run_8b=True,
                reason=f"Sem GPU suficiente, mas {ram}MB RAM — 8B Q4 na CPU (lento)",
            )

        return LLMRecommendation(
            suggested_device="cpu",
            can_run_8b=False,
            reason=f"VRAM={vram}MB, RAM={ram}MB — insuficiente para 8B Q4",
        )
