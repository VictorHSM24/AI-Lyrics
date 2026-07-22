"""Testes da Sprint 21.5 — SemanticEngine Streaming Intelligence.

Cobre a nova política híbrida de disparo do SemanticEngine:
  - Gatilho de crescimento: dispara durante fala contínua quando
    growth_chars >= 22 AND append_words >= 3 AND elapsed >= 1000ms.
  - Gatilho de debounce (fallback): dispara após pausa (400ms).
  - Rate limiting: não dispara mais que 1 vez a cada 1000ms.
  - Filtro de filler: não dispara quando só filler foi adicionado.
  - Compatibilidade: debounce fallback continua funcionando.

Cenários obrigatórios:
  - "O Senhor é meu pastor..." → inferência durante a fala.
  - "Porque Deus amou o mundo..." → inferência durante a fala.
  - Fala contínua sem conteúdo novo → não dispara excessivamente.
  - Pausa na fala → debounce fallback dispara.
"""

from __future__ import annotations

import time
import unittest
from typing import Any
from unittest.mock import MagicMock

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    IntentCandidate,
    SemanticInferenceCompleted,
    SpeechPartial,
    SpeechPartialUpdated,
)
from pipeline.metadata import EventMetadata
from semantic.cache import SemanticCache
from semantic.context_engine import ContextEngine
from semantic.engine import SemanticEngine
from semantic.local_provider import StubProvider


# ============================================================
# Helpers — fixtures.
# ============================================================


def _make_meta(
    session_id: str = "test-session",
    origin: str = "StreamingSTTService",
    correlation_id: str | None = None,
) -> EventMetadata:
    return EventMetadata.for_initial(
        session_id=session_id, origin=origin,
        correlation_id=correlation_id,
    )


def _make_partial_updated(
    text: str,
    appended: str = "",
    correlation_id: str | None = None,
) -> SpeechPartialUpdated:
    meta = _make_meta(correlation_id=correlation_id)
    return SpeechPartialUpdated(
        meta=meta, text=text, appended_text=appended or text,
        language="pt", confidence=0.9, latency_ms=100,
        audio_duration_ms=2000, is_stable=False,
    )


def _make_partial(text: str, correlation_id: str | None = None) -> SpeechPartial:
    meta = _make_meta(correlation_id=correlation_id)
    return SpeechPartial(
        meta=meta, text=text, language="pt",
        confidence=0.9, latency_ms=100, audio_duration_ms=2000,
        is_stable=False,
    )


class _EventCollector:
    def __init__(self, bus: PipelineEventBus, event_types: list) -> None:
        self.events: list = []
        for et in event_types:
            bus.subscribe(et, self.events.append)

    def of_type(self, et) -> list:
        return [e for e in self.events if isinstance(e, et)]

    def clear(self) -> None:
        self.events.clear()


class _SemanticStubProvider(StubProvider):
    """StubProvider estendido com respostas para as 5 referências semânticas.

    O StubProvider original só reconhece "nicodemos", "bom pastor", etc.
    Este stub estendido também reconhece as referências semânticas da
    Sprint 21.5: Salmos 23, João 3:16, Filipenses 4:13, Efésios 6,
    Salmos 23:4.
    """

    _EXTRA_RESPONSES: list[tuple[str, list[dict[str, Any]]]] = [
        ("senhor é meu pastor", [
            {"book": "Salmos", "chapter": 23, "verse": 0, "confidence": 0.90,
             "reason": "O Senhor é meu pastor"},
        ]),
        ("deus amou o mundo", [
            {"book": "João", "chapter": 3, "verse": 16, "confidence": 0.92,
             "reason": "Porque Deus amou o mundo"},
        ]),
        ("tudo posso", [
            {"book": "Filipenses", "chapter": 4, "verse": 13, "confidence": 0.88,
             "reason": "Tudo posso naquele que me fortalece"},
        ]),
        ("armadura de deus", [
            {"book": "Efésios", "chapter": 6, "verse": 11, "confidence": 0.85,
             "reason": "Vestir a armadura de Deus"},
        ]),
        ("vale da sombra", [
            {"book": "Salmos", "chapter": 23, "verse": 4, "confidence": 0.87,
             "reason": "Ainda que eu andasse pelo vale da sombra da morte"},
        ]),
    ]

    def infer(self, context: Any, timeout_ms: int = 5000) -> Any:
        from semantic.types import SemanticCandidate, SemanticResult
        text_lower = context.current_text.lower()
        # Primeiro tentar respostas extra (Sprint 21.5).
        for pattern, candidates in self._EXTRA_RESPONSES:
            if pattern in text_lower:
                cands = tuple(
                    SemanticCandidate(
                        book=c["book"], chapter=c["chapter"],
                        verse=c["verse"], confidence=c["confidence"],
                        reason=c["reason"],
                    )
                    for c in candidates
                )
                return SemanticResult(
                    intent="show_reference", candidates=cands,
                    inference_ms=1, provider="stub", model="stub-v1",
                )
        # Fallback para o StubProvider original.
        return super().infer(context, timeout_ms)


