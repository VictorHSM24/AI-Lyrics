"""Dataclasses de configuração (imutáveis).

Todos os módulos recebem ``Config`` por injeção. Nenhum módulo deve
redefinir estes tipos nem ler YAML diretamente.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HolyricsConfig:
    """Configuração do cliente Holyrics."""

    base_url: str
    token: str
    timeout_ms: int


@dataclass(frozen=True)
class VadConfig:
    """Configuração do Voice Activity Detection."""

    mode: str  # "silero" | "webrtcvad"
    min_speech_ms: int
    pause_threshold_ms: int


@dataclass(frozen=True)
class STTConfig:
    """Configuração do Speech-to-Text.

    Campos:
        model: nome ou path do modelo (ex.: "large-v3-turbo", "small").
        device: dispositivo de inferência ("cuda", "cpu", "auto").
        compute_type: tipo de quantização ("float16", "int8_float16",
            "int8", "float32").
        language: código ISO do idioma ("pt", "en", "es").
        chunk_length_s: duração do chunk em segundos (30 padrão Whisper).
        vad: configuração do VAD interno do Whisper (não confundir com
            o VAD do microfone).
        backend: backend STT ("faster-whisper" — único suportado).
        beam_size: beam size para decoding (1 = greedy, 5 = beam search).
        vad_filter: se True, ativa VAD interno do Whisper para descartar
            silêncio antes da transcrição.
    """

    model: str
    device: str
    compute_type: str
    language: str
    chunk_length_s: int
    vad: VadConfig
    backend: str = "faster-whisper"
    beam_size: int = 1
    vad_filter: bool = False


@dataclass(frozen=True)
class LLMConfig:
    """Configuração do LLM (Ollama/llama.cpp)."""

    base_url: str
    model: str
    lazy_load: bool
    timeout_ms: int
    max_tokens: int


@dataclass(frozen=True)
class SearchConfig:
    """Configuração da busca híbrida (FTS5 + embeddings + RRF)."""

    fts5_db: str
    embeddings_path: str
    embedding_model: str
    embedding_device: str  # "cpu" | "cuda"
    rrf_k: int
    top_k: int
    search_gap: float


@dataclass(frozen=True)
class StateConfig:
    """Configuração do gerenciador de estado."""

    default_version: str
    persist_path: str


@dataclass(frozen=True)
class CacheConfig:
    """Configuração das camadas de cache."""

    recent_capacity: int
    embedding_capacity: int
    holyrics_ttl_s: int
    current_verse_ttl_s: int


@dataclass(frozen=True)
class ConfidenceConfig:
    """Limiares do Confidence Manager."""

    min_execute: float
    min_confirm: float
    stt_min: float
    parser_high: float
    parser_compact: float


@dataclass(frozen=True)
class LogConfig:
    """Configuração de logging."""

    path: str
    level: str


@dataclass(frozen=True)
class AudioConfig:
    """Configuração de captura de áudio do microfone.

    Campos:
        input_device: nome do dispositivo (match parcial case-insensitive)
            ou índice inteiro como string (ex.: "0").
        sample_rate: taxa de amostragem em Hz (ex.: 16000).
        channels: número de canais (1 = mono).
        chunk_ms: duração de cada chunk em milissegundos (10/20/30 para webrtcvad).
        vad_enabled: se True, aplica VAD para descartar silêncio.
        min_speech_ms: duração mínima de fala para emitir um segmento.
        max_silence_ms: silêncio máximo dentro da fala antes de finalizar o segmento.
        vad_mode: aggressividade do webrtcvad (0=menos, 3=mais).
        max_segment_ms: duração máxima de um segmento antes de flush forçado.
    """

    input_device: str
    sample_rate: int
    channels: int
    chunk_ms: int
    vad_enabled: bool
    min_speech_ms: int
    max_silence_ms: int
    vad_mode: int = 3
    max_segment_ms: int = 30_000


@dataclass(frozen=True)
class Config:
    """Configuração raiz do sistema. Imutável após carregamento."""

    holyrics: HolyricsConfig
    stt: STTConfig
    llm: LLMConfig
    search: SearchConfig
    state: StateConfig
    cache: CacheConfig
    confidence: ConfidenceConfig
    log: LogConfig
    mode: str  # "auto" | "confirm" | "quick"
    audio: AudioConfig | None = None  # opcional (backward-compatible)
