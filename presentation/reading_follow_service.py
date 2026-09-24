"""ReadingFollowService — Sprint 23.2 + Sprint 28 (Fase 7).

Modo de acompanhamento de leitura.

Responsabilidade:
    - Ativar quando uma referência com intervalo de versículos é detectada
      (ReferenceDetected com verse_end != verse_start) ou manualmente via API.
    - Pré-carregar os textos de todos os versículos do intervalo.
    - Apresentar o versículo inicial no Holyrics.
    - Sprint 28 (Fase 7) — Consumir SpeechCommittedWords (primário, contínuo)
      com debounce 300ms, threshold adaptativo e mínimo 5 palavras.
    - Manter SpeechTranscribed como fallback (finalização).
    - Comparar o texto com o versículo atual via fuzzy matching.
    - Quando a similaridade >= threshold, avançar para o próximo versículo.
    - Desativar automaticamente ao concluir o intervalo ou manualmente.

Fluxo de eventos (Sprint 28 — Fase 7):
    ReferenceDetected (verse_end != verse_start)
        ↓
    ReadingFollowService._on_reference_detected()
        ↓
    Pré-carregar versículos via Searcher.search_by_reference()
        ↓
    HolyricsClient.show_verse(verse_start)
        ↓
    publicar ReadingFollowStarted
        ↓
    SpeechCommittedWords (contínuo)
        ↓
    _on_committed_words()
        ↓
    acumula full_committed_text em _reading_buffer
        ↓
    debounce 300ms
        ↓
    se len(buffer.split()) >= 5:
        fuzzy match (rapidfuzz) buffer vs versículo atual
        ↓
        se similaridade >= threshold_adaptativo:
            current_verse += 1
            _reading_buffer = "" (reset)
            se current_verse > verse_end → ReadingFollowEnded(reason="completed")
            senão → HolyricsClient.show_verse(current_verse) + ReadingFollowAdvanced

    SpeechTranscribed (fallback)
        ↓
    _on_speech_transcribed()
        ↓
    fuzzy match texto final (fallback se committed não avançou)

VersionChanged → recarregar versículos na nova versão e reapresentar versículo atual.
"""

from __future__ import annotations

import logging
import threading
import time
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, Protocol

from integracao_holyrics.client import HolyricsClient
from integracao_holyrics.exceptions import HolyricsError
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    NavigationCommandDetected,
    ReadingFollowAdvanced,
    ReadingFollowEnded,
    ReadingFollowStarted,
    ReferenceDetected,
    SpeechCommittedWords,
    SpeechTranscribed,
    VersePresented,
    VersionChanged,
)
from pipeline.metadata import EventMetadata

logger = logging.getLogger(__name__)

__all__ = ["ReadingFollowService", "SearcherProtocol", "adaptive_threshold"]


_DEFAULT_FUZZY_THRESHOLD = 0.70

# Sprint 28 (Fase 7) — Continuous Reading Follow.
_DEFAULT_DEBOUNCE_MS = 300
_DEFAULT_MIN_WORDS = 5

# Sprint 30 — Cursor sequencial de palavras (detecção de fim de verso).
# Em vez de partial_ratio do buffer acumulado (que casa o versículo em
# qualquer posição da fala e não prova que a CAUDA foi lida), cada
# palavra committed nova avança um cursor sobre as palavras do
# versículo — em ordem. O versículo só é considerado lido quando o
# cursor atinge a cauda (N-2 palavras ou >=80% de cobertura).
_LOOKAHEAD_WORDS = 6        # tolera palavras puladas/misheard
_TAIL_SLACK = 2             # últimas N palavras podem ser perdidas
_COMPLETION_RATIO = 0.80    # cobertura mínima combinada com cauda
_MIN_MATCHED_WORDS = 4      # mínimo absoluto de palavras casadas
_WORD_FUZZY_MIN = 85.0      # similaridade por palavra (>=4 chars)


class SearcherProtocol(Protocol):
    """Interface mínima do Searcher usada por ReadingFollowService."""

    def search_by_reference(
        self,
        book_name: str,
        chapter: int,
        verse: int | None = None,
        *,
        version: str | None = None,
    ) -> Any: ...

    def search_chapter(
        self,
        book_name: str,
        chapter: int,
        *,
        version: str | None = None,
    ) -> Any: ...


