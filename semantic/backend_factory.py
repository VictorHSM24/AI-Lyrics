"""semantic/backend_factory.py — Factory de backends LLM (Sprint 21.3).

Cria o backend correto com base na configuração. O resto do sistema
(LocalLLMProvider, SemanticEngine) não conhece essa decisão.

Mapeamento:
    provider=ollama  → OllamaBackend (endpoint nativo /api/chat)
    provider=openai  → OpenAIBackend (/v1/chat/completions)
    provider=lmstudio → OpenAIBackend (LM Studio é OpenAI-compatible)
    provider=vllm    → OpenAIBackend (vLLM é OpenAI-compatible)

Sprint 21.3 — Etapa 6: Factory.
"""

from __future__ import annotations

import logging
from typing import Any

from semantic.llm_backend import LLMBackend
from semantic.ollama_backend import OllamaBackend
from semantic.openai_backend import OpenAIBackend

logger = logging.getLogger(__name__)

__all__ = ["create_backend", "BACKEND_ALIASES"]


# Mapeamento de aliases → backend real.
# Backends OpenAI-compatible podem ser referenciados por vários nomes.
BACKEND_ALIASES: dict[str, str] = {
    "ollama": "ollama",
    "openai": "openai",
    "lmstudio": "openai",
    "lm-studio": "openai",
    "vllm": "openai",
    "llama-cpp": "openai",
    "llamacpp": "openai",
    "openai-compatible": "openai",
}


def create_backend(
    provider: str,
    base_url: str,
    model: str,
    api_key: str = "",
    **kwargs: Any,
) -> LLMBackend:
    """Cria o backend LLM correto com base no nome do provider.

    Args:
        provider: nome do provider ("ollama", "openai", "lmstudio", "vllm").
        base_url: URL base do servidor.
            Para OllamaBackend: SEM /v1 (ex.: "http://localhost:11434").
            Para OpenAIBackend: COM /v1 (ex.: "http://localhost:11434/v1").
        model: nome do modelo.
        api_key: chave de API (opcional).
        **kwargs: argumentos adicionais específicos do backend.

    Returns:
        Instância de LLMBackend.

    Raises:
        ValueError: se o provider não for reconhecido.
    """
    canonical = BACKEND_ALIASES.get(provider.lower())
    if canonical is None:
        raise ValueError(
            f"unknown LLM provider: {provider!r}. "
            f"Supported: {sorted(BACKEND_ALIASES.keys())}"
        )

    if canonical == "ollama":
        logger.info(
            "BackendFactory: creating OllamaBackend (native /api/chat) "
            "for provider=%r, model=%s, base_url=%s",
            provider, model, base_url,
        )
        return OllamaBackend(
            base_url=base_url,
            model=model,
            api_key=api_key,
        )

    if canonical == "openai":
        logger.info(
            "BackendFactory: creating OpenAIBackend (/v1/chat/completions) "
            "for provider=%r, model=%s, base_url=%s",
            provider, model, base_url,
        )
        return OpenAIBackend(
            base_url=base_url,
            model=model,
            api_key=api_key,
            capability_cache=kwargs.get("capability_cache"),
        )

    # Nunca deveria chegar aqui — BACKEND_ALIASES mapeia tudo.
    raise ValueError(f"unhandled canonical backend: {canonical!r}")


def normalize_base_url_for_backend(provider: str, base_url: str) -> str:
    """Normaliza a base_url para o backend correto.

    Ollama nativo: SEM /v1 (ex.: "http://localhost:11434").
    OpenAI-compatible: COM /v1 (ex.: "http://localhost:11434/v1").

    Útil quando a config tem base_url em um formato e o backend
    espera outro.
    """
    canonical = BACKEND_ALIASES.get(provider.lower(), "openai")
    if canonical == "ollama":
        # Remover /v1 se presente.
        return base_url.rstrip("/").removesuffix("/v1")
    # OpenAI: garantir /v1 presente.
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url = url + "/v1"
    return url
