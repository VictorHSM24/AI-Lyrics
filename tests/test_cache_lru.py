"""Testes do SemanticCache LRU (Sprint 28).

Valida:
- Cache LRU evicta entradas mais antigas quando excede max_entries.
- TTL expira entradas.
- Hit/miss tracking.
- max_entries default = 200 (conforme plano).
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from semantic.cache import SemanticCache
from semantic.types import SemanticResult


def _make_result(intent: str = "none") -> SemanticResult:
    return SemanticResult(
        intent=intent,
        candidates=[],
        inference_ms=10,
        provider="stub",
        model="stub-model",
    )


class TestCacheLRU:
    """Testes do cache LRU."""

    def test_default_max_entries_is_200(self):
        """Default max_entries = 200 conforme plano Sprint 28."""
        cache = SemanticCache()
        assert cache.stats()["max_entries"] == 200

    def test_lru_evicts_oldest(self):
        """LRU evicta a entrada menos recentemente usada."""
        cache = SemanticCache(ttl_seconds=300.0, max_entries=3)

        cache.put("hash-1", _make_result("a"))
        cache.put("hash-2", _make_result("b"))
        cache.put("hash-3", _make_result("c"))

        # Acessar hash-1 para torná-la mais recente (move to end).
        assert cache.get("hash-1") is not None

        # Adicionar hash-4 — deve evictar hash-2 (LRU = menos recente).
        cache.put("hash-4", _make_result("d"))

        assert cache.get("hash-2") is None  # evictada
        assert cache.get("hash-1") is not None  # ainda presente
        assert cache.get("hash-3") is not None  # ainda presente
        assert cache.get("hash-4") is not None  # recém adicionada

    def test_ttl_expires_entries(self):
        """Entradas expiram após TTL."""
        cache = SemanticCache(ttl_seconds=0.1, max_entries=10)
        cache.put("hash-1", _make_result("a"))
        assert cache.get("hash-1") is not None
        time.sleep(0.15)
        assert cache.get("hash-1") is None  # expirada

    def test_hit_miss_tracking(self):
        """Hit e miss são rastreados corretamente."""
        cache = SemanticCache(ttl_seconds=300.0, max_entries=10)
        cache.put("hash-1", _make_result("a"))

        assert cache.get("hash-1") is not None  # hit
        assert cache.get("hash-2") is None  # miss

        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_clear_resets_cache(self):
        """clear() remove todas as entradas e reseta stats."""
        cache = SemanticCache(ttl_seconds=300.0, max_entries=10)
        cache.put("hash-1", _make_result("a"))
        cache.get("hash-1")  # hit

        cache.clear()

        # Após clear, a entrada não existe mais.
        assert cache.get("hash-1") is None
        stats = cache.stats()
        assert stats["entries"] == 0
        # clear reseta hits/misses, mas o get acima conta como miss.
        assert stats["hits"] == 0
        assert stats["misses"] == 1  # miss do get após clear

    def test_put_overwrites_existing(self):
        """put sobrescreve entrada existente."""
        cache = SemanticCache(ttl_seconds=300.0, max_entries=10)
        cache.put("hash-1", _make_result("a"))
        cache.put("hash-1", _make_result("b"))

        result = cache.get("hash-1")
        assert result is not None
        assert result.intent == "b"
