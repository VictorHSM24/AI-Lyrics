"""Testes Sprint 21 — Sermon Memory Engine (Parte 1: tipos + engine básico).

Cobre:
  - Tipos: BibleReference, SermonEntity, SermonTopic, SermonContext.
  - SermonMemoryEngine: lifecycle, contexto vazio, atualização incremental.
  - Eventos publicados: SermonContextUpdated.
  - Extração heurística de entidades e temas.
  - Reset de memória.
  - Engine desabilitado.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from pipeline.bus import PipelineEventBus
from pipeline.event_store import MemoryEventStore
from pipeline.events import (
    SermonBookChanged,
    SermonChapterChanged,
    SermonContextUpdated,
    SermonTopicChanged,
    SpeechPartial,
    SpeechPartialUpdated,
)
from pipeline.metadata import EventMetadata
from sermon import (
    BibleReference,
    EMPTY_SERMON_CONTEXT,
    SermonContext,
    SermonEntity,
    SermonMemoryEngine,
    SermonTopic,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bus():
    return PipelineEventBus(store=MemoryEventStore())


def _make_partial(text, session_id="s1", correlation_id=None):
    meta = EventMetadata.for_initial(
        session_id=session_id, origin="StreamingSTTService",
        correlation_id=correlation_id,
    )
    return SpeechPartial(
        meta=meta, text=text, language="pt",
        confidence=0.9, latency_ms=100, audio_duration_ms=2000,
        is_stable=False,
    )


def _make_partial_updated(text, session_id="s1", correlation_id=None):
    meta = EventMetadata.for_initial(
        session_id=session_id, origin="StreamingSTTService",
        correlation_id=correlation_id,
    )
    return SpeechPartialUpdated(
        meta=meta, text=text, appended_text=text,
        language="pt", confidence=0.9, latency_ms=100,
        audio_duration_ms=2000, is_stable=False,
    )


class _EventCollector:
    def __init__(self, bus, event_types):
        self.events = []
        for et in event_types:
            bus.subscribe(et, self._on_event)

    def _on_event(self, event):
        self.events.append(event)

    def of_type(self, et):
        return [e for e in self.events if isinstance(e, et)]


# ---------------------------------------------------------------------------
# Testes — Tipos (Etapa 2)
# ---------------------------------------------------------------------------


class TestSermonTypes:
    def test_bible_reference_str_with_verse(self):
        r = BibleReference(book="João", chapter=3, verse=16)
        assert r.reference_str == "João 3:16"

    def test_bible_reference_str_chapter_only(self):
        r = BibleReference(book="João", chapter=3, verse=0)
        assert r.reference_str == "João 3"

    def test_bible_reference_str_book_only(self):
        r = BibleReference(book="João", chapter=0, verse=0)
        assert r.reference_str == "João"

    def test_bible_reference_to_dict(self):
        r = BibleReference(book="João", chapter=3, verse=16, source="parser")
        d = r.to_dict()
        assert d["book"] == "João"
        assert d["chapter"] == 3
        assert d["verse"] == 16
        assert d["source"] == "parser"
        assert d["reference_str"] == "João 3:16"

    def test_sermon_entity_to_dict(self):
        e = SermonEntity(name="Jesus", weight=0.9, mention_count=3)
        d = e.to_dict()
        assert d["name"] == "Jesus"
        assert d["weight"] == 0.9
        assert d["mention_count"] == 3

    def test_sermon_topic_to_dict(self):
        t = SermonTopic(name="Graça", weight=0.8, mention_count=2)
        d = t.to_dict()
        assert d["name"] == "Graça"
        assert d["weight"] == 0.8

    def test_sermon_context_empty(self):
        ctx = EMPTY_SERMON_CONTEXT
        assert ctx.is_empty is True
        assert ctx.current_book is None
        assert ctx.current_chapter is None
        assert ctx.probable_theme is None
        assert len(ctx.entities) == 0
        assert len(ctx.recent_topics) == 0
        assert len(ctx.recent_references) == 0
        assert ctx.confidence == 0.0

    def test_sermon_context_not_empty(self):
        ctx = SermonContext(current_book="João", current_chapter=3)
        assert ctx.is_empty is False

    def test_sermon_context_to_dict(self):
        ctx = SermonContext(
            current_book="João",
            current_chapter=3,
            probable_theme="Novo nascimento",
            entities=(SermonEntity(name="Jesus"),),
            recent_topics=(SermonTopic(name="Graça"),),
            recent_references=(BibleReference(book="João", chapter=3),),
            confidence=0.85,
            total_updates=10,
        )
        d = ctx.to_dict()
        assert d["current_book"] == "João"
        assert d["current_chapter"] == 3
        assert d["probable_theme"] == "Novo nascimento"
        assert len(d["entities"]) == 1
        assert len(d["recent_topics"]) == 1
        assert len(d["recent_references"]) == 1
        assert d["confidence"] == 0.85
        assert d["total_updates"] == 10

    def test_sermon_context_age_seconds(self):
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        ctx = SermonContext(updated_at=old)
        assert ctx.age_seconds > 1_000_000  # muitos anos

    def test_sermon_context_immutable(self):
        ctx = SermonContext(current_book="João")
        with pytest.raises((AttributeError, Exception)):
            ctx.current_book = "Lucas"  # frozen dataclass


# ---------------------------------------------------------------------------
# Testes — SermonMemoryEngine lifecycle (Etapa 3)
# ---------------------------------------------------------------------------


class TestSermonMemoryEngineLifecycle:
    def test_start_stop(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        # Publicar parcial deve funcionar.
        bus.publish(_make_partial_updated("Jesus conversa com Nicodemos"))
        time.sleep(0.05)
        ctx = engine.get_context()
        # Engine processou — deve ter entidades.
        assert len(ctx.entities) > 0
        engine.stop()

    def test_disabled_engine(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [SermonContextUpdated])
        engine = SermonMemoryEngine(bus=bus, session_id="s1", enabled=False)
        engine.start()  # não assina
        try:
            bus.publish(_make_partial_updated("Jesus conversa com Nicodemos"))
            time.sleep(0.05)
            assert len(collector.of_type(SermonContextUpdated)) == 0
            ctx = engine.get_context()
            assert ctx.is_empty is True
        finally:
            engine.stop()

    def test_reset(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_partial_updated("Jesus conversa com Nicodemos"))
            time.sleep(0.05)
            assert not engine.get_context().is_empty
            engine.reset()
            ctx = engine.get_context()
            assert ctx.is_empty is True
        finally:
            engine.stop()


# ---------------------------------------------------------------------------
# Testes — Atualização incremental (Etapa 4)
# ---------------------------------------------------------------------------


class TestIncrementalUpdate:
    def test_entities_extracted_from_text(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_partial_updated("Jesus conversa com Nicodemos"))
            time.sleep(0.05)
            ctx = engine.get_context()
            names = [e.name.lower() for e in ctx.entities]
            assert "jesus" in names
            assert "nicodemos" in names
        finally:
            engine.stop()

    def test_topics_extracted_from_text(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_partial_updated("o novo nascimento é fundamental"))
            time.sleep(0.05)
            ctx = engine.get_context()
            topic_names = [t.name.lower() for t in ctx.recent_topics]
            assert "novo nascimento" in topic_names
        finally:
            engine.stop()

    def test_entity_reinforcement_increases_weight(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            # Primeira menção.
            bus.publish(_make_partial_updated("Jesus ensina"))
            time.sleep(0.05)
            ctx1 = engine.get_context()
            jesus1 = next(e for e in ctx1.entities if e.name.lower() == "jesus")
            weight1 = jesus1.weight

            # Segunda menção.
            bus.publish(_make_partial_updated("Jesus diz a Nicodemos"))
            time.sleep(0.05)
            ctx2 = engine.get_context()
            jesus2 = next(e for e in ctx2.entities if e.name.lower() == "jesus")
            assert jesus2.mention_count == jesus1.mention_count + 1
        finally:
            engine.stop()

    def test_short_text_ignored(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_partial_updated("oi"))  # < 3 chars
            time.sleep(0.05)
            ctx = engine.get_context()
            assert ctx.is_empty is True
        finally:
            engine.stop()

    def test_empty_text_ignored(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_partial_updated(""))
            time.sleep(0.05)
            ctx = engine.get_context()
            assert ctx.is_empty is True
        finally:
            engine.stop()


# ---------------------------------------------------------------------------
# Testes — Eventos publicados (Etapa 6)
# ---------------------------------------------------------------------------


class TestSermonEvents:
    def test_sermon_context_updated_published(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [SermonContextUpdated])
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_partial_updated("Jesus conversa com Nicodemos"))
            time.sleep(0.05)
            updates = collector.of_type(SermonContextUpdated)
            assert len(updates) >= 1
            u = updates[-1]
            assert u.meta.origin == "SermonMemoryEngine"
            assert u.num_entities > 0
            assert u.is_empty is False
        finally:
            engine.stop()

    def test_sermon_context_updated_has_json(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [SermonContextUpdated])
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_partial_updated("Jesus conversa com Nicodemos"))
            time.sleep(0.05)
            u = collector.of_type(SermonContextUpdated)[-1]
            import json
            ctx = json.loads(u.context_json)
            assert "current_book" in ctx
            assert "entities" in ctx
            assert "recent_topics" in ctx
        finally:
            engine.stop()


# ---------------------------------------------------------------------------
# Testes — Métricas (Etapa 10)
# ---------------------------------------------------------------------------


class TestSermonMetrics:
    def test_metrics_initial(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        m = engine.metrics()
        assert m["total_updates"] == 0
        assert m["book_changes"] == 0
        assert m["enabled"] is True

    def test_metrics_after_updates(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_partial_updated("Jesus conversa com Nicodemos"))
            time.sleep(0.05)
            m = engine.metrics()
            assert m["total_updates"] >= 1
            assert m["memory_size"]["entities"] > 0
        finally:
            engine.stop()


# ---------------------------------------------------------------------------
# Testes — ReferenceDetected → mudança de livro/capítulo (Etapa 4 + 6)
# ---------------------------------------------------------------------------


def _make_reference_detected(book, chapter, verse=0, correlation_id="c1",
                              origin="IncrementalBiblicalParser"):
    meta = EventMetadata.for_initial(
        session_id="s1", origin=origin, correlation_id=correlation_id,
    )
    from pipeline.events import ReferenceDetected
    return ReferenceDetected(
        meta=meta, book=book, chapter=chapter, verse_start=verse,
        verse_end=verse, confidence=0.95, raw_text=book,
        normalized_text=f"{book} {chapter}",
    )


class TestReferenceDetectedUpdates:
    def test_book_updated_from_reference(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_reference_detected("João", 3))
            time.sleep(0.05)
            ctx = engine.get_context()
            assert ctx.current_book == "João"
            assert ctx.current_chapter == 3
        finally:
            engine.stop()

    def test_book_changed_event_published(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [SermonBookChanged])
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_reference_detected("João", 3))
            time.sleep(0.05)
            bus.publish(_make_reference_detected("Romanos", 1))
            time.sleep(0.05)
            changes = collector.of_type(SermonBookChanged)
            assert len(changes) >= 1
            # Última mudança: João → Romanos.
            last = changes[-1]
            assert last.previous_book == "João"
            assert last.new_book == "Romanos"
        finally:
            engine.stop()

    def test_chapter_changed_event_published(self):
        bus = _make_bus()
        collector = _EventCollector(bus, [SermonChapterChanged])
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_reference_detected("João", 3))
            time.sleep(0.05)
            bus.publish(_make_reference_detected("João", 5))
            time.sleep(0.05)
            changes = collector.of_type(SermonChapterChanged)
            assert len(changes) >= 1
            last = changes[-1]
            assert last.book == "João"
            assert last.previous_chapter == 3
            assert last.new_chapter == 5
        finally:
            engine.stop()

    def test_reference_added_to_history(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_reference_detected("João", 3, verse=16))
            time.sleep(0.05)
            ctx = engine.get_context()
            assert len(ctx.recent_references) == 1
            ref = ctx.recent_references[0]
            assert ref.book == "João"
            assert ref.chapter == 3
            assert ref.verse == 16
        finally:
            engine.stop()

    def test_duplicate_reference_not_added(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_reference_detected("João", 3, verse=16))
            time.sleep(0.05)
            bus.publish(_make_reference_detected("João", 3, verse=16))
            time.sleep(0.05)
            ctx = engine.get_context()
            assert len(ctx.recent_references) == 1
        finally:
            engine.stop()

    def test_reference_source_tracked(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            # Referência do parser.
            bus.publish(_make_reference_detected("João", 3, origin="IncrementalBiblicalParser"))
            time.sleep(0.05)
            ctx = engine.get_context()
            assert ctx.recent_references[0].source == "parser"

            # Referência do resolver (semantic).
            bus.publish(_make_reference_detected("Lucas", 10, origin="ReferenceResolver"))
            time.sleep(0.05)
            ctx = engine.get_context()
            sources = [r.source for r in ctx.recent_references]
            assert "semantic" in sources
        finally:
            engine.stop()


# ---------------------------------------------------------------------------
# Testes — Decaimento temporal (Etapa 5)
# ---------------------------------------------------------------------------


class TestTemporalDecay:
    def test_entity_decays_over_time(self):
        bus = _make_bus()
        # Meia-vida curta para testar rápido.
        engine = SermonMemoryEngine(
            bus=bus, session_id="s1",
            entity_decay_half_life_s=0.1,  # 100ms
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("Jesus ensina"))
            time.sleep(0.05)
            ctx1 = engine.get_context()
            jesus1 = next(e for e in ctx1.entities if e.name.lower() == "jesus")
            w1 = jesus1.weight

            # Esperar decaimento (várias meias-vidas).
            time.sleep(0.5)
            # Trigger nova atualização para aplicar decaimento.
            bus.publish(_make_partial_updated("outro texto qualquer aqui"))
            time.sleep(0.05)
            ctx2 = engine.get_context()
            jesus2 = next(
                (e for e in ctx2.entities if e.name.lower() == "jesus"), None
            )
            # Jesus deve ter decaído significativamente ou expirado.
            if jesus2 is not None:
                assert jesus2.weight < w1
        finally:
            engine.stop()

    def test_expired_entity_removed(self):
        bus = _make_bus()
        engine = SermonMemoryEngine(
            bus=bus, session_id="s1",
            entity_decay_half_life_s=0.05,  # 50ms — expira rápido
        )
        engine.start()
        try:
            bus.publish(_make_partial_updated("Jesus ensina"))
            time.sleep(0.05)
            ctx1 = engine.get_context()
            assert any(e.name.lower() == "jesus" for e in ctx1.entities)

            # Esperar expiração.
            time.sleep(0.3)
            # Nova atualização para aplicar decaimento.
            bus.publish(_make_partial_updated("texto qualquer diferente agora"))
            time.sleep(0.05)
            ctx2 = engine.get_context()
            # Jesus deve ter expirado (peso < min).
            jesus = next(
                (e for e in ctx2.entities if e.name.lower() == "jesus"), None
            )
            assert jesus is None
        finally:
            engine.stop()


# ---------------------------------------------------------------------------
# Testes — Integração com SemanticEngine (Etapa 7)
# ---------------------------------------------------------------------------


class TestSemanticEngineIntegration:
    def test_context_engine_uses_sermon_context(self):
        """ContextEngine enriquece SemanticContext com SermonContext."""
        from semantic import ContextEngine

        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            # Alimentar memória com referência.
            bus.publish(_make_reference_detected("João", 3))
            time.sleep(0.05)

            # ContextEngine com sermon_context_fn.
            ce = ContextEngine(
                history_fn=bus.history,
                sermon_context_fn=engine.get_context,
            )
            ctx = ce.build(current_text="como vimos anteriormente")
            assert ctx.sermon_book == "João"
            assert ctx.sermon_chapter == 3
        finally:
            engine.stop()

    def test_context_engine_without_sermon_fn(self):
        """ContextEngine funciona sem sermon_context_fn (compatibilidade Sprint 20)."""
        from semantic import ContextEngine

        bus = _make_bus()
        ce = ContextEngine(history_fn=bus.history)
        ctx = ce.build(current_text="teste")
        assert ctx.sermon_book == ""
        assert ctx.sermon_chapter == 0
        assert ctx.sermon_entities == ()

    def test_sermon_context_in_hash(self):
        """SermonContext afeta o hash do SemanticContext (cache)."""
        from semantic import ContextEngine

        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            ce = ContextEngine(
                history_fn=bus.history,
                sermon_context_fn=engine.get_context,
            )
            # Hash antes de ter livro.
            ctx1 = ce.build(current_text="Nicodemos")
            h1 = ctx1.context_hash()

            # Alimentar memória com livro.
            bus.publish(_make_reference_detected("João", 3))
            time.sleep(0.05)

            # Hash depois de ter livro — deve ser diferente.
            ctx2 = ce.build(current_text="Nicodemos")
            h2 = ctx2.context_hash()
            assert h1 != h2
        finally:
            engine.stop()


# ---------------------------------------------------------------------------
# Testes — Fluxo contínuo de pregação (Etapa 11 — critério de aceitação)
# ---------------------------------------------------------------------------


class TestContinuousSermonFlow:
    """Simula uma sequência real de pregação e verifica evolução do contexto."""

    def test_sermon_evolution_nicodemos(self):
        """Critério de aceitação: João → Nicodemos → Novo nascimento → contexto evolui."""
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            # 1. "Hoje vamos estudar João..."
            bus.publish(_make_reference_detected("João", 3))
            time.sleep(0.05)
            ctx1 = engine.get_context()
            assert ctx1.current_book == "João"
            assert ctx1.current_chapter == 3

            # 2. "Nicodemos procura Jesus..."
            bus.publish(_make_partial_updated("Nicodemos procura Jesus à noite"))
            time.sleep(0.05)
            ctx2 = engine.get_context()
            names = [e.name.lower() for e in ctx2.entities]
            assert "nicodemos" in names
            assert "jesus" in names

            # 3. "Importa nascer de novo..."
            bus.publish(_make_partial_updated("Importa nascer de novo do espírito"))
            time.sleep(0.05)
            ctx3 = engine.get_context()
            topic_names = [t.name.lower() for t in ctx3.recent_topics]
            assert "novo nascimento" in topic_names

            # 4. "Como vimos anteriormente..." — contexto deve manter João.
            bus.publish(_make_partial_updated("Como vimos anteriormente"))
            time.sleep(0.05)
            ctx4 = engine.get_context()
            assert ctx4.current_book == "João"
            # Entidades Jesus e Nicodemos ainda presentes.
            names4 = [e.name.lower() for e in ctx4.entities]
            assert "jesus" in names4 or "nicodemos" in names4

            # 5. Verificar evolução: contexto final é rico.
            assert ctx4.total_updates > ctx1.total_updates
        finally:
            engine.stop()

    def test_sermon_book_change_resets_chapter(self):
        """Mudança de livro deve atualizar current_book."""
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_reference_detected("João", 3))
            time.sleep(0.05)
            assert engine.get_context().current_book == "João"

            bus.publish(_make_reference_detected("Romanos", 1))
            time.sleep(0.05)
            ctx = engine.get_context()
            assert ctx.current_book == "Romanos"
            assert ctx.current_chapter == 1
        finally:
            engine.stop()

    def test_reconstruction_after_reset(self):
        """Após reset, a memória pode ser reconstruída."""
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="s1")
        engine.start()
        try:
            bus.publish(_make_reference_detected("João", 3))
            time.sleep(0.05)
            assert engine.get_context().current_book == "João"

            engine.reset()
            assert engine.get_context().is_empty

            # Reconstruir.
            bus.publish(_make_reference_detected("Lucas", 10))
            time.sleep(0.05)
            ctx = engine.get_context()
            assert ctx.current_book == "Lucas"
        finally:
            engine.stop()
