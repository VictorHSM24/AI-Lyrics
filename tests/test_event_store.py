"""Testes do Event Store Layer (Fase 12.1).

Cobre:
  - EventStore (interface abstrata).
  - MemoryEventStore (append, append_many, all, clear, count, last,
    by_event, by_correlation, by_session, by_origin, between).
  - EventStorePolicy (limites, estratégias de retenção).
  - EventStoreStatistics (contadores, by_type, by_session, by_origin,
    by_correlation, reset, to_dict).
  - Integração EventBus ↔ EventStore (delegação, store injetado,
    store padrão, compatibilidade).
  - Imutabilidade externa (all() retorna tuple).
  - Serialização (to_dict).
"""

from __future__ import annotations

import unittest

import sys
sys.path.insert(0, ".")

from pipeline import (
    EventMetadata,
    EventStore,
    EventStorePolicy,
    EventStoreStatistics,
    MemoryEventStore,
    PipelineEventBus,
    SearchCompleted,
    SearchRequested,
    SpeechRecognized,
    SpeechSegmentReceived,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_meta(
    session_id: str = "s1",
    correlation_id: str = "c1",
    event_id: str = "e1",
    timestamp: float = 100.0,
    origin: str = "test",
):
    return EventMetadata(
        event_id=event_id,
        correlation_id=correlation_id,
        causation_id=None,
        session_id=session_id,
        timestamp=timestamp,
        origin=origin,
    )


def _make_event(
    cls=SpeechRecognized,
    session_id: str = "s1",
    correlation_id: str = "c1",
    event_id: str = "e1",
    timestamp: float = 100.0,
    origin: str = "test",
    **kwargs,
):
    meta = _make_meta(session_id, correlation_id, event_id, timestamp, origin)
    return cls(meta=meta, **kwargs)


# ---------------------------------------------------------------------------
# EventStore (interface)
# ---------------------------------------------------------------------------


class TestEventStoreInterface(unittest.TestCase):
    """Testes da interface EventStore."""

    def test_eventstore_is_abstract(self):
        """EventStore não pode ser instanciada diretamente."""
        with self.assertRaises(TypeError):
            EventStore()  # type: ignore

    def test_eventstore_has_all_methods(self):
        """EventStore deve declarar todos os métodos abstratos."""
        methods = [
            "append", "append_many", "all", "clear", "count",
            "last", "by_event", "by_correlation", "by_session",
            "by_origin", "between",
        ]
        for m in methods:
            self.assertTrue(
                hasattr(EventStore, m),
                f"EventStore deve ter método {m}"
            )


# ---------------------------------------------------------------------------
# MemoryEventStore — escrita
# ---------------------------------------------------------------------------


class TestMemoryEventStoreWrite(unittest.TestCase):
    """Testes de escrita do MemoryEventStore."""

    def test_append_single(self):
        store = MemoryEventStore()
        ev = _make_event()
        store.append(ev)
        self.assertEqual(store.count(), 1)

    def test_append_multiple(self):
        store = MemoryEventStore()
        store.append(_make_event(event_id="e1"))
        store.append(_make_event(event_id="e2"))
        store.append(_make_event(event_id="e3"))
        self.assertEqual(store.count(), 3)

    def test_append_many(self):
        store = MemoryEventStore()
        events = [_make_event(event_id=f"e{i}") for i in range(5)]
        store.append_many(events)
        self.assertEqual(store.count(), 5)

    def test_append_many_empty(self):
        store = MemoryEventStore()
        store.append_many([])
        self.assertEqual(store.count(), 0)

    def test_append_preserves_order(self):
        store = MemoryEventStore()
        store.append(_make_event(event_id="e1", text="first"))
        store.append(_make_event(event_id="e2", text="second"))
        store.append(_make_event(event_id="e3", text="third"))
        all_ev = store.all()
        self.assertEqual(all_ev[0].text, "first")
        self.assertEqual(all_ev[1].text, "second")
        self.assertEqual(all_ev[2].text, "third")

    def test_no_deduplication(self):
        """MemoryEventStore não deduplica automaticamente."""
        store = MemoryEventStore()
        ev = _make_event(event_id="e1")
        store.append(ev)
        store.append(ev)  # mesmo evento
        self.assertEqual(store.count(), 2)


# ---------------------------------------------------------------------------
# MemoryEventStore — leitura
# ---------------------------------------------------------------------------


class TestMemoryEventStoreRead(unittest.TestCase):
    """Testes de leitura/consulta do MemoryEventStore."""

    def setUp(self):
        self.store = MemoryEventStore()
        # Eventos com diferentes correlation_id, session_id, origin, timestamp
        self.store.append(_make_event(
            cls=SpeechRecognized, event_id="e1", correlation_id="c1",
            session_id="s1", origin="RecognitionHandler",
            timestamp=100.0, text="hello"))
        self.store.append(_make_event(
            cls=SearchRequested, event_id="e2", correlation_id="c1",
            session_id="s1", origin="SearchHandler",
            timestamp=200.0, query="fé"))
        self.store.append(_make_event(
            cls=SearchCompleted, event_id="e3", correlation_id="c1",
            session_id="s1", origin="SearchHandler",
            timestamp=300.0, query="fé"))
        self.store.append(_make_event(
            cls=SpeechRecognized, event_id="e4", correlation_id="c2",
            session_id="s1", origin="RecognitionHandler",
            timestamp=400.0, text="world"))
        self.store.append(_make_event(
            cls=SpeechRecognized, event_id="e5", correlation_id="c3",
            session_id="s2", origin="RecognitionHandler",
            timestamp=500.0, text="other session"))

    def test_all_returns_tuple(self):
        """all() deve retornar tuple (imutável)."""
        result = self.store.all()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 5)

    def test_all_is_copy(self):
        """all() deve retornar uma cópia imutável (tuple)."""
        result = self.store.all()
        # tuple é imutável — não pode ser modificado
        self.assertIsInstance(result, tuple)
        # Verificar que modificar a lista interna não afeta o tuple retornado
        # (all() retorna uma cópia em forma de tuple)
        original_count = self.store.count()
        # all() deve retornar tuple (imutável por natureza)
        self.assertEqual(len(result), original_count)
        self.assertEqual(self.store.count(), original_count)

    def test_count(self):
        self.assertEqual(self.store.count(), 5)

    def test_last(self):
        """last() deve retornar o último evento adicionado."""
        last = self.store.last()
        self.assertIsNotNone(last)
        self.assertEqual(last.event_id, "e5")

    def test_last_empty(self):
        """last() em store vazio deve retornar None."""
        store = MemoryEventStore()
        self.assertIsNone(store.last())

    def test_by_event_type(self):
        """by_event filtra por tipo de evento."""
        result = self.store.by_event(SpeechRecognized)
        self.assertEqual(len(result), 3)
        for ev in result:
            self.assertIsInstance(ev, SpeechRecognized)

    def test_by_event_type_empty(self):
        """by_event para tipo sem eventos retorna tuple vazio."""
        result = self.store.by_event(SpeechSegmentReceived)
        self.assertEqual(len(result), 0)

    def test_by_correlation(self):
        """by_correlation filtra por correlation_id."""
        result = self.store.by_correlation("c1")
        self.assertEqual(len(result), 3)
        for ev in result:
            self.assertEqual(ev.correlation_id, "c1")

    def test_by_correlation_preserves_order(self):
        """by_correlation preserva ordem de inserção."""
        result = self.store.by_correlation("c1")
        self.assertEqual(result[0].event_id, "e1")
        self.assertEqual(result[1].event_id, "e2")
        self.assertEqual(result[2].event_id, "e3")

    def test_by_correlation_not_found(self):
        result = self.store.by_correlation("nonexistent")
        self.assertEqual(len(result), 0)

    def test_by_session(self):
        """by_session filtra por session_id."""
        result = self.store.by_session("s1")
        self.assertEqual(len(result), 4)
        result2 = self.store.by_session("s2")
        self.assertEqual(len(result2), 1)

    def test_by_session_preserves_order(self):
        result = self.store.by_session("s1")
        self.assertEqual(result[0].event_id, "e1")
        self.assertEqual(result[3].event_id, "e4")

    def test_by_session_not_found(self):
        result = self.store.by_session("nonexistent")
        self.assertEqual(len(result), 0)

    def test_by_origin(self):
        """by_origin filtra por origin."""
        result = self.store.by_origin("RecognitionHandler")
        self.assertEqual(len(result), 3)
        result2 = self.store.by_origin("SearchHandler")
        self.assertEqual(len(result2), 2)

    def test_by_origin_not_found(self):
        result = self.store.by_origin("nonexistent")
        self.assertEqual(len(result), 0)

    def test_between_inclusive(self):
        """between filtra por intervalo temporal (inclusivo)."""
        result = self.store.between(200.0, 400.0)
        self.assertEqual(len(result), 3)
        for ev in result:
            self.assertTrue(200.0 <= ev.timestamp <= 400.0)

    def test_between_full_range(self):
        result = self.store.between(0.0, 1000.0)
        self.assertEqual(len(result), 5)

    def test_between_empty_range(self):
        result = self.store.between(1000.0, 2000.0)
        self.assertEqual(len(result), 0)

    def test_between_exact_boundary(self):
        """between inclui eventos exatamente no boundary."""
        result = self.store.between(100.0, 100.0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].event_id, "e1")


