"""ReadingFollowService — Sprint 23.2.

Modo de acompanhamento de leitura.

Responsabilidade:
    - Ativar quando uma referência com intervalo de versículos é detectada
      (ReferenceDetected com verse_end != verse_start) ou manualmente via API.
    - Pré-carregar os textos de todos os versículos do intervalo.
    - Apresentar o versículo inicial no Holyrics.
    - Consumir SpeechTranscribed (transcrição final após pausa do VAD).
    - Comparar o texto transcrito com o versículo atual via fuzzy matching.
    - Quando a similaridade >= threshold, avançar para o próximo versículo.
    - Desativar automaticamente ao concluir o intervalo ou manualmente.

Fluxo de eventos:
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
    SpeechTranscribed
        ↓
    _on_speech_transcribed()
        ↓
    fuzzy match (rapidfuzz) texto transcrito vs versículo atual
        ↓
    se similaridade >= threshold:
        current_verse += 1
        se current_verse > verse_end → publicar ReadingFollowEnded(reason="completed")
        senão → HolyricsClient.show_verse(current_verse) + publicar ReadingFollowAdvanced

VersionChanged → recarregar versículos na nova versão e reapresentar versículo atual.
"""

from __future__ import annotations

import logging
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol

from integracao_holyrics.client import HolyricsClient
from integracao_holyrics.exceptions import HolyricsError
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    ReadingFollowAdvanced,
    ReadingFollowEnded,
    ReadingFollowStarted,
    ReferenceDetected,
    SpeechTranscribed,
    VersionChanged,
)
from pipeline.metadata import EventMetadata

logger = logging.getLogger(__name__)

__all__ = ["ReadingFollowService", "SearcherProtocol"]


_DEFAULT_FUZZY_THRESHOLD = 0.70


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
            "total_verses": max(0, self.verse_end - self.verse_start + 1) if self.active else 0,
            "verses_read": max(0, self.current_verse - self.verse_start) if self.active else 0,
        }


