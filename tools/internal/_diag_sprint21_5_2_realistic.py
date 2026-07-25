"""Sprint 21.5.2 — Cenário REALISTA de streaming incremental.

Simula como o StreamingSTTService realmente publica eventos:
- SpeechPartial com texto parcial inicial
- Múltiplos SpeechPartialUpdated conforme a janela deslizante
  adiciona palavras a cada 400ms

O ponto-chave: a cada SpeechPartialUpdated, o SemanticEngine
CANCELA o debounce anterior e reavalia. Se o crescimento entre
eventos for < min_growth_chars (20) E < min_append_words (3),
o gatilho de crescimento não dispara E o debounce é cancelado
antes de expirar.

Resultado: durante fala contínua, o debounce NUNCA expira e
o gatilho de crescimento pode nunca disparar se cada incremento
for pequeno.
"""
from __future__ import annotations

import logging
import sys
import time
from typing import Any

_LOG_FILE = r"C:\Users\USER\Documents\AI Lyrics\_diag_sprint21_5_2_realistic_output.txt"
_fh = open(_LOG_FILE, "w", encoding="utf-8")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=_fh,
)
logger = logging.getLogger("diag")

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    SpeechPartial,
    SpeechPartialUpdated,
    SemanticInferenceCompleted,
)
from pipeline.metadata import EventMetadata
from semantic.cache import SemanticCache
from semantic.context_engine import ContextEngine
from semantic.engine import SemanticEngine
from semantic.types import SemanticResult


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._available = True

    @property
    def name(self) -> str:
        return "RecordingProvider"

    @property
    def model_name(self) -> str:
        return "diag-stub"

    def is_available(self) -> bool:
        return self._available

    def infer(self, context: Any, timeout_ms: int = 5000) -> SemanticResult:
        self.calls.append(context.current_text)
        logger.info("    >>> LLM CHAMADO com texto=%r", context.current_text[:80])
        return SemanticResult(
            intent="none",
            candidates=[],
            inference_ms=10,
            provider=self.name,
            model=self.model_name,
        )

    def warmup(self) -> None:
        pass


def instrument_engine(engine: SemanticEngine) -> None:
    """Instrumenta _schedule_inference para registrar decisão."""
    original_schedule = engine._schedule_inference

    def patched_schedule(text: str, meta: EventMetadata) -> None:
        stripped = text.strip()
        with engine._lock:
            now = time.monotonic()
            if engine._last_inference_monotonic == 0.0:
                elapsed_ms = float("inf")
                elapsed_str = "inf (primeira)"
            else:
                elapsed_ms = (now - engine._last_inference_monotonic) * 1000.0
                elapsed_str = f"{elapsed_ms:.0f}ms"

            growth_chars = engine._count_growth_chars(stripped)
            append_words = engine._count_append_words(stripped)
            rate_ok = elapsed_ms >= engine._min_interval_ms
            growth_ok = growth_chars >= engine._min_growth_chars
            append_ok = append_words >= engine._min_append_words
            debounce_active = engine._debounce_timer is not None

        from semantic.engine import _MIN_TEXT_LENGTH
        if len(stripped) < _MIN_TEXT_LENGTH:
            logger.info(
                "  [DECISÃO] SKIP: texto curto (len=%d < %d) | text=%r",
                len(stripped), _MIN_TEXT_LENGTH, stripped[:60],
            )
            original_schedule(text, meta)
            return

        if rate_ok and growth_ok and append_ok:
            logger.info(
                "  [DECISÃO] GROWTH TRIGGER dispara | "
                "growth=%d(>=20) append=%d(>=3) elapsed=%s(>=1000ms) | text=%r",
                growth_chars, append_words, elapsed_str, stripped[:60],
            )
        else:
            motivos = []
            if not rate_ok:
                motivos.append(f"rate_limit({elapsed_str}<1000ms)")
            if not growth_ok:
                motivos.append(f"growth({growth_chars}<20)")
            if not append_ok:
                motivos.append(f"append({append_words}<3)")
            logger.info(
                "  [DECISÃO] NÃO dispara growth | motivos=[%s] | "
                "growth=%d append=%d elapsed=%s debounce_active=%s | text=%r",
                ", ".join(motivos), growth_chars, append_words,
                elapsed_str, debounce_active, stripped[:60],
            )
            logger.info(
                "    → Debounce %dms agendado (será cancelado pelo próximo evento "
                "se a fala continuar)",
                engine._debounce_ms,
            )
        original_schedule(text, meta)

    engine._schedule_inference = patched_schedule


# ---------------------------------------------------------------------
# Cenários de streaming incremental
# ---------------------------------------------------------------------

