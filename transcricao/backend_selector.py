"""BackendSelector — seleção automática de backend de inferência (Sprint 19.1).

Responsabilidade:
  - Selecionar o backend de inferência mais adequado com base no hardware.
  - Aplicar override via configuração do usuário.
  - Resolver "auto" para um backend concreto.

Sprint 19.1 — GPU Runtime & Hardware Acceleration:
  O BackendSelector é o único componente que toma a decisão de qual
  backend usar. Ele consulta o HardwareDetector e a configuração do
  usuário, e retorna um BackendInfo descrevendo o backend escolhido.

  Prioridade (quando backend="auto"):
    1. CUDA (NVIDIA + ctranslate2)
    2. DirectML (AMD/Intel/NVIDIA + onnxruntime-directml)
    3. ROCm (AMD + ROCm, Linux)
    4. CPU (sempre disponível)

  Override via config:
    stt:
      backend: auto       # seleção automática
      backend: cuda       # força CUDA
      backend: directml   # força DirectML
      backend: rocm       # força ROCm
      backend: cpu        # força CPU

  O BackendSelector NÃO instancia o backend — apenas decide. A
  instanciação é feita pelo STTExecutor/STT com base no BackendInfo.
"""

from __future__ import annotations

import logging
from typing import Any

from core.hardware import HardwareDetector, HardwareProfile
from transcricao.inference_backend import BackendCapability, BackendInfo

logger = logging.getLogger(__name__)

__all__ = ["BackendSelector", "BackendSelectionError"]


class BackendSelectionError(Exception):
    """Erro na seleção de backend."""


# Capacidades de cada backend (em ordem de prioridade).
_BACKEND_CAPABILITIES: tuple[BackendCapability, ...] = (
    BackendCapability(
        name="cuda",
        priority=1,
        supports_fp16=True,
        supports_int8=True,
        requires_nvidia=True,
    ),
    BackendCapability(
        name="directml",
        priority=2,
        supports_fp16=False,  # DirectML só suporta float32 para Whisper ONNX
        supports_int8=False,
        requires_directml=True,
    ),
    BackendCapability(
        name="rocm",
        priority=3,
        supports_fp16=True,
        supports_int8=True,
        requires_amd=True,
        requires_rocm=True,
    ),
    BackendCapability(
        name="cpu",
        priority=4,
        supports_fp16=False,
        supports_int8=True,
    ),
)


