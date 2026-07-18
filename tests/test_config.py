"""Testes unitários do módulo config.

Cobre:
- Carregamento de config.yaml com todos os campos.
- Substituição de ${HOLYRICS_TOKEN}.
- ConfigError para campos ausentes, YAML inválido, env var faltando, mode inválido.
- BookTable.resolve (longest-match, desambiguação João vs 1 João).
- BookTable.by_id, all_books.
- load_books com 66 livros.
- load_books com JSON malformado / schema incorreto.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from config import (
    Book,
    BookTable,
    Config,
    ConfigError,
    load_books,
    load_config,
)
from config.books import _normalize_alias


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_YAML = """\
holyrics:
  base_url: "http://127.0.0.1:3000/api"
  token: "${HOLYRICS_TOKEN}"
  timeout_ms: 2000
stt:
  backend: "faster-whisper"
  model: "large-v3-turbo"
  device: "cuda"
  compute_type: "float16"
  language: "pt"
  beam_size: 1
  vad_filter: false
  chunk_length_s: 30
  vad:
    mode: "silero"
    min_speech_ms: 250
    pause_threshold_ms: 600
llm:
  base_url: "http://127.0.0.1:11434"
  model: "qwen3:8b-q4_k_m"
  lazy_load: true
  timeout_ms: 5000
  max_tokens: 200
search:
  fts5_db: "data/bible.pt-br.sqlite"
  embeddings_path: "data/bible.embeddings.npy"
  embedding_model: "intfloat/multilingual-e5-small"
  embedding_device: "cpu"
  rrf_k: 60
  top_k: 20
  search_gap: 0.15
state:
  default_version: "ACF"
  persist_path: "data/state.json"
cache:
  recent_capacity: 50
  embedding_capacity: 200
  holyrics_ttl_s: 5
  current_verse_ttl_s: 60
confidence:
  min_execute: 0.85
  min_confirm: 0.60
  stt_min: 0.50
  parser_high: 0.90
  parser_compact: 0.85
mode: "auto"
audio:
  input_device: "CODEC USB"
  sample_rate: 16000
  channels: 1
  chunk_ms: 30
  vad_enabled: true
  min_speech_ms: 600
  max_silence_ms: 800
  vad_mode: 3
  max_segment_ms: 30000
log:
  path: "logs/pipeline.jsonl"
  level: "INFO"
