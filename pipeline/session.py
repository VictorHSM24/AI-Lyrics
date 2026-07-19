"""PipelineSession — representa um sermão completo.

Uma sessão engloba todo o processamento desde o início até o fim de
um sermão. Integra-se naturalmente com Continuous Evaluation.

Campos:
  - session_id: identificador único.
  - started_at: timestamp de início.
  - ended_at: timestamp de fim (0 se ativa).
  - processed_segments: total de segmentos processados.
  - processed_queries: total de consultas processadas.
  - presentations: total de apresentações executadas.
  - errors: total de erros registrados.
  - statistics: dict com estatísticas agregadas.
  - correlation_ids: tuple de correlation_ids processados.

Imutável (frozen dataclass). Mudanças produzem nova sessão.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable


def _default_session_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class PipelineSession:
    """Sessão imutável do Pipeline (um sermão completo).

    Mudanças produzem nova sessão via `with_*` methods.
    """

    session_id: str = field(default_factory=_default_session_id)
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0
    processed_segments: int = 0
    processed_queries: int = 0
    presentations: int = 0
    errors: int = 0
    statistics: dict = field(default_factory=dict)
    correlation_ids: tuple = field(default_factory=tuple)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """True se a sessão não foi finalizada."""
        return self.ended_at == 0.0

    @property
    def is_ended(self) -> bool:
        """True se a sessão foi finalizada."""
        return self.ended_at > 0.0

    @property
    def duration_s(self) -> float:
        """Duração em segundos (até agora se ativa, até fim se finalizada)."""
        end = self.ended_at if self.ended_at > 0 else time.time()
        return max(0.0, end - self.started_at)

    @property
    def unique_correlations(self) -> int:
        """Número de correlation_ids únicos (= fluxos processados)."""
        return len(self.correlation_ids)

    def has_correlation(self, correlation_id: str) -> bool:
        """True se a sessão processou este correlation_id."""
        return correlation_id in self.correlation_ids

    @property
    def segments_per_minute(self) -> float:
        """Throughput de segmentos por minuto."""
        duration = self.duration_s
        if duration <= 0:
            return 0.0
        return (self.processed_segments / duration) * 60.0

    @property
    def queries_per_minute(self) -> float:
        """Throughput de consultas por minuto."""
        duration = self.duration_s
        if duration <= 0:
            return 0.0
        return (self.processed_queries / duration) * 60.0

    @property
    def error_rate(self) -> float:
        """Taxa de erro (erros / segmentos)."""
        if self.processed_segments == 0:
            return 0.0
        return self.errors / self.processed_segments

    @property
    def presentation_rate(self) -> float:
        """Taxa de apresentação (apresentações / consultas)."""
        if self.processed_queries == 0:
            return 0.0
        return self.presentations / self.processed_queries

    # ------------------------------------------------------------------
    # Fábricas (produzem nova sessão)
    # ------------------------------------------------------------------

    @staticmethod
    def create(
        session_id: str | None = None,
        started_at: float | None = None,
        id_generator: Callable[[], str] = _default_session_id,
    ) -> "PipelineSession":
        """Cria nova sessão ativa."""
        return PipelineSession(
            session_id=session_id or id_generator(),
            started_at=started_at if started_at is not None else time.time(),
        )

    def with_segment_processed(self, correlation_id: str) -> "PipelineSession":
        """Retorna nova sessão com segmento processado."""
        new_corr = self.correlation_ids
        if correlation_id not in new_corr:
            new_corr = self.correlation_ids + (correlation_id,)
        return PipelineSession(
            session_id=self.session_id,
            started_at=self.started_at,
            ended_at=self.ended_at,
            processed_segments=self.processed_segments + 1,
            processed_queries=self.processed_queries,
            presentations=self.presentations,
            errors=self.errors,
            statistics=self.statistics,
            correlation_ids=new_corr,
        )

    def with_query_processed(self) -> "PipelineSession":
        """Retorna nova sessão com consulta processada."""
        return PipelineSession(
            session_id=self.session_id,
            started_at=self.started_at,
            ended_at=self.ended_at,
            processed_segments=self.processed_segments,
            processed_queries=self.processed_queries + 1,
            presentations=self.presentations,
            errors=self.errors,
            statistics=self.statistics,
            correlation_ids=self.correlation_ids,
        )

    def with_presentation(self) -> "PipelineSession":
        """Retorna nova sessão com apresentação executada."""
        return PipelineSession(
            session_id=self.session_id,
            started_at=self.started_at,
            ended_at=self.ended_at,
            processed_segments=self.processed_segments,
            processed_queries=self.processed_queries,
            presentations=self.presentations + 1,
            errors=self.errors,
            statistics=self.statistics,
            correlation_ids=self.correlation_ids,
        )

    def with_error(self) -> "PipelineSession":
        """Retorna nova sessão com erro registrado."""
        return PipelineSession(
            session_id=self.session_id,
            started_at=self.started_at,
            ended_at=self.ended_at,
            processed_segments=self.processed_segments,
            processed_queries=self.processed_queries,
            presentations=self.presentations,
            errors=self.errors + 1,
            statistics=self.statistics,
            correlation_ids=self.correlation_ids,
        )

    def with_statistics(self, statistics: dict) -> "PipelineSession":
        """Retorna nova sessão com statistics atualizado."""
        return PipelineSession(
            session_id=self.session_id,
            started_at=self.started_at,
            ended_at=self.ended_at,
            processed_segments=self.processed_segments,
            processed_queries=self.processed_queries,
            presentations=self.presentations,
            errors=self.errors,
            statistics=statistics,
            correlation_ids=self.correlation_ids,
        )

    def with_ended(self, ended_at: float | None = None) -> "PipelineSession":
        """Finaliza a sessão."""
        return PipelineSession(
            session_id=self.session_id,
            started_at=self.started_at,
            ended_at=ended_at if ended_at is not None else time.time(),
            processed_segments=self.processed_segments,
            processed_queries=self.processed_queries,
            presentations=self.presentations,
            errors=self.errors,
            statistics=self.statistics,
            correlation_ids=self.correlation_ids,
        )

    # ------------------------------------------------------------------
    # Serialização
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "is_active": self.is_active,
            "duration_s": self.duration_s,
            "processed_segments": self.processed_segments,
            "processed_queries": self.processed_queries,
            "presentations": self.presentations,
            "errors": self.errors,
            "error_rate": self.error_rate,
            "presentation_rate": self.presentation_rate,
            "segments_per_minute": self.segments_per_minute,
            "queries_per_minute": self.queries_per_minute,
            "unique_correlations": self.unique_correlations,
            "statistics": dict(self.statistics),
            "correlation_ids": list(self.correlation_ids),
        }


def PipelineState_increment_query(session: PipelineSession) -> PipelineSession:
    """Helper interno para incrementar queries (legacy, usar with_query_processed)."""
    return session.with_query_processed()


__all__ = [
    "PipelineSession",
    "_default_session_id",
]
