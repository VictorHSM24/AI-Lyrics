"""semantic/provider.py — Interface SemanticProvider (Sprint 20).

Responsabilidade:
  - Definir o contrato (Protocol) que todo provider deve implementar.
  - Permitir múltiplos providers (OpenAI, Gemini, Ollama, LMStudio, LocalGGUF).
  - A Sprint 20 implementa apenas um provider local, mas a arquitetura
    nasce preparada para múltiplos.

Contrato:
  - Provider recebe SemanticContext + timeout.
  - Provider retorna SemanticResult (NUNCA texto livre).
  - Provider pode levantar SemanticTimeout ou SemanticError.
  - Provider NUNCA acessa EventBus, Searcher, Holyrics, frontend ou banco.

Sprint 20 — Semantic Understanding Engine.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from semantic.types import SemanticContext, SemanticResult


__all__ = ["SemanticProvider"]


@runtime_checkable
class SemanticProvider(Protocol):
    """Interface para providers de compreensão semântica.

    Implementações:
      - semantic.local_provider.LocalLLMProvider (Sprint 20 — provider local)
      - Futuro: OpenAIProvider, GeminiProvider, OllamaProvider, etc.

    Regras:
      1. O provider NUNCA retorna texto livre — apenas SemanticResult.
      2. O provider NUNCA publica eventos no EventBus.
      3. O provider NUNCA acessa Holyrics, Searcher ou frontend.
      4. O provider deve respeitar o timeout.
      5. Se o modelo retornar JSON inválido, o provider deve retornar
         SemanticResult(intent="none") em vez de levantar exceção
         (a camada de segurança do SemanticEngine valida o schema).
    """

    @property
    def name(self) -> str:
        """Nome do provider ('local-llm', 'openai', 'stub', etc.)."""
        ...

    @property
    def model_name(self) -> str:
        """Nome do modelo usado ('llama3.2:3b', 'gpt-4o-mini', etc.)."""
        ...

    def infer(self, context: SemanticContext, timeout_ms: int = 5000) -> SemanticResult:
        """Executa inferência semântica no contexto.

        Args:
            context: contexto construído pelo ContextEngine.
            timeout_ms: timeout máximo em milissegundos.

        Returns:
            SemanticResult estruturado.

        Raises:
            SemanticTimeout: se a inferência exceder o timeout.
            SemanticError: se houver erro de comunicação ou modelo.
        """
        ...

    def is_available(self) -> bool:
        """Verifica se o provider está disponível (modelo carregado, servidor online)."""
        ...

    def close(self) -> None:
        """Libera recursos (conexões, modelo em memória)."""
        ...