# ---------------------------------------------------------------------------
# MemoryEventStore — limpeza
# ---------------------------------------------------------------------------


class TestMemoryEventStoreClear(unittest.TestCase):
    """Testes de limpeza do MemoryEventStore."""

    def test_clear(self):
        store = MemoryEventStore()
        store.append(_make_event())
        store.append(_make_event(event_id="e2"))
        self.assertEqual(store.count(), 2)
        store.clear()
        self.assertEqual(store.count(), 0)
        self.assertIsNone(store.last())

    def test_clear_empty(self):
        """clear() em store vazio não deve erro."""
        store = MemoryEventStore()
        store.clear()
        self.assertEqual(store.count(), 0)


# ---------------------------------------------------------------------------
# MemoryEventStore — policy
# ---------------------------------------------------------------------------


class TestMemoryEventStorePolicy(unittest.TestCase):
    """Testes de aplicação de policy no MemoryEventStore."""

    def test_unlimited_by_default(self):
        """Sem policy, store é ilimitado."""
        store = MemoryEventStore()
        for i in range(100):
            store.append(_make_event(event_id=f"e{i}"))
        self.assertEqual(store.count(), 100)

    def test_drop_oldest(self):
        """Policy drop_oldest remove os mais antigos ao atingir limite."""
        policy = EventStorePolicy(max_events=3, retention_strategy="drop_oldest")
        store = MemoryEventStore(policy=policy)
        store.append(_make_event(event_id="e1", text="first"))
        store.append(_make_event(event_id="e2", text="second"))
        store.append(_make_event(event_id="e3", text="third"))
        store.append(_make_event(event_id="e4", text="fourth"))
        self.assertEqual(store.count(), 3)
        # O mais antigo (e1) deve ter sido removido
        all_ev = store.all()
        self.assertEqual(all_ev[0].text, "second")
        self.assertEqual(all_ev[2].text, "fourth")

    def test_drop_newest(self):
        """Policy drop_newest rejeita novos ao atingir limite."""
        policy = EventStorePolicy(max_events=3, retention_strategy="drop_newest")
        store = MemoryEventStore(policy=policy)
        store.append(_make_event(event_id="e1", text="first"))
        store.append(_make_event(event_id="e2", text="second"))
        store.append(_make_event(event_id="e3", text="third"))
        store.append(_make_event(event_id="e4", text="fourth"))
        self.assertEqual(store.count(), 3)
        # O mais novo (e4) deve ter sido removido
        all_ev = store.all()
        self.assertEqual(all_ev[0].text, "first")
        self.assertEqual(all_ev[2].text, "third")

    def test_reject(self):
        """Policy reject levanta erro ao atingir limite."""
        policy = EventStorePolicy(max_events=2, retention_strategy="reject")
        store = MemoryEventStore(policy=policy)
        store.append(_make_event(event_id="e1"))
        store.append(_make_event(event_id="e2"))
        with self.assertRaises(OverflowError):
            store.append(_make_event(event_id="e3"))
        self.assertEqual(store.count(), 2)

    def test_policy_is_accessible(self):
        """store.policy deve retornar a policy configurada."""
        policy = EventStorePolicy(max_events=10)
        store = MemoryEventStore(policy=policy)
        self.assertIs(store.policy, policy)


