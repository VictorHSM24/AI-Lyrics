"""semantic — Camada de compreensão semântica (Sprint 20).

Arquitetura:
    SpeechPartial / SpeechPartialUpdated
            │
            ▼
    SemanticEngine (assina SpeechPartial/Updated, paralelo ao parser)
            │
            ├─ ContextEngine.build() → SemanticContext
            ├─ SemanticCache.get() → cache hit?
            ├─ SemanticProvider.infer() → SemanticResult
            └─ publica IntentCandidate
                    │
                    ▼
    ReferenceResolver (assina IntentCandidate)
            │
            ├─ verifica parser já resolveu (bus.history)
            ├─ valida candidatos via Searcher
            ├─ escolhe maior confiança
            └─ publica ReferenceDetected

Componentes:
  - types.py: SemanticCandidate, SemanticResult, SemanticContext
  - provider.py: SemanticProvider (Protocol)
  - local_provider.py: LocalLLMProvider (HTTP OpenAI-compatible), StubProvider
  - context_engine.py: ContextEngine
  - cache.py: SemanticCache
  - engine.py: SemanticEngine
  - resolver.py: ReferenceResolver

Sprint 20 — Semantic Understanding Engine.
"""

from semantic.types import (
    SemanticCandidate,
    SemanticContext,
    SemanticError,
    SemanticResult,
    SemanticTimeout,
)
from semantic.provider import SemanticProvider
from semantic.local_provider import LocalLLMProvider, StubProvider
from semantic.context_engine import ContextEngine
from semantic.cache import SemanticCache
from semantic.engine import SemanticEngine
from semantic.resolver import ReferenceResolver
from semantic.thinking_sanitizer import ThinkingSanitizer, SanitizationResult
from semantic.capability_cache import (
    CapabilityCache,
    CapabilityResult,
    CapabilityState,
    is_think_rejection_error,
)

__all__ = [
    "SemanticCandidate",
    "SemanticContext",
    "SemanticError",
    "SemanticResult",
    "SemanticTimeout",
    "SemanticProvider",
    "LocalLLMProvider",
    "StubProvider",
    "ContextEngine",
    "SemanticCache",
    "SemanticEngine",
    "ReferenceResolver",
    "ThinkingSanitizer",
    "SanitizationResult",
    "CapabilityCache",
    "CapabilityResult",
    "CapabilityState",
    "is_think_rejection_error",
]
