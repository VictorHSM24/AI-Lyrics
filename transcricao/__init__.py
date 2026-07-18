"""Módulo de transcrição Speech-to-Text offline.

API pública:
    STT — transcrição offline com Faster-Whisper.
    STTResult — resultado de transcrição.
    STTMetrics — métricas acumuladas.
    STTBackend — protocolo para backends de STT.
    FasterWhisperBackend — backend Faster-Whisper (CTranslate2).
"""

from transcricao.stt import (
    FasterWhisperBackend,
    STT,
    STTBackend,
    STTMetrics,
    STTResult,
)

__all__ = [
    "STT",
    "STTResult",
    "STTMetrics",
    "STTBackend",
    "FasterWhisperBackend",
]
