"""semantic/ollama_backend.py — Backend nativo do Ollama (Sprint 21.3).

Implementa LLMBackend usando o endpoint NATIVO do Ollama:

    POST /api/chat

Diferenças em relação ao endpoint OpenAI-compatible (/v1/chat/completions):

1. O endpoint nativo respeita o parâmetro `think: false` (desativa
   completamente o raciocínio explícito do modelo).
2. O endpoint OpenAI-compatible aceita o parâmetro mas IGNORA internamente
   — o modelo continua gerando thinking (evidência Sprint 21.2).
3. O endpoint nativo separa `message.content` e `message.thinking` em
   campos distintos — não há necessidade de sanitização.
4. Opções de geração vão em `options` (não no raiz do payload).

Sprint 21.3 — Etapa 3 + 4: endpoint nativo + mecanismo oficial de thinking.
"""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request
from typing import Any

from semantic.llm_backend import (
    BackendRequest,
    BackendResponse,
    LLMBackend,
)
from semantic.types import SemanticError, SemanticTimeout

logger = logging.getLogger(__name__)

__all__ = ["OllamaBackend"]


class OllamaBackend(LLMBackend):
    """Backend LLM usando o protocolo nativo do Ollama.

    Usa POST /api/chat (não /v1/chat/completions).

    Vantagens:
      - Respeita think: false (mecanismo oficial para impedir thinking).
      - Separa content e thinking em campos distintos.
      - Latência baixa (~2.7s com qwen3:8b-q4_K_M, think: false).

    Args:
        base_url: URL base do servidor Ollama (sem /v1).
            Ex.: "http://localhost:11434".
        model: nome do modelo (ex.: "qwen3:8b-q4_K_M").
        api_key: chave de API (geralmente "ollama" ou "").
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3:8b-q4_K_M",
        api_key: str = "",
    ) -> None:
        # Garantir que base_url NÃO termina com /v1 (endpoint nativo).
        self._base_url = base_url.rstrip("/").removesuffix("/v1")
        self._model = model
        self._api_key = api_key

    # ------------------------------------------------------------------
    # Identificação
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def endpoint(self) -> str:
        return f"{self._base_url}/api/chat"

    # ------------------------------------------------------------------
    # Capacidades (estáticas — o backend conhece sua própria API)
    # ------------------------------------------------------------------

    def supports_think_parameter(self) -> bool:
        """Ollama nativo suporta think: false oficialmente.

        Não há detecção por tentativa — é uma capacidade conhecida
        do protocolo nativo do Ollama (Sprint 21.3 — Etapa 7).
        """
        return True

    # ------------------------------------------------------------------
    # Disponibilidade
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Verifica se o servidor Ollama está online (GET /api/tags)."""
        try:
            url = f"{self._base_url}/api/tags"
            req = urllib.request.Request(
                url, method="GET",
                headers=self._build_headers(self._api_key),
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def check_model_available(self) -> bool:
        """Verifica se o modelo está instalado (GET /api/tags).

        Ollama normaliza nomes para minúsculas — comparação case-insensitive.
        """
        target = self._model.lower()
        try:
            url = f"{self._base_url}/api/tags"
            req = urllib.request.Request(
                url, method="GET",
                headers=self._build_headers(self._api_key),
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status != 200:
                    return False
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("models", [])
                for m in models:
                    name = (m.get("name", "") or m.get("model", "")).lower()
                    # Match exato ou por prefixo de tag (ex.: "qwen3:8b" vs "qwen3:8b-q4_K_M").
                    if name == target or name.startswith(target + ":") \
                            or target.startswith(name + ":"):
                        return True
                return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Construção do payload (protocolo nativo Ollama)
    # ------------------------------------------------------------------

    def build_payload(self, request: BackendRequest) -> dict[str, Any]:
        """Constrói payload no formato nativo do Ollama (/api/chat).

        Diferenças em relação ao formato OpenAI:
          - options.num_predict em vez de max_tokens.
          - options.temperature e options.top_p dentro de options.
          - think no raiz do payload (não dentro de options).
          - stream: false (sempre não-streaming para inferência síncrona).
        """
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "top_p": request.top_p,
                "num_predict": request.max_tokens,
            },
        }
        # Etapa 4 — mecanismo oficial Ollama para impedir thinking.
        # O endpoint nativo /api/chat respeita think: false (evidência Sprint 21.2).
        if request.disable_thinking:
            payload["think"] = False
            logger.debug(
                "OllamaBackend: sending think=false (model=%s, native endpoint)",
                request.model,
            )
        return payload

    # ------------------------------------------------------------------
    # Envio da requisição
    # ------------------------------------------------------------------

    def send_request(
        self, payload: dict[str, Any], timeout_s: float,
    ) -> BackendResponse:
        """Envia POST /api/chat e retorna BackendResponse padronizada."""
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
            # Parsear resposta nativa.
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
            raise SemanticError(
                f"HTTP {e.code} error from Ollama /api/chat: {err_body[:200]}"
            ) from e
        except socket.timeout as e:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            logger.warning(
                "OllamaBackend: timeout after %.1fs (url=%s)",
                timeout_s, url,
            )
            raise SemanticTimeout(
                f"HTTP timeout after {timeout_s}s (Ollama /api/chat)"
            ) from e
        except urllib.error.URLError as e:
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                raise SemanticTimeout(f"HTTP timeout: {e}") from e
            raise SemanticError(f"HTTP error: {e}") from e
        except Exception as e:
            raise SemanticError(f"unexpected Ollama error: {e}") from e

    # ------------------------------------------------------------------
    # Interpretação da resposta (protocolo nativo)
    # ------------------------------------------------------------------

    def parse_response(self, raw: str) -> BackendResponse:
        """Interpreta resposta no formato nativo do Ollama /api/chat.

        Formato nativo (não-OpenAI):
            {
              "model": "...",
              "message": {
                "role": "assistant",
                "content": "...",      ← conteúdo útil
                "thinking": "..."      ← raciocínio (vazio se think: false)
              },
              "done": true,
              "done_reason": "stop",
              "prompt_eval_count": 86,
              "eval_count": 18,
              ...
            }

        Diferenças em relação ao formato OpenAI:
          - message.content em vez de choices[0].message.content.
          - message.thinking em vez de choices[0].message.reasoning.
          - done_reason em vez de choices[0].finish_reason.
          - prompt_eval_count/eval_count em vez de usage.prompt_tokens/completion_tokens.
        """
        response = BackendResponse()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            response.error = f"invalid JSON from Ollama: {e}"
            logger.warning(
                "OllamaBackend: invalid JSON response: %s (raw=%r)",
                e, raw[:200],
            )
            return response

        # Extrair message (pode estar ausente em respostas de erro).
        msg = data.get("message")
        if not isinstance(msg, dict):
            response.error = "Ollama response missing 'message' field"
            return response

        response.content = msg.get("content", "") or ""
        # thinking vem em campo separado — não há necessidade de sanitização.
        response.thinking = msg.get("thinking", "") or ""
        response.finish_reason = data.get("done_reason", "") or ""
        response.prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
        response.completion_tokens = int(data.get("eval_count", 0) or 0)

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
            "protocol": "ollama-native",
        }
