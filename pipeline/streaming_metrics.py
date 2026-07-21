"""StreamingPipelineMetrics — métricas de latência do Sprint 19 (Sprint 19).

Responsabilidade:
  - Agregar métricas de todos os componentes do Streaming Pipeline.
  - Medir latência em cada estágio:
      captura → SpeechPartial
      SpeechPartial → Parser
      Parser → ReferenceDetected
      ReferenceDetected → Holyrics
      latência total
  - Expor via API para monitoramento.

Sprint 19 — Streaming Speech Pipeline:
  Este coletor é instanciado no CompositionRoot e recebe referências
  aos componentes do Streaming Pipeline. Ele não interfere no fluxo —
  apenas lê métricas já expostas pelos componentes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["StreamingPipelineMetrics", "StreamingPipelineSnapshot"]


@dataclass
class StreamingPipelineSnapshot:
    """Snapshot instantâneo das métricas do Streaming Pipeline.

    Todos os valores são agregados desde o início da sessão ou
    desde o último reset.
    """
    # RingBuffer
    ring_buffer_filled_samples: int = 0
    ring_buffer_available_seconds: float = 0.0

    # SlidingWindow
    sliding_window_total_extractions: int = 0
    sliding_window_total_empty: int = 0

    # STTExecutor
    stt_executor_total_jobs: int = 0
    stt_executor_total_segment_jobs: int = 0
    stt_executor_total_audio_jobs: int = 0
    stt_executor_avg_wait_ms: float = 0.0
    stt_executor_avg_exec_ms: float = 0.0

    # StreamingSTTService
    streaming_stt_total_windows: int = 0
    streaming_stt_total_transcriptions: int = 0
    streaming_stt_total_partials_published: int = 0
    streaming_stt_total_updates_published: int = 0
    streaming_stt_total_skipped_no_change: int = 0
    streaming_stt_total_skipped_empty: int = 0
    streaming_stt_avg_latency_ms: float = 0.0

    # IncrementalBiblicalParser
    incremental_parser_total_partials_processed: int = 0
    incremental_parser_total_candidates_published: int = 0
    incremental_parser_total_detected_published: int = 0
    incremental_parser_avg_latency_ms: float = 0.0

    # Timestamp do snapshot
    snapshot_timestamp: float = field(default_factory=time.time)


class StreamingPipelineMetrics:
    """Coletor de métricas do Streaming Pipeline (Sprint 19).

    Args:
        ring_buffer: RingBuffer (ou None se desabilitado).
        sliding_window: SlidingWindow (ou None).
        stt_executor: STTExecutor (ou None).
        streaming_stt: StreamingSTTService (ou None).
        incremental_parser: IncrementalBiblicalParser (ou None).

    Uso:
        metrics = StreamingPipelineMetrics(
            ring_buffer=ring_buffer,
            sliding_window=sliding_window,
            stt_executor=stt_executor,
            streaming_stt=streaming_stt,
            incremental_parser=incremental_parser,
        )
        snapshot = metrics.snapshot()
    """

    def __init__(
        self,
        ring_buffer: Any | None = None,
        sliding_window: Any | None = None,
        stt_executor: Any | None = None,
        streaming_stt: Any | None = None,
        incremental_parser: Any | None = None,
    ) -> None:
        self._ring_buffer = ring_buffer
        self._sliding_window = sliding_window
        self._stt_executor = stt_executor
        self._streaming_stt = streaming_stt
        self._incremental_parser = incremental_parser

        logger.info("StreamingPipelineMetrics initialized.")

    def snapshot(self) -> StreamingPipelineSnapshot:
        """Coleta um snapshot instantâneo de todas as métricas."""
        snap = StreamingPipelineSnapshot()

        # RingBuffer
        if self._ring_buffer is not None:
            snap.ring_buffer_filled_samples = self._ring_buffer.filled
            snap.ring_buffer_available_seconds = (
                self._ring_buffer.available_seconds
            )

        # SlidingWindow
        if self._sliding_window is not None:
            snap.sliding_window_total_extractions = (
                self._sliding_window.total_extractions
            )
            snap.sliding_window_total_empty = (
                self._sliding_window.total_empty
            )

        # STTExecutor
        if self._stt_executor is not None:
            snap.stt_executor_total_jobs = self._stt_executor.total_jobs
            snap.stt_executor_total_segment_jobs = (
                self._stt_executor.total_segment_jobs
            )
            snap.stt_executor_total_audio_jobs = (
                self._stt_executor.total_audio_jobs
            )
            snap.stt_executor_avg_wait_ms = self._stt_executor.avg_wait_ms
            snap.stt_executor_avg_exec_ms = self._stt_executor.avg_exec_ms

        # StreamingSTTService
        if self._streaming_stt is not None:
            snap.streaming_stt_total_windows = (
                self._streaming_stt.total_windows
            )
            snap.streaming_stt_total_transcriptions = (
                self._streaming_stt.total_transcriptions
            )
            snap.streaming_stt_total_partials_published = (
                self._streaming_stt.total_partials_published
            )
            snap.streaming_stt_total_updates_published = (
                self._streaming_stt.total_updates_published
            )
            snap.streaming_stt_total_skipped_no_change = (
                self._streaming_stt.total_skipped_no_change
            )
            snap.streaming_stt_total_skipped_empty = (
                self._streaming_stt.total_skipped_empty
            )
            snap.streaming_stt_avg_latency_ms = (
                self._streaming_stt.avg_latency_ms
            )

        # IncrementalBiblicalParser
        if self._incremental_parser is not None:
            snap.incremental_parser_total_partials_processed = (
                self._incremental_parser.total_partials_processed
            )
            snap.incremental_parser_total_candidates_published = (
                self._incremental_parser.total_candidates_published
            )
            snap.incremental_parser_total_detected_published = (
                self._incremental_parser.total_detected_published
            )
            snap.incremental_parser_avg_latency_ms = (
                self._incremental_parser.avg_latency_ms
            )

        return snap

    def to_dict(self) -> dict:
        """Retorna métricas como dict (para API/JSON)."""
        snap = self.snapshot()
        return {
            "ring_buffer": {
                "filled_samples": snap.ring_buffer_filled_samples,
                "available_seconds": round(
                    snap.ring_buffer_available_seconds, 2
                ),
            },
            "sliding_window": {
                "total_extractions": snap.sliding_window_total_extractions,
                "total_empty": snap.sliding_window_total_empty,
            },
            "stt_executor": {
                "total_jobs": snap.stt_executor_total_jobs,
                "total_segment_jobs": snap.stt_executor_total_segment_jobs,
                "total_audio_jobs": snap.stt_executor_total_audio_jobs,
                "avg_wait_ms": round(snap.stt_executor_avg_wait_ms, 2),
                "avg_exec_ms": round(snap.stt_executor_avg_exec_ms, 2),
            },
            "streaming_stt": {
                "total_windows": snap.streaming_stt_total_windows,
                "total_transcriptions": snap.streaming_stt_total_transcriptions,
                "total_partials_published": snap.streaming_stt_total_partials_published,
                "total_updates_published": snap.streaming_stt_total_updates_published,
                "total_skipped_no_change": snap.streaming_stt_total_skipped_no_change,
                "total_skipped_empty": snap.streaming_stt_total_skipped_empty,
                "avg_latency_ms": round(snap.streaming_stt_avg_latency_ms, 2),
            },
            "incremental_parser": {
                "total_partials_processed": snap.incremental_parser_total_partials_processed,
                "total_candidates_published": snap.incremental_parser_total_candidates_published,
                "total_detected_published": snap.incremental_parser_total_detected_published,
                "avg_latency_ms": round(snap.incremental_parser_avg_latency_ms, 2),
            },
            "snapshot_timestamp": snap.snapshot_timestamp,
        }