def _make_engine(
    bus: PipelineEventBus,
    *,
    debounce_ms: int = 100,
    min_growth_chars: int = 20,
    min_append_words: int = 3,
    min_interval_ms: int = 100,
    provider: Any = None,
) -> SemanticEngine:
    """Cria SemanticEngine com parâmetros configuráveis para testes.

    Defaults usam valores pequenos (100ms) para que os testes sejam rápidos.
    """
    ce = ContextEngine(history_fn=bus.history)
    cache = SemanticCache(ttl_seconds=60)
    return SemanticEngine(
        bus=bus,
        provider=provider or StubProvider(),
        context_engine=ce,
        cache=cache,
        session_id="test-session",
        debounce_ms=debounce_ms,
        timeout_ms=5000,
        enabled=True,
        min_growth_chars=min_growth_chars,
        min_append_words=min_append_words,
        min_interval_ms=min_interval_ms,
    )


def _make_bus() -> PipelineEventBus:
    return PipelineEventBus(store=MagicMock())


# ============================================================
# Testes — Gatilho de crescimento (durante fala contínua).
# ============================================================


class TestGrowthTrigger(unittest.TestCase):
    """Gatilho de crescimento dispara durante fala contínua."""

    def test_growth_trigger_fires_immediately(self):
        """Texto com 22+ chars e 3+ palavras dispara sem esperar debounce."""
        bus = _make_bus()
        collector = _EventCollector(bus, [SemanticInferenceCompleted])
        # min_interval_ms=0 para não bloquear o primeiro disparo.
        engine = _make_engine(
            bus, debounce_ms=10000,  # debounce longo — não deve disparar
            min_growth_chars=20, min_append_words=3, min_interval_ms=0,
        )
        engine.start()
        try:
            # "O Senhor é meu pastor" = 22 chars, 5 palavras.
            bus.publish(_make_partial_updated("O Senhor é meu pastor"))
            time.sleep(0.05)  # tempo para execução síncrona
            telemetries = collector.of_type(SemanticInferenceCompleted)
            # Deve ter disparado imediatamente (não esperou debounce 10000ms).
            self.assertEqual(len(telemetries), 1,
                             "Gatilho de crescimento deve disparar imediatamente")
        finally:
            engine.stop()

    def test_growth_trigger_fires_during_continuous_speech(self):
        """Durante fala contínua, LLM é chamado antes do silêncio."""
        bus = _make_bus()
        collector = _EventCollector(bus, [SemanticInferenceCompleted])
        engine = _make_engine(
            bus, debounce_ms=10000,  # debounce muito longo
            min_growth_chars=20, min_append_words=3, min_interval_ms=50,
        )
        engine.start()
        try:
            # Simular fala contínua: parciais chegam a cada 50ms.
            texts = [
                "O Senhor",           # 9 chars, 2 words — não dispara
                "O Senhor é meu",      # 15 chars, 4 words — growth=6 < 22
                "O Senhor é meu pastor",  # 22 chars, 5 words — dispara!
            ]
            for text in texts:
                bus.publish(_make_partial_updated(text))
                time.sleep(0.06)  # > min_interval_ms=50

            telemetries = collector.of_type(SemanticInferenceCompleted)
            self.assertGreaterEqual(len(telemetries), 1,
                                    "LLM deve ser chamado durante fala contínua")
        finally:
            engine.stop()

    def test_short_text_does_not_fire_growth(self):
        """Texto com < 8 chars não dispara (filtro mínimo)."""
        bus = _make_bus()
        collector = _EventCollector(bus, [IntentCandidate])
        engine = _make_engine(
            bus, debounce_ms=10000,
            min_growth_chars=5, min_append_words=1, min_interval_ms=0,
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("oi"))  # 2 chars < 8
            time.sleep(0.05)
            self.assertEqual(len(collector.of_type(IntentCandidate)), 0)
        finally:
            engine.stop()


