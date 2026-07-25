"""Sprint 21.5.2 — Auditoria da Política de Disparo do SemanticEngine.

Script INSTRUMENTADO de diagnóstico. Não modifica arquivos do projeto.
Simula o fluxo: SpeechPartial → SemanticEngine → política de disparo → LLM?

Para cada frase de referência implícita, registra:
  - SpeechPartial recebido
  - growth_chars calculado
  - append_words calculado
  - rate_limit (elapsed_ms)
  - cache_hit
  - debounce_active
  - growth_trigger
  - debounce_trigger
  - decisão final (LLM chamado? Se não, qual motivo impediu?)

Uso:
    python _diag_sprint21_5_2.py
"""
from __future__ import annotations

import logging
import sys
import time
import threading
from typing import Any

# Configurar logging para escrever em arquivo (evita problemas de flush
# no Windows com caracteres Unicode no stdout via PowerShell).
_LOG_FILE = r"C:\Users\USER\Documents\AI Lyrics\_diag_sprint21_5_2_output.txt"
_fh = open(_LOG_FILE, "w", encoding="utf-8")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=_fh,
)
logger = logging.getLogger("diag")

# Importar componentes do projeto.
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    SpeechPartial,
    SpeechPartialUpdated,
    IntentCandidate,
    SemanticInferenceCompleted,
)
from pipeline.metadata import EventMetadata
from semantic.cache import SemanticCache
from semantic.context_engine import ContextEngine
from semantic.engine import SemanticEngine
from semantic.types import SemanticResult, SemanticCandidate


# ---------------------------------------------------------------------
# Provider stub que registra todas as chamadas
# ---------------------------------------------------------------------

class RecordingProvider:
    """Provider que registra todas as chamadas e retorna intent=none."""

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
        logger.info("  >>> LLM CHAMADO com texto=%r", context.current_text[:80])
        return SemanticResult(
            intent="none",
            candidates=[],
            inference_ms=10,
            provider=self.name,
            model=self.model_name,
        )

    def warmup(self) -> None:
        pass


# ---------------------------------------------------------------------
# Monkey-patch do SemanticEngine para registrar TODOS os critérios
# ---------------------------------------------------------------------

