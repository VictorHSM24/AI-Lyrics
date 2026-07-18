"""Sermon Context Engine — infraestrutura de contexto do sermão.

Módulo responsável por manter o estado do sermão em andamento.
Totalmente desacoplado do restante do sistema (Searcher, Ranking, LLM,
Parser, KnowledgeBase, Holyrics, Embeddings).

API pública:
  - SermonContext: DTO imutável do estado do sermão.
  - SermonContextEngine: engine que evolui o contexto via eventos.
  - ContextWindowConfig: configuração da janela de contexto e expiração.
  - Eventos tipados: BookChanged, ChapterChanged, ReferenceResolved,
    ReferenceRepeated, ReferenceCompleted, ThemeMentioned, EntityMentioned,
    ConceptMentioned, EventMentioned, ContextReset.

Design:
  - DTOs imutáveis (frozen dataclass).
  - Atualizações retornam novo SermonContext (nunca modificam o atual).
  - Eventos tipados (frozen dataclass).
  - Política de expiração determinística baseada em contadores.
  - Janela de contexto configurável.
  - Nenhum estado global.
  - Nenhum conhecimento de outros componentes.

Compatibilidade futura (Streaming Speech Pipeline):
  O engine processa eventos de alto nível. No futuro, eventos de baixo
  nível (BOOK_DETECTED, CHAPTER_DETECTED, VERSE_DETECTED, etc.) poderão
  ser agregados em eventos de alto nível antes de chegar ao engine, ou
  o engine poderá ser estendido para processá-los diretamente.
"""

from context.dtos import SermonContext
from context.engine import ContextWindowConfig, SermonContextEngine
from context.events import (
    BookChanged,
    ChapterChanged,
    ConceptMentioned,
    ContextEvent,
    ContextReset,
    EntityMentioned,
    EventMentioned,
    ReferenceCompleted,
    ReferenceRepeated,
    ReferenceResolved,
    SermonContextEvent,
    ThemeMentioned,
)

__all__ = [
    "SermonContext",
    "SermonContextEngine",
    "ContextWindowConfig",
    "ContextEvent",
    "BookChanged",
    "ChapterChanged",
    "ReferenceResolved",
    "ReferenceRepeated",
    "ReferenceCompleted",
    "ThemeMentioned",
    "EntityMentioned",
    "ConceptMentioned",
    "EventMentioned",
    "ContextReset",
    "SermonContextEvent",
]
