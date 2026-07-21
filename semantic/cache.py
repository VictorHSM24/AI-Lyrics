"""semantic/cache.py — Cache de inferências semânticas (Sprint 20, Etapa 8).

Responsabilidade:
  - Cachear SemanticResult por hash do contexto.
  - Evitar consultar o LLM quando o mesmo contexto já foi processado.
  - TTL configurável (default 5 minutos).
  - Limite de entradas (default 256) para evitar crescimento infinito.

Implementação:
  - Cache LRU simples com dict + OrderedDict.
  - Hash via SemanticContext.context_hash().
  - Thread-safe via Lock (EventBus é síncrono, mas protege contra
    futuros usos async).

Sprint 20 — Semantic Understanding Engine.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from semantic.types import SemanticResult

logger = logging.getLogger(__name__)

__all__ = ["SemanticCache", "CacheEntry"]


class CacheEntry:
    """Entrada do cache."""

    __slots__ = ("result", "expires_at", "hits")

    def __init__(self, result: SemanticResult, ttl_seconds: float) -> None:
        self.result = result
        self.expires_at = time.monotonic() + ttl_seconds
        self.hits = 0

    @property
    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at


class SemanticCache:
    """Cache LRU com TTL para resultados semânticos.

    Args:
        ttl_seconds: tempo de vida de cada entrada (default 300s = 5min).
        max_entries: máximo de entradas (default 256).
    """

    def __init__(
        self,
        ttl_seconds: float = 300.0,
        max_entries: int = 256,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, context_hash: str) -> SemanticResult | None:
        """Retorna resultado cacheado se válido, None caso contrário."""
        with self._lock:
            entry = self._store.get(context_hash)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired:
                del self._store[context_hash]
                self._misses += 1
                return None
            # Move to end (LRU).
            self._store.move_to_end(context_hash)
            entry.hits += 1
            self._hits += 1
            return entry.result

    def put(self, context_hash: str, result: SemanticResult) -> None:
        """Armazena resultado no cache."""
        with self._lock:
            # Evict se exceder max_entries.
            while len(self._store) >= self._max:
                self._store.popitem(last=False)  # Remove oldest (LRU)
            self._store[context_hash] = CacheEntry(result, self._ttl)

    def clear(self) -> None:
        """Limpa o cache."""
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, Any]:
        """Estatísticas do cache."""
        with self._lock:
            return {
                "entries": len(self._store),
                "max_entries": self._max,
                "ttl_seconds": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / max(self._hits + self._misses, 1),
            }
