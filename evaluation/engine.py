"""Engine de Continuous Evaluation.

Responsabilidade única:
  - Receber um EvaluationEvent e registrar EvaluationRecord.
  - Atualizar repository.
  - Nunca calcular métricas, relatórios ou regressões (isso é
    responsabilidade de MetricsCalculator, ReportGenerator,
    RegressionDetector).

Nunca conhece:
  - Searcher
  - Ranking
  - Holyrics
  - Parser
  - LLM
  - Embeddings
  - KnowledgeBase
  - Context Engine
  - Feedback Learning

O Engine apenas registra eventos. Métricas, relatórios e regressões
são calculados sob demanda por outros componentes.

Design:
  - record(event) → cria EvaluationRecord e persiste.
  - list_records() → tuple de registros.
  - reset() → limpa todos os registros.
  - Clock injetável para testes.
  - ID generator injetável para testes.
"""

from __future__ import annotations

import time
import uuid
from typing import Callable

from evaluation.dtos import EvaluationRecord, QueryClassification
from evaluation.events import (
    CandidateAccepted,
    CandidatePresented,
    CandidateRejected,
    EvaluationEvent,
    EvaluationReset,
    ManualCorrection,
    NoResultFound,
    SearchExecuted,
    SearchFailed,
)
from evaluation.metrics import (
    EVENT_CANDIDATE_ACCEPTED,
    EVENT_CANDIDATE_PRESENTED,
    EVENT_CANDIDATE_REJECTED,
    EVENT_MANUAL_CORRECTION,
    EVENT_NO_RESULT_FOUND,
    EVENT_SEARCH_EXECUTED,
    EVENT_SEARCH_FAILED,
)
from evaluation.repository import EvaluationRepository


# Tipo do gerador de IDs
IDGenerator = Callable[[], str]


def _default_id_generator() -> str:
    """Gerador de IDs padrão (UUID4)."""
    return str(uuid.uuid4())


class EvaluationEngine:
    """Engine que registra eventos de avaliação.

    Uso:
        engine = EvaluationEngine(repository)
        engine.record(SearchExecuted(query="pedro", timestamp=...))
        records = engine.list_records()

    Desacoplamento:
        - Não conhece nenhum outro componente do sistema.
        - Apenas registra eventos via repository.
    """

    def __init__(
        self,
        repository: EvaluationRepository,
        clock: Callable[[], float] = time.time,
        id_generator: IDGenerator = _default_id_generator,
    ) -> None:
        """Inicializa engine.

        Args:
            repository: repository de persistência.
            clock: função que retorna timestamp (para testes).
            id_generator: função que gera IDs únicos (para testes).
        """
        self._repo = repository
        self._clock = clock
        self._id_gen = id_generator

    @property
    def repository(self) -> EvaluationRepository:
        """Repository de persistência."""
        return self._repo

    # ------------------------------------------------------------------
    # Registro de eventos
    # ------------------------------------------------------------------

    def record(self, event: EvaluationEvent) -> EvaluationRecord:
        """Registra um evento e retorna o EvaluationRecord criado.

        Args:
            event: evento tipado (SearchExecuted, CandidateAccepted, etc.).

        Returns:
            EvaluationRecord criado e persistido.
        """
        # EvaluationReset é tratado separadamente
        if isinstance(event, EvaluationReset):
            self.reset()
            return EvaluationRecord(
                record_id=self._id_gen(),
                timestamp=event.timestamp if event.timestamp > 0 else self._clock(),
                event_type="evaluation_reset",
                query=event.query,
                classification=event.classification,
                context_signature=event.context_signature,
                operator_id=event.operator_id,
            )

        timestamp = event.timestamp if event.timestamp > 0 else self._clock()
        event_type, extra = self._extract_event_data(event)

        record = EvaluationRecord(
            record_id=self._id_gen(),
            timestamp=timestamp,
            event_type=event_type,
            query=event.query,
            classification=event.classification,
            candidate_id=extra.get("candidate_id", ""),
            context_signature=event.context_signature,
            book=extra.get("book", ""),
            operator_id=event.operator_id,
            duration_ms=extra.get("duration_ms", 0.0),
            metadata=extra.get("metadata", ()),
        )
        self._repo.add(record)
        return record

    def _extract_event_data(self, event: EvaluationEvent) -> tuple[str, dict]:
        """Extrai tipo e dados específicos do evento.

        Args:
            event: evento tipado.

        Returns:
            Tupla (event_type_str, dict_dados_extras).
        """
        if isinstance(event, SearchExecuted):
            return EVENT_SEARCH_EXECUTED, {
                "duration_ms": event.duration_ms,
                "book": event.book,
                "metadata": (("result_count", str(event.result_count)),),
            }
        if isinstance(event, CandidatePresented):
            return EVENT_CANDIDATE_PRESENTED, {
                "candidate_id": event.candidate_id,
                "metadata": (("rank_position", str(event.rank_position)),),
            }
        if isinstance(event, CandidateAccepted):
            return EVENT_CANDIDATE_ACCEPTED, {
                "candidate_id": event.candidate_id,
                "book": event.book,
            }
        if isinstance(event, CandidateRejected):
            return EVENT_CANDIDATE_REJECTED, {
                "candidate_id": event.candidate_id,
                "book": event.book,
            }
        if isinstance(event, ManualCorrection):
            return EVENT_MANUAL_CORRECTION, {
                "candidate_id": event.corrected_candidate_id,
                "book": event.book,
                "metadata": (
                    ("original_candidate_id", event.original_candidate_id),
                    ("corrected_candidate_id", event.corrected_candidate_id),
                ),
            }
        if isinstance(event, SearchFailed):
            return EVENT_SEARCH_FAILED, {
                "metadata": (("error_message", event.error_message),),
            }
        if isinstance(event, NoResultFound):
            return EVENT_NO_RESULT_FOUND, {
                "book": event.book,
            }
        # Tipo desconhecido — registrar como genérico
        return "unknown", {}

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    def list_records(self) -> tuple[EvaluationRecord, ...]:
        """Lista todos os registros."""
        return self._repo.list_all()

    def list_since(self, timestamp: float) -> tuple[EvaluationRecord, ...]:
        """Lista registros desde um timestamp."""
        return self._repo.list_since(timestamp)

    def list_between(
        self, start: float, end: float
    ) -> tuple[EvaluationRecord, ...]:
        """Lista registros em um intervalo temporal."""
        return self._repo.list_between(start, end)

    def get_record(self, record_id: str) -> EvaluationRecord | None:
        """Recupera um registro pelo ID."""
        return self._repo.get(record_id)

    def record_count(self) -> int:
        """Número total de registros."""
        return len(self._repo)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Limpa todos os registros."""
        self._repo.clear()

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Persiste em disco (delegado ao repository)."""
        self._repo.flush()


__all__ = ["EvaluationEngine"]
