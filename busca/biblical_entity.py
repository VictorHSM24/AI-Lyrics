"""BiblicalEntity — modelo de entidade do grafo de conhecimento bíblico.

Define:
  - BiblicalEntityType: enum de tipos de entidade (PARABLE, MIRACLE, PERSON, etc.)
  - BiblicalEntity: DTO imutável representando uma entidade bíblica.

Esta é a evolução natural do conceito genérico da Knowledge Base.
Cada entidade possui:
  - id: identificador único (snake_case)
  - name: nome de exibição
  - type: tipo da entidade (BiblicalEntityType)
  - aliases: apelidos/sinônimos
  - books, chapters: referências bíblicas
  - characters, places, events, themes: elementos narrativos
  - keywords, boost_terms: termos para busca
  - related: IDs de entidades relacionadas (grafo)
  - references: referências bíblicas estruturadas
  - metadata: metadados extras para expansão futura
  - confidence: confiança do match

Design:
  - BiblicalEntity é frozen (imutável).
  - BiblicalEntityType é um enum string (extensível).
  - Novos tipos podem ser adicionados ao enum sem quebrar código existente.
  - O formato JSON é compatível com a versão anterior (campos novos são
    opcionais, campos antigos são preservados).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from busca.bible_reference import BibleReference


class BiblicalEntityType(str, Enum):
    """Tipo de entidade bíblica no grafo de conhecimento.

    Herda de str para serialização JSON direta e comparação com strings.
    Novos tipos podem ser adicionados sem quebrar código existente.

    Valores:
        PERSON: personagem bíblico (ex.: "rei Davi", "profeta Elias").
        PLACE: lugar bíblico (ex.: "monte Sinai", "monte Carmelo").
        EVENT: evento bíblico (ex.: "êxodo", "Pentecostes", "dilúvio").
        PARABLE: parábola de Jesus (ex.: "filho pródigo", "bom samaritano").
        MIRACLE: milagre (ex.: "multiplicação dos pães", "Pedro anda sobre as águas").
        PROPHECY: profecia ou visão profética (ex.: "vale de ossos secos").
        THEME: tema teológico (ex.: "fruto do Espírito").
        OBJECT: objeto bíblico (ex.: "arca de Noé", "torre de Babel").
        SYMBOL: símbolo bíblico (ex.: "pedra angular").
        BOOK: livro bíblico.
        CHAPTER: capítulo bíblico.
        VERSE: versículo bíblico.
        GROUP: grupo de pessoas (ex.: "discípulos", "fariseus").
        DOCTRINE: doutrina ou ensino (ex.: "armadura de Deus").
        METAPHOR: metáfora bíblica (ex.: "videira verdadeira", "bom pastor").
        CEREMONY: cerimônia ou ritual.
        KINGDOM: reino bíblico.
        OUTRO: tipo não classificado.
    """

    PERSON = "PERSON"
    PLACE = "PLACE"
    EVENT = "EVENT"
    PARABLE = "PARABLE"
    MIRACLE = "MIRACLE"
    PROPHECY = "PROPHECY"
    THEME = "THEME"
    OBJECT = "OBJECT"
    SYMBOL = "SYMBOL"
    BOOK = "BOOK"
    CHAPTER = "CHAPTER"
    VERSE = "VERSE"
    GROUP = "GROUP"
    DOCTRINE = "DOCTRINE"
    METAPHOR = "METAPHOR"
    CEREMONY = "CEREMONY"
    KINGDOM = "KINGDOM"
    OUTRO = "OUTRO"

    @classmethod
    def from_string(cls, value: str) -> BiblicalEntityType:
        """Converte string para enum, com fallback para OUTRO.

        Args:
            value: string representando o tipo (ex.: "PARABLE", "parable").

        Returns:
            BiblicalEntityType correspondente, ou OUTRO se não reconhecido.
        """
        if not value:
            return cls.OUTRO
        upper = value.strip().upper()
        try:
            return cls(upper)
        except ValueError:
            # Tentar match case-insensitive
            for member in cls:
                if member.value == upper:
                    return member
            return cls.OUTRO


@dataclass(frozen=True)
class BiblicalEntity:
    """Entidade do grafo de conhecimento bíblico (imutável).

    Evolução do conceito genérico da Knowledge Base. Cada entidade
    representa um conceito bíblico com tipo explícito e relacionamentos.

    Atributos:
        id: identificador único da entidade (snake_case, ex.: "filho_prodigo").
            Obrigatório.
        name: nome de exibição (ex.: "Filho Pródigo"). Obrigatório.
        type: tipo da entidade (BiblicalEntityType). Obrigatório.
        aliases: apelidos/sinônimos para matching.
        books: livros bíblicos relacionados.
        chapters: capítulos relacionados.
        characters: personagens mencionados.
        places: lugares mencionados.
        events: eventos mencionados.
        themes: temas mencionados.
        keywords: termos relevantes para busca FTS.
        boost_terms: termos que devem receber boost no ranking.
        related: IDs de entidades relacionadas (arestas do grafo).
        references: referências bíblicas estruturadas (ex.: "Lucas 15:11-32").
        metadata: metadados extras para expansão futura.
        confidence: confiança do match (0.0 a 1.0).

    Example:
        >>> entity = BiblicalEntity(
        ...     id="filho_prodigo",
        ...     name="Filho Pródigo",
        ...     type=BiblicalEntityType.PARABLE,
        ...     books=("Lucas",),
        ...     chapters=(15,),
        ...     related=("bom_pastor",),
        ... )
        >>> print(entity.id, entity.type)
        filho_prodigo BiblicalEntityType.PARABLE
    """

    id: str
    name: str
    type: BiblicalEntityType = BiblicalEntityType.OUTRO
    aliases: tuple[str, ...] = ()
    books: tuple[str, ...] = ()
    chapters: tuple[int, ...] = ()
    characters: tuple[str, ...] = ()
    places: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    boost_terms: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    references: tuple[BibleReference, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    confidence: float = 0.9

    @property
    def is_valid(self) -> bool:
        """True se a entidade tem id, name e type válidos."""
        return bool(self.id) and bool(self.name) and self.type != BiblicalEntityType.OUTRO or bool(self.id)

    @property
    def related_count(self) -> int:
        """Número de entidades relacionadas."""
        return len(self.related)
