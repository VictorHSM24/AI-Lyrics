"""IncrementalBiblicalParser — parser incremental de referências (Sprint 19 + 28).

Responsabilidade:
  - Consumir SpeechCommittedWords do StreamingSTTService (Sprint 28).
  - Manter estado incremental: book → chapter → verse.
  - Publicar ReferenceCandidate (confiança crescente).
  - Publicar ReferenceDetected quando confidence >= threshold.
  - Resetar estado em SpeechTranscribed (finalização do fluxo).

Sprint 28 — Streaming First com LocalAgreement-2:
  O parser agora consome SpeechCommittedWords (palavras confirmed por
  LocalAgreement-2) em vez de SpeechPartial/Updated. Committed words
  são texto confiável que não vai mudar mais — o parser pode processar
  sem risco de retrabalho por revisão regressiva do Whisper.

  Exemplo:
    committed "joão"                          → ReferenceCandidate(book=João, conf=0.40)
    committed "joão capítulo três"            → ReferenceCandidate(book=João, chapter=3, conf=0.75)
    committed "joão capítulo três versículo dezesseis"
                                              → ReferenceDetected(book=João, chapter=3, verse=16, conf=0.98)

  O parser NUNCA chama Holyrics diretamente. Quando publica
  ReferenceDetected, o VersePresentationService existente cuida
  da apresentação.

Evitar retrabalho:
  O parser mantém estado entre chamadas. Quando recebe
  SpeechCommittedWords com committed_text, apenas processa o
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
    SpeechCommittedWords,
    SpeechTranscribed,
)
from pipeline.metadata import EventMetadata
# Sprint 21.9 — Telemetria de observabilidade (não altera comportamento).
from telemetry import hooks as telemetry_hooks

logger = logging.getLogger(__name__)

__all__ = ["IncrementalBiblicalParser"]

# Marcadores (mesmos do parser determinístico).
_CHAPTER_MARKERS = frozenset({"capitulo", "cap"})
_VERSE_MARKERS = frozenset({"versiculo", "vers", "v", "verso"})

# Sprint 23.2 — Reading Follow Mode.
# Marcadores de intervalo de versículos: "do 1 ao 3", "de 1 a 3", "1 ate 3".
# Apos encontrar verse_start, procuramos por estes marcadores seguidos
# de um numero que representa verse_end.
_RANGE_END_MARKERS = frozenset({"ao", "a", "ate", "até"})

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
_VERSE_EXTENSO = frozenset({"vers", "versiculo", "versiculo:", "v", "verso"})


class IncrementalBiblicalParser:
    """Parser incremental que evolui estado a cada SpeechCommittedWords.

    Args:
        books: ParserBookTable para resolução de livros.
        normalizer: Normalizer para normalizar texto (criado internamente
            se omitido).
        bus: PipelineEventBus para publicar eventos.
        session_id: ID da sessão atual.
        threshold: confiança mínima para publicar ReferenceDetected
            (default 0.90). Abaixo disso, publica ReferenceCandidate.

    Lifecycle:
        start() — inscreve em SpeechCommittedWords e SpeechTranscribed.
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
        self._current_verse_end: int | None = None
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
        """Inscreve no EventBus para receber SpeechCommittedWords e SpeechTranscribed.

        Sprint 28 — o parser agora consome SpeechCommittedWords (palavras
        confirmed por LocalAgreement-2) em vez de SpeechPartial/Updated.
        SpeechTranscribed é usado para reset (finalização do fluxo).
        """
        if self._subscribed:
            return
        self._bus.subscribe(SpeechCommittedWords, self._on_committed_words)
        self._bus.subscribe(SpeechTranscribed, self._on_transcribed)
        self._subscribed = True
        logger.info(
            "IncrementalBiblicalParser started — subscribed to "
            "SpeechCommittedWords and SpeechTranscribed."
        )

    def stop(self) -> None:
        """Desinscreve do EventBus."""
        if not self._subscribed:
            return
        self._subscribed = False
        logger.info("IncrementalBiblicalParser stopped.")

    def reset(self) -> None:
        """Reseta estado incremental para um novo fluxo.

        Chamado quando um novo SpeechCommittedWords chega (novo correlation_id),
        quando SpeechTranscribed fecha o segmento, ou externamente.
        """
        self._current_book = None
        self._current_chapter = None
        self._current_verse = None
        self._current_verse_end = None
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

    def _on_committed_words(self, event: SpeechCommittedWords) -> None:
        """Recebe SpeechCommittedWords (palavras confirmed por LocalAgreement-2).

        Sprint 28 — processa apenas committed_text (palavras novas
        confirmed nesta iteração). Como committed words são estáveis
        por definição (2 transcrições concordaram), não há risco de
        retrabalho por revisão regressiva.
        """
        # Se é um novo correlation_id, resetar estado.
        if (self._correlation_id is not None
                and event.correlation_id != self._correlation_id):
            self.reset()

        # Processar apenas as palavras novas committed.
        text_to_process = event.committed_text
        self._process(text_to_process, event, is_first=(self._correlation_id is None))

    def _on_transcribed(self, event: SpeechTranscribed) -> None:
        """Recebe SpeechTranscribed (finalização do fluxo).

        Sprint 28 — resetar estado incremental para o próximo fluxo.
        O parser não processa SpeechTranscribed (o incremental já
        detectou em committed words). Apenas limpa o estado.
        """
        logger.debug(
            "IncrementalBiblicalParser: SpeechTranscribed received — resetting "
            "(corr=%s, text=%r).",
            event.correlation_id, event.text[:60],
        )
        self.reset()

    # ------------------------------------------------------------------
    # Processamento incremental
    # ------------------------------------------------------------------

    def _process(
        self,
        text: str,
        source_event: SpeechCommittedWords | SpeechTranscribed,
        is_first: bool,
    ) -> None:
        """Processa texto incremental e publica eventos conforme apropriado."""
        if not text or not text.strip():
            return

        # Se já publicamos ReferenceDetected, verificar se o texto contém
        # uma correção parcial (apenas verso ou capítulo) ou um livro
        # bíblico diferente do atual.
        #
        # Correção parcial: pregador disse "João 3:16" e depois "verso 4"
        # — manter livro e capítulo, mudar apenas o verso.
        #
        # Novo livro: pregador disse "João 3:16" e depois "Salmos 23:1"
        # sem pausa suficiente para resetar o correlation_id.
        if self._detected_published:
            if self._current_book is not None:
                norm_check = self._norm.normalize(text)
                if norm_check:
                    # 1. Tentar correção de capítulo ("capítulo 5")
                    #    ANTES de verso, pois "capítulo 2, verso 18"
                    #    contém ambos.
                    corrected = self._try_chapter_correction(
                        norm_check, source_event,
                    )
                    if corrected:
                        return
                    # 2. Tentar correção de verso ("verso 4", "versículo 4").
                    corrected = self._try_verse_correction(
                        norm_check, source_event,
                    )
                    if corrected:
                        return
                    # 3. Tentar novo livro.
                    new_book = self._books.resolve(norm_check)
                    if (new_book is not None
                            and new_book.book.id != self._current_book.book.id):
                        logger.info(
                            "IncrementalParser: new book detected after "
                            "ReferenceDetected (old=%s, new=%s) — resetting "
                            "to detect new reference (corr=%s).",
                            self._current_book.book.canonical,
                            new_book.book.canonical,
                            self._correlation_id,
                        )
                        self.reset()
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

        # Sprint 23.2 — apos encontrar versiculo, tentar encontrar
        # verse_end (intervalo "do 1 ao 3"). _try_find_verse ja setou
        # _expecting = "done", mas podemos ter verse_end no texto.
        if changed and self._current_verse is not None and self._current_verse_end is None:
            self._try_find_verse_end(norm)

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
        # Ignora dígitos que são parte de marcador de verso ("verso 7").
        if self._current_chapter is None:
            for i, tok in enumerate(tokens):
                if tok.isdigit():
                    # Pular se o token anterior é marcador de verso.
                    if i > 0 and tokens[i - 1] in _VERSE_MARKERS:
                        continue
                    num = int(tok)
                    if 1 <= num <= 200:
                        self._current_chapter = num
                        self._expecting = "verse"
                        logger.debug(
                            "IncrementalParser: chapter=%d (unmarked)",
                            num,
                        )
                        return True
                    # Heurística: número colado "316" → cap=3, verso=16.
                    # Tenta dividir em chapter|verse quando o número
                    # é > 200 (inválido como capítulo isolado).
                    if num > 200:
                        split = self._try_split_chapter_verse(tok)
                        if split is not None:
                            ch, vs = split
                            self._current_chapter = ch
                            self._current_verse = vs
                            self._expecting = "done"
                            logger.debug(
                                "IncrementalParser: chapter=%d verse=%d "
                                "(split from %s)",
                                ch, vs, tok,
                            )
                            return True

        return False

    @staticmethod
    def _try_split_chapter_verse(
        token: str,
    ) -> tuple[int, int] | None:
        """Tenta dividir um número colado em capítulo e verso.

        Exemplos: "316" → (3, 16), "118" → (1, 18), "231" → (2, 31).
        Prefere split com verso de 2 dígitos (mais comum em PT-BR).
        """
        n = len(token)
        if n < 3 or n > 4:
            return None
        # Tentar split 1|n-1 (cap=1 dígito, verso=resto).
        ch1 = int(token[:1])
        vs1 = int(token[1:])
        if 1 <= ch1 <= 200 and 1 <= vs1 <= 200:
            return (ch1, vs1)
        # Tentar split 2|n-2 (cap=2 dígitos, verso=resto).
        if n >= 4:
            ch2 = int(token[:2])
            vs2 = int(token[2:])
            if 1 <= ch2 <= 200 and 1 <= vs2 <= 200:
                return (ch2, vs2)
        return None

    def _try_verse_correction(
        self,
        norm_text: str,
        source_event: SpeechCommittedWords | SpeechTranscribed,
    ) -> bool:
        """Detecta correção de verso após ReferenceDetected.

        Se o pregador disse "verso 4" ou "versículo 4" após já ter
        apresentado uma referência, manter livro e capítulo e mudar
        apenas o verso. Publica nova ReferenceDetected com o verso
        corrigido.
        """
        if self._current_book is None or self._current_chapter is None:
            return False

        tokens = norm_text.split()

        # Passada 1: marcador explícito ("verso 4", "versículo 4").
        for i, tok in enumerate(tokens):
            if tok in _VERSE_MARKERS:
                if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                    new_verse = int(tokens[i + 1])
                    if 1 <= new_verse <= 200:
                        old_verse = self._current_verse
                        if old_verse == new_verse:
                            return False
                        logger.info(
                            "IncrementalParser: verse correction "
                            "%s %d:%d → %d (corr=%s).",
                            self._current_book.book.canonical,
                            self._current_chapter, old_verse or 0,
                            new_verse, self._correlation_id,
                        )
                        self._current_verse = new_verse
                        self._current_verse_end = None
                        self._detected_published = False
                        self._anticipation_published = False
                        self._last_completeness = ""
                        self._evaluate_and_publish(source_event, 0)
                        return True
        return False

    def _try_chapter_correction(
        self,
        norm_text: str,
        source_event: SpeechCommittedWords | SpeechTranscribed,
    ) -> bool:
        """Detecta correção de capítulo após ReferenceDetected.

        Se o pregador disse "capítulo 5" após já ter apresentado uma
        referência, manter o livro e mudar o capítulo (resetando o
        verso). Publica nova ReferenceCandidate com o capítulo corrigido.
        """
        if self._current_book is None:
            return False

        tokens = norm_text.split()
        for i, tok in enumerate(tokens):
            if tok in _CHAPTER_MARKERS:
                if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                    new_chapter = int(tokens[i + 1])
                    if 1 <= new_chapter <= 200:
                        old_chapter = self._current_chapter
                        if old_chapter == new_chapter:
                            return False
                        logger.info(
                            "IncrementalParser: chapter correction "
                            "%s %d → %d (corr=%s).",
                            self._current_book.book.canonical,
                            old_chapter or 0, new_chapter,
                            self._correlation_id,
                        )
                        self._current_chapter = new_chapter
                        self._current_verse = None
                        self._current_verse_end = None
                        self._detected_published = False
                        self._anticipation_published = False
                        self._last_completeness = ""
                        self._evaluate_and_publish(source_event, 0)
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
        # Passada 1: marcadores explícitos (prioridade).
        # Ignora marcadores que aparecem antes do capítulo no texto
        # (provavelmente de uma utterance anterior misturada).
        chapter_idx = -1
        for i, tok in enumerate(tokens):
            if tok.isdigit() and int(tok) == self._current_chapter:
                chapter_idx = i
                break

        for i, tok in enumerate(tokens):
            if tok in _VERSE_MARKERS:
                # Pular se o marcador aparece antes do capítulo.
                if chapter_idx >= 0 and i < chapter_idx:
                    continue
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
        # Se o texto tem 2+ números, o primeiro é o capítulo (já
        # identificado) e o segundo é o verso. Se o texto tem apenas
        # 1 número E esse número é diferente do capítulo atual,
        # esse número é o verso (o capítulo já veio em um commit
        # anterior). Se o número único é igual ao capítulo, ignorar
        # (é o próprio capítulo sendo repetido pelo Whisper).
        if self._current_verse is None:
            digits = [int(t) for t in tokens if t.isdigit()
                      and 1 <= int(t) <= 200]
            if len(digits) >= 2:
                # Pular o primeiro (capítulo), usar o segundo.
                self._current_verse = digits[1]
                self._expecting = "done"
                logger.debug(
                    "IncrementalParser: verse=%d (unmarked, skip chapter)",
                    digits[1],
                )
                return True
            elif len(digits) == 1 and digits[0] != self._current_chapter:
                # Só um número diferente do capítulo — é o verso.
                self._current_verse = digits[0]
                self._expecting = "done"
                logger.debug(
                    "IncrementalParser: verse=%d (unmarked, single)",
                    digits[0],
                )
                return True

        return False

    def _try_find_verse_end(self, norm_text: str) -> bool:
        """Tenta identificar o versículo final de um intervalo.

        Sprint 23.2 — Reading Follow Mode.

        Procura por marcadores de intervalo ("ao", "a", "ate", "até")
        seguidos de um número, após o verse_start já identificado.

        Retorna True se encontrou verse_end.
        """
        if self._current_verse is None:
            return False

        tokens = norm_text.split()
        for i, tok in enumerate(tokens):
            if tok in _RANGE_END_MARKERS:
                if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                    verse_end = int(tokens[i + 1])
                    if verse_end > self._current_verse and verse_end <= 200:
                        self._current_verse_end = verse_end
                        logger.debug(
                            "IncrementalParser: verse_end=%d (range marker=%s)",
                            verse_end, tok,
                        )
                        return True

        return False

    # ------------------------------------------------------------------
    # Publicação de eventos
    # ------------------------------------------------------------------

    def _evaluate_and_publish(
        self,
        source_event: SpeechCommittedWords | SpeechTranscribed,
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

        # Sprint 21.9 — telemetria: registrar decisão do parser.
        corr_id = self._correlation_id or source_event.correlation_id
        book_name = book.canonical
        chapter_val = self._current_chapter or 0
        verse_val = self._current_verse or 0

        # Se confiança >= threshold e temos pelo menos book+chapter,
        # publicar ReferenceDetected.
        if confidence >= self._threshold and completeness in ("chapter", "verse"):
            # Sprint 21.9 — telemetria.
            telemetry_hooks.parser_event(
                correlation_id=corr_id,
                text_processed=self._seen_text,
                expecting=self._expecting,
                completeness=completeness,
                book=book_name,
                chapter=chapter_val,
                verse=verse_val,
                confidence=confidence,
                decision="publish_detected",
                published_event="ReferenceDetected",
                latency_ms=latency_ms,
            )
            self._publish_detected(source_event, book, confidence, latency_ms)
            self._detected_published = True
        else:
            # Publicar ReferenceCandidate (telemetria — sempre).
            # Sprint 21.9 — telemetria.
            telemetry_hooks.parser_event(
                correlation_id=corr_id,
                text_processed=self._seen_text,
                expecting=self._expecting,
                completeness=completeness,
                book=book_name,
                chapter=chapter_val,
                verse=verse_val,
                confidence=confidence,
                decision="publish_candidate",
                published_event="ReferenceCandidate",
                latency_ms=latency_ms,
            )
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
                # Sprint 21.9 — telemetria.
                telemetry_hooks.parser_event(
                    correlation_id=corr_id,
                    text_processed=self._seen_text,
                    expecting=self._expecting,
                    completeness=completeness,
                    book=book_name,
                    chapter=chapter_val,
                    verse=verse_val,
                    confidence=confidence,
                    decision="publish_antecipada",
                    published_event="ReferenceAntecipada",
                    latency_ms=latency_ms,
                )
                self._publish_anticipation(
                    source_event, book, confidence, completeness, latency_ms,
                )
                self._anticipation_published = True

    def _publish_candidate(
        self,
        source_event: SpeechCommittedWords,
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
            verse_end=self._current_verse_end or self._current_verse or 0,
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
        source_event: SpeechCommittedWords,
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
            verse_end=self._current_verse_end or self._current_verse or 0,
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
        source_event: SpeechCommittedWords,
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

        verse_end_val = self._current_verse_end or self._current_verse or 0

        event = ReferenceDetected(
            meta=meta,
            intent="OPEN_REFERENCE",
            book=book.canonical,
            book_id=book.id,
            chapter=self._current_chapter or 0,
            verse_start=self._current_verse or 0,
            verse_end=verse_end_val,
            confidence=round(confidence, 4),
            raw_text=getattr(source_event, "full_committed_text", "") or getattr(source_event, "text", ""),
            normalized_text=normalized,
        )
        self._bus.publish(event)
        self._total_detected_published += 1
        logger.info(
            "ReferenceDetected (incremental): %s %d:%d%s confidence=%.2f "
            "latency=%dms (corr=%s)",
            book.canonical,
            self._current_chapter or 0,
            self._current_verse or 0,
            f"-{verse_end_val}" if verse_end_val != (self._current_verse or 0) else "",
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
