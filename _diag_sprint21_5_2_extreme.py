"""Sprint 21.5.2 — Cenário EXTREMO: fala contínua com incrementos mínimos.

Simula o pior caso: o pregador fala continuamente sem pausas,
e o Whisper adiciona 1 palavra por vez a cada 400ms.

Neste cenário:
- O debounce é cancelado a cada novo SpeechPartialUpdated
- O gatilho de crescimento pode não disparar se o incremento
  entre eventos for < min_growth_chars (20)
- O debounce nunca expira porque é sempre cancelado

Resultado esperado: se a fala for contínua o suficiente,
o growth eventualmente dispara. Mas se o _last_inferred_text
for setado por um debounce que dispara no meio, o growth
pode nunca atingir 20.
"""
from __future__ import annotations

import logging
import time
from typing import Any

_LOG_FILE = r"C:\Users\USER\Documents\AI Lyrics\_diag_sprint21_5_2_extreme_output.txt"
_fh = open(_LOG_FILE, "w", encoding="utf-8")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=_fh,
)
logger = logging.getLogger("diag")

from pipeline.bus import PipelineEventBus
from pipeline.events import SpeechPartial, SpeechPartialUpdated, SemanticInferenceCompleted
from pipeline.metadata import EventMetadata
from semantic.cache import SemanticCache
from semantic.context_engine import ContextEngine
from semantic.engine import SemanticEngine
from semantic.types import SemanticResult


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


def instrument(engine: SemanticEngine) -> None:
    original = engine._schedule_inference
    def patched(text: str, meta: EventMetadata) -> None:
        stripped = text.strip()
        with engine._lock:
            now = time.monotonic()
            if engine._last_inference_monotonic == 0.0:
                elapsed_str = "inf"
            else:
                elapsed_str = f"{(now - engine._last_inference_monotonic)*1000:.0f}ms"
            growth = engine._count_growth_chars(stripped)
            append = engine._count_append_words(stripped)
            rate_ok = (engine._last_inference_monotonic == 0.0 or
                       (now - engine._last_inference_monotonic)*1000 >= engine._min_interval_ms)
            growth_ok = growth >= engine._min_growth_chars
            append_ok = append >= engine._min_append_words
            debounce_active = engine._debounce_timer is not None
        from semantic.engine import _MIN_TEXT_LENGTH
        if len(stripped) < _MIN_TEXT_LENGTH:
            logger.info("  [SKIP] texto curto len=%d | text=%r", len(stripped), stripped[:60])
            original(text, meta)
            return
        if rate_ok and growth_ok and append_ok:
            logger.info("  [GROWTH DISPARA] growth=%d append=%d elapsed=%s | %r",
                        growth, append, elapsed_str, stripped[:60])
        else:
            motivos = []
            if not rate_ok: motivos.append(f"rate({elapsed_str}<1000ms)")
            if not growth_ok: motivos.append(f"growth({growth}<20)")
            if not append_ok: motivos.append(f"append({append}<3)")
            logger.info("  [NÃO DISPARA] %s | growth=%d append=%d elapsed=%s debounce=%s | %r",
                        ", ".join(motivos), growth, append, elapsed_str,
                        debounce_active, stripped[:60])
        original(text, meta)
    engine._schedule_inference = patched


def simular_continuo(bus: PipelineEventBus, palavras: list[str], session_id: str,
                     intervalo_ms: int = 400, nome: str = "") -> None:
    """Simula fala contínua: 1 palavra por vez, sem pausas."""
    logger.info("\n" + "#" * 70)
    logger.info("# FALA CONTÍNUA: %s", nome)
    logger.info("# %d palavras, intervalo=%dms (sem pausas)", len(palavras), intervalo_ms)
    logger.info("#" * 70)

    # Construir incrementos: cada incremento adiciona 1 palavra.
    incrementos = []
    acumulado = ""
    for p in palavras:
        acumulado = (acumulado + " " + p).strip()
        incrementos.append(acumulado)

    # Primeiro evento: SpeechPartial.
    meta = EventMetadata.for_initial(session_id=session_id, origin="StreamingSTTService")
    corr = meta.correlation_id
    caus = meta.event_id
    logger.info("  >> [%d] SpeechPartial: %r", 0, incrementos[0])
    bus.publish(SpeechPartial(meta=meta, text=incrementos[0], language="pt",
                              confidence=0.85, latency_ms=500, audio_duration_ms=6000))

    # Subsequentes: SpeechPartialUpdated a cada intervalo_ms.
    for i, texto in enumerate(incrementos[1:], 1):
        time.sleep(intervalo_ms / 1000.0)
        meta = EventMetadata.for_next(
            previous=EventMetadata(event_id=caus, correlation_id=corr,
                                   causation_id=None, session_id=session_id,
                                   timestamp=time.time(), origin="StreamingSTTService"),
            origin="StreamingSTTService")
        caus = meta.event_id
        logger.info("  >> [%d] SpeechPartialUpdated: %r", i, texto[:60])
        bus.publish(SpeechPartialUpdated(meta=meta, text=texto,
                                         appended_text=palavras[i], language="pt",
                                         confidence=0.85, latency_ms=500, audio_duration_ms=6000))

    # Aguardar debounce final.
    logger.info("  >> Fala terminou. Aguardando 1.5s para debounce...")
    time.sleep(1.5)


