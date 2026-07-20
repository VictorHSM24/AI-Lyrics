"""Funções de carregamento de configuração e tabela de livros.

Lê ``config.yaml`` (com substituição de ``${VAR}`` por env vars) e
``books.json`` (tabela canônica de 66 livros). Valida campos obrigatórios
e retorna objetos imutáveis.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import yaml

from config.books import Book, BookTable
from config.models import (
    AudioConfig,
    CacheConfig,
    ConfidenceConfig,
    Config,
    HolyricsConfig,
    LLMConfig,
    LogConfig,
    SearchConfig,
    StateConfig,
    STTConfig,
    VadConfig,
)
from core.exceptions import ConfigError

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _substitute_env(value: str, path_hint: str) -> str:
    """Substitui ``${VAR}`` em ``value`` por ``os.environ[VAR]``.

    Levanta ``ConfigError`` se a variável não estiver definida.
    """

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        env_val = os.environ.get(var_name)
        if env_val is None:
            raise ConfigError(
                f"environment variable '{var_name}' not set "
                f"(referenced in config: {path_hint})"
            )
        return env_val

    return _ENV_VAR_PATTERN.sub(_replace, value)


def _substitute_env_recursive(data: Any, path_hint: str = "") -> Any:
    """Aplica ``_substitute_env`` recursivamente em strings dentro de ``data``."""
    if isinstance(data, str):
        return _substitute_env(data, path_hint)
    if isinstance(data, dict):
        return {
            k: _substitute_env_recursive(v, f"{path_hint}.{k}" if path_hint else k)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_substitute_env_recursive(v, path_hint) for v in data]
    return data


def _require(data: dict[str, Any], key: str, path: str) -> Any:
    """Exige ``key`` em ``data`` ou levanta ``ConfigError``."""
    if key not in data:
        raise ConfigError(f"missing required field '{path}.{key}'")
    return data[key]


def _build_holyrics(data: dict[str, Any]) -> HolyricsConfig:
    base_url = _require(data, "base_url", "holyrics")
    token = _require(data, "token", "holyrics")
    timeout_ms = _require(data, "timeout_ms", "holyrics")
    return HolyricsConfig(base_url=base_url, token=token, timeout_ms=int(timeout_ms))


def _build_vad(data: dict[str, Any]) -> VadConfig:
    mode = _require(data, "mode", "stt.vad")
    min_speech_ms = _require(data, "min_speech_ms", "stt.vad")
    pause_threshold_ms = _require(data, "pause_threshold_ms", "stt.vad")
    return VadConfig(
        mode=str(mode),
        min_speech_ms=int(min_speech_ms),
        pause_threshold_ms=int(pause_threshold_ms),
    )


def _build_stt(data: dict[str, Any]) -> STTConfig:
    model = _require(data, "model", "stt")
    device = _require(data, "device", "stt")
    compute_type = _require(data, "compute_type", "stt")
    language = _require(data, "language", "stt")
    chunk_length_s = _require(data, "chunk_length_s", "stt")
    vad_data = _require(data, "vad", "stt")
    backend = data.get("backend", "faster-whisper")
    beam_size = data.get("beam_size", 1)
    vad_filter = data.get("vad_filter", False)
    cpu_threads = data.get("cpu_threads", 0)
    valid_backends = {"faster-whisper"}
    if str(backend) not in valid_backends:
        raise ConfigError(
            f"invalid stt.backend '{backend}' (valid: {sorted(valid_backends)})"
        )
    return STTConfig(
        model=str(model),
        device=str(device),
        compute_type=str(compute_type),
        language=str(language),
        chunk_length_s=int(chunk_length_s),
        vad=_build_vad(vad_data),
        backend=str(backend),
        beam_size=int(beam_size),
        vad_filter=bool(vad_filter),
        cpu_threads=int(cpu_threads),
    )


def _build_llm(data: dict[str, Any]) -> LLMConfig:
    base_url = _require(data, "base_url", "llm")
    model = _require(data, "model", "llm")
    lazy_load = _require(data, "lazy_load", "llm")
    timeout_ms = _require(data, "timeout_ms", "llm")
    max_tokens = _require(data, "max_tokens", "llm")
    return LLMConfig(
        base_url=str(base_url),
        model=str(model),
        lazy_load=bool(lazy_load),
        timeout_ms=int(timeout_ms),
        max_tokens=int(max_tokens),
    )


def _build_search(data: dict[str, Any]) -> SearchConfig:
    fts5_db = _require(data, "fts5_db", "search")
    embeddings_path = _require(data, "embeddings_path", "search")
    embedding_model = _require(data, "embedding_model", "search")
    embedding_device = _require(data, "embedding_device", "search")
    rrf_k = _require(data, "rrf_k", "search")
    top_k = _require(data, "top_k", "search")
    search_gap = _require(data, "search_gap", "search")
    return SearchConfig(
        fts5_db=str(fts5_db),
        embeddings_path=str(embeddings_path),
        embedding_model=str(embedding_model),
        embedding_device=str(embedding_device),
        rrf_k=int(rrf_k),
        top_k=int(top_k),
        search_gap=float(search_gap),
    )


def _build_state(data: dict[str, Any]) -> StateConfig:
    default_version = _require(data, "default_version", "state")
    persist_path = _require(data, "persist_path", "state")
    return StateConfig(
        default_version=str(default_version),
        persist_path=str(persist_path),
    )


def _build_cache(data: dict[str, Any]) -> CacheConfig:
    recent_capacity = _require(data, "recent_capacity", "cache")
    embedding_capacity = _require(data, "embedding_capacity", "cache")
    holyrics_ttl_s = _require(data, "holyrics_ttl_s", "cache")
    current_verse_ttl_s = _require(data, "current_verse_ttl_s", "cache")
    return CacheConfig(
        recent_capacity=int(recent_capacity),
        embedding_capacity=int(embedding_capacity),
        holyrics_ttl_s=int(holyrics_ttl_s),
        current_verse_ttl_s=int(current_verse_ttl_s),
    )


def _build_confidence(data: dict[str, Any]) -> ConfidenceConfig:
    min_execute = _require(data, "min_execute", "confidence")
    min_confirm = _require(data, "min_confirm", "confidence")
    stt_min = _require(data, "stt_min", "confidence")
    parser_high = _require(data, "parser_high", "confidence")
    parser_compact = _require(data, "parser_compact", "confidence")
    return ConfidenceConfig(
        min_execute=float(min_execute),
        min_confirm=float(min_confirm),
        stt_min=float(stt_min),
        parser_high=float(parser_high),
        parser_compact=float(parser_compact),
    )


def _build_log(data: dict[str, Any]) -> LogConfig:
    path = _require(data, "path", "log")
    level = _require(data, "level", "log")
    return LogConfig(path=str(path), level=str(level))


def _build_audio(data: dict[str, Any]) -> AudioConfig:
    input_device = _require(data, "input_device", "audio")
    sample_rate = _require(data, "sample_rate", "audio")
    channels = _require(data, "channels", "audio")
    chunk_ms = _require(data, "chunk_ms", "audio")
    vad_enabled = _require(data, "vad_enabled", "audio")
    min_speech_ms = _require(data, "min_speech_ms", "audio")
    max_silence_ms = _require(data, "max_silence_ms", "audio")
    vad_mode = data.get("vad_mode", 3)
    max_segment_ms = data.get("max_segment_ms", 30_000)
    valid_chunk_ms = {10, 20, 30}
    if int(chunk_ms) not in valid_chunk_ms:
        raise ConfigError(
            f"audio.chunk_ms must be one of {sorted(valid_chunk_ms)}, got {chunk_ms}"
        )
    if not (0 <= int(vad_mode) <= 3):
        raise ConfigError(f"audio.vad_mode must be 0..3, got {vad_mode}")
    return AudioConfig(
        input_device=str(input_device),
        sample_rate=int(sample_rate),
        channels=int(channels),
        chunk_ms=int(chunk_ms),
        vad_enabled=bool(vad_enabled),
        min_speech_ms=int(min_speech_ms),
        max_silence_ms=int(max_silence_ms),
        vad_mode=int(vad_mode),
        max_segment_ms=int(max_segment_ms),
    )


def _build_config(data: dict[str, Any]) -> Config:
    """Constrói ``Config`` imutável a partir de dict parseado do YAML."""
    holyrics = _build_holyrics(_require(data, "holyrics", "root"))
    stt = _build_stt(_require(data, "stt", "root"))
    llm = _build_llm(_require(data, "llm", "root"))
    search = _build_search(_require(data, "search", "root"))
    state = _build_state(_require(data, "state", "root"))
    cache = _build_cache(_require(data, "cache", "root"))
    confidence = _build_confidence(_require(data, "confidence", "root"))
    log = _build_log(_require(data, "log", "root"))
    mode = str(_require(data, "mode", "root"))
    valid_modes = {"auto", "confirm", "quick"}
    if mode not in valid_modes:
        raise ConfigError(
            f"invalid mode '{mode}' (valid: {sorted(valid_modes)})"
        )
    # audio é opcional (backward-compatible)
    audio: AudioConfig | None = None
    if "audio" in data:
        audio = _build_audio(data["audio"])
    return Config(
        holyrics=holyrics,
        stt=stt,
        llm=llm,
        search=search,
        state=state,
        cache=cache,
        confidence=confidence,
        log=log,
        mode=mode,
        audio=audio,
    )


def load_config(path: str = "config/config.yaml") -> Config:
    """Carrega ``config.yaml``, substitui ``${VAR}``, valida e retorna ``Config``.

    Args:
        path: caminho para o arquivo YAML.

    Returns:
        ``Config`` imutável.

    Raises:
        ConfigError: arquivo ausente, YAML inválido, campo obrigatório faltando,
            env var não definida, ou valor inválido.
    """
    if not os.path.isfile(path):
        raise ConfigError(f"config file not found: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be a mapping, got {type(raw).__name__}")
    substituted = _substitute_env_recursive(raw)
    return _build_config(substituted)


def load_books(path: str = "config/books.json") -> BookTable:
    """Carrega ``books.json`` e retorna ``BookTable``.

    Args:
        path: caminho para o arquivo JSON.

    Returns:
        ``BookTable`` com os 66 livros e aliases normalizadas.

    Raises:
        ConfigError: arquivo ausente, JSON inválido, schema incorreto.
    """
    if not os.path.isfile(path):
        raise ConfigError(f"books file not found: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"invalid JSON in {path}: {e}") from e
    if not isinstance(raw, list):
        raise ConfigError(f"books root must be a list, got {type(raw).__name__}")
    books: list[Book] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ConfigError(f"books[{i}] must be an object, got {type(entry).__name__}")
        if "id" not in entry or "canonical" not in entry or "aliases" not in entry:
            raise ConfigError(
                f"books[{i}] missing required field (id, canonical, aliases)"
            )
        book_id = entry["id"]
        canonical = entry["canonical"]
        aliases = entry["aliases"]
        if not isinstance(book_id, int) or not (1 <= book_id <= 66):
            raise ConfigError(
                f"books[{i}].id must be int in 1..66, got {book_id!r}"
            )
        if not isinstance(canonical, str) or not canonical:
            raise ConfigError(f"books[{i}].canonical must be non-empty string")
        if not isinstance(aliases, list) or not all(
            isinstance(a, str) for a in aliases
        ):
            raise ConfigError(f"books[{i}].aliases must be list of strings")
        priority = entry.get("priority", 0)
        if not isinstance(priority, int):
            raise ConfigError(
                f"books[{i}].priority must be int, got {type(priority).__name__}"
            )
        books.append(Book(id=book_id, canonical=canonical, aliases=list(aliases), priority=priority))
    if len(books) != 66:
        raise ConfigError(f"expected 66 books, got {len(books)}")
    return BookTable(books)
