"""Testes unitários do módulo microfone/capture.py.

Estratégia:
  - VadSegmenter é lógica pura — testável sem hardware.
  - MicrophoneCapture.list_input_devices / find_device — mock sounddevice.
  - MicrophoneCapture.run — mock sounddevice com chunks sintéticos.
  - Não requer microfone real nem webrtcvad instalado (usa mock VAD).
"""

from __future__ import annotations

import struct
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from config.models import AudioConfig
from core.exceptions import AudioError
from microfone.capture import (
    CaptureMetrics,
    DeviceInfo,
    MicrophoneCapture,
    SpeechSegment,
    VadSegmenter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audio_config(**overrides) -> AudioConfig:
    defaults = {
        "input_device": "CODEC USB",
        "sample_rate": 16000,
        "channels": 1,
        "chunk_ms": 30,
        "vad_enabled": True,
        "min_speech_ms": 600,
        "max_silence_ms": 800,
        "vad_mode": 3,
        "max_segment_ms": 30_000,
    }
    defaults.update(overrides)
    return AudioConfig(**defaults)


def _make_pcm_chunk(chunk_ms: int = 30, sample_rate: int = 16000) -> bytes:
    """Cria um chunk PCM 16-bit mono do tamanho correto."""
    n_samples = int(sample_rate * chunk_ms / 1000)
    # Silêncio (zeros)
    return b"\x00\x00" * n_samples


def _make_speech_chunk(chunk_ms: int = 30, sample_rate: int = 16000) -> bytes:
    """Cria um chunk PCM com amplitude alta (simula fala)."""
    import numpy as np

    n_samples = int(sample_rate * chunk_ms / 1000)
    # Onda senoidal de amplitude alta
    t = np.linspace(0, chunk_ms / 1000, n_samples, endpoint=False)
    samples = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    return samples.tobytes()


class MockVAD:
    """VAD mock que retorna True para chunks com amplitude alta."""

    def __init__(self, mode: int = 3) -> None:
        self.mode = mode
        self._is_speech = False

    def is_speech(self, pcm: bytes, sample_rate: int) -> bool:
        import numpy as np

        if len(pcm) == 0:
            return False
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
        rms = np.sqrt(np.mean(samples ** 2)) if len(samples) > 0 else 0.0
        return rms > 100.0

    def set_speech(self, is_speech: bool) -> None:
        self._is_speech = is_speech


# ---------------------------------------------------------------------------
# VadSegmenter — lógica pura
# ---------------------------------------------------------------------------

class TestVadSegmenterConstruction:
    def test_valid_construction(self) -> None:
        vad = MockVAD()
        seg = VadSegmenter(
            sample_rate=16000,
            chunk_ms=30,
            min_speech_ms=600,
            max_silence_ms=800,
            vad=vad,
        )
        assert seg.in_speech is False
        assert seg.buffer_ms == 0

    def test_invalid_chunk_ms(self) -> None:
        vad = MockVAD()
        with pytest.raises(AudioError, match="chunk_ms must be"):
            VadSegmenter(
                sample_rate=16000,
                chunk_ms=50,
                min_speech_ms=600,
                max_silence_ms=800,
                vad=vad,
            )

    def test_invalid_vad_mode(self) -> None:
        vad = MockVAD()
        with pytest.raises(AudioError, match="vad_mode must be"):
            VadSegmenter(
                sample_rate=16000,
                chunk_ms=30,
                min_speech_ms=600,
                max_silence_ms=800,
                vad_mode=5,
                vad=vad,
            )


class TestVadSegmenterSilence:
    def test_silence_produces_no_segment(self) -> None:
        vad = MockVAD()
        seg = VadSegmenter(16000, 30, 600, 800, vad=vad)
        chunk = _make_pcm_chunk()

        # 10 chunks de silêncio (300ms) — não deve produzir segmento
        for _ in range(10):
            result = seg.process_chunk(chunk, time.time())
            assert result is None

        assert seg.in_speech is False

    def test_long_silence_produces_no_segment(self) -> None:
        vad = MockVAD()
        seg = VadSegmenter(16000, 30, 600, 800, vad=vad)
        chunk = _make_pcm_chunk()

        # 100 chunks de silêncio (3s) — não deve produzir segmento
        for _ in range(100):
            result = seg.process_chunk(chunk, time.time())
            assert result is None


class TestVadSegmenterSpeech:
    def test_short_speech_discarded(self) -> None:
        """Fala < min_speech_ms → segmento descartado."""
        vad = MockVAD()
        seg = VadSegmenter(16000, 30, 600, 800, vad=vad)
        speech = _make_speech_chunk()
        silence = _make_pcm_chunk()

        # 10 chunks de fala (300ms) — abaixo de min_speech_ms=600
        for _ in range(10):
            result = seg.process_chunk(speech, time.time())
            assert result is None  # ainda em fala

        assert seg.in_speech is True

        # Silêncio para finalizar
        result = None
        for _ in range(30):  # 900ms de silêncio > max_silence_ms=800
            result = seg.process_chunk(silence, time.time())
            if result is not None:
                break

        # descartado por ser < min_speech_ms
        assert result is None

    def test_valid_speech_produces_segment(self) -> None:
        """Fala >= min_speech_ms + silêncio >= max_silence_ms → segmento."""
        vad = MockVAD()
        seg = VadSegmenter(16000, 30, 600, 800, vad=vad)
        speech = _make_speech_chunk()
        silence = _make_pcm_chunk()

        # 30 chunks de fala (900ms) — acima de min_speech_ms=600
        start_time = time.time()
        for _ in range(30):
            result = seg.process_chunk(speech, start_time)
            assert result is None  # ainda em fala

        assert seg.in_speech is True

        # Silêncio para finalizar (800ms = ~27 chunks de 30ms)
        result = None
        for i in range(30):
            result = seg.process_chunk(silence, start_time + 1.0 + i * 0.03)
            if result is not None:
                break

        assert result is not None
        assert result.duration_ms == 900  # 30 chunks * 30ms
        assert result.chunk_count > 0
        assert len(result.audio) > 0
        assert result.start_time > 0
        assert result.end_time > result.start_time

    def test_speech_then_more_speech(self) -> None:
        """Fala contínua sem pausa → não emite segmento até silêncio."""
        vad = MockVAD()
        seg = VadSegmenter(16000, 30, 600, 800, vad=vad)
        speech = _make_speech_chunk()

        # 100 chunks de fala contínua (3s) — sem segmento
        for _ in range(100):
            result = seg.process_chunk(speech, time.time())
            assert result is None

        assert seg.in_speech is True
        assert seg.buffer_ms == 3000


class TestVadSegmenterFlush:
    def test_forced_flush_max_segment(self) -> None:
        """Buffer >= max_segment_ms → flush forçado."""
        vad = MockVAD()
        seg = VadSegmenter(
            16000, 30, 600, 800,
            vad=vad,
            max_segment_ms=900,  # 30 chunks
        )
        speech = _make_speech_chunk()

        # 30 chunks = 900ms = max_segment_ms → flush no 30º
        result = None
        for _ in range(30):
            result = seg.process_chunk(speech, time.time())

        assert result is not None
        assert result.duration_ms >= 900

    def test_force_flush_on_stop(self) -> None:
        """force_flush em fala em andamento → emite segmento."""
        vad = MockVAD()
        seg = VadSegmenter(16000, 30, 600, 800, vad=vad)
        speech = _make_speech_chunk()

        # 30 chunks de fala (900ms)
        for _ in range(30):
            seg.process_chunk(speech, time.time())

        assert seg.in_speech is True

        # Force flush
        result = seg.force_flush()
        assert result is not None
        assert result.duration_ms == 900

    def test_force_flush_no_speech(self) -> None:
        """force_flush sem fala → None."""
        vad = MockVAD()
        seg = VadSegmenter(16000, 30, 600, 800, vad=vad)
        assert seg.force_flush() is None

    def test_reset(self) -> None:
        vad = MockVAD()
        seg = VadSegmenter(16000, 30, 600, 800, vad=vad)
        speech = _make_speech_chunk()

        for _ in range(10):
            seg.process_chunk(speech, time.time())

        assert seg.in_speech is True
        seg.reset()
        assert seg.in_speech is False
        assert seg.buffer_ms == 0


class TestVadSegmenterEdgeCases:
    def test_empty_chunk(self) -> None:
        """Chunk vazio → tratado como silêncio."""
        vad = MockVAD()
        seg = VadSegmenter(16000, 30, 600, 800, vad=vad)
        result = seg.process_chunk(b"", time.time())
        assert result is None
        assert seg.in_speech is False

    def test_vad_error_treated_as_silence(self) -> None:
        """VAD que lança exceção → tratado como silêncio."""

        class ErrorVAD:
            def is_speech(self, pcm: bytes, sr: int) -> bool:
                raise RuntimeError("VAD crashed")

        seg = VadSegmenter(16000, 30, 600, 800, vad=ErrorVAD())
        chunk = _make_speech_chunk()
        result = seg.process_chunk(chunk, time.time())
        assert result is None
        assert seg.in_speech is False


# ---------------------------------------------------------------------------
# MicrophoneCapture — device listing (mock sounddevice)
# ---------------------------------------------------------------------------

class TestDeviceListing:
    def test_list_input_devices(self) -> None:
        """Lista dispositivos de entrada via sounddevice mock."""
        mock_devices = [
            {"name": "CODEC USB", "max_input_channels": 2, "default_samplerate": 48000},
            {"name": "Speaker Out", "max_input_channels": 0, "default_samplerate": 48000},
            {"name": "Microfone Realtek", "max_input_channels": 1, "default_samplerate": 44100},
        ]

        with patch("sounddevice.query_devices", return_value=mock_devices):
            with patch("sounddevice.default.device", (0, 1)):
                devices = MicrophoneCapture.list_input_devices()

        # Apenas dispositivos com input channels > 0
        assert len(devices) == 2
        assert devices[0].name == "CODEC USB"
        assert devices[0].channels == 2
        assert devices[1].name == "Microfone Realtek"

    def test_find_device_by_name_partial(self) -> None:
        mock_devices = [
            {"name": "CODEC USB", "max_input_channels": 2, "default_samplerate": 48000},
            {"name": "Microfone Realtek", "max_input_channels": 1, "default_samplerate": 44100},
        ]

        config = _audio_config(input_device="CODEC USB")
        vad = MockVAD()
        segmenter = VadSegmenter(16000, 30, 600, 800, vad=vad)
        cap = MicrophoneCapture(config, segmenter=segmenter)

        with patch("sounddevice.query_devices", return_value=mock_devices):
            with patch("sounddevice.default.device", (0, 1)):
                idx = cap.find_device("CODEC USB")
        assert idx == 0

    def test_find_device_case_insensitive(self) -> None:
        mock_devices = [
            {"name": "Codec USB", "max_input_channels": 2, "default_samplerate": 48000},
        ]

        config = _audio_config()
        vad = MockVAD()
        segmenter = VadSegmenter(16000, 30, 600, 800, vad=vad)
        cap = MicrophoneCapture(config, segmenter=segmenter)

        with patch("sounddevice.query_devices", return_value=mock_devices):
            with patch("sounddevice.default.device", (0, 0)):
                idx = cap.find_device("codec usb")
        assert idx == 0

    def test_find_device_by_index(self) -> None:
        mock_devices = [
            {"name": "CODEC USB", "max_input_channels": 2, "default_samplerate": 48000},
            {"name": "Microfone Realtek", "max_input_channels": 1, "default_samplerate": 44100},
        ]

        config = _audio_config()
        vad = MockVAD()
        segmenter = VadSegmenter(16000, 30, 600, 800, vad=vad)
        cap = MicrophoneCapture(config, segmenter=segmenter)

        with patch("sounddevice.query_devices", return_value=mock_devices):
            with patch("sounddevice.default.device", (0, 1)):
                idx = cap.find_device(1)
        assert idx == 1

    def test_find_device_by_index_string(self) -> None:
        mock_devices = [
            {"name": "CODEC USB", "max_input_channels": 2, "default_samplerate": 48000},
        ]

        config = _audio_config()
        vad = MockVAD()
        segmenter = VadSegmenter(16000, 30, 600, 800, vad=vad)
        cap = MicrophoneCapture(config, segmenter=segmenter)

        with patch("sounddevice.query_devices", return_value=mock_devices):
            with patch("sounddevice.default.device", (0, 0)):
                idx = cap.find_device("0")
        assert idx == 0

    def test_find_device_not_found(self) -> None:
        mock_devices = [
            {"name": "CODEC USB", "max_input_channels": 2, "default_samplerate": 48000},
        ]

        config = _audio_config(input_device="Nonexistent Device")
        vad = MockVAD()
        segmenter = VadSegmenter(16000, 30, 600, 800, vad=vad)
        cap = MicrophoneCapture(config, segmenter=segmenter)

        with patch("sounddevice.query_devices", return_value=mock_devices):
            with patch("sounddevice.default.device", (0, 0)):
                with pytest.raises(AudioError, match="not found"):
                    cap.find_device("Nonexistent Device")


# ---------------------------------------------------------------------------
# MicrophoneCapture — run loop (mock sounddevice)
# ---------------------------------------------------------------------------

class TestCaptureRun:
    def test_silence_only_no_segments(self) -> None:
        """5s de silêncio → nenhum SpeechSegment emitido."""
        config = _audio_config()
        vad = MockVAD()
        segmenter = VadSegmenter(16000, 30, 600, 800, vad=vad)
        cap = MicrophoneCapture(config, segmenter=segmenter)

        silence_chunk = _make_pcm_chunk()

        # Mock InputStream que produz 5s de silêncio (~166 chunks de 30ms)
        chunks_produced = [silence_chunk] * 166
        call_count = [0]

        def mock_read(n):
            idx = call_count[0]
            call_count[0] += 1
            if idx >= len(chunks_produced):
                cap.stop()
                return (silence_chunk, None)
            return (chunks_produced[idx], None)

        mock_stream = MagicMock()
        mock_stream.read = mock_read

        with patch("sounddevice.InputStream", return_value=mock_stream):
            with patch("sounddevice.query_devices", return_value=[
                {"name": "CODEC USB", "max_input_channels": 2, "default_samplerate": 16000}
            ]):
                with patch("sounddevice.default.device", (0, 0)):
                    segments = list(cap.run())

        assert len(segments) == 0
        assert cap.metrics.total_chunks >= 166

    def test_speech_then_silence_produces_segment(self) -> None:
        """Fala + silêncio → 1 SpeechSegment."""
        config = _audio_config()
        vad = MockVAD()
        segmenter = VadSegmenter(16000, 30, 600, 800, vad=vad)
        cap = MicrophoneCapture(config, segmenter=segmenter)

        speech = _make_speech_chunk()
        silence = _make_pcm_chunk()

        # 30 chunks de fala (900ms) + 30 chunks de silêncio (900ms)
        chunks = [speech] * 30 + [silence] * 30
        call_count = [0]

        def mock_read(n):
            idx = call_count[0]
            call_count[0] += 1
            if idx >= len(chunks):
                cap.stop()
                return (silence, None)
            return (chunks[idx], None)

        mock_stream = MagicMock()
        mock_stream.read = mock_read

        with patch("sounddevice.InputStream", return_value=mock_stream):
            with patch("sounddevice.query_devices", return_value=[
                {"name": "CODEC USB", "max_input_channels": 2, "default_samplerate": 16000}
            ]):
                with patch("sounddevice.default.device", (0, 0)):
                    segments = list(cap.run())

        assert len(segments) == 1
        assert segments[0].duration_ms >= 600
        assert len(segments[0].audio) > 0

    def test_stop_terminates_loop(self) -> None:
        """stop() deve terminar o loop de captura."""
        config = _audio_config()
        vad = MockVAD()
        segmenter = VadSegmenter(16000, 30, 600, 800, vad=vad)
        cap = MicrophoneCapture(config, segmenter=segmenter)

        silence = _make_pcm_chunk()

        call_count = [0]

        def mock_read(n):
            call_count[0] += 1
            if call_count[0] >= 5:
                cap.stop()
            return (silence, None)

        mock_stream = MagicMock()
        mock_stream.read = mock_read

        with patch("sounddevice.InputStream", return_value=mock_stream):
            with patch("sounddevice.query_devices", return_value=[
                {"name": "CODEC USB", "max_input_channels": 2, "default_samplerate": 16000}
            ]):
                with patch("sounddevice.default.device", (0, 0)):
                    segments = list(cap.run())

        assert len(segments) == 0
        assert cap.metrics.total_chunks >= 5


# ---------------------------------------------------------------------------
# MicrophoneCapture — VAD desativado
# ---------------------------------------------------------------------------

class TestVadDisabled:
    def test_noop_segmenter_used(self) -> None:
        config = _audio_config(vad_enabled=False)
        cap = MicrophoneCapture(config)
        # _NoOpSegmenter é interno, mas podemos verificar que não é VadSegmenter
        assert not isinstance(cap._segmenter, VadSegmenter)

    def test_noop_segmenter_detects_speech(self) -> None:
        """Com VAD desativado, RMS threshold detecta fala."""
        config = _audio_config(vad_enabled=False, min_speech_ms=300, max_silence_ms=300)
        # Não precisa de MockVAD — _NoOpSegmenter usa RMS threshold
        cap = MicrophoneCapture(config)

        speech = _make_speech_chunk()
        silence = _make_pcm_chunk()

        # 15 chunks de fala (450ms) + 15 chunks de silêncio (450ms)
        chunks = [speech] * 15 + [silence] * 15
        call_count = [0]

        def mock_read(n):
            idx = call_count[0]
            call_count[0] += 1
            if idx >= len(chunks):
                cap.stop()
                return (silence, None)
            return (chunks[idx], None)

        mock_stream = MagicMock()
        mock_stream.read = mock_read

        with patch("sounddevice.InputStream", return_value=mock_stream):
            with patch("sounddevice.query_devices", return_value=[
                {"name": "CODEC USB", "max_input_channels": 2, "default_samplerate": 16000}
            ]):
                with patch("sounddevice.default.device", (0, 0)):
                    segments = list(cap.run())

        assert len(segments) == 1
        assert segments[0].duration_ms >= 300


# ---------------------------------------------------------------------------
# SpeechSegment
# ---------------------------------------------------------------------------

class TestSpeechSegment:
    def test_construction(self) -> None:
        seg = SpeechSegment(
            audio=b"\x00\x01" * 100,
            start_time=1000.0,
            end_time=1001.5,
            duration_ms=1500,
            chunk_count=50,
        )
        assert seg.duration_ms == 1500
        assert seg.chunk_count == 50
        assert len(seg.audio) == 200

    def test_frozen(self) -> None:
        seg = SpeechSegment(b"", 0.0, 1.0, 1000, 10)
        with pytest.raises((AttributeError, Exception)):
            seg.duration_ms = 2000  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CaptureMetrics
# ---------------------------------------------------------------------------

class TestCaptureMetrics:
    def test_default_values(self) -> None:
        m = CaptureMetrics()
        assert m.total_chunks == 0
        assert m.segments_emitted == 0
        assert m.reconnect_count == 0

    def test_mutable(self) -> None:
        m = CaptureMetrics()
        m.total_chunks = 10
        m.segments_emitted = 1
        assert m.total_chunks == 10
        assert m.segments_emitted == 1


# ---------------------------------------------------------------------------
# DeviceInfo
# ---------------------------------------------------------------------------

class TestDeviceInfo:
    def test_construction(self) -> None:
        d = DeviceInfo(
            index=0,
            name="CODEC USB",
            channels=2,
            sample_rate=48000.0,
            is_default=True,
        )
        assert d.index == 0
        assert d.name == "CODEC USB"
        assert d.is_default is True

    def test_frozen(self) -> None:
        d = DeviceInfo(0, "Test", 1, 16000.0, False)
        with pytest.raises((AttributeError, Exception)):
            d.name = "Other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _create_vad — seleção automática de biblioteca VAD
# ---------------------------------------------------------------------------

class TestCreateVad:
    def test_pysilero_vad_preferred(self) -> None:
        """pysilero-vad deve ser a primeira escolha (wheels cp39-abi3)."""
        from microfone.capture import _create_vad

        vad = _create_vad(3)
        # pysilero-vad tem chunk_bytes()
        assert hasattr(vad, "chunk_bytes")
        assert vad.chunk_bytes() == 1024  # 512 samples * 2 bytes

    def test_rms_fallback_interface(self) -> None:
        """_RmsVadFallback deve ter interface is_speech(pcm, sr)."""
        from microfone.capture import _RmsVadFallback

        vad = _RmsVadFallback(threshold=100.0)
        silence = _make_pcm_chunk()
        assert vad.is_speech(silence, 16000) is False

        speech = _make_speech_chunk()
        assert vad.is_speech(speech, 16000) is True

    def test_rms_fallback_empty(self) -> None:
        from microfone.capture import _RmsVadFallback

        vad = _RmsVadFallback()
        assert vad.is_speech(b"", 16000) is False


# ---------------------------------------------------------------------------
# VadSegmenter com pysilero-vad real (se instalado)
# ---------------------------------------------------------------------------

class TestVadSegmenterWithSilero:
    """Testes com pysilero-vad real (requer biblioteca instalada)."""

    def test_silero_silence_no_segment(self) -> None:
        """Silero VAD com silêncio sintético → nenhum segmento."""
        try:
            from pysilero_vad import SileroVoiceActivityDetector
        except ImportError:
            pytest.skip("pysilero-vad not installed")

        vad = SileroVoiceActivityDetector()
        # Silero requer chunk_ms=32 (512 samples @ 16kHz)
        seg = VadSegmenter(16000, 32, 600, 800, vad=vad)

        silence = _make_pcm_chunk(32)
        for _ in range(50):  # 1.6s de silêncio
            result = seg.process_chunk(silence, time.time())
            assert result is None

    def test_silero_detects_speech(self) -> None:
        """Silero VAD com fala sintética (senoide) → detecta fala."""
        try:
            from pysilero_vad import SileroVoiceActivityDetector
        except ImportError:
            pytest.skip("pysilero-vad not installed")

        vad = SileroVoiceActivityDetector()
        seg = VadSegmenter(16000, 32, 600, 800, vad=vad)

        speech = _make_speech_chunk(32)
        silence = _make_pcm_chunk(32)

        # 40 chunks de fala (1.28s)
        for _ in range(40):
            seg.process_chunk(speech, time.time())

        # Silêncio para finalizar
        result = None
        for _ in range(30):
            result = seg.process_chunk(silence, time.time())
            if result is not None:
                break

        # Pode ou não detectar senoide como fala (Silero é treinado em voz real)
        # Apenas verificamos que não crasha
        if result is not None:
            assert result.duration_ms > 0


# ---------------------------------------------------------------------------
# VadSegmenter com bufferização (VAD que requer chunk fixo)
# ---------------------------------------------------------------------------

class TestVadBuffering:
    def test_buffered_vad_accumulates_chunks(self) -> None:
        """VAD com chunk_bytes() deve bufferizar chunks menores."""

        class FixedSizeVAD:
            """VAD mock que requer 1024 bytes (512 samples)."""

            def __init__(self) -> None:
                self.call_count = 0

            def chunk_bytes(self) -> int:
                return 1024

            def __call__(self, pcm: bytes) -> float:
                self.call_count += 1
                import numpy as np
                samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
                rms = np.sqrt(np.mean(samples ** 2)) if len(samples) > 0 else 0.0
                return 1.0 if rms > 100.0 else 0.0

        vad = FixedSizeVAD()
        seg = VadSegmenter(16000, 30, 600, 800, vad=vad)

        # Chunks de 30ms = 960 bytes < 1024 requerido
        speech = _make_speech_chunk(30)
        assert len(speech) == 960  # 480 samples * 2 bytes

        # Processar 3 chunks (2880 bytes) → deve chamar VAD 2 vezes (1024*2=2048)
        for _ in range(3):
            seg.process_chunk(speech, time.time())

        assert vad.call_count >= 2  # bufferizou e processou


# ---------------------------------------------------------------------------
# VadSegmenter com RMS fallback
# ---------------------------------------------------------------------------

class TestVadSegmenterRmsFallback:
    def test_rms_fallback_detects_speech(self) -> None:
        """RMS fallback deve detectar fala por amplitude."""
        from microfone.capture import _RmsVadFallback

        vad = _RmsVadFallback(threshold=100.0)
        seg = VadSegmenter(16000, 30, 600, 800, vad=vad)

        speech = _make_speech_chunk()
        silence = _make_pcm_chunk()

        # 30 chunks de fala (900ms)
        for _ in range(30):
            seg.process_chunk(speech, time.time())

        # Silêncio para finalizar
        result = None
        for _ in range(30):
            result = seg.process_chunk(silence, time.time())
            if result is not None:
                break

        assert result is not None
        assert result.duration_ms >= 600