# ============================================================
# Testes — Rate limiting.
# ============================================================


class TestRateLimiting(unittest.TestCase):
    """Rate limiting: não dispara mais que 1 vez a cada min_interval_ms."""

    def test_rate_limit_prevents_rapid_fire(self):
        """Dois parciais em rápida sucessão: só 1 dispara (rate limit)."""
        bus = _make_bus()
        collector = _EventCollector(bus, [SemanticInferenceCompleted])
        engine = _make_engine(
            bus, debounce_ms=10000,
            min_growth_chars=20, min_append_words=3,
            min_interval_ms=500,  # 500ms entre chamadas
        )
        engine.start()
        try:
            # Primeiro: dispara (22 chars, 5 words, elapsed=inf).
            bus.publish(_make_partial_updated("O Senhor é meu pastor"))
            time.sleep(0.05)
            count1 = len(collector.of_type(SemanticInferenceCompleted))
            self.assertEqual(count1, 1)

            # Segundo: 22+ chars novos, 3+ words novas, mas < 500ms.
            bus.publish(_make_partial_updated(
                "O Senhor é meu pastor e nada me faltará agora"))
            time.sleep(0.05)
            count2 = len(collector.of_type(SemanticInferenceCompleted))
            # Não deve ter disparado (rate limit).
            self.assertEqual(count2, 1,
                             "Rate limit deve impedir disparo rápido")
        finally:
            engine.stop()

    def test_rate_limit_allows_after_interval(self):
        """Após min_interval_ms, novo disparo é permitido."""
        bus = _make_bus()
        collector = _EventCollector(bus, [SemanticInferenceCompleted])
        engine = _make_engine(
            bus, debounce_ms=10000,
            min_growth_chars=20, min_append_words=3,
            min_interval_ms=100,  # 100ms
        )
        engine.start()
        try:
            # Primeiro disparo.
            bus.publish(_make_partial_updated("O Senhor é meu pastor"))
            time.sleep(0.05)
            self.assertEqual(len(collector.of_type(SemanticInferenceCompleted)), 1)

            # Aguardar rate limit.
            time.sleep(0.08)  # > 100ms total

            # Segundo disparo: 22+ chars novos, 3+ words novas.
            bus.publish(_make_partial_updated(
                "O Senhor é meu pastor e nada me faltará hoje sim"))
            time.sleep(0.05)
            self.assertEqual(len(collector.of_type(SemanticInferenceCompleted)), 2,
                             "Após intervalo, novo disparo deve ser permitido")
        finally:
            engine.stop()


# ============================================================
# Testes — Filtro de filler (append_words).
# ============================================================


class TestFillerFilter(unittest.TestCase):
    """Filtro de filler: não dispara quando só filler foi adicionado."""

    def test_filler_does_not_fire(self):
        """Acréscimo de 22+ chars mas < 3 palavras: não dispara."""
        bus = _make_bus()
        collector = _EventCollector(bus, [SemanticInferenceCompleted])
        # Usar provider que conta chamadas.
        calls: list = []

        class _CountingStub(StubProvider):
            def infer(self, context, timeout_ms=5000):
                calls.append(context.current_text)
                return super().infer(context, timeout_ms)

        engine = _make_engine(
            bus, debounce_ms=10000,
            min_growth_chars=20, min_append_words=3,
            min_interval_ms=0,
            provider=_CountingStub(),
        )
        engine.start()
        try:
            # Primeiro: dispara (22 chars, 5 words).
            bus.publish(_make_partial_updated("O Senhor é meu pastor"))
            time.sleep(0.05)
            self.assertEqual(len(calls), 1)

            # Segundo: 22+ chars novos mas só 1 palavra nova.
            # "O Senhor é meu pastor" + " amémamémamémamémamémamém" (25 chars, 1 word)
            bus.publish(_make_partial_updated(
                "O Senhor é meu pastor amémamémamémamémamémamém"))
            time.sleep(0.05)
            # Não deve ter disparado (append_words < 3).
            self.assertEqual(len(calls), 1,
                             "Filler com < 3 palavras não deve disparar")
        finally:
            engine.stop()


# ============================================================
# Testes — Debounce fallback (compatibilidade).
# ============================================================


