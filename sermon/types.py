"""sermon/types.py — Tipos da memória de sermão (Sprint 21).

Responsabilidade:
  - Definir BibleReference (referência bíblica histórica).
  - Definir SermonEntity (entidade reconhecida com peso/idade).
  - Definir SermonTopic (tema provável com peso/idade).
  - Definir SermonContext (memória viva da pregação).

Estes tipos são IMUTÁVEIS (frozen dataclasses) e serializáveis.
Não dependem de nenhum outro módulo do AI Lyrics.

Sprint 21 — Sermon Memory Engine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


__all__ = [
    "BibleReference",
    "SermonEntity",
    "SermonTopic",
    "SermonContext",
    "EMPTY_SERMON_CONTEXT",
]


def _now_utc() -> datetime:
    """Timestamp UTC atual."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# BibleReference — referência bíblica histórica
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BibleReference:
    """Referência bíblica detectada durante o sermão.

    Atributos:
        book: nome canônico do livro ("João").
        chapter: capítulo (0 se desconhecido).
        verse: versículo (0 se capítulo inteiro).
        detected_at: timestamp UTC da detecção.
        source: origem ("parser" | "semantic" | "manual").
    """

    book: str = ""
    chapter: int = 0
    verse: int = 0
    detected_at: datetime = field(default_factory=_now_utc)
    source: str = "parser"

    @property
    def reference_str(self) -> str:
        if self.verse > 0:
            return f"{self.book} {self.chapter}:{self.verse}"
        if self.chapter > 0:
            return f"{self.book} {self.chapter}"
        return self.book

    def to_dict(self) -> dict[str, Any]:
        return {
            "book": self.book,
            "chapter": self.chapter,
            "verse": self.verse,
            "detected_at": self.detected_at.isoformat(),
            "source": self.source,
            "reference_str": self.reference_str,
        }


# ---------------------------------------------------------------------------
# SermonEntity — entidade reconhecida com peso temporal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SermonEntity:
    """Entidade mencionada no sermão (pessoa, lugar, conceito).

    O peso decai com o tempo (Etapa 5 — Decaimento temporal).

    Atributos:
        name: nome da entidade ("Jesus", "Nicodemos", "Jerusalém").
        weight: peso atual [0.0, 1.0] — decai com o tempo.
        first_seen: timestamp UTC da primeira menção.
        last_seen: timestamp UTC da última menção.
        mention_count: número de menções.
    """

    name: str = ""
    weight: float = 1.0
    first_seen: datetime = field(default_factory=_now_utc)
    last_seen: datetime = field(default_factory=_now_utc)
    mention_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weight": round(self.weight, 4),
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "mention_count": self.mention_count,
        }


# ---------------------------------------------------------------------------
# SermonTopic — tema provável com peso temporal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SermonTopic:
    """Tema provável do sermão.

    Atributos:
        name: nome do tema ("Novo nascimento", "Graça", "Fé").
        weight: peso atual [0.0, 1.0] — decai com o tempo.
        first_seen: timestamp UTC.
        last_seen: timestamp UTC.
        mention_count: número de menções.
    """

    name: str = ""
    weight: float = 1.0
    first_seen: datetime = field(default_factory=_now_utc)
    last_seen: datetime = field(default_factory=_now_utc)
    mention_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weight": round(self.weight, 4),
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "mention_count": self.mention_count,
        }


# ---------------------------------------------------------------------------
# SermonContext — memória viva da pregação
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SermonContext:
    """Memória viva da pregação (Sprint 21).

    Objeto IMUTÁVEL. Atualizações geram novas instâncias via
    SermonMemoryEngine.apply_*().

    Atributos:
        current_book: livro atual do sermão ("João") ou None.
        current_chapter: capítulo atual ou None.
        probable_theme: tema provável ("Novo nascimento") ou None.
        entities: entidades reconhecidas (ordenadas por peso decrescente).
        recent_topics: temas recentes (ordenados por peso decrescente).
        recent_references: referências bíblicas recentes (mais recente primeiro).
        confidence: confiança geral do contexto [0.0, 1.0].
        updated_at: timestamp UTC da última atualização.
        sermon_started_at: timestamp UTC do início do sermão.
        total_updates: número total de atualizações.
    """

    current_book: str | None = None
    current_chapter: int | None = None
    probable_theme: str | None = None
    entities: tuple[SermonEntity, ...] = field(default_factory=tuple)
    recent_topics: tuple[SermonTopic, ...] = field(default_factory=tuple)
    recent_references: tuple[BibleReference, ...] = field(default_factory=tuple)
    confidence: float = 0.0
    updated_at: datetime = field(default_factory=_now_utc)
    sermon_started_at: datetime = field(default_factory=_now_utc)
    total_updates: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_book": self.current_book,
            "current_chapter": self.current_chapter,
            "probable_theme": self.probable_theme,
            "entities": [e.to_dict() for e in self.entities],
            "recent_topics": [t.to_dict() for t in self.recent_topics],
            "recent_references": [r.to_dict() for r in self.recent_references],
            "confidence": round(self.confidence, 4),
            "updated_at": self.updated_at.isoformat(),
            "sermon_started_at": self.sermon_started_at.isoformat(),
            "total_updates": self.total_updates,
        }

    @property
    def is_empty(self) -> bool:
        """True se o contexto ainda não foi populado."""
        return (
            self.current_book is None
            and self.current_chapter is None
            and self.probable_theme is None
            and len(self.entities) == 0
            and len(self.recent_topics) == 0
            and len(self.recent_references) == 0
        )

    @property
    def age_seconds(self) -> float:
        """Segundos desde a última atualização."""
        return (_now_utc() - self.updated_at).total_seconds()

    @property
    def sermon_duration_seconds(self) -> float:
        """Duração total do sermão em segundos."""
        return (_now_utc() - self.sermon_started_at).total_seconds()

    @property
    def top_entities(self, limit: int = 5) -> tuple[SermonEntity, ...]:
        """Top-N entidades por peso."""
        return tuple(sorted(self.entities, key=lambda e: e.weight, reverse=True)[:limit])

    @property
    def top_topics(self, limit: int = 3) -> tuple[SermonTopic, ...]:
        """Top-N temas por peso."""
        return tuple(sorted(self.recent_topics, key=lambda t: t.weight, reverse=True)[:limit])


# Instância vazia reutilizável.
EMPTY_SERMON_CONTEXT = SermonContext()