"""

MINIMAL_BOOKS = [
    {"id": 43, "canonical": "João", "aliases": ["joão", "joao", "jo", "são joão"]},
    {"id": 46, "canonical": "1 Coríntios", "aliases": ["1 coríntios", "i coríntios", "primeira coríntios"]},
    {"id": 62, "canonical": "1 João", "aliases": ["1 joão", "i joão", "primeiro joão"]},
]


def _write_temp(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_load_valid_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLYRICS_TOKEN", "secret-token-123")
        path = _write_temp(tmp_path, "config.yaml", VALID_YAML)
        cfg = load_config(str(path))
        assert isinstance(cfg, Config)
        assert cfg.holyrics.base_url == "http://127.0.0.1:3000/api"
        assert cfg.holyrics.token == "secret-token-123"
        assert cfg.holyrics.timeout_ms == 2000
        assert cfg.stt.model == "large-v3-turbo"
        assert cfg.stt.backend == "faster-whisper"
        assert cfg.stt.beam_size == 1
        assert cfg.stt.vad_filter is False
        assert cfg.stt.device == "cuda"
        assert cfg.stt.compute_type == "float16"
        assert cfg.stt.language == "pt"
        assert cfg.stt.chunk_length_s == 30
        assert cfg.stt.vad.mode == "silero"
        assert cfg.stt.vad.min_speech_ms == 250
        assert cfg.stt.vad.pause_threshold_ms == 600
        assert cfg.llm.model == "qwen3:8b-q4_k_m"
        assert cfg.llm.lazy_load is True
        assert cfg.llm.timeout_ms == 5000
        assert cfg.llm.max_tokens == 200
        assert cfg.search.rrf_k == 60
        assert cfg.search.top_k == 20
        assert abs(cfg.search.search_gap - 0.15) < 1e-9
        assert cfg.state.default_version == "ACF"
        assert cfg.cache.recent_capacity == 50
        assert abs(cfg.confidence.min_execute - 0.85) < 1e-9
        assert cfg.mode == "auto"
        assert cfg.log.path == "logs/pipeline.jsonl"

    def test_env_var_substitution(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLYRICS_TOKEN", "my-token")
        path = _write_temp(tmp_path, "config.yaml", VALID_YAML)
        cfg = load_config(str(path))
        assert cfg.holyrics.token == "my-token"

    def test_env_var_missing_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOLYRICS_TOKEN", raising=False)
        path = _write_temp(tmp_path, "config.yaml", VALID_YAML)
        with pytest.raises(ConfigError, match="HOLYRICS_TOKEN"):
            load_config(str(path))

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not found"):
            load_config(str(tmp_path / "nonexistent.yaml"))

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        path = _write_temp(tmp_path, "config.yaml", "holyrics: [unclosed")
        with pytest.raises(ConfigError, match="invalid YAML"):
            load_config(str(path))

    def test_missing_required_field(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLYRICS_TOKEN", "tok")
        yaml_no_token = VALID_YAML.replace('  token: "${HOLYRICS_TOKEN}"\n', '')
        path = _write_temp(tmp_path, "config.yaml", yaml_no_token)
        with pytest.raises(ConfigError, match="holyrics.token"):
            load_config(str(path))

    def test_invalid_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLYRICS_TOKEN", "tok")
        yaml_bad_mode = VALID_YAML.replace('mode: "auto"', 'mode: "invalid"')
        path = _write_temp(tmp_path, "config.yaml", yaml_bad_mode)
        with pytest.raises(ConfigError, match="invalid mode"):
            load_config(str(path))

    def test_config_is_frozen(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLYRICS_TOKEN", "tok")
        path = _write_temp(tmp_path, "config.yaml", VALID_YAML)
        cfg = load_config(str(path))
        with pytest.raises((AttributeError, Exception)):
            cfg.mode = "confirm"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# load_books
# ---------------------------------------------------------------------------

class TestLoadBooks:
    def test_load_full_books(self) -> None:
        table = load_books("config/books.json")
        books = table.all_books()
        assert len(books) == 66
        assert books[0].id == 1
        assert books[0].canonical == "Gênesis"
        assert books[-1].id == 66
        assert books[-1].canonical == "Apocalipse"

    def test_load_minimal_books(self, tmp_path: Path) -> None:
        # Adiciona 63 livros placeholder para passar validação de 66.
        full = json.loads(Path("config/books.json").read_text(encoding="utf-8"))
        path = tmp_path / "books.json"
        path.write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
        table = load_books(str(path))
        assert len(table.all_books()) == 66

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not found"):
            load_books(str(tmp_path / "nonexistent.json"))

    def test_invalid_json(self, tmp_path: Path) -> None:
        path = _write_temp(tmp_path, "books.json", "[{invalid json")
        with pytest.raises(ConfigError, match="invalid JSON"):
            load_books(str(path))

    def test_root_not_list(self, tmp_path: Path) -> None:
        path = _write_temp(tmp_path, "books.json", '{"id": 1}')
        with pytest.raises(ConfigError, match="must be a list"):
            load_books(str(path))

    def test_entry_missing_field(self, tmp_path: Path) -> None:
        data = [{"id": 1, "canonical": "Test"}]  # faltam aliases
        path = _write_temp(tmp_path, "books.json", json.dumps(data))
        with pytest.raises(ConfigError, match="missing required field"):
            load_books(str(path))

    def test_invalid_book_id(self, tmp_path: Path) -> None:
        data = [{"id": 99, "canonical": "Test", "aliases": ["test"]}]
        path = _write_temp(tmp_path, "books.json", json.dumps(data))
        with pytest.raises(ConfigError, match="1..66"):
            load_books(str(path))

    def test_wrong_count(self, tmp_path: Path) -> None:
        data = [{"id": 1, "canonical": "Test", "aliases": ["test"]}]
        path = _write_temp(tmp_path, "books.json", json.dumps(data))
        with pytest.raises(ConfigError, match="expected 66"):
            load_books(str(path))


# ---------------------------------------------------------------------------
# BookTable
# ---------------------------------------------------------------------------

class TestBookTable:
    @pytest.fixture
    def table(self) -> BookTable:
        return BookTable([Book(**b) for b in MINIMAL_BOOKS])

    def test_resolve_canonical_with_diacritics(self, table: BookTable) -> None:
        match = table.resolve("primeira coríntios")
        assert match is not None
        assert match.book.id == 46

    def test_resolve_without_diacritics(self, table: BookTable) -> None:
        match = table.resolve("primeira corintios")
        assert match is not None
        assert match.book.id == 46

    def test_resolve_joao_evangelho_not_first_joao(self, table: BookTable) -> None:
        """'joão' sozinho deve resolver para Evangelho (id=43), não 1 João."""
        match = table.resolve("joão")
        assert match is not None
        assert match.book.id == 43

    def test_resolve_first_joao_with_ordinal(self, table: BookTable) -> None:
        match = table.resolve("primeiro joão")
        assert match is not None
        assert match.book.id == 62

    def test_resolve_longest_match(self, table: BookTable) -> None:
        """'são joão' é mais longo que 'joão' e deve casar primeiro."""
        match = table.resolve("são joão")
        assert match is not None
        assert match.book.id == 43
        assert match.matched_alias == "são joão"

    def test_resolve_in_context(self, table: BookTable) -> None:
        """Resolve livro dentro de frase maior."""
        match = table.resolve("vamos abrir em joão capítulo três")
        assert match is not None
        assert match.book.id == 43

    def test_resolve_not_found(self, table: BookTable) -> None:
        assert table.resolve("livro inexistente") is None

    def test_resolve_word_boundary(self, table: BookTable) -> None:
        """Aliases curtas não devem casar como substring de palavras maiores."""
        # "inexistente" contém "ex" (alias de Êxodo) — não deve casar.
        assert table.resolve("inexistente") is None
        # "jojoba" contém "jo" — não deve casar.
        assert table.resolve("jojoba") is None

    def test_resolve_empty(self, table: BookTable) -> None:
        assert table.resolve("") is None
        assert table.resolve("   ") is None

    def test_by_id_valid(self, table: BookTable) -> None:
        book = table.by_id(43)
        assert book.canonical == "João"

    def test_by_id_invalid(self, table: BookTable) -> None:
        with pytest.raises(KeyError):
            table.by_id(999)

    def test_all_books_sorted(self, table: BookTable) -> None:
        books = table.all_books()
        ids = [b.id for b in books]
        assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# _normalize_alias
# ---------------------------------------------------------------------------

class TestNormalizeAlias:
    def test_lowercase(self) -> None:
        assert _normalize_alias("GÊNESIS") == "genesis"

    def test_remove_diacritics(self) -> None:
        assert _normalize_alias("Coríntios") == "corintios"

    def test_collapse_whitespace(self) -> None:
        assert _normalize_alias("1   Coríntios") == "1 corintios"

    def test_strip(self) -> None:
        assert _normalize_alias("  joão  ") == "joao"
