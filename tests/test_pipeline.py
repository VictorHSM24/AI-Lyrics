"""Testes unitários do módulo core/pipeline.py.

Estratégia:
  - Pipeline é uma fachada — testa-se lifecycle e delegação.
  - Cria-se um DB FTS5 de teste em tmp_path para que o wiring funcione.
  - Usa-se BookTable real do config/books.json.
  - healthcheck() testa status de componentes.
  - process_utterance() delega ao orchestrator — testa-se que a fachade
    repassa corretamente.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from config import BookTable, Config, load_books, load_config
from core.exceptions import PipelineError
from core.pipeline import ApplicationContext, Pipeline
from core.pipeline_metrics import PipelineMetrics
from core.types import LogEntry, Utterance


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FTS5_SCHEMA = (
    "CREATE VIRTUAL TABLE verses USING fts5("
    "book, chapter UNINDEXED, verse UNINDEXED, text, "
    "version UNINDEXED, id UNINDEXED, "
    "tokenize = 'unicode61 remove_diacritics 2')"
)

_SAMPLE_VERSES = [
    {"book_id": 43, "book": "João", "chapter": 3, "verse": 16,
     "text": "Porque Deus amou o mundo de tal maneira", "version": "ACF"},
    {"book_id": 43, "book": "João", "chapter": 3, "verse": 17,
     "text": "Porque Deus enviou o seu Filho", "version": "ACF"},
    {"book_id": 1, "book": "Gênesis", "chapter": 1, "verse": 1,
     "text": "No princípio criou Deus os céus e a terra", "version": "ACF"},
]


def _build_test_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_FTS5_SCHEMA)
        for v in _SAMPLE_VERSES:
            vid = f"{v['book_id']:02d}{v['chapter']:03d}{v['verse']:03d}"
            conn.execute(
                "INSERT INTO verses (book, chapter, verse, text, version, id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (v["book"], v["chapter"], v["verse"], v["text"], v["version"], vid),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _set_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOLYRICS_TOKEN", "test-token-123")


@pytest.fixture(autouse=True)
def _mock_holyrics_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mocka chamadas HTTP do Holyrics para evitar timeouts em testes."""
    from integracao_holyrics import HolyricsClient
    from integracao_holyrics.models import ShowVerseResult
    monkeypatch.setattr(HolyricsClient, "test_connection", lambda self: True)
    monkeypatch.setattr(
        HolyricsClient, "show_verse",
        lambda self, book_id, chapter, verse, version="ACF", quick=False: ShowVerseResult(
            status="ok", verse_id=f"{book_id:02d}{chapter:03d}{(verse or 0):03d}",
            book_id=book_id, chapter=chapter, verse=verse, version=version,
        ),
    )


@pytest.fixture
def book_table() -> BookTable:
    return load_books("config/books.json")