def simular_streaming_incremental(
    bus: PipelineEventBus,
    incrementos: list[str],
    session_id: str,
    intervalo_ms: int = 400,
) -> None:
    """Simula o StreamingSTTService publicando incrementos.

    Args:
        incrementos: lista de textos parciais crescentes.
            Ex: ["O Senhor", "O Senhor é meu", "O Senhor é meu pastor."]
        intervalo_ms: intervalo entre eventos (default 400ms = janela real).
    """
    if not incrementos:
        return

    # Primeiro evento: SpeechPartial.
    meta = EventMetadata.for_initial(
        session_id=session_id,
        origin="StreamingSTTService",
    )
    correlation_id = meta.correlation_id
    causation_id = meta.event_id

    logger.info("  >> SpeechPartial: %r", incrementos[0])
    event = SpeechPartial(
        meta=meta,
        text=incrementos[0],
        language="pt",
        confidence=0.85,
        latency_ms=500,
        audio_duration_ms=6000,
        is_stable=False,
    )
    bus.publish(event)

    # Eventos subsequentes: SpeechPartialUpdated.
    for i, texto in enumerate(incrementos[1:], 1):
        time.sleep(intervalo_ms / 1000.0)
        appended = texto[len(incrementos[i - 1]):].strip()
        meta = EventMetadata.for_next(
            previous=EventMetadata(
                event_id=causation_id,
                correlation_id=correlation_id,
                causation_id=None,
                session_id=session_id,
                timestamp=time.time(),
                origin="StreamingSTTService",
            ),
            origin="StreamingSTTService",
        )
        causation_id = meta.event_id
        logger.info("  >> SpeechPartialUpdated: full=%r appended=%r", texto[:60], appended)
        event = SpeechPartialUpdated(
            meta=meta,
            text=texto,
            appended_text=appended,
            language="pt",
            confidence=0.85,
            latency_ms=500,
            audio_duration_ms=6000,
            is_stable=False,
        )
        bus.publish(event)


def main() -> None:
    logger.info("=" * 70)
    logger.info("Sprint 21.5.2 — Cenário REALISTA de Streaming Incremental")
    logger.info("=" * 70)

    bus = PipelineEventBus()
    provider = RecordingProvider()
    cache = SemanticCache(ttl_seconds=300.0, max_entries=256)
    context_engine = ContextEngine(
        history_fn=bus.history,
        window_seconds=45,
        max_recent_chars=500,
    )

    engine = SemanticEngine(
        bus=bus,
        provider=provider,
        context_engine=context_engine,
        cache=cache,
        session_id="diag-session",
        debounce_ms=800,  # valor real do config.yaml
        timeout_ms=5000,
        enabled=True,
        min_growth_chars=20,
        min_append_words=3,
        min_interval_ms=1000,
    )

    instrument_engine(engine)

    telemetry: list[SemanticInferenceCompleted] = []
    bus.subscribe(SemanticInferenceCompleted, lambda e: telemetry.append(e))
    engine.start()

    # Cenários: cada frase simulada como incrementos de ~2-3 palavras
    # (como o Whisper realmente transcreve com janela deslizante de 6s).
    cenarios = [
        ("O Senhor é meu pastor.", [
            "O Senhor",
            "O Senhor é meu",
            "O Senhor é meu pastor.",
        ]),
        ("Porque Deus amou o mundo.", [
            "Porque Deus",
            "Porque Deus amou o",
            "Porque Deus amou o mundo.",
        ]),
        ("Tudo posso naquele que me fortalece.", [
            "Tudo posso",
            "Tudo posso naquele que",
            "Tudo posso naquele que me fortalece.",
        ]),
        ("Ainda que eu ande pelo vale da sombra da morte.", [
            "Ainda que eu",
            "Ainda que eu ande pelo",
            "Ainda que eu ande pelo vale da",
            "Ainda que eu ande pelo vale da sombra da morte.",
        ]),
        ("A armadura de Deus.", [
            "A armadura",
            "A armadura de Deus.",
        ]),
    ]

    for nome, incrementos in cenarios:
        logger.info("\n" + "#" * 70)
        logger.info("# FRASE: %r (%d incrementos)", nome, len(incrementos))
        logger.info("# Incrementos: %s", incrementos)
        logger.info("#" * 70)

        # Resetar estado do engine entre frases (como reset_flow do STT).
        with engine._lock:
            if engine._debounce_timer is not None:
                engine._debounce_timer.cancel()
                engine._debounce_timer = None
            engine._pending_text = ""
            engine._pending_meta = None
            engine._last_inferred_text = ""
            engine._last_inference_monotonic = 0.0

        simular_streaming_incremental(bus, incrementos, "diag-session", intervalo_ms=400)

        # Aguardar debounce + margem.
        logger.info("  >> Aguardando 1.5s para debounce expirar...")
        time.sleep(1.5)

    # Relatório.
    logger.info("\n\n" + "=" * 70)
    logger.info("RELATÓRIO FINAL")
    logger.info("=" * 70)
    logger.info("Chamadas ao LLM: %d", len(provider.calls))
    for c in provider.calls:
        logger.info("  %r", c[:80])
    logger.info("Telemetria: %d eventos", len(telemetry))
    for t in telemetry:
        logger.info(
            "  intent=%s cached=%s context=%r error=%r",
            t.intent, t.cached, t.context_text[:60], t.error,
        )
    stats = engine.stats()
    logger.info("Stats: growth=%d debounce=%d calls=%d",
                stats["total_growth_triggers"],
                stats["total_debounce_triggers"],
                stats["total_calls"])

    engine.stop()
    _fh.flush()
    _fh.close()
    print(f"Concluído. Saída em: {_LOG_FILE}")


if __name__ == "__main__":
    main()
