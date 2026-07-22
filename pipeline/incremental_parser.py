"""IncrementalBiblicalParser — parser incremental de referências (Sprint 19).

Responsabilidade:
  - Consumir SpeechPartial / SpeechPartialUpdated do StreamingSTTService.
  - Manter estado incremental: book → chapter → verse.
  - Publicar ReferenceCandidate (confiança crescente).
  - Publicar ReferenceDetected quando confidence >= threshold.

Sprint 19 — Streaming Speech Pipeline:
  Diferente do Parser determinístico (que processa texto completo
  e é stateless), este parser evolui estado a cada SpeechPartialUpdated.

  Exemplo:
    "joão"                          → ReferenceCandidate(book=João, conf=0.40)
    "joão capítulo três"            → ReferenceCandidate(book=João, chapter=3, conf=0.75)
    "joão capítulo três versículo dezesseis"
                                    → ReferenceDetected(book=João, chapter=3, verse=16, conf=0.98)

  O parser NUNCA chama Holyrics diretamente. Quando publica
  ReferenceDetected, o VersePresentationService existente cuida
  da apresentação.

Evitar retrabalho (Etapa 7):
  O parser mantém estado entre chamadas. Quando recebe
  SpeechPartialUpdated com appended_text, apenas processa o
  trecho novo — não reprocessa o texto já visto.

  Estado mantido:
    - _current_book: Book identificado (ou None)
    - _current_chapter: capítulo identificado (ou None)
    - _current_verse: versículo identificado (ou None)
    - _seen_text: texto já processado (para evitar reprocessar)
    - _expecting: o que o parser espera a seguir ("book" | "chapter" | "verse" | "done")

Thread Safety:
  - O parser é chamado na thread do StreamingSTTService (via EventBus).
  - Como mantém estado, NÃO é stateless — uma instância por fluxo.
  - O BiblicalNLUService existente (stateless) continua processando
    SpeechTranscribed em paralelo, sem interferir.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from core.types import Intent
from parser.books import BookResolveResult, ParserBookTable
from parser.normalizer import Normalizer
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    ReferenceAntecipada,
    ReferenceCandidate,
    ReferenceDetected,
    SpeechPartial,
    SpeechPartialUpdated,
)
from pipeline.metadata import EventMetadata

logger = logging.getLogger(__name__)

__all__ = ["IncrementalBiblicalParser"]

# Marcadores (mesmos do parser determinístico).
_CHAPTER_MARKERS = frozenset({"capitulo", "cap"})
_VERSE_MARKERS = frozenset({"versiculo", "vers", "v"})

# Confianças por nível de completude.
_C_BOOK_ONLY = 0.40
_C_BOOK_CHAPTER = 0.75
_C_BOOK_CHAPTER_VERSE = 0.98

# Threshold para publicar ReferenceDetected (vs ReferenceCandidate).
_DETECTION_THRESHOLD = 0.90

# Sprint 21.4 — Streaming First.
# Threshold para publicar ReferenceAntecipada (apresentação antecipada
# no Holyrics durante a fala, antes do silêncio fechar o segmento).
# Conforme decisão do usuário: só antecipa a partir de "chapter"
# (confidence 0.75). Book-only (0.40) é muito incerto.
_DEFAULT_ANTICIPATION_THRESHOLD = 0.60

# Marcadores de capítulo/versículo por extenso.
_CHAPTER_EXTENSO = frozenset({"cap", "capitulo", "capitulo:"})
_VERSE_EXTENSO = frozenset({"vers", "versiculo", "versiculo:", "v"})


class IncrementalBiblicalParser:
    """Parser incremental que evolui estado a cada SpeechPartial.

    Args:
        books: ParserBookTable para resolução de livros.
        normalizer: Normalizer para normalizar texto (criado internamente
            se omitido).
        bus: PipelineEventBus para publicar eventos.
        session_id: ID da sessão atual.
        threshold: confiança mínima para publicar ReferenceDetected
            (default 0.90). Abaixo disso, publica ReferenceCandidate.

    Lifecycle:
        start() — inscreve em SpeechPartial e SpeechPartialUpdated.
        stop()  — desinscreve (marca como parado).
        reset() — reseta estado incremental (chamado a novo fluxo).
    """

    def __init__(
        self,
        books: ParserBookTable,
        bus: PipelineEventBus,
        session_id: str,
        normalizer: Normalizer | None = None,
        threshold: float = _DETECTION_THRESHOLD,
        anticipation_threshold: float = _DEFAULT_ANTICIPATION_THRESHOLD,
    ) -> None:
        self._books = books
        self._norm = normalizer or Normalizer()
        self._bus = bus
        self._session_id = session_id
        self._threshold = threshold
        # Sprint 21.4 — Streaming First.
        # Threshold para publicar ReferenceAntecipada (apresentação
        # antecipada no Holyrics durante a fala). Conforme decisão do
        # usuário: só antecipa a partir de "chapter" (confidence 0.75).
        self._anticipation_threshold = anticipation_threshold
        self._subscribed = False

        # Estado incremental.
        self._current_book: BookResolveResult | None = None
        self._current_chapter: int | None = None
        self._current_verse: int | None = None
        self._seen_text: str = ""
        self._correlation_id: str | None = None
        self._causation_id: str | None = None
        self._last_completeness: str = ""  # "book" | "chapter" | "verse"

        # Estado de expectativa: o que procurar a seguir.
        # "book" → procurar livro
        # "chapter" → livro encontrado, procurar capítulo
        # "verse" → capítulo encontrado, procurar versículo
        # "done" → referência completa, não processar mais
        self._expecting: str = "book"

        # Flag: já publicamos ReferenceDetected para este fluxo?
        self._detected_published: bool = False

        # Sprint 21.4 — Flag: já publicamos ReferenceAntecipada para
        # este fluxo? Evita republicar antecipadas para o mesmo nível
        # de completude. Resetado quando o fluxo resetta.
        self._anticipation_published: bool = False

        # Métricas.
        self._total_partials_processed = 0
        self._total_candidates_published = 0
        self._total_detected_published = 0
        self._total_latency_ms = 0
        # Sprint 21.4 — métrica de antecipação.
        self._total_anticipations_published = 0

        logger.info(
            "IncrementalBiblicalParser initialized "
            "(threshold=%.2f, anticipation_threshold=%.2f).",
            threshold, anticipation_threshold,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inscreve no EventBus para receber SpeechPartial/Updated."""
        if self._subscribed:
            return
        self._bus.subscribe(SpeechPartial, self._on_partial)
        self._bus.subscribe(SpeechPartialUpdated, self._on_partial_updated)
        self._subscribed = True
        logger.info(
            "IncrementalBiblicalParser started — subscribed to "
            "SpeechPartial and SpeechPartialUpdated."
        )

    def stop(self) -> None:
        """Desinscreve do EventBus."""
        if not self._subscribed:
            return
        self._subscribed = False
        logger.info("IncrementalBiblicalParser stopped.")

    def reset(self) -> None:
        """Reseta estado incremental para um novo fluxo.

        Chamado quando um novo SpeechPartial chega (novo correlation_id)
        ou externamente quando o VAD fecha um segmento.
        """
        self._current_book = None
        self._current_chapter = None
        self._current_verse = None
        self._seen_text = ""
        self._correlation_id = None
        self._causation_id = None
        self._last_completeness = ""
        self._expecting = "book"
        self._detected_published = False
        # Sprint 21.4 — resetar flag de antecipação.
        self._anticipation_published = False
        logger.debug("IncrementalBiblicalParser state reset.")

    # ------------------------------------------------------------------
    # Handlers do EventBus
    # ------------------------------------------------------------------

    def _on_partial(self, event: SpeechPartial) -> None:
        """Recebe SpeechPartial (primeira transcrição do fluxo)."""
        self._process(event.text, event, is_first=True)

    def _on_partial_updated(self, event: SpeechPartialUpdated) -> None:
        """Recebe SpeechPartialUpdated (evolução da transcrição).

        Usa appended_text (diff) para evitar reprocessar texto já visto.
        """
        # Se é um novo correlation_id, resetar estado.
        if (self._correlation_id is not None
                and event.correlation_id != self._correlation_id):
            self.reset()

        # Processar apenas o trecho novo (appended_text).
        # Se appended_text estiver vazio, usar text completo (fallback).
        text_to_process = event.appended_text or event.text
        self._process(text_to_process, event, is_first=False)

    # ------------------------------------------------------------------
    # Processamento incremental
    # ------------------------------------------------------------------

    def _process(
        self,
        text: str,
        source_event: SpeechPartial | SpeechPartialUpdated,
        is_first: bool,
    ) -> None:
        """Processa texto incremental e publica eventos conforme apropriado."""
        if not text or not text.strip():
            return

        # Se já publicamos ReferenceDetected, ignorar até reset.
        if self._detected_published:
            return

        t0 = time.monotonic()
        self._total_partials_processed += 1

        # Inicializar correlation_id no primeiro evento.
        if is_first or self._correlation_id is None:
            self._correlation_id = source_event.correlation_id
            self._causation_id = source_event.meta.event_id
            self._seen_text = ""

        # Normalizar o texto novo.
        norm = self._norm.normalize(text)
        if not norm:
            return

        # Acumular texto visto (para contexto futuro, se necessário).
        self._seen_text = (self._seen_text + " " + norm).strip()

        # Processar conforme expectativa.
        # Usar `changed = changed or ...` permite cascateamento:
        # se o texto completo chegar de uma vez ("joao capitulo 3
        # versiculo 16"), book → chapter → verse são detectados em
        # uma única passada.
        changed = False

        if self._expecting == "book":
            changed = self._try_find_book(norm) or changed

        if self._expecting == "chapter":
            changed = self._try_find_chapter(norm) or changed

        if self._expecting == "verse":
            changed = self._try_find_verse(norm) or changed

        if not changed:
            # Tentar encontrar livro mesmo em estágio avançado
            # (caso o Whisper tenha reescrito o texto).
            if self._expecting in ("chapter", "verse") and self._current_book is None:
                changed = self._try_find_book(norm)

        latency_ms = int((time.monotonic() - t0) * 1000)
        self._total_latency_ms += latency_ms

        if changed:
            self._evaluate_and_publish(source_event, latency_ms)

    # ------------------------------------------------------------------
    # Detecção incremental de componentes
    # ------------------------------------------------------------------

    def _try_find_book(self, norm_text: str) -> bool:
        """Tenta identificar um livro bíblico no texto.

        Retorna True se encontrou (e avança expectativa para "chapter").
        """
        result = self._books.resolve(norm_text)
        if result is None:
            return False

        # Se já tínhamos um livro e é o mesmo, não mudou.
        if (self._current_book is not None
                and self._current_book.book.id == result.book.id):
            # Livro já identificado — tentar avançar para chapter.
            self._expecting = "chapter"
            return False

        self._current_book = result
        self._expecting = "chapter"
        logger.debug(
            "IncrementalParser: book=%s (conf=%.2f)",
            result.book.canonical, result.confidence,
        )
        return True

    def _try_find_chapter(self, norm_text: str) -> bool:
        """Tenta identificar o capítulo no texto.

        Procura por marcadores ("capitulo N") ou número isolado
        após o livro.

        Retorna True se encontrou (e avança expectativa para "verse").
        """
        if self._current_book is None:
            return False

        # Passada 1: marcadores explícitos (prioridade).
        tokens = norm_text.split()
        for i, tok in enumerate(tokens):
            if tok in _CHAPTER_MARKERS:
                if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                    chapter = int(tokens[i + 1])
                    if 1 <= chapter <= 200:
                        self._current_chapter = chapter
                        self._expecting = "verse"
                        logger.debug(
                            "IncrementalParser: chapter=%d (marker)",
                            chapter,
                        )
                        return True

        # Passada 2: números sem marcador (apenas se nenhum marcador).
        if self._current_chapter is None:
            for tok in tokens:
                if tok.isdigit():
                    num = int(tok)
                    if 1 <= num <= 200:
                        self._current_chapter = num
                        self._expecting = "verse"
                        logger.debug(
                            "IncrementalParser: chapter=%d (unmarked)",
                            num,
                        )
                        return True

        return False

    def _try_find_verse(self, norm_text: str) -> bool:
        """Tenta identificar o versículo no texto.

        Procura por marcadores ("versiculo N") ou número após capítulo.

        Retorna True se encontrou (e avança expectativa para "done").
        """
        if self._current_book is None or self._current_chapter is None:
            return False

        tokens = norm_text.split()

        # Passada 1: marcadores explícitos (prioridade).
        for i, tok in enumerate(tokens):
            if tok in _VERSE_MARKERS:
                if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                    verse = int(tokens[i + 1])
                    if 1 <= verse <= 200:
                        self._current_verse = verse
                        self._expecting = "done"
                        logger.debug(
                            "IncrementalParser: verse=%d (marker)",
                            verse,
                        )
                        return True

        # Passada 2: números sem marcador (apenas se nenhum marcador).
        # Pular o primeiro dígito (que é o capítulo já identificado).
        if self._current_verse is None:
            digit_count = 0
            for tok in tokens:
                if tok.isdigit():
                    digit_count += 1
                    if digit_count <= 1:
                        continue
                    num = int(tok)
                    if 1 <= num <= 200:
                        self._current_verse = num
                        self._expecting = "done"
                        logger.debug(
                            "IncrementalParser: verse=%d (unmarked)",
                            num,
                        )
                        return True

        return False

    # ------------------------------------------------------------------
    # Publicação de eventos
    # ------------------------------------------------------------------

    def _evaluate_and_publish(
        self,
        source_event: SpeechPartial | SpeechPartialUpdated,
        latency_ms: int,
    ) -> None:
        """Avalia estado atual e publica ReferenceCandidate ou ReferenceDetected."""
        if self._current_book is None:
            return

        book = self._current_book.book
        book_conf = self._current_book.confidence

        # Determinar completude e confiança.
        if self._current_verse is not None:
            completeness = "verse"
            confidence = _C_BOOK_CHAPTER_VERSE * book_conf
        elif self._current_chapter is not None:
            completeness = "chapter"
            confidence = _C_BOOK_CHAPTER * book_conf
        else:
            completeness = "book"
            confidence = _C_BOOK_ONLY * book_conf

        # Não republicar se a completude não mudou.
        if completeness == self._last_completeness:
            return
        self._last_completeness = completeness

        # Se confiança >= threshold e temos pelo menos book+chapter,
        # publicar ReferenceDetected.
        if confidence >= self._threshold and completeness in ("chapter", "verse"):
            self._publish_detected(source_event, book, confidence, latency_ms)
            self._detected_published = True
        else:
            # Publicar ReferenceCandidate (telemetria — sempre).
            self._publish_candidate(
                source_event, book, confidence, completeness, latency_ms,
            )

            # Sprint 21.4 — Streaming First.
            # Se confiança >= anticipation_threshold e temos pelo menos
            # book+chapter (conforme decisão do usuário: não antecipa em
            # book-only), publicar ReferenceAntecipada para disparar a
            # apresentação antecipada no Holyrics via
            # VersePresentationService. Diferente de ReferenceCandidate
            # (telemetria), ReferenceAntecipada dispara apresentação.
            #
            # Só publica uma antecipada por fluxo (para evitar
            # apresentações múltiplas enquanto o versículo é falado).
            # Se o versículo completar, o ReferenceDetected acima já
            # tratou; se não completar, a antecipada de "chapter" é a
            # apresentação provisória.
            if (
                not self._anticipation_published
                and confidence >= self._anticipation_threshold
                and completeness in ("chapter", "verse")
            ):
                self._publish_anticipation(
                    source_event, book, confidence, completeness, latency_ms,
                )
                self._anticipation_published = True

    def _publish_candidate(
        self,
        source_event: SpeechPartial | SpeechPartialUpdated,
        book: Any,
        confidence: float,
        completeness: str,
        latency_ms: int,
    ) -> None:
        """Publica ReferenceCandidate."""
        meta = EventMetadata.for_next(
            previous=EventMetadata(
                event_id=self._causation_id or source_event.meta.event_id,
                correlation_id=self._correlation_id or source_event.correlation_id,
                causation_id=None,
                session_id=self._session_id,
                timestamp=source_event.meta.timestamp,
                origin="StreamingSTTService",
            ),
            origin="IncrementalBiblicalParser",
        )
        self._causation_id = meta.event_id

        normalized = self._build_normalized(book, self._current_chapter, self._current_verse)

        event = ReferenceCandidate(
            meta=meta,
            book=book.canonical,
            book_id=book.id,
            chapter=self._current_chapter or 0,
            verse_start=self._current_verse or 0,
            verse_end=self._current_verse or 0,
            confidence=round(confidence, 4),
            completeness=completeness,
            normalized_text=normalized,
        )
        self._bus.publish(event)
        self._total_candidates_published += 1
        logger.info(
            "ReferenceCandidate: %s completeness=%s confidence=%.2f (corr=%s)",
            book.canonical, completeness, confidence, meta.correlation_id,
        )

    def _publish_anticipation(
        self,
        source_event: SpeechPartial | SpeechPartialUpdated,
        book: Any,
        confidence: float,
        completeness: str,
        latency_ms: int,
    ) -> None:
        """Publica ReferenceAntecipada (Sprint 21.4 — Streaming First).

        Diferente de ReferenceCandidate (telemetria), este evento dispara
        a apresentação antecipada no Holyrics via VersePresentationService.
        Diferente de ReferenceDetected (definitivo), este evento pode ser
        confirmado ou corrigido por um ReferenceDetected posterior.
        """
        meta = EventMetadata.for_next(
            previous=EventMetadata(
                event_id=self._causation_id or source_event.meta.event_id,
                correlation_id=self._correlation_id or source_event.correlation_id,
                causation_id=None,
                session_id=self._session_id,
                timestamp=source_event.meta.timestamp,
                origin="StreamingSTTService",
            ),
            origin="IncrementalBiblicalParser",
        )
        self._causation_id = meta.event_id

        normalized = self._build_normalized(book, self._current_chapter, self._current_verse)

        event = ReferenceAntecipada(
            meta=meta,
            book=book.canonical,
            book_id=book.id,
            chapter=self._current_chapter or 0,
            verse_start=self._current_verse or 0,
            verse_end=self._current_verse or 0,
            confidence=round(confidence, 4),
            completeness=completeness,
            normalized_text=normalized,
        )
        self._bus.publish(event)
        self._total_anticipations_published += 1
        logger.info(
            "ReferenceAntecipada: %s completeness=%s confidence=%.2f "
            "latency=%dms (corr=%s) — apresentação antecipada",
            book.canonical, completeness, confidence, latency_ms,
            meta.correlation_id,
        )

    def _publish_detected(
        self,
        source_event: SpeechPartial | SpeechPartialUpdated,
        book: Any,
        confidence: float,
        latency_ms: int,
    ) -> None:
        """Publica ReferenceDetected (evento definitivo)."""
        meta = EventMetadata.for_next(
            previous=EventMetadata(
                event_id=self._causation_id or source_event.meta.event_id,
                correlation_id=self._correlation_id or source_event.correlation_id,
                causation_id=None,
                session_id=self._session_id,
                timestamp=source_event.meta.timestamp,
                origin="StreamingSTTService",
            ),
            origin="IncrementalBiblicalParser",
        )
        self._causation_id = meta.event_id

        normalized = self._build_normalized(book, self._current_chapter, self._current_verse)

        event = ReferenceDetected(
            meta=meta,
            intent="OPEN_REFERENCE",
            book=book.canonical,
            book_id=book.id,
            chapter=self._current_chapter or 0,
            verse_start=self._current_verse or 0,
            verse_end=self._current_verse or 0,
            confidence=round(confidence, 4),
            raw_text=source_event.text if hasattr(source_event, "text") else "",
            normalized_text=normalized,
        )
        self._bus.publish(event)
        self._total_detected_published += 1
        logger.info(
            "ReferenceDetected (incremental): %s %d:%d confidence=%.2f "
            "latency=%dms (corr=%s)",
            book.canonical,
            self._current_chapter or 0,
            self._current_verse or 0,
            confidence,
            latency_ms,
            meta.correlation_id,
        )

    @staticmethod
    def _build_normalized(book: Any, chapter: int | None, verse: int | None) -> str:
        """Constrói texto normalizado da referência."""
        ref = book.canonical.lower()
        if chapter is not None:
            ref += f" {chapter}"
            if verse is not None:
                ref += f":{verse}"
        return ref

    # ------------------------------------------------------------------
    # Propriedades
    # ------------------------------------------------------------------

    @property
    def total_partials_processed(self) -> int:
        return self._total_partials_processed

    @property
    def total_candidates_published(self) -> int:
        return self._total_candidates_published

    @property
    def total_detected_published(self) -> int:
        return self._total_detected_published

    # Sprint 21.4 — métrica de antecipação.
    @property
    def total_anticipations_published(self) -> int:
        return self._total_anticipations_published

    @property
    def avg_latency_ms(self) -> float:
        if self._total_partials_processed == 0:
            return 0.0
        return self._total_latency_ms / self._total_partials_processed
