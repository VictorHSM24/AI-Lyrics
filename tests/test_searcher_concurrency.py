"""Testes de concorrência do Searcher (Sprint 18.0.1).

Sprint 18.0.1 — Tornar o Searcher Thread-Safe.

Valida que a refatoração da camada de acesso ao SQLite eliminou
definitivamente o erro "SQLite objects created in a thread can only
be used in that same thread".

Cenários:
  - 5 threads chamando search_by_reference simultaneamente.
  - 20 buscas simultâneas (search + search_by_reference).
  - Pipeline completo: SpeechWorker → ReferenceDetected → Searcher
    → VerseResolved → Holyrics → VersePresented executado em thread
    separada (simulando o cenário real).
  - Verificação de que múltiplas threads podem usar o mesmo Searcher
    sem mutex, sem check_same_thread=False, sem ProgrammingError.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pytest

from busca.exceptions import SearchError
from busca.searcher import Searcher
from config.books import BookTable
from config.loader import load_books
from config.models import SearchConfig


# Reutiliza fixtures do test_searcher.py
SAMPLE_VERSES = [
    {"book": "Gênesis", "book_id": 1, "chapter": 1, "verse": 1,
     "text": "No princípio criou Deus os céus e a terra.", "version": "ACF"},
    {"book": "Gênesis", "book_id": 1, "chapter": 1, "verse": 2,
     "text": "E a terra era sem forma e vazia; e havia trevas sobre a face do abismo.",
     "version": "ACF"},
    {"book": "Gênesis", "book_id": 1, "chapter": 1, "verse": 3,
     "text": "E disse Deus: Haja luz. E houve luz.", "version": "ACF"},
    {"book": "João", "book_id": 43, "chapter": 3, "verse": 16,
     "text": "Porque Deus amou o mundo de tal maneira que deu o seu Filho unigênito.",
     "version": "ACF"},
    {"book": "João", "book_id": 43, "chapter": 3, "verse": 17,
     "text": "Porque Deus enviou o seu Filho ao mundo, para que o mundo seja salvo por ele.",
     "version": "ACF"},
    {"book": "Romanos", "book_id": 45, "chapter": 8, "verse": 28,
     "text": "E sabemos que todas as coisas cooperam para o bem daqueles que amam a Deus.",
     "version": "ACF"},
    {"book": "Mateus", "book_id": 40, "chapter": 5, "verse": 13,
     "text": "Vós sois o sal da terra.", "version": "ACF"},
]


def _build_test_db(db_path: str, verses: list[dict]) -> None:
    """Cria um banco SQLite FTS5 de teste."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE verses USING fts5("
            "id UNINDEXED, book, chapter UNINDEXED, verse UNINDEXED, "
            "text, version, tokenize='unicode61 remove_diacritics 2')"
        )
        for v in verses:
            verse_id = f"{v['book_id']:02d}{v['chapter']:03d}{v['verse']:03d}"
            conn.execute(
                "INSERT INTO verses (id, book, chapter, verse, text, version) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (verse_id, v["book"], v["chapter"], v["verse"],
                 v["text"], v["version"]),
            )
        conn.commit()
    finally:
        conn.close()


def _search_config(db_path: str) -> SearchConfig:
    return SearchConfig(
        fts5_db=db_path,
        embeddings_path="data/bible.embeddings.npy",
        embedding_model="intfloat/multilingual-e5-small",
        embedding_device="cpu",
        rrf_k=60,
        top_k=20,
        search_gap=0.15,
    )


@pytest.fixture
def book_table() -> BookTable:
    books_path = Path(__file__).parent.parent / "config" / "books.json"
    return load_books(str(books_path))


@pytest.fixture
def test_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "test_concurrency.sqlite")
    _build_test_db(db_path, SAMPLE_VERSES)
    return db_path


@pytest.fixture
def searcher(test_db: str, book_table: BookTable) -> Searcher:
    config = _search_config(test_db)
    return Searcher(config, book_table, version="ACF")


# ============================================================
# Teste 1 — 5 threads chamando search_by_reference simultaneamente.
# ============================================================