class TestDebounceFallback(unittest.TestCase):
    """Debounce fallback continua funcionando para pausa na fala."""

    def test_debounce_fires_on_pause(self):
        """Quando a fala para, debounce expira e dispara inferência."""
        bus = _make_bus()
        collector = _EventCollector(bus, [IntentCandidate])
        # min_growth_chars alto para forçar uso do debounce.
        engine = _make_engine(
            bus, debounce_ms=80,
            min_growth_chars=1000,  # impossível — força debounce
            min_append_words=100,
            min_interval_ms=0,
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated(
                "O texto onde Jesus conversa com Nicodemos"))
            time.sleep(0.2)  # esperar debounce 80ms
            intents = collector.of_type(IntentCandidate)
            self.assertGreaterEqual(len(intents), 1,
                                    "Debounce deve disparar após pausa")
        finally:
            engine.stop()

    def test_debounce_canceled_by_new_partial(self):
        """Novo parcial cancela debounce anterior (comportamento original)."""
        bus = _make_bus()
        collector = _EventCollector(bus, [IntentCandidate])
        # min_growth_chars alto para forçar uso do debounce.
        engine = _make_engine(
            bus, debounce_ms=200,
            min_growth_chars=1000,  # força debounce
            min_append_words=100,
            min_interval_ms=0,
        )
        engine.start()
        try:
            # Publicar parcial e cancelar antes de debounce expirar.
            bus.publish(_make_partial_updated("O texto onde Jesus conversa"))
            time.sleep(0.05)  # < 200ms
            bus.publish(_make_partial_updated(
                "O texto onde Jesus conversa com Nicodemos"))
            time.sleep(0.05)  # < 200ms — debounce resetado
            # Não deve ter disparado ainda (debounce foi resetado).
            self.assertEqual(len(collector.of_type(IntentCandidate)), 0)
            # Aguardar debounce expirar.
            time.sleep(0.3)
            self.assertGreaterEqual(len(collector.of_type(IntentCandidate)), 1)
        finally:
            engine.stop()


# ============================================================
# Testes — Métricas.
# ============================================================


class TestStreamingMetrics(unittest.TestCase):
    """Métricas de growth_triggers e debounce_triggers são rastreadas."""

    def test_growth_trigger_metric_incremented(self):
        bus = _make_bus()
        _EventCollector(bus, [SemanticInferenceCompleted])
        engine = _make_engine(
            bus, debounce_ms=10000,
            min_growth_chars=20, min_append_words=3, min_interval_ms=0,
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("O Senhor é meu pastor"))
            time.sleep(0.05)
            stats = engine.stats()
            self.assertGreaterEqual(stats["total_growth_triggers"], 1)
        finally:
            engine.stop()

    def test_debounce_trigger_metric_incremented(self):
        bus = _make_bus()
        engine = _make_engine(
            bus, debounce_ms=80,
            min_growth_chars=1000,  # força debounce
            min_append_words=100,
            min_interval_ms=0,
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated(
                "O texto onde Jesus conversa com Nicodemos"))
            time.sleep(0.2)
            stats = engine.stats()
            self.assertGreaterEqual(stats["total_debounce_triggers"], 1)
        finally:
            engine.stop()

    def test_stats_includes_new_fields(self):
        bus = _make_bus()
        engine = _make_engine(bus)
        stats = engine.stats()
        self.assertIn("total_growth_triggers", stats)
        self.assertIn("total_debounce_triggers", stats)
        self.assertIn("min_growth_chars", stats)
        self.assertIn("min_append_words", stats)
        self.assertIn("min_interval_ms", stats)


# ============================================================
# Testes — Cenários obrigatórios (5 referências semânticas).
# ============================================================


