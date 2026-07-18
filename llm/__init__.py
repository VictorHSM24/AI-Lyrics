"""Módulo LLM — interpretação semântica de comandos bíblicos.

API pública:
    LLMClient(config, book_table) → cliente Ollama/Qwen3.
    LLMError — exceção de domínio do módulo.

Responsabilidades (Blueprint §4.4, Módulo 6):
  - Conectar ao servidor LLM (Ollama, OpenAI-compatible).
  - Carregar modelo lazy (só na primeira chamada).
  - Montar prompt (system + few-shot + estado atual).
  - Validar JSON de resposta contra schema.
  - Retornar Intent ou sinalizar falha (action="none").

Limites explícitos:
  - Não chama Holyrics.
  - Não chama Searcher.
  - Não modifica estado.
  - Não implementa cache.
  - Apenas produz Intent.
"""

from __future__ import annotations

from llm.client import LLMClient, LLMError
from llm.prompts import (
    CORRECTION_PROMPT,
    FEW_SHOT_EXAMPLES,
    SYSTEM_PROMPT,
    VALID_ACTIONS,
    build_correction_messages,
    build_messages,
    validate_response,
)

__all__ = [
    "LLMClient",
    "LLMError",
    "SYSTEM_PROMPT",
    "FEW_SHOT_EXAMPLES",
    "CORRECTION_PROMPT",
    "VALID_ACTIONS",
    "build_messages",
    "build_correction_messages",
    "validate_response",
]
