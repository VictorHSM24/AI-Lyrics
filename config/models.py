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
        device: dispositivo de inferência ("cuda", "cpu", "auto",
            "directml", "rocm"). Sprint 19.1: "auto" seleciona
            automaticamente com base no hardware detectado.
        compute_type: tipo de quantização ("float16", "int8_float16",
            "int8", "float32", "auto"). Sprint 19.1: "auto" resolve
            com base no backend selecionado.
        language: código ISO do idioma ("pt", "en", "es").
        chunk_length_s: duração do chunk em segundos (30 padrão Whisper).
        vad: configuração do VAD interno do Whisper (não confundir com
            o VAD do microfone).
        backend: backend STT. Sprint 19.1 valores:
            - "faster-whisper" (legacy, mapeia para CPU/CUDA conforme device)
            - "auto" (seleção automática: CUDA > DirectML > ROCm > CPU)
            - "cuda" (força CUDA/NVIDIA via ctranslate2)
            - "directml" (força DirectML via onnxruntime-directml — AMD/Intel)
            - "rocm" (força ROCm — Linux AMD)
            - "cpu" (força CPU)
        beam_size: beam size para decoding (1 = greedy, 5 = beam search).
        vad_filter: se True, ativa VAD interno do Whisper para descartar
            silêncio antes da transcrição.
        cpu_threads: número de threads CPU (0 = default do sistema).
        gpu_memory_limit_mb: limite de VRAM em MB para GPU backends
            (0 = sem limite). Sprint 19.1.
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
    cpu_threads: int = 0  # 0 = default do faster-whisper (os.cpu_count())
    gpu_memory_limit_mb: int = 0  # Sprint 19.1: 0 = sem limite


@dataclass(frozen=True)
class LLMConfig:
    """Configuração do LLM (Ollama/llama.cpp)."""

    base_url: str
    model: str
    lazy_load: bool
    timeout_ms: int
    max_tokens: int


@dataclass(frozen=True)
class OllamaConfig:
    """Configuração do provider Ollama para o SemanticEngine (Sprint 21.1).

    Campos:
        enabled: se True, o provider tenta usar Ollama; se False, fallback stub.
        base_url: URL base OpenAI-compatible (geralmente ".../v1").
        api_key: API key enviada no header Authorization. Ollama aceita
            qualquer valor não-vazio quando auth está desligada. Use
            "ollama" por padrão.
        model: nome do modelo instalado no Ollama (ex.: "qwen3:8b-q4_K_M").
        temperature: temperatura da amostragem (recomendado 0.0-0.1).
        top_p: nucleus sampling (0.0-1.0).
        max_tokens: máximo de tokens na resposta.
        timeout_seconds: timeout HTTP em segundos.
        disable_thinking: se True, envia explicitamente "think": false no
            payload. Modelos sem suporte a esse parâmetro devem ignorá-lo
            silenciosamente.
    """

    enabled: bool
    base_url: str
    api_key: str
    model: str
    temperature: float
    top_p: float
    max_tokens: int
    timeout_seconds: float
    disable_thinking: bool = True


@dataclass(frozen=True)
class SemanticConfig:
    """Configuração da camada semântica (Sprint 21.1).

    Campos:
        provider: "stub" | "ollama" — seleciona qual provider instanciar
            no CompositionRoot.
        ollama: configuração específica do Ollama (usada quando
            provider == "ollama").
        debounce_ms: debounce antes de invocar o LLM após SpeechPartialUpdated.
            Sprint 21.5 — reduzido de 800ms para 400ms. Agora o gatilho
            principal é o crescimento significativo, não o debounce.
        timeout_ms: timeout da inferência semântica.
        min_text_length: mínimo de caracteres para invocar o LLM.
        enabled: kill switch global para a camada semântica.
        min_growth_chars: Sprint 21.5 — mínimo de caracteres novos desde
            a última inferência para disparar durante fala contínua.
        min_append_words: Sprint 21.5 — mínimo de palavras novas desde
            a última inferência (filtra filler).
        min_interval_ms: Sprint 21.5 — intervalo mínimo entre chamadas
            (rate limit).
        rag: Sprint 22.2 — limiares da ContextPolicy (priorização RAG).
        context: Sprint 22.2 — limiares de confiança do SermonMemory
            para inclusão/ remoção do current_book no prompt.
    """

    provider: str
    ollama: OllamaConfig
    debounce_ms: int = 400  # Sprint 21.5 — era 800, agora 400
    timeout_ms: int = 5000
    min_text_length: int = 8
    enabled: bool = True
    # Sprint 21.5 — Streaming Intelligence.
    min_growth_chars: int = 20
    min_append_words: int = 3
    min_interval_ms: int = 1000
    # Sprint 22.2 — Priorização RAG e política de contexto.
    rag: "RagPolicyConfig | None" = None
    context: "SermonContextPolicyConfig | None" = None


