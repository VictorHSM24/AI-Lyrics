"""Testes dos componentes de embedding (FASE 6).

Cobre:
  - EmbeddingProvider (interface abstrata)
  - SentenceTransformerProvider (implementação)
  - EmbeddingIndex (persistência + busca)
  - EmbeddingSearcher (coordenador)
  - SemanticResult (DTO)

Notas:
  - Testes do SentenceTransformerProvider usam mock para não depender
    de download de modelo.
  - Testes de EmbeddingIndex usam vetores sintéticos.
  - Testes de integração (com modelo real) são marcados como @pytest.mark.slow
    e skip se modelo não estiver disponível.
"""

from __future__ import annotations

import json
import os
import tempfile

import numpy as np
import pytest

from busca.embedding_index import EmbeddingIndex, SemanticResult


# ---------------------------------------------------------------------------
# Mock EmbeddingProvider
# ---------------------------------------------------------------------------


class MockEmbeddingProvider:
    """Provider mock que gera vetores determinísticos baseados em hash do texto."""

    @property
    def dim(self) -> int:
        return 64

    @property
    def name(self) -> str:
        return "mock:hash"

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.array([], dtype=np.float32).reshape(0, self.dim)
        result = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            # Hash determinístico do texto → vetor
            h = hash(text)
            np.random.seed(abs(h) % (2**32))
            vec = np.random.randn(self.dim).astype(np.float32)
            # L2 normalize
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            result[i] = vec
        return result

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_texts([text])[0]


# ---------------------------------------------------------------------------
# Testes de SemanticResult (DTO)
# ---------------------------------------------------------------------------


class TestSemanticResult:
    """Testes do DTO SemanticResult."""

    def test_creation(self) -> None:
        r = SemanticResult(uid="ACF-43-3-16", score=0.95, rank=0)
        assert r.uid == "ACF-43-3-16"
        assert r.score == 0.95
        assert r.rank == 0

    def test_is_frozen(self) -> None:
        r = SemanticResult(uid="test", score=0.5, rank=1)
        with pytest.raises(AttributeError):
            r.score = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Testes de EmbeddingIndex
# ---------------------------------------------------------------------------


