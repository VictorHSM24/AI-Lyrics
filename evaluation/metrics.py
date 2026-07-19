"""Calculadora de métricas para Continuous Evaluation.

Responsabilidade única:
  - Receber uma coleção de EvaluationRecord.
  - Calcular EvaluationMetrics agregadas.
  - Calcular métricas por classificação, livro, contexto.
  - Calcular fatias temporais.
  - Calcular precisão por grupo.

Nenhuma regra de negócio além de cálculo de métricas.
Não conhece Engine, Repository, Reports, Regressions.

Design:
  - MetricsCalculator é stateless.
  - Recebe registros e retorna métricas (imutáveis).
  - Usa EvaluationPolicy para thresholds.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from evaluation.dtos import (
    EvaluationMetrics,
    EvaluationRecord,
    QueryClassification,
    TemporalSlice,
    TemporalWindow,
)
from evaluation.policy import EvaluationPolicy


# ---------------------------------------------------------------------------
# Nomes de tipos de evento (centralizados)
# ---------------------------------------------------------------------------

EVENT_SEARCH_EXECUTED = "search_executed"
EVENT_CANDIDATE_PRESENTED = "candidate_presented"
EVENT_CANDIDATE_ACCEPTED = "candidate_accepted"
EVENT_CANDIDATE_REJECTED = "candidate_rejected"
EVENT_MANUAL_CORRECTION = "manual_correction"
EVENT_SEARCH_FAILED = "search_failed"
EVENT_NO_RESULT_FOUND = "no_result_found"
EVENT_EVALUATION_RESET = "evaluation_reset"


class MetricsCalculator:
    """Calculadora de métricas a partir de EvaluationRecord.

    Uso:
        calc = MetricsCalculator()
        metrics = calc.calculate(records)
        slice_24h = calc.temporal_slice(records, TemporalWindow.LAST_24H, now)
    """

    def __init__(self, policy: EvaluationPolicy | None = None) -> None:
        self._policy = policy or EvaluationPolicy()

    @property
    def policy(self) -> EvaluationPolicy:
        return self._policy

    # ------------------------------------------------------------------
    # Cálculo de métricas agregadas
    # ------------------------------------------------------------------

    def calculate(self, records: tuple[EvaluationRecord, ...]) -> EvaluationMetrics:
        """Calcula métricas agregadas a partir de registros.

        Args:
            records: tuple de EvaluationRecord.

        Returns:
            EvaluationMetrics agregadas.
        """
        total_searches = 0
        total_presented = 0
        total_accepted = 0
        total_rejected = 0
        total_manual_corrections = 0
        total_no_result = 0
        total_failed = 0
        total_duration_ms = 0.0

        by_classification_count: dict[QueryClassification, int] = defaultdict(int)
        by_book_count: dict[str, int] = defaultdict(int)
        by_context_count: dict[str, int] = defaultdict(int)

        for r in records:
            if r.event_type == EVENT_SEARCH_EXECUTED:
                total_searches += 1
                total_duration_ms += r.duration_ms
                by_classification_count[r.classification] += 1
                if r.book:
                    by_book_count[r.book] += 1
                if r.context_signature:
                    by_context_count[r.context_signature] += 1
            elif r.event_type == EVENT_CANDIDATE_PRESENTED:
                total_presented += 1
            elif r.event_type == EVENT_CANDIDATE_ACCEPTED:
                total_accepted += 1
            elif r.event_type == EVENT_CANDIDATE_REJECTED:
                total_rejected += 1
            elif r.event_type == EVENT_MANUAL_CORRECTION:
                total_manual_corrections += 1
            elif r.event_type == EVENT_NO_RESULT_FOUND:
                total_no_result += 1
            elif r.event_type == EVENT_SEARCH_FAILED:
                total_failed += 1

        by_classification = tuple(sorted(
            by_classification_count.items(),
            key=lambda x: x[1],
            reverse=True,
        ))
        by_book = tuple(sorted(
            by_book_count.items(),
            key=lambda x: x[1],
            reverse=True,
        ))
        by_context = tuple(sorted(
            by_context_count.items(),
            key=lambda x: x[1],
            reverse=True,
        ))

        return EvaluationMetrics(
            total_searches=total_searches,
            total_presented=total_presented,
            total_accepted=total_accepted,
            total_rejected=total_rejected,
            total_manual_corrections=total_manual_corrections,
            total_no_result=total_no_result,
            total_failed=total_failed,
            total_duration_ms=total_duration_ms,
            by_classification=by_classification,
            by_book=by_book,
            by_context=by_context,
        )

    # ------------------------------------------------------------------
    # Fatias temporais
    # ------------------------------------------------------------------

    def temporal_slice(
        self,
        records: tuple[EvaluationRecord, ...],
        window: TemporalWindow,
        now: float,
    ) -> TemporalSlice:
        """Calcula métricas para uma janela temporal.

        Args:
            records: todos os registros disponíveis.
            window: janela temporal (LAST_24H, LAST_7D, etc.).
            now: timestamp atual.

        Returns:
            TemporalSlice com métricas da janela.
        """
        seconds = self._policy.window_seconds(window)
        if seconds == float("inf"):
            start = 0.0
        else:
            start = now - seconds
        filtered = tuple(r for r in records if r.timestamp >= start)
        metrics = self.calculate(filtered)
        return TemporalSlice(
            window=window,
            start_timestamp=start,
            end_timestamp=now,
            metrics=metrics,
            record_count=len(filtered),
        )

    def all_temporal_slices(
        self,
        records: tuple[EvaluationRecord, ...],
        now: float,
    ) -> tuple[TemporalSlice, ...]:
        """Calcula todas as fatias temporais suportadas.

        Args:
            records: todos os registros.
            now: timestamp atual.

        Returns:
            Tuple de TemporalSlice (24h, 7d, 30d, all).
        """
        return tuple(
            self.temporal_slice(records, w, now)
            for w in self._policy.supported_windows()
        )

    # ------------------------------------------------------------------
    # Precisão por grupo
    # ------------------------------------------------------------------

    def precision_by_book(
        self, records: tuple[EvaluationRecord, ...]
    ) -> tuple[tuple[str, float, int], ...]:
        """Calcula precisão por livro.

        Para cada livro, calcula:
            precisão = aceitos / (aceitos + rejeitados + correções)

        Args:
            records: registros a analisar.

        Returns:
            Tuple de (book, precision, total_events) ordenado por
            precisão crescente (menor precisão primeiro).
        """
        by_book: dict[str, dict[str, int]] = defaultdict(
            lambda: {"accepted": 0, "rejected": 0, "corrections": 0}
        )
        for r in records:
            if not r.book:
                continue
            if r.event_type == EVENT_CANDIDATE_ACCEPTED:
                by_book[r.book]["accepted"] += 1
            elif r.event_type == EVENT_CANDIDATE_REJECTED:
                by_book[r.book]["rejected"] += 1
            elif r.event_type == EVENT_MANUAL_CORRECTION:
                by_book[r.book]["corrections"] += 1

        results = []
        for book, counts in by_book.items():
            total = counts["accepted"] + counts["rejected"] + counts["corrections"]
            if total == 0:
                continue
            if not self._policy.is_book_confident(total):
                continue
            precision = counts["accepted"] / total
            results.append((book, precision, total))

        results.sort(key=lambda x: x[1])  # menor precisão primeiro
        return tuple(results)

    def precision_by_classification(
        self, records: tuple[EvaluationRecord, ...]
    ) -> tuple[tuple[QueryClassification, float, int], ...]:
        """Calcula precisão por classificação de consulta.

        Args:
            records: registros a analisar.

        Returns:
            Tuple de (classification, precision, total_events).
        """
        by_cls: dict[QueryClassification, dict[str, int]] = defaultdict(
            lambda: {"accepted": 0, "rejected": 0, "corrections": 0}
        )
        for r in records:
            if r.event_type == EVENT_CANDIDATE_ACCEPTED:
                by_cls[r.classification]["accepted"] += 1
            elif r.event_type == EVENT_CANDIDATE_REJECTED:
                by_cls[r.classification]["rejected"] += 1
            elif r.event_type == EVENT_MANUAL_CORRECTION:
                by_cls[r.classification]["corrections"] += 1

        results = []
        for cls, counts in by_cls.items():
            total = counts["accepted"] + counts["rejected"] + counts["corrections"]
            if total == 0:
                continue
            precision = counts["accepted"] / total
            results.append((cls, precision, total))

        results.sort(key=lambda x: x[1])
        return tuple(results)

    # ------------------------------------------------------------------
    # Consultas mais difíceis
    # ------------------------------------------------------------------

    def hardest_queries(
        self, records: tuple[EvaluationRecord, ...], limit: int | None = None
    ) -> tuple[tuple[str, int], ...]:
        """Identifica consultas com mais falhas.

        Falha = rejeição + correção manual + sem resultado.

        Args:
            records: registros a analisar.
            limit: número máximo de resultados (default: policy.top_queries_limit).

        Returns:
            Tuple de (query, failure_count) ordenado por falhas decrescente.
        """
        if limit is None:
            limit = self._policy.top_queries_limit

        failures: dict[str, int] = defaultdict(int)
        for r in records:
            if not r.query:
                continue
            if r.event_type in (
                EVENT_CANDIDATE_REJECTED,
                EVENT_MANUAL_CORRECTION,
                EVENT_NO_RESULT_FOUND,
            ):
                failures[r.query] += 1

        sorted_failures = sorted(
            failures.items(), key=lambda x: x[1], reverse=True
        )
        return tuple(sorted_failures[:limit])

    # ------------------------------------------------------------------
    # Candidatos que mais vencem
    # ------------------------------------------------------------------

    def top_candidates(
        self, records: tuple[EvaluationRecord, ...], limit: int | None = None
    ) -> tuple[tuple[str, int], ...]:
        """Identifica candidatos mais aceitos.

        Args:
            records: registros a analisar.
            limit: número máximo (default: policy.top_candidates_limit).

        Returns:
            Tuple de (candidate_id, win_count) ordenado por aceites decrescente.
        """
        if limit is None:
            limit = self._policy.top_candidates_limit

        wins: dict[str, int] = defaultdict(int)
        for r in records:
            if not r.candidate_id:
                continue
            if r.event_type == EVENT_CANDIDATE_ACCEPTED:
                wins[r.candidate_id] += 1

        sorted_wins = sorted(wins.items(), key=lambda x: x[1], reverse=True)
        return tuple(sorted_wins[:limit])


__all__ = ["MetricsCalculator"]