class ReadingFollowService:
    """Serviço de acompanhamento de leitura de versículos.

    Args:
        searcher: Searcher (ou mock) para resolver versículos.
        holyrics: HolyricsClient para apresentar versículos.
        bus: PipelineEventBus para assinar e publicar eventos.
        session_id: ID da sessão atual.
        version: versão bíblica padrão.
        fuzzy_threshold: similaridade mínima para considerar versículo lido.
    """

    def __init__(
        self,
        searcher: SearcherProtocol,
        holyrics: HolyricsClient,
        bus: PipelineEventBus,
        session_id: str,
        version: str = "ACF",
        fuzzy_threshold: float = _DEFAULT_FUZZY_THRESHOLD,
    ) -> None:
        self._searcher = searcher
        self._holyrics = holyrics
        self._bus = bus
        self._session_id = session_id
        self._version = version
        self._fuzzy_threshold = fuzzy_threshold
        self._subscribed = False

        self._state = FollowState(version=version)

        logger.info(
            "ReadingFollowService initialized "
            "(version=%s, fuzzy_threshold=%.2f).",
            version, fuzzy_threshold,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inscreve no EventBus."""
        if self._subscribed:
            return
        self._bus.subscribe(ReferenceDetected, self._on_reference_detected)
        self._bus.subscribe(SpeechTranscribed, self._on_speech_transcribed)
        self._bus.subscribe(VersionChanged, self._on_version_changed)
        self._subscribed = True
        logger.info("ReadingFollowService started — subscribed to events.")

    def stop(self) -> None:
        """Desinscreve do EventBus."""
        if not self._subscribed:
            return
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
    ) -> bool:
        """Ativa o modo de acompanhamento manualmente.

        Returns:
            True se ativado com sucesso, False se já ativo ou erro.
        """
        if self._state.active:
            logger.warning("ReadingFollowService: já ativo, ignorando ativação.")
            return False

        if verse_end <= verse_start:
            logger.warning(
                "ReadingFollowService: verse_end (%d) deve ser > verse_start (%d).",
                verse_end, verse_start,
            )
            return False

        return self._do_activate(
            book_id=book_id,
            book_name=book_name,
            chapter=chapter,
            verse_start=verse_start,
            verse_end=verse_end,
            version=version or self._version,
        )

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
        self._state = FollowState(
            active=True,
            book=self._state.book,
            book_id=self._state.book_id,
            chapter=self._state.chapter,
            verse_start=self._state.verse_start,
            verse_end=self._state.verse_end,
            current_verse=next_verse,
            version=self._state.version,
            verse_texts=self._state.verse_texts,
        )

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

        version = version.strip().upper()
        if self._state.active:
            old = self._state.version
            self._version = version
            self._state = FollowState(
                active=True,
                book=self._state.book,
                book_id=self._state.book_id,
                chapter=self._state.chapter,
                verse_start=self._state.verse_start,
                verse_end=self._state.verse_end,
                current_verse=self._state.current_verse,
                version=version,
                verse_texts=self._state.verse_texts,
            )
            self._reload_verse_texts()
            self._present_verse(self._state.current_verse)
            logger.info(
                "ReadingFollowService: version changed %s → %s (reloaded).",
                old, version,
            )
        else:
            self._version = version
            self._state = FollowState(version=version)
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
        """Ativa automaticamente quando ReferenceDetected tem intervalo."""
        if self._state.active:
            return

        if event.verse_end <= 0 or event.verse_end <= event.verse_start:
            return

        if event.book_id <= 0 or event.chapter <= 0:
            return

        self._do_activate(
            book_id=event.book_id,
            book_name=event.book,
            chapter=event.chapter,
            verse_start=event.verse_start,
            verse_end=event.verse_end,
            version=self._version,
        )

    def _on_speech_transcribed(self, event: SpeechTranscribed) -> None:
        """Compara texto transcrito com versículo atual e avança se lido."""
        if not self._state.active:
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

        score = _fuzzy_similarity(norm_transcribed, norm_verse)
        logger.info(
            "ReadingFollowService: fuzzy match score=%.2f (verse=%d, text=%q...)",
            score, self._state.current_verse, event.text[:80],
        )

        if score >= self._fuzzy_threshold:
            self._advance_verse(score)

    def _on_version_changed(self, event: VersionChanged) -> None:
        """Recarrega versículos quando a versão muda."""
        if not self._state.active:
            self._version = event.new_version
            return

        self._state = FollowState(
            active=True,
            book=self._state.book,
            book_id=self._state.book_id,
            chapter=self._state.chapter,
            verse_start=self._state.verse_start,
            verse_end=self._state.verse_end,
            current_verse=self._state.current_verse,
            version=event.new_version,
            verse_texts=self._state.verse_texts,
        )
        self._version = event.new_version
        self._reload_verse_texts()
        self._present_verse(self._state.current_verse)
        logger.info(
            "ReadingFollowService: version changed via event to %s.",
            event.new_version,
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
            verse_texts=verse_texts,
        )

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
        self._state = FollowState(version=self._version)
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
        self._state = FollowState(
            active=True,
            book=self._state.book,
            book_id=self._state.book_id,
            chapter=self._state.chapter,
            verse_start=self._state.verse_start,
            verse_end=self._state.verse_end,
            current_verse=next_verse,
            version=self._state.version,
            verse_texts=self._state.verse_texts,
        )

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
        """Pré-carrega os textos de todos os versículos do intervalo."""
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
            self._state = FollowState(
                active=True,
                book=self._state.book,
                book_id=self._state.book_id,
                chapter=self._state.chapter,
                verse_start=self._state.verse_start,
                verse_end=self._state.verse_end,
                current_verse=self._state.current_verse,
                version=self._state.version,
                verse_texts=texts,
            )

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
