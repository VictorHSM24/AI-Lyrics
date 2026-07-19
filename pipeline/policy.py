"""PipelinePolicy — política centralizada do Pipeline.

Centraliza todos os parâmetros do Pipeline: timeouts, buffers,
intervalos, limites, retries. Nenhum número mágico espalhado pelo
código.

Stateless. Apenas armazena configurações.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelinePolicy:
    """Política centralizada do Pipeline.

    Todos os parâmetros configuráveis em um lugar. Imutável.

    Atributos:
        # Timeouts (ms)
        recognition_timeout_ms: timeout para STT.
        search_timeout_ms: timeout para busca.
        ranking_timeout_ms: timeout para ranking.
        intelligence_timeout_ms: timeout para Sermon Intelligence.
        presentation_timeout_ms: timeout para Holyrics.
        feedback_timeout_ms: timeout para Feedback.
        evaluation_timeout_ms: timeout para Evaluation.

        # Buffers e limites
        max_segment_duration_ms: duração máxima de segmento.
        max_query_length: comprimento máximo de query.
        max_results_per_search: máximo de resultados por busca.
        max_candidates_per_ranking: máximo de candidatos após ranking.
        max_history_events: máximo de eventos no histórico do bus.
        max_session_segments: máximo de segmentos por sessão.

        # Retries
        max_retries_recognition: retries para STT.
        max_retries_search: retries para busca.
        max_retries_presentation: retries para Holyrics.

        # Intervalos (ms)
        min_interval_between_segments_ms: intervalo mínimo entre segmentos.
        debounce_ms: debounce para segmentos rápidos.

        # Backpressure (preparado, não implementado)
        backpressure_enabled: se True, ativa backpressure (futuro).
        backpressure_threshold: limite para ativar backpressure (futuro).
        backpressure_strategy: estratégia ("drop_oldest" | "drop_newest" | "block").

        # Comportamento
        continue_on_error: se True, pipeline continua após erro não-fatal.
        auto_present: se True, apresenta automaticamente o melhor candidato.
        auto_record_feedback: se True, registra feedback automático.
        auto_record_evaluation: se True, registra métricas automaticamente.
    """

    # Timeouts (ms)
    recognition_timeout_ms: int = 5000
    search_timeout_ms: int = 2000
    ranking_timeout_ms: int = 500
    intelligence_timeout_ms: int = 500
    presentation_timeout_ms: int = 2000
    feedback_timeout_ms: int = 500
    evaluation_timeout_ms: int = 500

    # Buffers e limites
    max_segment_duration_ms: int = 30000
    max_query_length: int = 500
    max_results_per_search: int = 50
    max_candidates_per_ranking: int = 20
    max_history_events: int = 10000
    max_session_segments: int = 10000

    # Retries
    max_retries_recognition: int = 1
    max_retries_search: int = 1
    max_retries_presentation: int = 2

    # Intervalos (ms)
    min_interval_between_segments_ms: int = 100
    debounce_ms: int = 200

    # Backpressure (preparado, não implementado)
    backpressure_enabled: bool = False
    backpressure_threshold: int = 100
    backpressure_strategy: str = "drop_oldest"

    # Comportamento
    continue_on_error: bool = True
    auto_present: bool = True
    auto_record_feedback: bool = True
    auto_record_evaluation: bool = True

    # ------------------------------------------------------------------
    # Properties de conveniência
    # ------------------------------------------------------------------

    @property
    def total_timeout_ms(self) -> int:
        """Soma de todos os timeouts (estimativa pior caso)."""
        return (
            self.recognition_timeout_ms
            + self.search_timeout_ms
            + self.ranking_timeout_ms
            + self.intelligence_timeout_ms
            + self.presentation_timeout_ms
            + self.feedback_timeout_ms
            + self.evaluation_timeout_ms
        )

    def is_segment_valid(self, duration_ms: int) -> bool:
        """True se a duração do segmento está dentro do limite."""
        return 0 < duration_ms <= self.max_segment_duration_ms

    def is_query_valid(self, query: str) -> bool:
        """True se a query está dentro do limite de comprimento."""
        return 0 < len(query) <= self.max_query_length

    def should_continue_on_error(self, recoverable: bool) -> bool:
        """Decide se pipeline continua após erro."""
        if not self.continue_on_error:
            return False
        return recoverable

    def retry_count_for(self, stage: str) -> int:
        """Retorna o número de retries para um estágio.

        Args:
            stage: "recognition", "search", "presentation", etc.
        """
        mapping = {
            "recognition": self.max_retries_recognition,
            "search": self.max_retries_search,
            "presentation": self.max_retries_presentation,
        }
        return mapping.get(stage, 0)


__all__ = [
    "PipelinePolicy",
]
