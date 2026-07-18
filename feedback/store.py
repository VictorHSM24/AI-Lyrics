"""Store de armazenamento puro para Feedback Learning.

Responsabilidade única:
  - Armazenar e recuperar FeedbackStatistics.
  - Persistir em JSON.
  - Carregar de JSON.

Nenhuma regra de negócio aqui:
  - Não calcula pesos.
  - Não aplica decaimento.
  - Não decide bônus.
  - Não conhece Ranking, Searcher, Engine, etc.

Design:
  - FeedbackStore mantém um dict interno {FeedbackKey: FeedbackStatistics}.
  - Operações são explícitas: get, put, delete, list, clear.
  - Persistência via JSON (load/save).
  - Interface permite futura troca por SQLite sem alterar Engine.
"""

from __future__ import annotations

import json
import os
from typing import Iterator

from feedback.dtos import FeedbackKey, FeedbackStatistics


class FeedbackStore:
    """Armazenamento puro de FeedbackStatistics.

    Mantém um dict interno mapeando FeedbackKey → FeedbackStatistics.
    Não contém regra de negócio — apenas CRUD e persistência.

    Uso:
        store = FeedbackStore()
        store.put(key, stats)
        stats = store.get(key)
        store.save("feedback.json")
        store.load("feedback.json")
    """

    def __init__(self) -> None:
        """Inicializa store vazio."""
        self._data: dict[FeedbackKey, FeedbackStatistics] = {}

    # ------------------------------------------------------------------
    # Operações CRUD
    # ------------------------------------------------------------------

    def get(self, key: FeedbackKey) -> FeedbackStatistics | None:
        """Recupera estatísticas para uma chave.

        Args:
            key: FeedbackKey.

        Returns:
            FeedbackStatistics ou None se não existe.
        """
        return self._data.get(key)

    def put(self, key: FeedbackKey, stats: FeedbackStatistics) -> None:
        """Armazena/atualiza estatísticas para uma chave.

        Args:
            key: FeedbackKey.
            stats: FeedbackStatistics a armazenar.
        """
        self._data[key] = stats

    def delete(self, key: FeedbackKey) -> bool:
        """Remove estatísticas para uma chave.

        Args:
            key: FeedbackKey.

        Returns:
            True se removido, False se não existia.
        """
        if key in self._data:
            del self._data[key]
            return True
        return False

    def has(self, key: FeedbackKey) -> bool:
        """Verifica se existe estatísticas para uma chave."""
        return key in self._data

    def list_keys(self) -> tuple[FeedbackKey, ...]:
        """Lista todas as chaves armazenadas."""
        return tuple(self._data.keys())

    def list_all(self) -> tuple[FeedbackStatistics, ...]:
        """Lista todas as estatísticas armazenadas."""
        return tuple(self._data.values())

    def clear(self) -> None:
        """Remove todas as estatísticas."""
        self._data.clear()

    def __len__(self) -> int:
        """Número de entradas armazenadas."""
        return len(self._data)

    def __iter__(self) -> Iterator[FeedbackStatistics]:
        """Itera sobre as estatísticas armazenadas."""
        return iter(self._data.values())

    def __contains__(self, key: FeedbackKey) -> bool:
        """Verifica se a chave existe (suporta `in`)."""
        return key in self._data

    # ------------------------------------------------------------------
    # Persistência JSON
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Salva todas as estatísticas em arquivo JSON.

        Args:
            path: caminho do arquivo JSON.
        """
        data = {
            "version": 1,
            "entries": [stats.to_dict() for stats in self._data.values()],
        }
        # Garantir que o diretório existe
        dir_path = os.path.dirname(path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, path: str) -> None:
        """Carrega estatísticas de arquivo JSON.

        Substitui o conteúdo atual. Se o arquivo não existe, mantém vazio.

        Args:
            path: caminho do arquivo JSON.
        """
        if not os.path.exists(path):
            self._data.clear()
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._data.clear()
        entries = data.get("entries", [])
        for entry in entries:
            stats = FeedbackStatistics.from_dict(entry)
            self._data[stats.key] = stats

    def to_json(self) -> str:
        """Serializa para string JSON (para testes e transmissão)."""
        data = {
            "version": 1,
            "entries": [stats.to_dict() for stats in self._data.values()],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    def from_json(self, json_str: str) -> None:
        """Desserializa de string JSON. Substitui o conteúdo atual."""
        data = json.loads(json_str)
        self._data.clear()
        entries = data.get("entries", [])
        for entry in entries:
            stats = FeedbackStatistics.from_dict(entry)
            self._data[stats.key] = stats


__all__ = ["FeedbackStore"]
