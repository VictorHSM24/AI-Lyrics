"""Exemplo de uso do módulo de transcrição STT.

Executa: python examples/use_stt.py

Demonstra:
  1. STT com MockBackend (sem faster-whisper real).
  2. STT com FasterWhisperBackend mockado (sem GPU/download).
  3. c_stt_from_logprob — conversão de confidence.
  4. Métricas de transcrição.
  5. GPU → CPU fallback.

NOTA: Para transcrição real, descomente a seção "STT real" e tenha
faster-whisper + modelo baixado. O exemplo usa mocks por padrão.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.models import STTConfig, VadConfig
from microfone.capture import SpeechSegment
from transcricao.stt import (
    FasterWhisperBackend,
    STT,
    STTMetrics,
    STTResult,
)


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


def _make_speech_pcm(duration_ms: int = 2000, sample_rate: int = 16000) -> bytes:
    """Cria PCM 16-bit mono com senoide (simula fala)."""
    t = np.linspace(0, duration_ms / 1000, int(sample_rate * duration_ms / 1000), endpoint=False)
    samples = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    return samples.tobytes()


def _make_segment(duration_ms: int = 2000, audio: bytes | None = None) -> SpeechSegment:
    if audio is None:
        audio = _make_speech_pcm(duration_ms)
    return SpeechSegment(
        audio=audio,
        start_time=time.time(),
        end_time=time.time() + duration_ms / 1000,
        duration_ms=duration_ms,
        chunk_count=duration_ms // 30,
    )


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------

class MockSegment:
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
    def __init__(self, language: str = "pt") -> None:
        self.language = language
        self.language_probability = 0.95
        self.duration = 2.0
        self.duration_after_vad = 2.0
        self.all_language_probs = None
        self.transcription_options = None
        self.vad_options = None


class MockBackend:
    """Mock de STTBackend para demonstração sem faster-whisper."""

    def __init__(self, text: str = "vamos abrir em joao tres dezesseis",
                 avg_logprob: float = -0.2) -> None:
        self._text = text
        self._avg_logprob = avg_logprob
        self.loaded = False

    def load(self) -> None:
        self.loaded = True
        print("  [MockBackend] model loaded")

    def transcribe(self, audio, language, beam_size, vad_filter, chunk_length):
        seg = MockSegment(text=self._text, avg_logprob=self._avg_logprob)
        return self._text, language, self._avg_logprob, (seg,)

    def close(self) -> None:
        print("  [MockBackend] model unloaded")


def main() -> None:
    print("=== Transcrição STT com Faster-Whisper ===\n")

    # 1. STT com MockBackend
    print("--- STT com MockBackend ---\n")
    config = _stt_config()
    backend = MockBackend(text="vamos abrir em joao capitulo tres versiculo dezesseis")
    stt = STT(config, backend=backend)

    segment = _make_segment(duration_ms=4200, audio=_make_speech_pcm(4200))
    result = stt.transcribe(segment)

    print(f"  STTResult:")
    print(f"    text          = {result.text!r}")
    print(f"    language      = {result.language}")
    print(f"    confidence    = {result.confidence:.3f}")
    print(f"    processing_ms = {result.processing_ms}")
    print(f"    audio_ms      = {result.audio_duration_ms}")
    print(f"    segments      = {len(result.segments_raw)}")

    # 2. c_stt_from_logprob — conversão de confidence
    print("\n--- c_stt_from_logprob (conversão de confidence) ---\n")
    for lp in [0.5, 0.0, -0.3, -0.5, -1.0, -2.0, -5.0]:
        c = stt.c_stt_from_logprob(lp)
        print(f"  avg_logprob={lp:6.1f} → confidence={c:.3f}")

    # 3. Métricas
    print("\n--- Métricas ---\n")
    # Transcrever alguns segmentos
    for _ in range(3):
        stt.transcribe(segment)

    m = stt.metrics
    print(f"  total_transcriptions = {m.total_transcriptions}")
    print(f"  successful           = {m.successful}")
    print(f"  avg_confidence       = {m.avg_confidence:.3f}")
    print(f"  avg_processing_ms    = {m.avg_processing_ms:.1f}")
    print(f"  total_audio_ms       = {m.total_audio_ms}")
    print(f"  rtf                  = {m.rtf:.3f}")
    print(f"  model_loaded         = {m.model_loaded}")

    stt.close()

    # 4. FasterWhisperBackend com mock (sem GPU/download)
    print("\n--- FasterWhisperBackend (mock WhisperModel) ---\n")
    config_gpu = _stt_config(device="cuda", compute_type="float16")
    backend_fw = FasterWhisperBackend(config_gpu)

    mock_model = MagicMock()
    segs = [
        MockSegment(text="proximo", avg_logprob=-0.15),
    ]
    mock_info = MockTranscriptionInfo(language="pt")
    mock_model.transcribe.return_value = (iter(segs), mock_info)

    # Simular CUDA indisponível → fallback CPU
    with patch("faster_whisper.WhisperModel", return_value=mock_model):
        with patch.object(backend_fw, "_check_cuda", return_value=False):
            backend_fw.load()

    print(f"  device configurado   = {config_gpu.device}")
    print(f"  device efetivo       = {backend_fw.actual_device}")
    print(f"  compute_type efetivo = {backend_fw.actual_compute_type}")
    print(f"  houve fallback       = {backend_fw.actual_device != config_gpu.device}")

    # Transcrever
    audio = np.zeros(16000, dtype=np.float32)
    text, lang, logprob, segments = backend_fw.transcribe(
        audio=audio,
        language="pt",
        beam_size=1,
        vad_filter=False,
        chunk_length=30,
    )
    print(f"\n  Transcrição:")
    print(f"    text     = {text!r}")
    print(f"    language = {lang}")
    print(f"    logprob  = {logprob}")

    backend_fw.close()

    # 5. STT real (descomente para usar)
    print("\n--- STT real (comentado) ---\n")
    print("  # from config import load_config")
    print("  # from microfone.capture import MicrophoneCapture, AudioConfig")
    print("  #")
    print("  # config = load_config('config/config.yaml')")
    print("  # stt = STT(config.stt)")
    print("  #")
    print("  # # Capturar e transcrever")
    print("  # cap = MicrophoneCapture(config.audio)")
    print("  # for segment in cap.run():")
    print("  #     result = stt.transcribe(segment)")
    print("  #     if result.text:")
    print("  #         print(f'{result.confidence:.2f}: {result.text}')")
    print("  # cap.stop()")
    print("  # stt.close()")

    print("\n=== Concluído ===")


if __name__ == "__main__":
    main()