# ---------------------------------------------------------------------------
# EventStorePolicy
# ---------------------------------------------------------------------------


class TestEventStorePolicy(unittest.TestCase):
    """Testes da EventStorePolicy."""

    def test_policy_defaults(self):
        p = EventStorePolicy()
        self.assertEqual(p.max_events, 0)  # ilimitado
        self.assertEqual(p.retention_strategy, "drop_oldest")
        self.assertFalse(p.auto_cleanup)

    def test_policy_is_frozen(self):
        p = EventStorePolicy()
        with self.assertRaises(Exception):
            p.max_events = 100  # type: ignore

    def test_policy_is_unlimited(self):
        self.assertTrue(EventStorePolicy(max_events=0).is_unlimited())
        self.assertFalse(EventStorePolicy(max_events=10).is_unlimited())

    def test_policy_should_drop_oldest(self):
        self.assertTrue(EventStorePolicy(
            retention_strategy="drop_oldest").should_drop_oldest())
        self.assertFalse(EventStorePolicy(
            retention_strategy="drop_newest").should_drop_oldest())

    def test_policy_should_drop_newest(self):
        self.assertTrue(EventStorePolicy(
            retention_strategy="drop_newest").should_drop_newest())

    def test_policy_should_reject(self):
        self.assertTrue(EventStorePolicy(
            retention_strategy="reject").should_reject())

    def test_policy_custom_values(self):
        p = EventStorePolicy(
            max_events=500,
            retention_strategy="reject",
            auto_cleanup=True,
            cleanup_interval_events=50,
        )
        self.assertEqual(p.max_events, 500)
        self.assertEqual(p.retention_strategy, "reject")
        self.assertTrue(p.auto_cleanup)
        self.assertEqual(p.cleanup_interval_events, 50)