def instrument_engine(engine: SemanticEngine) -> dict:
    """Envolve _schedule_inference e _should_fire_on_growth com logs.

    Retorna um dict acumulando evidências por frase.
    """
    evidence: dict[str, list[dict]] = {}

    original_schedule = engine._schedule_inference
    original_should_fire = engine._should_fire_on_growth
    original_run = engine._run_inference

    current_phrase = {"text": ""}

    def set_phrase(text: str) -> None:
        current_phrase["text"] = text
        evidence.setdefault(text, [])

    def patched_should_fire(text: str) -> bool:
        now = time.monotonic()
        if engine._last_inference_monotonic == 0.0:
            elapsed_ms = float("inf")
            elapsed_str = "infinito (primeira)"
        else:
            elapsed_ms = (now - engine._last_inference_monotonic) * 1000.0
            elapsed_str = f"{elapsed_ms:.1f}ms"

        growth_chars = engine._count_growth_chars(text)
        append_words = engine._count_append_words(text)

        rate_limit_ok = elapsed_ms >= engine._min_interval_ms
        growth_ok = growth_chars >= engine._min_growth_chars
        append_ok = append_words >= engine._min_append_words

        decision = original_should_fire(text)

        # Determinar motivo se não dispara.
        motivos = []
        if not rate_limit_ok:
            motivos.append(
                f"rate_limit (elapsed={elapsed_str} < min_interval={engine._min_interval_ms}ms)"
            )
        if not growth_ok:
            motivos.append(
                f"growth_chars ({growth_chars} < min_growth={engine._min_growth_chars})"
            )
        if not append_ok:
            motivos.append(
                f"append_words ({append_words} < min_append={engine._min_append_words})"
            )

        logger.info(
            "  [_should_fire_on_growth] text=%r\n"
            "    growth_chars=%d (min=%d) -> %s\n"
            "    append_words=%d (min=%d) -> %s\n"
            "    elapsed_ms=%s (min_interval=%dms) -> %s\n"
            "    DECISÃO: %s%s",
            text[:80],
            growth_chars, engine._min_growth_chars,
            "OK" if growth_ok else "FALHA",
            append_words, engine._min_append_words,
            "OK" if append_ok else "FALHA",
            elapsed_str, engine._min_interval_ms,
            "OK" if rate_limit_ok else "FALHA",
            "DISPARA" if decision else "NÃO DISPARA",
            f" | Motivos: {'; '.join(motivos)}" if motivos else "",
        )

        return decision

    def patched_schedule(text: str, meta: EventMetadata) -> None:
        phrase = current_phrase["text"]
        logger.info(
            "=" * 70 + "\nSpeechPartial recebido: text=%r (len=%d, frase=%r)",
            text, len(text), phrase,
        )

        # Pré-verificar cache para registrar se haveria cache hit.
        # (O cache é consultado dentro de _run_inference, mas queremos
        # registrar a intenção antes da decisão de disparo.)
        cache_hit_preview = False
        try:
            ctx = engine._context_engine.build(
                current_text=text.strip(),
                session_id=engine._session_id,
                correlation_id=meta.correlation_id,
            )
            ctx_hash = ctx.context_hash()
            cached = engine._cache.get(ctx_hash)
            cache_hit_preview = cached is not None
        except Exception as e:
            ctx_hash = f"<erro: {e}>"

        # Verificar debounce ativo.
        debounce_active = engine._debounce_timer is not None

        # Verificar enabled.
        if not engine._enabled:
            logger.info("  DECISÃO FINAL: NÃO chama LLM | Motivo: engine desabilitado")
            evidence.setdefault(phrase, []).append({
                "text": text,
                "decision": "skip_disabled",
                "reason": "engine desabilitado",
            })
            return

        # Verificar min_text_length.
        stripped = text.strip()
        from semantic.engine import _MIN_TEXT_LENGTH
        if len(stripped) < _MIN_TEXT_LENGTH:
            logger.info(
                "  DECISÃO FINAL: NÃO chama LLM | Motivo: texto curto "
                "(len=%d < min_text_length=%d)",
                len(stripped), _MIN_TEXT_LENGTH,
            )
            evidence.setdefault(phrase, []).append({
                "text": text,
                "decision": "skip_short",
                "reason": f"texto curto (len={len(stripped)} < {_MIN_TEXT_LENGTH})",
            })
            return

        # Chamar o _should_fire_on_growth instrumentado.
        with engine._lock:
            should_fire = patched_should_fire(stripped)

        if should_fire:
            logger.info("  >> Gatilho de CRESCIMENTO dispara — chamando _fire_inference")
            evidence.setdefault(phrase, []).append({
                "text": text,
                "decision": "growth_trigger",
                "growth_chars": engine._count_growth_chars(stripped),
                "append_words": engine._count_append_words(stripped),
                "cache_hit_preview": cache_hit_preview,
            })
        else:
            logger.info(
                "  >> Gatilho de crescimento NÃO dispara — agendando debounce %dms",
                engine._debounce_ms,
            )
            evidence.setdefault(phrase, []).append({
                "text": text,
                "decision": "debounce_scheduled",
                "debounce_ms": engine._debounce_ms,
                "cache_hit_preview": cache_hit_preview,
            })

        # Chamar o schedule original (que vai disparar ou agendar debounce).
        original_schedule(text, meta)

    def patched_run(text: str, meta: EventMetadata) -> None:
        logger.info("  [_run_inference] Iniciando — text=%r", text[:80])
        # Construir contexto e verificar cache.
        context = engine._context_engine.build(
            current_text=text,
            session_id=engine._session_id,
            correlation_id=meta.correlation_id,
        )
        ctx_hash = context.context_hash()
        cached = engine._cache.get(ctx_hash)
        if cached is not None:
            logger.info(
                "  [_run_inference] CACHE HIT (hash=%s) — LLM NÃO será chamado",
                ctx_hash,
            )
        else:
            logger.info(
                "  [_run_inference] cache miss (hash=%s) — LLM será chamado",
                ctx_hash,
            )
        original_run(text, meta)

    engine._schedule_inference = patched_schedule
    engine._should_fire_on_growth = patched_should_fire
    engine._run_inference = patched_run

    evidence["_set_phrase"] = set_phrase  # type: ignore
    return evidence


# ---------------------------------------------------------------------
# Teste principal
# ---------------------------------------------------------------------

FRASES = [
    "O Senhor é meu pastor.",
    "Porque Deus amou o mundo.",
    "Tudo posso naquele que me fortalece.",
    "Ainda que eu ande pelo vale da sombra da morte.",
    "A armadura de Deus.",
]


