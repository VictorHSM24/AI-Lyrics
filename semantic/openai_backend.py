"""semantic/openai_backend.py — Backend OpenAI-compatible (Sprint 21.3).

Implementa LLMBackend usando o protocolo OpenAI:

    POST /v1/chat/completions

Compatível com:
  - OpenAI API
  - LM Studio
  - vLLM
  - llama.cpp server
  - quaisquer servidores OpenAI-compatible

Diferenças em relação ao OllamaBackend:
  - Usa /v1/chat/completions (não /api/chat).
  - think: false é enviado mas pode ser ignorado pelo backend (evidência
    Sprint 21.2: OpenAI-compatible do Ollama aceita mas ignora).
  - Resposta em choices[0].message.content / reasoning.
  - max_tokens no raiz (não em options.num_predict).

Sprint 21.3 — Etapa 5: preservar compatibilidade OpenAI.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import urllib.error
import urllib.request
from typing import Any

from semantic.llm_backend import (
    BackendRequest,
    BackendResponse,
    LLMBackend,
)
from semantic.capability_cache import (
    CapabilityCache,
    CapabilityState,
    is_think_rejection_error,
)
from semantic.types import SemanticError, SemanticTimeout

logger = logging.getLogger(__name__)

__all__ = ["OpenAIBackend"]


class OpenAIBackend(LLMBackend):
    """Backend LLM usando o protocolo OpenAI (/v1/chat/completions).

    Compatível com OpenAI, LM Studio, vLLM, llama.cpp e outros.

    Args:
        base_url: URL base do servidor COM /v1.
            Ex.: "http://localhost:11434/v1", "https://api.openai.com/v1".
        model: nome do modelo.
        api_key: chave de API (pode ser "" para servidores locais).
        capability_cache: cache compartilhado de capacidades (opcional).
            Se None, cria um interno. Útil quando múltiplos backends
            compartilham o mesmo servidor.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "gpt-3.5-turbo",
        api_key: str = "",
        capability_cache: CapabilityCache | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        # Capability detection (Etapa 7) — apenas para backends OpenAI-compatible.
        # Ollama nativo NÃO usa capability detection (conhece sua API).
        self._capability_cache = capability_cache or CapabilityCache()

    # ------------------------------------------------------------------
    # Identificação
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "openai"

    @property
    def endpoint(self) -> str:
        return f"{self._base_url}/chat/completions"

    # ------------------------------------------------------------------
    # Capacidades
    # ------------------------------------------------------------------

    def supports_think_parameter(self) -> bool:
        """OpenAI-compatible: detecta suporte a think por tentativa.

        Diferente do Ollama nativo (que conhece sua API), backends
        OpenAI-compatible variam — alguns aceitam think: false, outros
        rejeitam com erro 400.

        A detecção é feita uma única vez na primeira inferência e
        cacheada em CapabilityCache.
        """
        return self._capability_cache.get_state("think") == CapabilityState.SUPPORTED

    def get_capability_cache(self) -> CapabilityCache:
        """Expõe o cache de capacidades (para o provider coordenar detecção)."""
        return self._capability_cache

    def should_detect_capability(self) -> bool:
        """Verifica se a detecção de capability ainda precisa ser feita."""
        return self._capability_cache.should_try("think")

    def record_capability_supported(self, detection_ms: float = 0.0) -> None:
        """Registra que o backend suporta think: false."""
        self._capability_cache.record_detection(
            "think", CapabilityState.SUPPORTED, detection_ms=detection_ms,
        )

    def record_capability_unsupported(
        self, detection_ms: float = 0.0, error: str = "",
    ) -> None:
        """Registra que o backend rejeita think: false."""
        self._capability_cache.record_detection(
            "think", CapabilityState.UNSUPPORTED,
            detection_ms=detection_ms, error_message=error,
        )

    # ------------------------------------------------------------------
    # Disponibilidade
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Verifica se o servidor está online (GET /v1/models)."""
        try:
            url = f"{self._base_url}/models"
            req = urllib.request.Request(
                url, method="GET",
                headers=self._build_headers(self._api_key),
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def check_model_available(self) -> bool:
        """Verifica se o modelo está instalado (GET /v1/models).

        Formato OpenAI: data[].id.
        """
        target = self._model.lower()
        try:
            url = f"{self._base_url}/models"
            req = urllib.request.Request(
                url, method="GET",
                headers=self._build_headers(self._api_key),
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status != 200:
                    return False
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("data", [])
                for m in models:
                    name = (m.get("id", "") or m.get("name", "")).lower()
                    if name == target or name.startswith(target + ":") \
                            or target.startswith(name + ":"):
                        return True
                return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Construção do payload (protocolo OpenAI)
    # ------------------------------------------------------------------

    def build_payload(self, request: BackendRequest) -> dict[str, Any]:
        """Constrói payload no formato OpenAI (/v1/chat/completions)."""
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        # think: false apenas se o backend foi detectado como suportando.
        # Antes da primeira detecção, NÃO enviamos think (UNKNOWN).
        if request.disable_thinking and self.supports_think_parameter():
            payload["think"] = False
            logger.debug(
                "OpenAIBackend: sending think=false (model=%s, capability=cached)",
                request.model,
            )
        return payload

    # ------------------------------------------------------------------
    # Envio da requisição
    # ------------------------------------------------------------------

    def send_request(
        self, payload: dict[str, Any], timeout_s: float,
    ) -> BackendResponse:
        """Envia POST /v1/chat/completions e retorna BackendResponse."""
        import time
        body = json.dumps(payload).encode("utf-8")
        url = self.endpoint
        req = urllib.request.Request(
            url,
            data=body,
            headers=self._build_headers(self._api_key),
            method="POST",
        )
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read().decode("utf-8")
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            response = self.parse_response(raw)
            response.http_status = 200
            response.http_time_ms = elapsed_ms
            response.raw_response = raw
            response.used_think_parameter = payload.get("think") is False
            return response
        except urllib.error.HTTPError as e:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            # Encapsular info para capability detection (status + body).
            raise SemanticError(
                f"HTTP {e.code} error: {err_body[:200]}"
            ) from e
        except socket.timeout as e:
            raise SemanticTimeout(
                f"HTTP timeout after {timeout_s}s (OpenAI endpoint)"
            ) from e
        except urllib.error.URLError as e:
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                raise SemanticTimeout(f"HTTP timeout: {e}") from e
            raise SemanticError(f"HTTP error: {e}") from e
        except Exception as e:
            raise SemanticError(f"unexpected OpenAI backend error: {e}") from e

    # ------------------------------------------------------------------
    # Interpretação da resposta (protocolo OpenAI)
    # ------------------------------------------------------------------

    def parse_response(self, raw: str) -> BackendResponse:
        """Interpreta resposta no formato OpenAI.

        Formato:
            {
              "choices": [
                {
                  "message": {
                    "role": "assistant",
                    "content": "...",
                    "reasoning": "..."   ← thinking (alguns backends)
                  },
                  "finish_reason": "stop"
                }
              ],
              "usage": {
                "prompt_tokens": 60,
                "completion_tokens": 18
              }
            }
        """
        response = BackendResponse()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            response.error = f"invalid JSON from OpenAI endpoint: {e}"
            return response

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            response.error = "OpenAI response missing 'choices'"
            return response

        first = choices[0]
        if not isinstance(first, dict):
            response.error = "OpenAI choices[0] is not a dict"
            return response

        msg = first.get("message", {})
        if not isinstance(msg, dict):
            response.error = "OpenAI message is not a dict"
            return response

        response.content = msg.get("content", "") or ""
        # Alguns backends OpenAI-compatible expõem thinking como "reasoning".
        response.thinking = msg.get("reasoning", "") or msg.get("thinking", "") or ""
        response.finish_reason = first.get("finish_reason", "") or ""

        usage = data.get("usage", {})
        if isinstance(usage, dict):
            response.prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            response.completion_tokens = int(usage.get("completion_tokens", 0) or 0)

        return response

    # ------------------------------------------------------------------
    # Telemetria específica
    # ------------------------------------------------------------------

    def get_telemetry(self) -> dict[str, Any]:
        return {
            "backend_name": self.name,
            "endpoint": self.endpoint,
            "base_url": self._base_url,
            "model": self._model,
            "supports_think_parameter": self.supports_think_parameter(),
            "protocol": "openai-compatible",
            "capability_state": self._capability_cache.get_state("think").value,
        }

    # ------------------------------------------------------------------
    # Helper para capability detection (usado pelo provider)
    # ------------------------------------------------------------------

    @staticmethod
    def is_think_rejection(err_msg: str) -> bool:
        """Verifica se um erro SemanticError indica rejeição do parâmetro think.

        Extrai status code da mensagem e aplica heurística.
        """
        m = re.search(r"HTTP (\d+)", err_msg)
        status_code = int(m.group(1)) if m else 0
        return is_think_rejection_error(status_code, err_msg)
