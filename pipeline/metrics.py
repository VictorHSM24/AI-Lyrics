"""PipelineMetrics — métricas do Pipeline.

Responsabilidade única: registrar métricas de processamento.
Nenhuma decisão. Nenhuma regra de negócio.

Métricas registradas:
  - segmentos recebidos e processados
  - consultas processadas
  - apresentações executadas
  - latência total e por etapa
  - erros
  - tempo médio por etapa
  - throughput (segmentos/min, consultas/min)

Mutável (não frozen) — é um agregador de métricas em tempo real.
Mas não tem lógica de negócio, apenas contadores e timers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineMetrics:
    """Agregador de métricas do Pipeline.

    Mutável (contadores em tempo real). Nenhuma decisão.
    """

    # Contadores
    segments_received: int = 0
    segments_processed: int = 0
    segments_dropped: int = 0
    queries_processed: int = 0
    presentations_executed: int = 0
    presentations_failed: int = 0
    errors_total: int = 0
    errors_recoverable: int = 0
    errors_fatal: int = 0

    # Latência acumulada (ms)
    total_latency_ms: float = 0.0
    recognition_latency_ms: float = 0.0
    search_latency_ms: float = 0.0
    ranking_latency_ms: float = 0.0
    intelligence_latency_ms: float = 0.0
    presentation_latency_ms: float = 0.0
    feedback_latency_ms: float = 0.0
    evaluation_latency_ms: float = 0.0

    # Timestamps
    started_at: float = field(default_factory=time.time)
    last_event_at: float = 0.0

    # Estatísticas por correlation_id
    correlation_count: int = 0

    # ------------------------------------------------------------------
    # Registro de eventos
    # ------------------------------------------------------------------

    def record_segment_received(self) -> None:
        self.segments_received += 1
        self.last_event_at = time.time()

    def record_segment_processed(self, latency_ms: float = 0.0) -> None:
        self.segments_processed += 1
        self.total_latency_ms += latency_ms
        self.last_event_at = time.time()

    def record_segment_dropped(self) -> None:
        self.segments_dropped += 1
        self.last_event_at = time.time()

    def record_query_processed(self) -> None:
        self.queries_processed += 1
        self.last_event_at = time.time()

    def record_presentation(self, success: bool = True) -> None:
        if success:
            self.presentations_executed += 1
        else:
            self.presentations_failed += 1
        self.last_event_at = time.time()

    def record_error(self, recoverable: bool = True) -> None:
        self.errors_total += 1
        if recoverable:
            self.errors_recoverable += 1
        else:
            self.errors_fatal += 1
        self.last_event_at = time.time()

    def record_correlation(self) -> None:
        self.correlation_count += 1

    # ------------------------------------------------------------------
    # Latência por etapa
    # ------------------------------------------------------------------

    def record_recognition_latency(self, ms: float) -> None:
        self.recognition_latency_ms += ms

    def record_search_latency(self, ms: float) -> None:
        self.search_latency_ms += ms

    def record_ranking_latency(self, ms: float) -> None:
        self.ranking_latency_ms += ms

    def record_intelligence_latency(self, ms: float) -> None:
        self.intelligence_latency_ms += ms

    def record_presentation_latency(self, ms: float) -> None:
        self.presentation_latency_ms += ms

    def record_feedback_latency(self, ms: float) -> None:
        self.feedback_latency_ms += ms

    def record_evaluation_latency(self, ms: float) -> None:
        self.evaluation_latency_ms += ms

    # ------------------------------------------------------------------
    # Properties (cálculos)
    # ------------------------------------------------------------------

    @property
    def duration_s(self) -> float:
        """Duração total em segundos."""
        end = self.last_event_at if self.last_event_at > 0 else time.time()
        return max(0.0, end - self.started_at)

    @property
    def avg_latency_ms(self) -> float:
        """Latência média por segmento processado."""
        if self.segments_processed == 0:
            return 0.0
        return self.total_latency_ms / self.segments_processed

    @property
    def avg_recognition_latency_ms(self) -> float:
        if self.segments_processed == 0:
            return 0.0
        return self.recognition_latency_ms / self.segments_processed

    @property
    def avg_search_latency_ms(self) -> float:
        if self.queries_processed == 0:
            return 0.0
        return self.search_latency_ms / self.queries_processed

    @property
    def avg_ranking_latency_ms(self) -> float:
        if self.queries_processed == 0:
            return 0.0
        return self.ranking_latency_ms / self.queries_processed

    @property
    def avg_intelligence_latency_ms(self) -> float:
        if self.queries_processed == 0:
            return 0.0
        return self.intelligence_latency_ms / self.queries_processed

    @property
    def avg_presentation_latency_ms(self) -> float:
        total_pres = self.presentations_executed + self.presentations_failed
        if total_pres == 0:
            return 0.0
        return self.presentation_latency_ms / total_pres

    @property
    def throughput_segments_per_min(self) -> float:
        """Throughput de segmentos por minuto."""
        duration = self.duration_s
        if duration <= 0:
            return 0.0
        return (self.segments_processed / duration) * 60.0

    @property
    def throughput_queries_per_min(self) -> float:
        """Throughput de consultas por minuto."""
        duration = self.duration_s
        if duration <= 0:
            return 0.0
        return (self.queries_processed / duration) * 60.0

    @property
    def error_rate(self) -> float:
        """Taxa de erro (erros / segmentos recebidos)."""
        if self.segments_received == 0:
            return 0.0
        return self.errors_total / self.segments_received

    @property
    def drop_rate(self) -> float:
        """Taxa de descarte (dropped / received)."""
        if self.segments_received == 0:
            return 0.0
        return self.segments_dropped / self.segments_received

    @property
    def presentation_success_rate(self) -> float:
        """Taxa de sucesso de apresentações."""
        total = self.presentations_executed + self.presentations_failed
        if total == 0:
            return 0.0
        return self.presentations_executed / total

    @property
    def processing_success_rate(self) -> float:
        """Taxa de sucesso de processamento (processed / received)."""
        if self.segments_received == 0:
            return 0.0
        return self.segments_processed / self.segments_received

    # ------------------------------------------------------------------
    # Reset e serialização
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Zera todas as métricas."""
        self.segments_received = 0
        self.segments_processed = 0
        self.segments_dropped = 0
        self.queries_processed = 0
        self.presentations_executed = 0
        self.presentations_failed = 0
        self.errors_total = 0
        self.errors_recoverable = 0
        self.errors_fatal = 0
        self.total_latency_ms = 0.0
        self.recognition_latency_ms = 0.0
        self.search_latency_ms = 0.0
        self.ranking_latency_ms = 0.0
        self.intelligence_latency_ms = 0.0
        self.presentation_latency_ms = 0.0
        self.feedback_latency_ms = 0.0
        self.evaluation_latency_ms = 0.0
        self.started_at = time.time()
        self.last_event_at = 0.0
        self.correlation_count = 0

    def to_dict(self) -> dict:
        return {
            "segments_received": self.segments_received,
            "segments_processed": self.segments_processed,
            "segments_dropped": self.segments_dropped,
            "queries_processed": self.queries_processed,
            "presentations_executed": self.presentations_executed,
            "presentations_failed": self.presentations_failed,
            "errors_total": self.errors_total,
            "errors_recoverable": self.errors_recoverable,
            "errors_fatal": self.errors_fatal,
            "total_latency_ms": self.total_latency_ms,
            "avg_latency_ms": self.avg_latency_ms,
            "avg_recognition_latency_ms": self.avg_recognition_latency_ms,
            "avg_search_latency_ms": self.avg_search_latency_ms,
            "avg_ranking_latency_ms": self.avg_ranking_latency_ms,
            "avg_intelligence_latency_ms": self.avg_intelligence_latency_ms,
            "avg_presentation_latency_ms": self.avg_presentation_latency_ms,
            "throughput_segments_per_min": self.throughput_segments_per_min,
            "throughput_queries_per_min": self.throughput_queries_per_min,
            "error_rate": self.error_rate,
            "drop_rate": self.drop_rate,
            "presentation_success_rate": self.presentation_success_rate,
            "processing_success_rate": self.processing_success_rate,
            "duration_s": self.duration_s,
            "correlation_count": self.correlation_count,
        }


__all__ = [
    "PipelineMetrics",
]
