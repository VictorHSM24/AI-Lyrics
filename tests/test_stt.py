"""Testes unitários do módulo transcricao/stt.py.

Estratégia:
  - c_stt_from_logprob é lógica pura — testável sem modelo.
  - _pcm_to_float32 é lógica pura — testável sem modelo.
  - STT.transcribe usa MockBackend (não requer faster-whisper real).
  - FasterWhisperBackend.load/transcribe testado com mock de WhisperModel.
  - Não requer GPU nem download de modelo.
"""

from __future__ import annotations

import math
import time
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from config.models import STTConfig, VadConfig
from core.exceptions import STTError
from microfone.capture import SpeechSegment
from transcricao.stt import (
    FasterWhisperBackend,
    STT,
    STTMetrics,
    STTResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stt_config(**overrides) -> STTConfig:
    defaults = {
        "model": "large-v3-turbo",
        "device": "cpu",
        "compute_type": "int8",
        "language": "pt",
        "chunk_length_s": 30,
        "vad": VadConfig(mode="silero", min_speech_ms=250, pause_threshold_ms=600),
        "backend": "faster-whisper",
        "beam_size": 1,
        "vad_filter": False,
    }
    defaults.update(overrides)
    return STTConfig(**defaults)


def _make_pcm(duration_ms: int = 1000, sample_rate: int = 16000) -> bytes:
    """Cria PCM 16-bit mono de duração especificada (silêncio)."""
    n_samples = int(sample_rate * duration_ms / 1000)
    return b"\x00\x00" * n_samples


def _make_speech_pcm(duration_ms: int = 1000, sample_rate: int = 16000) -> bytes:
    """Cria PCM 16-bit mono com senoide (simula fala)."""
    t = np.linspace(0, duration_ms / 1000, int(sample_rate * duration_ms / 1000), endpoint=False)
    samples = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    return samples.tobytes()


def _make_segment(duration_ms: int = 1000, audio: bytes | None = None) -> SpeechSegment:
    if audio is None:
        audio = _make_pcm(duration_ms)
    return SpeechSegment(
        audio=audio,
        start_time=time.time(),
        end_time=time.time() + duration_ms / 1000,
        duration_ms=duration_ms,
        chunk_count=duration_ms // 30,
    )


class MockSegment:
    """Mock de faster_whisper.transcribe.Segment."""

    def __init__(self, text: str, avg_logprob: float = -0.3) -> None:
        self.text = text
        self.avg_logprob = avg_logprob
        self.start = 0.0
        self.end = 1.0
        self.id = 0
        self.tokens = []
        self.compression_ratio = 1.0
        self.no_speech_prob = 0.1
        self.words = None
        self.temperature = 0.0
        self.seek = 0


class MockTranscriptionInfo:
    """Mock de faster_whisper.transcribe.TranscriptionInfo."""

    def __init__(self, language: str = "pt") -> None:
        self.language = language
        self.language_probability = 0.95
        self.duration = 1.0
        self.duration_after_vad = 1.0
        self.all_language_probs = None
        self.transcription_options = None
        self.vad_options = None


class MockBackend:
    """Mock de STTBackend para testes sem faster-whisper."""

    def __init__(
        self,
        text: str = "vamos abrir em joao tres dezesseis",
        language: str = "pt",
        avg_logprob: float = -0.3,
    ) -> None:
        self._text = text
        self._language = language
        self._avg_logprob = avg_logprob
        self.loaded = False
        self.closed = False
        self.transcribe_calls: list[dict] = []

    def load(self) -> None:
        self.loaded = True

    def transcribe(
        self,
        audio: Any,
        language: str,
        beam_size: int,
        vad_filter: bool,
        chunk_length: int,
    ) -> tuple[str, str, float, tuple[Any, ...]]:
        self.transcribe_calls.append({
            "audio_len": len(audio) if hasattr(audio, "__len__") else 0,
            "language": language,
            "beam_size": beam_size,
            "vad_filter": vad_filter,
            "chunk_length": chunk_length,
        })
        seg = MockSegment(text=self._text, avg_logprob=self._avg_logprob)
        return self._text, self._language, self._avg_logprob, (seg,)

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# STTResult
# ---------------------------------------------------------------------------

class TestSTTResult:
    def test_construction(self) -> None:
        r = STTResult(
            text="joao tres dezesseis",
            language="pt",
            confidence=0.92,
            processing_ms=150,
            audio_duration_ms=2000,
        )
        assert r.text == "joao tres dezesseis"
        assert r.language == "pt"
        assert r.confidence == 0.92
        assert r.processing_ms == 150
        assert r.audio_duration_ms == 2000

    def test_frozen(self) -> None:
        r = STTResult("", "pt", 0.0, 0, 0)
        with pytest.raises((AttributeError, Exception)):
            r.text = "other"  # type: ignore[misc]

    def test_default_segments_raw(self) -> None:
        r = STTResult("text", "pt", 0.9, 100, 1000)
        assert r.segments_raw == ()


# ---------------------------------------------------------------------------
# STTMetrics
# ---------------------------------------------------------------------------

class TestSTTMetrics:
    def test_defaults(self) -> None:
        m = STTMetrics()
        assert m.total_transcriptions == 0
        assert m.successful == 0
        assert m.avg_confidence == 0.0
        assert m.rtf == 0.0

    def test_avg_confidence(self) -> None:
        m = STTMetrics()
        m.successful = 3
        m.total_confidence = 2.7
        assert abs(m.avg_confidence - 0.9) < 0.001

    def test_avg_processing_ms(self) -> None:
        m = STTMetrics()
        m.successful = 2
        m.total_processing_ms = 300
        assert m.avg_processing_ms == 150.0

    def test_rtf(self) -> None:
        m = STTMetrics()
        m.total_audio_ms = 10000
        m.total_processing_ms = 1000
        assert m.rtf == 0.1

    def test_mutable(self) -> None:
        m = STTMetrics()
        m.total_transcriptions = 5
        m.successful = 3
        assert m.total_transcriptions == 5


# ---------------------------------------------------------------------------
# c_stt_from_logprob — lógica pura
# ---------------------------------------------------------------------------

class TestConfidenceFromLogprob:
    def test_zero_logprob(self) -> None:
        """logprob=0 → confidence alta (~0.88)."""
        stt = _make_stt_with_mock()
        c = stt.c_stt_from_logprob(0.0)
        expected = 1.0 / (1.0 + math.exp(0))  # sigmoid(0) = 0.5... wait
        # sigmoid(0 * 2) = sigmoid(0) = 0.5
        assert abs(c - 0.5) < 0.01

    def test_positive_logprob(self) -> None:
        """logprob positivo → confidence > 0.5."""
        stt = _make_stt_with_mock()
        c = stt.c_stt_from_logprob(0.5)
        assert c > 0.5
        assert c < 1.0

    def test_negative_logprob(self) -> None:
        """logprob negativo → confidence < 0.5."""
        stt = _make_stt_with_mock()
        c = stt.c_stt_from_logprob(-1.0)
        assert c < 0.5
        assert c > 0.0

    def test_very_negative_logprob(self) -> None:
        """logprob muito negativo → confidence ~0."""
        stt = _make_stt_with_mock()
        c = stt.c_stt_from_logprob(-5.0)
        assert c < 0.01

    def test_none_logprob(self) -> None:
        """logprob None → confidence neutra (0.5)."""
        stt = _make_stt_with_mock()
        c = stt.c_stt_from_logprob(None)  # type: ignore[arg-type]
        assert c == 0.5

    def test_nan_logprob(self) -> None:
        """logprob NaN → confidence neutra (0.5)."""
        stt = _make_stt_with_mock()
        c = stt.c_stt_from_logprob(float("nan"))
        assert c == 0.5

    def test_confidence_bounded(self) -> None:
        """Confidence deve estar em [0, 1]."""
        stt = _make_stt_with_mock()
        for lp in [-10, -5, -1, 0, 1, 5, 10]:
            c = stt.c_stt_from_logprob(float(lp))
            assert 0.0 <= c <= 1.0


def _make_stt_with_mock() -> STT:
    """Cria STT com MockBackend (não carrega modelo real)."""
    config = _stt_config()
    backend = MockBackend()
    return STT(config, backend=backend)


# ---------------------------------------------------------------------------
# _pcm_to_float32 — lógica pura
# ---------------------------------------------------------------------------

class TestPcmToFloat32:
    def test_silence(self) -> None:
        """PCM de silêncio → array de zeros."""
        pcm = b"\x00\x00" * 100
        audio = STT._pcm_to_float32(pcm)
        assert len(audio) == 100
        assert np.all(audio == 0.0)
        assert audio.dtype == np.float32

    def test_max_amplitude(self) -> None:
        """PCM com amplitude máxima → float32 ~1.0."""
        pcm = b"\xff\x7f" * 10  # 32767 = 0x7FFF
        audio = STT._pcm_to_float32(pcm)
        assert np.allclose(audio, 32767 / 32768.0)

    def test_min_amplitude(self) -> None:
        """PCM com amplitude mínima → float32 ~-1.0."""
        pcm = b"\x00\x80" * 10  # -32768 = 0x8000
        audio = STT._pcm_to_float32(pcm)
        assert np.allclose(audio, -32768 / 32768.0)

    def test_empty(self) -> None:
        """PCM vazio → array vazio."""
        audio = STT._pcm_to_float32(b"")
        assert len(audio) == 0

    def test_normalization_range(self) -> None:
        """Todos os valores devem estar em [-1.0, 1.0]."""
        import struct
        # Gerar PCM com valores aleatórios
        samples = np.random.randint(-32768, 32767, 500).astype(np.int16)
        pcm = samples.tobytes()
        audio = STT._pcm_to_float32(pcm)
        assert np.all(audio >= -1.0)
        assert np.all(audio <= 1.0)


# ---------------------------------------------------------------------------
# STT.transcribe — com MockBackend
# ---------------------------------------------------------------------------

class TestSTTTranscribe:
    def test_successful_transcription(self) -> None:
        config = _stt_config()
        backend = MockBackend(text="joao tres dezesseis", avg_logprob=-0.2)
        stt = STT(config, backend=backend)

        segment = _make_segment(duration_ms=2000, audio=_make_speech_pcm(2000))
        result = stt.transcribe(segment)

        assert result.text == "joao tres dezesseis"
        assert result.language == "pt"
        assert 0.0 < result.confidence <= 1.0
        assert result.processing_ms >= 0
        assert result.audio_duration_ms == 2000
        assert len(result.segments_raw) > 0

    def test_empty_text(self) -> None:
        """Texto vazio → confidence 0."""
        config = _stt_config()
        backend = MockBackend(text="", avg_logprob=-2.0)
        stt = STT(config, backend=backend)

        segment = _make_segment(duration_ms=1000)
        result = stt.transcribe(segment)

        assert result.text == ""
        assert result.confidence == 0.0

    def test_short_audio_skipped(self) -> None:
        """Áudio < 100ms → skip com confidence 0."""
        config = _stt_config()
        backend = MockBackend()
        stt = STT(config, backend=backend)

        segment = _make_segment(duration_ms=50)
        result = stt.transcribe(segment)

        assert result.text == ""
        assert result.confidence == 0.0
        assert len(backend.transcribe_calls) == 0  # backend não chamado

    def test_metrics_updated(self) -> None:
        config = _stt_config()
        backend = MockBackend(text="teste", avg_logprob=-0.3)
        stt = STT(config, backend=backend)

        segment = _make_segment(duration_ms=1000, audio=_make_speech_pcm(1000))
        stt.transcribe(segment)
        stt.transcribe(segment)

        assert stt.metrics.total_transcriptions == 2
        assert stt.metrics.successful == 2
        assert stt.metrics.total_audio_ms == 2000
        assert stt.metrics.total_processing_ms >= 0

    def test_transcribe_pcm_convenience(self) -> None:
        config = _stt_config()
        backend = MockBackend(text="teste direto")
        stt = STT(config, backend=backend)

        pcm = _make_speech_pcm(1500)
        result = stt.transcribe_pcm(pcm)

        assert result.text == "teste direto"
        assert result.audio_duration_ms == 1500

    def test_transcribe_pcm_wrong_sample_rate(self) -> None:
        config = _stt_config()
        backend = MockBackend()
        stt = STT(config, backend=backend)

        with pytest.raises(STTError, match="sample_rate must be 16000"):
            stt.transcribe_pcm(b"\x00" * 100, sample_rate=8000)

    def test_backend_receives_correct_params(self) -> None:
        config = _stt_config(beam_size=5, vad_filter=True, chunk_length_s=15)
        backend = MockBackend()
        stt = STT(config, backend=backend)

        segment = _make_segment(duration_ms=1000, audio=_make_speech_pcm(1000))
        stt.transcribe(segment)

        assert len(backend.transcribe_calls) == 1
        call = backend.transcribe_calls[0]
        assert call["language"] == "pt"
        assert call["beam_size"] == 5
        assert call["vad_filter"] is True
        assert call["chunk_length"] == 15


# ---------------------------------------------------------------------------
# STT — lifecycle
# ---------------------------------------------------------------------------

class TestSTTLifecycle:
    def test_init_loads_model(self) -> None:
        config = _stt_config()
        backend = MockBackend()
        stt = STT(config, backend=backend)

        assert backend.loaded is True
        assert stt.is_loaded is True
        assert stt.metrics.model_loaded is True

    def test_close_unloads(self) -> None:
        config = _stt_config()
        backend = MockBackend()
        stt = STT(config, backend=backend)

        stt.close()
        assert backend.closed is True
        assert stt.is_loaded is False

    def test_unsupported_backend(self) -> None:
        config = _stt_config(backend="unknown")
        with pytest.raises(STTError, match="unsupported STT backend"):
            STT(config)

    def test_transcribe_error_increments_failures(self) -> None:
        config = _stt_config()

        class ErrorBackend(MockBackend):
            def transcribe(self, **kwargs):
                raise STTError("transcription failed")

        stt = STT(config, backend=ErrorBackend())

        segment = _make_segment(duration_ms=1000, audio=_make_speech_pcm(1000))
        with pytest.raises(STTError):
            stt.transcribe(segment)

        assert stt.metrics.failed == 1
        assert stt.metrics.errors == 1


# ---------------------------------------------------------------------------
# FasterWhisperBackend — com mock de WhisperModel
# ---------------------------------------------------------------------------

class TestFasterWhisperBackend:
    def test_load_cpu(self) -> None:
        config = _stt_config(device="cpu", compute_type="int8")
        backend = FasterWhisperBackend(config)

        with patch("faster_whisper.WhisperModel") as mock_cls:
            backend.load()
            mock_cls.assert_called_once_with(
                "large-v3-turbo",
                device="cpu",
                compute_type="int8",
            )
        assert backend.actual_device == "cpu"

    def test_load_cuda_fallback_to_cpu(self) -> None:
        """CUDA indisponível → fallback para CPU int8."""
        config = _stt_config(device="cuda", compute_type="float16")
        backend = FasterWhisperBackend(config)

        with patch("faster_whisper.WhisperModel") as mock_cls:
            with patch.object(backend, "_check_cuda", return_value=False):
                backend.load()
                mock_cls.assert_called_once_with(
                    "large-v3-turbo",
                    device="cpu",
                    compute_type="int8",
                )
        assert backend.actual_device == "cpu"
        assert backend.actual_compute_type == "int8"

    def test_load_cuda_gpu_error_fallback(self) -> None:
        """Erro ao carregar na GPU → fallback para CPU."""
        config = _stt_config(device="cuda", compute_type="float16")
        backend = FasterWhisperBackend(config)

        mock_model = MagicMock()

        def mock_init(model, device, compute_type):
            if device == "cuda":
                raise RuntimeError("CUDA OOM")
            return mock_model

        with patch("faster_whisper.WhisperModel", side_effect=mock_init):
            with patch.object(backend, "_check_cuda", return_value=True):
                backend.load()

        assert backend.actual_device == "cpu"
        assert backend.actual_compute_type == "int8"

    def test_load_complete_failure(self) -> None:
        """Falha em GPU e CPU → STTError."""
        config = _stt_config(device="cuda", compute_type="float16")
        backend = FasterWhisperBackend(config)

        with patch("faster_whisper.WhisperModel", side_effect=RuntimeError("fail")):
            with patch.object(backend, "_check_cuda", return_value=True):
                with pytest.raises(STTError, match="failed to load"):
                    backend.load()

    def test_load_import_error(self) -> None:
        config = _stt_config()
        backend = FasterWhisperBackend(config)

        with patch.dict("sys.modules", {"faster_whisper": None}):
            with pytest.raises(STTError, match="faster-whisper not installed"):
                backend.load()

    def test_transcribe_not_loaded(self) -> None:
        config = _stt_config()
        backend = FasterWhisperBackend(config)
        # Não chamar load()

        with pytest.raises(STTError, match="model not loaded"):
            backend.transcribe(
                audio=np.array([0.0], dtype=np.float32),
                language="pt",
                beam_size=1,
                vad_filter=False,
                chunk_length=30,
            )

    def test_transcribe_success(self) -> None:
        config = _stt_config()
        backend = FasterWhisperBackend(config)

        mock_model = MagicMock()
        mock_seg = MockSegment(text="teste", avg_logprob=-0.3)
        mock_info = MockTranscriptionInfo(language="pt")
        mock_model.transcribe.return_value = (
            iter([mock_seg]),
            mock_info,
        )

        with patch("faster_whisper.WhisperModel", return_value=mock_model):
            backend.load()

        audio = np.zeros(16000, dtype=np.float32)
        text, lang, logprob, segments = backend.transcribe(
            audio=audio,
            language="pt",
            beam_size=1,
            vad_filter=False,
            chunk_length=30,
        )

        assert text == "teste"
        assert lang == "pt"
        assert logprob == -0.3
        assert len(segments) == 1

    def test_transcribe_multiple_segments(self) -> None:
        config = _stt_config()
        backend = FasterWhisperBackend(config)

        mock_model = MagicMock()
        segs = [
            MockSegment(text="vamos abrir", avg_logprob=-0.2),
            MockSegment(text="em joao tres", avg_logprob=-0.4),
            MockSegment(text="versiculo dezesseis", avg_logprob=-0.3),
        ]
        mock_info = MockTranscriptionInfo(language="pt")
        mock_model.transcribe.return_value = (iter(segs), mock_info)

        with patch("faster_whisper.WhisperModel", return_value=mock_model):
            backend.load()

        audio = np.zeros(48000, dtype=np.float32)
        text, lang, logprob, segments = backend.transcribe(
            audio=audio,
            language="pt",
            beam_size=1,
            vad_filter=False,
            chunk_length=30,
        )

        assert text == "vamos abrir em joao tres versiculo dezesseis"
        # avg_logprob = (-0.2 + -0.4 + -0.3) / 3 = -0.3
        assert abs(logprob - (-0.3)) < 0.001
        assert len(segments) == 3

    def test_transcribe_empty_segments(self) -> None:
        config = _stt_config()
        backend = FasterWhisperBackend(config)

        mock_model = MagicMock()
        mock_info = MockTranscriptionInfo(language="pt")
        mock_model.transcribe.return_value = (iter([]), mock_info)

        with patch("faster_whisper.WhisperModel", return_value=mock_model):
            backend.load()

        audio = np.zeros(16000, dtype=np.float32)
        text, lang, logprob, segments = backend.transcribe(
            audio=audio,
            language="pt",
            beam_size=1,
            vad_filter=False,
            chunk_length=30,
        )

        assert text == ""
        assert logprob == 0.0
        assert len(segments) == 0

    def test_transcribe_error(self) -> None:
        config = _stt_config()
        backend = FasterWhisperBackend(config)

        mock_model = MagicMock()
        mock_model.transcribe.side_effect = RuntimeError("model crashed")

        with patch("faster_whisper.WhisperModel", return_value=mock_model):
            backend.load()

        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(STTError, match="transcription failed"):
            backend.transcribe(
                audio=audio,
                language="pt",
                beam_size=1,
                vad_filter=False,
                chunk_length=30,
            )

    def test_close(self) -> None:
        config = _stt_config()
        backend = FasterWhisperBackend(config)

        with patch("faster_whisper.WhisperModel", return_value=MagicMock()):
            backend.load()
        backend.close()
        # Model deve ser None após close
        assert backend._model is None

    def test_check_cuda(self) -> None:
        config = _stt_config()
        backend = FasterWhisperBackend(config)

        # _check_cuda delega para HardwareDetector.detect()
        from core.hardware import HardwareProfile, CpuInfo

        mock_profile_with_cuda = HardwareProfile(
            cpu=CpuInfo("Test", 4, 8, "x86_64"),
            ram_mb=16000,
            gpus=(),
            os_name="windows",
            os_version="10",
            python_version="3.14",
        )
        # has_cuda é property baseada em gpus — precisamos de uma GPU NVIDIA
        from core.hardware import GpuInfo
        mock_profile_with_cuda = HardwareProfile(
            cpu=CpuInfo("Test", 4, 8, "x86_64"),
            ram_mb=16000,
            gpus=(GpuInfo("RTX 4060", "nvidia", 8000, "full", "12"),),
            os_name="windows",
            os_version="10",
            python_version="3.14",
        )
        mock_profile_without_cuda = HardwareProfile(
            cpu=CpuInfo("Test", 4, 8, "x86_64"),
            ram_mb=16000,
            gpus=(),
            os_name="windows",
            os_version="10",
            python_version="3.14",
        )

        with patch("core.hardware.HardwareDetector.detect", return_value=mock_profile_with_cuda):
            assert backend._check_cuda() is True

        with patch("core.hardware.HardwareDetector.detect", return_value=mock_profile_without_cuda):
            assert backend._check_cuda() is False


# ---------------------------------------------------------------------------
# STTBackend Protocol
# ---------------------------------------------------------------------------

class TestSTTBackendProtocol:
    def test_mock_backend_is_protocol(self) -> None:
        """MockBackend deve satisfazer STTBackend Protocol."""
        from transcricao.stt import STTBackend

        backend = MockBackend()
        assert isinstance(backend, STTBackend)

    def test_faster_whisper_backend_is_protocol(self) -> None:
        from transcricao.stt import STTBackend

        config = _stt_config()
        backend = FasterWhisperBackend(config)
        assert isinstance(backend, STTBackend)
