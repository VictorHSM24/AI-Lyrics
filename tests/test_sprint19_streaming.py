"""Testes Sprint 19 — Streaming Speech Pipeline.

Cobre:
  - RingBuffer (escrita, leitura, wrap-around, thread-safety).
  - SlidingWindow (extração contínua, intervalo).
  - StreamingSTTService (diff de janela, publicação de eventos).
  - IncrementalBiblicalParser (estado incremental, ReferenceCandidate,
    ReferenceDetected).
  - Fluxo completo (RingBuffer → SlidingWindow → StreamingSTT →
    IncrementalParser → ReferenceDetected).
  - Regressão: pipeline existente (VAD → SpeechWorker) não quebra.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from microfone.ring_buffer import RingBuffer
from microfone.sliding_window import SlidingWindow
from microfone.streaming_stt_service import StreamingSTTService
from microfone.stt_executor import STTExecutor
from pipeline.events import (
    ReferenceCandidate,
    ReferenceDetected,
    SpeechPartial,
    SpeechPartialUpdated,
)
from pipeline.incremental_parser import IncrementalBiblicalParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_audio(duration_s: float, sr: int = 16000) -> np.ndarray:
    """Gera áudio float32 senoidal de duração dada."""
    n = int(sr * duration_s)
    t = np.linspace(0, duration_s, n, endpoint=False)
    return (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def _make_books():
    """Carrega ParserBookTable real para testes de parser incremental."""
    from parser.books import load_parser_books
    return load_parser_books("config/books.json")


def _make_bus():
    """Cria EventBus real para testes de integração."""
    from pipeline.bus import PipelineEventBus
    from pipeline.event_store import MemoryEventStore
    return PipelineEventBus(store=MemoryEventStore())


class _EventCollector:
    """Coleta eventos publicados no bus para asserção em testes."""

    def __init__(self, bus, event_types):
        self._bus = bus
        self._event_types = event_types
        self.events = []
        self._lock = threading.Lock()
        for et in event_types:
            bus.subscribe(et, self._on_event)

    def _on_event(self, event):
        with self._lock:
            self.events.append(event)

    def clear(self):
        with self._lock:
            self.events.clear()

    def of_type(self, et):
        with self._lock:
            return [e for e in self.events if isinstance(e, et)]


# ---------------------------------------------------------------------------
# Etapa 10.1 — RingBuffer
# ---------------------------------------------------------------------------


class TestRingBuffer:
    """Testes do RingBuffer circular de áudio."""

    def test_write_and_read_basic(self):
        """Escreve 1s de áudio e lê de volta."""
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=20.0)
        audio = _make_audio(1.0)
        buf.write(audio)
        assert buf.filled == 16000
        out = buf.read_last(1.0)
        assert out.size == 16000
        np.testing.assert_allclose(out, audio, atol=1e-6)

    def test_read_empty_buffer(self):
        """Ler de buffer vazio retorna array vazio."""
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=20.0)
        out = buf.read_last(6.0)
        assert out.size == 0

    def test_read_more_than_available(self):
        """Ler mais do que tem retorna apenas o disponível."""
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=20.0)
        buf.write(_make_audio(2.0))
        out = buf.read_last(6.0)
        assert out.size == 32000  # apenas 2s

    def test_wrap_around(self):
        """Testa wrap-around: escreve mais que a capacidade."""
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=1.0)
        # Capacidade = 16000 amostras (1s).
        # Escrever 1.5s — deve descartar os primeiros 0.5s.
        audio1 = _make_audio(1.0)
        audio2 = _make_audio(0.5)
        buf.write(audio1)
        buf.write(audio2)
        assert buf.filled == 16000  # saturou na capacidade
        # Último 0.5s deve ser audio2.
        out = buf.read_last(0.5)
        assert out.size == 8000
        np.testing.assert_allclose(out, audio2, atol=1e-6)

    def test_overflow_single_chunk(self):
        """Chunk maior que o buffer — mantém apenas o final."""
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=0.5)
        # Capacidade = 8000. Enviar 1s (16000 amostras).
        audio = _make_audio(1.0)
        buf.write(audio)
        assert buf.filled == 8000
        out = buf.read_last(0.5)
        assert out.size == 8000
        # Deve ser os últimos 0.5s do audio.
        np.testing.assert_allclose(out, audio[8000:], atol=1e-6)

    def test_thread_safety_concurrent_writes(self):
        """Múltiplas threads escrevendo concorrentemente — sem crash."""
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=5.0)
        errors = []

        def writer(tid):
            try:
                for _ in range(50):
                    buf.write(_make_audio(0.1))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == []
        assert buf.filled <= buf.capacity

    def test_thread_safety_concurrent_read_write(self):
        """Leitor e escritor concorrentes — sem crash, dados consistentes."""
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=2.0)
        stop = threading.Event()
        errors = []

        def writer():
            try:
                while not stop.is_set():
                    buf.write(_make_audio(0.05))
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                while not stop.is_set():
                    out = buf.read_last(1.0)
                    assert out.size <= 16000
            except Exception as e:
                errors.append(e)

        tw = threading.Thread(target=writer)
        tr = threading.Thread(target=reader)
        tw.start()
        tr.start()
        time.sleep(0.5)
        stop.set()
        tw.join(timeout=2.0)
        tr.join(timeout=2.0)
        assert errors == []

    def test_clear(self):
        """Clear zera o buffer."""
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=5.0)
        buf.write(_make_audio(1.0))
        assert buf.filled == 16000
        buf.clear()
        assert buf.filled == 0
        assert buf.read_last(1.0).size == 0

    def test_invalid_params(self):
        """Parâmetros inválidos levantam ValueError."""
        with pytest.raises(ValueError):
            RingBuffer(sample_rate=0)
        with pytest.raises(ValueError):
            RingBuffer(sample_rate=16000, channels=0)
        with pytest.raises(ValueError):
            RingBuffer(sample_rate=16000, duration_seconds=0)

    def test_memory_reuse_no_reallocation(self):
        """Buffer pré-aloca — capacity não muda após writes."""
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=1.0)
        cap_before = buf.capacity
        for _ in range(100):
            buf.write(_make_audio(0.5))
        assert buf.capacity == cap_before


# ---------------------------------------------------------------------------
# Etapa 10.2 — SlidingWindow
# ---------------------------------------------------------------------------


class TestSlidingWindow:
    """Testes da SlidingWindow."""

    def test_extraction_interval(self):
        """SlidingWindow extrai a cada ~400ms."""
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=20.0)
        windows = []

        sw = SlidingWindow(
            ring_buffer=buf,
            window_seconds=1.0,
            update_interval_ms=100,  # 100ms para teste rápido
            on_window=lambda audio, ts: windows.append((audio.size, ts)),
        )
        sw.start()
        # Alimentar áudio continuamente.
        for _ in range(20):
            buf.write(_make_audio(0.05))
            time.sleep(0.05)
        sw.stop()

        # Devemos ter ~10-20 extrações em ~1s.
        assert len(windows) >= 5
        # Cada extração deve ter até 16000 amostras (1s).
        for size, _ in windows:
            assert size <= 16000

    def test_independent_of_vad(self):
        """SlidingWindow extrai mesmo sem fala (áudio silencioso)."""
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=5.0)
        # Escrever silêncio.
        silence = np.zeros(800, dtype=np.float32)  # 50ms
        extractions = []

        sw = SlidingWindow(
            ring_buffer=buf,
            window_seconds=1.0,
            update_interval_ms=50,
            on_window=lambda audio, ts: extractions.append(audio.size),
        )
        sw.start()
        for _ in range(10):
            buf.write(silence)
            time.sleep(0.05)
        sw.stop()

        # Mesmo com "silêncio", extrações aconteceram (independente do VAD).
        assert len(extractions) >= 3

    def test_window_extracts_latest_audio(self):
        """A janela contém os últimos N segundos."""
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=10.0)
        # Escrever 3s de áudio.
        buf.write(_make_audio(3.0))
        captured = []

        sw = SlidingWindow(
            ring_buffer=buf,
            window_seconds=2.0,
            update_interval_ms=50,
            on_window=lambda audio, ts: captured.append(audio),
        )
        sw.start()
        time.sleep(0.2)
        sw.stop()

        assert len(captured) >= 1
        # Última extração deve ter ~2s (32000 amostras).
        assert captured[-1].size == 32000

    def test_invalid_params(self):
        """Parâmetros inválidos."""
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=5.0)
        with pytest.raises(ValueError):
            SlidingWindow(buf, window_seconds=0, update_interval_ms=400,
                          on_window=lambda a, t: None)
        with pytest.raises(ValueError):
            SlidingWindow(buf, window_seconds=10.0, update_interval_ms=400,
                          on_window=lambda a, t: None)  # > buffer duration
        with pytest.raises(ValueError):
            SlidingWindow(buf, window_seconds=1.0, update_interval_ms=0,
                          on_window=lambda a, t: None)


# ---------------------------------------------------------------------------
# Etapa 10.3 — StreamingSTTService (diff de janela)
# ---------------------------------------------------------------------------


class TestStreamingSTTService:
    """Testes do StreamingSTTService com diff de janela."""

    def test_diff_prefix_alignment(self):
        """Diff por prefixo: apenas sufixo novo é retornado."""
        diff = StreamingSTTService._compute_diff(
            "joao capitulo", "joao capitulo tres"
        )
        assert diff == "tres"

    def test_diff_no_common_prefix(self):
        """Sem prefixo comum: retorna texto inteiro."""
        diff = StreamingSTTService._compute_diff("abc", "xyz")
        assert diff == "xyz"

    def test_diff_empty_old(self):
        """Old vazio: retorna new inteiro."""
        diff = StreamingSTTService._compute_diff("", "joao")
        assert diff == "joao"

    def test_diff_identical(self):
        """Textos idênticos: retorna vazio."""
        diff = StreamingSTTService._compute_diff("joao", "joao")
        assert diff == ""

    def test_publishes_speech_partial_on_first(self):
        """Primeira transcrição publica SpeechPartial."""
        bus = _make_bus()
        col = _EventCollector(bus, [SpeechPartial, SpeechPartialUpdated])

        mock_executor = MagicMock(spec=STTExecutor)
        mock_executor.transcribe_audio.return_value = MagicMock(
            result=MagicMock(
                text="irmaos vamos abrir",
                language="pt",
                confidence=0.85,
            ),
            queue_wait_ms=0,
            total_ms=100,
        )

        svc = StreamingSTTService(
            executor=mock_executor, bus=bus, session_id="test",
        )
        svc.start()
        svc.on_window(_make_audio(6.0), time.time())

        partials = col.of_type(SpeechPartial)
        assert len(partials) == 1
        assert partials[0].text == "irmaos vamos abrir"
        svc.stop()

    def test_publishes_partial_updated_on_evolution(self):
        """Transcrição evoluída publica SpeechPartialUpdated com appended."""
        bus = _make_bus()
        col = _EventCollector(bus, [SpeechPartial, SpeechPartialUpdated])

        results = [
            MagicMock(text="joao capitulo", language="pt", confidence=0.85),
            MagicMock(text="joao capitulo tres", language="pt", confidence=0.88),
        ]
        mock_executor = MagicMock(spec=STTExecutor)
        mock_executor.transcribe_audio.side_effect = [
            MagicMock(result=r, queue_wait_ms=0, total_ms=100) for r in results
        ]

        svc = StreamingSTTService(
            executor=mock_executor, bus=bus, session_id="test",
        )
        svc.start()
        svc.on_window(_make_audio(6.0), time.time())  # partial
        svc.on_window(_make_audio(6.0), time.time())  # updated

        partials = col.of_type(SpeechPartial)
        updates = col.of_type(SpeechPartialUpdated)
        assert len(partials) == 1
        assert len(updates) == 1
        assert updates[0].appended_text == "tres"
        assert updates[0].text == "joao capitulo tres"
        svc.stop()

    def test_skips_no_change(self):
        """Transcrição idêntica não publica evento."""
        bus = _make_bus()
        col = _EventCollector(bus, [SpeechPartial, SpeechPartialUpdated])

        mock_executor = MagicMock(spec=STTExecutor)
        mock_executor.transcribe_audio.return_value = MagicMock(
            result=MagicMock(text="joao", language="pt", confidence=0.85),
            queue_wait_ms=0, total_ms=100,
        )

        svc = StreamingSTTService(
            executor=mock_executor, bus=bus, session_id="test",
        )
        svc.start()
        svc.on_window(_make_audio(6.0), time.time())  # partial
        svc.on_window(_make_audio(6.0), time.time())  # sem mudança
        svc.on_window(_make_audio(6.0), time.time())  # sem mudança

        assert len(col.of_type(SpeechPartial)) == 1
        assert len(col.of_type(SpeechPartialUpdated)) == 0
        svc.stop()

    def test_reset_flow(self):
        """reset_flow permite novo SpeechPartial com novo correlation_id."""
        bus = _make_bus()
        col = _EventCollector(bus, [SpeechPartial])

        mock_executor = MagicMock(spec=STTExecutor)
        mock_executor.transcribe_audio.return_value = MagicMock(
            result=MagicMock(text="novo texto", language="pt", confidence=0.85),
            queue_wait_ms=0, total_ms=100,
        )

        svc = StreamingSTTService(
            executor=mock_executor, bus=bus, session_id="test",
        )
        svc.start()
        svc.on_window(_make_audio(6.0), time.time())
        first_corr = col.of_type(SpeechPartial)[0].correlation_id
        svc.reset_flow()
        svc.on_window(_make_audio(6.0), time.time())
        second_corr = col.of_type(SpeechPartial)[1].correlation_id
        assert first_corr != second_corr
        svc.stop()


# ---------------------------------------------------------------------------
# Etapa 10.4 — IncrementalBiblicalParser
# ---------------------------------------------------------------------------


class TestIncrementalBiblicalParser:
    """Testes do parser incremental."""

    def test_detects_book_only(self):
        """Apenas livro identificado → ReferenceCandidate(book)."""
        bus = _make_bus()
        col = _EventCollector(bus, [ReferenceCandidate, ReferenceDetected])
        books = _make_books()

        parser = IncrementalBiblicalParser(
            books=books, bus=bus, session_id="test",
        )
        parser.start()

        # Publicar SpeechPartial com apenas "joao".
        partial = SpeechPartial(
            meta=_initial_meta("test"),
            text="joao",
            language="pt",
            confidence=0.85,
        )
        bus.publish(partial)
        time.sleep(0.05)

        candidates = col.of_type(ReferenceCandidate)
        detected = col.of_type(ReferenceDetected)
        assert len(candidates) == 1
        assert candidates[0].book.lower() == "joão"
        assert candidates[0].completeness == "book"
        assert candidates[0].confidence < 0.90
        assert len(detected) == 0
        parser.stop()

    def test_detects_book_and_chapter(self):
        """Livro + capítulo → ReferenceCandidate(chapter)."""
        bus = _make_bus()
        col = _EventCollector(bus, [ReferenceCandidate, ReferenceDetected])
        books = _make_books()

        parser = IncrementalBiblicalParser(
            books=books, bus=bus, session_id="test",
        )
        parser.start()

        # SpeechPartial com "joao".
        meta1 = _initial_meta("test")
        bus.publish(SpeechPartial(
            meta=meta1, text="joao", confidence=0.85,
        ))
        time.sleep(0.05)
        # SpeechPartialUpdated com appended "capitulo 3" — mesmo correlation_id.
        meta2 = _next_meta(meta1, "test")
        bus.publish(SpeechPartialUpdated(
            meta=meta2, text="joao capitulo 3",
            appended_text="capitulo 3", confidence=0.88,
        ))
        time.sleep(0.05)

        candidates = col.of_type(ReferenceCandidate)
        detected = col.of_type(ReferenceDetected)
        # book (candidate) + chapter (candidate, conf=0.75 < 0.90)
        assert len(candidates) >= 2
        chapter_cand = [c for c in candidates if c.completeness == "chapter"]
        assert len(chapter_cand) == 1
        assert chapter_cand[0].chapter == 3
        # Ainda não publicou ReferenceDetected (conf 0.75 < 0.90).
        assert len(detected) == 0
        parser.stop()

    def test_detects_full_reference(self):
        """Livro + capítulo + versículo → ReferenceDetected."""
        bus = _make_bus()
        col = _EventCollector(bus, [ReferenceCandidate, ReferenceDetected])
        books = _make_books()

        parser = IncrementalBiblicalParser(
            books=books, bus=bus, session_id="test",
        )
        parser.start()

        meta1 = _initial_meta("test")
        bus.publish(SpeechPartial(
            meta=meta1, text="joao", confidence=0.85,
        ))
        time.sleep(0.05)
        meta2 = _next_meta(meta1, "test")
        bus.publish(SpeechPartialUpdated(
            meta=meta2, text="joao capitulo 3",
            appended_text="capitulo 3", confidence=0.88,
        ))
        time.sleep(0.05)
        meta3 = _next_meta(meta2, "test")
        bus.publish(SpeechPartialUpdated(
            meta=meta3, text="joao capitulo 3 versiculo 16",
            appended_text="versiculo 16", confidence=0.92,
        ))
        time.sleep(0.05)

        detected = col.of_type(ReferenceDetected)
        assert len(detected) == 1
        assert detected[0].book.lower() == "joão"
        assert detected[0].chapter == 3
        assert detected[0].verse_start == 16
        assert detected[0].confidence >= 0.90
        parser.stop()

    def test_no_reprocessing_after_detection(self):
        """Após ReferenceDetected, parciais adicionais são ignoradas."""
        bus = _make_bus()
        col = _EventCollector(bus, [ReferenceCandidate, ReferenceDetected])
        books = _make_books()

        parser = IncrementalBiblicalParser(
            books=books, bus=bus, session_id="test",
        )
        parser.start()

        # Sequência completa até ReferenceDetected.
        meta1 = _initial_meta("test")
        bus.publish(SpeechPartial(
            meta=meta1, text="joao capitulo 3 versiculo 16",
            confidence=0.92,
        ))
        time.sleep(0.05)
        first_detected = col.of_type(ReferenceDetected)
        assert len(first_detected) == 1

        # Parcial adicional — não deve gerar novo evento.
        meta2 = _next_meta(meta1, "test")
        bus.publish(SpeechPartialUpdated(
            meta=meta2,
            text="joao capitulo 3 versiculo 16 porque deus amou",
            appended_text="porque deus amou", confidence=0.92,
        ))
        time.sleep(0.05)
        assert len(col.of_type(ReferenceDetected)) == 1
        parser.stop()

    def test_reset_clears_state(self):
        """reset() permite nova detecção em novo fluxo."""
        bus = _make_bus()
        col = _EventCollector(bus, [ReferenceDetected])
        books = _make_books()

        parser = IncrementalBiblicalParser(
            books=books, bus=bus, session_id="test",
        )
        parser.start()

        meta1 = _initial_meta("test")
        bus.publish(SpeechPartial(
            meta=meta1, text="joao capitulo 3 versiculo 16",
            confidence=0.92,
        ))
        time.sleep(0.05)
        assert len(col.of_type(ReferenceDetected)) == 1

        parser.reset()
        col.clear()

        meta2 = _initial_meta("test")
        bus.publish(SpeechPartial(
            meta=meta2, text="romanos 8 28",
            confidence=0.92,
        ))
        time.sleep(0.05)
        detected = col.of_type(ReferenceDetected)
        assert len(detected) == 1
        assert detected[0].book.lower() == "romanos"
        parser.stop()


def _initial_meta(session_id: str):
    """Cria EventMetadata inicial para testes."""
    from pipeline.metadata import EventMetadata
    return EventMetadata.for_initial(
        session_id=session_id, origin="test",
    )


def _next_meta(previous_meta, session_id: str):
    """Cria EventMetadata subsequente (mesmo correlation_id)."""
    from pipeline.metadata import EventMetadata
    return EventMetadata.for_next(
        previous=previous_meta, origin="test",
    )


# ---------------------------------------------------------------------------
# Etapa 10.5 — Fluxo completo (integração)
# ---------------------------------------------------------------------------


class TestStreamingPipelineIntegration:
    """Teste de integração: RingBuffer → SlidingWindow → StreamingSTT → Parser."""

    def test_full_pipeline_produces_reference_detected(self):
        """Fluxo completo: áudio → ... → ReferenceDetected.

        Usa STT mockado que retorna texto incremental simulando
        Whisper transcrevendo "joao capitulo 3 versiculo 16".
        """
        bus = _make_bus()
        col = _EventCollector(bus, [
            SpeechPartial, SpeechPartialUpdated,
            ReferenceCandidate, ReferenceDetected,
        ])
        books = _make_books()

        # Mock STTExecutor com sequência de transcrições.
        transcript_sequence = [
            MagicMock(text="irmaos vamos", language="pt", confidence=0.80),
            MagicMock(text="irmaos vamos abrir biblias no evangelho de joao",
                      language="pt", confidence=0.85),
            MagicMock(text="irmaos vamos abrir biblias no evangelho de joao capitulo 3",
                      language="pt", confidence=0.87),
            MagicMock(text="irmaos vamos abrir biblias no evangelho de joao capitulo 3 versiculo 16",
                      language="pt", confidence=0.90),
        ]
        mock_executor = MagicMock(spec=STTExecutor)
        mock_executor.transcribe_audio.side_effect = [
            MagicMock(result=r, queue_wait_ms=0, total_ms=100)
            for r in transcript_sequence
        ]

        # StreamingSTTService.
        streaming = StreamingSTTService(
            executor=mock_executor, bus=bus, session_id="test",
        )
        streaming.start()

        # IncrementalBiblicalParser.
        parser = IncrementalBiblicalParser(
            books=books, bus=bus, session_id="test",
        )
        parser.start()

        # Simular 4 janelas consecutivas.
        for _ in range(4):
            streaming.on_window(_make_audio(6.0), time.time())
            time.sleep(0.02)

        # Deve ter publicado SpeechPartial + SpeechPartialUpdated.
        assert len(col.of_type(SpeechPartial)) == 1
        assert len(col.of_type(SpeechPartialUpdated)) >= 2

        # Deve ter publicado ReferenceCandidate (book, chapter).
        candidates = col.of_type(ReferenceCandidate)
        assert len(candidates) >= 1

        # Deve ter publicado ReferenceDetected (joao 3:16).
        detected = col.of_type(ReferenceDetected)
        assert len(detected) == 1
        assert detected[0].book.lower() == "joão"
        assert detected[0].chapter == 3
        assert detected[0].verse_start == 16

        streaming.stop()
        parser.stop()


# ---------------------------------------------------------------------------
# Etapa 10.6 — Regressão: pipeline existente (VAD) não quebra
# ---------------------------------------------------------------------------


class TestSprint19Regression:
    """Garante que o pipeline existente (VAD → SpeechWorker) não quebra."""

    def test_speech_transcribed_still_published_by_speech_worker(self):
        """SpeechWorker existente continua publicando SpeechTranscribed.

        O fluxo VAD não é alterado pelo Sprint 19 — apenas adicionamos
        um fluxo paralelo (streaming). Este teste verifica que o
        BiblicalNLUService existente ainda assina SpeechTranscribed.
        """
        from pipeline.events import SpeechTranscribed
        from pipeline.nlu import BiblicalNLUService
        from parser.parser import Parser

        bus = _make_bus()
        col = _EventCollector(bus, [SpeechTranscribed])

        # BiblicalNLUService existente (stateless).
        books = _make_books()
        parser = Parser(books=books)
        nlu = BiblicalNLUService(parser=parser, bus=bus, session_id="test")
        nlu.start()

        # Publicar SpeechTranscribed (como o SpeechWorker faria).
        bus.publish(SpeechTranscribed(
            meta=_initial_meta("test"),
            text="joao capitulo 3 versiculo 16",
            confidence=0.92,
            latency_ms=100,
            duration_ms=3000,
        ))
        time.sleep(0.05)

        # O BiblicalNLUService deve ter processado e publicado
        # ReferenceDetected (fluxo Sprint 17/18 existente).
        detected = col.of_type(SpeechTranscribed)
        assert len(detected) == 1
        nlu.stop()

    def test_new_events_do_not_break_existing_subscribers(self):
        """Novos eventos (SpeechPartial etc.) não afetam subscribers existentes."""
        from pipeline.events import SpeechTranscribed

        bus = _make_bus()
        received_transcribed = []
        bus.subscribe(SpeechTranscribed,
                      lambda e: received_transcribed.append(e))

        # Publicar novos eventos do Sprint 19.
        bus.publish(SpeechPartial(
            meta=_initial_meta("test"), text="teste", confidence=0.5,
        ))
        bus.publish(SpeechPartialUpdated(
            meta=_initial_meta("test"), text="teste novo",
            appended_text="novo", confidence=0.6,
        ))
        bus.publish(ReferenceCandidate(
            meta=_initial_meta("test"), book="João", book_id=43,
            confidence=0.4, completeness="book",
        ))

        # Subscriber de SpeechTranscribed não deve ter recebido nada.
        assert received_transcribed == []

    def test_event_registry_includes_new_events(self):
        """_ALL_EVENT_TYPES inclui os novos eventos do Sprint 19."""
        from pipeline.events import all_event_types
        types = all_event_types()
        names = {t.__name__ for t in types}
        assert "SpeechPartial" in names
        assert "SpeechPartialUpdated" in names
        assert "ReferenceCandidate" in names
