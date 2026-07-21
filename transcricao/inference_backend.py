"""InferenceBackend — abstração de backend de inferência STT (Sprint 19.1).

Responsabilidade:
  - Definir interface comum para todos os backends de inferência.
  - Permitir que o STT seja agnóstico ao hardware (CPU/CUDA/DirectML/ROCm).
  - Cada implementação carrega o modelo Whisper no formato adequado.

Sprint 19.1 — GPU Runtime & Hardware Acceleration:
  Antes desta sprint, o STT era hardcoded para FasterWhisperBackend
  (ctranslate2), que suporta apenas CUDA (NVIDIA) e CPU. Para suportar
  GPU AMD (RX 7600), criamos esta abstração com múltiplas implementações:

  - CPUBackend: faster-whisper com ctranslate2 (CPU, existente).
  - CUDABackend: faster-whisper com ctranslate2 (CUDA NVIDIA, existente).
  - DirectMLBackend: onnxruntime + DirectML (AMD/Intel/NVIDIA, novo).
  - ROCmBackend: faster-whisper com ctranslate2 ROCm (Linux AMD, futuro).

  O STT depende apenas da interface InferenceBackend. A seleção do
  backend concreto é feita pelo BackendSelector com base no hardware
  detectado e na configuração do usuário.

Thread Safety:
  - Backends são carregados uma vez na inicialização.
  - transcribe() é chamado concorrentemente pelo STTExecutor (Lock).
  - Implementações devem ser thread-safe após load().
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = [
    "InferenceBackend",
    "BackendInfo",
    "BackendCapability",
]


@runtime_checkable
class InferenceBackend(Protocol):
    """Interface comum para backends de inferência STT.

    Todas as implementações (CPU, CUDA, DirectML, ROCm) devem seguir
    esta interface. O STT chama apenas estes métodos — não conhece
    detalhes do hardware nem do engine de inferência.
    """

    def load(self) -> None:
        """Carrega o modelo na memória/GPU. Chamado uma vez na inicialização.

        Raises:
            STTError: se o modelo não puder ser carregado.
        """
        ...

    def transcribe(
        self,
        audio: Any,
        language: str,
        beam_size: int,
        vad_filter: bool,
        chunk_length: int,
    ) -> tuple[str, str, float, tuple[Any, ...]]:
        """Transcreve áudio.

        Args:
            audio: ndarray float32 [-1.0, 1.0] (16kHz mono).
            language: código ISO do idioma ("pt", "en").
            beam_size: beam size para decoding (1 = greedy).
            vad_filter: se True, ativa VAD interno.
            chunk_length: duração do chunk em segundos.

        Returns:
            (texto, idioma, avg_logprob, segmentos_brutos).

        Raises:
            STTError: se a transcrição falhar.
        """
        ...

    def unload(self) -> None:
        """Libera o modelo da memória/GPU."""
        ...

    @property
    def actual_device(self) -> str:
        """Device real usado ('cpu', 'cuda', 'directml', 'rocm')."""
        ...

    @property
    def actual_compute_type(self) -> str:
        """Compute type real usado ('float16', 'int8', etc.)."""
        ...

    @property
    def backend_name(self) -> str:
        """Nome do backend ('faster-whisper-cpu', 'faster-whisper-cuda',
        'onnx-directml', etc.)."""
        ...

    @property
    def is_loaded(self) -> bool:
        """True se o modelo está carregado e pronto para inferência."""
        ...

    @property
    def fallback_reason(self) -> str:
        """Razão de fallback (vazia se não houve fallback)."""
        ...


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class BackendCapability:
    """Capacidades de um backend (para seleção automática).

    Atributos:
        name: nome do backend ('cpu', 'cuda', 'directml', 'rocm').
        priority: prioridade de seleção (menor = maior prioridade).
        supports_fp16: suporta compute_type float16.
        supports_int8: suporta compute_type int8.
        requires_nvidia: requer GPU NVIDIA.
        requires_amd: requer GPU AMD.
        requires_directml: requer onnxruntime-directml instalado.
        requires_rocm: requer ROCm instalado.
    """

    def __init__(
        self,
        name: str,
        priority: int,
        supports_fp16: bool = False,
        supports_int8: bool = True,
        requires_nvidia: bool = False,
        requires_amd: bool = False,
        requires_directml: bool = False,
        requires_rocm: bool = False,
    ) -> None:
        self.name = name
        self.priority = priority
        self.supports_fp16 = supports_fp16
        self.supports_int8 = supports_int8
        self.requires_nvidia = requires_nvidia
        self.requires_amd = requires_amd
        self.requires_directml = requires_directml
        self.requires_rocm = requires_rocm


class BackendInfo:
    """Informações sobre um backend selecionado.

    Retornado pelo BackendSelector para que o STT saiba qual backend
    concreto instanciar.
    """

    def __init__(
        self,
        backend_type: str,
        device: str,
        compute_type: str,
        reason: str,
    ) -> None:
        self.backend_type = backend_type  # 'cpu', 'cuda', 'directml', 'rocm'
        self.device = device
        self.compute_type = compute_type
        self.reason = reason

    def __repr__(self) -> str:
        return (
            f"BackendInfo(backend={self.backend_type}, "
            f"device={self.device}, compute={self.compute_type})"
        )
