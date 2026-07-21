"""Testes Sprint 20 — Semantic Understanding Engine.

Cobre:
  - Tipos: SemanticCandidate, SemanticResult, SemanticContext.
  - Provider: StubProvider, LocalLLMProvider (schema validation).
  - ContextEngine: construção de contexto a partir do histórico.
  - SemanticCache: hit, miss, TTL, LRU, estatísticas.
  - SemanticEngine: debounce, cache, publicação de IntentCandidate.
  - ReferenceResolver: validação via Searcher, dedup vs parser,
    escolha por confiança, publicação de ReferenceDetected.
  - Segurança: schema inválido descartado, texto livre descartado.
  - Integração: parser vence LLM, LLM só quando necessário.
  - Cache: mesmo contexto não re-chama provider.
  - Timeout: provider indisponível, timeout tratado.
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from pipeline.bus import PipelineEventBus
from pipeline.event_store import MemoryEventStore
from pipeline.events import (
    IntentCandidate,
    ReferenceDetected,
    ReferenceInvalid,
    SemanticInferenceCompleted,
    SemanticResolutionCompleted,
    SpeechPartial,
    SpeechPartialUpdated,
)
from pipeline.metadata import EventMetadata
from semantic import (
    ContextEngine,
    LocalLLMProvider,
    ReferenceResolver,
    SemanticCache,
    SemanticCandidate,
    SemanticContext,
    SemanticEngine,
    SemanticError,
    SemanticProvider,
    SemanticResult,
    SemanticTimeout,
    StubProvider,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bus():
    return PipelineEventBus(store=MemoryEventStore())


def _make_meta(session_id="test-session", origin="StreamingSTTService"):
    return EventMetadata.for_initial(session_id=session_id, origin=origin)


def _make_partial(text, session_id="test-session", correlation_id=None):
    meta = EventMetadata.for_initial(
        session_id=session_id,
        origin="StreamingSTTService",
        correlation_id=correlation_id,
    )
    return SpeechPartial(
        meta=meta, text=text, language="pt",
        confidence=0.9, latency_ms=100, audio_duration_ms=2000,
        is_stable=False,
    )


def _make_partial_updated(text, session_id="test-session", correlation_id=None):
    meta = EventMetadata.for_initial(
        session_id=session_id,
        origin="StreamingSTTService",
        correlation_id=correlation_id,
    )
    return SpeechPartialUpdated(
        meta=meta, text=text, appended_text=text,
        language="pt", confidence=0.9, latency_ms=100,
        audio_duration_ms=2000, is_stable=False,
    )


class _EventCollector:
    def __init__(self, bus, event_types):
        self._bus = bus
        self.events = []
        for et in event_types:
            bus.subscribe(et, self._on_event)

    def _on_event(self, event):
        self.events.append(event)

    def of_type(self, et):
        return [e for e in self.events if isinstance(e, et)]

    def clear(self):
        self.events.clear()


class _MockSearcher:
    """Searcher mock que valida referências."""

    def __init__(self, valid_refs=None):
        # valid_refs: set de (book, chapter, verse) — verse=0 significa capítulo
        self._valid = valid_refs or set()
        self._book_table = MagicMock()
        self._book_table.resolve = MagicMock(return_value=MagicMock(
            book=MagicMock(id=43, canonical="João")
        ))

    def search_by_reference(self, book_name, chapter, verse=None, version=None):
        # Normalizar nome do livro para comparação.
        book_lower = book_name.lower().strip()
        # Aceitar variações de "João".
        joao_variants = {"joão", "joao", "jo", "john"}
        if book_lower in joao_variants:
            book_key = "João"
        elif book_lower in {"provérbios", "proverbios", "prov"}:
            book_key = "Provérbios"
        elif book_lower in {"lucas", "luke", "lc"}:
            book_key = "Lucas"
        elif book_lower in {"mateus", "matthew", "mt"}:
            book_key = "Mateus"
        elif book_lower in {"gênesis", "genesis", "gen", "gn"}:
            book_key = "Gênesis"
        elif book_lower in {"isaías", "isaías", "is", "isa"}:
            book_key = "Isaías"
        else:
            book_key = book_name

        key = (book_key, chapter, verse if verse else 0)
        if key in self._valid:
            return MagicMock()  # SearchResult truthy
        # Tentar capítulo sem versículo.
        if verse and (book_key, chapter, 0) in self._valid:
            return None  # Capítulo existe mas versículo não
        return None


# ---------------------------------------------------------------------------
# Testes — Tipos (Etapa 4)
# ---------------------------------------------------------------------------


class TestSemanticTypes:
    def test_candidate_creation(self):
        c = SemanticCandidate(book="João", chapter=3, verse=16, confidence=0.82)
        assert c.book == "João"
        assert c.chapter == 3
        assert c.verse == 16
        assert c.confidence == 0.82

    def test_candidate_to_dict(self):
        c = SemanticCandidate(book="João", chapter=3, verse=0, confidence=0.7, reason="Nicodemos")
        d = c.to_dict()
        assert d["book"] == "João"
        assert d["chapter"] == 3
        assert d["verse"] == 0
        assert d["confidence"] == 0.7
        assert d["reason"] == "Nicodemos"

    def test_result_has_candidates(self):
        r = SemanticResult(
            intent="show_reference",
            candidates=(SemanticCandidate(book="João", chapter=3),),
        )
        assert r.has_candidates is True

    def test_result_no_candidates(self):
        r = SemanticResult(intent="none")
        assert r.has_candidates is False

    def test_result_empty_candidates(self):
        r = SemanticResult(intent="show_reference", candidates=())
        assert r.has_candidates is False

    def test_context_hash_deterministic(self):
        c1 = SemanticContext(current_text="Nicodemos", last_book="João")
        c2 = SemanticContext(current_text="Nicodemos", last_book="João")
        assert c1.context_hash() == c2.context_hash()

    def test_context_hash_differs(self):
        c1 = SemanticContext(current_text="Nicodemos")
        c2 = SemanticContext(current_text="Bom pastor")
        assert c1.context_hash() != c2.context_hash()

    def test_context_hash_ignores_session_id(self):
        c1 = SemanticContext(current_text="Nicodemos", session_id="s1")
        c2 = SemanticContext(current_text="Nicodemos", session_id="s2")
        assert c1.context_hash() == c2.context_hash()


# ---------------------------------------------------------------------------
# Testes — StubProvider (Etapa 3)
# ---------------------------------------------------------------------------


class TestStubProvider:
    def test_nicodemos(self):
        p = StubProvider()
        ctx = SemanticContext(current_text="o texto onde Jesus conversa com Nicodemos")
        r = p.infer(ctx)
        assert r.intent == "show_reference"
        assert len(r.candidates) == 2
        assert r.candidates[0].book == "João"
        assert r.candidates[0].chapter == 3
        assert r.candidates[0].confidence > r.candidates[1].confidence

    def test_guardar_coracao(self):
        p = StubProvider()
        ctx = SemanticContext(current_text="o versículo que fala para guardar o coração")
        r = p.infer(ctx)
        assert r.intent == "show_reference"
        assert r.candidates[0].book == "Provérbios"
        assert r.candidates[0].chapter == 4
        assert r.candidates[0].verse == 23

    def test_bom_pastor(self):
        p = StubProvider()
        ctx = SemanticContext(current_text="a passagem do bom pastor")
        r = p.infer(ctx)
        assert r.intent == "show_reference"
        assert r.candidates[0].book == "João"
        assert r.candidates[0].chapter == 10

    def test_no_match(self):
        p = StubProvider()
        ctx = SemanticContext(current_text="hoje está chovendo muito")
        r = p.infer(ctx)
        assert r.intent == "none"
        assert len(r.candidates) == 0

    def test_is_available(self):
        assert StubProvider().is_available() is True

    def test_is_semantic_provider(self):
        assert isinstance(StubProvider(), SemanticProvider)


# ---------------------------------------------------------------------------
# Testes — LocalLLMProvider schema validation (Etapa 7)
# ---------------------------------------------------------------------------


class TestLocalLLMProviderSchema:
    def test_parse_valid_json(self):
        p = LocalLLMProvider()
        content = json.dumps({
            "intent": "show_reference",
            "candidates": [
                {"book": "João", "chapter": 3, "verse": 16,
                 "confidence": 0.82, "reason": "Nicodemos"}
            ]
        })
        r = p._parse_and_validate(content)
        assert r.intent == "show_reference"
        assert len(r.candidates) == 1
        assert r.candidates[0].book == "João"

    def test_parse_markdown_fenced(self):
        p = LocalLLMProvider()
        content = '```json\n{"intent":"none","candidates":[]}\n```'
        r = p._parse_and_validate(content)
        assert r.intent == "none"

    def test_parse_invalid_json(self):
        p = LocalLLMProvider()
        r = p._parse_and_validate("isso não é JSON")
        assert r.intent == "none"
        assert len(r.candidates) == 0

    def test_parse_text_free_discarded(self):
        p = LocalLLMProvider()
        r = p._parse_and_validate("A referência é João 3:16")
        assert r.intent == "none"

    def test_parse_missing_intent(self):
        p = LocalLLMProvider()
        r = p._parse_and_validate('{"candidates":[]}')
        assert r.intent == "none"

    def test_parse_invalid_intent(self):
        p = LocalLLMProvider()
        r = p._parse_and_validate('{"intent":"delete_database","candidates":[]}')
        assert r.intent == "none"

    def test_parse_candidate_missing_book(self):
        p = LocalLLMProvider()
        r = p._parse_and_validate(
            '{"intent":"show_reference","candidates":[{"chapter":3}]}'
        )
        assert r.intent == "none"  # candidato inválido → sem candidatos

    def test_parse_candidate_negative_chapter(self):
        p = LocalLLMProvider()
        r = p._parse_and_validate(
            '{"intent":"show_reference","candidates":[{"book":"João","chapter":-1}]}'
        )
        assert r.intent == "none"

    def test_parse_confidence_clamped(self):
        p = LocalLLMProvider()
        r = p._parse_and_validate(
            '{"intent":"show_reference","candidates":['
            '{"book":"João","chapter":3,"verse":16,"confidence":1.5}]}'
        )
        assert r.candidates[0].confidence == 1.0

    def test_parse_extra_fields_ignored(self):
        p = LocalLLMProvider()
        r = p._parse_and_validate(
            '{"intent":"show_reference","candidates":['
            '{"book":"João","chapter":3,"verse":16,"confidence":0.8,'
            '"extra":"malicious","sql":"DROP TABLE"}]}'
        )
        assert r.candidates[0].book == "João"
        # Campos extras não causam erro — apenas ignorados.

    def test_reason_truncated(self):
        p = LocalLLMProvider()
        long_reason = "A" * 200
        r = p._parse_and_validate(
            f'{{"intent":"show_reference","candidates":['
            f'{{"book":"João","chapter":3,"confidence":0.8,"reason":"{long_reason}"}}]}}'
        )
        assert len(r.candidates[0].reason) <= 80


# ---------------------------------------------------------------------------
# Testes — ContextEngine (Etapa 6)
# ---------------------------------------------------------------------------


class TestContextEngine:
    def test_empty_history(self):
        ce = ContextEngine(history_fn=lambda: [])
        ctx = ce.build(current_text="Nicodemos", session_id="s1")
        assert ctx.current_text == "Nicodemos"
        assert ctx.recent_text == ""
        assert ctx.last_book == ""

    def test_with_recent_partial(self):
        bus = _make_bus()
        bus.publish(_make_partial("texto anterior do pregador"))
        ce = ContextEngine(history_fn=bus.history)
        ctx = ce.build(current_text="Nicodemos")
        assert "texto anterior" in ctx.recent_text

    def test_with_last_reference(self):
        bus = _make_bus()
        # Publicar um ReferenceDetected
        meta = _make_meta()
        bus.publish(ReferenceDetected(
            meta=meta, book="João", chapter=3, verse_start=16,
            confidence=0.95, raw_text="joão 3 16", normalized_text="João 3:16",
        ))
        ce = ContextEngine(history_fn=bus.history)
        ctx = ce.build(current_text="como vimos anteriormente")
        assert ctx.last_book == "João"
        assert ctx.last_chapter == 3
        assert "João 3:16" in ctx.last_reference

    def test_window_filters_old_events(self):
        bus = _make_bus()
        # Evento antigo (timestamp baixo).
        old_meta = EventMetadata(
            event_id="old", correlation_id="old", causation_id=None,
            session_id="s", timestamp=time.time() - 100, origin="test",
        )
        bus.publish(SpeechPartial(
            meta=old_meta, text="texto muito antigo",
        ))
        ce = ContextEngine(history_fn=bus.history, window_seconds=10.0)
        ctx = ce.build(current_text="atual")
        assert "muito antigo" not in ctx.recent_text

    def test_current_text_not_in_recent(self):
        bus = _make_bus()
        bus.publish(_make_partial("texto atual"))
        ce = ContextEngine(history_fn=bus.history)
        ctx = ce.build(current_text="texto atual")
        # current_text não deve aparecer em recent_text (evita duplicação).
        assert ctx.recent_text == "" or "texto atual" not in ctx.recent_text


# ---------------------------------------------------------------------------
# Testes — SemanticCache (Etapa 8)
# ---------------------------------------------------------------------------


class TestSemanticCache:
    def test_miss_then_hit(self):
        cache = SemanticCache(ttl_seconds=60)
        h = "abc123"
        assert cache.get(h) is None
        result = SemanticResult(intent="show_reference")
        cache.put(h, result)
        assert cache.get(h) is result

    def test_ttl_expiry(self):
        cache = SemanticCache(ttl_seconds=0.05)  # 50ms
        cache.put("h1", SemanticResult(intent="none"))
        time.sleep(0.1)
        assert cache.get("h1") is None

    def test_lru_eviction(self):
        cache = SemanticCache(ttl_seconds=60, max_entries=3)
        for i in range(4):
            cache.put(f"h{i}", SemanticResult(intent="none"))
        # h0 deve ter sido evictado (LRU).
        assert cache.get("h0") is None
        assert cache.get("h3") is not None

    def test_stats(self):
        cache = SemanticCache(ttl_seconds=60)
        cache.put("h1", SemanticResult(intent="none"))
        cache.get("h1")  # hit
        cache.get("h2")  # miss
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["entries"] == 1

    def test_clear(self):
        cache = SemanticCache(ttl_seconds=60)
        cache.put("h1", SemanticResult(intent="none"))
        cache.clear()
        assert cache.get("h1") is None
        assert cache.stats()["entries"] == 0


# ---------------------------------------------------------------------------
# Testes — SemanticEngine (Etapa 2)
# ---------------------------------------------------------------------------


class TestSemanticEngine:
    def test_debounce_and_publish(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [IntentCandidate, SemanticInferenceCompleted])
        provider = StubProvider()
        ce = ContextEngine(history_fn=bus.history)
        cache = SemanticCache(ttl_seconds=60)
        engine = SemanticEngine(
            bus=bus, provider=provider, context_engine=ce,
            cache=cache, session_id="s1", debounce_ms=50, timeout_ms=2000,
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("o texto onde Jesus conversa com Nicodemos"))
            time.sleep(0.2)  # esperar debounce + inferência
            intents = collector.of_type(IntentCandidate)
            assert len(intents) == 1
            assert intents[0].intent == "show_reference"
            # Validar que candidatos foram serializados.
            cands = json.loads(intents[0].candidates_json)
            assert cands[0]["book"] == "João"
        finally:
            engine.stop()

    def test_short_text_ignored(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [IntentCandidate])
        provider = StubProvider()
        ce = ContextEngine(history_fn=bus.history)
        cache = SemanticCache(ttl_seconds=60)
        engine = SemanticEngine(
            bus=bus, provider=provider, context_engine=ce,
            cache=cache, session_id="s1", debounce_ms=50,
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("oi"))  # < 8 chars
            time.sleep(0.15)
            assert len(collector.of_type(IntentCandidate)) == 0
        finally:
            engine.stop()

    def test_cache_hit_skips_provider(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [IntentCandidate, SemanticInferenceCompleted])
        # Provider que conta chamadas.
        calls = []
        class _CountingProvider:
            @property
            def name(self): return "counting"
            @property
            def model_name(self): return "test"
            def is_available(self): return True
            def infer(self, ctx, timeout_ms=5000):
                calls.append(1)
                return SemanticResult(
                    intent="show_reference",
                    candidates=(SemanticCandidate(book="João", chapter=3, confidence=0.8),),
                )
            def close(self): pass
        provider = _CountingProvider()
        ce = ContextEngine(history_fn=bus.history)
        cache = SemanticCache(ttl_seconds=60)
        engine = SemanticEngine(
            bus=bus, provider=provider, context_engine=ce,
            cache=cache, session_id="s1", debounce_ms=50,
        )
        engine.start()
        try:
            # Mesmo texto duas vezes → provider chamado 1x, cache hit 1x.
            bus.publish(_make_partial_updated("Nicodemos conversando"))
            time.sleep(0.15)
            bus.publish(_make_partial_updated("Nicodemos conversando"))
            time.sleep(0.15)
            assert len(calls) == 1
            # Segunda chamada veio do cache.
            telemetries = collector.of_type(SemanticInferenceCompleted)
            assert any(t.cached for t in telemetries)
        finally:
            engine.stop()

    def test_provider_unavailable(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [SemanticInferenceCompleted])
        class _UnavailableProvider:
            @property
            def name(self): return "unavail"
            @property
            def model_name(self): return "test"
            def is_available(self): return False
            def infer(self, ctx, timeout_ms=5000): raise AssertionError("should not be called")
            def close(self): pass
        engine = SemanticEngine(
            bus=bus, provider=_UnavailableProvider(),
            context_engine=ContextEngine(history_fn=bus.history),
            cache=SemanticCache(ttl_seconds=60),
            session_id="s1", debounce_ms=50,
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("o texto onde Jesus conversa com Nicodemos"))
            time.sleep(0.15)
            teles = collector.of_type(SemanticInferenceCompleted)
            assert len(teles) == 1
            assert "not available" in teles[0].error
        finally:
            engine.stop()

    def test_provider_timeout(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [SemanticInferenceCompleted])
        class _TimeoutProvider:
            @property
            def name(self): return "timeout"
            @property
            def model_name(self): return "test"
            def is_available(self): return True
            def infer(self, ctx, timeout_ms=5000): raise SemanticTimeout("timed out")
            def close(self): pass
        engine = SemanticEngine(
            bus=bus, provider=_TimeoutProvider(),
            context_engine=ContextEngine(history_fn=bus.history),
            cache=SemanticCache(ttl_seconds=60),
            session_id="s1", debounce_ms=50, timeout_ms=1000,
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("o texto onde Jesus conversa com Nicodemos"))
            time.sleep(0.15)
            teles = collector.of_type(SemanticInferenceCompleted)
            assert len(teles) == 1
            assert "timeout" in teles[0].error.lower()
        finally:
            engine.stop()

    def test_disabled_engine(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [IntentCandidate])
        engine = SemanticEngine(
            bus=bus, provider=StubProvider(),
            context_engine=ContextEngine(history_fn=bus.history),
            cache=SemanticCache(ttl_seconds=60),
            session_id="s1", debounce_ms=50, enabled=False,
        )
        engine.start()  # não assina nada
        try:
            bus.publish(_make_partial_updated("o texto onde Jesus conversa com Nicodemos"))
            time.sleep(0.15)
            assert len(collector.of_type(IntentCandidate)) == 0
        finally:
            engine.stop()


# ---------------------------------------------------------------------------
# Testes — ReferenceResolver (Etapa 5)
# ---------------------------------------------------------------------------


class TestReferenceResolver:
    def _make_intent_candidate(self, candidates, correlation_id="corr-1"):
        meta = EventMetadata.for_initial(
            session_id="s1", origin="SemanticEngine",
            correlation_id=correlation_id,
        )
        return IntentCandidate(
            meta=meta,
            intent="show_reference",
            candidates_json=json.dumps([c.to_dict() for c in candidates]),
            inference_ms=100,
            provider="stub",
            model="stub-v1",
            context_hash="abc",
            cached=False,
        )

    def test_resolves_valid_candidate(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [ReferenceDetected, SemanticResolutionCompleted])
        searcher = _MockSearcher(valid_refs={("João", 3, 0), ("João", 3, 16)})
        resolver = ReferenceResolver(bus=bus, searcher=searcher, session_id="s1")
        resolver.start()
        try:
            cand = SemanticCandidate(book="João", chapter=3, verse=16, confidence=0.82)
            bus.publish(self._make_intent_candidate([cand]))
            refs = collector.of_type(ReferenceDetected)
            assert len(refs) == 1
            assert refs[0].book == "João"
            assert refs[0].chapter == 3
            assert refs[0].verse_start == 16
            assert refs[0].meta.origin == "ReferenceResolver"
            res = collector.of_type(SemanticResolutionCompleted)
            assert res[0].resolved is True
        finally:
            resolver.stop()

    def test_parser_already_resolved_skips(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [ReferenceDetected])
        # Simular que o parser já publicou ReferenceDetected para esta correlation_id.
        parser_meta = EventMetadata.for_initial(
            session_id="s1", origin="IncrementalBiblicalParser",
            correlation_id="corr-1",
        )
        bus.publish(ReferenceDetected(
            meta=parser_meta, book="João", chapter=3, verse_start=16,
            confidence=0.98, raw_text="joão 3 16", normalized_text="João 3:16",
        ))
        collector.clear()  # limpar, mas o evento está no history

        searcher = _MockSearcher(valid_refs={("João", 3, 16)})
        resolver = ReferenceResolver(bus=bus, searcher=searcher, session_id="s1")
        resolver.start()
        try:
            cand = SemanticCandidate(book="João", chapter=3, verse=16, confidence=0.82)
            bus.publish(self._make_intent_candidate([cand], correlation_id="corr-1"))
            # Resolver NÃO deve publicar novo ReferenceDetected.
            assert len(collector.of_type(ReferenceDetected)) == 0
        finally:
            resolver.stop()

    def test_all_candidates_invalid(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [ReferenceDetected, SemanticResolutionCompleted])
        searcher = _MockSearcher(valid_refs=set())  # nada é válido
        resolver = ReferenceResolver(bus=bus, searcher=searcher, session_id="s1")
        resolver.start()
        try:
            cands = [
                SemanticCandidate(book="João", chapter=999, confidence=0.8),
                SemanticCandidate(book="LivroInexistente", chapter=1, confidence=0.7),
            ]
            bus.publish(self._make_intent_candidate(cands))
            assert len(collector.of_type(ReferenceDetected)) == 0
            res = collector.of_type(SemanticResolutionCompleted)
            assert res[0].resolved is False
            assert res[0].reason == "all_invalid"
        finally:
            resolver.stop()

    def test_low_confidence_skipped(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [ReferenceDetected])
        searcher = _MockSearcher(valid_refs={("João", 3, 0)})
        resolver = ReferenceResolver(
            bus=bus, searcher=searcher, session_id="s1",
            min_confidence=0.80,
        )
        resolver.start()
        try:
            cand = SemanticCandidate(book="João", chapter=3, confidence=0.50)
            bus.publish(self._make_intent_candidate([cand]))
            assert len(collector.of_type(ReferenceDetected)) == 0
        finally:
            resolver.stop()

    def test_highest_confidence_chosen(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [ReferenceDetected])
        searcher = _MockSearcher(valid_refs={
            ("João", 3, 0), ("João", 3, 5), ("João", 3, 16),
        })
        resolver = ReferenceResolver(bus=bus, searcher=searcher, session_id="s1")
        resolver.start()
        try:
            cands = [
                SemanticCandidate(book="João", chapter=3, verse=5, confidence=0.61),
                SemanticCandidate(book="João", chapter=3, verse=16, confidence=0.82),
            ]
            bus.publish(self._make_intent_candidate(cands))
            refs = collector.of_type(ReferenceDetected)
            assert len(refs) == 1
            assert refs[0].verse_start == 16  # maior confiança
        finally:
            resolver.stop()

    def test_chapter_only_candidate(self):
        """Candidato com verse=0 (capítulo inteiro) deve ser válido se capítulo existe."""
        bus = _make_bus()
        collector = _EventCollector(bus, [ReferenceDetected])
        searcher = _MockSearcher(valid_refs={("João", 3, 0)})
        resolver = ReferenceResolver(bus=bus, searcher=searcher, session_id="s1")
        resolver.start()
        try:
            cand = SemanticCandidate(book="João", chapter=3, verse=0, confidence=0.85)
            bus.publish(self._make_intent_candidate([cand]))
            refs = collector.of_type(ReferenceDetected)
            assert len(refs) == 1
            assert refs[0].chapter == 3
            assert refs[0].verse_start == 0
        finally:
            resolver.stop()

    def test_disabled_resolver(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [ReferenceDetected])
        resolver = ReferenceResolver(
            bus=bus, searcher=_MockSearcher(), session_id="s1",
            enabled=False,
        )
        resolver.start()  # não assina
        try:
            cand = SemanticCandidate(book="João", chapter=3, confidence=0.85)
            bus.publish(self._make_intent_candidate([cand]))
            assert len(collector.of_type(ReferenceDetected)) == 0
        finally:
            resolver.stop()

    def test_invalid_candidates_json(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [ReferenceDetected, SemanticResolutionCompleted])
        resolver = ReferenceResolver(bus=bus, searcher=_MockSearcher(), session_id="s1")
        resolver.start()
        try:
            meta = EventMetadata.for_initial(
                session_id="s1", origin="SemanticEngine",
            )
            bus.publish(IntentCandidate(
                meta=meta, intent="show_reference",
                candidates_json="not valid json",
            ))
            assert len(collector.of_type(ReferenceDetected)) == 0
            res = collector.of_type(SemanticResolutionCompleted)
            assert res[0].reason == "no_candidates"
        finally:
            resolver.stop()


# ---------------------------------------------------------------------------
# Testes — Integração completa (Etapa 10)
# ---------------------------------------------------------------------------


class TestIntegration:
    """Testes end-to-end: SpeechPartial → SemanticEngine → ReferenceResolver → ReferenceDetected."""

    def test_full_flow_implicit_reference(self):
        """'o texto onde Jesus conversa com Nicodemos' → João 3."""
        bus = _make_bus()
        collector = _EventCollector(bus, [
            IntentCandidate, ReferenceDetected, SemanticResolutionCompleted,
        ])
        searcher = _MockSearcher(valid_refs={
            ("João", 3, 0), ("João", 3, 5), ("João", 3, 16),
        })
        provider = StubProvider()
        ce = ContextEngine(history_fn=bus.history)
        cache = SemanticCache(ttl_seconds=60)
        engine = SemanticEngine(
            bus=bus, provider=provider, context_engine=ce,
            cache=cache, session_id="s1", debounce_ms=50,
        )
        resolver = ReferenceResolver(bus=bus, searcher=searcher, session_id="s1")
        engine.start()
        resolver.start()
        try:
            bus.publish(_make_partial_updated(
                "o texto onde Jesus conversa com Nicodemos"
            ))
            time.sleep(0.3)
            # IntentCandidate publicado.
            assert len(collector.of_type(IntentCandidate)) == 1
            # ReferenceDetected publicado pelo resolver.
            refs = collector.of_type(ReferenceDetected)
            assert len(refs) == 1
            assert refs[0].book == "João"
            assert refs[0].chapter == 3
            # Resolution completed.
            res = collector.of_type(SemanticResolutionCompleted)
            assert res[0].resolved is True
        finally:
            engine.stop()
            resolver.stop()

    def test_parser_wins_over_semantic(self):
        """Quando parser publica ReferenceDetected, semantic é descartado."""
        bus = _make_bus()
        collector = _EventCollector(bus, [ReferenceDetected])
        searcher = _MockSearcher(valid_refs={("João", 3, 16)})
        provider = StubProvider()
        ce = ContextEngine(history_fn=bus.history)
        cache = SemanticCache(ttl_seconds=60)
        engine = SemanticEngine(
            bus=bus, provider=provider, context_engine=ce,
            cache=cache, session_id="s1", debounce_ms=50,
        )
        resolver = ReferenceResolver(bus=bus, searcher=searcher, session_id="s1")
        engine.start()
        resolver.start()
        try:
            # Publicar SpeechPartialUpdated com texto que tem referência explícita.
            # O parser (que não está rodando neste teste) normalmente publicaria
            # ReferenceDetected. Simulamos isso manualmente.
            corr_id = "test-corr-parser-wins"
            partial = _make_partial_updated(
                "vamos para João 3:16", correlation_id=corr_id,
            )
            bus.publish(partial)

            # Simular parser publicando ReferenceDetected rapidamente.
            parser_meta = EventMetadata.for_initial(
                session_id="s1", origin="IncrementalBiblicalParser",
                correlation_id=corr_id,
            )
            bus.publish(ReferenceDetected(
                meta=parser_meta, book="João", chapter=3, verse_start=16,
                confidence=0.98, raw_text="joão 3 16",
                normalized_text="João 3:16",
            ))
            collector.clear()

            # Esperar debounce do semantic engine.
            time.sleep(0.3)

            # Semantic engine publicou IntentCandidate, mas resolver deve
            # ver que parser já resolveu e NÃO publicar novo ReferenceDetected.
            refs = collector.of_type(ReferenceDetected)
            assert len(refs) == 0  # resolver respeitou o parser
        finally:
            engine.stop()
            resolver.stop()

    def test_no_reference_for_non_biblical_text(self):
        """Texto não-bíblico não gera ReferenceDetected."""
        bus = _make_bus()
        collector = _EventCollector(bus, [ReferenceDetected])
        searcher = _MockSearcher(valid_refs=set())
        provider = StubProvider()
        ce = ContextEngine(history_fn=bus.history)
        cache = SemanticCache(ttl_seconds=60)
        engine = SemanticEngine(
            bus=bus, provider=provider, context_engine=ce,
            cache=cache, session_id="s1", debounce_ms=50,
        )
        resolver = ReferenceResolver(bus=bus, searcher=searcher, session_id="s1")
        engine.start()
        resolver.start()
        try:
            bus.publish(_make_partial_updated("hoje está chovendo muito forte"))
            time.sleep(0.2)
            assert len(collector.of_type(ReferenceDetected)) == 0
        finally:
            engine.stop()
            resolver.stop()

    def test_cache_avoids_duplicate_inference(self):
        """Mesmo contexto duas vezes → 1 chamada ao provider."""
        bus = _make_bus()
        collector = _EventCollector(bus, [SemanticInferenceCompleted])
        calls = []
        class _CountingStub:
            @property
            def name(self): return "counting"
            @property
            def model_name(self): return "stub"
            def is_available(self): return True
            def infer(self, ctx, timeout_ms=5000):
                calls.append(1)
                return SemanticResult(
                    intent="show_reference",
                    candidates=(SemanticCandidate(book="João", chapter=3, confidence=0.8),),
                )
            def close(self): pass
        engine = SemanticEngine(
            bus=bus, provider=_CountingStub(),
            context_engine=ContextEngine(history_fn=bus.history),
            cache=SemanticCache(ttl_seconds=60),
            session_id="s1", debounce_ms=50,
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("Nicodemos conversando com Jesus"))
            time.sleep(0.15)
            bus.publish(_make_partial_updated("Nicodemos conversando com Jesus"))
            time.sleep(0.15)
            assert len(calls) == 1
            teles = collector.of_type(SemanticInferenceCompleted)
            assert any(t.cached for t in teles)
        finally:
            engine.stop()