def main() -> None:
    logger.info("=" * 70)
    logger.info("Sprint 21.5.2 — Cenário EXTREMO: Fala Contínua")
    logger.info("=" * 70)

    bus = PipelineEventBus()
    provider = RecordingProvider()
    cache = SemanticCache()
    ctx_engine = ContextEngine(history_fn=bus.history, window_seconds=45, max_recent_chars=500)
    engine = SemanticEngine(bus=bus, provider=provider, context_engine=ctx_engine,
                            cache=cache, session_id="diag", debounce_ms=800,
                            timeout_ms=5000, enabled=True,
                            min_growth_chars=20, min_append_words=3, min_interval_ms=1000)
    instrument(engine)
    telemetry: list[SemanticInferenceCompleted] = []
    bus.subscribe(SemanticInferenceCompleted, lambda e: telemetry.append(e))
    engine.start()

    # Cenário 1: Frase curta palavra por palavra.
    simular_continuo(bus, "O Senhor é meu pastor e nada me faltará".split(),
                     "diag", 400, "O Senhor é meu pastor e nada me faltará")

    # Reset entre cenários.
    with engine._lock:
        if engine._debounce_timer:
            engine._debounce_timer.cancel()
            engine._debounce_timer = None
        engine._pending_text = ""
        engine._pending_meta = None
        engine._last_inferred_text = ""
        engine._last_inference_monotonic = 0.0
    time.sleep(1.2)

    # Cenário 2: Fala longa e contínua (sem pausas) — simula pregador
    # que fala por 30+ segundos sem parar, com o Whisper adicionando
    # 1 palavra por vez a cada 400ms.
    simular_continuo(bus,
                     "Irmãos hoje queremos meditar na palavra que diz o Senhor é meu pastor e nada me faltará ele me faz repousar em verdes pastos".split(),
                     "diag", 400, "Pregação longa e contínua (20 palavras)")

    # Reset.
    with engine._lock:
        if engine._debounce_timer:
            engine._debounce_timer.cancel()
            engine._debounce_timer = None
        engine._pending_text = ""
        engine._pending_meta = None
        engine._last_inferred_text = ""
        engine._last_inference_monotonic = 0.0
    time.sleep(1.2)

    # Cenário 3: Incrementos de 2 palavras por vez (mais realista para
    # janela de 6s do Whisper).
    palavras = "Porque Deus amou o mundo de tal maneira que deu o seu filho unigênito".split()
    incrementos_2 = []
    for i in range(0, len(palavras), 2):
        incrementos_2.append(" ".join(palavras[:i+2]))

    logger.info("\n" + "#" * 70)
    logger.info("# INCREMENTOS DE 2 PALAVRAS: Porque Deus amou o mundo...")
    logger.info("#" * 70)
    meta = EventMetadata.for_initial(session_id="diag", origin="StreamingSTTService")
    corr = meta.correlation_id
    caus = meta.event_id
    logger.info("  >> [0] SpeechPartial: %r", incrementos_2[0])
    bus.publish(SpeechPartial(meta=meta, text=incrementos_2[0], language="pt",
                              confidence=0.85, latency_ms=500, audio_duration_ms=6000))
    for i, texto in enumerate(incrementos_2[1:], 1):
        time.sleep(0.4)
        meta = EventMetadata.for_next(
            previous=EventMetadata(event_id=caus, correlation_id=corr,
                                   causation_id=None, session_id="diag",
                                   timestamp=time.time(), origin="StreamingSTTService"),
            origin="StreamingSTTService")
        caus = meta.event_id
        logger.info("  >> [%d] SpeechPartialUpdated: %r", i, texto[:60])
        bus.publish(SpeechPartialUpdated(meta=meta, text=texto,
                                         appended_text="2palavras", language="pt",
                                         confidence=0.85, latency_ms=500, audio_duration_ms=6000))
    logger.info("  >> Aguardando 1.5s...")
    time.sleep(1.5)

    # Relatório.
    logger.info("\n\n" + "=" * 70)
    logger.info("RELATÓRIO FINAL")
    logger.info("=" * 70)
    logger.info("Chamadas ao LLM: %d", len(provider.calls))
    for c in provider.calls:
        logger.info("  %r", c[:80])
    logger.info("Telemetria: %d eventos", len(telemetry))
    stats = engine.stats()
    logger.info("Stats: growth=%d debounce=%d calls=%d",
                stats["total_growth_triggers"], stats["total_debounce_triggers"],
                stats["total_calls"])

    engine.stop()
    _fh.flush()
    _fh.close()
    print(f"Concluído. Saída em: {_LOG_FILE}")


if __name__ == "__main__":
    main()
