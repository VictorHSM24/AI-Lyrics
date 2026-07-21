"""sermon — Memória de contexto contínua da pregação (Sprint 21).

Arquitetura:
    SpeechPartial / SpeechPartialUpdated / ReferenceDetected
            │
            ▼
    SermonMemoryEngine (atualiza SermonContext incrementalmente)
            │
            ├─ publica SermonContextUpdated (a cada atualização)
            ├─ publica SermonBookChanged (quando livro muda)
            ├─ publica SermonChapterChanged (quando capítulo muda)
            └─ publica SermonTopicChanged (quando tema muda)
                    │
                    ▼
    SemanticEngine (consome SermonContextUpdated para enriquecer contexto)

Componentes:
  - types.py: BibleReference, SermonEntity, SermonTopic, SermonContext
  - engine.py: SermonMemoryEngine

Sprint 21 — Sermon Memory Engine.
"""

from sermon.types import (
    BibleReference,
    EMPTY_SERMON_CONTEXT,
    SermonContext,
    SermonEntity,
    SermonTopic,
)
from sermon.engine import SermonMemoryEngine

__all__ = [
    "BibleReference",
    "EMPTY_SERMON_CONTEXT",
    "SermonContext",
    "SermonEntity",
    "SermonTopic",
    "SermonMemoryEngine",
]
