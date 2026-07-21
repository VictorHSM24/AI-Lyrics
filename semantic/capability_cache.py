"""semantic/capability_cache.py — Cache de capacidades do backend LLM (Sprint 21.1.1).

Responsabilidade única:
  - Detectar e cachear capacidades do backend LLM (ex.: suporte ao
    parâmetro `think` da API Ollama).
  - A detecção ocorre uma única vez por processo — após a primeira
    inferência, o resultado é cached e nunca mais testado.

Motivação:
  A Sprint 21.1 detectava suporte a thinking pelo NOME do modelo
  (`model.startswith("qwen3")`). Isso quebra em:
    - proxies OpenAI-compatible
    - modelos renomeados
    - versões futuras
    - aliases
    - modelos customizados

  A Sprint 21.1.1 detecta pela CAPACIDADE real do backend — envia
  `think: false` na primeira requisição e observa a resposta:
    - Aceito → SUPPORTED
    - Erro 400 / "unknown field" / "invalid parameter" → UNSUPPORTED

Sprint 21.1.1 — Hardening do LocalLLMProvider.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

__all__ = ["CapabilityState", "CapabilityCache", "CapabilityResult"]


class CapabilityState(Enum):
    """Estados possíveis para uma capacidade do backend."""
    UNKNOWN = "unknown"          # Ainda não testada.
    SUPPORTED = "supported"      # Backend aceita o parâmetro.
    UNSUPPORTED = "unsupported"  # Backend rejeita o parâmetro.


@dataclass
class CapabilityResult:
    """Resultado da detecção de uma capacidade.

    Campos:
        state: estado final (SUPPORTED ou UNSUPPORTED).
        detection_ms: tempo gasto na detecção em ms.
        error_message: mensagem de erro se UNSUPPORTED, "" caso contrário.
    """
    state: CapabilityState
    detection_ms: float = 0.0
    error_message: str = ""


class CapabilityCache:
    """Cache thread-safe de capacidades do backend LLM.

    Uso típico (think parameter):
        cache = CapabilityCache()
        if cache.should_try("think"):
            result = cache.detect_think(send_fn)
            if result.state == CapabilityState.SUPPORTED:
                # usar think: false nas próximas requisições
                ...

    Thread-safe. A detecção é realizada apenas uma vez por capacidade.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Mapa: nome_capacidade → (CapabilityState, detection_ms, error_msg)
        self._cache: dict[str, CapabilityResult] = {}
        # Contagem de tentativas de detecção (para telemetria).
        self._detection_attempts: dict[str, int] = {}

    def get_state(self, capability: str) -> CapabilityState:
        """Retorna o estado atual de uma capacidade.

        Retorna UNKNOWN se ainda não foi detectada.
        """
        with self._lock:
            result = self._cache.get(capability)
            return result.state if result else CapabilityState.UNKNOWN

    def should_try(self, capability: str) -> bool:
        """Verifica se a capacidade ainda precisa ser detectada.

        Retorna True se o estado for UNKNOWN (ainda não testada).
        Retorna False se já foi detectada (SUPPORTED ou UNSUPPORTED).
        """
        return self.get_state(capability) == CapabilityState.UNKNOWN

    def record_detection(
        self,
        capability: str,
        state: CapabilityState,
        detection_ms: float = 0.0,
        error_message: str = "",
    ) -> None:
        """Registra o resultado da detecção de uma capacidade.

        Após registrado, a capacidade não será mais testada.
        """
        with self._lock:
            if capability in self._cache:
                # Já detectada — não sobrescrever (idempotente).
                logger.debug(
                    "CapabilityCache: '%s' already detected as %s — ignoring new result",
                    capability, self._cache[capability].state.value,
                )
                return
            self._cache[capability] = CapabilityResult(
                state=state,
                detection_ms=detection_ms,
                error_message=error_message,
            )
            attempts = self._detection_attempts.get(capability, 0) + 1
            self._detection_attempts[capability] = attempts

            logger.debug(
                "CapabilityCache: '%s' detected as %s (attempts=%d, ms=%.1f, error=%r)",
                capability, state.value, attempts, detection_ms, error_message[:80],
            )

    def get_result(self, capability: str) -> CapabilityResult | None:
        """Retorna o resultado completo da detecção, ou None se não detectada."""
        with self._lock:
            return self._cache.get(capability)

    def get_detection_attempts(self, capability: str) -> int:
        """Retorna o número de tentativas de detecção para uma capacidade.

        Esperado: 1 (apenas uma tentativa por processo).
        """
        with self._lock:
            return self._detection_attempts.get(capability, 0)

    def metrics(self) -> dict[str, object]:
        """Retorna métricas para telemetria."""
        with self._lock:
            return {
                "capabilities": {
                    cap: {
                        "state": r.state.value,
                        "detection_ms": r.detection_ms,
                        "error": r.error_message[:120],
                        "attempts": self._detection_attempts.get(cap, 0),
                    }
                    for cap, r in self._cache.items()
                },
                "total_capabilities_tracked": len(self._cache),
            }

    def reset(self) -> None:
        """Reseta o cache (útil para testes)."""
        with self._lock:
            self._cache.clear()
            self._detection_attempts.clear()


# ---------------------------------------------------------------------------
# Heurísticas para detectar rejeição do parâmetro think.
# ---------------------------------------------------------------------------

# Substrings que indicam que o backend não reconhece o parâmetro `think`.
# Case-insensitive. Compatível com múltiplos backends OpenAI-compatible.
_THINK_REJECTION_SIGNALS: tuple[str, ...] = (
    "unknown field",
    "unknown parameter",
    "unknown argument",
    "invalid parameter",
    "invalid argument",
    "unsupported parameter",
    "unsupported argument",
    "unrecognized parameter",
    "unrecognized field",
    "think is not a valid field",
    "field think is not",
    "does not support think",
    "no such field",
    "extra fields",
    "additional properties",
)


def is_think_rejection_error(status_code: int, error_body: str) -> bool:
    """Heurística: determina se um erro HTTP indica rejeição do parâmetro think.

    Args:
        status_code: código HTTP da resposta (geralmente 400 ou 422).
        error_body: corpo da resposta de erro.

    Returns:
        True se o erro parece ser rejeição do parâmetro think.
    """
    if status_code not in (400, 404, 422):
        return False
    body_lower = error_body.lower()
    for signal in _THINK_REJECTION_SIGNALS:
        if signal in body_lower:
            return True
    # Verificar menção específica a "think" no erro.
    if "think" in body_lower and (
        "field" in body_lower or "parameter" in body_lower
        or "argument" in body_lower or "unknown" in body_lower
    ):
        return True
    return False
