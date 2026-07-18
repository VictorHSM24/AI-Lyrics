"""Módulo de captura de áudio do microfone com VAD.

API pública:
    MicrophoneCapture — captura contínua com VAD, produz SpeechSegments.
    VadSegmenter — segmentador de fala VAD (lógica pura, testável).
    SpeechSegment — segmento completo de fala.
    DeviceInfo — informação de dispositivo de entrada.
    CaptureMetrics — métricas de captura.
"""

from microfone.capture import (
    CaptureMetrics,
    DeviceInfo,
    MicrophoneCapture,
    SpeechSegment,
    VadSegmenter,
)

__all__ = [
    "MicrophoneCapture",
    "VadSegmenter",
    "SpeechSegment",
    "DeviceInfo",
    "CaptureMetrics",
]