@pytest.fixture
def test_config(tmp_path: Path, book_table: BookTable) -> Config:
    """Config real com DB de teste em tmp_path."""
    db_path = str(tmp_path / "test.sqlite")
    _build_test_db(db_path)
    state_path = str(tmp_path / "state.json")
    cfg = load_config("config/config.yaml")
    # Reconstruir Config com paths de teste (frozen dataclass)
    from config.models import (
        CacheConfig, Config, ConfidenceConfig, HolyricsConfig,
        LLMConfig, LogConfig, SearchConfig, StateConfig, STTConfig, VadConfig,
    )
    return Config(
        holyrics=cfg.holyrics,
        stt=cfg.stt,
        llm=cfg.llm,
        search=SearchConfig(
            fts5_db=db_path,
            embeddings_path=str(tmp_path / "emb.npy"),
            embedding_model=cfg.search.embedding_model,
            embedding_device=cfg.search.embedding_device,
            rrf_k=cfg.search.rrf_k,
            top_k=cfg.search.top_k,
            search_gap=cfg.search.search_gap,
        ),
        state=StateConfig(
            default_version=cfg.state.default_version,
            persist_path=state_path,
        ),
        cache=cfg.cache,
        confidence=cfg.confidence,
        log=cfg.log,
        mode=cfg.mode,
        audio=cfg.audio,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utterance(text: str = "joão 3 16", c_stt: float = 0.95) -> Utterance:
    return Utterance(text=text, c_stt=c_stt, audio_ms=2000)


# ---------------------------------------------------------------------------
# Construtor
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_with_config_object(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        assert p.started is False
        assert p.context is None

    def test_init_with_config_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = Pipeline("config/config.yaml", load_books("config/books.json"))
        assert p.started is False

    def test_init_creates_metrics(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        assert isinstance(p.metrics, PipelineMetrics)
        assert p.metrics.total_utterances == 0


# ---------------------------------------------------------------------------
# Lifecycle: start / stop
# ---------------------------------------------------------------------------


class TestStartStop:
    def test_start_sets_started(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        assert p.started is True
        p.stop()

    def test_start_creates_context(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        assert p.context is not None
        assert isinstance(p.context, ApplicationContext)
        p.stop()

    def test_start_creates_orchestrator(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        entry = p.process_utterance(_utterance())
        assert isinstance(entry, LogEntry)
        p.stop()

    def test_double_start_raises(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        with pytest.raises(PipelineError, match="already started"):
            p.start()
        p.stop()

    def test_stop_clears_context(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        assert p.context is not None
        p.stop()
        assert p.context is None
        assert p.started is False

    def test_stop_idempotent(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        p.stop()
        p.stop()

    def test_stop_without_start(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.stop()

    def test_start_stop_start_cycle(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        p.stop()
        p.start()
        assert p.started is True
        p.stop()


# ---------------------------------------------------------------------------
# healthcheck
# ---------------------------------------------------------------------------


class TestHealthcheck:
    def test_not_started(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        status = p.healthcheck()
        assert status == {
            "holyrics": False, "search": False, "state": False,
            "parser": False, "llm": False,
        }

    def test_started(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        status = p.healthcheck()
        assert "holyrics" in status
        assert "search" in status
        assert "state" in status
        assert "parser" in status
        assert "llm" in status
        assert status["state"] is True
        assert status["parser"] is True
        p.stop()

    def test_after_stop(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        p.stop()
        status = p.healthcheck()
        assert status["state"] is False
        assert status["parser"] is False


# ---------------------------------------------------------------------------
# process_utterance — delegação
# ---------------------------------------------------------------------------


class TestProcessUtterance:
    def test_not_started_raises(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        with pytest.raises(PipelineError, match="not started"):
            p.process_utterance(_utterance())

    def test_after_stop_raises(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        p.stop()
        with pytest.raises(PipelineError, match="not started"):
            p.process_utterance(_utterance())

    def test_returns_log_entry(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        entry = p.process_utterance(_utterance(c_stt=0.95))
        assert isinstance(entry, LogEntry)
        assert entry.audio_ms == 2000
        p.stop()

    def test_updates_metrics(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        p.process_utterance(_utterance())
        assert p.metrics.total_utterances == 1
        p.stop()

    def test_multiple_accumulates(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        for _ in range(5):
            p.process_utterance(_utterance())
        assert p.metrics.total_utterances == 5
        p.stop()

    def test_none_action(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        entry = p.process_utterance(_utterance(text="olá tudo bem"))
        assert isinstance(entry, LogEntry)
        p.stop()


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    def test_started(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        assert p.started is False
        p.start()
        assert p.started is True
        p.stop()
        assert p.started is False

    def test_metrics(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        assert isinstance(p.metrics, PipelineMetrics)

    def test_context_none_before_start(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        assert p.context is None

    def test_context_after_start(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        ctx = p.context
        assert ctx is not None
        assert hasattr(ctx, "parser")
        assert hasattr(ctx, "searcher")
        assert hasattr(ctx, "decision_engine")
        assert hasattr(ctx, "state_manager")
        assert hasattr(ctx, "holyrics")
        assert hasattr(ctx, "book_table")
        p.stop()


# ---------------------------------------------------------------------------
# ApplicationContext
# ---------------------------------------------------------------------------


class TestApplicationContext:
    def test_is_dataclass(self) -> None:
        import dataclasses
        assert dataclasses.is_dataclass(ApplicationContext)

    def test_fields(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        ctx = p.context
        assert ctx is not None
        assert ctx.parser is not None
        assert ctx.decision_engine is not None
        assert ctx.state_manager is not None
        assert ctx.holyrics is not None
        assert ctx.book_table is not None
        p.stop()


# ---------------------------------------------------------------------------
# Wiring interno
# ---------------------------------------------------------------------------


class TestWiring:
    def test_parser(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        from parser.parser import Parser
        assert isinstance(p.context.parser, Parser)
        p.stop()

    def test_decision_engine(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        from core.decision import DecisionEngine
        assert isinstance(p.context.decision_engine, DecisionEngine)
        p.stop()

    def test_state_manager(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        from estado.state import BibleStateManager
        assert isinstance(p.context.state_manager, BibleStateManager)
        p.stop()

    def test_holyrics(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        from integracao_holyrics import HolyricsClient
        assert isinstance(p.context.holyrics, HolyricsClient)
        p.stop()

    def test_searcher_or_none(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        from busca.searcher import Searcher
        assert p.context.searcher is None or isinstance(p.context.searcher, Searcher)
        p.stop()


# ---------------------------------------------------------------------------
# Integração ponta-a-ponta
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_show_command(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        entry = p.process_utterance(_utterance(text="joão 3 16", c_stt=0.98))
        assert entry.parser.get("action") == "show"
        assert entry.total_ms >= 0
        p.stop()

    def test_none_command(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        entry = p.process_utterance(_utterance(text="bom dia pessoal"))
        assert entry.parser.get("action") in ("none", None)
        p.stop()

    def test_metrics_snapshot(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        p.process_utterance(_utterance())
        p.process_utterance(_utterance())
        snap = p.metrics.snapshot()
        assert snap.total_utterances == 2
        p.stop()

    def test_state_persisted_on_stop(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        p.process_utterance(_utterance(text="joão 3 16", c_stt=0.98))
        p.stop()
        # state.json deve ter sido criado
        assert os.path.isfile(test_config.state.persist_path)
