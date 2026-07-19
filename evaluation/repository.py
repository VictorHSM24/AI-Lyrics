"""Repository de Continuous Evaluation.

Camada de abstração sobre EvaluationStore que define a interface de
persistência. Permite futura troca por SQLite sem alterar EvaluationEngine.

Responsabilidade:
  - Fornecer interface clara para persistência de EvaluationRecord.
  - Delegar para EvaluationStore (JSON hoje, SQLite no futuro).
  - Isolar o Engine de detalhes de persistência.

Design:
  - EvaluationRepository encapsula EvaluationStore.
  - Interface: add, get, list_all, list_since, list_between, clear.
  - Persistência automática opcional (auto_save).
  - Path do arquivo JSON configurável.
"""

from __future__ import annotations

import os
from typing import Protocol

from evaluation.dtos import EvaluationRecord
from evaluation.store import EvaluationStore


# ---------------------------------------------------------------------------
# Protocol (interface para futura implementação SQLite)
# ---------------------------------------------------------------------------


class EvaluationRepositoryProtocol(Protocol):
    """Interface que qualquer repository de avaliação deve implementar."""

    def add(self, record: EvaluationRecord) -> None:
        ...

    def get(self, record_id: str) -> EvaluationRecord | None:
        ...

    def list_all(self) -> tuple[EvaluationRecord, ...]:
        ...

    def list_since(self, timestamp: float) -> tuple[EvaluationRecord, ...]:
        ...

    def list_between(
        self, start: float, end: float
    ) -> tuple[EvaluationRecord, ...]:
        ...

    def clear(self) -> None:
        ...

    def flush(self) -> None:
        ...


# ---------------------------------------------------------------------------
# Implementação JSON
# ---------------------------------------------------------------------------


class EvaluationRepository:
    """Repository de avaliação com persistência JSON.

    Encapsula EvaluationStore e adiciona:
      - Persistência automática opcional.
      - Consultas temporais (list_since, list_between).
      - Interface clara para futura troca por SQLite.

    Uso:
        repo = EvaluationRepository("evaluation.json")
        repo.add(record)
        records = repo.list_since(timestamp)
        repo.flush()

    Com auto_save=True, cada add() persiste em disco imediatamente.
    Com auto_save=False (default), flush() deve ser chamado explicitamente.
    """

    def __init__(
        self,
        path: str | None = None,
        auto_save: bool = False,
    ) -> None:
        """Inicializa repository.

        Args:
            path: caminho do arquivo JSON. Se None, não persiste em disco.
            auto_save: se True, persiste a cada add(). Se False,
                flush() deve ser chamado explicitamente.
        """
        self._store = EvaluationStore()
        self._path = path
        self._auto_save = auto_save
        if path and os.path.exists(path):
            self._store.load(path)

    # ------------------------------------------------------------------
    # Operações CRUD
    # ------------------------------------------------------------------

    def add(self, record: EvaluationRecord) -> None:
        """Adiciona um registro.

        Se auto_save=True, persiste em disco imediatamente.
        """
        self._store.add(record)
        if self._auto_save and self._path:
            self._store.save(self._path)

    def get(self, record_id: str) -> EvaluationRecord | None:
        """Recupera um registro pelo ID."""
        return self._store.get(record_id)

    def has(self, record_id: str) -> bool:
        """Verifica se existe um registro com o ID."""
        return self._store.has(record_id)

    def list_all(self) -> tuple[EvaluationRecord, ...]:
        """Lista todos os registros."""
        return self._store.list_all()

    def list_since(self, timestamp: float) -> tuple[EvaluationRecord, ...]:
        """Lista registros com timestamp >= timestamp."""
        return self._store.list_since(timestamp)

    def list_between(
        self, start: float, end: float
    ) -> tuple[EvaluationRecord, ...]:
        """Lista registros dentro de um intervalo temporal."""
        return self._store.list_between(start, end)

    def list_by_event_type(self, event_type: str) -> tuple[EvaluationRecord, ...]:
        """Lista registros por tipo de evento."""
        return self._store.list_by_event_type(event_type)

    def list_by_query(self, query: str) -> tuple[EvaluationRecord, ...]:
        """Lista registros por consulta."""
        return self._store.list_by_query(query)

    def clear(self) -> None:
        """Remove todos os registros."""
        self._store.clear()
        if self._auto_save and self._path:
            self._store.save(self._path)

    def flush(self) -> None:
        """Persiste em disco explicitamente."""
        if self._path:
            self._store.save(self._path)

    # ------------------------------------------------------------------
    # Introspecção
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, record_id: str) -> bool:
        return record_id in self._store

    @property
    def path(self) -> str | None:
        """Caminho do arquivo JSON (ou None se em memória)."""
        return self._path

    @property
    def auto_save(self) -> bool:
        """Se True, persiste a cada add()."""
        return self._auto_save

    @property
    def store(self) -> EvaluationStore:
        """Store interno (para acesso direto em testes)."""
        return self._store


__all__ = ["EvaluationRepository", "EvaluationRepositoryProtocol"]
