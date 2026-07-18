"""Testes unitários do indexador FTS5.

Cobre:
- build (importação incremental).
- rebuild (drop + create + import).
- idempotência (rebuild duas vezes não corrompe).
- múltiplas versões.
- filtragem por versão.
- validação (book_id fora de range, texto vazio, campos ausentes).
- estatísticas.
- busca FTS5 básica (sanity check do tokenizer).
- tratamento de erros (fonte ausente, JSON inválido).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from busca import BibleIndexer, IndexerError, IndexStats


# ---------------------------------------------------------------------------
# Dados de teste
# ---------------------------------------------------------------------------

SAMPLE_VERSES = [
    {"book": "Gênesis", "book_id": 1, "chapter": 1, "verse": 1,
     "text": "No princípio criou Deus os céus e a terra.", "version": "ACF"},
    {"book": "João", "book_id": 43, "chapter": 3, "verse": 16,
     "text": "Porque Deus amou o mundo de tal maneira que deu o seu Filho unigênito.",
     "version": "ACF"},
    {"book": "Romanos", "book_id": 45, "chapter": 8, "verse": 28,
     "text": "E sabemos que todas as coisas cooperam para o bem daqueles que amam a Deus.",
     "version": "ACF"},
    {"book": "Mateus", "book_id": 40, "chapter": 5, "verse": 13,
     "text": "Vós sois o sal da terra.", "version": "ACF"},
    {"book": "João", "book_id": 43, "chapter": 3, "verse": 16,
     "text": "Porque Deus amou o mundo de tal maneira que deu o seu Filho unigênito.",
     "version": "NVI"},
]

INVALID_VERSES = [
    {"book": "Inválido", "book_id": 99, "chapter": 1, "verse": 1,
     "text": "book_id fora de range", "version": "ACF"},
    {"book": "Vazio", "book_id": 1, "chapter": 1, "verse": 1,
     "text": "", "version": "ACF"},
    {"book": "SemTexto", "book_id": 2, "chapter": 1, "verse": 1,
     "version": "ACF"},  # falta 'text'
    {"book": "Bom", "book_id": 43, "chapter": 3, "verse": 16,
     "text": "Porque Deus amou o mundo.", "version": "ACF"},
]


def _write_json(path: Path, data: list[dict]) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def source_file(tmp_path: Path) -> Path:
    return _write_json(tmp_path / "bible_source.json", SAMPLE_VERSES)


@pytest.fixture
def invalid_source_file(tmp_path: Path) -> Path:
    return _write_json(tmp_path / "invalid.json", INVALID_VERSES)


@pytest.fixture
def indexer(tmp_path: Path) -> BibleIndexer:
    return BibleIndexer(str(tmp_path / "test.sqlite"))


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

class TestBuild:
    def test_build_creates_table_and_inserts(self, indexer: BibleIndexer, source_file: Path) -> None:
        stats = indexer.build(str(source_file))
        assert isinstance(stats, IndexStats)
        assert stats.total_verses == 5
        assert "ACF" in stats.versions
        assert "NVI" in stats.versions
        assert stats.verses_per_version["ACF"] == 4
        assert stats.verses_per_version["NVI"] == 1
        assert stats.skipped_invalid == 0
        assert stats.rebuilt is False
        assert os.path.isfile(stats.db_path)

    def test_build_creates_directory(self, tmp_path: Path, source_file: Path) -> None:
        db_path = tmp_path / "subdir" / "nested" / "test.sqlite"
        indexer = BibleIndexer(str(db_path))
        indexer.build(str(source_file))
        assert db_path.exists()

    def test_build_incremental(self, indexer: BibleIndexer, source_file: Path) -> None:
        """build sem rebuild=True adiciona à tabela existente."""
        indexer.build(str(source_file))
        # Segunda chamada sem rebuild — dobra as linhas.
        stats = indexer.build(str(source_file))
        assert stats.total_verses == 10

    def test_build_filtered_version(self, indexer: BibleIndexer, source_file: Path) -> None:
        stats = indexer.build(str(source_file), version="ACF")
        assert stats.total_verses == 4
        assert "NVI" not in stats.versions
        assert stats.versions == ["ACF"]

    def test_build_filtered_nvi(self, indexer: BibleIndexer, source_file: Path) -> None:
        stats = indexer.build(str(source_file), version="NVI")
        assert stats.total_verses == 1
        assert stats.versions == ["NVI"]


# ---------------------------------------------------------------------------
# rebuild
# ---------------------------------------------------------------------------

class TestRebuild:
    def test_rebuild_drops_and_recreates(self, indexer: BibleIndexer, source_file: Path) -> None:
        # Primeira importação.
        indexer.build(str(source_file))
        assert indexer.get_stats().total_verses == 5
        # Rebuild — tabela é dropada e recriada.
        stats = indexer.rebuild(str(source_file))
        assert stats.total_verses == 5
        assert stats.rebuilt is True

    def test_rebuild_idempotent(self, indexer: BibleIndexer, source_file: Path) -> None:
        """Rebuild duas vezes não corrompe dados."""
        stats1 = indexer.rebuild(str(source_file))
        stats2 = indexer.rebuild(str(source_file))
        assert stats1.total_verses == stats2.total_verses == 5
        assert stats1.versions == stats2.versions

    def test_rebuild_after_incremental(self, indexer: BibleIndexer, source_file: Path) -> None:
        """Incremental seguido de rebuild volta ao estado correto."""
        indexer.build(str(source_file))
        indexer.build(str(source_file))  # agora 10
        assert indexer.get_stats().total_verses == 10
        stats = indexer.rebuild(str(source_file))
        assert stats.total_verses == 5  # voltou ao normal


# ---------------------------------------------------------------------------
# add_version
# ---------------------------------------------------------------------------

class TestAddVersion:
    def test_add_version_to_existing(self, tmp_path: Path) -> None:
        acf_data = [v for v in SAMPLE_VERSES if v["version"] == "ACF"]
        nvi_data = [v for v in SAMPLE_VERSES if v["version"] == "NVI"]
        acf_file = _write_json(tmp_path / "acf.json", acf_data)
        nvi_file = _write_json(tmp_path / "nvi.json", nvi_data)
        idx = BibleIndexer(str(tmp_path / "test.sqlite"))

        # Importa ACF primeiro.
        idx.build(str(acf_file))
        assert idx.get_stats().versions == ["ACF"]

        # Adiciona NVI.
        stats = idx.add_version(str(nvi_file), version="NVI")
        assert "NVI" in stats.versions
        assert stats.verses_per_version["NVI"] == 1
        assert stats.verses_per_version["ACF"] == 4


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------

class TestValidation:
    def test_skip_invalid_book_id(self, indexer: BibleIndexer, invalid_source_file: Path) -> None:
        stats = indexer.build(str(invalid_source_file))
        # 3 inválidos (book_id 99, texto vazio, falta 'text'), 1 válido.
        assert stats.skipped_invalid == 3
        assert stats.total_verses == 1

    def test_skip_book_id_zero(self, tmp_path: Path) -> None:
        data = [
            {"book": "Bad", "book_id": 0, "chapter": 1, "verse": 1,
             "text": "zero", "version": "ACF"},
            {"book": "Good", "book_id": 1, "chapter": 1, "verse": 1,
             "text": "ok", "version": "ACF"},
        ]
        src = _write_json(tmp_path / "src.json", data)
        idx = BibleIndexer(str(tmp_path / "test.sqlite"))
        stats = idx.build(str(src))
        assert stats.skipped_invalid == 1
        assert stats.total_verses == 1

    def test_skip_book_id_67(self, tmp_path: Path) -> None:
        data = [
            {"book": "Bad", "book_id": 67, "chapter": 1, "verse": 1,
             "text": "over", "version": "ACF"},
        ]
        src = _write_json(tmp_path / "src.json", data)
        idx = BibleIndexer(str(tmp_path / "test.sqlite"))
        stats = idx.build(str(src))
        assert stats.skipped_invalid == 1
        assert stats.total_verses == 0

    def test_skip_whitespace_text(self, tmp_path: Path) -> None:
        data = [
            {"book": "Ws", "book_id": 1, "chapter": 1, "verse": 1,
             "text": "   ", "version": "ACF"},
        ]
        src = _write_json(tmp_path / "src.json", data)
        idx = BibleIndexer(str(tmp_path / "test.sqlite"))
        stats = idx.build(str(src))
        assert stats.skipped_invalid == 1


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_stats_after_build(self, indexer: BibleIndexer, source_file: Path) -> None:
        indexer.build(str(source_file))
        stats = indexer.get_stats()
        assert stats.total_verses == 5
        assert set(stats.versions) == {"ACF", "NVI"}
        assert stats.verses_per_version["ACF"] == 4

    def test_stats_no_db(self, tmp_path: Path) -> None:
        idx = BibleIndexer(str(tmp_path / "nonexistent.sqlite"))
        with pytest.raises(IndexerError, match="not found"):
            idx.get_stats()

    def test_stats_no_table(self, tmp_path: Path) -> None:
        db_path = tmp_path / "empty.sqlite"
        sqlite3.connect(str(db_path)).close()  # cria DB vazio
        idx = BibleIndexer(str(db_path))
        with pytest.raises(IndexerError, match="does not exist"):
            idx.get_stats()


# ---------------------------------------------------------------------------
# drop
# ---------------------------------------------------------------------------

class TestDrop:
    def test_drop_removes_table(self, indexer: BibleIndexer, source_file: Path) -> None:
        indexer.build(str(source_file))
        assert indexer.get_stats().total_verses == 5
        indexer.drop()
        with pytest.raises(IndexerError, match="does not exist"):
            indexer.get_stats()

    def test_drop_idempotent(self, indexer: BibleIndexer, source_file: Path) -> None:
        indexer.build(str(source_file))
        indexer.drop()
        indexer.drop()  # não deve erro


# ---------------------------------------------------------------------------
# FTS5 search (sanity check)
# ---------------------------------------------------------------------------

class TestFTS5Search:
    def test_search_deus_amou_mundo(self, indexer: BibleIndexer, source_file: Path) -> None:
        indexer.build(str(source_file))
        conn = sqlite3.connect(indexer._db_path)
        rows = conn.execute(
            "SELECT id, book, chapter, verse FROM verses "
            "WHERE verses MATCH 'deus amou o mundo' ORDER BY bm25(verses)"
        ).fetchall()
        conn.close()
        assert len(rows) > 0
        # João 3:16 deve estar no resultado (id 43003016).
        ids = [r[0] for r in rows]
        assert "43003016" in ids

    def test_search_sal_terra(self, indexer: BibleIndexer, source_file: Path) -> None:
        indexer.build(str(source_file))
        conn = sqlite3.connect(indexer._db_path)
        rows = conn.execute(
            "SELECT id FROM verses WHERE verses MATCH 'sal terra'"
        ).fetchall()
        conn.close()
        assert len(rows) > 0
        ids = [r[0] for r in rows]
        assert "40005013" in ids  # Mateus 5:13

    def test_search_with_diacritics_removed(self, indexer: BibleIndexer, source_file: Path) -> None:
        """Tokenizer remove_diacritics 2: buscar sem acentos deve funcionar."""
        indexer.build(str(source_file))
        conn = sqlite3.connect(indexer._db_path)
        # "cooperam" sem acento deve encontrar "cooperam" no texto.
        rows = conn.execute(
            "SELECT id FROM verses WHERE verses MATCH 'cooperam'"
        ).fetchall()
        conn.close()
        assert len(rows) > 0
        ids = [r[0] for r in rows]
        assert "45008028" in ids  # Romanos 8:28

    def test_search_filter_by_version(self, indexer: BibleIndexer, source_file: Path) -> None:
        indexer.build(str(source_file))
        conn = sqlite3.connect(indexer._db_path)
        rows = conn.execute(
            "SELECT id, version FROM verses WHERE verses MATCH 'deus' "
            "AND version = 'NVI'"
        ).fetchall()
        conn.close()
        assert len(rows) > 0
        assert all(r[1] == "NVI" for r in rows)


# ---------------------------------------------------------------------------
# Erros
# ---------------------------------------------------------------------------

class TestErrors:
    def test_source_not_found(self, indexer: BibleIndexer, tmp_path: Path) -> None:
        with pytest.raises(IndexerError, match="not found"):
            indexer.build(str(tmp_path / "nonexistent.json"))

    def test_invalid_json(self, indexer: BibleIndexer, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("[{invalid json", encoding="utf-8")
        with pytest.raises(IndexerError, match="invalid JSON"):
            indexer.build(str(bad))

    def test_root_not_list(self, indexer: BibleIndexer, tmp_path: Path) -> None:
        bad = tmp_path / "notlist.json"
        bad.write_text('{"key": "value"}', encoding="utf-8")
        with pytest.raises(IndexerError, match="must be a list"):
            indexer.build(str(bad))


# ---------------------------------------------------------------------------
# ID format
# ---------------------------------------------------------------------------

class TestIdFormat:
    def test_id_is_bbccc_vvv(self, indexer: BibleIndexer, source_file: Path) -> None:
        indexer.build(str(source_file))
        conn = sqlite3.connect(indexer._db_path)
        row = conn.execute(
            "SELECT id FROM verses WHERE book='João' AND chapter=3 AND verse=16 AND version='ACF'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "43003016"

    def test_id_single_digit_book(self, indexer: BibleIndexer, source_file: Path) -> None:
        indexer.build(str(source_file))
        conn = sqlite3.connect(indexer._db_path)
        row = conn.execute(
            "SELECT id FROM verses WHERE book='Gênesis' AND chapter=1 AND verse=1"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "01001001"
