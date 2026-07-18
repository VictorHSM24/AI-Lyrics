"""Eventos tipados para o Sermon Context Engine.

Os eventos representam mudanças de estado do sermão — não comandos.
Eles são emitidos pelo pipeline (atualmente não conectado) e processados
pelo SermonContextEngine para evoluir o contexto.

Design:
  - Todos os eventos são frozen dataclasses (imutáveis).
  - Cada evento carrega apenas os dados necessários para atualizar o contexto.
  - Eventos não conhecem o SermonContext — apenas o engine os processa.
  - Novos eventos podem ser adicionados sem quebrar eventos existentes.

Compatibilidade futura (Streaming Speech Pipeline):
  Os eventos atuais são de alto nível (ReferenceResolved, BookChanged).
  No futuro, eventos de baixo nível serão emitidos pelo streaming:
    - BOOK_DETECTED
    - CHAPTER_DETECTED
    - VERSE_DETECTED
    - REFERENCE_COMPLETED
    - CONCEPT_DETECTED
    - THEME_DETECTED
  Estes eventos de baixo nível poderão ser agregados em eventos de alto
  nível antes de chegar ao Context Engine, ou o engine poderá processá-los
  diretamente. A arquitetura suporta ambas as evoluções.

Eventos implementados:
  - BookChanged: livro ativo mudou.
  - ChapterChanged: capítulo ativo mudou.
  - ReferenceResolved: referência bíblica completa foi resolvida.
  - ReferenceRepeated: referência repetida (ex.: "aquele versículo").
  - ReferenceCompleted: referência foi completada (ex.: "versículo 16" após "João 3").
  - ThemeMentioned: tema mencionado.
  - EntityMentioned: personagem/lugar mencionado.
  - ConceptMentioned: conceito do Knowledge Graph mencionado.
  - EventMentioned: evento bíblico mencionado.
  - ContextReset: contexto reiniciado completamente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from busca.bible_reference import BibleReference


# ---------------------------------------------------------------------------
# Evento base (apenas para type hints — não é usado diretamente)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextEvent:
    """Base abstrata para eventos de contexto.

    Todos os eventos herdam desta classe. O campo `timestamp` é opcional
    e pode ser usado para ordenação cronológica no futuro.
    """

    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# Eventos de referência e livro
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BookChanged(ContextEvent):
    """Livro ativo mudou.

    Emitido quando o usuário menciona um livro explicitamente.
    Ex.: "Abram em João" → BookChanged(book="João", book_id=43).

    Atributos:
        book: nome canônico do livro (ex.: "João").
        book_id: ID do livro (1..66).
    """

    book: str = ""
    book_id: int = 0


@dataclass(frozen=True)
class ChapterChanged(ContextEvent):
    """Capítulo ativo mudou.

    Emitido quando o usuário menciona um capítulo.
    Ex.: "capítulo três" → ChapterChanged(chapter=3).

    Pode ser emitido isoladamente (capítulo do livro ativo) ou junto
    com BookChanged.

    Atributos:
        chapter: número do capítulo.
    """

    chapter: int = 0


@dataclass(frozen=True)
class ReferenceResolved(ContextEvent):
    """Referência bíblica completa foi resolvida.

    Emitido quando uma referência completa é identificada.
    Ex.: "João 3:16" → ReferenceResolved(reference=BibleReference(João, 3, 16)).

    Atributos:
        reference: BibleReference resolvida.
    """

    reference: BibleReference | None = None


@dataclass(frozen=True)
class ReferenceRepeated(ContextEvent):
    """Referência repetida (ex.: "aquele versículo", "volta naquele texto").

    Indica que o usuário está se referindo à referência anterior.
    O engine deve manter a referência ativa.

    Atributos:
        hint: texto do usuário (ex.: "aquele versículo") — apenas para log.
    """

    hint: str = ""


@dataclass(frozen=True)
class ReferenceCompleted(ContextEvent):
    """Referência foi completada a partir do contexto ativo.

    Ex.: "João 3" (BookChanged + ChapterChanged) seguido de "versículo 16"
    → ReferenceCompleted(reference=BibleReference(João, 3, 16)).

    Atributos:
        reference: BibleReference completada.
    """

    reference: BibleReference | None = None


# ---------------------------------------------------------------------------
# Eventos de temas, entidades, conceitos, eventos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThemeMentioned(ContextEvent):
    """Tema mencionado no sermão.

    Ex.: "armadura de Deus", "capacete da salvação", "espada do Espírito".

    Atributos:
        theme: nome do tema.
    """

    theme: str = ""


@dataclass(frozen=True)
class EntityMentioned(ContextEvent):
    """Personagem ou lugar mencionado.

    Ex.: "Pedro", "Jesus", "monte Sinai", "Betel".

    Atributos:
        name: nome do personagem ou lugar.
        entity_type: "person" ou "place" (para futura distinção).
    """

    name: str = ""
    entity_type: str = ""  # "person" | "place" | ""


@dataclass(frozen=True)
class ConceptMentioned(ContextEvent):
    """Conceito do Knowledge Graph mencionado.

    Ex.: "filho pródigo", "bom pastor", "Pentecostes".

    Atributos:
        concept_id: ID do conceito no Knowledge Graph (ex.: "filho_prodigo").
        concept_name: nome de exibição do conceito.
    """

    concept_id: str = ""
    concept_name: str = ""


@dataclass(frozen=True)
class EventMentioned(ContextEvent):
    """Evento bíblico mencionado.

    Ex.: "parábola do filho pródigo", "multiplicação dos pães".

    Atributos:
        event: nome do evento.
    """

    event: str = ""


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextReset(ContextEvent):
    """Contexto reiniciado completamente.

    Emitido entre sermões ou quando o usuário explicitamente pede reset.
    O engine retorna um SermonContext vazio.
    """

    reason: str = ""


# ---------------------------------------------------------------------------
# Union de todos os eventos (para type hints)
# ---------------------------------------------------------------------------


SermonContextEvent = Union[
    BookChanged,
    ChapterChanged,
    ReferenceResolved,
    ReferenceRepeated,
    ReferenceCompleted,
    ThemeMentioned,
    EntityMentioned,
    ConceptMentioned,
    EventMentioned,
    ContextReset,
]


__all__ = [
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
