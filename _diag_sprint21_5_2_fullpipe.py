"""Sprint 21.5.2 — Teste DEFINITIVO: 3 subscribers reais no EventBus.

Simula a ordem real de inscrição do composition.py:
1. IncrementalParser (linha 617)
2. SermonMemoryEngine (linha 813)
3. SemanticEngine (linha 841)

Se o SermonMemoryEngine (ou qualquer handler entre eles) lançar
exceção, o SemanticEngine NUNCA recebe o evento, porque o EventBus
não tem try/except no loop de handlers.

Este teste verifica:
1. Se o SermonMemoryEngine lança exceção ao processar textos
   de referências implícitas
2. Se o SemanticEngine recebe eventos após o SermonMemoryEngine
3. Se a exceção (se houver) bloqueia a entrega ao SemanticEngine
"""
from __future__ import annotations

import logging
import time
from typing import Any

_LOG_FILE = r"C:\Users\USER\Documents\AI Lyrics\_diag_sprint21_5_2_fullpipe_output.txt"
_fh = open(_LOG_FILE, "w", encoding="utf-8")
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG para ver TODOS os logs
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=_fh,
)
logger = logging.getLogger("diag")

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    SpeechPartial,
    SpeechPartialUpdated,
    SemanticInferenceCompleted,
    ReferenceDetected,
)
from pipeline.metadata import EventMetadata
from semantic.cache import SemanticCache
from semantic.context_engine import ContextEngine
from semantic.engine import SemanticEngine
from semantic.types import SemanticResult
from sermon import SermonMemoryEngine


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
    @property
    def name(self) -> str: return "RecordingProvider"
    @property
    def model_name(self) -> str: return "diag-stub"
    def is_available(self) -> bool: return True
    def infer(self, context: Any, timeout_ms: int = 5000) -> SemanticResult:
        self.calls.append(context.current_text)
        logger.info("    >>> LLM CHAMADO: %r", context.current_text[:80])
        return SemanticResult(intent="none", candidates=[], inference_ms=10,
                              provider=self.name, model=self.model_name)
    def warmup(self) -> None: pass


def main() -> None:
    logger.info("=" * 70)
    logger.info("Sprint 21.5.2 — Teste DEFINITIVO: 3 Subscribers Reais")
    logger.info("=" * 70)

    bus = PipelineEventBus()

    # 1. IncrementalParser — não podemos instanciar facilmente sem books,
    #    mas podemos criar um handler proxy que simula seu comportamento.
    #    O IncrementalParser não lança exceções (apenas retorna early).
    def fake_incremental_parser_handler(event):
        logger.debug("  [IncrementalParser] recebeu %r (não faz nada)", event.text[:60])

    bus.subscribe(SpeechPartial, fake_incremental_parser_handler)
    bus.subscribe(SpeechPartialUpdated, fake_incremental_parser_handler)

    # 2. SermonMemoryEngine — REAL
    sermon_engine = SermonMemoryEngine(bus=bus, session_id="diag")
    sermon_engine.start()
    logger.info("SermonMemoryEngine iniciado.")

    # 3. SemanticEngine — REAL com provider de gravação
    provider = RecordingProvider()
    cache = SemanticCache()
    ctx_engine = ContextEngine(
        history_fn=bus.history,
        sermon_context_fn=sermon_engine.get_context,
    )
    engine = SemanticEngine(
        bus=bus, provider=provider, context_engine=ctx_engine,
        cache=cache, session_id="diag", debounce_ms=800,
        timeout_ms=5000, enabled=True,
        min_growth_chars=20, min_append_words=3, min_interval_ms=1000,
    )
    engine.start()
    logger.info("SemanticEngine iniciado.")

    telemetry: list[SemanticInferenceCompleted] = []
    bus.subscribe(SemanticInferenceCompleted, lambda e: telemetry.append(e))

    # Verificar ordem de inscrição.
    handlers_sp = bus._subscriptions.get(SpeechPartial, [])
    handlers_spu = bus._subscriptions.get(SpeechPartialUpdated, [])
    logger.info("Ordem de inscrição SpeechPartial: %d handlers", len(handlers_sp))
    logger.info("Ordem de inscrição SpeechPartialUpdated: %d handlers", len(handlers_spu))

    # Testar cada frase.
    FRASES = [
        "O Senhor é meu pastor.",
        "Porque Deus amou o mundo.",
        "Tudo posso naquele que me fortalece.",
        "Ainda que eu ande pelo vale da sombra da morte.",
        "A armadura de Deus.",
    ]

    for frase in FRASES:
        logger.info("\n" + "#" * 70)
        logger.info("# FRASE: %r", frase)
        logger.info("#" * 70)

        # Resetar estado do engine entre frases.
        with engine._lock:
            if engine._debounce_timer:
                engine._debounce_timer.cancel()
                engine._debounce_timer = None
            engine._pending_text = ""
            engine._pending_meta = None
            engine._last_inferred_text = ""
            engine._last_inference_monotonic = 0.0

        # Publicar SpeechPartial.
        meta = EventMetadata.for_initial(
            session_id="diag", origin="StreamingSTTService")
        event = SpeechPartial(
            meta=meta, text=frase, language="pt", confidence=0.85,
            latency_ms=500, audio_duration_ms=6000, is_stable=False)

        try:
            bus.publish(event)
            logger.info("  bus.publish() concluído SEM exceção")
        except Exception as e:
            logger.error("  bus.publish() lançou EXCEÇÃO: %s", e, exc_info=True)

        # Aguardar debounce.
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
        logger.info("  intent=%s cached=%s context=%r error=%r",
                    t.intent, t.cached, t.context_text[:60], t.error)
    stats = engine.stats()
    logger.info("Stats: growth=%d debounce=%d calls=%d",
                stats["total_growth_triggers"],
                stats["total_debounce_triggers"],
                stats["total_calls"])

    engine.stop()
    sermon_engine.stop()
    _fh.flush()
    _fh.close()
    print(f"Concluído. Saída em: {_LOG_FILE}")


if __name__ == "__main__":
    main()
