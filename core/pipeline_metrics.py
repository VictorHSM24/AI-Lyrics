"""Métricas do pipeline (submódulo interno de core/pipeline.py).

Responsabilidade: acumular tempos e contadores por stage do pipeline,
calcular médias e produzir snapshots imutáveis para auditoria/log.

Este módulo é interno ao pipeline. Módulos externos não devem importá-lo
diretamente — a API pública do pipeline está em core/pipeline.py.

Limites explícitos (o que este módulo NÃO faz):
  - Não executa stages.
  - Não constrói LogEntry.
  - Não persiste métricas.
  - Não envia telemetria.
  - Não toma decisões baseadas nas métricas.

Design:
  - StageTiming é frozen (registro imutável de uma execução).
  - PipelineMetrics é mutável (acumulador vivo durante a execução).
  - PipelineMetricsSnapshot é frozen (ponto no tempo para log/auditoria).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

StageName = Literal["stt", "parser", "llm", "search", "decision", "holyrics"]


# ---------------------------------------------------------------------------
# StageTiming — registro imutável de uma execução de stage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageTiming:
    """Timing de uma execução individual de stage.

    Atributos:
        stage: nome do stage ("stt", "parser", "llm", "search",
            "decision", "holyrics").
        duration_ms: tempo de execução em milissegundos.
        success: True se o stage completou sem exceção.
        error_msg: mensagem de erro se success=False, else None.
    """

    stage: StageName
    duration_ms: float
    success: bool
    error_msg: str | None = None


# ---------------------------------------------------------------------------
# PipelineMetricsSnapshot — ponto no tempo imutável
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineMetricsSnapshot:
    """Snapshot imutável das métricas do pipeline.

    Produzido por PipelineMetrics.snapshot() para log/auditoria.
    Não deve ser mutado após criação.
    """

    total_utterances: int
    total_executes: int
    total_errors: int
    avg_stage_ms: dict[str, float] = field(default_factory=dict)
    stage_counts: dict[str, int] = field(default_factory=dict)
    stage_errors: dict[str, int] = field(default_factory=dict)
    stage_total_ms: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# PipelineMetrics — acumulador mutável
# ---------------------------------------------------------------------------


@dataclass
class PipelineMetrics:
    """Métricas acumuladas do pipeline durante a execução.

    Mutável: cada stage chama record() ao finalizar. snapshot() produz
    uma cópia imutável para log/auditoria sem expor o estado interno.

    Attributes:
        total_utterances: total de utterances processadas.
        total_executes: total de decisions executadas (outcome=execute).
        total_errors: total de erros em qualquer stage.
    """

    total_utterances: int = 0
    total_executes: int = 0
    total_errors: int = 0

    _stage_counts: dict[str, int] = field(default_factory=dict)
    _stage_errors: dict[str, int] = field(default_factory=dict)
    _stage_total_ms: dict[str, float] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    def record(self, timing: StageTiming) -> None:
        """Registra um StageTiming no acumulador.

        Atualiza contadores, erros e tempo acumulado por stage.
        Incrementa total_errors se timing.success=False.

        Args:
            timing: registro de execução de stage.
        """
        stage = timing.stage
        self._stage_counts[stage] = self._stage_counts.get(stage, 0) + 1
        self._stage_total_ms[stage] = (
            self._stage_total_ms.get(stage, 0.0) + timing.duration_ms
        )
        if not timing.success:
            self._stage_errors[stage] = self._stage_errors.get(stage, 0) + 1
            self.total_errors += 1
            logger.warning(
                "Stage %s failed in %.2f ms: %s",
                stage,
                timing.duration_ms,
                timing.error_msg,
            )

    def record_utterance(self) -> None:
        """Incrementa o contador de utterances processadas."""
        self.total_utterances += 1

    def record_execute(self) -> None:
        """Incrementa o contador de decisions executadas."""
        self.total_executes += 1

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    def avg_time_ms(self, stage: str) -> float:
        """Tempo médio (ms) de um stage.

        Returns:
            Média de duração em ms, ou 0.0 se o stage não foi executado.
        """
        count = self._stage_counts.get(stage, 0)
        if count == 0:
            return 0.0
        return self._stage_total_ms.get(stage, 0.0) / count

    def stage_count(self, stage: str) -> int:
        """Número de execuções de um stage."""
        return self._stage_counts.get(stage, 0)

    def stage_errors(self, stage: str) -> int:
        """Número de erros de um stage."""
        return self._stage_errors.get(stage, 0)

    def stage_total_time_ms(self, stage: str) -> float:
        """Tempo total acumulado (ms) de um stage."""
        return self._stage_total_ms.get(stage, 0.0)

    # ------------------------------------------------------------------
    # Propriedades derivadas — LLM
    # ------------------------------------------------------------------

    @property
    def llm_calls(self) -> int:
        """Total de chamadas ao LLM."""
        return self.stage_count("llm")

    @property
    def llm_failures(self) -> int:
        """Total de falhas do LLM."""
        return self.stage_errors("llm")

    @property
    def llm_success(self) -> int:
        """Total de chamadas bem-sucedidas ao LLM."""
        return self.llm_calls - self.llm_failures

    @property
    def llm_avg_latency_ms(self) -> float:
        """Latência média (ms) das chamadas ao LLM."""
        return self.avg_time_ms("llm")

    # ------------------------------------------------------------------
    # Snapshot imutável
    # ------------------------------------------------------------------

    def snapshot(self) -> PipelineMetricsSnapshot:
        """Produz um snapshot imutável das métricas atuais.

        O snapshot é uma cópia profunda dos dicionários internos —
        mutações posteriores em PipelineMetrics não afetam snapshots
        já produzidos.

        Returns:
            PipelineMetricsSnapshot com o estado atual.
        """
        return PipelineMetricsSnapshot(
            total_utterances=self.total_utterances,
            total_executes=self.total_executes,
            total_errors=self.total_errors,
            avg_stage_ms={
                s: self.avg_time_ms(s) for s in self._stage_counts
            },
            stage_counts=dict(self._stage_counts),
            stage_errors=dict(self._stage_errors),
            stage_total_ms=dict(self._stage_total_ms),
        )

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Zera todas as métricas acumuladas."""
        self.total_utterances = 0
        self.total_executes = 0
        self.total_errors = 0
        self._stage_counts.clear()
        self._stage_errors.clear()
        self._stage_total_ms.clear()
