"""DirectMLBackend — backend ONNX Runtime com DirectML (Sprint 19.1).

Responsabilidade:
  - Carregar modelo Whisper em formato ONNX via optimum.
  - Executar inferência via onnxruntime com DmlExecutionProvider.
  - Suporta GPUs AMD, Intel e NVIDIA no Windows via DirectX 12.

Sprint 19.1 — GPU Runtime & Hardware Acceleration:
  Este backend permite usar a AMD RX 7600 para inferência Whisper.
  O ctranslate2 (faster-whisper) não suporta GPU AMD, então usamos
  ONNX Runtime com DirectML como alternativa.

  Usa `optimum` (HuggingFace) para carregar modelos Whisper ONNX com
  arquitetura encoder-decoder (encoder_model.onnx + decoder_model.onnx).
  O optimum gerencia o download e cache automaticamente via HuggingFace Hub.

  Modelos Whisper ONNX são publicados pela Microsoft/HuggingFace:
  https://huggingface.co/onnx-community

Limitações documentadas (Windows + RX 7600):
  - DirectML não suporta beam_size > 1 de forma nativa no Whisper ONNX.
    Recomendado beam_size=1 (greedy decoding).
  - DirectML não suporta float16 para Whisper ONNX (apenas float32).
    O overhead de float32 é parcialmente compensado pela GPU.
  - VAD interno do Whisper não está disponível no modelo ONNX base.
    O VAD do microfone (SpeechPipeline) já cuida disso.
  - chunk_length é fixo no modelo ONNX (30s padrão).
  - VRAM usada não é exposta via API do onnxruntime-directml.
    Para monitorar, usar Gerenciador de Tarefas ou AMD Adrenalin.

Thread Safety:
  - onnxruntime.InferenceSession é thread-safe para Run().
  - O STTExecutor serializa acesso mesmo assim (Lock).
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["DirectMLBackend", "DirectMLBackendError"]


class DirectMLBackendError(Exception):
    """Erro específico do DirectMLBackend."""


# Mapeamento de nomes de modelo faster-whisper → modelos ONNX.
# A HuggingFace/onnx-community publica modelos Whisper ONNX.
_ONNX_MODEL_MAP = {
    "large-v3-turbo": "onnx-community/whisper-large-v3-turbo",
    "large-v3": "onnx-community/whisper-large-v3",
    "large-v2": "onnx-community/whisper-large-v2",
    "medium": "onnx-community/whisper-medium",
    "small": "onnx-community/whisper-small",
    "base": "onnx-community/whisper-base",
    "tiny": "onnx-community/whisper-tiny",
}


class DirectMLBackend:
    """Backend ONNX Runtime com DirectML para GPU AMD/Intel/NVIDIA.

    Implementa a interface InferenceBackend (Protocol).

    Args:
        model_name: nome do modelo faster-whisper (ex.: "large-v3-turbo").
            Será mapeado para o modelo ONNX correspondente.
        compute_type: tipo de compute ("float32" para DirectML — float16
            não suportado).
        device_id: índice da GPU DirectML (0 = GPU primária).
        gpu_memory_limit_mb: limite de VRAM em MB (0 = sem limite).
            NOTA: onnxruntime-directml não suporta limite direto de VRAM.
            Este parâmetro é aceito mas ignorado por ora.
        num_threads: número de threads CPU para ops paralelos (0 = auto).

    Note:
        Este backend requer `onnxruntime-directml` e `optimum` instalados.
        O modelo ONNX é baixado automaticamente na primeira execução
        via HuggingFace Hub (cache em ~/.cache/huggingface/hub).
    """

    def __init__(
        self,
        model_name: str,
        compute_type: str = "float32",
        device_id: int = 0,
        gpu_memory_limit_mb: int = 0,
        num_threads: int = 0,
    ) -> None:
        self._model_name = model_name
        self._requested_compute_type = compute_type
        self._device_id = device_id
        self._gpu_memory_limit_mb = gpu_memory_limit_mb
        self._num_threads = num_threads

        self._processor: Any = None  # WhisperProcessor (tokenizer + feature extractor)
        self._model: Any = None      # ORTModelForSpeechSeq2Seq
        self._actual_compute_type = "float32"  # DirectML só suporta float32
        self._fallback_reason = ""
        self._is_loaded = False

        # Resolver nome do modelo ONNX.
        self._onnx_model_id = _ONNX_MODEL_MAP.get(
            model_name,
            f"onnx-community/whisper-{model_name}",
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Carrega o modelo Whisper ONNX via optimum com DirectML.

        Usa ORTModelForSpeechSeq2Seq do optimum para carregar encoder+decoder
        ONNX com DmlExecutionProvider.

        Raises:
            DirectMLBackendError: se onnxruntime-directml/optimum não estiver
                instalado ou se o modelo não puder ser carregado.
        """
        # Verificar onnxruntime-directml.
        try:
            import onnxruntime as ort
        except ImportError as e:
            raise DirectMLBackendError(
                f"onnxruntime not installed: {e}. "
                "Install with: pip install onnxruntime-directml"
            ) from e

        providers = ort.get_available_providers()
        if "DmlExecutionProvider" not in providers:
            raise DirectMLBackendError(
                "DmlExecutionProvider not available. "
                "Install onnxruntime-directml: pip install onnxruntime-directml"
            )

        # Verificar optimum.
        try:
            from optimum.onnxruntime import ORTModelForSpeechSeq2Seq
        except ImportError as e:
            raise DirectMLBackendError(
                f"optimum not installed: {e}. "
                "Install with: pip install optimum"
            ) from e

        # Verificar transformers (para processor).
        try:
            from transformers import WhisperProcessor
        except ImportError as e:
            raise DirectMLBackendError(
                f"transformers not installed: {e}. "
                "Install with: pip install transformers"
            ) from e

        logger.info(
            "DirectMLBackend: loading ONNX model=%s via optimum (device_id=%d)",
            self._onnx_model_id, self._device_id,
        )

        # Configurar provider options para DirectML.
        provider_options = [
            {
                "device_id": self._device_id,
                # DirectML não tem opção de limite de VRAM direto.
            }
        ]

        # Carregar modelo ONNX via optimum.
        # ORTModelForSpeechSeq2Seq gerencia encoder + decoder automaticamente.
        try:
            self._model = ORTModelForSpeechSeq2Seq.from_pretrained(
                self._onnx_model_id,
                provider="DmlExecutionProvider",
                provider_options=provider_options,
            )
        except Exception as e:
            raise DirectMLBackendError(
                f"failed to load ONNX model {self._onnx_model_id}: {e}. "
                f"The model will be downloaded from HuggingFace on first use. "
                f"Ensure you have internet access and disk space."
            ) from e

        # Carregar processor (tokenizer + feature extractor).
        try:
            self._processor = WhisperProcessor.from_pretrained(
                self._onnx_model_id
            )
        except Exception as e:
            raise DirectMLBackendError(
                f"failed to load WhisperProcessor: {e}"
            ) from e

        # Verificar qual provider está ativo.
        active_providers = []
        try:
            # ORTModelForSpeechSeq2Seq expõe session internamente.
            if hasattr(self._model, "encoder") and hasattr(self._model.encoder, "session"):
                active_providers = self._model.encoder.session.get_providers()
        except Exception:
            pass

        logger.info(
            "DirectMLBackend: loaded successfully "
            "(active_providers=%s, compute_type=%s)",
            active_providers or ["unknown"],
            self._actual_compute_type,
        )

        if active_providers and "DmlExecutionProvider" not in active_providers:
            self._fallback_reason = (
                f"DirectML not active (providers={active_providers}) — "
                f"using CPU"
            )
            logger.warning(
                "DirectMLBackend: DmlExecutionProvider not active! "
                "Providers: %s", active_providers
            )

        self._is_loaded = True

    # ------------------------------------------------------------------
    # Transcrição
    # ------------------------------------------------------------------

    def transcribe(
        self,
        audio: Any,
        language: str,
        beam_size: int,
        vad_filter: bool,
        chunk_length: int,
    ) -> tuple[str, str, float, tuple[Any, ...]]:
        """Transcreve áudio usando ONNX Runtime + DirectML.

        Args:
            audio: ndarray float32 [-1.0, 1.0] (16kHz mono).
            language: código ISO do idioma ("pt", "en").
            beam_size: ignorado (DirectML usa greedy decoding).
            vad_filter: ignorado (VAD não disponível no ONNX base).
            chunk_length: ignorado (fixo no modelo ONNX).

        Returns:
            (texto, idioma, avg_logprob, segmentos_brutos).
        """
        if not self._is_loaded or self._model is None:
            raise DirectMLBackendError("model not loaded — call load() first")

        try:
            import torch
            import numpy as np
        except ImportError as e:
            raise DirectMLBackendError(
                f"torch/numpy not installed: {e}"
            ) from e

        try:
            # 1. Extrair features (log-mel spectrogram) via processor.
            forced_decoder_ids = self._processor.get_decoder_prompt_ids(
                language=language, task="transcribe"
            )

            # 2. Preparar input features.
            inputs = self._processor(
                audio, sampling_rate=16000, return_tensors="pt"
            )
            input_features = inputs.input_features

            # 3. Gerar tokens via modelo ONNX.
            # max_new_tokens + len(decoder_input_ids) deve ser <= 448
            # (max_target_positions do Whisper). forced_decoder_ids para
            # language+task tipicamente adiciona 2-4 tokens ao decoder.
            # Usar margem segura: 448 - len(forced_decoder_ids) - 1.
            num_forced = len(forced_decoder_ids) if forced_decoder_ids else 0
            max_new_tokens = max(200, 448 - num_forced - 1)
            t0 = time.monotonic()
            with torch.no_grad():
                predicted_ids = self._model.generate(
                    input_features,
                    forced_decoder_ids=forced_decoder_ids,
                    max_new_tokens=max_new_tokens,
                    num_beams=1,  # greedy (DirectML não suporta beam search bem)
                    do_sample=False,
                )
            gen_ms = (time.monotonic() - t0) * 1000
            logger.debug("DirectMLBackend: generate took %.0fms", gen_ms)

            # 4. Decodificar tokens → texto.
            text = self._processor.batch_decode(
                predicted_ids, skip_special_tokens=True
            )[0].strip()

            # avg_logprob não disponível via ONNX — usar heurística.
            avg_logprob = -0.3 if text else -1.0

            return text, language, avg_logprob, ()

        except Exception as e:
            logger.error("DirectMLBackend transcribe error: %s", e)
            raise DirectMLBackendError(f"transcription failed: {e}") from e

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def unload(self) -> None:
        """Libera o modelo da memória/GPU."""
        self._model = None
        self._processor = None
        # Forçar garbage collection para liberar VRAM.
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        self._is_loaded = False
        logger.info("DirectMLBackend: model unloaded")

    def close(self) -> None:
        """Alias para unload() — compatibilidade com STTBackend Protocol."""
        self.unload()

    # ------------------------------------------------------------------
    # Propriedades (interface InferenceBackend)
    # ------------------------------------------------------------------

    @property
    def actual_device(self) -> str:
        return "directml"

    @property
    def actual_compute_type(self) -> str:
        return self._actual_compute_type

    @property
    def backend_name(self) -> str:
        return "onnx-directml"

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    @property
    def fallback_reason(self) -> str:
        return self._fallback_reason
