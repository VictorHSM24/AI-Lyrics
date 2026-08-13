"""Sprint 22.0 — Teste de integração end-to-end do modo RAG.

Valida o fluxo completo:
1. BibleRetriever aquecido.
2. SemanticEngine com bible_retriever injetado.
3. SpeechPartialUpdated publicado → SemanticEngine recupera candidatos do
   BibleRetriever → injeta no contexto → StubProvider escolhe top
   candidato → IntentCandidate publicado.
4. Modo Atual (sem retriever) ainda funciona (compatibilidade).
5. Fallback quando retriever retorna 0 candidatos.
"""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    SpeechCommittedWords,
    IntentCandidate,
)
from pipeline.metadata import EventMetadata
from semantic.engine import SemanticEngine
from semantic.local_provider import StubProvider
from semantic.context_engine import ContextEngine
from semantic.cache import SemanticCache
from knowledge import warmup_bible_retriever
from config.loader import load_books


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_meta(
    session_id: str = "test-session",
    origin: str = "StreamingSTTService",
    correlation_id: str | None = None,
) -> EventMetadata:
    return EventMetadata.for_initial(
        session_id=session_id, origin=origin,
        correlation_id=correlation_id,
    )


def _make_committed(
    text: str,
    correlation_id: str | None = None,
) -> SpeechCommittedWords:
    """Cria SpeechCommittedWords (Sprint 28 — substitui _make_partial_updated)."""
    meta = _make_meta(correlation_id=correlation_id)
    return SpeechCommittedWords(
        meta=meta, committed_text=text, full_committed_text=text,
        words=tuple(), language="pt",
        confidence=0.9, latency_ms=100, audio_duration_ms=2000,
    )


def _make_bus() -> PipelineEventBus:
    return PipelineEventBus(store=MagicMock())


class _EventCollector:
    def __init__(self, bus: PipelineEventBus, event_types: list) -> None:
        self.events: list = []
        for et in event_types:
            bus.subscribe(et, self.events.append)

    def of_type(self, et) -> list:
        return [e for e in self.events if isinstance(e, et)]


