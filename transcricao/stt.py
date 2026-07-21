"""Speech-to-Text offline com Faster-Whisper.

Escolha de bibliotecas (justificativa técnica):
  - **faster-whisper** (CTranslate2): reimplementação otimizada do Whisper,
    4x mais rápido que openai-whisper com mesma qualidade. Suporta GPU
    (CUDA) e CPU, quantização INT8/FP16, e transcrição streaming.
    Wheels pré-compiladas para Windows (cp311-abi3), sem Visual C++.
  - **ctranslate2**: engine de inferência otimizado para Transformer models.
    Wheels cp314 para Python 3.14 no Windows.
  - **numpy**: conversão PCM bytes → float32 para faster-whisper.

Pipeline:
  1. SpeechSegment (PCM 16kHz mono 16-bit) chega do microfone/capture.py.
  2. PCM bytes → numpy float32 [-1.0, 1.0].
  3. faster-whisper transcreve com condition_on_previous_text=False.
  4. Segmentos são concatenados, avg_logprob médio calculado.
  5. avg_logprob → confidence via sigmoid (c_stt_from_logprob).
  6. STTResult retornado com texto, language, confidence, timing.

GPU → CPU fallback:
  - Se device="cuda" mas CUDA não disponível, fallback automático para CPU
    com compute_type="int8" (mais estável em CPU) e warning logado.
  - Se modelo não carrega (OOM, libs faltando), STTError.

Inicialização única:
  - Modelo carregado uma vez no __init__ e reutilizado para todas as
    transcrições. WhisperModel é thread-safe para transcrição sequencial.

Backend swapping:
  - STTBackend protocol define a interface. FasterWhisperBackend é a
    implementação padrão. Novos backends (Parakeet, etc.) podem ser
    adicionados sem mudar STT.

Limitações do Faster-Whisper (aceitáveis para o cenário):
  - Modelo "large-v3-turbo" requer download inicial (~1.5GB) do HuggingFace.
    Após download, funciona 100% offline (cache local).
  - GPU requer CUDA 12 + cuDNN 9 (libs do Purfview para Windows).
  - Sem GPU, CPU funciona mas com latência maior (~10x).
  - beam_size=1 (greedy) é mais rápido mas ligeiramente menos preciso.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from config.models import STTConfig
from core.exceptions import STTError
from microfone.capture import SpeechSegment

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SAMPLE_RATE = 16000
_BYTES_PER_SAMPLE = 2  # 16-bit
_MIN_AUDIO_MS = 100  # abaixo disso, ignora (provável ruído)
_SILENCE_CONFIDENCE = 0.0  # texto vazio → confidence 0
_NEUTRAL_CONFIDENCE = 0.5  # avg_logprob ausente → neutro

# ---------------------------------------------------------------------------
# Modelos (DTOs)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class STTResult:
    """Resultado de uma transcrição.

    Atributos:
        text: texto transcrito (lowercase, sem pontuação Whisper).
        language: código ISO do idioma detectado ("pt", "en").
        confidence: confiança da transcrição [0.0, 1.0].
            Derivada de avg_logprob via sigmoid. 0.0 = silêncio/ruído.
        processing_ms: tempo de processamento da transcrição em ms.
        audio_duration_ms: duração do áudio de entrada em ms.
        segments_raw: segmentos brutos do faster-whisper (para debug).
    """

    text: str
    language: str
    confidence: float
    processing_ms: int
    audio_duration_ms: int
    segments_raw: tuple[Any, ...] = ()


@dataclass
class STTMetrics:
    """Métricas acumuladas de transcrição para monitoramento.

    Acumuladas desde a inicialização ou último reset.
    """

    total_transcriptions: int = 0
    successful: int = 0
    failed: int = 0
    empty_text: int = 0
    total_audio_ms: int = 0
    total_processing_ms: int = 0
    total_confidence: float = 0.0
    gpu_fallback: bool = False
    model_loaded: bool = False
    model_load_ms: int = 0
    errors: int = 0
    # Sprint 17.3 — Janela deslizante das últimas N transcrições.
    recent_processing_ms: list[int] = field(default_factory=list)
    recent_audio_ms: list[int] = field(default_factory=list)
    recent_confidence: list[float] = field(default_factory=list)
    recent_rtf: list[float] = field(default_factory=list)
    _window_size: int = 20

    @property
    def avg_confidence(self) -> float:
        """Confiança média das transcrições bem-sucedidas."""
        if self.successful == 0:
            return 0.0
        return self.total_confidence / self.successful

    @property
    def avg_processing_ms(self) -> float:
        """Tempo médio de processamento em ms."""
        if self.successful == 0:
            return 0.0
        return self.total_processing_ms / self.successful

    @property
    def rtf(self) -> float:
        """Real-Time Factor: processing_ms / audio_ms. < 1.0 = mais rápido que tempo real."""
        if self.total_audio_ms == 0:
            return 0.0
        return self.total_processing_ms / self.total_audio_ms

    # ------------------------------------------------------------------
    # Sprint 17.3 — Média móvel (últimas 20 transcrições).
    # ------------------------------------------------------------------

    def _prune(self) -> None:
        """Mantém apenas os últimos _window_size elementos."""
        if len(self.recent_processing_ms) > self._window_size:
            self.recent_processing_ms = self.recent_processing_ms[-self._window_size:]
        if len(self.recent_audio_ms) > self._window_size:
            self.recent_audio_ms = self.recent_audio_ms[-self._window_size:]
        if len(self.recent_confidence) > self._window_size:
            self.recent_confidence = self.recent_confidence[-self._window_size:]
        if len(self.recent_rtf) > self._window_size:
            self.recent_rtf = self.recent_rtf[-self._window_size:]

    def record_recent(
        self,
        processing_ms: int,
        audio_ms: int,
        confidence: float,
    ) -> None:
        """Registra métricas de uma transcrição na janela deslizante."""
        self.recent_processing_ms.append(processing_ms)
        self.recent_audio_ms.append(audio_ms)
        self.recent_confidence.append(confidence)
        rtf = processing_ms / audio_ms if audio_ms > 0 else 0.0
        self.recent_rtf.append(rtf)
        self._prune()

    @property
    def moving_avg_processing_ms(self) -> float:
        """Média móvel do tempo de processamento (últimas 20)."""
        if not self.recent_processing_ms:
            return 0.0
        return sum(self.recent_processing_ms) / len(self.recent_processing_ms)

    @property
    def moving_avg_rtf(self) -> float:
        """Média móvel do RTF (últimas 20)."""
        if not self.recent_rtf:
            return 0.0
        return sum(self.recent_rtf) / len(self.recent_rtf)

    @property
    def moving_avg_confidence(self) -> float:
        """Média móvel da confiança (últimas 20)."""
        if not self.recent_confidence:
            return 0.0
        return sum(self.recent_confidence) / len(self.recent_confidence)


# ---------------------------------------------------------------------------
# Backend Protocol (para futuras trocas de backend)
# ---------------------------------------------------------------------------


@runtime_checkable
class STTBackend(Protocol):
    """Protocolo para backends de STT.

    Permite adicionar novos backends (Parakeet, Whisper.cpp, etc.)
    sem mudar a classe STT.
    """

    def load(self) -> None:
        """Carrega o modelo na memória/GPU. Chamado uma vez na inicialização."""
        ...

    def transcribe(
        self,
        audio: Any,  # numpy.ndarray float32
        language: str,
        beam_size: int,
        vad_filter: bool,
        chunk_length: int,
    ) -> tuple[str, str, float, tuple[Any, ...]]:
        """Transcreve áudio.

        Args:
            audio: numpy array float32 [-1.0, 1.0], 16kHz mono.
            language: código ISO do idioma ("pt").
            beam_size: beam size para decoding.
            vad_filter: se True, ativa VAD interno.
            chunk_length: duração do chunk em segundos.

        Returns:
            Tupla (texto, idioma_detectado, avg_logprob, segmentos_brutos).
        """
        ...

    def close(self) -> None:
        """Libera recursos do modelo."""
        ...


# ---------------------------------------------------------------------------
# Faster-Whisper Backend
# ---------------------------------------------------------------------------


class FasterWhisperBackend:
    """Backend Faster-Whisper (CTranslate2).

    Carrega WhisperModel uma vez e reutiliza para todas as transcrições.
    Fallback automático GPU → CPU se CUDA não disponível.
    """

    def __init__(self, config: STTConfig) -> None:
        self._config = config
        self._model: Any = None  # faster_whisper.WhisperModel
        self._actual_device: str = config.device
        self._actual_compute_type: str = config.compute_type
        self._actual_cpu_threads: int = config.cpu_threads
        self._fallback_reason: str = ""

    def load(self) -> None:
        """Carrega o modelo WhisperModel.

        Fallback GPU → CPU:
        - Se device="cuda" mas CUDA indisponível, usa CPU com int8.
        - Se modelo não carrega, STTError.
        """
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise STTError(
                f"faster-whisper not installed: {e}. "
                "Install with: pip install faster-whisper"
            ) from e

        device = self._config.device
        compute_type = self._config.compute_type
        cpu_threads = self._config.cpu_threads

        # Resolver "auto" para device concreto.
        if device == "auto":
            cuda_available = self._check_cuda()
            device = "cuda" if cuda_available else "cpu"
            self._actual_device = device
            if device == "cpu":
                compute_type = "int8"
                self._actual_compute_type = "int8"
            logger.info(
                "STT device='auto' resolved to '%s' (cuda_available=%s)",
                device, cuda_available,
            )

        # Tentar GPU se configurado
        if device == "cuda":
            cuda_available = self._check_cuda()
            if not cuda_available:
                logger.warning(
                    "CUDA not available — falling back to CPU (int8). "
                    "GPU is recommended for low-latency transcription."
                )
                self._fallback_reason = (
                    "CUDA not available — falling back to CPU (int8)"
                )
                device = "cpu"
                compute_type = "int8"
                self._actual_device = "cpu"
                self._actual_compute_type = "int8"

        # Resolver cpu_threads=0 → default do sistema.
        if cpu_threads <= 0:
            try:
                import os as _os
                cpu_threads = _os.cpu_count() or 0
            except Exception:
                cpu_threads = 0
        self._actual_cpu_threads = cpu_threads

        # Construir kwargs para WhisperModel.
        kwargs: dict[str, Any] = {
            "device": device,
            "compute_type": compute_type,
        }
        if cpu_threads > 0:
            kwargs["cpu_threads"] = cpu_threads

        try:
            logger.info(
                "Loading Whisper model: model=%s, device=%s, compute_type=%s, cpu_threads=%s",
                self._config.model,
                device,
                compute_type,
                cpu_threads if cpu_threads > 0 else "default",
            )
            self._model = WhisperModel(
                self._config.model,
                **kwargs,
            )
            logger.info(
                "Whisper model loaded successfully (device=%s, compute_type=%s, cpu_threads=%s)",
                device,
                compute_type,
                cpu_threads if cpu_threads > 0 else "default",
            )
        except Exception as e:
            # Se falhou na GPU, tentar CPU antes de desistir
            if device == "cuda":
                logger.warning(
                    "GPU load failed: %s — falling back to CPU (int8)", e
                )
                self._fallback_reason = (
                    f"GPU load failed: {e} — falling back to CPU (int8)"
                )
                try:
                    fallback_kwargs: dict[str, Any] = {
                        "device": "cpu",
                        "compute_type": "int8",
                    }
                    if cpu_threads > 0:
                        fallback_kwargs["cpu_threads"] = cpu_threads
                    self._model = WhisperModel(
                        self._config.model,
                        **fallback_kwargs,
                    )
                    self._actual_device = "cpu"
                    self._actual_compute_type = "int8"
                    logger.info(
                        "Whisper model loaded on CPU fallback (int8, cpu_threads=%s)",
                        cpu_threads if cpu_threads > 0 else "default",
                    )
                    return
                except Exception as e2:
                    raise STTError(
                        f"failed to load Whisper model on both GPU and CPU: "
                        f"GPU error={e}, CPU error={e2}"
                    ) from e2
            raise STTError(f"failed to load Whisper model: {e}") from e

    def _check_cuda(self) -> bool:
        """Verifica se CUDA está disponível para ctranslate2.

        Delega a detecção para ``core.hardware.HardwareDetector`` para
        evitar duplicação de lógica de infraestrutura.
        """
        from core.hardware import HardwareDetector

        profile = HardwareDetector.detect()
        return profile.has_cuda

    def transcribe(
        self,
        audio: Any,
        language: str,
        beam_size: int,
        vad_filter: bool,
        chunk_length: int,
    ) -> tuple[str, str, float, tuple[Any, ...]]:
        """Transcreve áudio com faster-whisper.

        Returns:
            (texto, idioma, avg_logprob, segmentos_brutos)
        """
        if self._model is None:
            raise STTError("model not loaded — call load() first")

        try:
            segments_iter, info = self._model.transcribe(
                audio,
                language=language,
                beam_size=beam_size,
                vad_filter=vad_filter,
                chunk_length=chunk_length,
                condition_on_previous_text=False,
            )
            # Consumir o iterador (faster-whisper é lazy)
            segments = list(segments_iter)
        except Exception as e:
            raise STTError(f"transcription failed: {e}") from e

        # Concatenar texto
        text = " ".join(seg.text.strip() for seg in segments).strip()

        # Calcular avg_logprob médio
        logprobs = [seg.avg_logprob for seg in segments if seg.avg_logprob is not None]
        avg_logprob = sum(logprobs) / len(logprobs) if logprobs else 0.0

        detected_lang = info.language or language

        return text, detected_lang, avg_logprob, tuple(segments)

    def close(self) -> None:
        """Libera o modelo da memória."""
        self._model = None
        logger.info("Whisper model unloaded")

    @property
    def actual_device(self) -> str:
        """Device efetivamente usado (após fallback)."""
        return self._actual_device

    @property
    def actual_compute_type(self) -> str:
        """Compute type efetivamente usado (após fallback)."""
        return self._actual_compute_type

    @property
    def actual_cpu_threads(self) -> int:
        """Threads CPU efetivamente usadas (0 = default faster-whisper)."""
        return self._actual_cpu_threads

    @property
    def fallback_reason(self) -> str:
        """Motivo do fallback (vazio se não houve fallback)."""
        return self._fallback_reason


# ---------------------------------------------------------------------------
# STT (classe principal)
# ---------------------------------------------------------------------------


class STT:
    """Speech-to-Text offline com Faster-Whisper.

    Carrega o modelo uma vez no __init__ e reutiliza para todas as
    transcrições. Thread-safe para uso sequencial.

    Args:
        config: STTConfig com configurações do modelo.
        backend: backend STT (criado internamente se omitido).

    Example:
        >>> stt = STT(config)
        >>> result = stt.transcribe(segment)
        >>> print(result.text)
        "vamos abrir em joao capitulo tres versiculo dezesseis"
    """

    def __init__(
        self,
        config: STTConfig,
        backend: STTBackend | None = None,
    ) -> None:
        self._config = config
        self._metrics = STTMetrics()

        # Criar ou usar backend fornecido
        if backend is not None:
            self._backend = backend
        else:
            self._backend = STT._create_backend(config)

        # Sprint 19.1 — Envolver backend GPU com BackendFallbackManager.
        # Backends GPU (DirectML, CUDA, ROCm) são envolvidos para permitir
        # fallback automático para CPU após N falhas consecutivas.
        # Backends CPU não são envolvidos (não há para onde cair).
        if backend is None and STT._is_gpu_backend(self._backend):
            self._backend = STT._wrap_with_fallback(self._backend, config)

        # Carregar modelo
        load_start = time.monotonic()
        self._backend.load()
        self._metrics.model_load_ms = int((time.monotonic() - load_start) * 1000)
        self._metrics.model_loaded = True

        # Verificar se houve fallback GPU → CPU
        if isinstance(self._backend, FasterWhisperBackend):
            self._metrics.gpu_fallback = (
                self._backend.actual_device != config.device
            )

    @staticmethod
    def _is_gpu_backend(backend: STTBackend) -> bool:
        """Verifica se um backend é GPU (requer fallback)."""
        backend_name = getattr(backend, "backend_name", "")
        device = getattr(backend, "actual_device", "cpu")
        return (
            "directml" in backend_name
            or "cuda" in backend_name
            or "rocm" in backend_name
            or device in ("directml", "cuda", "rocm")
        )

    @staticmethod
    def _wrap_with_fallback(
        gpu_backend: STTBackend, config: STTConfig
    ) -> STTBackend:
        """Envolve um backend GPU com BackendFallbackManager.

        Cria uma factory para o CPU backend que será usado se fallback
        for disparado. A factory cria um FasterWhisperBackend com
        compute_type=int8 (estável em CPU).
        """
        from transcricao.backend_fallback import BackendFallbackManager
        from dataclasses import replace

        # Factory: cria CPU backend (FasterWhisperBackend com int8).
        def cpu_factory() -> STTBackend:
            cpu_config = replace(
                config,
                device="cpu",
                compute_type="int8",
                backend="faster-whisper",
            )
            return FasterWhisperBackend(cpu_config)

        return BackendFallbackManager(
            gpu_backend=gpu_backend,
            cpu_backend_factory=cpu_factory,
            max_consecutive_failures=3,
        )

    @staticmethod
    def _create_backend(config: STTConfig) -> STTBackend:
        """Cria o backend apropriado com base na config e hardware.

        Sprint 19.1 — GPU Runtime & Hardware Acceleration:
          Usa BackendSelector para escolher entre CPU/CUDA/DirectML/ROCm.
          Mantém compatibilidade com config.backend="faster-whisper"
          (legacy) mapeando para CPU/CUDA conforme device.

        Args:
            config: STTConfig com backend, device, compute_type.

        Returns:
            Instância de STTBackend (FasterWhisperBackend ou DirectMLBackend).
        """
        # Compatibilidade legacy: "faster-whisper" significa CPU ou CUDA.
        # Sprint 19.1: novos valores "auto", "directml", "rocm" também.
        backend_str = config.backend.lower()

        if backend_str == "faster-whisper":
            # Legacy: decidir entre CPU/CUDA pelo device.
            if config.device == "cuda":
                backend_str = "cuda"
            else:
                backend_str = "cpu"

        # Usar BackendSelector para validar e resolver compute_type.
        from transcricao.backend_selector import BackendSelector, BackendSelectionError
        try:
            info = BackendSelector.select(
                requested_backend=backend_str,
                requested_compute_type=config.compute_type,
            )
        except BackendSelectionError as e:
            raise STTError(f"backend selection failed: {e}") from e

        logger.info(
            "STT: backend selected = %s (device=%s, compute=%s, reason=%s)",
            info.backend_type, info.device, info.compute_type, info.reason,
        )

        # Instanciar backend concreto.
        if info.backend_type == "directml":
            from transcricao.directml_backend import DirectMLBackend
            return DirectMLBackend(
                model_name=config.model,
                compute_type=info.compute_type,
                device_id=0,
            )

        # CPU e CUDA usam FasterWhisperBackend (ctranslate2).
        # Criar STTConfig ajustada com device/compute_type resolvidos.
        from dataclasses import replace
        resolved_config = replace(
            config,
            device=info.device if info.backend_type != "cpu" else "cpu",
            compute_type=info.compute_type,
        )
        return FasterWhisperBackend(resolved_config)

    def transcribe(self, segment: SpeechSegment) -> STTResult:
        """Transcreve um SpeechSegment em texto.

        Args:
            segment: SpeechSegment com PCM 16kHz mono 16-bit.

        Returns:
            STTResult com texto, language, confidence, timing.

        Raises:
            STTError: se a transcrição falhar.
        """
        audio_duration_ms = segment.duration_ms
        self._metrics.total_transcriptions += 1
        self._metrics.total_audio_ms += audio_duration_ms

        # Áudio muito curto → ignora (provável ruído)
        if audio_duration_ms < _MIN_AUDIO_MS:
            logger.debug(
                "Audio too short (%d ms < %d ms) — skipping",
                audio_duration_ms,
                _MIN_AUDIO_MS,
            )
            self._metrics.empty_text += 1
            return STTResult(
                text="",
                language=self._config.language,
                confidence=_SILENCE_CONFIDENCE,
                processing_ms=0,
                audio_duration_ms=audio_duration_ms,
            )

        # Converter PCM bytes → numpy float32
        audio = self._pcm_to_float32(segment.audio)

        # Transcrever
        proc_start = time.monotonic()
        try:
            text, language, avg_logprob, segments_raw = self._backend.transcribe(
                audio=audio,
                language=self._config.language,
                beam_size=self._config.beam_size,
                vad_filter=self._config.vad_filter,
                chunk_length=self._config.chunk_length_s,
            )
        except STTError:
            self._metrics.failed += 1
            self._metrics.errors += 1
            raise
        processing_ms = int((time.monotonic() - proc_start) * 1000)

        self._metrics.total_processing_ms += processing_ms

        # Texto vazio → confidence 0
        if not text:
            self._metrics.empty_text += 1
            logger.debug("Empty transcription (audio_duration=%d ms)", audio_duration_ms)
            return STTResult(
                text="",
                language=language,
                confidence=_SILENCE_CONFIDENCE,
                processing_ms=processing_ms,
                audio_duration_ms=audio_duration_ms,
                segments_raw=segments_raw,
            )

        # Calcular confidence
        confidence = self.c_stt_from_logprob(avg_logprob)

        self._metrics.successful += 1
        self._metrics.total_confidence += confidence

        # Sprint 17.3 — Registrar na janela deslizante.
        self._metrics.record_recent(processing_ms, audio_duration_ms, confidence)

        rtf = processing_ms / audio_duration_ms if audio_duration_ms > 0 else 0
        logger.info(
            "STT: text=%r, confidence=%.3f, processing_ms=%d, audio_ms=%d, rtf=%.2f, "
            "moving_avg_ms=%.0f, moving_avg_rtf=%.2f",
            text[:80] + ("..." if len(text) > 80 else ""),
            confidence,
            processing_ms,
            audio_duration_ms,
            rtf,
            self._metrics.moving_avg_processing_ms,
            self._metrics.moving_avg_rtf,
        )

        return STTResult(
            text=text,
            language=language,
            confidence=confidence,
            processing_ms=processing_ms,
            audio_duration_ms=audio_duration_ms,
            segments_raw=segments_raw,
        )

    def transcribe_pcm(self, pcm: bytes, sample_rate: int = 16000) -> STTResult:
        """Transcreve PCM bytes diretamente (sem SpeechSegment).

        Método de conveniência para testes e uso direto.

        Args:
            pcm: PCM 16-bit signed little-endian.
            sample_rate: taxa de amostragem (deve ser 16000).

        Returns:
            STTResult.
        """
        if sample_rate != _SAMPLE_RATE:
            raise STTError(
                f"sample_rate must be {_SAMPLE_RATE}, got {sample_rate}"
            )

        duration_ms = int(len(pcm) / (_BYTES_PER_SAMPLE * sample_rate) * 1000)
        segment = SpeechSegment(
            audio=pcm,
            start_time=time.time(),
            end_time=time.time(),
            duration_ms=duration_ms,
            chunk_count=0,
        )
        return self.transcribe(segment)

    def c_stt_from_logprob(self, avg_logprob: float) -> float:
        """Converte avg_logprob do Whisper em confidence [0.0, 1.0].

        Fórmula: sigmoid(avg_logprob * 2)

        Mapeamento:
        - avg_logprob = 0.0  → confidence = 0.88 (áudio muito claro)
        - avg_logprob = -0.5 → confidence = 0.73
        - avg_logprob = -1.0 → confidence = 0.12
        - avg_logprob = -2.0 → confidence = 0.02

        Calibrar empiricamente com áudio real do pregador.

        Args:
            avg_logprob: log-probabilidade média do Whisper (tipicamente -1..0).

        Returns:
            Confidence [0.0, 1.0].
        """
        if avg_logprob is None or math.isnan(avg_logprob):
            logger.warning("avg_logprob is None/NaN — using neutral confidence")
            return _NEUTRAL_CONFIDENCE
        confidence = 1.0 / (1.0 + math.exp(-avg_logprob * 2))
        return max(0.0, min(1.0, confidence))

    def close(self) -> None:
        """Libera o modelo da memória."""
        self._backend.close()
        self._metrics.model_loaded = False
        logger.info(
            "STT closed: transcriptions=%d, successful=%d, avg_confidence=%.3f, rtf=%.2f",
            self._metrics.total_transcriptions,
            self._metrics.successful,
            self._metrics.avg_confidence,
            self._metrics.rtf,
        )

    @property
    def metrics(self) -> STTMetrics:
        """Métricas acumuladas de transcrição."""
        return self._metrics

    @property
    def is_loaded(self) -> bool:
        """True se o modelo está carregado."""
        return self._metrics.model_loaded

    @property
    def backend(self) -> STTBackend:
        """Backend STT em uso."""
        return self._backend

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    @staticmethod
    def _pcm_to_float32(pcm: bytes) -> Any:
        """Converte PCM 16-bit signed LE → numpy float32 [-1.0, 1.0].

        Args:
            pcm: bytes PCM 16-bit mono little-endian.

        Returns:
            numpy.ndarray float32 normalizado [-1.0, 1.0].
        """
        import numpy as np

        if len(pcm) == 0:
            return np.array([], dtype=np.float32)
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        # Normalizar para [-1.0, 1.0]
        samples /= 32768.0
        return samples