class TestFiveThreadsSearchByReference:
    """5 threads chamando search_by_reference() simultaneamente.

    Resultado esperado: nenhum ProgrammingError, todas retornam
    o versículo correto.
    """

    def test_5_threads_no_programming_error(
        self, searcher: Searcher,
    ) -> None:
        refs = [
            ("João", 3, 16),
            ("Gênesis", 1, 1),
            ("Romanos", 8, 28),
            ("Mateus", 5, 13),
            ("Gênesis", 1, 2),
        ]
        errors: list[Exception] = []
        results: dict[int, Any] = {}
        barrier = threading.Barrier(len(refs))

        def worker(idx: int, book: str, ch: int, vs: int) -> None:
            try:
                barrier.wait(timeout=5.0)  # todas disparam juntas
                result = searcher.search_by_reference(book, ch, vs)
                results[idx] = result
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(
                target=worker,
                args=(i, *refs[i]),
                name=f"Searcher-Worker-{i}",
                daemon=True,
            )
            for i in range(len(refs))
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        # Nenhum erro deve ter ocorrido.
        assert errors == [], f"Erros encontrados: {errors}"
        # Todas as 5 threads devem ter retornado um resultado.
        assert len(results) == 5
        # Resultados devem ser não-None e ter texto não-vazio.
        for idx, result in results.items():
            assert result is not None, f"Thread {idx} retornou None"
            assert result.text, f"Thread {idx} retornou texto vazio"
            assert result.chapter == refs[idx][1]
            assert result.verse == refs[idx][2]

    def test_5_threads_correct_results(
        self, searcher: Searcher,
    ) -> None:
        """Cada thread deve receber o versículo correto, não cruzado."""
        refs = [
            ("João", 3, 16, "Porque Deus amou"),
            ("Gênesis", 1, 1, "No princípio"),
            ("Romanos", 8, 28, "cooperam"),
            ("Mateus", 5, 13, "sal da terra"),
            ("Gênesis", 1, 2, "sem forma"),
        ]
        results: dict[int, Any] = {}
        errors: list[Exception] = []
        barrier = threading.Barrier(len(refs))

        def worker(idx: int, book: str, ch: int, vs: int, expected: str) -> None:
            try:
                barrier.wait(timeout=5.0)
                result = searcher.search_by_reference(book, ch, vs)
                results[idx] = result
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(
                target=worker,
                args=(i, *refs[i]),
                name=f"Searcher-Verify-{i}",
                daemon=True,
            )
            for i in range(len(refs))
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert errors == [], f"Erros: {errors}"
        for idx, (_, _, _, expected) in enumerate(refs):
            assert results[idx] is not None
            assert expected in results[idx].text, (
                f"Thread {idx} esperava '{expected}' mas recebeu "
                f"'{results[idx].text}'"
            )


# ============================================================
# Teste 2 — 20 buscas simultâneas (search + search_by_reference).
# ============================================================


class TestTwentyConcurrentSearches:
    """20 buscas simultâneas misturando search() e search_by_reference().

    Verifica: nenhum deadlock, nenhum lock infinito, nenhum erro SQLite.
    """

    def test_20_concurrent_mixed_searches(
        self, searcher: Searcher,
    ) -> None:
        queries = [
            ("ref", ("João", 3, 16)),
            ("ref", ("Gênesis", 1, 1)),
            ("ref", ("Romanos", 8, 28)),
            ("ref", ("Mateus", 5, 13)),
            ("ref", ("Gênesis", 1, 2)),
            ("text", "deus amou o mundo"),
            ("text", "princípio criou"),
            ("text", "cooperam para o bem"),
            ("text", "sal da terra"),
            ("text", "haja luz"),
            ("ref", ("João", 3, 17)),
            ("text", "deus enviou"),
            ("ref", ("Gênesis", 1, 3)),
            ("text", "trevas sobre a face"),
            ("ref", ("João", 3, 16)),
            ("text", "deus amou o mundo"),
            ("ref", ("Gênesis", 1, 1)),
            ("text", "sal da terra"),
            ("ref", ("Romanos", 8, 28)),
            ("text", "princípio criou"),
        ]
        assert len(queries) == 20

        errors: list[Exception] = []
        results: list[Any] = [None] * 20
        barrier = threading.Barrier(20)

        def worker(idx: int, q_type: str, q_data: Any) -> None:
            try:
                barrier.wait(timeout=5.0)
                if q_type == "ref":
                    book, ch, vs = q_data
                    results[idx] = searcher.search_by_reference(book, ch, vs)
                else:
                    results[idx] = searcher.search(q_data)
            except Exception as e:
                errors.append((idx, e))

        threads = [
            threading.Thread(
                target=worker,
                args=(i, q[0], q[1]),
                name=f"Mixed-Worker-{i}",
                daemon=True,
            )
            for i, q in enumerate(queries)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        assert errors == [], f"Erros encontrados: {errors}"
        # Todas as 20 buscas devem ter retornado algo.
        for idx, r in enumerate(results):
            assert r is not None or r == [], (
                f"Thread {idx} retornou None inesperadamente"
            )

    def test_no_deadlock_with_thread_pool(
        self, searcher: Searcher,
    ) -> None:
        """20 buscas via ThreadPoolExecutor — verifica que não há deadlock."""
        refs = [("João", 3, 16), ("Gênesis", 1, 1)] * 10

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(searcher.search_by_reference, *r)
                for r in refs
            ]
            # Deve terminar em menos de 15s (sem deadlock).
            done_count = 0
            for future in as_completed(futures, timeout=15.0):
                result = future.result()  # raises se deu erro
                assert result is not None
                done_count += 1
            assert done_count == 20