def _make_engine(
    bus: PipelineEventBus,
    *,
    bible_retriever: Any = None,
    rag_top_k: int = 5,
    rag_fallback_on_empty: bool = True,
) -> SemanticEngine:
    return SemanticEngine(
        bus=bus,
        provider=StubProvider(),
        context_engine=ContextEngine(history_fn=bus.history),
        cache=SemanticCache(),
        session_id="test-session",
        debounce_ms=0,
        timeout_ms=5000,
        enabled=True,
        min_growth_chars=5,
        min_append_words=1,
        min_interval_ms=0,
        bible_retriever=bible_retriever,
        rag_top_k=rag_top_k,
        rag_fallback_on_empty=rag_fallback_on_empty,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def book_table():
    return load_books("config/books.json")


@pytest.fixture(scope="module")
def retriever(book_table):
    r, _ = warmup_bible_retriever(
        sources_dir="data/sources",
        book_table=book_table,
        top_k_default=20,
    )
    yield r
    r.close()


# ---------------------------------------------------------------------------
# Testes de integração
# ---------------------------------------------------------------------------


class TestRAGIntegration:
    """Testa o fluxo completo do modo RAG."""

    def test_rag_mode_chooses_top_candidate(self, retriever):
        """No modo RAG, o StubProvider escolhe o top candidato do retriever."""
        import json
        bus = _make_bus()
        engine = _make_engine(bus, bible_retriever=retriever)
        engine.start()

        collector = _EventCollector(bus, [IntentCandidate])

        bus.publish(_make_committed(
            "Porque Deus amou o mundo de tal maneira",
            correlation_id="test-corr-1",
        ))

        time.sleep(0.5)
        engine.stop()

        intents = collector.of_type(IntentCandidate)
        assert len(intents) >= 1, "IntentCandidate não foi publicado"
        result = intents[0]
        assert result.intent == "show_reference"
        # candidates_json é uma string JSON com a lista de candidatos.
        cands = json.loads(result.candidates_json)
        assert len(cands) >= 1
        top = cands[0]
        assert top["book"] == "João"
        assert top["chapter"] == 3
        assert top["verse"] == 16

    def test_rag_mode_numeros_6_24(self, retriever):
        """No modo RAG, Números 6:24 é encontrado (caso de referência)."""
        import json
        bus = _make_bus()
        engine = _make_engine(bus, bible_retriever=retriever)
        engine.start()

        collector = _EventCollector(bus, [IntentCandidate])

        bus.publish(_make_committed(
            "O Senhor te abençoe e te guarde",
            correlation_id="test-corr-num",
        ))

        time.sleep(0.5)
        engine.stop()

        intents = collector.of_type(IntentCandidate)
        assert len(intents) >= 1
        result = intents[0]
        assert result.intent == "show_reference"
        cands = json.loads(result.candidates_json)
        top = cands[0]
        assert top["book"] == "Números"
        assert top["chapter"] == 6
        assert top["verse"] == 24

    def test_current_mode_still_works(self):
        """No Modo Atual (sem retriever), o StubProvider usa respostas fixas."""
        bus = _make_bus()
        engine = _make_engine(bus, bible_retriever=None)
        engine.start()

        collector = _EventCollector(bus, [IntentCandidate])

        # "o texto onde Jesus conversa com nicodemos" está nos stubs.
        bus.publish(_make_committed(
            "o texto onde Jesus conversa com nicodemos",
            correlation_id="test-corr-2",
        ))

        time.sleep(0.5)
        engine.stop()

        intents = collector.of_type(IntentCandidate)
        assert len(intents) >= 1
        assert intents[0].intent == "show_reference"

    def test_rag_fallback_on_empty_disabled(self, retriever):
        """Com fallback_on_empty=False e 0 candidatos, não publica show_reference."""
        bus = _make_bus()
        engine = _make_engine(
            bus,
            bible_retriever=retriever,
            rag_fallback_on_empty=False,
        )
        engine.start()

        collector = _EventCollector(bus, [IntentCandidate])

        # Texto que não corresponde a nenhum versículo (palavras raras).
        bus.publish(_make_committed(
            "xyzzyqwerty nonsense blargh zzz",
            correlation_id="test-corr-3",
        ))

        time.sleep(0.5)
        engine.stop()

        # Como fallback_on_empty=False e 0 candidatos, não deve publicar
        # show_reference.
        for c in collector.of_type(IntentCandidate):
            assert c.intent != "show_reference", \
                "Não deveria publicar show_reference com 0 candidatos e fallback=False"


class TestRAGPrompt:
    """Testa que o prompt do LLM inclui candidatos RAG."""

    def test_user_prompt_includes_candidates(self):
        """_build_user_prompt inclui candidatos RAG quando presentes."""
        from semantic.local_provider import LocalLLMProvider, _SYSTEM_PROMPT_RAG
        from semantic.types import SemanticContext
        from knowledge.types import BibleCandidate, BibleVersionMatch

        v = BibleVersionMatch(version="ACF", text="O SENHOR te abençoe", score=0.95)
        c = BibleCandidate(
            book="Números", book_reference_id=4, chapter=6, verse=24,
            canonical_reference="Números 6:24", aggregated_score=0.95,
            versions=(v,), best_score=0.95, mean_score=0.95,
            num_versions=1, search_rank=1,
        )

        context = SemanticContext(
            current_text="O Senhor te abençoe",
            rag_candidates=(c,),
        )

        # StubProvider em modo RAG escolhe o top candidato.
        provider = StubProvider()
        result = provider.infer(context, timeout_ms=1000)
        assert result.intent == "show_reference"
        assert result.candidates[0].book == "Números"
        assert result.candidates[0].chapter == 6
        assert result.candidates[0].verse == 24

    def test_system_prompt_rag_exists(self):
        """_SYSTEM_PROMPT_RAG está definido e é diferente do _SYSTEM_PROMPT."""
        from semantic.local_provider import _SYSTEM_PROMPT, _SYSTEM_PROMPT_RAG
        assert _SYSTEM_PROMPT_RAG
        assert _SYSTEM_PROMPT_RAG != _SYSTEM_PROMPT
        assert "desambiguador" in _SYSTEM_PROMPT_RAG.lower()
        assert "lista" in _SYSTEM_PROMPT_RAG.lower()

    def test_select_system_prompt_rag(self):
        """_select_system_prompt retorna RAG quando há candidatos."""
        from semantic.local_provider import LocalLLMProvider, _SYSTEM_PROMPT, _SYSTEM_PROMPT_RAG
        from semantic.types import SemanticContext
        from knowledge.types import BibleCandidate, BibleVersionMatch

        v = BibleVersionMatch(version="ACF", text="t", score=0.9)
        c = BibleCandidate(
            book="João", book_reference_id=43, chapter=3, verse=16,
            canonical_reference="João 3:16", aggregated_score=0.9,
            versions=(v,), best_score=0.9, mean_score=0.9,
            num_versions=1, search_rank=1,
        )

        provider = LocalLLMProvider.__new__(LocalLLMProvider)

        ctx_with_rag = SemanticContext(rag_candidates=(c,))
        ctx_without_rag = SemanticContext()

        assert provider._select_system_prompt(ctx_with_rag) == _SYSTEM_PROMPT_RAG
        assert provider._select_system_prompt(ctx_without_rag) == _SYSTEM_PROMPT


class TestRAGConfig:
    """Testa a configuração do modo RAG."""

    def test_knowledge_config_defaults(self):
        """KnowledgeConfig tem defaults seguros (enabled=False)."""
        from config.models import KnowledgeConfig
        c = KnowledgeConfig()
        assert c.enabled is False
        assert c.sources_dir == "data/sources"
        assert c.top_k == 20
        assert c.fallback_on_empty is True
        assert c.warmup is True

    def test_knowledge_config_loaded_from_yaml(self):
        """Config carrega seção knowledge do config.yaml."""
        from config.loader import load_config
        c = load_config()
        assert c.knowledge is not None
        # Sprint 22.2 — knowledge.enabled agora é True no config default
        # (RAG ativado conforme Sprint 22.1 audit recommendation).
        assert c.knowledge.enabled is True
        assert c.knowledge.sources_dir == "data/sources"
        assert c.knowledge.top_k == 20

    def test_knowledge_config_optional(self):
        """Config funciona sem seção knowledge (backward-compatible)."""
        from config.loader import _build_knowledge
        c = _build_knowledge({})
        assert c.enabled is False
