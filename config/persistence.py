"""Persistência de configuração — Sprint 14.

Permite que a configuração do sistema seja gravada em disco
e sobreviva a reinicializações.

Mantém a imutabilidade da Config original: as alterações são
persistidas em um arquivo de overrides (config.overrides.json)
e aplicadas no próximo carregamento.

Fluxo:
    GET /configuration  →  lê Config atual (em memória)
    PUT /configuration  →  mescla overrides + salva em disco
    (restart)           →  load_config() aplica overrides salvos
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


DEFAULT_OVERRIDES_PATH = "config/config.overrides.json"
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def load_overrides(path: str = DEFAULT_OVERRIDES_PATH) -> dict[str, Any]:
    """Carrega overrides salvos em disco.

    Returns:
        Dict com overrides (vazio se arquivo não existir).
    """
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("overrides file %s is not a dict — ignoring", path)
            return {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("failed to load overrides from %s: %s", path, e)
        return {}


def save_overrides(overrides: dict[str, Any], path: str = DEFAULT_OVERRIDES_PATH) -> None:
    """Salva overrides em disco (atomicamente).

    Cria o diretório pai se não existir.
    """
    with _LOCK:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(overrides, f, indent=2, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
        logger.info("overrides saved to %s (%d keys)", path, len(overrides))


# ---------------------------------------------------------------------------
# Merge — aplica overrides em um dict de configuração.
# ---------------------------------------------------------------------------


def merge_overrides(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Mescla overrides em base (deep merge).

    - Dicts são mesclados recursivamente.
    - Tipos não-dict em overrides substituem base.
    - Keys em base não presentes em overrides são preservadas.
    """
    result = dict(base)
    for k, v in overrides.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = merge_overrides(result[k], v)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Validation — valida que um dict de configuração tem estrutura esperada.
# ---------------------------------------------------------------------------


ALLOWED_TOP_KEYS = frozenset({
    "holyrics", "stt", "llm", "search", "state", "cache",
    "confidence", "log", "mode", "audio",
})

# Sprint 17.5.2 — Conjuntos de valores válidos para campos críticos.
# Espelham a validação de config/loader.py para impedir que valores
# inválidos sejam persistidos em config.overrides.json e quebrem o
# restart do backend.
# Sprint 19.1 — estendido para suportar GPU AMD via DirectML e ROCm.
VALID_STT_BACKENDS = frozenset({
    "faster-whisper",  # legacy
    "auto",            # Sprint 19.1: seleção automática
    "cuda",
    "directml",
    "rocm",
    "cpu",
})
VALID_STT_DEVICES = frozenset({"cpu", "cuda", "auto", "directml", "rocm"})
VALID_STT_COMPUTE_TYPES = frozenset({
    "int8", "int8_float16", "float16", "float32", "auto",
})
VALID_STT_LANGUAGES = frozenset({"pt", "en", "es", "auto"})
VALID_AUDIO_CHUNK_MS = frozenset({10, 20, 30})


def validate_overrides(overrides: dict[str, Any]) -> list[str]:
    """Valida estrutura E valores de overrides.

    Sprint 17.5.2 — agora valida também valores críticos de stt e audio,
    espelhando config/loader.py. Isto impede que um valor inválido seja
    persistido em config.overrides.json e quebre o restart do backend.

    Returns:
        Lista de erros (vazia se válido).
    """
    errors: list[str] = []
    for k in overrides:
        if k not in ALLOWED_TOP_KEYS:
            errors.append(f"unknown key: {k!r} (allowed: {sorted(ALLOWED_TOP_KEYS)})")
    if "mode" in overrides and not isinstance(overrides["mode"], str):
        errors.append("mode must be a string")
    if "mode" in overrides and isinstance(overrides["mode"], str):
        if overrides["mode"] not in {"auto", "confirm", "quick"}:
            errors.append(f"invalid mode: {overrides['mode']!r} (auto, confirm, quick)")

    # Sprint 17.5.2 — Validação de stt.* (campos críticos).
    stt = overrides.get("stt")
    if isinstance(stt, dict):
        backend = stt.get("backend")
        if backend is not None and str(backend) not in VALID_STT_BACKENDS:
            errors.append(
                f"invalid stt.backend: {backend!r} "
                f"(valid: {sorted(VALID_STT_BACKENDS)})"
            )
        device = stt.get("device")
        if device is not None and str(device) not in VALID_STT_DEVICES:
            errors.append(
                f"invalid stt.device: {device!r} "
                f"(valid: {sorted(VALID_STT_DEVICES)})"
            )
        compute_type = stt.get("compute_type")
        if compute_type is not None and str(compute_type) not in VALID_STT_COMPUTE_TYPES:
            errors.append(
                f"invalid stt.compute_type: {compute_type!r} "
                f"(valid: {sorted(VALID_STT_COMPUTE_TYPES)})"
            )
        language = stt.get("language")
        if language is not None and str(language) not in VALID_STT_LANGUAGES:
            errors.append(
                f"invalid stt.language: {language!r} "
                f"(valid: {sorted(VALID_STT_LANGUAGES)})"
            )
        cpu_threads = stt.get("cpu_threads")
        if cpu_threads is not None:
            if not isinstance(cpu_threads, int) or isinstance(cpu_threads, bool):
                errors.append(f"stt.cpu_threads must be int, got {type(cpu_threads).__name__}")
            elif cpu_threads < 0 or cpu_threads > 128:
                errors.append(f"stt.cpu_threads out of range (0..128): {cpu_threads}")
        beam_size = stt.get("beam_size")
        if beam_size is not None:
            if not isinstance(beam_size, int) or isinstance(beam_size, bool):
                errors.append(f"stt.beam_size must be int, got {type(beam_size).__name__}")
            elif beam_size < 1 or beam_size > 20:
                errors.append(f"stt.beam_size out of range (1..20): {beam_size}")

    # Sprint 17.5.2 — Validação de audio.* (campos críticos).
    audio = overrides.get("audio")
    if isinstance(audio, dict):
        chunk_ms = audio.get("chunk_ms")
        if chunk_ms is not None:
            if not isinstance(chunk_ms, int) or isinstance(chunk_ms, bool):
                errors.append(f"audio.chunk_ms must be int, got {type(chunk_ms).__name__}")
            elif chunk_ms not in VALID_AUDIO_CHUNK_MS:
                errors.append(
                    f"invalid audio.chunk_ms: {chunk_ms} "
                    f"(valid: {sorted(VALID_AUDIO_CHUNK_MS)})"
                )
        vad_mode = audio.get("vad_mode")
        if vad_mode is not None:
            if not isinstance(vad_mode, int) or isinstance(vad_mode, bool):
                errors.append(f"audio.vad_mode must be int, got {type(vad_mode).__name__}")
            elif not (0 <= vad_mode <= 3):
                errors.append(f"audio.vad_mode out of range (0..3): {vad_mode}")
        sample_rate = audio.get("sample_rate")
        if sample_rate is not None:
            if not isinstance(sample_rate, int) or isinstance(sample_rate, bool):
                errors.append(f"audio.sample_rate must be int, got {type(sample_rate).__name__}")
            elif sample_rate <= 0:
                errors.append(f"audio.sample_rate must be positive: {sample_rate}")
        channels = audio.get("channels")
        if channels is not None:
            if not isinstance(channels, int) or isinstance(channels, bool):
                errors.append(f"audio.channels must be int, got {type(channels).__name__}")
            elif channels not in (1, 2):
                errors.append(f"audio.channels must be 1 or 2: {channels}")

    return errors
