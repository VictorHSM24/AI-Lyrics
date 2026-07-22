"""semantic/llm_backend.py — Abstração de backend LLM (Sprint 21.3).

Define a interface LLMBackend que encapsula toda a comunicação com o
servidor LLM (construção de payload, envio HTTP, interpretação de resposta).

Cada backend concreto implementa:
  - construir payload no protocolo nativo (Ollama, OpenAI, etc.)
  - enviar a requisição HTTP
  - interpretar a resposta no formato nativo
  - expor resultado padronizado (BackendResponse)

O LocalLLMProvider não conhece diferenças entre protocolos — apenas
consome a interface LLMBackend.

Sprint 21.3 — Arquitetura Multi-Backend para LLMs.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from semantic.types import SemanticError, SemanticTimeout

logger = logging.getLogger(__name__)

__all__ = [
    "LLMBackend",
    "BackendRequest",
    "BackendResponse",
    "BackendCapability",
]


# ---------------------------------------------------------------------------
# Tipos padronizados (protocolo-agnostic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackendRequest:
    """Pedido padronizado para um backend LLM.

    Atributos:
        system_prompt: prompt de sistema (instruções).
        user_prompt: prompt do usuário (texto + contexto).
        model: nome do modelo.
        temperature: temperatura (0.0-2.0).
        top_p: nucleus sampling (0.0-1.0).
        max_tokens: limite de tokens de saída.
        disable_thinking: se True, o backend deve impedir thinking.
        stream: se True, usa streaming (nem todos backends suportam).
    """
    system_prompt: str
    user_prompt: str
    model: str
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 300
    disable_thinking: bool = True
    stream: bool = False


@dataclass
class BackendResponse:
    """Resposta padronizada de um backend LLM.

    Atributos:
        content: conteúdo útil da resposta (texto após sanitização
            do protocolo, sem thinking).
        thinking: cadeia de raciocínio produzida pelo modelo, se houver
            (geralmente "" quando disable_thinking=True funciona).
        raw_response: resposta HTTP bruta (para depuração/telemetria).
        http_status: código HTTP (200 se sucesso, 0 se sem resposta).
        http_time_ms: tempo da requisição HTTP em ms.
        finish_reason: motivo de término ("stop", "length", "timeout", etc.).
        prompt_tokens: tokens consumidos pelo prompt.
        completion_tokens: tokens gerados pelo modelo.
        error: mensagem de erro não-fatal (vazia se sucesso).
        used_think_parameter: se o backend enviou think: false (telemetria).
    """
    content: str = ""
    thinking: str = ""
    raw_response: str = ""
    http_status: int = 0
    http_time_ms: float = 0.0
    finish_reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""
    used_think_parameter: bool = False


# ---------------------------------------------------------------------------
# Interface abstrata
# ---------------------------------------------------------------------------


class LLMBackend(ABC):
    """Interface abstrata para backends LLM.

    Cada backend concreto implementa esta interface. O LocalLLMProvider
    consome apenas esta interface — não conhece detalhes do protocolo.

    Responsabilidades do backend:
      1. Construir payload no protocolo nativo (build_payload).
      2. Enviar requisição HTTP (send_request).
      3. Interpretar resposta no formato nativo (parse_response).
      4. Verificar disponibilidade (is_available).
      5. Verificar se o modelo está instalado (check_model_available).
      6. Informar suporte a thinking (supports_think_parameter).

    O backend NÃO faz:
      - Sanitização de thinking (responsabilidade do provider/sanitizer).
      - Parse JSON do conteúdo (responsabilidade do provider).
      - Retry (responsabilidade do provider).
      - Telemetria de inferência (responsabilidade do provider).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome do backend (ex.: 'ollama', 'openai')."""
        ...

    @property
    @abstractmethod
    def endpoint(self) -> str:
        """Endpoint HTTP usado para inferência (ex.: '/api/chat')."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Verifica se o servidor está online."""
        ...

    @abstractmethod
    def check_model_available(self) -> bool:
        """Verifica se o modelo específico está instalado no servidor."""
        ...

    @abstractmethod
    def supports_think_parameter(self) -> bool:
        """Informa se o backend suporta o parâmetro think nativamente.

        Retorna True se o protocolo do backend tem um mecanismo oficial
        para impedir thinking (ex.: Ollama nativo com think: false).
        Retorna False se o backend é OpenAI-compatible e não tem
        mecanismo nativo para impedir thinking.

        Esta informação é estática (conhecida pelo backend) — não
        envolve detecção por tentativa.
        """
        ...

    @abstractmethod
    def build_payload(self, request: BackendRequest) -> dict[str, Any]:
        """Constrói o payload no protocolo nativo do backend."""
        ...

    @abstractmethod
    def send_request(
        self, payload: dict[str, Any], timeout_s: float,
    ) -> BackendResponse:
        """Envia a requisição HTTP e retorna a resposta padronizada.

        Levanta SemanticTimeout em caso de timeout.
        Levanta SemanticError em caso de erro HTTP não recuperável.
        """
        ...

    @abstractmethod
    def parse_response(self, raw: str) -> BackendResponse:
        """Interpreta a resposta bruta no formato nativo do backend.

        Extrai content, thinking, finish_reason e usage da resposta.
        Não sanitiza thinking — apenas extrai os campos.
        """
        ...

    # ------------------------------------------------------------------
    # Métodos utilitários compartilhados (não-abstratos)
    # ------------------------------------------------------------------

    def _build_headers(self, api_key: str = "") -> dict[str, str]:
        """Constrói headers HTTP comuns a todos backends."""
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def get_telemetry(self) -> dict[str, Any]:
        """Retorna telemetria específica do backend (para depuração).

        Pode ser sobrescrito por backends concretos para expor métricas
        adicionais (ex.: endpoint usado, versão do protocolo).
        """
        return {
            "backend_name": self.name,
            "endpoint": self.endpoint,
            "supports_think_parameter": self.supports_think_parameter(),
        }