# ============================================================
# Teste 3 — Pipeline completo em thread separada.
# ============================================================


class TestPipelineFullFlowInWorkerThread:
    """Pipeline completo executado em thread separada.

    Simula o cenário real: SpeechWorker publica ReferenceDetected
    em sua própria thread, o EventBus entrega sincronamente para
    o VersePresentationService, que chama Searcher.search_by_reference
    na mesma thread do SpeechWorker.

    Esperado: nenhum ProgrammingError, fluxo completo funciona.
    """

    def test_search_by_reference_in_worker_thread(
        self, searcher: Searcher,
    ) -> None:
        """Chama search_by_reference em thread separada (não main)."""
        result_holder: dict[str, Any] = {}
        error_holder: list[Exception] = []

        def worker() -> None:
            try:
                result = searcher.search_by_reference("João", 3, 16)
                result_holder["result"] = result
            except Exception as e:
                error_holder.append(e)

        t = threading.Thread(target=worker, name="SimulatedSpeechWorker", daemon=True)
        t.start()
        t.join(timeout=10.0)

        assert error_holder == [], f"Erro na thread worker: {error_holder}"
        assert "result" in result_holder
        result = result_holder["result"]
        assert result is not None
        assert "Porque Deus amou" in result.text
        assert result.book == "João"
        assert result.chapter == 3
        assert result.verse == 16

    def test_repeated_searches_across_threads(
        self, searcher: Searcher,
    ) -> None:
        """100 buscas distribuídas em 10 threads — estresse.

        Verifica que o Searcher é robusto sob carga multithreaded
        sustentada, não apenas em rajadas isoladas.
        """
        errors: list[Exception] = []
        success_count = 0
        lock = threading.Lock()
        barrier = threading.Barrier(10)

        def worker(tid: int) -> None:
            nonlocal success_count
            try:
                barrier.wait(timeout=5.0)
                for i in range(10):
                    result = searcher.search_by_reference("João", 3, 16)
                    if result is None:
                        errors.append(ValueError(f"t{tid}-{i}: None"))
                        return
                    with lock:
                        success_count += 1
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(i,), name=f"Stress-{i}", daemon=True)
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30.0)

        assert errors == [], f"Erros: {errors}"
        assert success_count == 100


# ============================================================
# Teste 4 — Verificação específica do erro original.
# ============================================================


