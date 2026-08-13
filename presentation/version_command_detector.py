"""VersionCommandDetector — Sprint 23.2 + Sprint 28 (Fase 8).

Detector determinístico de comandos de voz.

Responsabilidade:
    - Sprint 23.2: Consumir SpeechTranscribed para mudança de versão.
    - Sprint 28 (Fase 8): Consumir SpeechCommittedWords para comandos de
      navegação ("verso anterior", "volta", "pula", "próximo verso",
      "capítulo N", "versículo N").
    - Detectar padrões de mudança de versão ("muda pra NVI", etc.).
    - Validar a versão contra uma lista de versões conhecidas.
    - Publicar VersionChanged(source="voice") para mudança de versão.
    - Publicar NavigationCommandDetected para comandos de navegação.

Não usa LLM — é puramente determinístico com regex + fuzzy match,
para baixa latência. A mudança automática pode ser desabilitada via
flag _auto_enabled.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Protocol

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    NavigationCommandDetected,
    SpeechCommittedWords,
    SpeechTranscribed,
    VersionChanged,
)
from pipeline.metadata import EventMetadata

logger = logging.getLogger(__name__)

__all__ = ["VersionCommandDetector", "HolyricsProtocol"]


# Padrões de comando de mudança de versão.
# Captura o nome/abreviação da versão após o comando.
_VERSION_COMMAND_PATTERNS = [
    re.compile(
        r"(?:muda|mudar|troca|trocar|coloca|colocar|altera|alterar|p[oô]e|p[oô]r|troque)\s+(?:pra|para|na|para a|para o)\s+(?:vers[aã]o\s+)?([A-Za-z]{2,10})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:muda|mudar|troca|trocar|altera|alterar)\s+(?:a\s+)?vers[aã]o\s+(?:pra|para|para a|para o)?\s*([A-Za-z]{2,10})",
        re.IGNORECASE,
    ),
    re.compile(
        r"vers[aã]o\s+([A-Za-z]{2,10})",
        re.IGNORECASE,
    ),
]

# Versões bíblicas conhecidas/suportadas pelo Holyrics.
# Lista estática para validação rápida. Pode ser estendida dinamicamente
# via HolyricsClient.get_bible_versions().
_KNOWN_VERSIONS: frozenset[str] = frozenset({
    "ACF", "NVI", "ARA", "ARC", "NAA", "JFAA", "JFAA",
    "ACF", "ACF", "NVT", "NTLH", "NTLH", "KJA", "OL",
    "BBE", "WEB", "RVR", "RVR60", "RVR95", "NVI",
})

# Mapeamento de nomes comuns para abreviações canônicas.
_VERSION_ALIASES: dict[str, str] = {
    "almeida": "ACF",
    "almeida_corrigida": "ACF",
    "almeida_corrigida_fiel": "ACF",
    "nvi": "NVI",
    "nova_versao_internacional": "NVI",
    "ara": "ARA",
    "almeida_revista_atualizada": "ARA",
    "arc": "ARC",
    "almeida_revista_corrigida": "ARC",
    "naa": "NAA",
    "nova_almeida_atualizada": "NAA",
    "jfaa": "JFAA",
    "joao_ferreira_almeida_atualizada": "JFAA",
    "nvt": "NVT",
    "nova_versao_transformadora": "NVT",
    "ntlh": "NTLH",
    "nova_traducao_na_linguagem_de_hoje": "NTLH",
}


# Sprint 28 (Fase 8) — Comandos de navegação por voz (§15.4).
# Lista canônica de comandos e suas variações.
# Threshold alto (0.90) para evitar falsos positivos durante leitura.
_NAVIGATION_THRESHOLD = 0.90
_NAVIGATION_THRESHOLD_GOTO = 0.85  # "capítulo N" / "versículo N"

_NAVIGATION_COMMANDS_BACK: list[str] = [
    "verso anterior",
    "versículo anterior",
    "volta",
    "voltar",
]

_NAVIGATION_COMMANDS_FORWARD: list[str] = [
    "próximo verso",
    "próximo versículo",
    "proximo verso",
    "proximo versículo",
    "pula",
    "pular",
]

# Padrões regex para "capítulo N" e "versículo N".
_CHAPTER_PATTERN = re.compile(
    r"cap[ií]tulo\s+(\d+)", re.IGNORECASE,
)
_VERSE_PATTERN = re.compile(
    r"vers[ií]culo\s+(\d+)", re.IGNORECASE,
)


def _normalize_text(text: str) -> str:
    """Normaliza texto para comparação: lowercase, sem acentos, sem pontuação."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fuzzy_similarity(text1: str, text2: str) -> float:
    """Calcula similaridade fuzzy entre dois textos [0.0, 1.0]."""
    try:
        from rapidfuzz import fuzz
        score = fuzz.partial_ratio(text1, text2)
        return score / 100.0
    except ImportError:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, text1, text2).ratio()