@dataclass(frozen=True)
class RagPolicyConfig:
    """Sprint 22.2 — Limiares da ContextPolicy para priorização RAG.

    Princípio: quando há candidato dominante (top1 com score alto e
    gap grande vs top2), o contexto do sermão é omitido do prompt.
    O contexto só é incluído para desambiguação entre candidatos
    próximos.

    Campos:
        dominant_score: score mínimo do top1 para classificar como
            "alta confiança" (candidato dominante). Default 0.98.
        dominant_gap: diferença mínima top1-top2 para classificar
            como "alta confiança". gap >= dominant_gap → contexto
            omitido. Default 0.08.
        ambiguity_gap: diferença abaixo da qual dois candidatos são
            considerados empatados (alta ambiguidade) → contexto
            completo incluído. Default 0.03.
    """

    dominant_score: float = 0.98
    dominant_gap: float = 0.08
    ambiguity_gap: float = 0.03


@dataclass(frozen=True)
class SermonContextPolicyConfig:
    """Sprint 22.2 — Limiares de confiança do SermonMemory.

    Campos:
        min_confidence: confiança mínima do SermonMemory para incluir
            current_book no prompt em qualquer nível. Abaixo disso,
            contexto sempre omitido. Default 0.40.
        remove_when_confidence_below: limiar abaixo do qual o
            SermonMemory deve zerar current_book/current_chapter.
            Sprint 22.3 implementará a heurística dinâmica; por ora,
            apenas reservado para uso pela infraestrutura mínima.
            Default 0.25.
    """

    min_confidence: float = 0.40
    remove_when_confidence_below: float = 0.25


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
class TelemetryConfig:
    """Sprint 21.9 — Configuração da telemetria de observabilidade.

    Campos:
        enabled: se True, habilita a gravação de eventos em .jsonl.
        output_dir: diretório base para gravação. Será criada uma
            subpasta session_<timestamp> dentro dele. Se vazio,
            usa default (~/AI_Lyrics_telemetry).
    """

    enabled: bool = True
    output_dir: str = ""


@dataclass(frozen=True)
class KnowledgeConfig:
    """Sprint 22.0 — Configuração do BibleRetriever (RAG Local).

    Campos:
        enabled: se True, ativa o modo RAG Local (BibleRetriever →
            SemanticEngine). Se False, usa o Modo Atual (LLM direto).
            Permite testes A/B entre as duas arquiteturas.
        sources_dir: diretório com as bases .sqlite (default: data/sources).
        top_k: número máximo de candidatos a recuperar e enviar ao LLM.
        fallback_on_empty: se True, e o BibleRetriever retornar 0
            candidatos, o SemanticEngine cai para o comportamento
            atual (LLM direto sem candidatos). Se False, e 0
            candidatos, o SemanticEngine retorna intent="none".
        warmup: se True, executa o warm-up do BibleRetriever no startup.
    """

    enabled: bool = False
    sources_dir: str = "data/sources"
    top_k: int = 20
    fallback_on_empty: bool = True
    warmup: bool = True


@dataclass(frozen=True)
class ReadingFollowConfig:
    """Sprint 23.2 — Configuração do modo de acompanhamento de leitura.

    Campos:
        fuzzy_threshold: similaridade mínima (0.0-1.0) para considerar
            que o versículo foi lido (default 0.70).
        auto_version_change: se True, comandos de voz mudam a versão
            automaticamente (default True). O operador pode desabilitar
            via frontend.
    """

    fuzzy_threshold: float = 0.70
    auto_version_change: bool = True


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
    # Sprint 21.1 — Semantic Engine config (opcional p/ backward-compatible).
    semantic: "SemanticConfig | None" = None
    # Sprint 21.9 — Telemetria de observabilidade (opcional).
    telemetry: "TelemetryConfig | None" = None
    # Sprint 22.0 — Bible Knowledge Base RAG Local (opcional).
    knowledge: "KnowledgeConfig | None" = None
    # Sprint 23.2 — Reading Follow Mode (opcional).
    reading_follow: "ReadingFollowConfig | None" = None
