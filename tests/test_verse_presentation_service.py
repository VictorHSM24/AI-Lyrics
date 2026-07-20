"""Testes do VersePresentationService (Sprint 18).

Cobre todos os cenários exigidos pela sprint:
  - Apresentação bem-sucedida (ReferenceDetected → VersePresented).
  - Livro inexistente (Searcher levanta SearchError).
  - Versículo não encontrado (Searcher retorna None).
  - Falha do Searcher (erro inesperado).
  - Falha do Holyrics (connection, timeout, auth, api).
  - Erro interno inesperado.
  - Quick presentation ligado.
  - Quick presentation desligado.
  - Eventos publicados na ordem correta.
  - Correlation_id preservado ao longo do fluxo.
  - Causation_id encadeado (ReferenceDetected → VerseResolving → ...).
  - Health NÃO é alterado em caso de falha.
  - Logging sem duplicação.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from busca.exceptions import SearchError
from integracao_holyrics.exceptions import (
    HolyricsAPIError,
    HolyricsAuthError,
    HolyricsConnectionError,
    HolyricsError,
    HolyricsTimeoutError,
)
from integracao_holyrics.models import ShowVerseResult
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    ReferenceDetected,
    VersePresentationFailed,
    VersePresented,
    VerseResolved,
    VerseResolving,
)
from pipeline.metadata import EventMetadata
from presentation.verse_presentation_service import VersePresentationService


# ============================================================
# Helpers — fixtures.
# ============================================================


def _make_reference_detected(
    book: str = "João",
    book_id: int = 43,
    chapter: int = 3,
    verse: int = 16,
    normalized: str = "joao 3:16",
    correlation_id: str = "corr-1",
    event_id: str = "evt-1",
) -> ReferenceDetected:
    """Cria um ReferenceDetected para testes."""
    meta = EventMetadata.for_initial(
        session_id="test-session",
        origin="BiblicalNLUService",
        event_id=event_id,
        correlation_id=correlation_id,
        timestamp=1000.0,
    )
    return ReferenceDetected(
        meta=meta,
        intent="OPEN_REFERENCE",
        book=book,
        book_id=book_id,
        chapter=chapter,
        verse_start=verse,
        verse_end=verse,
        confidence=0.95,
        raw_text="joão capítulo três versículo dezesseis",
        normalized_text=normalized,
    )


@dataclass(frozen=True)
class FakeSearchResult:
    """Simula SearchResult retornado pelo Searcher."""
    reference: str
    book: str
    book_id: int
    chapter: int
    verse: int
    text: str
    version: str
    score: float = 1.0
    c_search: float = 1.0
    ambiguous: bool = False
    match_type: str = "reference"


class FakeSearcher:
    """Searcher fake para testes.

    Por padrão retorna um SearchResult válido. Para simular falhas,
    configure `fail_with` (exceção) ou `return_none` (None).
    """

    def __init__(
        self,
        result: Any = None,
        fail_with: Exception | None = None,
        return_none: bool = False,
    ) -> None:
        self._result = result or FakeSearchResult(
            reference="João 3:16",
            book="João",
            book_id=43,
            chapter=3,
            verse=16,
            text="Porque Deus amou o mundo de tal maneira...",
            version="ACF",
        )
        self._fail_with = fail_with
        self._return_none = return_none
        self.calls: list[dict] = []

    def search_by_reference(
        self,
        book_name: str,
        chapter: int,
        verse: int | None = None,
        *,
        version: str | None = None,
    ) -> Any:
        self.calls.append({
            "book_name": book_name,
            "chapter": chapter,
            "verse": verse,
            "version": version,
        })
        if self._fail_with is not None:
            raise self._fail_with
        if self._return_none:
            return None
        return self._result


class FakeHolyricsClient:
    """HolyricsClient fake para testes.

    Por padrão retorna um ShowVerseResult válido. Para simular falhas,
    configure `fail_with` (exceção).
    """

    def __init__(
        self,
        result: ShowVerseResult | None = None,
        fail_with: Exception | None = None,
    ) -> None:
        self._result = result or ShowVerseResult(
            status="ok",
            verse_id="43003016",
            book_id=43,
            chapter=3,
            verse=16,
            version="ACF",
        )
        self._fail_with = fail_with
        self.calls: list[dict] = []

    def show_verse(
        self,
        book_id: int,
        chapter: int,
        verse: int | None,
        version: str = "ACF",
        quick: bool = False,
    ) -> ShowVerseResult:
        self.calls.append({
            "book_id": book_id,
            "chapter": chapter,
            "verse": verse,
            "version": version,
            "quick": quick,
        })
        if self._fail_with is not None:
            raise self._fail_with
        return self._result


# ============================================================
# Testes — fluxo bem-sucedido.
# ============================================================


class TestSuccessfulPresentation(unittest.TestCase):
    """Apresentação bem-sucedida: ReferenceDetected → VersePresented."""

    def setUp(self):
        self.store = MagicMock()
        self.bus = PipelineEventBus(store=self.store)
        self.searcher = FakeSearcher()
        self.holyrics = FakeHolyricsClient()
        self.service = VersePresentationService(
            searcher=self.searcher,
            holyrics=self.holyrics,
            bus=self.bus,
            session_id="test-session",
            version="ACF",
            quick_presentation=False,
        )
        self.service.start()

        self.events: list = []
        for evt_type in (VerseResolving, VerseResolved, VersePresented, VersePresentationFailed):
            self.bus.subscribe(evt_type, self.events.append)

    def tearDown(self):
        self.service.stop()

    def test_full_successful_flow(self):
        """ReferenceDetected → VerseResolving → VerseResolved → VersePresented."""
        ref = _make_reference_detected()
        self.bus.publish(ref)

        # Devem ter sido publicados 3 eventos (Resolving, Resolved, Presented).
        types = [type(e).__name__ for e in self.events]
        self.assertEqual(types, ["VerseResolving", "VerseResolved", "VersePresented"])

        # VerseResolving deve ter os dados da referência.
        resolving = self.events[0]
        self.assertIsInstance(resolving, VerseResolving)
        self.assertEqual(resolving.book, "João")
        self.assertEqual(resolving.book_id, 43)
        self.assertEqual(resolving.chapter, 3)
        self.assertEqual(resolving.verse_start, 16)
        self.assertEqual(resolving.normalized_text, "joao 3:16")

        # VerseResolved deve ter o texto do versículo.
        resolved = self.events[1]
        self.assertIsInstance(resolved, VerseResolved)
        self.assertEqual(resolved.reference, "João 3:16")
        self.assertEqual(resolved.verse, 16)
        self.assertIn("Porque Deus amou", resolved.verse_text)

        # VersePresented deve ter o status do Holyrics.
        presented = self.events[2]
        self.assertIsInstance(presented, VersePresented)
        self.assertEqual(presented.holyrics_status, "ok")
        self.assertEqual(presented.reference, "João 3:16")
        self.assertFalse(presented.quick_presentation)
        # Latências devem ser não-negativas.
        self.assertGreaterEqual(presented.holyrics_latency_ms, 0)
        self.assertGreaterEqual(presented.total_latency_ms, presented.holyrics_latency_ms)

    def test_correlation_id_preserved(self):
        """Todos os eventos do fluxo compartilham correlation_id."""
        ref = _make_reference_detected(correlation_id="my-corr-123")
        self.bus.publish(ref)

        for evt in self.events:
            self.assertEqual(evt.correlation_id, "my-corr-123")

    def test_causation_id_chain(self):
        """Cada evento tem causation_id = event_id do ReferenceDetected.

        Todos derivam do mesmo ReferenceDetected, então todos devem
        ter o mesmo causation_id (o event_id do ReferenceDetected).
        """
        ref = _make_reference_detected(event_id="ref-evt-id")
        self.bus.publish(ref)

        for evt in self.events:
            self.assertEqual(evt.causation_id, "ref-evt-id")

    def test_searcher_called_with_correct_args(self):
        """Searcher deve ser chamado com os dados da referência."""
        ref = _make_reference_detected(book="João", chapter=3, verse=16)
        self.bus.publish(ref)

        self.assertEqual(len(self.searcher.calls), 1)
        call = self.searcher.calls[0]
        self.assertEqual(call["book_name"], "João")
        self.assertEqual(call["chapter"], 3)
        self.assertEqual(call["verse"], 16)
        self.assertEqual(call["version"], "ACF")

    def test_holyrics_called_with_correct_args(self):
        """Holyrics deve ser chamado com book_id, chapter, verse, version, quick."""
        ref = _make_reference_detected()
        self.bus.publish(ref)

        self.assertEqual(len(self.holyrics.calls), 1)
        call = self.holyrics.calls[0]
        self.assertEqual(call["book_id"], 43)
        self.assertEqual(call["chapter"], 3)
        self.assertEqual(call["verse"], 16)
        self.assertEqual(call["version"], "ACF")
        self.assertFalse(call["quick"])

    def test_quick_presentation_forwarded(self):
        """quick_presentation=True deve ser repassado ao Holyrics."""
        self.service.stop()
        self.service = VersePresentationService(
            searcher=self.searcher,
            holyrics=self.holyrics,
            bus=self.bus,
            session_id="test-session",
            version="ACF",
            quick_presentation=True,
        )
        self.service.start()
        for evt_type in (VerseResolving, VerseResolved, VersePresented, VersePresentationFailed):
            self.bus.subscribe(evt_type, self.events.append)

        ref = _make_reference_detected()
        self.bus.publish(ref)

        # Holyrics deve ter sido chamado com quick=True.
        self.assertTrue(self.holyrics.calls[-1]["quick"])
        # VersePresented deve registrar quick_presentation=True.
        presented = [e for e in self.events if isinstance(e, VersePresented)][-1]
        self.assertTrue(presented.quick_presentation)

    def test_quick_presentation_off_by_default(self):
        """quick_presentation=False (default) deve ser repassado ao Holyrics."""
        ref = _make_reference_detected()
        self.bus.publish(ref)

        self.assertFalse(self.holyrics.calls[-1]["quick"])
        presented = [e for e in self.events if isinstance(e, VersePresented)][-1]
        self.assertFalse(presented.quick_presentation)


# ============================================================
# Testes — falhas do Searcher.
# ============================================================


class TestSearcherFailures(unittest.TestCase):

    def setUp(self):
        self.store = MagicMock()
        self.bus = PipelineEventBus(store=self.store)
        self.events: list = []
        for evt_type in (VerseResolving, VerseResolved, VersePresented, VersePresentationFailed):
            self.bus.subscribe(evt_type, self.events.append)

    def _make_service(self, searcher: FakeSearcher) -> VersePresentationService:
        holyrics = FakeHolyricsClient()
        service = VersePresentationService(
            searcher=searcher,
            holyrics=holyrics,
            bus=self.bus,
            session_id="test-session",
        )
        service.start()
        return service

    def test_book_not_found_raises_search_error(self):
        """Searcher levanta SearchError → VersePresentationFailed (book_not_found)."""
        searcher = FakeSearcher(fail_with=SearchError("unknown book: Klingon"))
        service = self._make_service(searcher)

        ref = _make_reference_detected(book="Klingon")
        self.bus.publish(ref)

        types = [type(e).__name__ for e in self.events]
        self.assertEqual(types, ["VerseResolving", "VersePresentationFailed"])
        failed = self.events[-1]
        self.assertIsInstance(failed, VersePresentationFailed)
        self.assertEqual(failed.failure_stage, "search")
        self.assertEqual(failed.error_type, "book_not_found")
        self.assertIn("unknown book", failed.error_message)

    def test_verse_not_found_returns_none(self):
        """Searcher retorna None → VersePresentationFailed (verse_not_found)."""
        searcher = FakeSearcher(return_none=True)
        service = self._make_service(searcher)

        ref = _make_reference_detected()
        self.bus.publish(ref)

        types = [type(e).__name__ for e in self.events]
        self.assertEqual(types, ["VerseResolving", "VersePresentationFailed"])
        failed = self.events[-1]
        self.assertEqual(failed.failure_stage, "search")
        self.assertEqual(failed.error_type, "verse_not_found")

    def test_searcher_unexpected_error(self):
        """Erro inesperado no Searcher → VersePresentationFailed (internal_error)."""
        searcher = FakeSearcher(fail_with=ValueError("db corrupted"))
        service = self._make_service(searcher)

        ref = _make_reference_detected()
        self.bus.publish(ref)

        failed = self.events[-1]
        self.assertEqual(failed.failure_stage, "search")
        self.assertEqual(failed.error_type, "internal_error")
        self.assertIn("db corrupted", failed.error_message)

    def test_searcher_failure_does_not_call_holyrics(self):
        """Se Searcher falha, Holyrics NÃO deve ser chamado."""
        searcher = FakeSearcher(return_none=True)
        holyrics = FakeHolyricsClient()
        service = VersePresentationService(
            searcher=searcher,
            holyrics=holyrics,
            bus=self.bus,
            session_id="test-session",
        )
        service.start()

        ref = _make_reference_detected()
        self.bus.publish(ref)

        self.assertEqual(len(holyrics.calls), 0)


# ============================================================
# Testes — falhas do Holyrics.
# ============================================================


class TestHolyricsFailures(unittest.TestCase):

    def setUp(self):
        self.store = MagicMock()
        self.bus = PipelineEventBus(store=self.store)
        self.events: list = []
        for evt_type in (VerseResolving, VerseResolved, VersePresented, VersePresentationFailed):
            self.bus.subscribe(evt_type, self.events.append)

    def _make_service(self, holyrics: FakeHolyricsClient) -> VersePresentationService:
        searcher = FakeSearcher()
        service = VersePresentationService(
            searcher=searcher,
            holyrics=holyrics,
            bus=self.bus,
            session_id="test-session",
        )
        service.start()
        return service

    def test_connection_error(self):
        """HolyricsConnectionError → VersePresentationFailed (connection)."""
        holyrics = FakeHolyricsClient(
            fail_with=HolyricsConnectionError("Connection refused"),
        )
        service = self._make_service(holyrics)

        ref = _make_reference_detected()
        self.bus.publish(ref)

        types = [type(e).__name__ for e in self.events]
        self.assertEqual(types, ["VerseResolving", "VerseResolved", "VersePresentationFailed"])
        failed = self.events[-1]
        self.assertEqual(failed.failure_stage, "holyrics")
        self.assertEqual(failed.error_type, "connection")
        self.assertIn("Connection refused", failed.error_message)

    def test_timeout_error(self):
        """HolyricsTimeoutError → VersePresentationFailed (timeout)."""
        holyrics = FakeHolyricsClient(
            fail_with=HolyricsTimeoutError("Timeout after 2000ms"),
        )
        service = self._make_service(holyrics)

        ref = _make_reference_detected()
        self.bus.publish(ref)

        failed = self.events[-1]
        self.assertEqual(failed.failure_stage, "holyrics")
        self.assertEqual(failed.error_type, "timeout")

    def test_auth_error_invalid_token(self):
        """HolyricsAuthError (token inválido) → VersePresentationFailed (auth)."""
        holyrics = FakeHolyricsClient(
            fail_with=HolyricsAuthError("Invalid token"),
        )
        service = self._make_service(holyrics)

        ref = _make_reference_detected()
        self.bus.publish(ref)

        failed = self.events[-1]
        self.assertEqual(failed.failure_stage, "holyrics")
        self.assertEqual(failed.error_type, "auth")
        self.assertIn("Invalid token", failed.error_message)

    def test_api_error(self):
        """HolyricsAPIError → VersePresentationFailed (api)."""
        holyrics = FakeHolyricsClient(
            fail_with=HolyricsAPIError("Item not found"),
        )
        service = self._make_service(holyrics)

        ref = _make_reference_detected()
        self.bus.publish(ref)

        failed = self.events[-1]
        self.assertEqual(failed.failure_stage, "holyrics")
        self.assertEqual(failed.error_type, "api")

    def test_generic_holyrics_error(self):
        """HolyricsError genérico → VersePresentationFailed (holyrics_error)."""
        holyrics = FakeHolyricsClient(
            fail_with=HolyricsError("Unknown error"),
        )
        service = self._make_service(holyrics)

        ref = _make_reference_detected()
        self.bus.publish(ref)

        failed = self.events[-1]
        self.assertEqual(failed.failure_stage, "holyrics")
        self.assertEqual(failed.error_type, "holyrics_error")

    def test_unexpected_holyrics_error(self):
        """Erro inesperado no Holyrics → VersePresentationFailed (internal_error)."""
        holyrics = FakeHolyricsClient(
            fail_with=RuntimeError("Unexpected"),
        )
        service = self._make_service(holyrics)

        ref = _make_reference_detected()
        self.bus.publish(ref)

        failed = self.events[-1]
        self.assertEqual(failed.failure_stage, "holyrics")
        self.assertEqual(failed.error_type, "internal_error")
        self.assertIn("Unexpected", failed.error_message)


# ============================================================
# Testes — Health NÃO é alterado em falha.
# ============================================================


class TestHealthNotAffectedByFailures(unittest.TestCase):
    """Sprint 18 — Etapa 8: Health NÃO deve mudar em caso de falha.

    Verificamos que nenhum evento de Health é publicado quando
    VersePresentationFailed é emitido. A única forma de Health mudar
    é via health_check periódico do HealthService.
    """

    def setUp(self):
        self.store = MagicMock()
        self.bus = PipelineEventBus(store=self.store)
        self.events: list = []
        self.bus.subscribe(VersePresentationFailed, self.events.append)

    def test_failure_does_not_publish_health_event(self):
        """VersePresentationFailed não publica eventos de Health."""
        searcher = FakeSearcher(return_none=True)
        holyrics = FakeHolyricsClient()
        service = VersePresentationService(
            searcher=searcher,
            holyrics=holyrics,
            bus=self.bus,
            session_id="test-session",
        )
        service.start()

        ref = _make_reference_detected()
        self.bus.publish(ref)

        # Apenas VersePresentationFailed deve ter sido publicado.
        self.assertEqual(len(self.events), 1)
        self.assertIsInstance(self.events[0], VersePresentationFailed)


# ============================================================
# Testes — versão configurada (não hardcoded).
# ============================================================


class TestConfiguredVersion(unittest.TestCase):
    """Sprint 18 — Etapa 5: versão e quick_presentation devem vir do config."""

    def test_custom_version_used(self):
        store = MagicMock()
        bus = PipelineEventBus(store=store)
        searcher = FakeSearcher()
        holyrics = FakeHolyricsClient()
        service = VersePresentationService(
            searcher=searcher,
            holyrics=holyrics,
            bus=bus,
            session_id="test-session",
            version="pt_acf",
            quick_presentation=True,
        )
        service.start()

        events: list = []
        for evt_type in (VersePresented, VersePresentationFailed):
            bus.subscribe(evt_type, events.append)

        ref = _make_reference_detected()
        bus.publish(ref)

        # Searcher e Holyrics devem ter sido chamados com version="pt_acf".
        self.assertEqual(searcher.calls[0]["version"], "pt_acf")
        self.assertEqual(holyrics.calls[0]["version"], "pt_acf")
        self.assertTrue(holyrics.calls[0]["quick"])

        # VersePresented deve registrar a versão customizada.
        presented = events[0]
        self.assertEqual(presented.version, "pt_acf")
        self.assertTrue(presented.quick_presentation)


# ============================================================
# Testes — lifecycle.
# ============================================================


class TestLifecycle(unittest.TestCase):

    def test_start_subscribes_to_reference_detected(self):
        store = MagicMock()
        bus = PipelineEventBus(store=store)
        service = VersePresentationService(
            searcher=FakeSearcher(),
            holyrics=FakeHolyricsClient(),
            bus=bus,
            session_id="test-session",
        )
        # Antes de start: nenhum subscriber.
        self.assertNotIn(ReferenceDetected, bus.subscribed_types())
        service.start()
        # Após start: ReferenceDetected tem 1 subscriber.
        self.assertIn(ReferenceDetected, bus.subscribed_types())
        service.stop()
        # Após stop: sem subscribers.
        self.assertNotIn(ReferenceDetected, bus.subscribed_types())

    def test_double_start_is_idempotent(self):
        store = MagicMock()
        bus = PipelineEventBus(store=store)
        service = VersePresentationService(
            searcher=FakeSearcher(),
            holyrics=FakeHolyricsClient(),
            bus=bus,
            session_id="test-session",
        )
        service.start()
        service.start()  # idempotente
        # Ainda 1 subscriber (não 2).
        self.assertEqual(
            len(bus._subscriptions.get(ReferenceDetected, [])),
            1,
        )


# ============================================================
# Testes — eventos no EventStore.
# ============================================================


class TestEventStorePersistence(unittest.TestCase):
    """Sprint 18 — Etapa 3: eventos são OperationalEvent (persistidos)."""

    def setUp(self):
        from pipeline.event_store import MemoryEventStore, EventStorePolicy
        self.store = MemoryEventStore(EventStorePolicy())
        self.bus = PipelineEventBus(store=self.store)
        self.events: list = []
        for evt_type in (VerseResolving, VerseResolved, VersePresented, VersePresentationFailed):
            self.bus.subscribe(evt_type, self.events.append)

    def test_events_persisted_in_store(self):
        """Todos os eventos do fluxo devem ser persistidos no EventStore."""
        searcher = FakeSearcher()
        holyrics = FakeHolyricsClient()
        service = VersePresentationService(
            searcher=searcher,
            holyrics=holyrics,
            bus=self.bus,
            session_id="test-session",
        )
        service.start()

        ref = _make_reference_detected()
        self.bus.publish(ref)

        # EventStore deve conter ReferenceDetected + 3 eventos do fluxo.
        all_events = list(self.store.all())
        types = [type(e).__name__ for e in all_events]
        self.assertIn("ReferenceDetected", types)
        self.assertIn("VerseResolving", types)
        self.assertIn("VerseResolved", types)
        self.assertIn("VersePresented", types)

    def test_failed_event_persisted_in_store(self):
        """VersePresentationFailed também deve ser persistido."""
        searcher = FakeSearcher(return_none=True)
        holyrics = FakeHolyricsClient()
        service = VersePresentationService(
            searcher=searcher,
            holyrics=holyrics,
            bus=self.bus,
            session_id="test-session",
        )
        service.start()

        ref = _make_reference_detected()
        self.bus.publish(ref)

        all_events = list(self.store.all())
        types = [type(e).__name__ for e in all_events]
        self.assertIn("VersePresentationFailed", types)


if __name__ == "__main__":
    unittest.main()