class BackendSelector:
    """Seleciona o backend de inferência mais adequado.

    Métodos estáticos — não requer instância.
    """

    @staticmethod
    def select(
        requested_backend: str = "auto",
        requested_compute_type: str = "auto",
        profile: HardwareProfile | None = None,
    ) -> BackendInfo:
        """Seleciona o backend com base no hardware e na config.

        Args:
            requested_backend: "auto", "cuda", "directml", "rocm", ou "cpu".
            requested_compute_type: "auto", "float16", "int8_float16",
                "int8", "float32".
            profile: HardwareProfile (se None, detecta automaticamente).

        Returns:
            BackendInfo com backend_type, device, compute_type, reason.

        Raises:
            BackendSelectionError: se o backend solicitado não está
                disponível.
        """
        if profile is None:
            profile = HardwareDetector.detect()

        # Resolver "auto" para backend concreto.
        if requested_backend == "auto":
            return BackendSelector._select_auto(profile, requested_compute_type)

        # Backend específico solicitado — validar disponibilidade.
        return BackendSelector._select_specific(
            requested_backend, requested_compute_type, profile
        )

    @staticmethod
    def _select_auto(
        profile: HardwareProfile, requested_compute_type: str
    ) -> BackendInfo:
        """Seleção automática: percorre backends em ordem de prioridade."""
        for cap in _BACKEND_CAPABILITIES:
            if BackendSelector._is_available(cap, profile):
                compute = BackendSelector._resolve_compute_type(
                    cap, requested_compute_type, profile
                )
                reason = (
                    f"auto-selected {cap.name} "
                    f"(priority={cap.priority}, available=True)"
                )
                logger.info(
                    "BackendSelector: auto → %s (compute=%s)",
                    cap.name, compute,
                )
                return BackendInfo(
                    backend_type=cap.name,
                    device=cap.name,
                    compute_type=compute,
                    reason=reason,
                )

        # Nunca deveria chegar aqui — CPU é sempre disponível.
        raise BackendSelectionError(
            "no backend available — this should not happen "
            "(CPU should always be available)"
        )

    @staticmethod
    def _select_specific(
        backend: str, compute_type: str, profile: HardwareProfile
    ) -> BackendInfo:
        """Seleção específica: valida que o backend solicitado está disponível."""
        cap = BackendSelector._find_capability(backend)
        if cap is None:
            raise BackendSelectionError(
                f"unknown backend '{backend}' "
                f"(valid: auto, cuda, directml, rocm, cpu)"
            )

        if not BackendSelector._is_available(cap, profile):
            # Fallback gracioso para CPU se backend solicitado não disponível.
            if backend != "cpu":
                logger.warning(
                    "BackendSelector: backend '%s' not available — "
                    "falling back to CPU", backend,
                )
                cpu_cap = BackendSelector._find_capability("cpu")
                compute = BackendSelector._resolve_compute_type(
                    cpu_cap, compute_type, profile
                )
                return BackendInfo(
                    backend_type="cpu",
                    device="cpu",
                    compute_type=compute,
                    reason=(
                        f"requested '{backend}' not available — "
                        f"fell back to CPU"
                    ),
                )
            raise BackendSelectionError(
                f"backend '{backend}' not available on this hardware"
            )

        compute = BackendSelector._resolve_compute_type(
            cap, compute_type, profile
        )
        return BackendInfo(
            backend_type=cap.name,
            device=cap.name,
            compute_type=compute,
            reason=f"explicitly selected {cap.name}",
        )

    @staticmethod
    def _is_available(cap: BackendCapability, profile: HardwareProfile) -> bool:
        """Verifica se um backend está disponível no hardware atual."""
        if cap.name == "cpu":
            return True  # CPU sempre disponível.

        if cap.name == "cuda":
            return profile.has_cuda

        if cap.name == "directml":
            # DirectML requer onnxruntime-directml + GPU (AMD/Intel/NVIDIA).
            return profile.has_directml and len(profile.gpus) > 0

        if cap.name == "rocm":
            return profile.has_rocm

        return False

    @staticmethod
    def _find_capability(name: str) -> BackendCapability | None:
        """Encontra a capacidade de um backend pelo nome."""
        for cap in _BACKEND_CAPABILITIES:
            if cap.name == name:
                return cap
        return None

    @staticmethod
    def _resolve_compute_type(
        cap: BackendCapability,
        requested: str,
        profile: HardwareProfile,
    ) -> str:
        """Resolve o compute_type final com base no backend e hardware.

        Lógica:
        - "auto": usar o melhor compute_type suportado pelo backend.
        - Específico: validar que o backend suporta, senão usar default.
        """
        if cap.name == "cpu":
            if requested == "auto":
                return "int8"
            # CPU suporta: int8, int8_float16 (raro), float32.
            if requested in ("int8", "int8_float16", "float32"):
                return requested
            return "int8"  # fallback seguro

        if cap.name == "cuda":
            if requested == "auto":
                # CUDA com >= 8GB VRAM → float16, senão int8_float16.
                vram = profile.total_vram_mb
                if vram >= 8000:
                    return "float16"
                if vram >= 4000:
                    return "int8_float16"
                return "int8"
            # Validar que CUDA suporta o compute_type solicitado.
            if requested in ("float16", "int8_float16", "int8", "float32"):
                return requested
            return "float16"  # default CUDA

        if cap.name == "directml":
            # DirectML (Whisper ONNX) só suporta float32.
            if requested == "auto":
                return "float32"
            if requested == "float32":
                return requested
            # Outros compute_types não suportados — usar float32.
            logger.warning(
                "BackendSelector: DirectML does not support "
                "compute_type='%s' — using float32", requested
            )
            return "float32"

        if cap.name == "rocm":
            if requested == "auto":
                return "float16"
            if requested in ("float16", "int8_float16", "int8", "float32"):
                return requested
            return "float16"

        return "int8"  # fallback seguro

    @staticmethod
    def list_available(profile: HardwareProfile | None = None) -> list[dict]:
        """Lista todos os backends disponíveis com suas capacidades.

        Útil para a API expor opções ao frontend.
        """
        if profile is None:
            profile = HardwareDetector.detect()

        result: list[dict] = []
        for cap in _BACKEND_CAPABILITIES:
            available = BackendSelector._is_available(cap, profile)
            result.append({
                "name": cap.name,
                "priority": cap.priority,
                "available": available,
                "supports_fp16": cap.supports_fp16,
                "supports_int8": cap.supports_int8,
            })
        return result
