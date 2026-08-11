"""VersionCommandDetector — Sprint 23.2.

Detector determinístico de comandos de mudança de versão bíblica por voz.

Responsabilidade:
    - Consumir SpeechTranscribed (transcrição final após pausa do VAD).
    - Detectar padrões como "muda pra NVI", "troca para Almeida", etc.
    - Validar a versão contra uma lista de versões conhecidas.
    - Publicar VersionChanged(source="voice") quando detectado.

Não usa LLM — é puramente determinístico com regex, para baixa latência.
A mudança automática pode ser desabilitada via flag _auto_enabled.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

from pipeline.bus import PipelineEventBus
from pipeline.events import SpeechTranscribed, VersionChanged
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
        """Inscreve no EventBus."""
        if self._subscribed:
            return
        self._bus.subscribe(SpeechTranscribed, self._on_speech_transcribed)
        self._subscribed = True
        logger.info("VersionCommandDetector started — subscribed to SpeechTranscribed.")

    def stop(self) -> None:
        """Desinscreve do EventBus."""
        if not self._subscribed:
            return
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

    # ------------------------------------------------------------------
    # Lógica interna
    # ------------------------------------------------------------------

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
