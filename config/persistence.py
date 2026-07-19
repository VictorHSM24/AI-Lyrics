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


def validate_overrides(overrides: dict[str, Any]) -> list[str]:
    """Valida estrutura de overrides.

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
    return errors
