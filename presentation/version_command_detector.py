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
import time
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
from pipeline.speech_reference_grammar import (
    CHAPTER_MARKERS,
    VERSE_MARKERS,
    number_token,
)
from parser.normalizer import Normalizer

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

# Comandos de voz são curtos. Spans longos de committed text são
# leitura/pregação, não comandos — sem este guarda, "vamos voltar a
# velhas práticas" disparava "back" (partial_ratio casava "volta"
# como substring de "voltar").
_NAVIGATION_MAX_WORDS = 5
_NAVIGATION_MAX_FILLER = 2

# Dedup: o LocalAgreement-2 re-emite spans sobrepostos — o mesmo
# comando pode chegar em múltiplos SpeechCommittedWords consecutivos.
_NAV_DEDUP_S = 3.0
_NAV_MIN_INTERVAL_S = 2.0

# Sprint 31 — formas faladas reais: "voltar um", "volta versículo",
# "próximo". Comandos de 1 palavra só disparam quando são a utterance
# inteira (ver _on_committed_words).
_NAVIGATION_COMMANDS_BACK: list[str] = [
    "verso anterior",
    "versículo anterior",
    "voltar um versículo",
    "volta um versículo",
    "voltar versículo",
    "volta versículo",
    "voltar um",
    "volta um",
    "volta",
    "voltar",
    "anterior",
]

_NAVIGATION_COMMANDS_FORWARD: list[str] = [
    "próximo verso",
    "próximo versículo",
    "proximo verso",
    "proximo versículo",
    "avançar versículo",
    "próximo",
    "avança",
    "avançar",
    "pula",
    "pular",
    "seguinte",
]

# "capítulo N" / "versículo N" — mesmos marcadores/números do parser.
_SPEECH_NORM = Normalizer(protect_function_words=True)


def _normalize_text(text: str) -> str:
    """Normaliza texto para comparação: lowercase, sem acentos, sem pontuação."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


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
        self._last_nav_sig: tuple[str, int, str] | None = None
        self._last_nav_ts: float = 0.0
        self._last_nav_cmd: tuple[str, float] | None = None

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

        # Sprint 31 — avaliar a UTTERANCE (full_committed_text), não o
        # chunk. Chunks do LocalAgreement têm 1–3 palavras e cortam frases
        # em qualquer ponto: "...e o | próximo versículo | diz..." virava
        # comando no meio da leitura. Uma utterance nova começa após pausa
        # (novo correlation_id), então um comando dito isoladamente é a
        # utterance inteira; no meio de uma frase, nunca dispara.
        text_to_check = event.full_committed_text or event.committed_text
        if not text_to_check:
            return

        result = self._detect_navigation_command(text_to_check)
        if result is None:
            return

        command, target_value, confidence = result

        # Dedup: spans committed sobrepostos re-emitem as mesmas
        # palavras — sem isto, um único "volta" disparava vários
        # NavigationCommandDetected e a apresentação recuava N versos.
        now = time.monotonic()
        sig = (command, target_value, _normalize_text(text_to_check)[:80])
        if (self._last_nav_sig == sig
                and now - self._last_nav_ts < _NAV_DEDUP_S):
            return
        last_cmd, last_ts = self._last_nav_cmd or ("", 0.0)
        if command == last_cmd and now - last_ts < _NAV_MIN_INTERVAL_S:
            return
        self._last_nav_sig = sig
        self._last_nav_ts = now
        self._last_nav_cmd = (command, now)

        self._publish_navigation_command(
            event, command, target_value, text_to_check, confidence,
        )
        logger.info(
            "VersionCommandDetector: navigation command detected "
            "(command=%s, target=%d, confidence=%.2f, text=%r...)",
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
        tokens = norm.split()

        # Verificar "capítulo N" e "versículo N" primeiro (regex),
        # pois "versículo" pode confundir com "verso anterior".
        # Só aceitar se o texto for curto (comando, não leitura).
        if len(tokens) <= 5:
            # Números por extenso também ("versículo dezessete").
            ntoks = _SPEECH_NORM.normalize(text).split()
            for i, tok in enumerate(ntoks[:-1]):
                n = number_token(ntoks[i + 1])
                if not n:
                    continue
                if tok in CHAPTER_MARKERS:
                    return ("goto_chapter", n, _NAVIGATION_THRESHOLD_GOTO)
                if tok in VERSE_MARKERS and tok != "v":
                    return ("goto_verse", n, _NAVIGATION_THRESHOLD_GOTO)

        # Comandos de navegação são curtos — spans longos são
        # leitura/pregação, não comandos de voz.
        if len(tokens) > _NAVIGATION_MAX_WORDS:
            return None

        # Verificar comandos de retrocesso.
        for canonical in _NAVIGATION_COMMANDS_BACK:
            if self._matches_command(tokens, canonical):
                return ("back", 0, _NAVIGATION_THRESHOLD)

        # Verificar comandos de avanço.
        for canonical in _NAVIGATION_COMMANDS_FORWARD:
            if self._matches_command(tokens, canonical):
                return ("forward", 0, _NAVIGATION_THRESHOLD)

        return None

    @staticmethod
    def _matches_command(tokens: list[str], canonical: str) -> bool:
        """Verifica se o comando aparece como frase de tokens contíguos.

        Match por tokens inteiros (nunca substring) — "volta" não casa
        com "voltar"/"voltamos"/"voltou". Comandos de 1 palavra só
        disparam quando são o texto inteiro do span committed, pois
        palavras soltas ("volta", "pula") aparecem naturalmente na
        pregação ("vamos voltar", "pula essa parte").
        """
        cmd_tokens = _normalize_text(canonical).split()
        n = len(cmd_tokens)
        if n == 1:
            return tokens == cmd_tokens
        if len(tokens) < n or len(tokens) > n + _NAVIGATION_MAX_FILLER:
            return False
        for i in range(len(tokens) - n + 1):
            if tokens[i:i + n] == cmd_tokens:
                return True
        return False

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
