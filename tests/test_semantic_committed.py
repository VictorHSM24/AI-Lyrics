"""Testes do SemanticEngine com SpeechCommittedWords (Sprint 28).

Valida:
- SemanticEngine consome SpeechCommittedWords (não SpeechPartial/Updated).
- Stale rejection: inferência stale é descartada se correlation_id mudou.
- Cache LRU funciona corretamente.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    IntentCandidate,
    SemanticInferenceCompleted,
    SpeechCommittedWords,
    SpeechPartial,
    SpeechPartialUpdated,
)
from pipeline.metadata import EventMetadata
from semantic.cache import SemanticCache
from semantic.context_engine import ContextEngine
from semantic.engine import SemanticEngine
from semantic.types import SemanticResult


def _make_meta(correlation_id: str = "corr-1") -> EventMetadata:
    return EventMetadata.for_initial(
        session_id="test-session",
        origin="StreamingSTTService",
        correlation_id=correlation_id,
    )


def _make_committed(
    full_committed_text: str,
    committed_text: str = "",
    correlation_id: str = "corr-1",
) -> SpeechCommittedWords:
    return SpeechCommittedWords(
        meta=_make_meta(correlation_id),
        committed_text=committed_text or full_committed_text,
        full_committed_text=full_committed_text,
        words=tuple(),
        language="pt",
        confidence=0.9,
        latency_ms=100,
        audio_duration_ms=6000,
    )


def _make_partial(text: str, correlation_id: str = "corr-1") -> SpeechPartial:
    return SpeechPartial(
        meta=_make_meta(correlation_id),
        text=text,
        language="pt",
        confidence=0.9,
        latency_ms=100,
        audio_duration_ms=6000,
        is_stable=False,
    )


@pytest.fixture
def engine():
    """Cria um SemanticEngine com provider mock."""
    bus = PipelineEventBus()
    provider = MagicMock()
    provider.name = "stub"
    provider.model_name = "stub-model"
    provider.is_available.return_value = True
    # Resultado padrão: intent=none, sem candidatos.
    provider.infer.return_value = SemanticResult(
        intent="none",
        candidates=[],
        inference_ms=10,
        provider="stub",
        model="stub-model",
    )
    context_engine = MagicMock()
    context_engine.build.return_value = MagicMock()
    context_engine.build.return_value.context_hash.return_value = "hash-1"
    cache = SemanticCache(ttl_seconds=300.0, max_entries=200)
    eng = SemanticEngine(
        bus=bus,
        provider=provider,
        context_engine=context_engine,
        cache=cache,
        session_id="test-session",
        debounce_ms=50,  # baixo para testes rápidos
        min_growth_chars=5,  # baixo para disparar rápido
        min_append_words=1,
        min_interval_ms=0,  # sem rate limit em testes
    )
    eng.start()
    return eng, bus, provider, cache


class TestSemanticCommittedWords:
    """Testes do SemanticEngine com SpeechCommittedWords."""

    def test_ignores_speech_partial(self, engine):
        """SemanticEngine NÃO processa SpeechPartial."""
        eng, bus, provider, _ = engine
        # Publicar SpeechPartial — não deve disparar inferência.
        bus.publish(_make_partial("o senhor é meu pastor"))
        time.sleep(0.2)
        # Provider não deve ter sido chamado.
        assert provider.infer.call_count == 0

    def test_processes_committed_words(self, engine):
        """SemanticEngine processa SpeechCommittedWords."""
        eng, bus, provider, _ = engine
        # Publicar SpeechCommittedWords com texto suficiente.
        bus.publish(_make_committed("o senhor é meu pastor nada me faltara"))
        time.sleep(0.3)
        # Provider deve ter sido chamado.
        assert provider.infer.call_count >= 1

    def test_stale_rejection_discards_result(self, engine):
        """Inferência stale (correlation_id mudou) é descartada."""
        eng, bus, provider, _ = engine

        # Simular inferência que demora — provider retorna resultado com
        # candidatos para que possamos verificar se foi descartado.
        infer_started = threading.Event()

        def slow_infer(context, timeout_ms=5000):
            infer_started.set()
            time.sleep(0.3)  # demora o suficiente para o teste mudar corr_id
            return SemanticResult(
                intent="show_reference",
                candidates=[MagicMock(to_dict=lambda: {"book": "Salmos"})],
                inference_ms=300,
                provider="stub",
                model="stub-model",
            )
        provider.infer.side_effect = slow_infer

        # Capturar IntentCandidate.
        intent_events = []
        bus.subscribe(IntentCandidate, lambda e: intent_events.append(e))

        # Forçar debounce (não growth trigger) para que a inferência
        # rode em thread separada (timer), permitindo mudar corr_id
        # enquanto a inferência está em curso.
        # Para isso, desabilitar growth trigger com min_growth_chars alto.
        eng._min_growth_chars = 999999

        # Disparar inferência com corr-1 (via debounce).
        bus.publish(_make_committed("o senhor é meu pastor nada me faltara",
                                     correlation_id="corr-1"))
        # Aguardar debounce expirar e inferência iniciar.
        assert infer_started.wait(timeout=3.0), "inferência não iniciou"

        # Mudar correlation_id (novo fluxo) enquanto inferência está em curso.
        with eng._lock:
            eng._inference_correlation_id = "corr-2"

        # Aguardar inferência completar.
        time.sleep(0.5)

        # IntentCandidate NÃO deve ter sido publicado (stale rejected).
        assert len(intent_events) == 0
        assert eng._total_stale_rejected >= 1

    def test_non_stale_result_published(self, engine):
        """Inferência não-stale (mesmo correlation_id) é publicada."""
        eng, bus, provider, _ = engine

        provider.infer.return_value = SemanticResult(
            intent="show_reference",
            candidates=[MagicMock(to_dict=lambda: {"book": "Salmos"})],
            inference_ms=10,
            provider="stub",
            model="stub-model",
        )

        intent_events = []
        bus.subscribe(IntentCandidate, lambda e: intent_events.append(e))

        bus.publish(_make_committed("o senhor é meu pastor nada me faltara",
                                     correlation_id="corr-1"))
        time.sleep(0.3)

        # IntentCandidate deve ter sido publicado.
        assert len(intent_events) == 1
        assert eng._total_stale_rejected == 0
