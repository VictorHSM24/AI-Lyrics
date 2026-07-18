"""SermonContext — DTO imutável representando o estado do sermão.

O SermonContext é o estado completo do sermão em andamento. Ele contém
apenas informações de contexto — não executa buscas, não interpreta
intenção, não conversa com sistemas externos.

Design:
  - frozen dataclass (imutável).
  - Todas as coleções são tuples (imutáveis).
  - Nenhuma lista mutável.
  - Nenhum estado global.
  - Atualizações retornam um novo SermonContext (nunca modificam o atual).

Atributos:
  - book: livro ativo atual (ex.: "João") ou None.
  - book_id: ID do livro ativo (1..66) ou None.
  - chapter: capítulo ativo atual ou None.
  - last_reference: última referência resolvida (BibleReference) ou None.
  - recent_references: últimas N referências (mais recente primeiro).
  - recent_books: últimos N livros mencionados (mais recente primeiro).
  - recent_themes: últimos N temas mencionados ( mais recente primeiro).
  - recent_characters: últimos N personagens mencionados.
  - recent_concepts: últimos N conceitos mencionados (IDs do Knowledge Graph).
  - recent_events: últimos N eventos mencionados.
  - update_count: número de atualizações desde o último reset.
  - last_book_update: contador da última atualização que mencionou o livro ativo.
  - last_theme_update: contador da última atualização de tema.
  - last_character_update: contador da última atualização de personagem.
  - last_concept_update: contador da última atualização de conceito.
  - last_event_update: contador da última atualização de evento.

Compatibilidade futura:
  - Os contadores last_*_update permitem expiração natural baseada em
    "quantas atualizações desde a última menção".
  - A estrutura suporta o futuro Streaming Speech Pipeline, onde eventos
    como BOOK_DETECTED, CHAPTER_DETECTED, etc. serão emitidos em tempo real.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from busca.bible_reference import BibleReference


@dataclass(frozen=True)
class SermonContext:
    """Estado imutável do sermão em andamento.

    Todas as atualizações retornam um novo SermonContext via
    ``dataclasses.replace()``. O contexto anterior permanece válido.

    Atributos:
        book: nome do livro ativo (ex.: "João") ou None se nenhum.
        book_id: ID do livro ativo (1..66) ou None.
        chapter: capítulo ativo ou None.
        last_reference: última BibleReference resolvida ou None.
        recent_references: tuple de BibleReference (mais recente primeiro).
        recent_books: tuple de nomes de livros (mais recente primeiro,
            sem duplicatas consecutivas).
        recent_themes: tuple de temas (mais recente primeiro).
        recent_characters: tuple de personagens (mais recente primeiro).
        recent_concepts: tuple de IDs de conceitos (mais recente primeiro).
        recent_events: tuple de eventos (mais recente primeiro).
        update_count: total de atualizações desde o reset.
        last_book_update: update_count quando o livro ativo foi mencionado.
        last_chapter_update: update_count quando o capítulo foi mencionado.
        last_theme_update: update_count quando o último tema foi adicionado.
        last_character_update: update_count do último personagem.
        last_concept_update: update_count do último conceito.
        last_event_update: update_count do último evento.
        created_at: timestamp de criação (segundos desde epoch) ou 0.
        updated_at: timestamp da última atualização ou 0.
    """

    # --- Estado ativo ---
    book: str | None = None
    book_id: int | None = None
    chapter: int | None = None
    last_reference: BibleReference | None = None

    # --- Histórico recente (mais recente primeiro) ---
    recent_references: tuple = field(default_factory=tuple)  # tuple[BibleReference, ...]
    recent_books: tuple[str, ...] = field(default_factory=tuple)
    recent_themes: tuple[str, ...] = field(default_factory=tuple)
    recent_characters: tuple[str, ...] = field(default_factory=tuple)
    recent_concepts: tuple[str, ...] = field(default_factory=tuple)
    recent_events: tuple[str, ...] = field(default_factory=tuple)

    # --- Contadores para expiração ---
    update_count: int = 0
    last_book_update: int = 0
    last_chapter_update: int = 0
    last_theme_update: int = 0
    last_character_update: int = 0
    last_concept_update: int = 0
    last_event_update: int = 0

    # --- Timestamps ---
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def is_empty(self) -> bool:
        """True se o contexto está vazio (recém-criado ou resetado)."""
        return (
            self.book is None
            and self.chapter is None
            and self.last_reference is None
            and not self.recent_references
            and not self.recent_books
            and not self.recent_themes
            and not self.recent_characters
            and not self.recent_concepts
            and not self.recent_events
        )

    @property
    def has_active_book(self) -> bool:
        """True se há um livro ativo (não expirado)."""
        return self.book is not None

    @property
    def has_active_chapter(self) -> bool:
        """True se há um capítulo ativo."""
        return self.chapter is not None

    @property
    def has_active_reference(self) -> bool:
        """True se há uma referência ativa."""
        return self.last_reference is not None

    def to_dict(self) -> dict:
        """Serializa para dict (para debug, log, persistência futura).

        BibleReference é serializada via to_string() para legibilidade.
        """
        return {
            "book": self.book,
            "book_id": self.book_id,
            "chapter": self.chapter,
            "last_reference": self.last_reference.to_string() if self.last_reference else None,
            "recent_references": [
                r.to_string() if hasattr(r, "to_string") else str(r)
                for r in self.recent_references
            ],
            "recent_books": list(self.recent_books),
            "recent_themes": list(self.recent_themes),
            "recent_characters": list(self.recent_characters),
            "recent_concepts": list(self.recent_concepts),
            "recent_events": list(self.recent_events),
            "update_count": self.update_count,
            "last_book_update": self.last_book_update,
            "last_chapter_update": self.last_chapter_update,
            "last_theme_update": self.last_theme_update,
            "last_character_update": self.last_character_update,
            "last_concept_update": self.last_concept_update,
            "last_event_update": self.last_event_update,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def with_update(self, **changes) -> SermonContext:
        """Cria um novo SermonContext com mudanças aplicadas.

        Incrementa update_count automaticamente. Não modifica o contexto atual.

        Args:
            **changes: campos a alterar no novo contexto.

        Returns:
            Novo SermonContext com as mudanças aplicadas.
        """
        new_count = self.update_count + 1
        return replace(
            self,
            update_count=new_count,
            updated_at=changes.pop("updated_at", self.updated_at),
            **changes,
        )