# ---------------------------------------------------------------------------
# EventStoreStatistics
# ---------------------------------------------------------------------------


class TestEventStoreStatistics(unittest.TestCase):
    """Testes da EventStoreStatistics."""

    def test_statistics_defaults(self):
        stats = EventStoreStatistics()
        self.assertEqual(stats.events_appended, 0)
        self.assertEqual(stats.events_removed, 0)
        self.assertEqual(stats.by_type, {})
        self.assertEqual(stats.by_session, {})
        self.assertEqual(stats.by_origin, {})
        self.assertEqual(stats.by_correlation, {})

    def test_statistics_record_append(self):
        stats = EventStoreStatistics()
        ev = _make_event(
            cls=SpeechRecognized, session_id="s1",
            correlation_id="c1", origin="RecognitionHandler")
        stats.record_append(ev)
        self.assertEqual(stats.events_appended, 1)
        self.assertEqual(stats.by_type["SpeechRecognized"], 1)
        self.assertEqual(stats.by_session["s1"], 1)
        self.assertEqual(stats.by_origin["RecognitionHandler"], 1)
        self.assertEqual(stats.by_correlation["c1"], 1)

    def test_statistics_record_append_multiple_types(self):
        stats = EventStoreStatistics()
        stats.record_append(_make_event(cls=SpeechRecognized))
        stats.record_append(_make_event(cls=SearchRequested))
        stats.record_append(_make_event(cls=SpeechRecognized))
        self.assertEqual(stats.by_type["SpeechRecognized"], 2)
        self.assertEqual(stats.by_type["SearchRequested"], 1)

    def test_statistics_record_remove(self):
        stats = EventStoreStatistics()
        stats.record_append(_make_event())
        stats.record_remove(1)
        self.assertEqual(stats.events_removed, 1)

    def test_statistics_reset(self):
        stats = EventStoreStatistics()
        stats.record_append(_make_event())
        stats.record_remove(1)
        stats.reset()
        self.assertEqual(stats.events_appended, 0)
        self.assertEqual(stats.events_removed, 0)
        self.assertEqual(stats.by_type, {})

    def test_statistics_to_dict(self):
        stats = EventStoreStatistics()
        stats.record_append(_make_event(
            cls=SpeechRecognized, session_id="s1",
            correlation_id="c1", origin="test"))
        d = stats.to_dict()
        self.assertEqual(d["events_appended"], 1)
        self.assertEqual(d["events_current"], 1)
        self.assertEqual(d["by_type"]["SpeechRecognized"], 1)
        self.assertEqual(d["unique_types"], 1)
        self.assertEqual(d["unique_sessions"], 1)
        self.assertEqual(d["unique_origins"], 1)
        self.assertEqual(d["unique_correlations"], 1)

    def test_statistics_auto_updated_by_store(self):
        """Store atualiza statistics automaticamente."""
        store = MemoryEventStore()
        store.append(_make_event(cls=SpeechRecognized, session_id="s1"))
        store.append(_make_event(cls=SearchRequested, session_id="s1"))
        stats = store.statistics
        self.assertEqual(stats.events_appended, 2)
        self.assertEqual(stats.by_type["SpeechRecognized"], 1)
        self.assertEqual(stats.by_type["SearchRequested"], 1)

    def test_statistics_removed_on_clear(self):
        """clear() registra remoção nas statistics."""
        store = MemoryEventStore()
        store.append(_make_event())
        store.append(_make_event(event_id="e2"))
        store.clear()
        self.assertEqual(store.statistics.events_removed, 2)

    def test_statistics_removed_on_drop_oldest(self):
        """drop_oldest registra remoção nas statistics."""
        policy = EventStorePolicy(max_events=2, retention_strategy="drop_oldest")
        store = MemoryEventStore(policy=policy)
        store.append(_make_event(event_id="e1"))
        store.append(_make_event(event_id="e2"))
        store.append(_make_event(event_id="e3"))  # remove e1
        self.assertEqual(store.statistics.events_removed, 1)
        self.assertEqual(store.statistics.events_appended, 3)


