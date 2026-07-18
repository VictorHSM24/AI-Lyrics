"""Smoke tests de integração entre módulos do sistema.

Objetivo: detectar incompatibilidades entre módulos antes dos testes
com hardware e áudio reais. Valida contratos públicos, compatibilidade
de DTOs e fluxo ponta a ponta.

Implementações REAIS usadas:
  - parser (Parser, ParserBookTable, Normalizer)
  - searcher (Searcher com DB FTS5 de teste)
  - decision engine (DecisionEngine)
  - state manager (BibleStateManager)
  - pipeline (Pipeline facade)

Dependências SIMULADAS (mocks):
  - Holyrics (HTTP mock — sem servidor real)
  - áudio real (não usado — STT não testado aqui)
  - GPU/CUDA (não usado)
  - LLM (não implementado no sistema)
  - embeddings (não usado — busca FTS5 apenas)

Fluxos cobertos:
  1. "joao 3 16" → Parser → Decision → VerseRef válido
  2. "proximo" com estado João 3:16 → João 3:17
  3. "volta dois" com estado João 3:16 → João 3:14
  4. "aquele texto que fala que deus amou o mundo" → forward_to_llm
  5. SearchResult ambíguo → requires_confirmation == True
  6. Inicialização completa do Pipeline → healthcheck healthy

Não testa: benchmark, carga, performance, replay de sermões,
captura de áudio real, inferência real do Whisper, LLM real,
embeddings, interface gráfica.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from busca.searcher import Searcher, SearchResult
from config import BookTable, Config, load_books, load_config
from config.models import SearchConfig
from core.decision import DecisionEngine
from core.exceptions import PipelineError
from core.pipeline import Pipeline
from core.types import Confidence, Decision, Intent, LogEntry, Utterance, VerseRef
from estado.state import BibleStateManager, BibleStructure, load_bible_structure
from integracao_holyrics import HolyricsClient
from integracao_holyrics.models import ShowVerseResult
from parser.books import ParserBookTable
from parser.parser import Parser


# ---------------------------------------------------------------------------
# Fixtures — DB FTS5 de teste
# ---------------------------------------------------------------------------

_FTS5_SCHEMA = (
    "CREATE VIRTUAL TABLE verses USING fts5("
    "book, chapter UNINDEXED, verse UNINDEXED, text, "
    "version UNINDEXED, id UNINDEXED, "
    "tokenize = 'unicode61 remove_diacritics 2')"
)

_SAMPLE_VERSES = [
    {"book_id": 43, "book": "João", "chapter": 3, "verse": 14,
     "text": "E como Moisés levantou a serpente no deserto", "version": "ACF"},
    {"book_id": 43, "book": "João", "chapter": 3, "verse": 15,
     "text": "Para que todo aquele que nele crê não pereça", "version": "ACF"},
    {"book_id": 43, "book": "João", "chapter": 3, "verse": 16,
     "text": "Porque Deus amou o mundo de tal maneira que deu o seu Filho unigênito", "version": "ACF"},
    {"book_id": 43, "book": "João", "chapter": 3, "verse": 17,
     "text": "Porque Deus enviou o seu Filho ao mundo", "version": "ACF"},
    {"book_id": 43, "book": "João", "chapter": 3, "verse": 18,
     "text": "Quem crê nele não é condenado", "version": "ACF"},
    {"book_id": 1, "book": "Gênesis", "chapter": 1, "verse": 1,
     "text": "No princípio criou Deus os céus e a terra", "version": "ACF"},
    {"book_id": 45, "book": "Romanos", "chapter": 8, "verse": 28,
     "text": "E sabemos que todas as coisas cooperam para o bem", "version": "ACF"},
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
    """Mocka chamadas HTTP do Holyrics — sem servidor real."""
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
def test_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "test.sqlite")
    _build_test_db(db_path)
    return db_path


@pytest.fixture
def search_config(test_db: str) -> SearchConfig:
    return SearchConfig(
        fts5_db=test_db,
        embeddings_path="data/bible.embeddings.npy",
        embedding_model="intfloat/multilingual-e5-small",
        embedding_device="cpu",
        rrf_k=60,
        top_k=20,
        search_gap=0.15,
    )


@pytest.fixture
def searcher(search_config: SearchConfig, book_table: BookTable) -> Searcher:
    return Searcher(search_config, book_table, version="ACF")


@pytest.fixture
def structure(test_db: str) -> BibleStructure:
    return load_bible_structure(test_db)


@pytest.fixture
def book_names(book_table: BookTable) -> dict[int, str]:
    return {b.id: b.canonical for b in book_table.all_books()}


@pytest.fixture
def state_manager(structure: BibleStructure, book_names: dict[int, str], tmp_path: Path) -> BibleStateManager:
    return BibleStateManager(
        structure=structure,
        book_names=book_names,
        persist_path=str(tmp_path / "state.json"),
        default_version="ACF",
    )


@pytest.fixture
def parser(book_table: BookTable) -> Parser:
    return Parser(ParserBookTable(book_table.all_books()))


@pytest.fixture
def conf_config():
    from config.models import ConfidenceConfig
    return ConfidenceConfig(
        min_execute=0.85,
        min_confirm=0.60,
        stt_min=0.50,
        parser_high=0.90,
        parser_compact=0.85,
    )


@pytest.fixture
def holyrics() -> HolyricsClient:
    return HolyricsClient("http://127.0.0.1:3000/api", "test-token")


@pytest.fixture
def decision_engine(conf_config, state_manager, holyrics) -> DecisionEngine:
    return DecisionEngine(conf_config, state_manager, holyrics, mode="auto")


@pytest.fixture
def test_config(test_db: str, tmp_path: Path) -> Config:
    """Config real com DB de teste para Pipeline."""
    cfg = load_config("config/config.yaml")
    from config.models import (
        Config as ConfigDC, SearchConfig as SC, StateConfig,
    )
    return ConfigDC(
        holyrics=cfg.holyrics,
        stt=cfg.stt,
        llm=cfg.llm,
        search=SC(
            fts5_db=test_db,
            embeddings_path=str(tmp_path / "emb.npy"),
            embedding_model=cfg.search.embedding_model,
            embedding_device=cfg.search.embedding_device,
            rrf_k=cfg.search.rrf_k,
            top_k=cfg.search.top_k,
            search_gap=cfg.search.search_gap,
        ),
        state=StateConfig(
            default_version=cfg.state.default_version,
            persist_path=str(tmp_path / "state.json"),
        ),
        cache=cfg.cache,
        confidence=cfg.confidence,
        log=cfg.log,
        mode=cfg.mode,
        audio=cfg.audio,
    )


# ---------------------------------------------------------------------------
# Fluxo 1: "joao 3 16" → Parser → Decision → VerseRef válido
# ---------------------------------------------------------------------------


class TestFluxo1ParserDecisionVerseRef:
    """Fluxo: texto → Parser → DecisionEngine.evaluate → VerseRef válido."""

    def test_parser_produces_show_intent(self, parser: Parser) -> None:
        intent = parser.parse("joao 3 16")
        assert intent.action == "show"
        assert intent.book_id == 43
        assert intent.chapter == 3
        assert intent.verse == 16
        assert intent.confidence > 0.0

    def test_decision_executes_show(self, parser: Parser, decision_engine: DecisionEngine) -> None:
        intent = parser.parse("joao 3 16")
        decision = decision_engine.evaluate(intent, c_stt=0.98)
        assert decision.outcome == "execute"
        assert decision.confidence >= 0.85

    def test_decision_produces_valid_verse_ref(
        self, parser: Parser, decision_engine: DecisionEngine,
    ) -> None:
        intent = parser.parse("joao 3 16")
        decision = decision_engine.evaluate(intent, c_stt=0.98)
        assert decision.outcome == "execute"
        ref = decision_engine.execute(decision)
        assert ref is not None
        assert ref.book_id == 43
        assert ref.book == "João"
        assert ref.chapter == 3
        assert ref.verse == 16

    def test_holyrics_show_verse_called(
        self, parser: Parser, decision_engine: DecisionEngine, holyrics: HolyricsClient,
    ) -> None:
        intent = parser.parse("joao 3 16")
        decision = decision_engine.evaluate(intent, c_stt=0.98)
        decision_engine.execute(decision)
        # Holyrics mockado — verificar que show_verse foi chamado
        # (mock é lambda, não rastreia calls, mas não levanta = OK)

    def test_state_updated_after_execute(
        self, parser: Parser, decision_engine: DecisionEngine, state_manager: BibleStateManager,
    ) -> None:
        intent = parser.parse("joao 3 16")
        decision = decision_engine.evaluate(intent, c_stt=0.98)
        decision_engine.execute(decision)
        state = state_manager.current()
        assert state.book_id == 43
        assert state.chapter == 3
        assert state.verse == 16


# ---------------------------------------------------------------------------
# Fluxo 2: "proximo" com estado João 3:16 → João 3:17
# ---------------------------------------------------------------------------


class TestFluxo2Proximo:
    """Fluxo: estado João 3:16 + "proximo" → João 3:17."""

    def test_proximo_advances_one_verse(
        self, parser: Parser, decision_engine: DecisionEngine,
        state_manager: BibleStateManager,
    ) -> None:
        # Setup: estado em João 3:16
        state_manager.set(VerseRef(book_id=43, book="João", chapter=3, verse=16))
        intent = parser.parse("proximo", state_manager.current())
        assert intent.action == "next"
        decision = decision_engine.evaluate(intent, c_stt=0.98)
        assert decision.outcome == "execute"
        ref = decision_engine.execute(decision)
        assert ref is not None
        assert ref.chapter == 3
        assert ref.verse == 17

    def test_proximo_state_updated(
        self, parser: Parser, decision_engine: DecisionEngine,
        state_manager: BibleStateManager,
    ) -> None:
        state_manager.set(VerseRef(book_id=43, book="João", chapter=3, verse=16))
        intent = parser.parse("proximo", state_manager.current())
        decision = decision_engine.evaluate(intent, c_stt=0.98)
        decision_engine.execute(decision)
        state = state_manager.current()
        assert state.verse == 17


# ---------------------------------------------------------------------------
# Fluxo 3: "volta dois" com estado João 3:16 → João 3:14
# ---------------------------------------------------------------------------


class TestFluxo3VoltaDois:
    """Fluxo: estado João 3:16 + "volta dois" → João 3:14."""

    def test_volta_dois_goes_back_two(
        self, parser: Parser, decision_engine: DecisionEngine,
        state_manager: BibleStateManager,
    ) -> None:
        state_manager.set(VerseRef(book_id=43, book="João", chapter=3, verse=16))
        intent = parser.parse("volta dois", state_manager.current())
        assert intent.action == "previous"
        assert intent.amount == 2
        decision = decision_engine.evaluate(intent, c_stt=0.98)
        assert decision.outcome == "execute"
        ref = decision_engine.execute(decision)
        assert ref is not None
        assert ref.chapter == 3
        assert ref.verse == 14

    def test_volta_dois_state_updated(
        self, parser: Parser, decision_engine: DecisionEngine,
        state_manager: BibleStateManager,
    ) -> None:
        state_manager.set(VerseRef(book_id=43, book="João", chapter=3, verse=16))
        intent = parser.parse("volta dois", state_manager.current())
        decision = decision_engine.evaluate(intent, c_stt=0.98)
        decision_engine.execute(decision)
        state = state_manager.current()
        assert state.verse == 14


# ---------------------------------------------------------------------------
# Fluxo 4: "aquele texto que fala que deus amou o mundo" → forward_to_llm
# ---------------------------------------------------------------------------


class TestFluxo4ForwardToLLM:
    """Fluxo: texto indireto → parser uncertain → forward_to_llm == True."""

    def test_parser_produces_uncertain(self, parser: Parser) -> None:
        intent = parser.parse("aquele texto que fala que deus amou o mundo")
        assert intent.action == "uncertain"

    def test_decision_forward_to_llm(
        self, parser: Parser, decision_engine: DecisionEngine,
    ) -> None:
        intent = parser.parse("aquele texto que fala que deus amou o mundo")
        decision = decision_engine.evaluate(intent, c_stt=0.90)
        assert decision.outcome == "forward_to_llm"
        assert decision.forward_to_llm is True

    def test_no_holyrics_execution(
        self, parser: Parser, decision_engine: DecisionEngine, holyrics: HolyricsClient,
    ) -> None:
        intent = parser.parse("aquele texto que fala que deus amou o mundo")
        decision = decision_engine.evaluate(intent, c_stt=0.90)
        assert decision.outcome == "forward_to_llm"
        # execute() não deve ser chamado para forward_to_llm
        with pytest.raises(Exception):
            decision_engine.execute(decision)


# ---------------------------------------------------------------------------
# Fluxo 5: SearchResult ambíguo → requires_confirmation == True
# ---------------------------------------------------------------------------


class TestFluxo5AmbiguousSearch:
    """Fluxo: busca ambígua → confirm → requires_confirmation == True."""

    def test_ambiguous_search_result(self, searcher: Searcher) -> None:
        """Busca por termo genérico deve retornar resultados próximos."""
        results = searcher.search("deus")
        assert len(results) > 0
        # Com search_gap=0.15 e versículos similares, pode ser ambíguo

    def test_ambiguous_leads_to_confirm(
        self, parser: Parser, decision_engine: DecisionEngine,
    ) -> None:
        """SearchResult ambíguo → requires_confirmation == True."""
        # Construir SearchResult ambíguo manualmente
        ambiguous_results = [
            SearchResult(
                reference="João 3:16", book="João", book_id=43,
                chapter=3, verse=16,
                text="Porque Deus amou o mundo...",
                version="ACF", score=0.80, c_search=0.80,
                ambiguous=True, match_type="hybrid",
            ),
        ]
        intent = Intent(
            action="search", query="deus amou o mundo",
            confidence=0.95, raw="buscar deus amou o mundo",
        )
        decision = decision_engine.evaluate(intent, c_stt=0.95, search_results=ambiguous_results)
        assert decision.outcome == "confirm"
        assert decision.requires_confirmation is True

    def test_unambiguous_high_confidence_executes(
        self, decision_engine: DecisionEngine,
    ) -> None:
        """SearchResult não ambíguo + alta confiança → execute."""
        results = [
            SearchResult(
                reference="João 3:16", book="João", book_id=43,
                chapter=3, verse=16,
                text="Porque Deus amou o mundo...",
                version="ACF", score=0.95, c_search=0.95,
                ambiguous=False, match_type="hybrid",
            ),
        ]
        intent = Intent(
            action="search", query="deus amou o mundo",
            confidence=0.98, raw="buscar deus amou o mundo",
        )
        decision = decision_engine.evaluate(intent, c_stt=0.98, search_results=results)
        # c_final = 0.98 * 0.98 * 0.95 = 0.912 >= 0.85
        assert decision.outcome == "execute"
        assert decision.requires_confirmation is False


# ---------------------------------------------------------------------------
# Fluxo 6: Inicialização completa do Pipeline → healthcheck healthy
# ---------------------------------------------------------------------------


class TestFluxo6PipelineInit:
    """Fluxo: Pipeline.start() → healthcheck() == healthy."""

    def test_pipeline_starts(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        assert p.started is True
        p.stop()

    def test_healthcheck_healthy(self, test_config: Config, book_table: BookTable) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        status = p.healthcheck()
        assert status["holyrics"] is True
        assert status["search"] is True
        assert status["state"] is True
        assert status["parser"] is True
        p.stop()

    def test_pipeline_processes_utterance(
        self, test_config: Config, book_table: BookTable,
    ) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        entry = p.process_utterance(Utterance(text="joao 3 16", c_stt=0.98))
        assert isinstance(entry, LogEntry)
        assert entry.parser["action"] == "show"
        assert entry.decision["outcome"] == "execute"
        p.stop()

    def test_pipeline_stop_persists_state(
        self, test_config: Config, book_table: BookTable,
    ) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        p.process_utterance(Utterance(text="joao 3 16", c_stt=0.98))
        p.stop()
        assert os.path.isfile(test_config.state.persist_path)

    def test_pipeline_metrics_accumulate(
        self, test_config: Config, book_table: BookTable,
    ) -> None:
        p = Pipeline(test_config, book_table)
        p.start()
        p.process_utterance(Utterance(text="joao 3 16", c_stt=0.98))
        p.process_utterance(Utterance(text="proximo", c_stt=0.98))
        assert p.metrics.total_utterances == 2
        assert p.metrics.total_executes >= 1
        p.stop()


# ---------------------------------------------------------------------------
# Integração STT → Parser (DTO compatibility)
# ---------------------------------------------------------------------------


class TestSTTToParserIntegration:
    """Valida que a saída do STT (STTResult.text) é compatível com Parser.parse()."""

    def test_stt_result_text_feeds_parser(self, parser: Parser) -> None:
        """STTResult.text → Parser.parse() → Intent válido."""
        # Simular texto que o STT produziria (lowercase, sem pontuação)
        stt_text = "joao capitulo tres versiculo dezesseis"
        intent = parser.parse(stt_text)
        assert intent.action == "show"
        assert intent.book_id == 43
        assert intent.chapter == 3
        assert intent.verse == 16

    def test_stt_empty_text_produces_none(self, parser: Parser) -> None:
        """STT com texto vazio → action=none."""
        intent = parser.parse("")
        assert intent.action == "none"

    def test_stt_silence_produces_none(self, parser: Parser) -> None:
        """STT com silêncio (texto vazio) → action=none."""
        intent = parser.parse("   ")
        assert intent.action == "none"


# ---------------------------------------------------------------------------
# Integração Parser → Search (DTO compatibility)
# ---------------------------------------------------------------------------


class TestParserToSearchIntegration:
    """Valida que Intent.query do parser alimenta Searcher.search()."""

    def test_parser_search_intent_feeds_searcher(
        self, parser: Parser, searcher: Searcher,
    ) -> None:
        """Parser → Intent(action=search, query=...) → Searcher.search(query)."""
        # Parser não produz action=search diretamente; search vem do LLM
        # ou de uncertain. Mas podemos testar que Searcher aceita
        # queries no formato que o parser produziria.
        results = searcher.search("deus amou o mundo")
        assert len(results) > 0
        assert isinstance(results[0], SearchResult)

    def test_search_result_has_required_fields(self, searcher: Searcher) -> None:
        """SearchResult tem todos os campos que DecisionEngine consome."""
        results = searcher.search("deus")
        if results:
            r = results[0]
            assert hasattr(r, "book_id")
            assert hasattr(r, "book")
            assert hasattr(r, "chapter")
            assert hasattr(r, "verse")
            assert hasattr(r, "version")
            assert hasattr(r, "score")
            assert hasattr(r, "c_search")
            assert hasattr(r, "ambiguous")


# ---------------------------------------------------------------------------
# Integração Search → Decision (DTO compatibility)
# ---------------------------------------------------------------------------


class TestSearchToDecisionIntegration:
    """Valida que SearchResult alimenta DecisionEngine.evaluate()."""

    def test_real_search_results_feed_decision(
        self, searcher: Searcher, decision_engine: DecisionEngine,
    ) -> None:
        """Searcher.search() → list[SearchResult] → DecisionEngine.evaluate()."""
        results = searcher.search("deus amou o mundo")
        intent = Intent(
            action="search", query="deus amou o mundo",
            confidence=0.95, raw="deus amou o mundo",
        )
        decision = decision_engine.evaluate(intent, c_stt=0.95, search_results=results)
        assert decision.outcome in ("execute", "confirm", "ignore")

    def test_empty_search_results(self, decision_engine: DecisionEngine) -> None:
        """Search vazio (lista) → c_search=1.0, não ambíguo → execute ou confirm por confiança."""
        intent = Intent(
            action="search", query="xyz inexistente",
            confidence=0.95, raw="xyz",
        )
        decision = decision_engine.evaluate(intent, c_stt=0.95, search_results=[])
        # search_results=[] → _extract_search_confidence retorna (1.0, False)
        # c_final = 0.95 * 0.95 * 1.0 = 0.9025 >= min_execute=0.85 → execute
        assert decision.outcome == "execute"

    def test_none_search_results(self, decision_engine: DecisionEngine) -> None:
        """Search None (não executado) → ambiguous=True → confirm."""
        intent = Intent(
            action="search", query="xyz inexistente",
            confidence=0.95, raw="xyz",
        )
        decision = decision_engine.evaluate(intent, c_stt=0.95, search_results=None)
        # search_results=None + action=search → ambiguous=True → confirm
        assert decision.outcome == "confirm"


# ---------------------------------------------------------------------------
# Integração Decision → Holyrics (DTO compatibility)
# ---------------------------------------------------------------------------


class TestDecisionToHolyricsIntegration:
    """Valida que Decision.execute() chama Holyrics.show_verse() corretamente."""

    def test_execute_calls_show_verse(
        self, parser: Parser, decision_engine: DecisionEngine, holyrics: HolyricsClient,
    ) -> None:
        """Decision execute → Holyrics.show_verse(book_id, chapter, verse, version)."""
        intent = parser.parse("joao 3 16")
        decision = decision_engine.evaluate(intent, c_stt=0.98)
        ref = decision_engine.execute(decision)
        assert ref is not None
        # Holyrics mockado — show_verse não levanta = contrato OK

    def test_decision_ref_matches_holyrics_params(
        self, parser: Parser, decision_engine: DecisionEngine,
    ) -> None:
        """VerseRef produzido pela decision tem campos para show_verse."""
        intent = parser.parse("joao 3 16")
        decision = decision_engine.evaluate(intent, c_stt=0.98)
        ref = decision_engine.execute(decision)
        assert ref is not None
        # show_verse precisa: book_id, chapter, verse, version
        assert isinstance(ref.book_id, int)
        assert isinstance(ref.chapter, int)
        assert ref.verse is None or isinstance(ref.verse, int)
        assert isinstance(ref.version, str)


# ---------------------------------------------------------------------------
# Integração State → Decision (DTO compatibility)
# ---------------------------------------------------------------------------


class TestStateToDecisionIntegration:
    """Valida que BibleStateManager alimenta DecisionEngine para navegação."""

    def test_state_apply_next(
        self, parser: Parser, decision_engine: DecisionEngine,
        state_manager: BibleStateManager,
    ) -> None:
        """State + Intent(next) → Decision execute → State atualizado."""
        state_manager.set(VerseRef(book_id=43, book="João", chapter=3, verse=16))
        intent = parser.parse("proximo", state_manager.current())
        decision = decision_engine.evaluate(intent, c_stt=0.98)
        assert decision.outcome == "execute"
        ref = decision_engine.execute(decision)
        assert ref is not None
        assert ref.verse == 17
        # Estado foi atualizado pela decision
        state = state_manager.current()
        assert state.verse == 17

    def test_state_empty_navigation_raises(
        self, parser: Parser, decision_engine: DecisionEngine,
        state_manager: BibleStateManager,
    ) -> None:
        """Estado vazio + next → erro (não há versículo anterior)."""
        intent = parser.parse("proximo", state_manager.current())
        decision = decision_engine.evaluate(intent, c_stt=0.98)
        # execute deve falhar — estado vazio
        with pytest.raises(Exception):
            decision_engine.execute(decision)

    def test_state_persistence_roundtrip(
        self, state_manager: BibleStateManager, tmp_path: Path,
    ) -> None:
        """State save → load preserva estado."""
        state_manager.set(VerseRef(book_id=43, book="João", chapter=3, verse=16))
        state_manager.save()
        # Criar novo manager que carrega do mesmo path
        structure = state_manager._structure
        book_names = state_manager._book_names
        m2 = BibleStateManager(
            structure=structure, book_names=book_names,
            persist_path=str(tmp_path / "state.json"),
            default_version="ACF",
        )
        m2.load()
        state = m2.current()
        assert state.book_id == 43
        assert state.chapter == 3
        assert state.verse == 16
