"""Exceções de domínio do projeto."""

from __future__ import annotations


class AILyricsError(Exception):
    """Base para todas as exceções do projeto."""


class ConfigError(AILyricsError):
    """Erro de configuração (YAML inválido, campo ausente, env var faltando, etc.)."""


class StateError(AILyricsError):
    """Erro de estado (navegação inválida, versículo fora de range, etc.)."""


class AudioError(AILyricsError):
    """Erro de captura de áudio (dispositivo indisponível, VAD falhou, etc.)."""


class STTError(AILyricsError):
    """Erro de transcrição (modelo não carrega, CUDA OOM, áudio inválido, etc.)."""


class DecisionError(AILyricsError):
    """Erro do motor de decisão (intent inválido, execução falhou, etc.)."""


class PipelineError(AILyricsError):
    """Erro de orquestração do pipeline (stage falhou, timeout, etc.).

    Atributos:
        stage_timing: StageTiming da execução que falhou (opcional,
            anexado por pipeline_stages para que o orquestrador possa
            registrar o timing mesmo em caso de erro).
    """

    def __init__(self, *args, stage_timing=None) -> None:
        super().__init__(*args)
        self.stage_timing = stage_timing
