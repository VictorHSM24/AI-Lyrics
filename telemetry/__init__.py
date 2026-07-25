"""Sprint 21.9 — Infraestrutura de telemetria para observabilidade do pipeline.

Pacote desacoplado para registro de eventos em arquivos JSON Lines (.jsonl).
Não altera o comportamento do pipeline; apenas observa.

Uso típico (em qualquer componente do pipeline):

    from telemetry import telemetry

    telemetry.record("semantic_prompt", {
        "text": text,
        "prompt": prompt,
        "recent_text": recent_text,
    })

A escrita é assíncrona (fila consumida por thread dedicada) para não
bloquear o pipeline. Pode ser desabilitada via configuração.
"""
from __future__ import annotations

from .recorder import (
    TelemetryRecorder,
    get_recorder,
    configure_recorder,
    shutdown_recorder,
    record,
    is_enabled,
)

__all__ = [
    "TelemetryRecorder",
    "get_recorder",
    "configure_recorder",
    "shutdown_recorder",
    "record",
    "is_enabled",
]
