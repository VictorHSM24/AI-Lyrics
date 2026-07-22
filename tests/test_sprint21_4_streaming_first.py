"""Testes da Sprint 21.4 — Unificação do Pipeline de Transcrição (Streaming First).

Cobre os cenários exigidos pela sprint:
  - ReferenceAntecipada é publicado pelo IncrementalBiblicalParser quando
    confidence >= anticipation_threshold (0.60) e < detection_threshold (0.90).
  - ReferenceAntecipada NÃO é publicado para book-only (confidence 0.40).
  - ReferenceAntecipada É publicado para book+chapter (confidence 0.75).
  - ReferenceDetected continua sendo publicado para book+chapter+verse (0.98).
  - VersePresentationService assina ReferenceAntecipada e apresenta antecipadamente.
  - Quando ReferenceDetected chega com a MESMA referência da antecipada:
    apenas confirma (não reapresenta no Holyrics).
  - Quando ReferenceDetected chega com referência DIFERENTE da antecipada:
    corrige (apresenta a nova referência).
  - SpeechWorker (Fluxo A) continua funcionando: ReferenceDetected sem
    antecipação prévia apresenta normalmente.
  - Eventos antigos (ReferenceDetected, ReferenceCandidate) continuam sendo
    publicados — compatibilidade preservada.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from integracao_holyrics.models import ShowVerseResult
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    ReferenceAntecipada,
    ReferenceCandidate,
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


def _make_meta(
    correlation_id: str = "corr-1",
    event_id: str = "evt-1",
    origin: str = "IncrementalBiblicalParser",
) -> EventMetadata:
    return EventMetadata.for_initial(
        session_id="test-session",
        origin=origin,
        event_id=event_id,
        correlation_id=correlation_id,
        timestamp=1000.0,
    )


def _make_reference_anticipada(
    book: str = "Salmos",
    book_id: int = 19,
    chapter: int = 23,
    verse: int = 0,
    confidence: float = 0.75,
    completeness: str = "chapter",
    normalized: str = "salmos 23",
    correlation_id: str = "corr-1",
    event_id: str = "evt-ant-1",
) -> ReferenceAntecipada:
    """Cria um ReferenceAntecipada para testes."""
    meta = _make_meta(correlation_id=correlation_id, event_id=event_id)
    return ReferenceAntecipada(
        meta=meta,
        book=book,
        book_id=book_id,
        chapter=chapter,
        verse_start=verse,
        verse_end=verse,
        confidence=confidence,
        completeness=completeness,
        normalized_text=normalized,
    )


def _make_reference_detected(
    book: str = "Salmos",
    book_id: int = 19,
    chapter: int = 23,
    verse: int = 1,
    confidence: float = 0.98,
    normalized: str = "salmos 23:1",
    correlation_id: str = "corr-1",
    event_id: str = "evt-det-1",
) -> ReferenceDetected:
    """Cria um ReferenceDetected para testes."""
    meta = _make_meta(
        correlation_id=correlation_id,
        event_id=event_id,
        origin="BiblicalNLUService",
    )
    return ReferenceDetected(
        meta=meta,
        intent="OPEN_REFERENCE",
        book=book,
        book_id=book_id,
        chapter=chapter,
        verse_start=verse,
        verse_end=verse,
        confidence=confidence,
        raw_text="salmos vinte e três versículo um",
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
    """Searcher fake para testes."""

    def __init__(self, result: Any = None) -> None:
        self._result = result or FakeSearchResult(
            reference="Salmos 23:1",
            book="Salmos",
            book_id=19,
            chapter=23,
            verse=1,
            text="O Senhor é meu pastor...",
            version="ACF",
        )
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
        return self._result


class FakeHolyricsClient:
    """HolyricsClient fake para testes."""

    def __init__(self) -> None:
        self._result = ShowVerseResult(
            status="ok",
            verse_id="19023001",
            book_id=19,
            chapter=23,
            verse=1,
            version="ACF",
        )
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
        return self._result


def _collect_events(bus: PipelineEventBus) -> list:
    """Coleta eventos publicados no bus (inscreve nos tipos relevantes)."""
    events: list = []
    for evt_type in (
        ReferenceAntecipada, ReferenceCandidate, ReferenceDetected,
        VerseResolving, VerseResolved, VersePresented,
        VersePresentationFailed,
    ):
        bus.subscribe(evt_type, events.append)
    return events


# ============================================================
# Testes — ReferenceAntecipada event.
# ============================================================


class TestReferenceAntecipadaEvent(unittest.TestCase):
    """Valida o novo evento ReferenceAntecipada."""

    def test_event_type_is_class_name(self):
        """event_type é derivado do nome da classe."""
        ev = _make_reference_anticipada()
        self.assertEqual(ev.event_type, "ReferenceAntecipada")

    def test_event_is_operational(self):
        """ReferenceAntecipada é um OperationalEvent."""
        from pipeline.events import is_operational_event
        ev = _make_reference_anticipada()
        self.assertTrue(is_operational_event(ev))

    def test_event_has_required_fields(self):
        """ReferenceAntecipada tem todos os campos necessários."""
        ev = _make_reference_anticipada(
            book="João", book_id=43, chapter=3, verse=16,
            confidence=0.75, completeness="chapter",
            normalized="joao 3",
        )
        self.assertEqual(ev.book, "João")
        self.assertEqual(ev.book_id, 43)
        self.assertEqual(ev.chapter, 3)
        self.assertEqual(ev.verse_start, 16)
        self.assertEqual(ev.confidence, 0.75)
        self.assertEqual(ev.completeness, "chapter")
        self.assertEqual(ev.normalized_text, "joao 3")

    def test_event_in_registry(self):
        """ReferenceAntecipada está no registro de eventos."""
        from pipeline.events import all_event_type_names
        self.assertIn("ReferenceAntecipada", all_event_type_names())


# ============================================================
# Testes — IncrementalBiblicalParser publica ReferenceAntecipada.
# ============================================================


class TestIncrementalParserAnticipation(unittest.TestCase):
    """Valida que o IncrementalBiblicalParser publica ReferenceAntecipada."""

    def setUp(self):
        from parser.books import load_parser_books
        from pipeline.incremental_parser import IncrementalBiblicalParser

        self.store = MagicMock()
        self.bus = PipelineEventBus(store=self.store)
        try:
            self.books = load_parser_books("config/books.json")
        except Exception:
            self.skipTest("config/books.json não disponível")

        self.parser = IncrementalBiblicalParser(
            books=self.books,
            bus=self.bus,
            session_id="test-session",
        )
        self.parser.start()

    def tearDown(self):
        self.parser.stop()

    def _publish_partial(self, text: str, correlation_id: str = "corr-1"):
        """Publica um SpeechPartial com o texto dado."""
        from pipeline.events import SpeechPartial
        meta = _make_meta(correlation_id=correlation_id, event_id="evt-p1")
        self.bus.publish(SpeechPartial(
            meta=meta, text=text, language="pt",
            confidence=0.9, latency_ms=100, audio_duration_ms=6000,
            is_stable=False,
        ))

    def test_book_only_does_not_publish_anticipation(self):
        """Book-only (confidence 0.40) NÃO publica ReferenceAntecipada."""
        events = _collect_events(self.bus)
        # "Salmos" → book only, confidence 0.40 < 0.60.
        self._publish_partial("Salmos")
        anticipations = [e for e in events if isinstance(e, ReferenceAntecipada)]
        self.assertEqual(len(anticipations), 0,
                         "Book-only não deve publicar ReferenceAntecipada")

    def test_book_chapter_publishes_anticipation(self):
        """Book+chapter (confidence 0.75) publica ReferenceAntecipada."""
        events = _collect_events(self.bus)
        # "Salmos 23" → book+chapter, confidence 0.75 >= 0.60.
        self._publish_partial("Salmos 23")
        anticipations = [e for e in events if isinstance(e, ReferenceAntecipada)]
        self.assertEqual(len(anticipations), 1,
                         "Book+chapter deve publicar ReferenceAntecipada")
        self.assertEqual(anticipations[0].completeness, "chapter")
        self.assertGreaterEqual(anticipations[0].confidence, 0.60)

    def test_reference_candidate_still_published(self):
        """ReferenceCandidate continua sendo publicado (compatibilidade)."""
        events = _collect_events(self.bus)
        self._publish_partial("Salmos 23")
        candidates = [e for e in events if isinstance(e, ReferenceCandidate)]
        self.assertGreaterEqual(len(candidates), 1,
                                "ReferenceCandidate deve continuar sendo publicado")

    def test_anticipation_published_only_once_per_flow(self):
        """Apenas uma ReferenceAntecipada por fluxo (não republica)."""
        events = _collect_events(self.bus)
        # Primeira parcial: "Salmos 23" → publica antecipada.
        self._publish_partial("Salmos 23", correlation_id="corr-1")
        # Segunda parcial com mesmo correlation_id: não deve republicar.
        from pipeline.events import SpeechPartialUpdated
        meta2 = EventMetadata.for_next(
            previous=EventMetadata(
                event_id="evt-p1", correlation_id="corr-1",
                causation_id=None, session_id="test-session",
                timestamp=1000.0, origin="StreamingSTTService",
            ),
            origin="StreamingSTTService",
        )
        self.bus.publish(SpeechPartialUpdated(
            meta=meta2, text="Salmos 23 1", appended_text="1",
            language="pt", confidence=0.9, latency_ms=100,
            audio_duration_ms=6000, is_stable=False,
        ))
        anticipations = [e for e in events if isinstance(e, ReferenceAntecipada)]
        self.assertEqual(len(anticipations), 1,
                         "Apenas uma antecipada por fluxo")


# ============================================================
# Testes — VersePresentationService com ReferenceAntecipada.
# ============================================================


class TestVersePresentationAnticipation(unittest.TestCase):
    """VersePresentationService apresenta antecipadamente."""

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

    def tearDown(self):
        self.service.stop()

    def test_anticipada_triggers_holyrics(self):
        """ReferenceAntecipada dispara show_verse no Holyrics."""
        events = _collect_events(self.bus)
        antic = _make_reference_anticipada(
            book="Salmos", book_id=19, chapter=23, verse=0,
            normalized="salmos 23", correlation_id="corr-1",
        )
        self.bus.publish(antic)
        # Holyrics foi chamado.
        self.assertEqual(len(self.holyrics.calls), 1)
        self.assertEqual(self.holyrics.calls[0]["book_id"], 19)
        self.assertEqual(self.holyrics.calls[0]["chapter"], 23)
        # VersePresented foi publicado.
        presented = [e for e in events if isinstance(e, VersePresented)]
        self.assertEqual(len(presented), 1)

    def test_anticipada_then_detected_same_ref_confirms(self):
        """Antecipada + Detected com mesma referência: só confirma (não reapresenta)."""
        events = _collect_events(self.bus)
        # Antecipada: Salmos 23:1.
        antic = _make_reference_anticipada(
            book="Salmos", book_id=19, chapter=23, verse=1,
            normalized="salmos 23:1", correlation_id="corr-1",
        )
        self.bus.publish(antic)
        # Detected com mesma referência (Salmos 23:1).
        detected = _make_reference_detected(
            book="Salmos", book_id=19, chapter=23, verse=1,
            normalized="salmos 23:1", correlation_id="corr-1",
        )
        self.bus.publish(detected)
        # Holyrics foi chamado APENAS uma vez (na antecipada).
        self.assertEqual(len(self.holyrics.calls), 1,
                         "Não deve reapresentar no Holyrics ao confirmar")
        # VersePresented foi publicado 2 vezes (antecipada + confirmação).
        presented = [e for e in events if isinstance(e, VersePresented)]
        self.assertEqual(len(presented), 2)
        # A segunda apresentação tem status="confirmed".
        self.assertEqual(presented[1].holyrics_status, "confirmed")
        self.assertEqual(presented[1].holyrics_latency_ms, 0)

    def test_anticipada_then_detected_different_ref_corrects(self):
        """Antecipada (Salmos 23) + Detected (Salmos 23:4): corrige."""
        # Configurar searcher para retornar Salmos 23:4 na segunda chamada.
        results = [
            FakeSearchResult(
                reference="Salmos 23", book="Salmos", book_id=19,
                chapter=23, verse=1, text="O Senhor é meu pastor",
                version="ACF",
            ),
            FakeSearchResult(
                reference="Salmos 23:4", book="Salmos", book_id=19,
                chapter=23, verse=4, text="Ainda que eu andasse",
                version="ACF",
            ),
        ]
        self.searcher.calls.clear()
        self.searcher._result = results[0]

        class MultiResultSearcher:
            def __init__(self):
                self.calls = []
                self._results = results
                self._idx = 0

            def search_by_reference(self, book_name, chapter, verse=None, *, version=None):
                self.calls.append({"book_name": book_name, "chapter": chapter,
                                   "verse": verse, "version": version})
                r = self._results[self._idx]
                self._idx += 1
                return r

        self.service._searcher = MultiResultSearcher()
        events = _collect_events(self.bus)

        # Antecipada: Salmos 23 (chapter only, verse=0).
        antic = _make_reference_anticipada(
            book="Salmos", book_id=19, chapter=23, verse=0,
            normalized="salmos 23", correlation_id="corr-1",
        )
        self.bus.publish(antic)
        # Detected: Salmos 23:4 (verse=4).
        detected = _make_reference_detected(
            book="Salmos", book_id=19, chapter=23, verse=4,
            normalized="salmos 23:4", correlation_id="corr-1",
        )
        self.bus.publish(detected)

        # Holyrics foi chamado 2 vezes (antecipada + correção).
        self.assertEqual(len(self.holyrics.calls), 2,
                         "Deve apresentar novamente ao corrigir")
        # Segunda chamada é a correção (verse=4).
        self.assertEqual(self.holyrics.calls[1]["verse"], 4)

    def test_detected_without_anticipada_presents_normally(self):
        """ReferenceDetected sem antecipação prévia: fluxo normal (Fluxo A)."""
        events = _collect_events(self.bus)
        detected = _make_reference_detected(
            book="João", book_id=43, chapter=3, verse=16,
            normalized="joao 3:16", correlation_id="corr-2",
        )
        self.bus.publish(detected)
        # Holyrics foi chamado uma vez.
        self.assertEqual(len(self.holyrics.calls), 1)
        # VersePresented foi publicado.
        presented = [e for e in events if isinstance(e, VersePresented)]
        self.assertEqual(len(presented), 1)
        # Status é "ok" (não "confirmed").
        self.assertEqual(presented[0].holyrics_status, "ok")

    def test_anticipada_metrics_tracked(self):
        """Métricas de antecipação são rastreadas."""
        antic = _make_reference_anticipada(correlation_id="corr-1")
        self.bus.publish(antic)
        self.assertEqual(self.service._total_anticipations, 1)
        self.assertEqual(self.service._total_presented, 1)

    def test_confirmation_metrics_tracked(self):
        """Métricas de confirmação são rastreadas."""
        antic = _make_reference_anticipada(
            book="Salmos", book_id=19, chapter=23, verse=1,
            correlation_id="corr-1",
        )
        self.bus.publish(antic)
        detected = _make_reference_detected(
            book="Salmos", book_id=19, chapter=23, verse=1,
            correlation_id="corr-1",
        )
        self.bus.publish(detected)
        self.assertEqual(self.service._total_anticipations, 1)
        self.assertEqual(self.service._total_confirmations, 1)


# ============================================================
# Testes — Compatibilidade (eventos antigos preservados).
# ============================================================


class TestStreamingFirstCompatibility(unittest.TestCase):
    """Garante que eventos antigos continuam funcionando."""

    def test_reference_detected_still_works(self):
        """ReferenceDetected sem antecipação apresenta normalmente."""
        store = MagicMock()
        bus = PipelineEventBus(store=store)
        searcher = FakeSearcher()
        holyrics = FakeHolyricsClient()
        service = VersePresentationService(
            searcher=searcher, holyrics=holyrics, bus=bus,
            session_id="test", version="ACF",
        )
        service.start()
        events = _collect_events(bus)
        detected = _make_reference_detected(correlation_id="corr-x")
        bus.publish(detected)
        presented = [e for e in events if isinstance(e, VersePresented)]
        self.assertEqual(len(presented), 1)
        service.stop()

    def test_reference_candidate_not_consumed_by_presentation(self):
        """ReferenceCandidate NÃO dispara apresentação (é telemetria)."""
        store = MagicMock()
        bus = PipelineEventBus(store=store)
        searcher = FakeSearcher()
        holyrics = FakeHolyricsClient()
        service = VersePresentationService(
            searcher=searcher, holyrics=holyrics, bus=bus,
            session_id="test", version="ACF",
        )
        service.start()
        # Publicar ReferenceCandidate.
        meta = _make_meta(correlation_id="corr-c")
        candidate = ReferenceCandidate(
            meta=meta, book="Salmos", book_id=19, chapter=23,
            verse_start=0, verse_end=0, confidence=0.40,
            completeness="book", normalized_text="salmos",
        )
        bus.publish(candidate)
        # Holyrics NÃO foi chamado.
        self.assertEqual(len(holyrics.calls), 0)
        service.stop()


if __name__ == "__main__":
    unittest.main()
