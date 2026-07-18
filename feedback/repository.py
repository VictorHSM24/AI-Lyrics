"""Repository de Feedback Learning.

Camada de abstração sobre FeedbackStore que define a interface de
persistência. Permite futura troca por SQLite sem alterar FeedbackEngine.

Responsabilidade:
  - Fornecer interface clara para persistência de FeedbackStatistics.
  - Delegar para FeedbackStore (JSON hoje, SQLite no futuro).
  - Isolar o Engine de detalhes de persistência.

Design:
  - FeedbackRepository encapsula FeedbackStore.
  - Interface: get, save, delete, list_all, list_by_query, clear.
  - Persistência automática opcional (auto_save).
  - Path do arquivo JSON configurável.

Futura troca por SQLite:
  - Criar FeedbackSQLiteRepository implementando a mesma interface.
  - Engine não muda — apenas a instância do repository.
"""

from __future__ import annotations

import os
from typing import Protocol

from feedback.dtos import FeedbackKey, FeedbackScope, FeedbackStatistics
from feedback.store import FeedbackStore


# ---------------------------------------------------------------------------
# Protocol (interface para futura implementação SQLite)
# ---------------------------------------------------------------------------


class FeedbackRepositoryProtocol(Protocol):
    """Interface que qualquer repository de feedback deve implementar.

    Permite futura troca por SQLite sem alterar o Engine.
    """

    def get(self, key: FeedbackKey) -> FeedbackStatistics | None:
        ...

    def save(self, stats: FeedbackStatistics) -> None:
        ...

    def delete(self, key: FeedbackKey) -> bool:
        ...

    def list_all(self) -> tuple[FeedbackStatistics, ...]:
        ...

    def list_by_query(self, query: str, scope: FeedbackScope) -> tuple[FeedbackStatistics, ...]:
        ...

    def clear(self) -> None:
        ...

    def flush(self) -> None:
        ...


# ---------------------------------------------------------------------------
# Implementação JSON
# ---------------------------------------------------------------------------


class FeedbackRepository:
    """Repository de feedback com persistência JSON.

    Encapsula FeedbackStore e adiciona:
      - Persistência automática opcional.
      - Consultas por query/scope.
      - Interface clara para futura troca por SQLite.

    Uso:
        repo = FeedbackRepository("feedback.json")
        repo.save(stats)
        stats = repo.get(key)
        repo.flush()  # salva em disco

    Com auto_save=True, cada save() persiste em disco imediatamente.
    Com auto_save=False (default), flush() deve ser chamado explicitamente.
    """

    def __init__(
        self,
        path: str | None = None,
        auto_save: bool = False,
    ) -> None:
        """Inicializa repository.

        Args:
            path: caminho do arquivo JSON. Se None, não persiste em disco
                (apenas em memória, útil para testes).
            auto_save: se True, persiste a cada save(). Se False,
                flush() deve ser chamado explicitamente.
        """
        self._store = FeedbackStore()
        self._path = path
        self._auto_save = auto_save
        if path and os.path.exists(path):
            self._store.load(path)

    # ------------------------------------------------------------------
    # Operações CRUD
    # ------------------------------------------------------------------

    def get(self, key: FeedbackKey) -> FeedbackStatistics | None:
        """Recupera estatísticas para uma chave."""
        return self._store.get(key)

    def save(self, stats: FeedbackStatistics) -> None:
        """Armazena/atualiza estatísticas.

        Se auto_save=True, persiste em disco imediatamente.
        """
        self._store.put(stats.key, stats)
        if self._auto_save and self._path:
            self._store.save(self._path)

    def delete(self, key: FeedbackKey) -> bool:
        """Remove estatísticas para uma chave."""
        result = self._store.delete(key)
        if result and self._auto_save and self._path:
            self._store.save(self._path)
        return result

    def list_all(self) -> tuple[FeedbackStatistics, ...]:
        """Lista todas as estatísticas."""
        return self._store.list_all()

    def list_by_query(
        self, query: str, scope: FeedbackScope
    ) -> tuple[FeedbackStatistics, ...]:
        """Lista estatísticas para uma query e scope específicos.

        Útil para consultar todas as preferências para uma dada consulta,
        independentemente do contexto ou candidato.

        Args:
            query: consulta normalizada.
            scope: escopo (GLOBAL, SESSION, etc.).

        Returns:
            Tuple de FeedbackStatistics matching.
        """
        return tuple(
            stats for stats in self._store
            if stats.key.query == query and stats.key.scope == scope
        )

    def list_by_scope(self, scope: FeedbackScope) -> tuple[FeedbackStatistics, ...]:
        """Lista todas as estatísticas de um escopo."""
        return tuple(stats for stats in self._store if stats.key.scope == scope)

    def clear(self) -> None:
        """Remove todas as estatísticas."""
        self._store.clear()
        if self._auto_save and self._path:
            self._store.save(self._path)

    def flush(self) -> None:
        """Persiste em disco explicitamente (se path configurado)."""
        if self._path:
            self._store.save(self._path)

    # ------------------------------------------------------------------
    # Introspecção
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: FeedbackKey) -> bool:
        return key in self._store

    @property
    def path(self) -> str | None:
        """Caminho do arquivo JSON (ou None se em memória)."""
        return self._path

    @property
    def auto_save(self) -> bool:
        """Se True, persiste a cada save()."""
        return self._auto_save

    @property
    def store(self) -> FeedbackStore:
        """Store interno (para acesso direto em testes)."""
        return self._store


__all__ = ["FeedbackRepository", "FeedbackRepositoryProtocol"]
