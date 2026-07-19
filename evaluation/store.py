"""Store de armazenamento puro para Continuous Evaluation.

Responsabilidade única:
  - Armazenar e recuperar EvaluationRecord.
  - Persistir em JSON.
  - Carregar de JSON.

Nenhuma regra de negócio aqui:
  - Não calcula métricas.
  - Não detecta regressões.
  - Não gera relatórios.
  - Não conhece Engine, Metrics, Reports, etc.

Design:
  - EvaluationStore mantém uma lista interna de EvaluationRecord.
  - Operações são explícitas: add, get, list, clear, filter.
  - Persistência via JSON (load/save).
  - Interface permite futura troca por SQLite sem alterar Engine.
"""

from __future__ import annotations

import json
import os
from typing import Iterator

from evaluation.dtos import EvaluationRecord


class EvaluationStore:
    """Armazenamento puro de EvaluationRecord.

    Mantém uma lista interna de registros. Não contém regra de
    negócio — apenas CRUD e persistência.

    Uso:
        store = EvaluationStore()
        store.add(record)
        record = store.get(record_id)
        records = store.list_all()
        store.save("evaluation.json")
        store.load("evaluation.json")
    """

    def __init__(self) -> None:
        """Inicializa store vazio."""
        self._records: list[EvaluationRecord] = []
        self._by_id: dict[str, EvaluationRecord] = {}

    # ------------------------------------------------------------------
    # Operações CRUD
    # ------------------------------------------------------------------

    def add(self, record: EvaluationRecord) -> None:
        """Adiciona um registro ao store.

        Args:
            record: EvaluationRecord a adicionar.
        """
        self._records.append(record)
        self._by_id[record.record_id] = record

    def get(self, record_id: str) -> EvaluationRecord | None:
        """Recupera um registro pelo ID.

        Args:
            record_id: ID do registro.

        Returns:
            EvaluationRecord ou None se não existe.
        """
        return self._by_id.get(record_id)

    def has(self, record_id: str) -> bool:
        """Verifica se existe um registro com o ID."""
        return record_id in self._by_id

    def list_all(self) -> tuple[EvaluationRecord, ...]:
        """Lista todos os registros (em ordem de inserção)."""
        return tuple(self._records)

    def list_since(self, timestamp: float) -> tuple[EvaluationRecord, ...]:
        """Lista registros com timestamp >= timestamp.

        Args:
            timestamp: timestamp mínimo (inclusive).

        Returns:
            Tuple de registros desde o timestamp.
        """
        return tuple(r for r in self._records if r.timestamp >= timestamp)

    def list_between(
        self, start: float, end: float
    ) -> tuple[EvaluationRecord, ...]:
        """Lista registros dentro de um intervalo temporal.

        Args:
            start: timestamp mínimo (inclusive).
            end: timestamp máximo (exclusive).

        Returns:
            Tuple de registros no intervalo.
        """
        return tuple(r for r in self._records if start <= r.timestamp < end)

    def list_by_event_type(self, event_type: str) -> tuple[EvaluationRecord, ...]:
        """Lista registros por tipo de evento.

        Args:
            event_type: tipo do evento ("search_executed", etc.).

        Returns:
            Tuple de registros do tipo especificado.
        """
        return tuple(r for r in self._records if r.event_type == event_type)

    def list_by_query(self, query: str) -> tuple[EvaluationRecord, ...]:
        """Lista registros por consulta normalizada.

        Args:
            query: consulta normalizada.

        Returns:
            Tuple de registros para a consulta.
        """
        return tuple(r for r in self._records if r.query == query)

    def clear(self) -> None:
        """Remove todos os registros."""
        self._records.clear()
        self._by_id.clear()

    def __len__(self) -> int:
        """Número de registros armazenados."""
        return len(self._records)

    def __iter__(self) -> Iterator[EvaluationRecord]:
        """Itera sobre os registros armazenados."""
        return iter(self._records)

    def __contains__(self, record_id: str) -> bool:
        """Verifica se o ID existe (suporta `in`)."""
        return record_id in self._by_id

    # ------------------------------------------------------------------
    # Persistência JSON
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Salva todos os registros em arquivo JSON.

        Args:
            path: caminho do arquivo JSON.
        """
        data = {
            "version": 1,
            "records": [r.to_dict() for r in self._records],
        }
        dir_path = os.path.dirname(path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, path: str) -> None:
        """Carrega registros de arquivo JSON.

        Substitui o conteúdo atual. Se o arquivo não existe, mantém vazio.

        Args:
            path: caminho do arquivo JSON.
        """
        if not os.path.exists(path):
            self.clear()
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.clear()
        records = data.get("records", [])
        for r in records:
            record = EvaluationRecord.from_dict(r)
            self.add(record)

    def to_json(self) -> str:
        """Serializa para string JSON."""
        data = {
            "version": 1,
            "records": [r.to_dict() for r in self._records],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    def from_json(self, json_str: str) -> None:
        """Desserializa de string JSON. Substitui o conteúdo atual."""
        data = json.loads(json_str)
        self.clear()
        records = data.get("records", [])
        for r in records:
            record = EvaluationRecord.from_dict(r)
            self.add(record)


__all__ = ["EvaluationStore"]
