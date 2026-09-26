"""IncrementalBiblicalParser — parser incremental de referências faladas.

Responsabilidade:
  - Consumir SpeechCommittedWords (palavras estáveis do LocalAgreement-2).
  - Publicar ReferenceCandidate (livro → capítulo) e ReferenceDetected
    (livro + capítulo + versículo, canonicamente válido).
  - Opcionalmente publicar ReferenceAntecipada no nível capítulo
    (``chapter_anticipation`` — DESLIGADO por padrão).

Sprint 31 — revisão de robustez (incidentes de culto a–g):

  * Re-parse por utterance: os tokens normalizados da utterance são
    acumulados e a gramática (``pipeline.speech_reference_grammar``) é
    re-executada sobre a janela inteira a cada chunk. Antes, cada chunk
    era analisado isoladamente e as fronteiras de chunk quebravam a
    leitura: "salmo vinte | e três" → Salmos 20:3; "versículo | um" →
    marcador perdido; "atos 2 do | 40 ao 47" → livro expirado.
  * Números por extenso inacabados ("vinte", "vinte e", "cento e") no
    fim do chunk são retidos até o próximo chunk (ou fim da utterance).
  * Limites canônicos: nunca emite referência impossível (Amós 19:99).
  * Continuação após pausa: "Primeira Coríntios" [pausa] "capítulo 14,
    versículo 10" completa (contexto de até ``carry_seconds``), mas só
    com marcador explícito ou par compacto "N M" logo no início da fala.
  * Antecipação de capítulo desligada por padrão: "Abra em Hebreus
    capítulo 12" (instrução à congregação) não apresenta 12:1 — a spec
    do benchmark exige PREPARE sem apresentação até o versículo.
  * Thread-safe: estado protegido por lock; eventos são publicados
    FORA do lock (handlers downstream fazem I/O no Holyrics).

O parser NUNCA chama o Holyrics — quem apresenta é o
VersePresentationService, a partir de ReferenceDetected.
"""

from __future__ import annotations

import logging
import threading
import time
import unicodedata
from typing import Any, Callable

from parser.books import BookResolveResult, ParserBookTable
from parser.canon import CanonBounds, load_canon_bounds
from parser.normalizer import Normalizer
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    PipelineStopped,
    ReferenceAntecipada,
    ReferenceCandidate,
    ReferenceDetected,
    SpeechCommittedWords,
    SpeechTranscribed,
)
from pipeline.metadata import EventMetadata
from pipeline.speech_reference_grammar import (
    MAX_CARRY_LEAD,
    RefParse,
    SpeechBookMatcher,
    parse_continuation,
    parse_mention,
)
# Sprint 21.9 — Telemetria de observabilidade (não altera comportamento).
from telemetry import hooks as telemetry_hooks

logger = logging.getLogger(__name__)

__all__ = ["IncrementalBiblicalParser"]

# Confianças por nível de completude (× confiança da alias do livro).
_C_BOOK_ONLY = 0.40
_C_BOOK_CHAPTER = 0.75
_C_BOOK_CHAPTER_VERSE = 0.98

# Threshold para publicar ReferenceDetected (vs ReferenceCandidate).
_DETECTION_THRESHOLD = 0.90

# Threshold para ReferenceAntecipada (só relevante com
# chapter_anticipation=True; book-only 0.40 nunca antecipa).
_DEFAULT_ANTICIPATION_THRESHOLD = 0.60

# Janela para completar uma referência iniciada antes de uma pausa.
_DEFAULT_CARRY_SECONDS = 10.0

# Palavras por extenso que ainda podem continuar via "e" ("vinte e oito").
_CONTINUABLE_NUMBERS = frozenset({
    "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta",
    "oitenta", "noventa", "cem", "cento",
})
_EXTENSO_WORDS = _CONTINUABLE_NUMBERS | frozenset({
    "um", "uma", "dois", "duas", "tres", "quatro", "cinco", "seis", "sete",
    "oito", "nove", "dez", "onze", "doze", "treze", "quatorze", "catorze",
    "quinze", "dezesseis", "dezasseis", "dezessete", "dezassete", "dezesete",
    "dezoito", "dezenove", "dezanove",
})