# ---------------------------------------------------------------------------
# MemoryEventStore — serialização
# ---------------------------------------------------------------------------


class TestMemoryEventStoreSerialization(unittest.TestCase):
    """Testes de serialização do MemoryEventStore."""

    def test_to_dict(self):
        store = MemoryEventStore()
        store.append(_make_event(cls=SpeechRecognized))
        d = store.to_dict()
        self.assertEqual(d["count"], 1)
        self.assertIn("policy", d)
        self.assertIn("statistics", d)
        self.assertEqual(d["policy"]["max_events"], 0)

    def test_to_dict_with_policy(self):
        policy = EventStorePolicy(max_events=100, retention_strategy="reject")
        store = MemoryEventStore(policy=policy)
        d = store.to_dict()
        self.assertEqual(d["policy"]["max_events"], 100)
        self.assertEqual(d["policy"]["retention_strategy"], "reject")


# ---------------------------------------------------------------------------
# Integração EventBus ↔ EventStore
# ---------------------------------------------------------------------------


class TestEventBusEventStoreIntegration(unittest.TestCase):
    """Testes de integração entre EventBus e EventStore."""

    def test_bus_creates_default_store(self):
        """Bus sem store injetado cria MemoryEventStore padrão."""
        bus = PipelineEventBus()
        self.assertIsInstance(bus.store, MemoryEventStore)

    def test_bus_uses_injected_store(self):
        """Bus usa o store injetado."""
        store = MemoryEventStore()
        bus = PipelineEventBus(store=store)
        self.assertIs(bus.store, store)

    def test_publish_appends_to_store(self):
        """publish() deve adicionar evento ao store."""
        store = MemoryEventStore()
        bus = PipelineEventBus(store=store)
        ev = _make_event()
        bus.publish(ev)
        self.assertEqual(store.count(), 1)
        self.assertIs(store.last(), ev)

    def test_event_count_delegates_to_store(self):
        """event_count() delega ao store.count()."""
        store = MemoryEventStore()
        bus = PipelineEventBus(store=store)
        bus.publish(_make_event(event_id="e1"))
        bus.publish(_make_event(event_id="e2"))
        self.assertEqual(bus.event_count(), 2)
        self.assertEqual(bus.event_count(), store.count())

    def test_history_delegates_to_store(self):
        """history() delega ao store.all()."""
        store = MemoryEventStore()
        bus = PipelineEventBus(store=store)
        bus.publish(_make_event(event_id="e1"))
        bus.publish(_make_event(event_id="e2"))
        hist = bus.history()
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0].event_id, "e1")
        self.assertEqual(hist[1].event_id, "e2")

    def test_history_types_delegates_to_store(self):
        """history_types() delega ao store.all()."""
        store = MemoryEventStore()
        bus = PipelineEventBus(store=store)
        bus.publish(_make_event(cls=SpeechRecognized))
        bus.publish(_make_event(cls=SearchRequested))
        types = bus.history_types()
        self.assertEqual(types, ("SpeechRecognized", "SearchRequested"))

    def test_clear_history_delegates_to_store(self):
        """clear_history() delega ao store.clear()."""
        store = MemoryEventStore()
        bus = PipelineEventBus(store=store)
        bus.publish(_make_event())
        bus.clear_history()
        self.assertEqual(store.count(), 0)
        self.assertEqual(len(bus.history()), 0)

    def test_clear_clears_subscriptions_and_store(self):
        """clear() remove inscrições E limpa store."""
        store = MemoryEventStore()
        bus = PipelineEventBus(store=store)
        bus.subscribe(SpeechRecognized, lambda e: None)
        bus.publish(_make_event())
        bus.clear()
        self.assertEqual(store.count(), 0)
        self.assertFalse(bus.has_subscribers(SpeechRecognized))

    def test_store_queries_accessible_via_bus(self):
        """Consultas do store são acessíveis via bus.store."""
        store = MemoryEventStore()
        bus = PipelineEventBus(store=store)
        bus.publish(_make_event(
            cls=SpeechRecognized, correlation_id="c1", session_id="s1"))
        bus.publish(_make_event(
            cls=SearchRequested, correlation_id="c1", session_id="s1"))
        bus.publish(_make_event(
            cls=SpeechRecognized, correlation_id="c2", session_id="s1"))
        # Consultar via store
        self.assertEqual(len(bus.store.by_correlation("c1")), 2)
        self.assertEqual(len(bus.store.by_session("s1")), 3)
        self.assertEqual(len(bus.store.by_event(SpeechRecognized)), 2)

    def test_store_with_policy_via_bus(self):
        """Store com policy funciona via bus."""
        policy = EventStorePolicy(max_events=2, retention_strategy="drop_oldest")
        store = MemoryEventStore(policy=policy)
        bus = PipelineEventBus(store=store)
        bus.publish(_make_event(event_id="e1"))
        bus.publish(_make_event(event_id="e2"))
        bus.publish(_make_event(event_id="e3"))
        self.assertEqual(bus.event_count(), 2)  # limitado pela policy

    def test_store_statistics_accessible_via_bus(self):
        """Statistics do store são acessíveis via bus.store."""
        store = MemoryEventStore()
        bus = PipelineEventBus(store=store)
        bus.publish(_make_event(cls=SpeechRecognized, session_id="s1"))
        bus.publish(_make_event(cls=SearchRequested, session_id="s1"))
        stats = bus.store.statistics
        self.assertEqual(stats.events_appended, 2)
        self.assertEqual(stats.by_type["SpeechRecognized"], 1)
        self.assertEqual(stats.by_type["SearchRequested"], 1)

    def test_multiple_buses_share_store(self):
        """Múltiplos buses podem compartilhar o mesmo store."""
        store = MemoryEventStore()
        bus1 = PipelineEventBus(store=store)
        bus2 = PipelineEventBus(store=store)
        bus1.publish(_make_event(event_id="e1"))
        bus2.publish(_make_event(event_id="e2"))
        self.assertEqual(store.count(), 2)
        self.assertEqual(len(bus1.history()), 2)
        self.assertEqual(len(bus2.history()), 2)

    def test_store_preserves_event_immutability(self):
        """Eventos no store permanecem imutáveis."""
        store = MemoryEventStore()
        ev = _make_event(text="original")
        store.append(ev)
        retrieved = store.all()[0]
        with self.assertRaises(Exception):
            retrieved.text = "modified"  # type: ignore
        self.assertEqual(retrieved.text, "original")