class HolyricsProtocol(Protocol):
    """Interface mínima do HolyricsClient para validar versões."""

    def get_bible_versions(self) -> Any: ...


class VersionCommandDetector:
    """Detector de comandos de mudança de versão por voz.

    Args:
        bus: PipelineEventBus para assinar e publicar eventos.
        session_id: ID da sessão atual.
        holyrics: HolyricsClient (opcional) para validar versões dinamicamente.
        auto_enabled: se True, publica VersionChanged ao detectar comando.
            Se False, apenas loga (operador desabilitou mudança automática).
        current_version: versão ativa atual (para incluir no evento).
    """

    def __init__(
        self,
        bus: PipelineEventBus,
        session_id: str,
        holyrics: HolyricsProtocol | None = None,
        auto_enabled: bool = True,
        current_version: str = "ACF",
    ) -> None:
        self._bus = bus
        self._session_id = session_id
        self._holyrics = holyrics
        self._auto_enabled = auto_enabled
        self._current_version = current_version
        self._subscribed = False
        self._available_versions: frozenset[str] | None = None

        logger.info(
            "VersionCommandDetector initialized (auto_enabled=%s, version=%s).",
            auto_enabled, current_version,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inscreve no EventBus.

        Sprint 28 (Fase 8) — adiciona SpeechCommittedWords para comandos
        de navegação. SpeechTranscribed mantido para mudança de versão.
        """
        if self._subscribed:
            return
        self._bus.subscribe(SpeechTranscribed, self._on_speech_transcribed)
        self._bus.subscribe(SpeechCommittedWords, self._on_committed_words)
        self._subscribed = True
        logger.info(
            "VersionCommandDetector started — subscribed to "
            "SpeechTranscribed + SpeechCommittedWords."
        )

    def stop(self) -> None:
        """Desinscreve do EventBus."""
        if not self._subscribed:
            return
        self._bus.unsubscribe(SpeechTranscribed, self._on_speech_transcribed)
        self._bus.unsubscribe(SpeechCommittedWords, self._on_committed_words)
        self._subscribed = False
        logger.info("VersionCommandDetector stopped.")

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def set_auto_enabled(self, enabled: bool) -> None:
        """Habilita/desabilita a mudança automática de versão por voz."""
        self._auto_enabled = enabled
        logger.info(
            "VersionCommandDetector: auto_enabled=%s.", enabled,
        )

    def set_current_version(self, version: str) -> None:
        """Atualiza a versão ativa atual."""
        self._current_version = version

    # ------------------------------------------------------------------
    # Handler do EventBus
    # ------------------------------------------------------------------

    def _on_speech_transcribed(self, event: SpeechTranscribed) -> None:
        """Detecta comandos de mudança de versão na transcrição."""
        if not self._auto_enabled:
            return

        if not event.text or not event.text.strip():
            return

        version = self._detect_version_command(event.text)
        if version is None:
            return

        if version == self._current_version:
            logger.debug(
                "VersionCommandDetector: versão %s já ativa, ignorando.",
                version,
            )
            return

        if not self._validate_version(version):
            logger.warning(
                "VersionCommandDetector: versão %s não reconhecida, ignorando.",
                version,
            )
            return

        old = self._current_version
        self._current_version = version
        self._publish_version_changed(old, version, source="voice")
        logger.info(
            "VersionCommandDetector: version changed %s → %s (voice).",
            old, version,
        )

    def _on_committed_words(self, event: SpeechCommittedWords) -> None:
        """Detecta comandos de navegação em SpeechCommittedWords (Sprint 28 — Fase 8).

        Comandos detectados (§15.4):
          - "verso anterior" / "versículo anterior" / "volta" / "voltar" → back
          - "próximo verso" / "próximo versículo" / "pula" / "pular" → forward
          - "capítulo N" → goto_chapter
          - "versículo N" → goto_verse

        Threshold alto (0.90) para evitar falsos positivos durante leitura.
        """
        if not self._auto_enabled:
            return

        if not event.full_committed_text:
            return

        result = self._detect_navigation_command(event.full_committed_text)
        if result is None:
            return

        command, target_value, confidence = result
        self._publish_navigation_command(
            event, command, target_value, event.full_committed_text, confidence,
        )
        logger.info(
            "VersionCommandDetector: navigation command detected "
            "(command=%s, target=%d, confidence=%.2f, text=%q...)",
            command, target_value, confidence, event.full_committed_text[:50],
        )

    # ------------------------------------------------------------------
    # Lógica interna
    # ------------------------------------------------------------------

    def _detect_navigation_command(
        self, text: str,
    ) -> tuple[str, int, float] | None:
        """Detecta comando de navegação no texto.

        Returns:
            (command, target_value, confidence) ou None.
            command: "back" | "forward" | "goto_chapter" | "goto_verse"
            target_value: N para goto_chapter/goto_verse, 0 para back/forward
            confidence: score do fuzzy match
        """
        norm = _normalize_text(text)

        # Verificar "capítulo N" e "versículo N" primeiro (regex),
        # pois "versículo" pode confundir com "verso anterior".
        # Só aceitar se o texto for curto (comando, não leitura).
        if len(norm.split()) <= 5:
            match = _CHAPTER_PATTERN.search(text)
            if match:
                n = int(match.group(1))
                return ("goto_chapter", n, _NAVIGATION_THRESHOLD_GOTO)

            match = _VERSE_PATTERN.search(text)
            if match:
                n = int(match.group(1))
                return ("goto_verse", n, _NAVIGATION_THRESHOLD_GOTO)

        # Verificar comandos de retrocesso.
        for canonical in _NAVIGATION_COMMANDS_BACK:
            score = _fuzzy_similarity(norm, _normalize_text(canonical))
            if score >= _NAVIGATION_THRESHOLD:
                return ("back", 0, score)

        # Verificar comandos de avanço.
        for canonical in _NAVIGATION_COMMANDS_FORWARD:
            score = _fuzzy_similarity(norm, _normalize_text(canonical))
            if score >= _NAVIGATION_THRESHOLD:
                return ("forward", 0, score)

        return None

    def _publish_navigation_command(
        self,
        source_event: SpeechCommittedWords,
        command: str,
        target_value: int,
        raw_text: str,
        confidence: float,
    ) -> None:
        """Publica NavigationCommandDetected no EventBus."""
        meta = EventMetadata.for_next(
            previous=source_event.meta,
            origin="VersionCommandDetector",
        )
        self._bus.publish(NavigationCommandDetected(
            meta=meta,
            command=command,
            target_value=target_value,
            raw_text=raw_text,
            confidence=confidence,
        ))

    def _detect_version_command(self, text: str) -> str | None:
        """Extrai a versão do texto usando os padrões de comando."""
        for pattern in _VERSION_COMMAND_PATTERNS:
            match = pattern.search(text)
            if match:
                raw = match.group(1).strip()
                version = self._normalize_version(raw)
                if version:
                    return version
        return None

    @staticmethod
    def _normalize_version(raw: str) -> str | None:
        """Normaliza o nome da versão para a abreviação canônica."""
        cleaned = raw.strip().upper()
        cleaned_no_accent = cleaned.replace("Á", "A").replace("Ã", "A")

        if cleaned_no_accent in _KNOWN_VERSIONS:
            return cleaned_no_accent

        lower = raw.strip().lower().replace(" ", "_")
        lower_no_accent = lower.replace("á", "a").replace("ã", "a")
        if lower_no_accent in _VERSION_ALIASES:
            return _VERSION_ALIASES[lower_no_accent]
        if lower in _VERSION_ALIASES:
            return _VERSION_ALIASES[lower]

        if len(cleaned_no_accent) >= 2 and cleaned_no_accent in _KNOWN_VERSIONS:
            return cleaned_no_accent

        return None

    def _validate_version(self, version: str) -> bool:
        """Valida a versão contra versões conhecidas e/ou Holyrics."""
        if version in _KNOWN_VERSIONS:
            return True

        if self._holyrics is not None and self._available_versions is None:
            try:
                result = self._holyrics.get_bible_versions()
                if isinstance(result, list):
                    self._available_versions = frozenset(
                        str(v).upper() for v in result
                    )
                elif hasattr(result, "versions"):
                    self._available_versions = frozenset(
                        str(v).upper() for v in result.versions
                    )
            except Exception:
                logger.exception("VersionCommandDetector: erro ao buscar versões do Holyrics.")
                self._available_versions = _KNOWN_VERSIONS

        if self._available_versions is not None:
            return version in self._available_versions

        return False

    def _publish_version_changed(
        self, old_version: str, new_version: str, source: str,
    ) -> None:
        meta = EventMetadata.for_session_event(
            session_id=self._session_id,
            origin="VersionCommandDetector",
        )
        self._bus.publish(VersionChanged(
            meta=meta,
            old_version=old_version,
            new_version=new_version,
            source=source,
        ))