def _bare(tok: str) -> str:
    t = unicodedata.normalize("NFKD", tok.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _unfinished_number_tail(raw: list[str]) -> int:
    """Quantos tokens crus finais formam um número por extenso inacabado.

    Retém a sequência inteira ("cento e cinquenta" pode virar "cento e
    cinquenta e um"). Pontuação após o token ("vinte,") encerra o número.
    """
    i = len(raw)
    while i > 0 and (_bare(raw[i - 1]) in _EXTENSO_WORDS or _bare(raw[i - 1]) == "e"):
        i -= 1
    while i < len(raw) and _bare(raw[i]) == "e":
        i += 1
    run = [_bare(t) for t in raw[i:]]
    if not run:
        return 0
    if run[-1] in _CONTINUABLE_NUMBERS or (
            run[-1] == "e" and len(run) >= 2 and run[-2] in _CONTINUABLE_NUMBERS):
        return len(run)
    return 0


class IncrementalBiblicalParser:
    """Parser incremental de referências faladas (thread-safe).

    Args:
        books: ParserBookTable para resolução de livros.
        bus: PipelineEventBus para publicar eventos.
        session_id: ID da sessão atual.
        normalizer: Normalizer de fala (default: protect_function_words).
        threshold: confiança mínima para ReferenceDetected (0.90).
        anticipation_threshold: confiança mínima para ReferenceAntecipada.
        chapter_anticipation: se True, "<livro> <cap>" sem versículo
            publica ReferenceAntecipada (apresenta <cap>:1). Default False.
        bounds: limites canônicos (default: config/canon_bounds.json).
        carry_seconds: validade do contexto livro/capítulo após pausa.
        clock: relógio monotônico (injetável em testes).
    """

    def __init__(
        self,
        books: ParserBookTable,
        bus: PipelineEventBus,
        session_id: str,
        normalizer: Normalizer | None = None,
        threshold: float = _DETECTION_THRESHOLD,
        anticipation_threshold: float = _DEFAULT_ANTICIPATION_THRESHOLD,
        chapter_anticipation: bool = False,
        bounds: CanonBounds | None = None,
        carry_seconds: float = _DEFAULT_CARRY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._books = books
        self._matcher = SpeechBookMatcher(books)
        # protect_function_words: "um"/"primeiro" não viram dígitos e só
        # I/II/III são romanos ("eu vi" não vira "eu 6").
        self._norm = normalizer or Normalizer(protect_function_words=True)
        self._bounds = bounds or load_canon_bounds()
        self._bus = bus
        self._session_id = session_id
        self._threshold = threshold
        self._anticipation_threshold = anticipation_threshold
        self._chapter_anticipation = chapter_anticipation
        self._carry_seconds = carry_seconds
        self._clock = clock
        self._subscribed = False
        self._lock = threading.RLock()

        # Contexto cross-utterance (sobrevive ao reset): (book, conf,
        # chapter|None, deadline).
        self._carry: tuple[Any, float, int | None, float] | None = None

        self._total_partials_processed = 0
        self._total_candidates_published = 0
        self._total_detected_published = 0
        self._total_latency_ms = 0
        self._total_anticipations_published = 0

        self.reset()
        logger.info(
            "IncrementalBiblicalParser initialized (threshold=%.2f, "
            "anticipation_threshold=%.2f, chapter_anticipation=%s, carry=%.0fs).",
            threshold, anticipation_threshold, chapter_anticipation, carry_seconds,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inscreve em SpeechCommittedWords, SpeechTranscribed e PipelineStopped."""
        if self._subscribed:
            return
        self._bus.subscribe(SpeechCommittedWords, self._on_committed_words)
        self._bus.subscribe(SpeechTranscribed, self._on_transcribed)
        self._bus.subscribe(PipelineStopped, self._on_pipeline_stopped)
        self._subscribed = True
        logger.info("IncrementalBiblicalParser started.")

    def stop(self) -> None:
        """Desinscreve do EventBus."""
        if not self._subscribed:
            return
        self._bus.unsubscribe(SpeechCommittedWords, self._on_committed_words)
        self._bus.unsubscribe(SpeechTranscribed, self._on_transcribed)
        self._bus.unsubscribe(PipelineStopped, self._on_pipeline_stopped)
        self._subscribed = False
        logger.info("IncrementalBiblicalParser stopped.")

    def reset(self) -> None:
        """Reseta o estado da utterance (o contexto de pausa é preservado)."""
        with self._lock:
            self._tokens: list[str] = []
            self._held_raw: list[str] = []
            self._scan_start = 0
            self._context: tuple[Any, float, int] | None = None
            self._last_detected: RefParse | None = None
            self._carry_usable = self._carry is not None
            self._correlation_id: str | None = None
            self._causation_id: str | None = None
            self._last_candidate_key: tuple | None = None
            self._detected_keys: set[tuple[int, int, int]] = set()
            self._detected_published = False
            self._anticipation_published = False
            self._tail_open: RefParse | None = None
            # Espelho de compatibilidade (inspecionado por testes/telemetria).
            self._current_book: BookResolveResult | None = None
            self._current_chapter: int | None = None
            self._current_verse: int | None = None
            self._current_verse_end: int | None = None
            self._expecting = "book"
            self._seen_text = ""

    # ------------------------------------------------------------------
    # Handlers do EventBus (threads de áudio/STT)
    # ------------------------------------------------------------------

    def _on_committed_words(self, event: SpeechCommittedWords) -> None:
        outbox: list[Any] = []
        with self._lock:
            if (self._correlation_id is not None
                    and event.correlation_id != self._correlation_id):
                self._end_utterance(event, outbox)
            if self._correlation_id is None:
                self._correlation_id = event.correlation_id
                self._causation_id = event.meta.event_id
            text = event.committed_text or ""
            if text.strip():
                t0 = time.perf_counter()
                self._total_partials_processed += 1
                self._ingest(text, event, outbox, final=False)
                self._total_latency_ms += int((time.perf_counter() - t0) * 1000)
        self._flush(outbox)

    def _on_transcribed(self, event: SpeechTranscribed) -> None:
        """Fim de segmento: fecha a utterance (preservando contexto de pausa)."""
        outbox: list[Any] = []
        with self._lock:
            if self._correlation_id is not None:
                self._end_utterance(event, outbox)
            else:
                self.reset()
        self._flush(outbox)

    def _on_pipeline_stopped(self, event: PipelineStopped) -> None:
        """Captura parada: descarta tudo, inclusive o contexto de pausa."""
        with self._lock:
            self._carry = None
            self.reset()
        logger.info("IncrementalBiblicalParser: pipeline stopped — state cleared.")

    def _flush(self, outbox: list[Any]) -> None:
        # Publicação fora do lock: handlers downstream fazem I/O (Holyrics).
        for ev in outbox:
            self._bus.publish(ev)

    # ------------------------------------------------------------------
    # Ingestão e avaliação
    # ------------------------------------------------------------------

    def _end_utterance(self, source: Any, outbox: list[Any]) -> None:
        """Processa números retidos, guarda contexto de pausa e reseta."""
        self._ingest("", source, outbox, final=True)
        tail = self._tail_open
        if tail is not None and tail.completeness in ("book", "chapter"):
            self._carry = (tail.book, tail.confidence, tail.chapter,
                           self._clock() + self._carry_seconds)
            logger.debug(
                "IncrementalParser: carrying %s %s across pause (%.0fs).",
                tail.book.canonical, tail.chapter or "", self._carry_seconds,
            )
        elif self._context is not None or self._tokens:
            self._carry = None
        self.reset()

    def _ingest(self, text: str, source: Any, outbox: list[Any], *, final: bool) -> None:
        raw = self._held_raw + SpeechBookMatcher.preprocess_raw(text.split())
        hold = 0 if final else _unfinished_number_tail(raw)
        stable, self._held_raw = raw[:len(raw) - hold], raw[len(raw) - hold:]
        if stable:
            norm = self._norm.normalize(" ".join(stable))
            if norm:
                self._tokens.extend(norm.split())
                self._seen_text = " ".join(self._tokens)
        self._evaluate(source, outbox, final)

    def _evaluate(self, source: Any, outbox: list[Any], final: bool) -> None:
        """Re-executa a gramática sobre os tokens ainda não consumidos."""
        tokens = self._tokens
        self._tail_open = None
        while self._scan_start < len(tokens):
            mentions = self._matcher.find(tokens, self._scan_start)
            first = mentions[0].start if mentions else len(tokens)
            r: RefParse | None = None
            kind = "mention"

            if self._context is not None and self._scan_start < first:
                book, conf, ch = self._context
                r = parse_continuation(tokens, self._scan_start, first, book, conf,
                                       ch, self._bounds, lead=None, final=final)
                kind = "correction"
            elif self._carry_usable and self._scan_start == 0:
                r = self._try_carry(tokens, first, mentions, final)
                kind = "carry"

            if r is None:
                if not mentions:
                    break
                m = mentions[0]
                limit = mentions[1].start if len(mentions) > 1 else len(tokens)
                r = parse_mention(tokens, m, limit, self._bounds, final)
                if final and limit == len(tokens):
                    # Estava aberta antes da pausa? → contexto de continuação.
                    probe = parse_mention(tokens, m, limit, self._bounds, False)
                    if probe.open and probe.completeness != "verse":
                        self._tail_open = probe

            if not self._handle(r, kind, source, outbox):
                break
        self._update_mirror()

    def _try_carry(self, tokens: list[str], first: int, mentions: list, final: bool) -> RefParse | None:
        book, conf, ch, deadline = self._carry  # type: ignore[misc]
        if self._clock() > deadline:
            self._carry = None
            self._carry_usable = False
            return None
        r = parse_continuation(tokens, 0, first, book, conf, ch, self._bounds,
                               lead=MAX_CARRY_LEAD, final=final)
        if r is not None:
            if r.open:
                return r  # "capítulo 14 versículo" | "dez": mantém o contexto
            self._carry = None
            self._carry_usable = False
            logger.info(
                "IncrementalParser: continuation after pause — %s %s:%s.",
                book.canonical, r.chapter, r.verse,
            )
            return r
        if (mentions and first <= MAX_CARRY_LEAD) or len(tokens) > MAX_CARRY_LEAD + 1 or final:
            self._carry_usable = False
        return None

    def _handle(self, r: RefParse, kind: str, source: Any, outbox: list[Any]) -> bool:
        """Publica o que ``r`` justifica. True = avançou (reavaliar)."""
        if r.rejected:
            logger.info(
                "IncrementalParser: %s %s rejeitado (%s) — %r.",
                kind, r.book.canonical, r.rejected, " ".join(self._tokens[-12:]),
            )
            self._scan_start = max(r.end, self._scan_start + 1)
            return True
        if r.verse is not None:
            self._emit(r, "verse", source, outbox)
            self._context = (r.book, r.confidence, r.chapter)
            self._last_detected = r
            self._scan_start = max(r.end, self._scan_start + 1)
            return True
        self._emit(r, r.completeness, source, outbox)
        if kind == "correction" and r.chapter is not None:
            self._context = (r.book, r.confidence, r.chapter)
        if r.open:
            self._tail_open = r
            return False
        self._scan_start = max(r.end, self._scan_start + 1)
        return True

    def _update_mirror(self) -> None:
        tail = self._tail_open
        if tail is not None:
            book, conf = tail.book, tail.confidence
            self._current_chapter, self._current_verse = tail.chapter, None
            self._current_verse_end = None
            self._expecting = "verse" if tail.chapter is not None else "chapter"
        elif self._context is not None:
            book, conf, self._current_chapter = self._context
            last = self._last_detected
            self._current_verse = last.verse if last else None
            self._current_verse_end = last.verse_end if last else None
            self._expecting = "done"
        else:
            self._current_book = None
            self._current_chapter = self._current_verse = self._current_verse_end = None
            self._expecting = "book"
            return
        self._current_book = BookResolveResult(
            book=book, matched_alias=book.canonical, confidence=conf,
            ambiguous=conf < 1.0, start=0, end=0,
        )

    # ------------------------------------------------------------------
    # Publicação
    # ------------------------------------------------------------------

    def _next_meta(self, source: Any) -> EventMetadata:
        meta = EventMetadata.for_next(
            previous=EventMetadata(
                event_id=self._causation_id or source.meta.event_id,
                correlation_id=self._correlation_id or source.correlation_id,
                causation_id=None,
                session_id=self._session_id,
                timestamp=source.meta.timestamp,
                origin="StreamingSTTService",
            ),
            origin="IncrementalBiblicalParser",
        )
        self._causation_id = meta.event_id
        return meta

    def _emit(self, r: RefParse, completeness: str, source: Any, outbox: list[Any]) -> None:
        book = r.book
        level = {"verse": _C_BOOK_CHAPTER_VERSE, "chapter": _C_BOOK_CHAPTER}.get(
            completeness, _C_BOOK_ONLY)
        confidence = round(level * r.confidence, 4)
        chapter, verse = r.chapter or 0, r.verse or 0
        verse_end = r.verse_end or r.verse or 0
        normalized = self._build_normalized(book, r.chapter, r.verse)
        corr = self._correlation_id or source.correlation_id

        def telemetry(decision: str, published: str) -> None:
            telemetry_hooks.parser_event(
                correlation_id=corr, text_processed=self._seen_text,
                expecting=self._expecting, completeness=completeness,
                book=book.canonical, chapter=chapter, verse=verse,
                confidence=confidence, decision=decision,
                published_event=published, latency_ms=0,
            )

        if completeness == "verse" and confidence >= self._threshold:
            key = (book.id, chapter, verse)
            if key in self._detected_keys:
                return
            self._detected_keys.add(key)
            telemetry("publish_detected", "ReferenceDetected")
            outbox.append(ReferenceDetected(
                meta=self._next_meta(source), intent="OPEN_REFERENCE",
                book=book.canonical, book_id=book.id, chapter=chapter,
                verse_start=verse, verse_end=verse_end, confidence=confidence,
                raw_text=getattr(source, "full_committed_text", "") or getattr(source, "text", ""),
                normalized_text=normalized,
            ))
            self._detected_published = True
            self._total_detected_published += 1
            logger.info(
                "ReferenceDetected (incremental): %s %d:%d%s confidence=%.2f (corr=%s)",
                book.canonical, chapter, verse,
                f"-{verse_end}" if verse_end != verse else "", confidence, corr,
            )
            return

        key = (book.id, chapter, verse, completeness)
        if key == self._last_candidate_key:
            return
        self._last_candidate_key = key
        telemetry("publish_candidate", "ReferenceCandidate")
        outbox.append(ReferenceCandidate(
            meta=self._next_meta(source), book=book.canonical, book_id=book.id,
            chapter=chapter, verse_start=verse, verse_end=verse_end,
            confidence=confidence, completeness=completeness,
            normalized_text=normalized,
        ))
        self._total_candidates_published += 1
        logger.info(
            "ReferenceCandidate: %s completeness=%s confidence=%.2f (corr=%s)",
            book.canonical, completeness, confidence, corr,
        )

        if (not self._anticipation_published
                and confidence >= self._anticipation_threshold
                and completeness in ("chapter", "verse")
                and (completeness != "chapter" or self._chapter_anticipation)):
            telemetry("publish_antecipada", "ReferenceAntecipada")
            outbox.append(ReferenceAntecipada(
                meta=self._next_meta(source), book=book.canonical,
                book_id=book.id, chapter=chapter, verse_start=verse,
                verse_end=verse_end, confidence=confidence,
                completeness=completeness, normalized_text=normalized,
            ))
            self._anticipation_published = True
            self._total_anticipations_published += 1
            logger.info(
                "ReferenceAntecipada: %s completeness=%s confidence=%.2f (corr=%s)",
                book.canonical, completeness, confidence, corr,
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

    @property
    def total_anticipations_published(self) -> int:
        return self._total_anticipations_published

    @property
    def avg_latency_ms(self) -> float:
        if self._total_partials_processed == 0:
            return 0.0
        return self._total_latency_ms / self._total_partials_processed
