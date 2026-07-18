"""Exemplo de uso do módulo de captura de áudio com VAD.

Executa: python examples/use_capture.py

Demonstra:
  1. Listagem de dispositivos de entrada.
  2. Resolução de dispositivo por nome.
  3. VadSegmenter com chunks sintéticos (sem hardware).
  4. MicrophoneCapture.run() com mock (sem hardware real).
  5. Métricas de captura.

NOTA: Para captura real, descomente a seção "Captura real" e tenha um
microfone conectado. O exemplo usa mocks por padrão para funcionar sem
hardware.
"""

from __future__ import annotations

import os
import sys
import time
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.models import AudioConfig
from microfone.capture import (
    CaptureMetrics,
    DeviceInfo,
    MicrophoneCapture,
    SpeechSegment,
    VadSegmenter,
)


def _make_speech_chunk(chunk_ms: int = 30, sample_rate: int = 16000) -> bytes:
    """Cria chunk PCM com amplitude alta (simula fala)."""
    n = int(sample_rate * chunk_ms / 1000)
    t = np.linspace(0, chunk_ms / 1000, n, endpoint=False)
    samples = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    return samples.tobytes()


def _make_silence_chunk(chunk_ms: int = 30, sample_rate: int = 16000) -> bytes:
    """Cria chunk PCM de silêncio."""
    n = int(sample_rate * chunk_ms / 1000)
    return b"\x00\x00" * n


class MockVAD:
    """VAD mock baseado em RMS threshold."""

    def __init__(self, mode: int = 3) -> None:
        self.mode = mode

    def is_speech(self, pcm: bytes, sample_rate: int) -> bool:
        if len(pcm) == 0:
            return False
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
        rms = np.sqrt(np.mean(samples ** 2)) if len(samples) > 0 else 0.0
        return rms > 100.0