class TestSemanticReferenceScenarios(unittest.TestCase):
    """Cenários obrigatórios da Sprint 21.5.

    Valida que referências semânticas geram inferência durante a fala,
    não apenas após o silêncio. Usa _SemanticStubProvider que reconhece
    as 5 referências semânticas da sprint.
    """

    def test_senhor_e_meu_pastor_fires_during_speech(self):
        """'O Senhor é meu pastor...' → Salmos 23 durante a fala."""
        bus = _make_bus()
        collector = _EventCollector(bus, [IntentCandidate, SemanticInferenceCompleted])
        engine = _make_engine(
            bus, debounce_ms=10000,  # debounce longo — prova que é growth
            min_growth_chars=20, min_append_words=3, min_interval_ms=0,
            provider=_SemanticStubProvider(),
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("O Senhor é meu pastor"))
            time.sleep(0.1)
            intents = collector.of_type(IntentCandidate)
            self.assertGreaterEqual(len(intents), 1,
                                    "Deve disparar durante a fala, sem esperar silêncio")
            import json
            cands = json.loads(intents[0].candidates_json)
            self.assertEqual(cands[0]["book"], "Salmos")
            self.assertEqual(cands[0]["chapter"], 23)
        finally:
            engine.stop()

    def test_porque_deus_amou_fires_during_speech(self):
        """'Porque Deus amou o mundo...' → João 3:16 durante a fala."""
        bus = _make_bus()
        collector = _EventCollector(bus, [IntentCandidate, SemanticInferenceCompleted])
        engine = _make_engine(
            bus, debounce_ms=10000,
            min_growth_chars=20, min_append_words=3, min_interval_ms=0,
            provider=_SemanticStubProvider(),
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("Porque Deus amou o mundo"))
            time.sleep(0.1)
            intents = collector.of_type(IntentCandidate)
            self.assertGreaterEqual(len(intents), 1)
            import json
            cands = json.loads(intents[0].candidates_json)
            self.assertEqual(cands[0]["book"], "João")
            self.assertEqual(cands[0]["chapter"], 3)
            self.assertEqual(cands[0]["verse"], 16)
        finally:
            engine.stop()

    def test_tudo_posso_fires_during_speech(self):
        """'Tudo posso naquele que me fortalece' → Filipenses 4:13."""
        bus = _make_bus()
        collector = _EventCollector(bus, [IntentCandidate, SemanticInferenceCompleted])
        engine = _make_engine(
            bus, debounce_ms=10000,
            min_growth_chars=20, min_append_words=3, min_interval_ms=0,
            provider=_SemanticStubProvider(),
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("Tudo posso naquele que me"))
            time.sleep(0.1)
            intents = collector.of_type(IntentCandidate)
            self.assertGreaterEqual(len(intents), 1)
            import json
            cands = json.loads(intents[0].candidates_json)
            self.assertEqual(cands[0]["book"], "Filipenses")
            self.assertEqual(cands[0]["chapter"], 4)
            self.assertEqual(cands[0]["verse"], 13)
        finally:
            engine.stop()

    def test_armadura_de_deus_fires_during_speech(self):
        """'A armadura de Deus...' → Efésios 6 durante a fala."""
        bus = _make_bus()
        collector = _EventCollector(bus, [IntentCandidate, SemanticInferenceCompleted])
        engine = _make_engine(
            bus, debounce_ms=10000,
            min_growth_chars=20, min_append_words=3, min_interval_ms=0,
            provider=_SemanticStubProvider(),
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("A armadura de Deus para"))
            time.sleep(0.1)
            intents = collector.of_type(IntentCandidate)
            self.assertGreaterEqual(len(intents), 1)
            import json
            cands = json.loads(intents[0].candidates_json)
            self.assertEqual(cands[0]["book"], "Efésios")
            self.assertEqual(cands[0]["chapter"], 6)
        finally:
            engine.stop()

    def test_ainda_que_eu_andasse_fires_during_speech(self):
        """'Ainda que eu andasse pelo vale...' → Salmos 23:4 durante a fala."""
        bus = _make_bus()
        collector = _EventCollector(bus, [IntentCandidate, SemanticInferenceCompleted])
        engine = _make_engine(
            bus, debounce_ms=10000,
            min_growth_chars=20, min_append_words=3, min_interval_ms=0,
            provider=_SemanticStubProvider(),
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("Ainda que eu andasse pelo vale da sombra"))
            time.sleep(0.1)
            intents = collector.of_type(IntentCandidate)
            self.assertGreaterEqual(len(intents), 1)
            import json
            cands = json.loads(intents[0].candidates_json)
            self.assertEqual(cands[0]["book"], "Salmos")
            self.assertEqual(cands[0]["chapter"], 23)
            self.assertEqual(cands[0]["verse"], 4)
        finally:
            engine.stop()


# ============================================================
# Testes — Compatibilidade (não regressão).
# ============================================================


