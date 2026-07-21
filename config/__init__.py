"""Módulo de configuração.

API pública:
    load_config(path) -> Config
    load_books(path) -> BookTable
    Config, BookTable, Book, BookMatch, ConfigError
"""

from config.books import Book, BookMatch, BookTable
from config.loader import load_books, load_config
from config.models import (
    AudioConfig,
    CacheConfig,
    ConfidenceConfig,
    Config,
    HolyricsConfig,
    LLMConfig,
    LogConfig,
    OllamaConfig,
    SearchConfig,
    SemanticConfig,
    StateConfig,
    STTConfig,
    VadConfig,
)
from core.exceptions import ConfigError

__all__ = [
    "load_config",
    "load_books",
    "Config",
    "HolyricsConfig",
    "STTConfig",
    "VadConfig",
    "LLMConfig",
    "OllamaConfig",
    "SemanticConfig",
    "SearchConfig",
    "StateConfig",
    "CacheConfig",
    "ConfidenceConfig",
    "LogConfig",
    "AudioConfig",
    "Book",
    "BookMatch",
    "BookTable",
    "ConfigError",
]