def main() -> None:
    print("=== Captura de Áudio com VAD ===\n")

    # Detectar qual VAD está disponível
    from microfone.capture import _create_vad
    vad_instance = _create_vad(3)
    vad_name = type(vad_instance).__name__
    if hasattr(vad_instance, "chunk_bytes"):
        vad_info = f"Silero VAD (chunk={vad_instance.chunk_bytes()} bytes)"
    else:
        vad_info = f"{vad_name} (RMS fallback)"
    print(f"VAD ativo: {vad_info}\n")

    config = AudioConfig(
        input_device="CODEC USB",
        sample_rate=16000,
        channels=1,
        chunk_ms=30,
        vad_enabled=True,
        min_speech_ms=600,
        max_silence_ms=800,
        vad_mode=3,
        max_segment_ms=30_000,
    )

    # 1. Listagem de dispositivos (mock)
    print("--- Listagem de dispositivos (mock) ---\n")
    mock_devices = [
        {"name": "CODEC USB", "max_input_channels": 2, "default_samplerate": 48000},
        {"name": "Microfone Realtek", "max_input_channels": 1, "default_samplerate": 44100},
        {"name": "Speaker Out", "max_input_channels": 0, "default_samplerate": 48000},
    ]
    with patch("sounddevice.query_devices", return_value=mock_devices):
        with patch("sounddevice.default.device", (0, 1)):
            devices = MicrophoneCapture.list_input_devices()
    for d in devices:
        default = " (default)" if d.is_default else ""
        print(f"  [{d.index}] {d.name} — {d.channels}ch, {d.sample_rate:.0f}Hz{default}")

    # 2. Resolução de dispositivo
    print("\n--- Resolução de dispositivo ---\n")
    vad = MockVAD()
    segmenter = VadSegmenter(16000, 30, 600, 800, vad=vad)
    cap = MicrophoneCapture(config, segmenter=segmenter)
    with patch("sounddevice.query_devices", return_value=mock_devices):
        with patch("sounddevice.default.device", (0, 1)):
            idx = cap.find_device("CODEC USB")
    print(f"  'CODEC USB' → índice {idx}")

    # 3. VadSegmenter com chunks sintéticos
    print("\n--- VadSegmenter (chunks sintéticos) ---\n")
    vad2 = MockVAD()
    seg = VadSegmenter(16000, 30, 600, 800, vad=vad2)

    speech = _make_speech_chunk()
    silence = _make_silence_chunk()

    # Simular: silêncio → fala → silêncio
    print("  Simulando: [silêncio 1s] [fala 1.2s] [silêncio 1s]")
    segments = []
    base_time = time.time()

    # 33 chunks de silêncio (~1s)
    for i in range(33):
        result = seg.process_chunk(silence, base_time + i * 0.03)
        if result:
            segments.append(result)

    # 40 chunks de fala (~1.2s)
    for i in range(40):
        result = seg.process_chunk(speech, base_time + 1.0 + i * 0.03)
        if result:
            segments.append(result)

    # 33 chunks de silêncio (~1s)
    for i in range(33):
        result = seg.process_chunk(silence, base_time + 2.2 + i * 0.03)
        if result:
            segments.append(result)

    # Force flush
    final = seg.force_flush()
    if final:
        segments.append(final)

    print(f"  Segmentos produzidos: {len(segments)}")
    for s in segments:
        print(f"    duration={s.duration_ms}ms, chunks={s.chunk_count}, "
              f"audio={len(s.audio)} bytes")

    # 4. MicrophoneCapture.run() com mock
    print("\n--- MicrophoneCapture.run() (mock stream) ---\n")
    vad3 = MockVAD()
    segmenter3 = VadSegmenter(16000, 30, 600, 800, vad=vad3)
    cap2 = MicrophoneCapture(config, segmenter=segmenter3)

    # Simular: 20 chunks fala + 30 chunks silêncio
    chunks_data = [speech] * 20 + [silence] * 30
    call_count = [0]

    def mock_read(n):
        idx = call_count[0]
        call_count[0] += 1
        if idx >= len(chunks_data):
            cap2.stop()
            return (silence, None)
        return (chunks_data[idx], None)

    mock_stream = MagicMock()
    mock_stream.read = mock_read

    with patch("sounddevice.InputStream", return_value=mock_stream):
        with patch("sounddevice.query_devices", return_value=mock_devices):
            with patch("sounddevice.default.device", (0, 0)):
                segments2 = list(cap2.run())

    print(f"  Segmentos: {len(segments2)}")
    if segments2:
        s = segments2[0]
        print(f"    duration={s.duration_ms}ms, chunks={s.chunk_count}")
    m = cap2.metrics
    print(f"  Métricas: chunks={m.total_chunks}, speech={m.speech_chunks}, "
          f"silence={m.silence_chunks}, segments={m.segments_emitted}")

    # 5. VAD desativado
    print("\n--- VAD desativado (RMS threshold) ---\n")
    config_no_vad = AudioConfig(
        input_device="CODEC USB",
        sample_rate=16000,
        channels=1,
        chunk_ms=30,
        vad_enabled=False,
        min_speech_ms=300,
        max_silence_ms=300,
    )
    cap3 = MicrophoneCapture(config_no_vad)

    chunks_data3 = [speech] * 15 + [silence] * 15
    call_count3 = [0]

    def mock_read3(n):
        idx = call_count3[0]
        call_count3[0] += 1
        if idx >= len(chunks_data3):
            cap3.stop()
            return (silence, None)
        return (chunks_data3[idx], None)

    mock_stream3 = MagicMock()
    mock_stream3.read = mock_read3

    with patch("sounddevice.InputStream", return_value=mock_stream3):
        with patch("sounddevice.query_devices", return_value=mock_devices):
            with patch("sounddevice.default.device", (0, 0)):
                segments3 = list(cap3.run())

    print(f"  Segmentos: {len(segments3)}")
    if segments3:
        print(f"    duration={segments3[0].duration_ms}ms")

    print("\n=== Concluído ===")
    print("\nNOTA: Para captura real, use:")
    print("  cap = MicrophoneCapture(config)")
    print("  for segment in cap.run():")
    print("      print(f'Speech: {segment.duration_ms}ms')")
    print("  # Em outra thread: cap.stop()")


if __name__ == "__main__":
    main()
