"""sermon/engine.py — SermonMemoryEngine (Sprint 21).

Responsabilidade única:
  Manter o estado da pregação (SermonContext) atualizado incrementalmente.

Regras:
  - Assina SpeechPartial, SpeechPartialUpdated, ReferenceDetected.
  - NÃO consulta LLM, Holyrics, banco ou frontend.
  - NÃO identifica referências bíblicas (isso é papel do parser/semantic).
  - Publica SermonContextUpdated após cada atualização.
  - Publica SermonBookChanged/SermonChapterChanged/SermonTopicChanged
    quando os campos correspondentes mudam.
  - Atualização incremental: nunca reconstrói do zero.
  - Decaimento temporal: entidades e temas perdem peso com o tempo.

Janelas configuráveis (Etapa 8 — Context Window):
  - text_window_seconds: 45s (texto recente para o SemanticEngine)
  - reference_window_seconds: 5min (referências bíblicas recentes)
  - topic_window_seconds: 10min (temas recentes)
  - entity_decay_half_life_s: 120s (meia-vida do decaimento de entidades)

Sprint 21 — Sermon Memory Engine.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from pipeline.events import (
    ReferenceDetected,
    SermonBookChanged,
    SermonChapterChanged,
    SermonContextUpdated,
    SermonTopicChanged,
    SpeechPartial,
    SpeechPartialUpdated,
)
from pipeline.metadata import EventMetadata
from sermon.types import (
    BibleReference,
    EMPTY_SERMON_CONTEXT,
    SermonContext,
    SermonEntity,
    SermonTopic,
)

logger = logging.getLogger(__name__)

__all__ = ["SermonMemoryEngine"]


# ---------------------------------------------------------------------------
# Configuração default (Etapa 8 — Context Windows)
# ---------------------------------------------------------------------------

_DEFAULT_TEXT_WINDOW_S = 45.0
_DEFAULT_REFERENCE_WINDOW_S = 300.0  # 5 min
_DEFAULT_TOPIC_WINDOW_S = 600.0      # 10 min
_DEFAULT_ENTITY_HALF_LIFE_S = 120.0  # 2 min
_DEFAULT_TOPIC_HALF_LIFE_S = 300.0   # 5 min
_DEFAULT_MAX_ENTITIES = 20
_DEFAULT_MAX_TOPICS = 10
_DEFAULT_MAX_REFERENCES = 15
_DEFAULT_MIN_ENTITY_WEIGHT = 0.05
_DEFAULT_MIN_TOPIC_WEIGHT = 0.05
_DEFAULT_CONFIDENCE_DECAY_S = 60.0  # confiança decai 50% a cada 60s sem atualização

# Entidades bíblicas comuns para reconhecimento heurístico leve.
# Não é "mini-LLM" — apenas marcação de menções para alimentar o contexto.
# O SemanticProvider fará a inferência real.
_BIBLICAL_ENTITIES: dict[str, float] = {
    "jesus": 1.0, "cristo": 1.0, "deus": 1.0, "espírito santo": 1.0,
    "nicodemos": 0.9, "paulo": 0.9, "pedro": 0.9, "joão": 0.9,
    "moisés": 0.9, "abrahão": 0.9, "abraão": 0.9, "davi": 0.9,
    "salomão": 0.9, "isaías": 0.9, "jeremias": 0.9,
    "fariseus": 0.7, "saduceus": 0.7, "discípulos": 0.7,
    "jerusalém": 0.7, "belém": 0.7, "galileia": 0.7,
    "egito": 0.7, "babel": 0.7,
}

# Temas comuns (não exaustivo — o LLM pode sugerir outros via SemanticProvider).
# Chaves podem incluir variantes textuais que mapeiam para o mesmo tema canônico.
_BIBLICAL_THEMES: dict[str, float] = {
    "novo nascimento": 0.9, "nascer de novo": 0.9, "nascer do espírito": 0.9,
    "graça": 0.85, "fé": 0.85, "salvação": 0.85,
    "pecado": 0.8, "arrependimento": 0.85, "perdão": 0.85,
    "amor": 0.7, "esperança": 0.75, "ressurreição": 0.9,
    "cruz": 0.85, "sangue": 0.8, "reino": 0.8, "igreja": 0.7,
    "oração": 0.75, "jejum": 0.7, "batismo": 0.85,
    "bom pastor": 0.9, "ovelhas": 0.7, "rebanho": 0.7,
    "guardar o coração": 0.9, "sabedoria": 0.8,
    "criação": 0.8, "dilúvio": 0.85, "aliança": 0.85,
    "sermão do monte": 0.9, "bem-aventuranças": 0.9,
    "parábola": 0.7, "samaritano": 0.85,
}

# Mapeamento de variantes textuais → nome canônico do tema.
# Quando uma variante é detectada, o tema é registrado com o nome canônico.
_THEME_CANONICAL_NAMES: dict[str, str] = {
    "nascer de novo": "Novo nascimento",
    "nascer do espírito": "Novo nascimento",
    "novo nascimento": "Novo nascimento",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _decay_weight(initial: float, age_seconds: float, half_life_s: float) -> float:
    """Decaimento exponencial: peso = initial * 0.5^(age / half_life).

    Etapa 5 — Decaimento temporal.
    """
    if age_seconds <= 0 or half_life_s <= 0:
        return initial
    return initial * math.pow(0.5, age_seconds / half_life_s)


class SermonMemoryEngine:
    """Mantém o SermonContext atualizado incrementalmente.

    Args:
        bus: EventBus para assinar/publicar eventos.
        session_id: ID da sessão atual.
        text_window_seconds: janela de texto recente (default 45s).
        reference_window_seconds: janela de referências (default 300s = 5min).
        topic_window_seconds: janela de temas (default 600s = 10min).
        entity_decay_half_life_s: meia-vida de entidades (default 120s).
        topic_decay_half_life_s: meia-vida de temas (default 300s).
        max_entities: máximo de entidades mantidas (default 20).
        max_topics: máximo de temas mantidos (default 10).
        max_references: máximo de referências mantidas (default 15).
        enabled: kill switch.
    """

    def __init__(
        self,
        bus: Any,
        session_id: str,
        text_window_seconds: float = _DEFAULT_TEXT_WINDOW_S,
        reference_window_seconds: float = _DEFAULT_REFERENCE_WINDOW_S,
        topic_window_seconds: float = _DEFAULT_TOPIC_WINDOW_S,
        entity_decay_half_life_s: float = _DEFAULT_ENTITY_HALF_LIFE_S,
        topic_decay_half_life_s: float = _DEFAULT_TOPIC_HALF_LIFE_S,
        max_entities: int = _DEFAULT_MAX_ENTITIES,
        max_topics: int = _DEFAULT_MAX_TOPICS,
        max_references: int = _DEFAULT_MAX_REFERENCES,
        enabled: bool = True,
    ) -> None:
        self._bus = bus
        self._session_id = session_id
        self._text_window_s = text_window_seconds
        self._ref_window_s = reference_window_seconds
        self._topic_window_s = topic_window_seconds
        self._entity_half_life = entity_decay_half_life_s
        self._topic_half_life = topic_decay_half_life_s
        self._max_entities = max_entities
        self._max_topics = max_topics
        self._max_references = max_references
        self._enabled = enabled

        # Estado interno mutável (o SermonContext exposto é imutável).
        self._context: SermonContext = EMPTY_SERMON_CONTEXT
        self._lock = threading.Lock()

        # Buffer de texto recente (timestamp, text) para janela de texto.
        self._text_buffer: list[tuple[float, str]] = []

        # Métricas (Etapa 10 — Observabilidade).
        self._metrics = {
            "total_updates": 0,
            "book_changes": 0,
            "chapter_changes": 0,
            "topic_changes": 0,
            "entity_expirations": 0,
            "topic_expirations": 0,
            "reference_expirations": 0,
            "started_at": time.time(),
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not self._enabled:
            logger.info("SermonMemoryEngine: disabled, not subscribing")
            return
        self._bus.subscribe(SpeechPartial, self._on_partial)
        self._bus.subscribe(SpeechPartialUpdated, self._on_partial_updated)
        self._bus.subscribe(ReferenceDetected, self._on_reference_detected)
        logger.info(
            "SermonMemoryEngine: started (text_window=%ss, ref_window=%ss, topic_window=%ss)",
            self._text_window_s, self._ref_window_s, self._topic_window_s,
        )

    def stop(self) -> None:
        try:
            self._bus.unsubscribe(SpeechPartial, self._on_partial)
            self._bus.unsubscribe(SpeechPartialUpdated, self._on_partial_updated)
            self._bus.unsubscribe(ReferenceDetected, self._on_reference_detected)
        except Exception:
            pass
        logger.info("SermonMemoryEngine: stopped")

    # ------------------------------------------------------------------
    # Acesso ao contexto
    # ------------------------------------------------------------------

    def get_context(self) -> SermonContext:
        """Retorna o SermonContext atual (imutável)."""
        with self._lock:
            return self._context

    def reset(self) -> None:
        """Reinicia a memória (novo sermão)."""
        with self._lock:
            self._context = EMPTY_SERMON_CONTEXT
            self._text_buffer.clear()
            self._metrics = {
                "total_updates": 0,
                "book_changes": 0,
                "chapter_changes": 0,
                "topic_changes": 0,
                "entity_expirations": 0,
                "topic_expirations": 0,
                "reference_expirations": 0,
                "started_at": time.time(),
            }
        logger.info("SermonMemoryEngine: memory reset")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_partial(self, event: SpeechPartial) -> None:
        self._process_text(event.text, event.meta)

    def _on_partial_updated(self, event: SpeechPartialUpdated) -> None:
        self._process_text(event.text, event.meta)

    def _on_reference_detected(self, event: ReferenceDetected) -> None:
        """Atualiza current_book/current_chapter e adiciona referência histórica."""
        if not self._enabled or not event.book:
            return
        with self._lock:
            self._apply_reference(event)
            self._publish_update(event.meta)

    # ------------------------------------------------------------------
    # Processamento de texto (Etapa 4 — Atualização incremental)
    # ------------------------------------------------------------------

    def _process_text(self, text: str, source_meta: EventMetadata) -> None:
        if not self._enabled or not text or len(text.strip()) < 3:
            return
        text = text.strip()

        with self._lock:
            now_ts = time.time()
            # Adicionar ao buffer de texto.
            self._text_buffer.append((now_ts, text))
            self._prune_text_buffer(now_ts)

            # Extrair entidades e temas do texto.
            new_entities = self._extract_entities(text)
            new_topics = self._extract_topics(text)

            # Atualizar entidades e temas incrementalmente.
            entities_changed = self._merge_entities(new_entities)
            topics_changed = self._merge_topics(new_topics)

            # Aplicar decaimento temporal.
            self._apply_decay()

            # Recalcular confiança.
            self._recompute_confidence()

            # Atualizar probable_theme se houver tema dominante.
            theme_changed = self._maybe_update_theme()

            # Publicar atualização.
            self._metrics["total_updates"] += 1
            self._context = SermonContext(
                current_book=self._context.current_book,
                current_chapter=self._context.current_chapter,
                probable_theme=self._context.probable_theme,
                entities=tuple(self._decay_and_sort_entities()),
                recent_topics=tuple(self._decay_and_sort_topics()),
                recent_references=self._context.recent_references,
                confidence=self._context.confidence,
                updated_at=_now_utc(),
                sermon_started_at=self._context.sermon_started_at,
                total_updates=self._metrics["total_updates"],
            )

        # Publicar eventos (fora do lock para evitar re-entrada).
        self._publish_update(source_meta)
        if theme_changed:
            self._publish_topic_changed(source_meta)

    # ------------------------------------------------------------------
    # Buffer de texto (Etapa 8 — Context Window)
    # ------------------------------------------------------------------

    def _prune_text_buffer(self, now_ts: float) -> None:
        """Remove textos fora da janela de texto."""
        cutoff = now_ts - self._text_window_s
        self._text_buffer = [(ts, t) for ts, t in self._text_buffer if ts >= cutoff]

    def get_recent_text(self, max_chars: int = 500) -> str:
        """Retorna texto recente concatenado (para o SemanticEngine)."""
        with self._lock:
            texts = [t for _, t in self._text_buffer[-10:]]
        joined = " ".join(texts)
        if len(joined) > max_chars:
            joined = joined[-max_chars:]
        return joined

    # ------------------------------------------------------------------
    # Extração heurística leve (NÃO é inferência — apenas marcação)
    # ------------------------------------------------------------------

    def _extract_entities(self, text: str) -> list[str]:
        """Extrai entidades bíblicas mencionadas no texto.

        Heurística simples: substring match case-insensitive contra
        um dicionário de entidades conhecidas. Não é inferência —
        apenas marcação para alimentar o contexto.
        """
        text_lower = text.lower()
        found: list[str] = []
        for entity, _weight in _BIBLICAL_ENTITIES.items():
            if entity in text_lower:
                # Capitalizar primeira letra para exibição.
                found.append(entity.capitalize())
        return found

    def _extract_topics(self, text: str) -> list[str]:
        """Extrai temas bíblicos mencionados no texto.

        Usa nomes canônicos quando a variante tem mapeamento.
        """
        text_lower = text.lower()
        found: list[str] = []
        for topic, _weight in _BIBLICAL_THEMES.items():
            if topic in text_lower:
                canonical = _THEME_CANONICAL_NAMES.get(topic, topic.capitalize())
                found.append(canonical)
        return found

    # ------------------------------------------------------------------
    # Merge incremental (Etapa 4)
    # ------------------------------------------------------------------

    def _merge_entities(self, new_names: list[str]) -> bool:
        """Adiciona ou reforça entidades. Retorna True se houve mudança."""
        if not new_names:
            return False
        now = _now_utc()
        existing = {e.name.lower(): e for e in self._context.entities}
        changed = False
        for name in new_names:
            key = name.lower()
            if key in existing:
                # Reforçar: aumentar peso (até 1.0) e atualizar last_seen.
                old = existing[key]
                new_weight = min(1.0, old.weight + 0.15)
                existing[key] = SermonEntity(
                    name=old.name,
                    weight=new_weight,
                    first_seen=old.first_seen,
                    last_seen=now,
                    mention_count=old.mention_count + 1,
                )
                changed = True
            else:
                existing[key] = SermonEntity(
                    name=name,
                    weight=0.8,
                    first_seen=now,
                    last_seen=now,
                    mention_count=1,
                )
                changed = True
        if changed:
            # Atualizar contexto parcialmente (será consolidado em _process_text).
            self._context = SermonContext(
                current_book=self._context.current_book,
                current_chapter=self._context.current_chapter,
                probable_theme=self._context.probable_theme,
                entities=tuple(existing.values()),
                recent_topics=self._context.recent_topics,
                recent_references=self._context.recent_references,
                confidence=self._context.confidence,
                updated_at=now,
                sermon_started_at=self._context.sermon_started_at,
                total_updates=self._context.total_updates,
            )
        return changed

    def _merge_topics(self, new_names: list[str]) -> bool:
        """Adiciona ou reforça temas. Retorna True se houve mudança."""
        if not new_names:
            return False
        now = _now_utc()
        existing = {t.name.lower(): t for t in self._context.recent_topics}
        changed = False
        for name in new_names:
            key = name.lower()
            if key in existing:
                old = existing[key]
                new_weight = min(1.0, old.weight + 0.2)
                existing[key] = SermonTopic(
                    name=old.name,
                    weight=new_weight,
                    first_seen=old.first_seen,
                    last_seen=now,
                    mention_count=old.mention_count + 1,
                )
                changed = True
            else:
                existing[key] = SermonTopic(
                    name=name,
                    weight=0.7,
                    first_seen=now,
                    last_seen=now,
                    mention_count=1,
                )
                changed = True
        if changed:
            self._context = SermonContext(
                current_book=self._context.current_book,
                current_chapter=self._context.current_chapter,
                probable_theme=self._context.probable_theme,
                entities=self._context.entities,
                recent_topics=tuple(existing.values()),
                recent_references=self._context.recent_references,
                confidence=self._context.confidence,
                updated_at=now,
                sermon_started_at=self._context.sermon_started_at,
                total_updates=self._context.total_updates,
            )
        return changed

    # ------------------------------------------------------------------
    # Decaimento temporal (Etapa 5)
    # ------------------------------------------------------------------

    def _apply_decay(self) -> None:
        """Aplica decaimento temporal a entidades e temas."""
        now = _now_utc()
        # Decair entidades.
        decayed_entities: list[SermonEntity] = []
        expired_entities = 0
        for e in self._context.entities:
            age = (now - e.last_seen).total_seconds()
            new_weight = _decay_weight(e.weight, age, self._entity_half_life)
            if new_weight < _DEFAULT_MIN_ENTITY_WEIGHT:
                expired_entities += 1
                continue
            decayed_entities.append(SermonEntity(
                name=e.name,
                weight=new_weight,
                first_seen=e.first_seen,
                last_seen=e.last_seen,
                mention_count=e.mention_count,
            ))
        # Decair temas.
        decayed_topics: list[SermonTopic] = []
        expired_topics = 0
        for t in self._context.recent_topics:
            age = (now - t.last_seen).total_seconds()
            new_weight = _decay_weight(t.weight, age, self._topic_half_life)
            if new_weight < _DEFAULT_MIN_TOPIC_WEIGHT:
                expired_topics += 1
                continue
            decayed_topics.append(SermonTopic(
                name=t.name,
                weight=new_weight,
                first_seen=t.first_seen,
                last_seen=t.last_seen,
                mention_count=t.mention_count,
            ))
        # Decair referências (remover fora da janela).
        ref_cutoff = now.timestamp() - self._ref_window_s
        kept_refs: list[BibleReference] = []
        expired_refs = 0
        for r in self._context.recent_references:
            if r.detected_at.timestamp() >= ref_cutoff:
                kept_refs.append(r)
            else:
                expired_refs += 1

        self._metrics["entity_expirations"] += expired_entities
        self._metrics["topic_expirations"] += expired_topics
        self._metrics["reference_expirations"] += expired_refs

        self._context = SermonContext(
            current_book=self._context.current_book,
            current_chapter=self._context.current_chapter,
            probable_theme=self._context.probable_theme,
            entities=tuple(decayed_entities),
            recent_topics=tuple(decayed_topics),
            recent_references=tuple(kept_refs),
            confidence=self._context.confidence,
            updated_at=now,
            sermon_started_at=self._context.sermon_started_at,
            total_updates=self._context.total_updates,
        )

    def _decay_and_sort_entities(self) -> list[SermonEntity]:
        """Ordena entidades por peso (decrescente) e limita ao máximo."""
        sorted_e = sorted(self._context.entities, key=lambda e: e.weight, reverse=True)
        return sorted_e[:self._max_entities]

    def _decay_and_sort_topics(self) -> list[SermonTopic]:
        """Ordena temas por peso (decrescente) e limita ao máximo."""
        sorted_t = sorted(self._context.recent_topics, key=lambda t: t.weight, reverse=True)
        return sorted_t[:self._max_topics]

    # ------------------------------------------------------------------
    # Confiança e tema provável
    # ------------------------------------------------------------------

    def _recompute_confidence(self) -> None:
        """Recalcula a confiança geral do contexto.

        Fatores:
          - Presença de livro atual: +0.3
          - Presença de capítulo atual: +0.2
          - Entidades com peso > 0.5: +0.2 (até limite)
          - Temas com peso > 0.5: +0.2 (até limite)
          - Referências recentes: +0.1
          - Decaimento por idade: -10% a cada 60s sem atualização
        """
        base = 0.0
        if self._context.current_book:
            base += 0.3
        if self._context.current_chapter:
            base += 0.2
        strong_entities = sum(1 for e in self._context.entities if e.weight > 0.5)
        if strong_entities > 0:
            base += min(0.2, strong_entities * 0.05)
        strong_topics = sum(1 for t in self._context.recent_topics if t.weight > 0.5)
        if strong_topics > 0:
            base += min(0.2, strong_topics * 0.07)
        if self._context.recent_references:
            base += 0.1
        # Decaimento por idade.
        age_s = (_now_utc() - self._context.updated_at).total_seconds()
        decay = _decay_weight(1.0, age_s, _DEFAULT_CONFIDENCE_DECAY_S)
        confidence = base * decay
        confidence = max(0.0, min(1.0, confidence))
        self._context = SermonContext(
            current_book=self._context.current_book,
            current_chapter=self._context.current_chapter,
            probable_theme=self._context.probable_theme,
            entities=self._context.entities,
            recent_topics=self._context.recent_topics,
            recent_references=self._context.recent_references,
            confidence=confidence,
            updated_at=_now_utc(),
            sermon_started_at=self._context.sermon_started_at,
            total_updates=self._context.total_updates,
        )

    def _maybe_update_theme(self) -> bool:
        """Atualiza probable_theme se houver tema dominante claro.

        Retorna True se mudou.
        """
        if not self._context.recent_topics:
            return False
        # Tema dominante = maior peso, com peso > 0.5.
        top = max(self._context.recent_topics, key=lambda t: t.weight)
        if top.weight < 0.5:
            return False
        # Capitalizar primeira letra.
        new_theme = top.name.capitalize()
        if self._context.probable_theme == new_theme:
            return False
        old_theme = self._context.probable_theme
        self._context = SermonContext(
            current_book=self._context.current_book,
            current_chapter=self._context.current_chapter,
            probable_theme=new_theme,
            entities=self._context.entities,
            recent_topics=self._context.recent_topics,
            recent_references=self._context.recent_references,
            confidence=self._context.confidence,
            updated_at=_now_utc(),
            sermon_started_at=self._context.sermon_started_at,
            total_updates=self._context.total_updates,
        )
        self._metrics["topic_changes"] += 1
        return True

    # ------------------------------------------------------------------
    # Referência detectada
    # ------------------------------------------------------------------

    def _apply_reference(self, event: ReferenceDetected) -> None:
        """Atualiza current_book/current_chapter e adiciona referência histórica."""
        now = _now_utc()
        old_book = self._context.current_book
        old_chapter = self._context.current_chapter

        # Determinar origem da referência.
        source = "semantic" if event.meta.origin == "ReferenceResolver" else "parser"

        # Adicionar referência histórica (no início, mais recente primeiro).
        new_ref = BibleReference(
            book=event.book,
            chapter=event.chapter,
            verse=event.verse_start,
            detected_at=now,
            source=source,
        )
        # Evitar duplicatas exatas consecutivas.
        refs = list(self._context.recent_references)
        if not (refs and refs[0].book == new_ref.book
                and refs[0].chapter == new_ref.chapter
                and refs[0].verse == new_ref.verse):
            refs.insert(0, new_ref)
        # Limitar e aplicar janela.
        refs = refs[:self._max_references]
        ref_cutoff = now.timestamp() - self._ref_window_s
        refs = [r for r in refs if r.detected_at.timestamp() >= ref_cutoff]

        # Atualizar livro/capítulo atuais.
        new_book = event.book
        new_chapter = event.chapter if event.chapter > 0 else old_chapter

        book_changed = new_book != old_book
        chapter_changed = (new_book == old_book) and (new_chapter != old_chapter)

        if book_changed:
            self._metrics["book_changes"] += 1
        if chapter_changed:
            self._metrics["chapter_changes"] += 1

        self._context = SermonContext(
            current_book=new_book,
            current_chapter=new_chapter,
            probable_theme=self._context.probable_theme,
            entities=self._context.entities,
            recent_topics=self._context.recent_topics,
            recent_references=tuple(refs),
            confidence=self._context.confidence,
            updated_at=now,
            sermon_started_at=self._context.sermon_started_at,
            total_updates=self._metrics["total_updates"],
        )

        # Publicar eventos de mudança (fora do lock — chamador já tem lock,
        # mas publish é síncrono e pode reentrar em outros handlers; isso é
        # seguro porque não há reentrância no próprio SermonMemoryEngine).
        if book_changed:
            self._publish_book_changed(event.meta, old_book or "", new_book)
        if chapter_changed:
            self._publish_chapter_changed(event.meta, new_book, old_chapter or 0, new_chapter or 0)

    # ------------------------------------------------------------------
    # Publicação de eventos
    # ------------------------------------------------------------------

    def _publish_update(self, source_meta: EventMetadata) -> None:
        """Publica SermonContextUpdated."""
        ctx = self._context
        meta = EventMetadata.for_next(
            previous=source_meta,
            origin="SermonMemoryEngine",
        )
        event = SermonContextUpdated(
            meta=meta,
            context_json=json.dumps(ctx.to_dict(), ensure_ascii=False),
            current_book=ctx.current_book or "",
            current_chapter=ctx.current_chapter or 0,
            probable_theme=ctx.probable_theme or "",
            num_entities=len(ctx.entities),
            num_topics=len(ctx.recent_topics),
            num_references=len(ctx.recent_references),
            confidence=round(ctx.confidence, 4),
            total_updates=ctx.total_updates,
            is_empty=ctx.is_empty,
        )
        self._bus.publish(event)

    def _publish_book_changed(
        self, source_meta: EventMetadata, previous: str, new: str
    ) -> None:
        meta = EventMetadata.for_next(
            previous=source_meta,
            origin="SermonMemoryEngine",
        )
        self._bus.publish(SermonBookChanged(
            meta=meta,
            previous_book=previous,
            new_book=new,
            confidence=self._context.confidence,
        ))

    def _publish_chapter_changed(
        self, source_meta: EventMetadata, book: str, previous: int, new: int
    ) -> None:
        meta = EventMetadata.for_next(
            previous=source_meta,
            origin="SermonMemoryEngine",
        )
        self._bus.publish(SermonChapterChanged(
            meta=meta,
            book=book,
            previous_chapter=previous,
            new_chapter=new,
        ))

    def _publish_topic_changed(self, source_meta: EventMetadata) -> None:
        meta = EventMetadata.for_next(
            previous=source_meta,
            origin="SermonMemoryEngine",
        )
        # Tema atual já foi atualizado em _maybe_update_theme.
        # Para publicar o tema anterior, precisaríamos ter guardado —
        # por simplicidade, publicamos apenas o novo.
        self._bus.publish(SermonTopicChanged(
            meta=meta,
            previous_theme="",  # não rastreado nesta iteração
            new_theme=self._context.probable_theme or "",
            confidence=self._context.confidence,
        ))

    # ------------------------------------------------------------------
    # Métricas (Etapa 10 — Observabilidade)
    # ------------------------------------------------------------------

    def metrics(self) -> dict[str, Any]:
        """Retorna métricas operacionais."""
        with self._lock:
            ctx = self._context
            uptime = time.time() - self._metrics["started_at"]
            updates_per_min = (
                self._metrics["total_updates"] / max(uptime / 60.0, 0.0167)
            )
            return {
                "total_updates": self._metrics["total_updates"],
                "updates_per_minute": round(updates_per_min, 2),
                "book_changes": self._metrics["book_changes"],
                "chapter_changes": self._metrics["chapter_changes"],
                "topic_changes": self._metrics["topic_changes"],
                "entity_expirations": self._metrics["entity_expirations"],
                "topic_expirations": self._metrics["topic_expirations"],
                "reference_expirations": self._metrics["reference_expirations"],
                "uptime_seconds": round(uptime, 1),
                "memory_size": {
                    "entities": len(ctx.entities),
                    "topics": len(ctx.recent_topics),
                    "references": len(ctx.recent_references),
                    "text_buffer": len(self._text_buffer),
                },
                "context_age_seconds": round(ctx.age_seconds, 1),
                "sermon_duration_seconds": round(ctx.sermon_duration_seconds, 1),
                "confidence": round(ctx.confidence, 4),
                "enabled": self._enabled,
            }
