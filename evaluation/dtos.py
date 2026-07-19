"""DTOs imutáveis do Continuous Evaluation.

Todos os DTOs são frozen dataclass (imutáveis, hashable, serializáveis).

DTOs:
  - QueryClassification: classificação do tipo de consulta.
  - EvaluationRecord: registro individual de um evento de avaliação.
  - EvaluationMetrics: métricas acumuladas (totais, taxas, agrupamentos).
  - EvaluationSummary: resumo agregado para relatórios.
  - EvaluationReport: relatório completo para auditoria.
  - TemporalSlice: fatia temporal das métricas (24h, 7d, 30d, all).
  - RegressionAlert: alerta de regressão detectada.

Design:
  - Todos frozen dataclass.
  - Coleções são tuples (imutáveis).
  - Nenhum estado mutável.
  - Serializáveis via to_dict / from_dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# QueryClassification — classificação do tipo de consulta
# ---------------------------------------------------------------------------


class QueryClassification(str, Enum):
    """Classificação do tipo de consulta.

    A arquitetura permite adicionar novos tipos sem quebrar compatibilidade.

    Valores:
        REFERENCE: referência bíblica direta (ex.: "João 3:16").
        BOOK: busca por livro (ex.: "João").
        CHARACTER: busca por personagem (ex.: "Pedro").
        CONCEPT: busca por conceito (ex.: "filho pródigo").
        THEME: busca por tema (ex.: "armadura de Deus").
        EVENT: busca por evento bíblico (ex.: "Pentecostes").
        UNKNOWN: classificação desconhecida/não determinada.
    """

    REFERENCE = "REFERENCE"
    BOOK = "BOOK"
    CHARACTER = "CHARACTER"
    CONCEPT = "CONCEPT"
    THEME = "THEME"
    EVENT = "EVENT"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# TemporalWindow — janela temporal para métricas
# ---------------------------------------------------------------------------


class TemporalWindow(str, Enum):
    """Janela temporal para consulta de métricas.

    Valores:
        LAST_24H: últimas 24 horas.
        LAST_7D: últimos 7 dias.
        LAST_30D: últimos 30 dias.
        ALL: desde o início (sem limite temporal).
    """

    LAST_24H = "LAST_24H"
    LAST_7D = "LAST_7D"
    LAST_30D = "LAST_30D"
    ALL = "ALL"


# ---------------------------------------------------------------------------
# EvaluationRecord — registro individual de um evento
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationRecord:
    """Registro individual de um evento de avaliação.

    Cada evento observado gera um EvaluationRecord. Os registros são
    imutáveis e serializáveis, permitindo auditoria completa.

    Atributos:
        record_id: ID único do registro (string).
        timestamp: timestamp do evento (segundos desde epoch).
        event_type: tipo do evento ("search_executed", "candidate_presented",
            "candidate_accepted", "candidate_rejected",
            "manual_correction", "search_failed", "no_result_found",
            "evaluation_reset").
        query: consulta normalizada do operador (lowercase, sem acento).
        classification: classificação da consulta (QueryClassification).
        candidate_id: ID do candidato envolvido (ou "" se não aplicável).
        context_signature: assinatura do contexto do sermão (ou "").
        book: nome do livro envolvido (ou "" se não aplicável).
        operator_id: ID do operador (para futura multi-operador, default "").
        duration_ms: duração da operação em ms (para buscas).
        metadata: tuple de pares (chave, valor) para dados extras.

    Imutável e hashable.
    """

    record_id: str
    timestamp: float
    event_type: str
    query: str = ""
    classification: QueryClassification = QueryClassification.UNKNOWN
    candidate_id: str = ""
    context_signature: str = ""
    book: str = ""
    operator_id: str = ""
    duration_ms: float = 0.0
    metadata: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        d = {
            "record_id": self.record_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "query": self.query,
            "classification": self.classification.value,
            "candidate_id": self.candidate_id,
            "context_signature": self.context_signature,
            "book": self.book,
            "operator_id": self.operator_id,
            "duration_ms": self.duration_ms,
            "metadata": list(self.metadata),
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> EvaluationRecord:
        return cls(
            record_id=d["record_id"],
            timestamp=d["timestamp"],
            event_type=d["event_type"],
            query=d.get("query", ""),
            classification=QueryClassification(d.get("classification", "UNKNOWN")),
            candidate_id=d.get("candidate_id", ""),
            context_signature=d.get("context_signature", ""),
            book=d.get("book", ""),
            operator_id=d.get("operator_id", ""),
            duration_ms=d.get("duration_ms", 0.0),
            metadata=tuple(tuple(p) for p in d.get("metadata", [])),
        )


# ---------------------------------------------------------------------------
# EvaluationMetrics — métricas acumuladas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationMetrics:
    """Métricas acumuladas de avaliação.

    Mantém contadores e taxas para um conjunto de registros. É imutável;
    atualizações retornam nova instância via dataclasses.replace.

    Atributos:
        total_searches: total de buscas executadas.
        total_presented: total de candidatos apresentados.
        total_accepted: total de candidatos aceitos.
        total_rejected: total de candidatos rejeitados.
        total_manual_corrections: total de correções manuais.
        total_no_result: total de buscas sem resultado.
        total_failed: total de buscas que falharam tecnicamente.
        total_duration_ms: duração total das buscas (ms).
        by_classification: tuple de pares (QueryClassification, count).
        by_book: tuple de pares (book_name, count).
        by_context: tuple de pares (context_signature, count).

    Properties:
        acceptance_rate: taxa de aceitação [0.0, 1.0].
        rejection_rate: taxa de rejeição [0.0, 1.0].
        precision: precisão = aceitos / (aceitos + rejeitados + correções).
        avg_duration_ms: tempo médio das buscas.
        no_result_rate: taxa de buscas sem resultado.
    """

    total_searches: int = 0
    total_presented: int = 0
    total_accepted: int = 0
    total_rejected: int = 0
    total_manual_corrections: int = 0
    total_no_result: int = 0
    total_failed: int = 0
    total_duration_ms: float = 0.0
    by_classification: tuple = field(default_factory=tuple)
    by_book: tuple = field(default_factory=tuple)
    by_context: tuple = field(default_factory=tuple)

    @property
    def acceptance_rate(self) -> float:
        if self.total_presented == 0:
            return 0.0
        return self.total_accepted / self.total_presented

    @property
    def rejection_rate(self) -> float:
        if self.total_presented == 0:
            return 0.0
        return self.total_rejected / self.total_presented

    @property
    def precision(self) -> float:
        """Precisão = aceitos / (aceitos + rejeitados + correções)."""
        denom = (self.total_accepted + self.total_rejected
                 + self.total_manual_corrections)
        if denom == 0:
            return 0.0
        return self.total_accepted / denom

    @property
    def avg_duration_ms(self) -> float:
        if self.total_searches == 0:
            return 0.0
        return self.total_duration_ms / self.total_searches

    @property
    def no_result_rate(self) -> float:
        if self.total_searches == 0:
            return 0.0
        return self.total_no_result / self.total_searches

    def to_dict(self) -> dict:
        return {
            "total_searches": self.total_searches,
            "total_presented": self.total_presented,
            "total_accepted": self.total_accepted,
            "total_rejected": self.total_rejected,
            "total_manual_corrections": self.total_manual_corrections,
            "total_no_result": self.total_no_result,
            "total_failed": self.total_failed,
            "total_duration_ms": self.total_duration_ms,
            "by_classification": [
                (c, n) for c, n in self.by_classification
            ],
            "by_book": [(b, n) for b, n in self.by_book],
            "by_context": [(c, n) for c, n in self.by_context],
        }

    @classmethod
    def from_dict(cls, d: dict) -> EvaluationMetrics:
        return cls(
            total_searches=d.get("total_searches", 0),
            total_presented=d.get("total_presented", 0),
            total_accepted=d.get("total_accepted", 0),
            total_rejected=d.get("total_rejected", 0),
            total_manual_corrections=d.get("total_manual_corrections", 0),
            total_no_result=d.get("total_no_result", 0),
            total_failed=d.get("total_failed", 0),
            total_duration_ms=d.get("total_duration_ms", 0.0),
            by_classification=tuple(
                (QueryClassification(c) if isinstance(c, str) else c, n)
                for c, n in d.get("by_classification", [])
            ),
            by_book=tuple(d.get("by_book", [])),
            by_context=tuple(d.get("by_context", [])),
        )


# ---------------------------------------------------------------------------
# TemporalSlice — fatia temporal das métricas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemporalSlice:
    """Fatia temporal das métricas.

    Representa as métricas em uma janela temporal específica.

    Atributos:
        window: janela temporal (TemporalWindow).
        start_timestamp: timestamp inicial da janela.
        end_timestamp: timestamp final da janela.
        metrics: EvaluationMetrics dentro da janela.
        record_count: número de registros na janela.
    """

    window: TemporalWindow
    start_timestamp: float
    end_timestamp: float
    metrics: EvaluationMetrics
    record_count: int

    def to_dict(self) -> dict:
        return {
            "window": self.window.value,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "metrics": self.metrics.to_dict(),
            "record_count": self.record_count,
        }


# ---------------------------------------------------------------------------
# EvaluationSummary — resumo agregado
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationSummary:
    """Resumo agregado de avaliação para relatórios.

    Atributos:
        total_records: total de registros avaliados.
        metrics: EvaluationMetrics agregadas.
        hardest_queries: tuple de (query, failure_count) — consultas
            mais difíceis (mais rejeições + correções + sem resultado).
        top_candidates: tuple de (candidate_id, win_count) — candidatos
            que mais vencem (mais aceitos).
        worst_books: tuple de (book, precision) — livros com menor
            precisão.
        worst_themes: tuple de (theme, precision) — temas mais
            problemáticos (reservado, vazio nesta fase).
    """

    total_records: int
    metrics: EvaluationMetrics
    hardest_queries: tuple = field(default_factory=tuple)
    top_candidates: tuple = field(default_factory=tuple)
    worst_books: tuple = field(default_factory=tuple)
    worst_themes: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "total_records": self.total_records,
            "metrics": self.metrics.to_dict(),
            "hardest_queries": list(self.hardest_queries),
            "top_candidates": list(self.top_candidates),
            "worst_books": list(self.worst_books),
            "worst_themes": list(self.worst_themes),
        }


# ---------------------------------------------------------------------------
# EvaluationReport — relatório completo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationReport:
    """Relatório completo de avaliação para auditoria.

    Atributos:
        generated_at: timestamp de geração do relatório.
        window: janela temporal do relatório.
        summary: EvaluationSummary agregado.
        temporal_slices: tuple de TemporalSlice (24h, 7d, 30d, all).
        regressions: tuple de RegressionAlert detectadas.
    """

    generated_at: float
    window: TemporalWindow
    summary: EvaluationSummary
    temporal_slices: tuple = field(default_factory=tuple)
    regressions: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "window": self.window.value,
            "summary": self.summary.to_dict(),
            "temporal_slices": [s.to_dict() for s in self.temporal_slices],
            "regressions": [r.to_dict() for r in self.regressions],
        }

    def to_text(self) -> str:
        """Gera relatório em texto legível.

        Exemplo:
            === Relatório de Avaliação ===
            Buscas: 1520
            Acertos: 1480
            Precisão: 97.4%
            Correções: 31
            Sem resultado: 9
            Tempo médio: 310 ms
        """
        m = self.summary.metrics
        lines = ["=== Relatório de Avaliação ==="]
        lines.append(f"Janela: {self.window.value}")
        lines.append(f"Buscas: {m.total_searches}")
        lines.append(f"Acertos: {m.total_accepted}")
        lines.append(f"Precisão: {m.precision * 100:.1f}%")
        lines.append(f"Correções: {m.total_manual_corrections}")
        lines.append(f"Sem resultado: {m.total_no_result}")
        lines.append(f"Tempo médio: {m.avg_duration_ms:.0f} ms")
        if self.summary.hardest_queries:
            lines.append("Consultas mais difíceis:")
            for q, n in self.summary.hardest_queries[:5]:
                lines.append(f"  - {q}: {n} falhas")
        if self.summary.worst_books:
            lines.append("Livros com menor precisão:")
            for b, p in self.summary.worst_books[:5]:
                lines.append(f"  - {b}: {p * 100:.1f}%")
        if self.regressions:
            lines.append("Regressões detectadas:")
            for r in self.regressions:
                lines.append(f"  - {r.metric_name}: {r.description}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# RegressionAlert — alerta de regressão
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegressionAlert:
    """Alerta de regressão detectada.

    Atributos:
        metric_name: nome da métrica que regrediu.
        description: descrição legível da regressão.
        previous_value: valor anterior da métrica.
        current_value: valor atual da métrica.
        threshold: threshold de regressão configurado.
        detected_at: timestamp da detecção.
        severity: severidade ("low", "medium", "high").
    """

    metric_name: str
    description: str
    previous_value: float
    current_value: float
    threshold: float
    detected_at: float
    severity: str = "low"

    def to_dict(self) -> dict:
        return {
            "metric_name": self.metric_name,
            "description": self.description,
            "previous_value": self.previous_value,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "detected_at": self.detected_at,
            "severity": self.severity,
        }


__all__ = [
    "QueryClassification",
    "TemporalWindow",
    "EvaluationRecord",
    "EvaluationMetrics",
    "TemporalSlice",
    "EvaluationSummary",
    "EvaluationReport",
    "RegressionAlert",
]