class TestStreamingCompatibility(unittest.TestCase):
    """Garante que o comportamento anterior (Sprint 20) continua funcionando."""

    def test_cache_hit_skips_provider(self):
        """Cache hit continua funcionando (não chama LLM)."""
        bus = _make_bus()
        collector = _EventCollector(bus, [SemanticInferenceCompleted])
        calls: list = []

        class _CountingStub(StubProvider):
            def infer(self, context, timeout_ms=5000):
                calls.append(context.current_text)
                return super().infer(context, timeout_ms)

        engine = _make_engine(
            bus, debounce_ms=80,
            min_growth_chars=1000,  # força debounce
            min_append_words=100,
            min_interval_ms=0,
            provider=_CountingStub(),
        )
        engine.start()
        try:
            # Mesmo texto duas vezes — segunda deve ser cache hit.
            text = "O texto onde Jesus conversa com Nicodemos"
            bus.publish(_make_partial_updated(text))
            time.sleep(0.2)
            bus.publish(_make_partial_updated(text))
            time.sleep(0.2)
            # Provider só deve ter sido chamado 1 vez (segunda é cache).
            self.assertEqual(len(calls), 1,
                             "Cache hit deve pular chamada ao provider")
        finally:
            engine.stop()

    def test_disabled_engine_does_not_fire(self):
        """Engine desabilitado não dispara (kill switch)."""
        bus = _make_bus()
        collector = _EventCollector(bus, [IntentCandidate])
        engine = SemanticEngine(
            bus=bus, provider=StubProvider(),
            context_engine=ContextEngine(history_fn=bus.history),
            cache=SemanticCache(ttl_seconds=60),
            session_id="test", debounce_ms=80,
            enabled=False,
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("O Senhor é meu pastor"))
            time.sleep(0.2)
            self.assertEqual(len(collector.of_type(IntentCandidate)), 0)
        finally:
            engine.stop()

    def test_provider_unavailable_handled(self):
        """Provider indisponível é tratado graciosamente."""
        bus = _make_bus()
        collector = _EventCollector(bus, [SemanticInferenceCompleted])

        class _UnavailableProvider(StubProvider):
            def is_available(self):
                return False

        engine = _make_engine(
            bus, debounce_ms=80,
            min_growth_chars=1000, min_append_words=100,
            min_interval_ms=0,
            provider=_UnavailableProvider(),
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated(
                "O texto onde Jesus conversa com Nicodemos"))
            time.sleep(0.2)
            telemetries = collector.of_type(SemanticInferenceCompleted)
            self.assertGreaterEqual(len(telemetries), 1)
            self.assertIn("not available", telemetries[0].error)
        finally:
            engine.stop()


# ============================================================
# Testes — Crescimento incremental (múltiplas inferências).
# ============================================================


class TestMultipleInferences(unittest.TestCase):
    """Múltiplas inferências durante um sermão longo."""

    def test_multiple_inferences_during_long_speech(self):
        """Sermão longo: múltiplas inferências, cada uma com texto novo."""
        bus = _make_bus()
        collector = _EventCollector(bus, [SemanticInferenceCompleted])
        engine = _make_engine(
            bus, debounce_ms=10000,
            min_growth_chars=20, min_append_words=3,
            min_interval_ms=50,  # rápido para testes
        )
        engine.start()
        try:
            # Simular sermão: frases crescentes.
            phrases = [
                "O Senhor é meu pastor",           # dispara (22 chars)
                "O Senhor é meu pastor e nada me faltará agora",  # dispara
                "O Senhor é meu pastor e nada me faltará hoje e sempre",
            ]
            for text in phrases:
                bus.publish(_make_partial_updated(text))
                time.sleep(0.08)  # > min_interval_ms=50

            telemetries = collector.of_type(SemanticInferenceCompleted)
            # Deve ter pelo menos 2 inferências para textos diferentes.
            self.assertGreaterEqual(len(telemetries), 2,
                                    "Múltiplas inferências devem ocorrer em sermão longo")
        finally:
            engine.stop()

    def test_same_text_does_not_refire(self):
        """Mesmo texto repetido não dispara nova inferência (growth=0)."""
        bus = _make_bus()
        collector = _EventCollector(bus, [SemanticInferenceCompleted])
        engine = _make_engine(
            bus, debounce_ms=10000,
            min_growth_chars=20, min_append_words=3,
            min_interval_ms=0,
        )
        engine.start()
        try:
            text = "O Senhor é meu pastor"
            bus.publish(_make_partial_updated(text))
            time.sleep(0.05)
            count1 = len(collector.of_type(SemanticInferenceCompleted))

            # Mesmo texto — growth=0, append_words=0.
            bus.publish(_make_partial_updated(text))
            time.sleep(0.05)
            count2 = len(collector.of_type(SemanticInferenceCompleted))

            # Não deve ter disparado novamente (growth=0 < 22).
            self.assertEqual(count2, count1,
                             "Texto repetido não deve disparar nova inferência")
        finally:
            engine.stop()


if __name__ == "__main__":
    unittest.main()