class TestSqliteThreadSafetyRegression:
    """Teste de regressão — garante que o erro original não volta.

    O erro era: "SQLite objects created in a thread can only be used
    in that same thread."
    """

    def test_searcher_created_in_main_used_in_worker(
        self, searcher: Searcher,
    ) -> None:
        """Searcher criado na thread main, usado em worker thread.

        Este é exatamente o cenário que falhava antes da Sprint 18.0.1:
        o CompositionRoot cria o Searcher na thread main, mas o
        VersePresentationService chama search_by_reference na thread
        SpeechWorker-Whisper.
        """
        # searcher foi criado pela fixture (thread main do pytest).
        # Vamos usá-lo em uma thread separada.
        error: list[Exception] = []

        def worker() -> None:
            try:
                # Antes da Sprint 18.0.1, isto levantaria:
                # sqlite3.ProgrammingError: SQLite objects created in a
                # thread can only be used in that same thread.
                result = searcher.search_by_reference("João", 3, 16)
                assert result is not None
                assert "Porque Deus amou" in result.text
            except sqlite3.ProgrammingError as e:
                error.append(e)
            except Exception as e:
                error.append(e)

        t = threading.Thread(target=worker, name="RegressionTest", daemon=True)
        t.start()
        t.join(timeout=10.0)

        assert error == [], (
            f"Regressão: SQLite ProgrammingError voltou! Erro: {error}"
        )

    def test_no_check_same_thread_false_used(self) -> None:
        """Verifica que o código NÃO usa check_same_thread=False.

        Inspeção estática do source do Searcher para garantir que
        a solução não recorre ao anti-pattern proibido.
        """
        import ast
        import inspect

        import busca.searcher as searcher_module

        source = inspect.getsource(searcher_module)
        tree = ast.parse(source)

        # Percorre todos os chamadas de função no módulo.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Verifica kwargs de qualquer chamada sqlite3.connect.
                for kw in node.keywords:
                    if kw.arg == "check_same_thread":
                        # Encontrou — é uma violação.
                        raise AssertionError(
                            "Searcher usa check_same_thread — "
                            "violação da Sprint 18.0.1"
                        )


# ============================================================
# Teste 5 — Pipeline completo com EventBus + VersePresentationService.
# ============================================================


class TestPipelineEventDrivenConcurrency:
    """Pipeline completo orientado a eventos em thread separada.

    Simula o fluxo real:
      SpeechWorker (thread) → ReferenceDetected → VersePresentationService
      → Searcher.search_by_reference → VerseResolved → VersePresented
    """

    def test_full_pipeline_in_worker_thread(
        self, searcher: Searcher, test_db: str,
    ) -> None:
        """Pipeline completo executado em thread worker."""
        from unittest.mock import MagicMock

        from pipeline.bus import PipelineEventBus
        from pipeline.events import (
            ReferenceDetected,
            VersePresentationFailed,
            VersePresented,
            VerseResolved,
            VerseResolving,
        )
        from pipeline.metadata import EventMetadata
        from presentation.verse_presentation_service import (
            VersePresentationService,
        )

        # Mock HolyricsClient — não faz chamada real.
        class FakeHolyrics:
            def __init__(self) -> None:
                self.calls = []

            def show_verse(self, book_id, chapter, verse, version="ACF", quick=False):
                self.calls.append((book_id, chapter, verse))
                from integracao_holyrics.models import ShowVerseResult
                return ShowVerseResult(
                    status="ok",
                    verse_id=f"{book_id:02d}{chapter:03d}{verse:03d}",
                    book_id=book_id, chapter=chapter, verse=verse,
                    version=version,
                )

        store = MagicMock()
        bus = PipelineEventBus(store=store)
        holyrics = FakeHolyrics()
        service = VersePresentationService(
            searcher=searcher,
            holyrics=holyrics,
            bus=bus,
            session_id="test-session",
        )
        service.start()

        events: list = []
        for evt_type in (VerseResolving, VerseResolved, VersePresented, VersePresentationFailed):
            bus.subscribe(evt_type, events.append)

        # Publicar ReferenceDetected em thread separada (simula SpeechWorker).
        meta = EventMetadata.for_initial(
            session_id="test-session",
            origin="SpeechWorker",
            correlation_id="test-corr",
            event_id="ref-evt-id",
        )
        ref = ReferenceDetected(
            meta=meta,
            intent="OPEN_REFERENCE",
            book="João",
            book_id=43,
            chapter=3,
            verse_start=16,
            verse_end=16,
            confidence=0.95,
            raw_text="joão três dezesseis",
            normalized_text="joao 3:16",
        )

        errors: list[Exception] = []

        def worker() -> None:
            try:
                bus.publish(ref)
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=worker, name="SimulatedSpeechWorker", daemon=True)
        t.start()
        t.join(timeout=10.0)
        service.stop()

        assert errors == [], f"Erro no pipeline: {errors}"
        types = [type(e).__name__ for e in events]
        assert types == ["VerseResolving", "VerseResolved", "VersePresented"], (
            f"Eventos esperados não publicados. Recebidos: {types}"
        )
        # Holyrics foi chamado.
        assert len(holyrics.calls) == 1
        assert holyrics.calls[0] == (43, 3, 16)
