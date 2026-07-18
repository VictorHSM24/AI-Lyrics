"""Módulo de estado da Bíblia (navegação e persistência).

API pública:
    BibleStateManager — gerencia estado e resolve navegação.
    BibleState — estado atual (book_id, chapter, verse, version).
    BibleStructure — limites de capítulo/versículo por livro.
    HistoryEntry — entrada do histórico de navegação.
    load_bible_structure — carrega estrutura de um DB FTS5.
"""

from estado.state import (
    BibleState,
    BibleStateManager,
    BibleStructure,
    HistoryEntry,
    load_bible_structure,
)

__all__ = [
    "BibleStateManager",
    "BibleState",
    "BibleStructure",
    "HistoryEntry",
    "load_bible_structure",
]