def simular_frase(bus: PipelineEventBus, frase: str, session_id: str) -> None:
    """Simula a publicação de SpeechPartial para uma frase.

    Simula o cenário realista: Whisper transcreve incrementalmente.
    A primeira janela traz o texto completo (frase curta falada em <6s).
    """
    logger.info("\n" + "#" * 70)
    logger.info("# TESTANDO FRASE: %r", frase)
    logger.info("#" * 70)

    meta = EventMetadata.for_initial(
        session_id=session_id,
        origin="StreamingSTTService",
    )
    event = SpeechPartial(
        meta=meta,
        text=frase,
        language="pt",
        confidence=0.85,
        latency_ms=500,
        audio_duration_ms=6000,
        is_stable=False,
    )
    bus.publish(event)


def main() -> None:
    logger.info("=" * 70)
    logger.info("Sprint 21.5.2 — Auditoria da Política de Disparo do SemanticEngine")
    logger.info("=" * 70)

    # Configurar componentes reais com provider de gravação.
    bus = PipelineEventBus()
    provider = RecordingProvider()
    cache = SemanticCache(ttl_seconds=300.0, max_entries=256)
    context_engine = ContextEngine(
        history_fn=bus.history,
        window_seconds=45,
        max_recent_chars=500,
    )

    # Usar os PARÂMETROS REAIS do config.yaml (debounce_ms=800).
    engine = SemanticEngine(
        bus=bus,
        provider=provider,
        context_engine=context_engine,
        cache=cache,
        session_id="diag-session",
        debounce_ms=800,  # ⚠️ Valor real do config.yaml
        timeout_ms=5000,
        enabled=True,
        min_growth_chars=20,
        min_append_words=3,
        min_interval_ms=1000,
    )

    # Instrumentar o engine.
    evidence = instrument_engine(engine)
    set_phrase = evidence["_set_phrase"]  # type: ignore

    # Registrar telemetria para ver o que chega ao frontend.
    telemetry_events: list[SemanticInferenceCompleted] = []

    def on_telemetry(event: SemanticInferenceCompleted) -> None:
        telemetry_events.append(event)
        logger.info(
            "  [TELEMETRIA] intent=%s, candidates=%d, cached=%s, error=%r, "
            "context_text=%r, inference_ms=%d",
            event.intent, event.num_candidates, event.cached,
            event.error, event.context_text[:60], event.inference_ms,
        )

    bus.subscribe(SemanticInferenceCompleted, on_telemetry)

    # Iniciar engine.
    engine.start()

    # Executar cada frase com intervalo para evitar rate limit entre frases.
    for i, frase in enumerate(FRASES):
        if i > 0:
            logger.info("\n--- Aguardando 1.2s para evitar rate limit entre frases ---")
            time.sleep(1.2)
        set_phrase(frase)
        simular_frase(bus, frase, "diag-session")
        # Aguardar debounce + margem para o timer disparar.
        time.sleep(1.0)

    # Aguardar qualquer debounce pendente.
    time.sleep(1.5)

    # Relatório final.
    logger.info("\n\n" + "=" * 70)
    logger.info("RELATÓRIO DE EVIDÊNCIAS")
    logger.info("=" * 70)

    for frase in FRASES:
        logger.info("\n--- Frase: %r ---", frase)
        entries = evidence.get(frase, [])
        if not entries:
            logger.info("  Nenhuma evidência registrada (evento não chegou?)")
            continue
        for j, entry in enumerate(entries):
            logger.info("  Evento %d:", j + 1)
            for k, v in entry.items():
                if k == "text":
                    continue
                logger.info("    %s: %s", k, v)

    logger.info("\n--- Telemetria recebida (%d eventos) ---", len(telemetry_events))
    for t in telemetry_events:
        logger.info(
            "  intent=%s, cached=%s, context=%r, error=%r",
            t.intent, t.cached, t.context_text[:60], t.error,
        )

    logger.info("\n--- Chamadas ao LLM (%d) ---", len(provider.calls))
    for c in provider.calls:
        logger.info("  %r", c[:80])

    logger.info("\n--- Stats do Engine ---")
    stats = engine.stats()
    for k, v in stats.items():
        logger.info("  %s: %s", k, v)

    # Parar engine.
    engine.stop()
    logger.info("\nFim do diagnóstico.")
    _fh.flush()
    _fh.close()
    print(f"Diagnóstico concluído. Saída em: {_LOG_FILE}")


if __name__ == "__main__":
    main()