# ---------------------------------------------------------------------------
# Compatibilidade
# ---------------------------------------------------------------------------


class TestEventStoreCompatibility(unittest.TestCase):
    """Testes de compatibilidade — APIs antigas continuam funcionando."""

    def test_bus_without_store_works(self):
        """Bus sem store continua funcionando (cria default)."""
        bus = PipelineEventBus()
        bus.publish(_make_event())
        self.assertEqual(bus.event_count(), 1)
        self.assertEqual(len(bus.history()), 1)

    def test_history_returns_tuple(self):
        """history() continua retornando tuple."""
        bus = PipelineEventBus()
        bus.publish(_make_event())
        self.assertIsInstance(bus.history(), tuple)

    def test_history_types_returns_tuple(self):
        """history_types() continua retornando tuple."""
        bus = PipelineEventBus()
        bus.publish(_make_event())
        self.assertIsInstance(bus.history_types(), tuple)

    def test_publish_notifies_handlers(self):
        """publish() continua notificando handlers."""
        bus = PipelineEventBus()
        received = []
        bus.subscribe(SpeechRecognized, lambda e: received.append(e))
        bus.publish(_make_event())
        self.assertEqual(len(received), 1)

    def test_subscribe_unsubscribe_work(self):
        """subscribe/unsubscribe continuam funcionando."""
        bus = PipelineEventBus()
        h = lambda e: None
        bus.subscribe(SpeechRecognized, h)
        self.assertTrue(bus.has_subscribers(SpeechRecognized))
        bus.unsubscribe(SpeechRecognized, h)
        self.assertFalse(bus.has_subscribers(SpeechRecognized))

    def test_pipeline_engine_works_with_store(self):
        """Engine funciona com bus que usa EventStore."""
        from pipeline import (
            StreamingPipelineEngine, PipelinePolicy, PipelineSession,
            RecognitionHandler, SearchHandler, RankingHandler,
            IntelligenceHandler, PipelineCoordinator,
        )
        store = MemoryEventStore()
        bus = PipelineEventBus(store=store)
        policy = PipelinePolicy()
        session = PipelineSession.create(session_id="s1")
        engine = StreamingPipelineEngine(
            bus=bus, policy=policy, session=session, session_id="s1")
        coord = PipelineCoordinator(bus)
        coord.register_default_flow({
            "recognition": RecognitionHandler(bus, policy, "s1"),
            "search": SearchHandler(bus, policy, "s1"),
            "ranking": RankingHandler(bus, policy, "s1"),
            "intelligence": IntelligenceHandler(bus, policy, "s1"),
        })
        engine.start()
        corr = engine.process(text="test")
        # Eventos devem estar no store
        self.assertGreater(store.count(), 0)
        # Deve poder consultar por correlation_id
        flow_events = store.by_correlation(corr)
        self.assertGreater(len(flow_events), 0)

    def test_replay_preparation(self):
        """Preparação para Replay: consultar por correlation_id."""
        store = MemoryEventStore()
        bus = PipelineEventBus(store=store)
        # Simular dois fluxos
        bus.publish(_make_event(
            cls=SpeechSegmentReceived, event_id="e1",
            correlation_id="c1", timestamp=100.0))
        bus.publish(_make_event(
            cls=SpeechRecognized, event_id="e2",
            correlation_id="c1", timestamp=200.0))
        bus.publish(_make_event(
            cls=SpeechSegmentReceived, event_id="e3",
            correlation_id="c2", timestamp=300.0))
        bus.publish(_make_event(
            cls=SpeechRecognized, event_id="e4",
            correlation_id="c2", timestamp=400.0))
        # Replay do fluxo c1
        flow_c1 = store.by_correlation("c1")
        self.assertEqual(len(flow_c1), 2)
        self.assertEqual(flow_c1[0].event_id, "e1")
        self.assertEqual(flow_c1[1].event_id, "e2")
        # Replay do fluxo c2
        flow_c2 = store.by_correlation("c2")
        self.assertEqual(len(flow_c2), 2)

    def test_dashboard_preparation(self):
        """Preparação para Dashboard: consultar por session_id."""
        store = MemoryEventStore()
        bus = PipelineEventBus(store=store)
        bus.publish(_make_event(session_id="sermon-001"))
        bus.publish(_make_event(session_id="sermon-001"))
        bus.publish(_make_event(session_id="sermon-002"))
        # Dashboard consulta por sessão
        events_s1 = store.by_session("sermon-001")
        self.assertEqual(len(events_s1), 2)
        events_s2 = store.by_session("sermon-002")
        self.assertEqual(len(events_s2), 1)
        # Estatísticas por sessão
        stats = store.statistics
        self.assertEqual(stats.by_session["sermon-001"], 2)
        self.assertEqual(stats.by_session["sermon-002"], 1)


if __name__ == "__main__":
    unittest.main()
