"""PipelineState — estado do Pipeline.

Responsabilidade única: armazenar o estado atual do Pipeline.
Nenhuma regra de negócio. Nenhuma decisão.

Campos:
  - running: True se o pipeline está ativo.
  - paused: True se o pipeline está pausado.
  - current_segment: segmento sendo processado (ou None).
  - last_query: última query processada.
  - last_candidate_id: último candidato apresentado.
  - last_event_type: tipo do último evento publicado.
  - last_event_timestamp: timestamp do último evento.
  - statistics: dict com contadores agregados.

Imutável (frozen dataclass). Mudanças produzem novo estado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PipelineState:
    """Estado imutável do Pipeline.

    Mudanças produzem novo estado via `with_*` methods ou
    `replace()`. Nenhuma mutação in-place.
    """

    running: bool = False
    paused: bool = False
    current_segment: Any = None  # SpeechSegmentReceived ou None
    last_query: str = ""
    last_candidate_id: str = ""
    last_event_type: str = ""
    last_event_timestamp: float = 0.0
    statistics: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """True se está rodando e não pausado."""
        return self.running and not self.paused

    @property
    def is_idle(self) -> bool:
        """True se não está rodando."""
        return not self.running

    @property
    def is_processing(self) -> bool:
        """True se está processando um segmento."""
        return self.is_active and self.current_segment is not None

    @property
    def has_last_query(self) -> bool:
        """True se há uma última query."""
        return bool(self.last_query)

    @property
    def has_last_candidate(self) -> bool:
        """True se há um último candidato apresentado."""
        return bool(self.last_candidate_id)

    # ------------------------------------------------------------------
    # Fábricas (produzem novo estado)
    # ------------------------------------------------------------------

    def with_running(self, running: bool) -> "PipelineState":
        """Retorna novo estado com running alterado."""
        return PipelineState(
            running=running,
            paused=self.paused if running else False,
            current_segment=self.current_segment if running else None,
            last_query=self.last_query,
            last_candidate_id=self.last_candidate_id,
            last_event_type=self.last_event_type,
            last_event_timestamp=self.last_event_timestamp,
            statistics=self.statistics,
        )

    def with_paused(self, paused: bool) -> "PipelineState":
        """Retorna novo estado com paused alterado."""
        return PipelineState(
            running=self.running,
            paused=paused,
            current_segment=self.current_segment if not paused else None,
            last_query=self.last_query,
            last_candidate_id=self.last_candidate_id,
            last_event_type=self.last_event_type,
            last_event_timestamp=self.last_event_timestamp,
            statistics=self.statistics,
        )

    def with_current_segment(self, segment: Any) -> "PipelineState":
        """Retorna novo estado com segmento atual."""
        return PipelineState(
            running=self.running,
            paused=self.paused,
            current_segment=segment,
            last_query=self.last_query,
            last_candidate_id=self.last_candidate_id,
            last_event_type=self.last_event_type,
            last_event_timestamp=self.last_event_timestamp,
            statistics=self.statistics,
        )

    def with_last_query(self, query: str) -> "PipelineState":
        """Retorna novo estado com última query."""
        return PipelineState(
            running=self.running,
            paused=self.paused,
            current_segment=self.current_segment,
            last_query=query,
            last_candidate_id=self.last_candidate_id,
            last_event_type=self.last_event_type,
            last_event_timestamp=self.last_event_timestamp,
            statistics=self.statistics,
        )

    def with_last_candidate(self, candidate_id: str) -> "PipelineState":
        """Retorna novo estado com último candidato."""
        return PipelineState(
            running=self.running,
            paused=self.paused,
            current_segment=self.current_segment,
            last_query=self.last_query,
            last_candidate_id=candidate_id,
            last_event_type=self.last_event_type,
            last_event_timestamp=self.last_event_timestamp,
            statistics=self.statistics,
        )

    def with_last_event(self, event_type: str, timestamp: float) -> "PipelineState":
        """Retorna novo estado com último evento."""
        return PipelineState(
            running=self.running,
            paused=self.paused,
            current_segment=self.current_segment,
            last_query=self.last_query,
            last_candidate_id=self.last_candidate_id,
            last_event_type=event_type,
            last_event_timestamp=timestamp,
            statistics=self.statistics,
        )

    def with_statistics(self, statistics: dict) -> "PipelineState":
        """Retorna novo estado com statistics atualizado."""
        return PipelineState(
            running=self.running,
            paused=self.paused,
            current_segment=self.current_segment,
            last_query=self.last_query,
            last_candidate_id=self.last_candidate_id,
            last_event_type=self.last_event_type,
            last_event_timestamp=self.last_event_timestamp,
            statistics=statistics,
        )

    def with_incremented_stat(self, key: str, amount: int = 1) -> "PipelineState":
        """Retorna novo estado com contador incrementado."""
        new_stats = dict(self.statistics)
        new_stats[key] = new_stats.get(key, 0) + amount
        return self.with_statistics(new_stats)

    def reset(self) -> "PipelineState":
        """Retorna estado inicial (zerado)."""
        return PipelineState()

    # ------------------------------------------------------------------
    # Serialização
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "paused": self.paused,
            "is_active": self.is_active,
            "is_processing": self.is_processing,
            "current_segment": (
                self.current_segment.to_dict()
                if self.current_segment is not None and hasattr(self.current_segment, "to_dict")
                else None
            ),
            "last_query": self.last_query,
            "last_candidate_id": self.last_candidate_id,
            "last_event_type": self.last_event_type,
            "last_event_timestamp": self.last_event_timestamp,
            "statistics": dict(self.statistics),
        }


__all__ = [
    "PipelineState",
]
