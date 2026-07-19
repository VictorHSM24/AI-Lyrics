"""Composition root — inicializa Core + Presentation Layer.

Este módulo é o ÚNICO lugar que conhece tanto o Core quanto a
Presentation Layer. Ele constrói as dependências e as injeta nos
Presentation Services.

A API FastAPI cons apenas as Presentation Services — nunca o Core.

Sprint 14: carrega config real (config.yaml + overrides) e instancia
AudioPresentationService, SystemPresentationService e
InfoPresentationService.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from pipeline import (
    MemoryEventStore,
    PipelineEventBus,
    PipelineMetrics,
    PipelinePolicy,
    PipelineSession,
    PipelineState,
)
from presentation import (
    AudioPresentationService,
    ConfigurationPresentationService,
    DiagnosticPresentationService,
    EventPresentationService,
    HealthPresentationService,
    InfoPresentationService,
    MetricsPresentationService,
    PipelinePresentationService,
    SessionPresentationService,
    SystemPresentationService,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CompositionRoot — contêiner de dependências.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompositionRoot:
    """Bundle imutável com todas as dependências inicializadas.

    A API consome apenas este objeto — nunca o Core diretamente.
    """

    # Core (não exposto diretamente à API).
    bus: PipelineEventBus
    store: MemoryEventStore
    state: PipelineState
    session: PipelineSession
    metrics: PipelineMetrics
    policy: PipelinePolicy

    # Config (carregada de config.yaml + overrides).
    config: Any

    # Presentation Services (expostos à API).
    pipeline_service: PipelinePresentationService
    session_service: SessionPresentationService
    metrics_service: MetricsPresentationService
    configuration_service: ConfigurationPresentationService
    health_service: HealthPresentationService
    diagnostic_service: DiagnosticPresentationService
    event_service: EventPresentationService
    audio_service: AudioPresentationService
    system_service: SystemPresentationService
    info_service: InfoPresentationService

    # Sprint 15.1 — Audio Capture
    audio_capture: Any  # AudioCaptureService


# ---------------------------------------------------------------------------
# Factory — cria o CompositionRoot.
# ---------------------------------------------------------------------------


def create_composition_root() -> CompositionRoot:
    """Cria e conecta todas as dependências do sistema.

    Ordem:
      1. Carrega config (config.yaml + overrides).
      2. Core (EventStore → EventBus → State/Session/Metrics/Policy).
      3. Presentation Services (recebem referências do Core + config).
    """
    # 1. Carregar config real.
    config = _load_config()

    # 2. Core
    store = MemoryEventStore()
    bus = PipelineEventBus(store=store)
    state = PipelineState()
    session = PipelineSession.create(session_id="session-api-default")
    metrics = PipelineMetrics()
    policy = PipelinePolicy()

    # 3. Presentation Services
    pipeline_service = PipelinePresentationService(
        state=state, session=session, metrics=metrics, bus=bus,
    )
    session_service = SessionPresentationService(session=session)
    metrics_service = MetricsPresentationService(metrics=metrics)
    configuration_service = ConfigurationPresentationService(
        config=config, pipeline_policy=policy,
    )
    health_service = HealthPresentationService(
        pipeline_state=state, bus=bus, store=store,
        stt_config=getattr(config, "stt", None),
        search_config=getattr(config, "search", None),
        llm_config=getattr(config, "llm", None),
        holyrics_config=getattr(config, "holyrics", None),
        audio_config=getattr(config, "audio", None),
    )
    diagnostic_service = DiagnosticPresentationService(
        pipeline_state=state, bus=bus, store=store,
    )
    event_service = EventPresentationService(bus=bus)

    # Sprint 15.1 — AudioCaptureService + AudioPresentationService.
    from microfone.audio_capture_service import AudioCaptureService
    audio_config = getattr(config, "audio", None)
    audio_sr = getattr(audio_config, "sample_rate", 16000) if audio_config else 16000
    audio_ch = getattr(audio_config, "channels", 1) if audio_config else 1
    audio_capture = AudioCaptureService(
        sample_rate=int(audio_sr),
        channels=int(audio_ch),
        blocksize=int(audio_sr * 0.03),  # 30ms
        buffer_size=100,
    )
    audio_service = AudioPresentationService(
        audio_config=audio_config,
        capture_service=audio_capture,
    )

    # Sprint 15.2 — Conectar AudioCaptureService ao HealthService.
    health_service._audio_capture = audio_capture

    system_service = SystemPresentationService(
        log_dir=_config_value(config, "log", "path") or "logs",
        cache_dir="cache",
        data_dir="data",
    )
    info_service = InfoPresentationService(
        api_version=_get_api_version(),
        name="AI Lyrics API",
        version=_get_backend_version(),
        build_id=os.environ.get("AI_LYRICS_BUILD_ID", ""),
        commit=os.environ.get("AI_LYRICS_COMMIT", ""),
        build_date=os.environ.get("AI_LYRICS_BUILD_DATE", ""),
        frontend_version="0.1.0",
        sdk_compatibility="0.1.0",
    )

    return CompositionRoot(
        bus=bus,
        store=store,
        state=state,
        session=session,
        metrics=metrics,
        policy=policy,
        config=config,
        pipeline_service=pipeline_service,
        session_service=session_service,
        metrics_service=metrics_service,
        configuration_service=configuration_service,
        health_service=health_service,
        diagnostic_service=diagnostic_service,
        event_service=event_service,
        audio_service=audio_service,
        system_service=system_service,
        info_service=info_service,
        audio_capture=audio_capture,
    )


def _load_config() -> Any:
    """Carrega config de config.yaml + overrides.

    Tenta carregar config.yaml via config.loader.load_config().
    Se falhar (arquivo ausente, dependência faltando), cai para
    _minimal_config() com overrides aplicados.
    """
    from config.persistence import load_overrides, merge_overrides

    overrides = load_overrides()

    try:
        from config.loader import load_config
        config = load_config("config/config.yaml")
        # Se há overrides, aplicá-los criando uma nova config.
        if overrides:
            from types import SimpleNamespace
            from dataclasses import asdict
            base = asdict(config)
            merged = merge_overrides(base, overrides)
            # Re-construir via _build_config para validar.
            from config.loader import _build_config
            return _build_config(merged)
        return config
    except Exception as e:
        logger.warning("Failed to load config.yaml: %s — using minimal config", e)
        minimal = _minimal_config()
        if overrides:
            from types import SimpleNamespace
            base = vars(minimal).copy()
            merged = merge_overrides(base, overrides)
            def to_ns(d):
                if isinstance(d, dict):
                    return SimpleNamespace(**{k: to_ns(v) for k, v in d.items()})
                return d
            return to_ns(merged)
        return minimal


def _config_value(config: Any, *path: str, default: Any = None) -> Any:
    """Navega em config por atributos aninhados."""
    cur = config
    for p in path:
        cur = getattr(cur, p, None) if cur is not None else None
        if cur is None:
            return default
    return cur


def _get_api_version() -> Any:
    """Retorna a versão atual da API."""
    from api.schemas import CURRENT_API_VERSION
    return CURRENT_API_VERSION


def _get_backend_version() -> str:
    """Retorna a versão do backend (semver string)."""
    from api.schemas import CURRENT_API_VERSION
    v = CURRENT_API_VERSION
    base = f"{v.major}.{v.minor}.{v.patch}"
    if v.pre:
        return f"{base}-{v.pre}"
    return base


def _minimal_config() -> Any:
    """Configuração mínima fallback quando config.yaml não está disponível.

    Sprint 14: ainda usado como fallback, mas a config real é
    carregada de config.yaml quando possível.
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        mode="auto",
        holyrics=SimpleNamespace(
            base_url="http://127.0.0.1:8091/api",
            token="",
            timeout_ms=2000,
        ),
        stt=SimpleNamespace(
            backend="faster-whisper",
            model="large-v3-turbo",
            device="cuda",
            compute_type="float16",
            language="pt",
            beam_size=1,
            vad_filter=False,
            chunk_length_s=30,
            vad=SimpleNamespace(mode="silero", min_speech_ms=250, pause_threshold_ms=600),
        ),
        llm=SimpleNamespace(
            base_url="http://127.0.0.1:11434",
            model="qwen3:8b-q4_k_m",
            lazy_load=True,
            timeout_ms=15000,
            max_tokens=200,
        ),
        search=SimpleNamespace(
            fts5_db="data/bible.pt-br.sqlite",
            embeddings_path="data/bible.embeddings.npy",
            embedding_model="intfloat/multilingual-e5-small",
            embedding_device="cpu",
            rrf_k=60,
            top_k=20,
            search_gap=0.15,
        ),
        state=SimpleNamespace(
            default_version="ACF",
            persist_path="data/state.json",
        ),
        cache=SimpleNamespace(
            recent_capacity=50,
            embedding_capacity=200,
            holyrics_ttl_s=5,
            current_verse_ttl_s=60,
        ),
        confidence=SimpleNamespace(
            min_execute=0.30,
            min_confirm=0.20,
            stt_min=0.10,
            parser_high=0.90,
            parser_compact=0.85,
        ),
        log=SimpleNamespace(
            path="logs/pipeline.jsonl",
            level="INFO",
        ),
        audio=SimpleNamespace(
            input_device="CODEC USB",
            sample_rate=16000,
            channels=1,
            chunk_ms=30,
            vad_enabled=True,
            min_speech_ms=600,
            max_silence_ms=800,
            vad_mode=3,
            max_segment_ms=30000,
        ),
    )


# ---------------------------------------------------------------------------
# Singleton — uma única instância por processo.
# ---------------------------------------------------------------------------


_root: CompositionRoot | None = None


def get_root() -> CompositionRoot:
    """Retorna o CompositionRoot singleton."""
    global _root
    if _root is None:
        _root = create_composition_root()
    return _root


def set_root(root: CompositionRoot) -> None:
    """Define o CompositionRoot singleton (útil para testes)."""
    global _root
    _root = root


def reset_root() -> None:
    """Reseta o singleton (útil para testes)."""
    global _root
    _root = None