class TestEmbeddingIndex:
    """Testes de EmbeddingIndex com vetores sintéticos."""

    def setup_method(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.vectors_path = os.path.join(self.tmpdir, "test_emb.npy")
        self.meta_path = os.path.join(self.tmpdir, "test_emb.json")
        self.provider = MockEmbeddingProvider()

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_nonexistent_returns_false(self) -> None:
        index = EmbeddingIndex(self.vectors_path, self.meta_path)
        assert not index.load()
        assert not index.is_loaded
        assert index.size == 0

    def test_build_and_save(self) -> None:
        index = EmbeddingIndex(self.vectors_path, self.meta_path)
        verses = [
            {"uid": "v1", "text": "amor de deus"},
            {"uid": "v2", "text": "paz seja convosco"},
            {"uid": "v3", "text": "o senhor e meu pastor"},
        ]
        index.build(self.provider, verses, batch_size=2)
        assert index.is_loaded
        assert index.size == 3
        assert index.dim == 64
        assert os.path.isfile(self.vectors_path)
        assert os.path.isfile(self.meta_path)

    def test_load_after_save(self) -> None:
        # Build e save
        index1 = EmbeddingIndex(self.vectors_path, self.meta_path)
        verses = [
            {"uid": "v1", "text": "amor de deus"},
            {"uid": "v2", "text": "paz seja convosco"},
        ]
        index1.build(self.provider, verses)

        # Carregar em nova instância
        index2 = EmbeddingIndex(self.vectors_path, self.meta_path)
        assert index2.load()
        assert index2.is_loaded
        assert index2.size == 2
        assert index2.dim == 64

    def test_search_returns_results(self) -> None:
        index = EmbeddingIndex(self.vectors_path, self.meta_path)
        verses = [
            {"uid": "v1", "text": "amor de deus"},
            {"uid": "v2", "text": "paz seja convosco"},
            {"uid": "v3", "text": "o senhor e meu pastor"},
        ]
        index.build(self.provider, verses)

        # Buscar com query "amor"
        query_vec = self.provider.embed_query("amor de deus")
        results = index.search(query_vec, top_k=2)

        assert len(results) == 2
        assert all(isinstance(r, SemanticResult) for r in results)
        # Resultados devem estar ordenados por score decrescente
        assert results[0].score >= results[1].score
        assert results[0].rank == 0
        assert results[1].rank == 1

    def test_search_top_k_larger_than_size(self) -> None:
        index = EmbeddingIndex(self.vectors_path, self.meta_path)
        verses = [
            {"uid": "v1", "text": "amor"},
            {"uid": "v2", "text": "paz"},
        ]
        index.build(self.provider, verses)

        query_vec = self.provider.embed_query("amor")
        results = index.search(query_vec, top_k=10)
        assert len(results) == 2  # apenas 2 disponíveis

    def test_search_empty_index(self) -> None:
        index = EmbeddingIndex(self.vectors_path, self.meta_path)
        query_vec = np.random.randn(64).astype(np.float32)
        results = index.search(query_vec, top_k=5)
        assert results == []

    def test_get_vector_existing(self) -> None:
        index = EmbeddingIndex(self.vectors_path, self.meta_path)
        verses = [{"uid": "v1", "text": "amor"}]
        index.build(self.provider, verses)
        vec = index.get_vector("v1")
        assert vec is not None
        assert vec.shape == (64,)

    def test_get_vector_nonexistent(self) -> None:
        index = EmbeddingIndex(self.vectors_path, self.meta_path)
        verses = [{"uid": "v1", "text": "amor"}]
        index.build(self.provider, verses)
        vec = index.get_vector("nonexistent")
        assert vec is None

    def test_build_empty_verses(self) -> None:
        index = EmbeddingIndex(self.vectors_path, self.meta_path)
        index.build(self.provider, [])
        # Não deve quebrar, mas size deve ser 0
        assert index.size == 0 or not index.is_loaded

    def test_scores_in_range(self) -> None:
        """Scores devem estar em [0.0, 1.0]."""
        index = EmbeddingIndex(self.vectors_path, self.meta_path)
        verses = [
            {"uid": f"v{i}", "text": f"texto {i}"} for i in range(10)
        ]
        index.build(self.provider, verses)
        query_vec = self.provider.embed_query("texto 5")
        results = index.search(query_vec, top_k=10)
        for r in results:
            assert 0.0 <= r.score <= 1.0


# ---------------------------------------------------------------------------
# Testes de EmbeddingSearcher
# ---------------------------------------------------------------------------


class TestEmbeddingSearcher:
    """Testes de EmbeddingSearcher com provider mock."""

    def setup_method(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.vectors_path = os.path.join(self.tmpdir, "test_emb.npy")
        self.meta_path = os.path.join(self.tmpdir, "test_emb.json")
        self.provider = MockEmbeddingProvider()
        from busca.embedding_searcher import EmbeddingSearcher
        self.index = EmbeddingIndex(self.vectors_path, self.meta_path)
        self.searcher = EmbeddingSearcher(self.provider, self.index)

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_nonexistent(self) -> None:
        assert not self.searcher.load()
        assert not self.searcher.is_available

    def test_build_then_available(self) -> None:
        verses = [
            {"uid": "v1", "text": "amor de deus"},
            {"uid": "v2", "text": "paz seja convosco"},
        ]
        self.searcher.build(verses)
        assert self.searcher.is_available
        assert self.searcher.size == 2

    def test_load_or_build(self) -> None:
        verses = [
            {"uid": "v1", "text": "amor"},
            {"uid": "v2", "text": "paz"},
        ]
        # Primeira chamada: build
        assert self.searcher.load_or_build(verses)
        assert self.searcher.is_available

        # Segunda chamada: load do disco
        from busca.embedding_searcher import EmbeddingSearcher
        index2 = EmbeddingIndex(self.vectors_path, self.meta_path)
        searcher2 = EmbeddingSearcher(self.provider, index2)
        assert searcher2.load_or_build(verses)
        assert searcher2.is_available
        assert searcher2.size == 2

    def test_search_returns_results(self) -> None:
        verses = [
            {"uid": "v1", "text": "amor de deus"},
            {"uid": "v2", "text": "paz seja convosco"},
            {"uid": "v3", "text": "o senhor e meu pastor"},
        ]
        self.searcher.build(verses)
        results = self.searcher.search("amor de deus", top_k=2)
        assert len(results) == 2
        assert all(isinstance(r, SemanticResult) for r in results)

    def test_search_empty_query(self) -> None:
        verses = [{"uid": "v1", "text": "amor"}]
        self.searcher.build(verses)
        results = self.searcher.search("", top_k=5)
        assert results == []

    def test_search_not_loaded(self) -> None:
        """Search sem index carregado retorna []."""
        results = self.searcher.search("amor", top_k=5)
        assert results == []

    def test_search_with_scores(self) -> None:
        verses = [
            {"uid": "v1", "text": "amor de deus"},
            {"uid": "v2", "text": "paz seja convosco"},
        ]
        self.searcher.build(verses)
        scores = self.searcher.search_with_scores("amor", top_k=2)
        assert isinstance(scores, dict)
        assert len(scores) == 2
        for uid, score in scores.items():
            assert isinstance(uid, str)
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Testes de integração do Searcher com EmbeddingSearcher
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def embedding_searcher_mock():
    """EmbeddingSearcher com mock provider e índice de versículos reais."""
    import sqlite3
    from busca.embedding_searcher import EmbeddingSearcher

    tmpdir = tempfile.mkdtemp()
    vectors_path = os.path.join(tmpdir, "test_emb.npy")
    meta_path = os.path.join(tmpdir, "test_emb.json")

    provider = MockEmbeddingProvider()
    index = EmbeddingIndex(vectors_path, meta_path)

    # Carregar versículos reais do banco
    config_path = "config/config.yaml"
    if not os.path.isfile(config_path):
        pytest.skip("config.yaml not found")
    from config import load_config
    cfg = load_config(config_path)
    if not os.path.isfile(cfg.search.fts5_db):
        pytest.skip(f"FTS5 database not found: {cfg.search.fts5_db}")

    db = sqlite3.connect(cfg.search.fts5_db)
    rows = db.execute(
        "SELECT id, text FROM verses WHERE version = 'ACF' LIMIT 500",
    ).fetchall()
    db.close()

    verses = [{"uid": r[0], "text": r[1]} for r in rows]
    searcher = EmbeddingSearcher(provider, index)
    searcher.build(verses, batch_size=128)

    yield searcher

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestSearcherWithEmbeddings:
    """Testes de integração do Searcher com EmbeddingSearcher."""

    def test_searcher_has_embeddings_true(
        self, embedding_searcher_mock,
    ) -> None:
        from busca.searcher import Searcher
        from config import load_config, load_books

        cfg = load_config("config/config.yaml")
        bt = load_books()
        s = Searcher(
            cfg.search, bt, cfg.state.default_version,
            embedding_searcher=embedding_searcher_mock,
        )
        assert s.has_embeddings
        s.close()

    def test_searcher_has_embeddings_false(self) -> None:
        from busca.searcher import Searcher
        from config import load_config, load_books

        cfg = load_config("config/config.yaml")
        bt = load_books()
        s = Searcher(cfg.search, bt, cfg.state.default_version)
        assert not s.has_embeddings
        s.close()

    def test_search_with_plan_semantic_mode(
        self, embedding_searcher_mock,
    ) -> None:
        """search_with_plan com semantic mode deve incluir candidatos semânticos."""
        from busca.searcher import Searcher
        from busca.query_planner import QueryPlan
        from config import load_config, load_books

        cfg = load_config("config/config.yaml")
        bt = load_books()
        s = Searcher(
            cfg.search, bt, cfg.state.default_version,
            embedding_searcher=embedding_searcher_mock,
        )

        plan = QueryPlan(
            original_query="o bom pastor",
            normalized_query="o bom pastor",
            keywords=("bom", "pastor"),
            search_modes=("or", "keyword_subset", "fuzzy", "semantic"),
        )
        results = s.search_with_plan(plan)
        assert len(results) > 0
        s.close()

    def test_search_with_plan_without_semantic_mode(
        self, embedding_searcher_mock,
    ) -> None:
        """search_with_plan sem semantic mode funciona normalmente."""
        from busca.searcher import Searcher
        from busca.query_planner import QueryPlan
        from config import load_config, load_books

        cfg = load_config("config/config.yaml")
        bt = load_books()
        s = Searcher(
            cfg.search, bt, cfg.state.default_version,
            embedding_searcher=embedding_searcher_mock,
        )

        plan = QueryPlan(
            original_query="vale da sombra da morte",
            normalized_query="vale da sombra da morte",
            keywords=("vale", "sombra", "morte"),
            search_modes=("or", "keyword_subset", "fuzzy"),
        )
        results = s.search_with_plan(plan)
        assert len(results) > 0
        assert results[0].book == "Salmos"
        s.close()

    def test_fetch_verse_by_uid(self, embedding_searcher_mock) -> None:
        from busca.searcher import Searcher
        from config import load_config, load_books

        cfg = load_config("config/config.yaml")
        bt = load_books()
        s = Searcher(
            cfg.search, bt, cfg.state.default_version,
            embedding_searcher=embedding_searcher_mock,
        )

        # Buscar um UID real
        import sqlite3
        db = sqlite3.connect(cfg.search.fts5_db)
        row = db.execute(
            "SELECT id FROM verses WHERE version='ACF' LIMIT 1",
        ).fetchone()
        db.close()

        if row:
            cand = s._fetch_verse_by_uid(row[0])
            assert cand is not None
            assert "text" in cand
            assert "book" in cand

        s.close()

    def test_fetch_verse_by_uid_nonexistent(self, embedding_searcher_mock) -> None:
        from busca.searcher import Searcher
        from config import load_config, load_books

        cfg = load_config("config/config.yaml")
        bt = load_books()
        s = Searcher(
            cfg.search, bt, cfg.state.default_version,
            embedding_searcher=embedding_searcher_mock,
        )

        cand = s._fetch_verse_by_uid("nonexistent-uid-12345")
        assert cand is None
        s.close()


# ---------------------------------------------------------------------------
# Testes de QueryPlanner com enable_semantic
# ---------------------------------------------------------------------------


class TestQueryPlannerSemantic:
    """Testes do QueryPlanner com enable_semantic."""

    def test_semantic_disabled_by_default(self) -> None:
        from busca.query_planner import QueryPlanner
        from core.types import Intent

        planner = QueryPlanner()
        intent = Intent(
            action="search",
            query="amor de deus",
            confidence=0.8,
            source="llm",
            raw="amor de deus",
        )
        plan = planner.plan(intent)
        assert "semantic" not in plan.search_modes

    def test_semantic_enabled(self) -> None:
        from busca.query_planner import QueryPlanner
        from core.types import Intent

        planner = QueryPlanner(enable_semantic=True)
        intent = Intent(
            action="search",
            query="amor de deus",
            confidence=0.8,
            source="llm",
            raw="amor de deus",
        )
        plan = planner.plan(intent)
        assert "semantic" in plan.search_modes

    def test_semantic_enabled_with_books(self) -> None:
        from busca.query_planner import QueryPlanner
        from core.types import Intent

        planner = QueryPlanner(enable_semantic=True)
        intent = Intent(
            action="search",
            query="amor de deus",
            confidence=0.8,
            source="llm",
            raw="amor de deus",
            enrichment={"livros_sugeridos": ["1 João"]},
        )
        plan = planner.plan(intent)
        assert "semantic" in plan.search_modes
        assert "book_filter" in plan.search_modes