def _normalize_text(text: str) -> str:
    """Normaliza texto para comparação: lowercase, sem acentos, sem pontuação."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    import re
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fuzzy_similarity(text1: str, text2: str) -> float:
    """Calcula similaridade fuzzy entre dois textos [0.0, 1.0].

    Usa rapiduzz partial_ratio para ser tolerante a texto extra
    (comentários do pregador antes/depois do versículo).
    """
    try:
        from rapidfuzz import fuzz
        score = fuzz.partial_ratio(text1, text2)
        return score / 100.0
    except ImportError:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, text1, text2).ratio()


def _word_match(spoken: str, verse_word: str) -> bool:
    """True se a palavra falada corresponde à palavra do versículo.

    Exato após normalização; fuzzy (>=0.85) apenas para palavras com
    >=4 caracteres — palavras curtas ("e", "de", "o") só casam exatas
    para não gerar falsos avanços do cursor.
    """
    if spoken == verse_word:
        return True
    if len(spoken) < 4 or len(verse_word) < 4:
        return False
    try:
        from rapidfuzz import fuzz
        return fuzz.ratio(spoken, verse_word) >= _WORD_FUZZY_MIN
    except ImportError:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, spoken, verse_word).ratio() >= _WORD_FUZZY_MIN / 100.0


def adaptive_threshold(verse_word_count: int) -> float:
    """Threshold adaptativo de fuzzy match (Sprint 28 — Fase 7, §15.5).

    Versículos curtos (< 30 palavras): 0.65 (mais tolerante).
    Versículos médios (30-79 palavras): 0.70 (padrão).
    Versículos longos (>= 80 palavras): 0.75 (mais estrito).
    """
    if verse_word_count < 30:
        return 0.65
    elif verse_word_count < 80:
        return 0.70
    else:
        return 0.75


@dataclass
class FollowState:
    """Estado imutável do modo de acompanhamento."""

    active: bool = False
    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse_start: int = 0
    verse_end: int = 0
    current_verse: int = 0
    version: str = "ACF"
    # Versão usada para COMPARAR a leitura (a Bíblia do pastor). Quando
    # igual à versão apresentada, o matching é mais confiável; se o
    # pastor lê outra versão, o operador configura separadamente.
    match_version: str = ""
    # Progresso dentro do versículo atual (0..1 — cursor/palavras).
    verse_progress: float = 0.0
    verse_texts: dict[int, str] | None = None

    def to_dict(self) -> dict:
        return {
            "active": self.active,
            "book": self.book,
            "book_id": self.book_id,
            "chapter": self.chapter,
            "verse_start": self.verse_start,
            "verse_end": self.verse_end,
            "current_verse": self.current_verse,
            "version": self.version,
            "match_version": self.match_version or self.version,
            "verse_progress": self.verse_progress,
            "total_verses": max(0, self.verse_end - self.verse_start + 1) if self.active else 0,
            "verses_read": max(0, self.current_verse - self.verse_start) if self.active else 0,
        }


class ReadingFollowService:
    """Serviço de acompanhamento de leitura de versículos.

    Sprint 28 (Fase 7) — Continuous Reading Follow:
        - Consome SpeechCommittedWords (primário, contínuo) com debounce.
        - Threshold adaptativo (0.65/0.70/0.75) baseado no tamanho do versículo.
        - Mínimo 5 committed words antes de fuzzy-match.
        - Mantém SpeechTranscribed como fallback.

    Args:
        searcher: Searcher (ou mock) para resolver versículos.
        holyrics: HolyricsClient para apresentar versículos.
        bus: PipelineEventBus para assinar e publicar eventos.
        session_id: ID da sessão atual.
        version: versão bíblica padrão.
        fuzzy_threshold: similaridade mínima para considerar versículo lido
            (fallback; threshold adaptativo é usado quando versículo está
            disponível).
        debounce_ms: debounce em ms após committed words antes de fuzzy-match.
        min_words: mínimo de committed words antes de fuzzy-match.
    """

    def __init__(
        self,
        searcher: SearcherProtocol,
        holyrics: HolyricsClient,
        bus: PipelineEventBus,
        session_id: str,
        version: str = "ACF",
        fuzzy_threshold: float = _DEFAULT_FUZZY_THRESHOLD,
        # Sprint 28 (Fase 7) — Continuous Reading Follow.
        debounce_ms: int = _DEFAULT_DEBOUNCE_MS,
        min_words: int = _DEFAULT_MIN_WORDS,
        # Sprint 30 — versão de leitura separada + auto-follow em
        # versículo apresentado.
        match_version: str | None = None,
        auto_follow_on_present: bool = True,
    ) -> None:
        self._searcher = searcher
        self._holyrics = holyrics
        self._bus = bus
        self._session_id = session_id
        self._version = version
        self._match_version = match_version or ""
        self._auto_follow = auto_follow_on_present
        self._fuzzy_threshold = fuzzy_threshold
        self._subscribed = False

        # Sprint 28 (Fase 7) — Continuous Reading Follow.
        self._debounce_ms = debounce_ms
        self._min_words = min_words
        self._reading_buffer = ""
        self._debounce_timer: threading.Timer | None = None
        self._buffer_lock = threading.Lock()

        # Sprint 30 — cursor sequencial sobre as palavras do versículo.
        self._verse_words: list[str] = []
        self._cursor: int = 0

        self._state = FollowState(version=version, match_version=self._match_version)

        logger.info(
            "ReadingFollowService initialized "
            "(version=%s, fuzzy_threshold=%.2f, debounce_ms=%d, min_words=%d).",
            version, fuzzy_threshold, debounce_ms, min_words,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inscreve no EventBus.

        Sprint 28 (Fase 7) — adiciona SpeechCommittedWords (primário).
        Sprint 28 (Fase 8) — adiciona NavigationCommandDetected.
        """
        if self._subscribed:
            return
        self._bus.subscribe(ReferenceDetected, self._on_reference_detected)
        self._bus.subscribe(SpeechCommittedWords, self._on_committed_words)
        self._bus.subscribe(SpeechTranscribed, self._on_speech_transcribed)
        self._bus.subscribe(VersionChanged, self._on_version_changed)
        self._bus.subscribe(NavigationCommandDetected, self._on_navigation_command)
        # Sprint 30 — ancora o follow no versículo apresentado (painel
        # do operador ou pipeline automático — ambos publicam
        # VersePresented). O próprio serviço NÃO publica VersePresented
        # ao apresentar (usa holyrics.show_verse direto), sem loop.
        self._bus.subscribe(VersePresented, self._on_verse_presented)
        self._subscribed = True
        logger.info(
            "ReadingFollowService started — subscribed to "
            "ReferenceDetected, SpeechCommittedWords, SpeechTranscribed, "
            "VersionChanged, NavigationCommandDetected, VersePresented."
        )

    def stop(self) -> None:
        """Desinscreve do EventBus."""
        if not self._subscribed:
            return
        self._bus.unsubscribe(ReferenceDetected, self._on_reference_detected)
        self._bus.unsubscribe(SpeechCommittedWords, self._on_committed_words)
        self._bus.unsubscribe(SpeechTranscribed, self._on_speech_transcribed)
        self._bus.unsubscribe(VersionChanged, self._on_version_changed)
        self._bus.unsubscribe(NavigationCommandDetected, self._on_navigation_command)
        # Cancelar debounce timer se ativo.
        with self._buffer_lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
        self._subscribed = False
        logger.info("ReadingFollowService stopped.")

    # ------------------------------------------------------------------
    # API pública (chamada via router do operador)
    # ------------------------------------------------------------------

    def activate(
        self,
        book_id: int,
        book_name: str,
        chapter: int,
        verse_start: int,
        verse_end: int,
        version: str | None = None,
        match_version: str | None = None,
    ) -> bool:
        """Ativa o modo de acompanhamento manualmente.

        Se ``verse_end <= verse_start``, o versículo único ancora o
        acompanhamento até o fim do capítulo (resolvido via
        ``search_chapter``).

        Returns:
            True se ativado com sucesso, False se já ativo ou erro.
        """
        if self._state.active:
            logger.warning("ReadingFollowService: já ativo, ignorando ativação.")
            return False

        ver = version or self._version
        if match_version is not None:
            self._match_version = match_version
        mv = self._match_version or ver

        if verse_end <= verse_start:
            # Versículo único — seguir até o fim do capítulo.
            verse_end = self._resolve_chapter_end(book_name, chapter, mv)
            if verse_end <= verse_start:
                logger.warning(
                    "ReadingFollowService: não foi possível resolver fim "
                    "do capítulo %s %d (verse_start=%d).",
                    book_name, chapter, verse_start,
                )
                return False

        return self._do_activate(
            book_id=book_id,
            book_name=book_name,
            chapter=chapter,
            verse_start=verse_start,
            verse_end=verse_end,
            version=ver,
        )

    def set_match_version(self, version: str | None) -> bool:
        """Define a versão de leitura do pastor (para comparação).

        ``None``/vazio = mesma versão apresentada. Se a versão de
        leitura não existir na base local, cai para a padrão via
        ``local_version()`` no carregamento dos textos.
        """
        mv = (version or "").strip()
        old = self._match_version
        self._match_version = mv
        if self._state.active and old != mv:
            self._state = replace(self._state, match_version=mv)
            self._reload_verse_texts()
            self._reset_cursor()
            logger.info(
                "ReadingFollowService: match_version %s → %s (reloaded).",
                old or "(=apresentação)", mv or "(=apresentação)",
            )
        else:
            self._state = replace(self._state, match_version=mv)
            logger.info(
                "ReadingFollowService: match_version set to %s (inactive).",
                mv or "(=apresentação)",
            )
        return True

    def _resolve_chapter_end(
        self, book_name: str, chapter: int, version: str,
    ) -> int:
        """Último versículo do capítulo na base local (0 se falhar)."""
        from presentation.version_map import local_version
        try:
            results = self._searcher.search_chapter(
                book_name, chapter, version=local_version(version),
            )
            verses = [r.verse for r in results if getattr(r, "verse", None)]
            return max(verses) if verses else 0
        except Exception:
            logger.exception(
                "ReadingFollowService: erro resolvendo fim do capítulo "
                "%s %d.", book_name, chapter,
            )
            return 0

    def deactivate(self) -> bool:
        """Desativa o modo de acompanhamento manualmente.

        Returns:
            True se desativado, False se já inativo.
        """
        if not self._state.active:
            return False
        self._do_deactivate(reason="manual_stop")
        return True

    def advance(self) -> bool:
        """Avança manualmente para o próximo versículo.

        Returns:
            True se avançou, False se inativo ou no último versículo.
        """
        if not self._state.active:
            return False

        next_verse = self._state.current_verse + 1
        if next_verse > self._state.verse_end:
            self._do_deactivate(reason="completed")
            return False

        prev = self._state.current_verse
        self._state = replace(
            self._state, current_verse=next_verse, verse_progress=0.0,
        )
        self._reset_cursor()

        self._present_verse(next_verse)
        self._publish_advanced(prev, next_verse, 1.0)
        logger.info(
            "ReadingFollowService: manual advance to %s %d:%d",
            self._state.book, self._state.chapter, next_verse,
        )
        return True

    def set_version(self, version: str) -> bool:
        """Muda a versão ativa e recarrega os textos dos versículos.

        Returns:
            True se mudou, False se versão inválida ou erro.
        """
        if not version or not version.strip():
            return False

        # Keys do Holyrics (pt_acf, en_kjv...) permanecem lowercase —
        # nomes locais simples ("acf") viram "ACF".
        from presentation.version_map import normalize_version_key
        version = normalize_version_key(version)
        if self._state.active:
            old = self._state.version
            self._version = version
            self._state = replace(self._state, version=version, verse_progress=0.0)
            self._reset_cursor()
            self._reload_verse_texts()
            self._present_verse(self._state.current_verse)
            logger.info(
                "ReadingFollowService: version changed %s → %s (reloaded).",
                old, version,
            )
        else:
            self._version = version
            self._state = replace(
                FollowState(version=version),
                match_version=self._match_version,
            )
            logger.info(
                "ReadingFollowService: version set to %s (inactive).",
                version,
            )
        return True

    def get_state(self) -> dict:
        """Retorna o estado atual como dict (para API/frontend)."""
        return self._state.to_dict()

    # ------------------------------------------------------------------
    # Handlers do EventBus
    # ------------------------------------------------------------------

    def _on_reference_detected(self, event: ReferenceDetected) -> None:
        """Ativa/re-ancora quando ReferenceDetected chega (intervalo ou único).

        Sprint 30 — versículo único também ancora o follow (até o fim
        do capítulo). Se já ativo, uma nova referência re-ancora —
        o pregador mudou de passagem.
        """
        if event.book_id <= 0 or event.chapter <= 0 or event.verse_start <= 0:
            return

        verse_end = event.verse_end if event.verse_end > event.verse_start else 0

        if self._state.active:
            # Re-ancorar apenas se for referência diferente.
            same = (
                self._state.book_id == event.book_id
                and self._state.chapter == event.chapter
                and self._state.current_verse == event.verse_start
            )
            if same:
                return
            self._do_deactivate(reason="reanchored")

        if verse_end <= 0:
            verse_end = self._resolve_chapter_end(
                event.book, event.chapter, self._match_version or self._version,
            )
            if verse_end <= event.verse_start:
                return

        self._do_activate(
            book_id=event.book_id,
            book_name=event.book,
            chapter=event.chapter,
            verse_start=event.verse_start,
            verse_end=verse_end,
            version=self._version,
        )

    def _on_verse_presented(self, event: VersePresented) -> None:
        """Ancora o follow no versículo apresentado (Sprint 30).

        Qualquer apresentação (OperatorPanel ou pipeline automático)
        publica VersePresented — o follow ancora nesse versículo e
        segue até o fim do capítulo. Se o pastor não ler, nada acontece;
        se ler até o fim, avança sozinho.
        """
        if not self._auto_follow:
            return
        if event.book_id <= 0 or event.chapter <= 0 or event.verse <= 0:
            return

        if self._state.active:
            same = (
                self._state.book_id == event.book_id
                and self._state.chapter == event.chapter
                and self._state.current_verse == event.verse
            )
            if same:
                return
            self._do_deactivate(reason="reanchored")

        verse_end = self._resolve_chapter_end(
            event.book, event.chapter, self._match_version or self._version,
        )
        if verse_end <= event.verse:
            return

        self._do_activate(
            book_id=event.book_id,
            book_name=event.book,
            chapter=event.chapter,
            verse_start=event.verse,
            verse_end=verse_end,
            version=self._version,
        )

    def _on_committed_words(self, event: SpeechCommittedWords) -> None:
        """Consome SpeechCommittedWords — cursor sequencial (Sprint 30).

        Processa committed_text (palavras NOVAS confirmadas) palavra a
        palavra, avançando o cursor sobre o versículo atual em ordem.
        O versículo só é considerado lido quando a CAUDA é alcançada
        (cursor >= max(N-2, 80% de N)). Palavras restantes no chunk já
        começam a casar com o próximo versículo — leitura contínua.
        """
        if not self._state.active:
            return

        if not event.committed_text:
            return

        norm = _normalize_text(event.committed_text)
        words = [w for w in norm.split() if w]
        if not words:
            return

        with self._buffer_lock:
            self._reading_buffer = (
                self._reading_buffer + " " + event.committed_text
            ).strip()

        self._consume_words(words)

    def _consume_words(self, words: list[str]) -> None:
        """Avança o cursor do versículo com as palavras committed.

        Palavras que não casam são ignoradas (pregador comentando).
        Quando a cauda do versículo é alcançada, avança e as palavras
        restantes continuam casando com o versículo seguinte.
        """
        for w in words:
            if not self._state.active or not self._verse_words:
                return
            j = self._find_next_word(w)
            if j is None:
                continue
            self._cursor = j + 1
            self._state = replace(
                self._state,
                verse_progress=round(self._cursor / len(self._verse_words), 3),
            )
            if self._verse_complete():
                coverage = self._cursor / len(self._verse_words)
                logger.info(
                    "ReadingFollowService: verse tail reached "
                    "(cursor=%d/%d, verse=%d) — advancing.",
                    self._cursor, len(self._verse_words),
                    self._state.current_verse,
                )
                with self._buffer_lock:
                    self._reading_buffer = ""
                self._advance_verse(coverage)

    def _find_next_word(self, spoken: str) -> int | None:
        """Índice da próxima palavra do versículo que casa com `spoken`.

        Busca em [cursor, cursor+LOOKAHEAD) — tolera o pregador pulando
        algumas palavras ou erros pontuais do Whisper.
        """
        n = len(self._verse_words)
        end = min(self._cursor + _LOOKAHEAD_WORDS, n)
        for j in range(self._cursor, end):
            if _word_match(spoken, self._verse_words[j]):
                return j
        return None

    def _verse_complete(self) -> bool:
        """True quando a cauda do versículo foi lida.

        cursor >= max(N - tail_slack, 80% de N): exige que as últimas
        palavras do versículo tenham sido ditas (em ordem), não apenas
        uma parte do início.
        """
        n = len(self._verse_words)
        if n == 0:
            return False
        needed = max(n - _TAIL_SLACK, int(n * _COMPLETION_RATIO + 0.999),
                     min(_MIN_MATCHED_WORDS, n))
        return self._cursor >= needed

    def _reset_cursor(self) -> None:
        """Reseta cursor e recarrega palavras do versículo atual."""
        self._cursor = 0
        text = (self._state.verse_texts or {}).get(self._state.current_verse, "")
        self._verse_words = [w for w in _normalize_text(text).split() if w]
        if self._state.active:
            self._state = replace(self._state, verse_progress=0.0)

    def _try_advance_from_buffer(self) -> None:
        """Tenta avançar versículo via fuzzy match no _reading_buffer.

        Chamado pelo debounce timer. Verifica mínimo de palavras e
        threshold adaptativo.
        """
        if not self._state.active:
            return

        with self._buffer_lock:
            buffer_text = self._reading_buffer
            # Limpar timer reference.
            self._debounce_timer = None

        if not buffer_text:
            return

        if self._state.verse_texts is None:
            return

        current_text = self._state.verse_texts.get(self._state.current_verse)
        if not current_text:
            return

        norm_buffer = _normalize_text(buffer_text)
        norm_verse = _normalize_text(current_text)

        if not norm_buffer or not norm_verse:
            return

        # Verificar mínimo de palavras.
        word_count = len(norm_buffer.split())
        if word_count < self._min_words:
            logger.debug(
                "ReadingFollowService: buffer tem %d palavras (< %d mínimo), "
                "aguardando mais committed words.",
                word_count, self._min_words,
            )
            return

        # Threshold adaptativo baseado no tamanho do versículo.
        verse_word_count = len(norm_verse.split())
        threshold = adaptive_threshold(verse_word_count)

        score = _fuzzy_similarity(norm_buffer, norm_verse)
        logger.info(
            "ReadingFollowService: fuzzy match (committed) score=%.2f "
            "(verse=%d, threshold=%.2f, verse_words=%d, buffer_words=%d)",
            score, self._state.current_verse, threshold,
            verse_word_count, word_count,
        )

        if score >= threshold:
            # Resetar buffer após avanço bem-sucedido.
            with self._buffer_lock:
                self._reading_buffer = ""
            self._advance_verse(score)

    def _on_speech_transcribed(self, event: SpeechTranscribed) -> None:
        """Compara texto transcrito com versículo atual e avança se lido.

        Fallback (Sprint 30): só age se o cursor sequencial não
        progrediu neste versículo (cursor == 0) — se o cursor está
        avançando via committed words, o fuzzy do texto final só
        arriscaria avanço duplo.
        """
        if not self._state.active:
            return

        if self._cursor > 0:
            return

        if not event.text or not event.text.strip():
            return

        if self._state.verse_texts is None:
            return

        current_text = self._state.verse_texts.get(self._state.current_verse)
        if not current_text:
            return

        norm_transcribed = _normalize_text(event.text)
        norm_verse = _normalize_text(current_text)

        if not norm_transcribed or not norm_verse:
            return

        # Threshold adaptativo baseado no tamanho do versículo.
        verse_word_count = len(norm_verse.split())
        threshold = adaptive_threshold(verse_word_count)

        score = _fuzzy_similarity(norm_transcribed, norm_verse)
        logger.info(
            "ReadingFollowService: fuzzy match (transcribed) score=%.2f "
            "(verse=%d, threshold=%.2f)",
            score, self._state.current_verse, threshold,
        )

        if score >= threshold:
            # Resetar buffer após avanço.
            with self._buffer_lock:
                self._reading_buffer = ""
            self._advance_verse(score)

    def _on_version_changed(self, event: VersionChanged) -> None:
        """Recarrega versículos quando a versão muda."""
        if not self._state.active:
            self._version = event.new_version
            return

        self._state = replace(
            self._state, version=event.new_version, verse_progress=0.0,
        )
        self._version = event.new_version
        self._reset_cursor()
        self._reload_verse_texts()
        self._present_verse(self._state.current_verse)
        logger.info(
            "ReadingFollowService: version changed via event to %s.",
            event.new_version,
        )

    def _on_navigation_command(self, event: NavigationCommandDetected) -> None:
        """Processa NavigationCommandDetected (Sprint 28 — Fase 8).

        Executa retrocesso/avanço/pulo conforme o comando detectado.
        Só age se o modo de acompanhamento estiver ativo.
        """
        if not self._state.active:
            return

        if event.command == "back":
            self._navigate_back(event.confidence)
        elif event.command == "forward":
            self._navigate_forward(event.confidence)
        elif event.command == "goto_verse":
            self._navigate_to_verse(event.target_value, event.confidence)
        elif event.command == "goto_chapter":
            # goto_chapter não é suportado dentro do ReadingFollow
            # (que opera em um intervalo fixo). Logar e ignorar.
            logger.info(
                "ReadingFollowService: goto_chapter(%d) ignorado "
                "(não suportado em modo de acompanhamento).",
                event.target_value,
            )

    def _navigate_back(self, confidence: float) -> None:
        """Retrocede 1 versículo (mínimo = verse_start)."""
        prev = self._state.current_verse
        new_verse = max(self._state.verse_start, prev - 1)
        if new_verse == prev:
            logger.info(
                "ReadingFollowService: back ignorado (já no versículo inicial %d).",
                prev,
            )
            return

        self._state = replace(
            self._state, current_verse=new_verse, verse_progress=0.0,
        )
        self._reset_cursor()
        # Resetar buffer de leitura.
        with self._buffer_lock:
            self._reading_buffer = ""
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None

        self._present_verse(new_verse)
        self._publish_advanced(prev, new_verse, confidence, reason="voice_command_back")
        logger.info(
            "ReadingFollowService: voice command back → %s %d:%d.",
            self._state.book, self._state.chapter, new_verse,
        )

    def _navigate_forward(self, confidence: float) -> None:
        """Avança 1 versículo (máximo = verse_end)."""
        prev = self._state.current_verse
        new_verse = min(self._state.verse_end, prev + 1)
        if new_verse == prev:
            # No último versículo — desativar.
            self._do_deactivate(reason="completed")
            return

        self._state = replace(
            self._state, current_verse=new_verse, verse_progress=0.0,
        )
        self._reset_cursor()
        # Resetar buffer de leitura.
        with self._buffer_lock:
            self._reading_buffer = ""
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None

        self._present_verse(new_verse)
        self._publish_advanced(prev, new_verse, confidence, reason="voice_command_forward")
        logger.info(
            "ReadingFollowService: voice command forward → %s %d:%d.",
            self._state.book, self._state.chapter, new_verse,
        )

    def _navigate_to_verse(self, verse: int, confidence: float) -> None:
        """Pula para versículo N do capítulo atual (dentro do intervalo)."""
        if verse < self._state.verse_start or verse > self._state.verse_end:
            logger.info(
                "ReadingFollowService: goto_verse(%d) fora do intervalo [%d-%d].",
                verse, self._state.verse_start, self._state.verse_end,
            )
            return

        prev = self._state.current_verse
        self._state = replace(
            self._state, current_verse=verse, verse_progress=0.0,
        )
        self._reset_cursor()
        # Resetar buffer de leitura.
        with self._buffer_lock:
            self._reading_buffer = ""
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None

        self._present_verse(verse)
        self._publish_advanced(prev, verse, confidence, reason="voice_command_goto")
        logger.info(
            "ReadingFollowService: voice command goto_verse → %s %d:%d.",
            self._state.book, self._state.chapter, verse,
        )

    # ------------------------------------------------------------------
    # Lógica interna
    # ------------------------------------------------------------------

    def _do_activate(
        self,
        book_id: int,
        book_name: str,
        chapter: int,
        verse_start: int,
        verse_end: int,
        version: str,
    ) -> bool:
        """Executa a ativação do modo."""
        verse_texts = self._load_verse_texts(
            book_name, chapter, verse_start, verse_end, version,
        )
        if not verse_texts:
            logger.error(
                "ReadingFollowService: falha ao carregar versículos "
                "%s %d:%d-%d (%s).",
                book_name, chapter, verse_start, verse_end, version,
            )
            return False

        self._state = FollowState(
            active=True,
            book=book_name,
            book_id=book_id,
            chapter=chapter,
            verse_start=verse_start,
            verse_end=verse_end,
            current_verse=verse_start,
            version=version,
            match_version=self._match_version,
            verse_progress=0.0,
            verse_texts=verse_texts,
        )
        # Sprint 30 — inicializar cursor do versículo inicial.
        self._reset_cursor()

        # Sprint 28 (Fase 7) — limpar buffer de leitura ao ativar.
        with self._buffer_lock:
            self._reading_buffer = ""
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None

        self._present_verse(verse_start)
        self._publish_started()
        logger.info(
            "ReadingFollowService: activated — %s %d:%d-%d (%s).",
            book_name, chapter, verse_start, verse_end, version,
        )
        return True

    def _do_deactivate(self, reason: str) -> None:
        """Executa a desativação do modo."""
        last_verse = self._state.current_verse
        book = self._state.book
        chapter = self._state.chapter
        self._state = replace(
            FollowState(version=self._version),
            match_version=self._match_version,
        )
        self._verse_words = []
        self._cursor = 0
        # Sprint 28 (Fase 7) — limpar buffer e cancelar debounce timer.
        with self._buffer_lock:
            self._reading_buffer = ""
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
        self._publish_ended(book, chapter, last_verse, reason)
        logger.info(
            "ReadingFollowService: deactivated (reason=%s, last_verse=%d).",
            reason, last_verse,
        )

    def _advance_verse(self, match_score: float) -> None:
        """Avança para o próximo versículo após fuzzy match positivo."""
        next_verse = self._state.current_verse + 1

        if next_verse > self._state.verse_end:
            self._do_deactivate(reason="completed")
            return

        prev = self._state.current_verse
        self._state = replace(
            self._state, current_verse=next_verse, verse_progress=0.0,
        )
        self._reset_cursor()

        self._present_verse(next_verse)
        self._publish_advanced(prev, next_verse, match_score)
        logger.info(
            "ReadingFollowService: advanced to %s %d:%d (score=%.2f).",
            self._state.book, self._state.chapter, next_verse, match_score,
        )

    def _load_verse_texts(
        self,
        book_name: str,
        chapter: int,
        verse_start: int,
        verse_end: int,
        version: str,
    ) -> dict[int, str]:
        """Pré-carrega os textos de todos os versículos do intervalo.

        Os textos são carregados na versão de LEITURA (match_version —
        a Bíblia que o pastor está lendo), que pode diferir da versão
        apresentada. A base FTS5 local cobre apenas algumas versões —
        keys do Holyrics (pt_*, en_*...) são mapeadas para a versão
        local equivalente quando existir.
        """
        from presentation.version_map import local_version
        version = local_version(self._match_version or version)
        texts: dict[int, str] = {}
        for v in range(verse_start, verse_end + 1):
            try:
                result = self._searcher.search_by_reference(
                    book_name, chapter, v, version=version,
                )
                if result is not None and hasattr(result, "text"):
                    texts[v] = result.text
                else:
                    logger.warning(
                        "ReadingFollowService: versículo %d não encontrado.",
                        v,
                    )
            except Exception:
                logger.exception(
                    "ReadingFollowService: erro ao buscar versículo %d.", v,
                )
        return texts

    def _reload_verse_texts(self) -> None:
        """Recarrega os textos dos versículos na versão atual."""
        if not self._state.active:
            return
        texts = self._load_verse_texts(
            self._state.book,
            self._state.chapter,
            self._state.verse_start,
            self._state.verse_end,
            self._state.version,
        )
        if texts:
            self._state = replace(self._state, verse_texts=texts)
            self._reset_cursor()

    def _present_verse(self, verse: int) -> None:
        """Apresenta o versículo no Holyrics."""
        try:
            self._holyrics.show_verse(
                book_id=self._state.book_id,
                chapter=self._state.chapter,
                verse=verse,
                version=self._state.version,
            )
        except HolyricsError:
            logger.exception(
                "ReadingFollowService: erro Holyrics ao apresentar %s %d:%d.",
                self._state.book, self._state.chapter, verse,
            )

    # ------------------------------------------------------------------
    # Publicação de eventos
    # ------------------------------------------------------------------

    def _publish_started(self) -> None:
        meta = EventMetadata.for_session_event(
            session_id=self._session_id,
            origin="ReadingFollowService",
        )
        self._bus.publish(ReadingFollowStarted(
            meta=meta,
            book=self._state.book,
            book_id=self._state.book_id,
            chapter=self._state.chapter,
            verse_start=self._state.verse_start,
            verse_end=self._state.verse_end,
            current_verse=self._state.current_verse,
            version=self._state.version,
        ))

    def _publish_advanced(
        self, prev_verse: int, current_verse: int, match_score: float,
        reason: str = "fuzzy_match",
    ) -> None:
        meta = EventMetadata.for_session_event(
            session_id=self._session_id,
            origin="ReadingFollowService",
        )
        self._bus.publish(ReadingFollowAdvanced(
            meta=meta,
            book=self._state.book,
            book_id=self._state.book_id,
            chapter=self._state.chapter,
            previous_verse=prev_verse,
            current_verse=current_verse,
            version=self._state.version,
            match_score=round(match_score, 4),
            reason=reason,
        ))

    def _publish_ended(
        self, book: str, chapter: int, last_verse: int, reason: str,
    ) -> None:
        meta = EventMetadata.for_session_event(
            session_id=self._session_id,
            origin="ReadingFollowService",
        )
        self._bus.publish(ReadingFollowEnded(
            meta=meta,
            book=book,
            chapter=chapter,
            last_verse=last_verse,
            reason=reason,
        ))
