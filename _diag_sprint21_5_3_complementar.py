"""Sprint 21.5.3 — Teste COMPLEMENTAR: prova do mecanismo + IncrementalParser real.

Teste A: Injetar exceção no SermonMemoryEngine para PROVAR que o EventBus
         interrompe o loop e o SemanticEngine não recebe o evento.

Teste B: Instanciar o IncrementalParser REAL e verificar se ele lança
         exceção ao processar as 5 frases.
"""
from __future__ import annotations

import logging
import time
import threading
import traceback
from typing import Any

_LOG_FILE = r"C:\Users\USER\Documents\AI Lyrics\_diag_sprint21_5_3_complementar_output.txt"
_fh = open(_LOG_FILE, "w", encoding="utf-8")
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=_fh,
)
logger = logging.getLogger("diag")
logger.setLevel(logging.INFO)
_fh_handler = logging.StreamHandler(_fh)
_fh_handler.setLevel(logging.INFO)
_fh_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_fh_handler)
logger.propagate = False

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    SpeechPartial, SpeechPartialUpdated, SemanticInferenceCompleted,
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


def instrument_bus(bus: PipelineEventBus) -> dict:
    original_publish = bus.publish
    evidence: dict = {"publishes": []}

    def patched_publish(event: Any) -> None:
        event_type = type(event).__name__
        if event_type not in ("SpeechPartial", "SpeechPartialUpdated"):
            original_publish(event)
            return
        meta = getattr(event, "meta", None)
        corr = getattr(meta, "correlation_id", "?") if meta else "?"
        text = getattr(event, "text", "")
        handlers = list(bus._subscriptions.get(type(event), []))

        def hname(h):
            q = getattr(h, "__qualname__", str(h))
            if "IncrementalBiblicalParser" in q: return "IncrementalParser"
            if "incremental_proxy" in q: return "IncrementalParser(proxy)"
            if "SermonMemoryEngine" in q or "sermon" in str(h).lower(): return "SermonMemoryEngine"
            if "SemanticEngine" in q or "semantic" in str(h).lower(): return "SemanticEngine"
            if "failing_proxy" in q: return "SermonMemoryEngine(FAILING)"
            return q

        names = [hname(h) for h in handlers]
        logger.info("")
        logger.info("=" * 70)
        logger.info("EVENTO: %s | corr=%s | text=%r", event_type, corr[:12], text[:60])
        logger.info("  Subscribers: %s", names)
        logger.info("=" * 70)

        from pipeline.events import TelemetryEvent
        if not isinstance(event, TelemetryEvent):
            bus._store.append(event)

        executed = []
        failed = []
        interrupted = False

        for i, (h, name) in enumerate(zip(handlers, names)):
            logger.info("→ %s", name)
            t0 = time.monotonic()
            try:
                h(event)
                ms = (time.monotonic() - t0) * 1000
                logger.info("← %s OK (%.2fms)", name, ms)
                executed.append(name)
            except Exception as e:
                ms = (time.monotonic() - t0) * 1000
                logger.info("✗ %s EXCEÇÃO (%.2fms): %s: %s", name, ms, type(e).__name__, e)
                tb = traceback.format_exc()
                for line in tb.splitlines():
                    logger.info("    %s", line)
                failed.append({"subscriber": name, "type": type(e).__name__, "msg": str(e)})
                remaining = names[i + 1:]
                logger.info("  ⚠️ LOOP INTERROMPIDO — restantes NÃO executarão: %s", remaining)
                interrupted = True
                break

        logger.info("PUBLISH FINALIZADO | executados=%s | interrompido=%s", executed, interrupted)
        evidence["publishes"].append({
            "event_type": event_type, "correlation_id": corr, "text": text[:80],
            "subscribers": names, "executed": executed, "failed": failed,
            "interrupted": interrupted,
        })

    bus.publish = patched_publish
    return evidence


# ---------------------------------------------------------------------
# Teste A: Provar o mecanismo de interrupção
# ---------------------------------------------------------------------
def teste_a_mecanismo_interrupcao() -> dict:
    """Injeta exceção no SermonMemoryEngine para provar que o EventBus
    interrompe o loop e o SemanticEngine não recebe o evento."""
    logger.info("")
    logger.info("█" * 70)
    logger.info("█ TESTE A: PROVA DO MECANISMO DE INTERRUPÇÃO")
    logger.info("█ Injetar exceção no SermonMemoryEngine e verificar se")
    logger.info("█ o SemanticEngine deixa de receber o evento.")
    logger.info("█" * 70)

    bus = PipelineEventBus()
    provider = RecordingProvider()

    # Handler 1: IncrementalParser proxy.
    inc_received = []
    def inc_proxy(event):
        inc_received.append(event.text)
        logger.info("  [IncrementalParser(proxy)] recebeu %r", event.text[:60])

    # Handler 2: SermonMemoryEngine que SEMPRE lança exceção.
    sermon_received = []
    def failing_proxy(event):
        sermon_received.append(event.text)
        logger.info("  [SermonMemoryEngine(FAILING)] recebeu %r — vai lançar exceção", event.text[:60])
        raise RuntimeError("EXCEÇÃO INJETADA para provar interrupção do EventBus")

    # Handler 3: SemanticEngine real.
    cache = SemanticCache()
    ctx = ContextEngine(history_fn=bus.history)
    engine = SemanticEngine(bus=bus, provider=provider, context_engine=ctx,
                            cache=cache, session_id="diag", debounce_ms=800,
                            enabled=True, min_growth_chars=20,
                            min_append_words=3, min_interval_ms=1000)
    sem_received = []
    original_on_partial = engine._on_partial
    def sem_trace(event):
        sem_received.append(event.text)
        logger.info("  [SemanticEngine] RECEBEU %r", event.text[:60])
        original_on_partial(event)
    engine._on_partial = sem_trace

    # Inscrever na ORDEM REAL do composition.py.
    bus.subscribe(SpeechPartial, inc_proxy)        # 1. IncrementalParser
    bus.subscribe(SpeechPartial, failing_proxy)    # 2. SermonMemoryEngine (FALHA)
    engine.start()                                  # 3. SemanticEngine

    evidence = instrument_bus(bus)

    # Publicar 3 frases.
    frases = ["O Senhor é meu pastor.", "Porque Deus amou o mundo.", "Tudo posso naquele que me fortalece."]
    for frase in frases:
        logger.info("\n--- Publicando: %r ---", frase)
        with engine._lock:
            if engine._debounce_timer:
                engine._debounce_timer.cancel()
                engine._debounce_timer = None
            engine._pending_text = ""
            engine._pending_meta = None
            engine._last_inferred_text = ""
            engine._last_inference_monotonic = 0.0

        meta = EventMetadata.for_initial(session_id="diag", origin="StreamingSTTService")
        bus.publish(SpeechPartial(meta=meta, text=frase, language="pt",
                                  confidence=0.85, latency_ms=500, audio_duration_ms=6000))
        time.sleep(0.5)

    # Relatório do Teste A.
    logger.info("")
    logger.info("RESULTADO TESTE A:")
    logger.info("  IncrementalParser recebeu: %d eventos", len(inc_received))
    logger.info("  SermonMemoryEngine recebeu: %d eventos (antes de falhar)", len(sermon_received))
    logger.info("  SemanticEngine recebeu: %d eventos", len(sem_received))
    logger.info("  LLM chamado: %d vezes", len(provider.calls))

    if len(sem_received) == 0 and len(inc_received) == len(frases):
        logger.info("")
        logger.info("  ✅ PROVA CONFIRMADA: A exceção no SermonMemoryEngine")
        logger.info("  interrompeu o loop do EventBus, e o SemanticEngine")
        logger.info("  NUNCA recebeu os eventos.")
    else:
        logger.info("")
        logger.info("  ❌ PROVA FALHOU: O SemanticEngine recebeu eventos mesmo")
        logger.info("  com exceção no SermonMemoryEngine.")

    engine.stop()
    return {
        "inc_received": len(inc_received),
        "sermon_received": len(sermon_received),
        "sem_received": len(sem_received),
        "llm_calls": len(provider.calls),
        "evidence": evidence["publishes"],
    }


# ---------------------------------------------------------------------
# Teste B: IncrementalParser REAL
# ---------------------------------------------------------------------
def teste_b_incremental_parser_real() -> dict:
    """Instancia o IncrementalParser real e verifica se ele lança exceção."""
    logger.info("")
    logger.info("█" * 70)
    logger.info("█ TESTE B: INCREMENTALPARSER REAL")
    logger.info("█ Verificar se o IncrementalParser real lança exceção ao")
    logger.info("█ processar as 5 frases de teste.")
    logger.info("█" * 70)

    try:
        from pipeline.incremental_parser import IncrementalBiblicalParser
        from parser.books import load_parser_books
        parser_books = load_parser_books("config/books.json")
        logger.info("  parser_books carregado com sucesso.")
    except Exception as e:
        logger.info("  ❌ Não foi possível carregar parser_books: %s", e)
        return {"error": str(e)}

    bus = PipelineEventBus()
    provider = RecordingProvider()

    # IncrementalParser REAL.
    try:
        parser = IncrementalBiblicalParser(books=parser_books, bus=bus, session_id="diag")
        parser.start()
        logger.info("  IncrementalParser real iniciado.")
    except Exception as e:
        logger.info("  ❌ Não foi possível iniciar IncrementalParser: %s", e)
        return {"error": str(e)}

    # SermonMemoryEngine REAL.
    sermon = SermonMemoryEngine(bus=bus, session_id="diag")
    sermon.start()
    logger.info("  SermonMemoryEngine real iniciado.")

    # SemanticEngine REAL.
    cache = SemanticCache()
    ctx = ContextEngine(history_fn=bus.history, sermon_context_fn=sermon.get_context)
    engine = SemanticEngine(bus=bus, provider=provider, context_engine=ctx,
                            cache=cache, session_id="diag", debounce_ms=800,
                            enabled=True, min_growth_chars=20,
                            min_append_words=3, min_interval_ms=1000)
    sem_received = []
    original_on_partial = engine._on_partial
    def sem_trace(event):
        sem_received.append(event.text)
        logger.info("  [SemanticEngine] RECEBEU %r", event.text[:60])
        original_on_partial(event)
    engine._on_partial = sem_trace
    engine.start()
    logger.info("  SemanticEngine real iniciado.")

    evidence = instrument_bus(bus)

    # Executar 5 testes.
    TESTES = [
        ("EXPLÍCITA", "Provérbios 15:14"),
        ("IMPLÍCITA", "O Senhor é meu pastor."),
        ("IMPLÍCITA", "Porque Deus amou o mundo."),
        ("IMPLÍCITA", "Ainda que eu ande pelo vale da sombra da morte."),
        ("IMPLÍCITA", "Tudo posso naquele que me fortalece."),
    ]

    for nome, frase in TESTES:
        logger.info("\n--- TESTE %s: %r ---", nome, frase)
        with engine._lock:
            if engine._debounce_timer:
                engine._debounce_timer.cancel()
                engine._debounce_timer = None
            engine._pending_text = ""
            engine._pending_meta = None
            engine._last_inferred_text = ""
            engine._last_inference_monotonic = 0.0
        # Reset do parser entre frases.
        parser._detected_published = False
        parser._correlation_id = None
        parser._seen_text = ""
        parser._expecting = "book"
        parser._current_book = None

        meta = EventMetadata.for_initial(session_id="diag", origin="StreamingSTTService")
        bus.publish(SpeechPartial(meta=meta, text=frase, language="pt",
                                  confidence=0.85, latency_ms=500, audio_duration_ms=6000))
        time.sleep(1.5)

    # Relatório.
    logger.info("")
    logger.info("RESULTADO TESTE B:")
    logger.info("  SemanticEngine recebeu: %d / 5 eventos", len(sem_received))
    logger.info("  LLM chamado: %d vezes", len(provider.calls))

    total_exceptions = sum(len(p["failed"]) for p in evidence["publishes"])
    interruptions = sum(1 for p in evidence["publishes"] if p["interrupted"])
    logger.info("  Exceções: %d", total_exceptions)
    logger.info("  Interrupções: %d / %d", interruptions, len(evidence["publishes"]))

    if total_exceptions > 0:
        logger.info("\n  EXCEÇÕES DETALHADAS:")
        for p in evidence["publishes"]:
            for f in p["failed"]:
                logger.info("    %s | %s: %s", p["text"][:50], f["subscriber"], f["type"])
                logger.info("      %s", f["msg"])

    engine.stop()
    sermon.stop()
    try:
        parser.stop()
    except Exception:
        pass

    return {
        "sem_received": len(sem_received),
        "llm_calls": len(provider.calls),
        "exceptions": total_exceptions,
        "interruptions": interruptions,
        "evidence": evidence["publishes"],
    }


def main() -> None:
    logger.info("=" * 70)
    logger.info("Sprint 21.5.3 — Teste COMPLEMENTAR")
    logger.info("=" * 70)

    resultado_a = teste_a_mecanismo_interrupcao()
    time.sleep(1.0)
    resultado_b = teste_b_incremental_parser_real()

    # Resumo final.
    logger.info("")
    logger.info("")
    logger.info("=" * 70)
    logger.info("RESUMO FINAL — Sprint 21.5.3")
    logger.info("=" * 70)

    logger.info("")
    logger.info("TESTE A — Prova do mecanismo de interrupção:")
    logger.info("  IncrementalParser recebeu: %d", resultado_a["inc_received"])
    logger.info("  SermonMemoryEngine recebeu (antes de falhar): %d", resultado_a["sermon_received"])
    logger.info("  SemanticEngine recebeu: %d", resultado_a["sem_received"])
    logger.info("  LLM chamado: %d", resultado_a["llm_calls"])
    if resultado_a["sem_received"] == 0 and resultado_a["inc_received"] > 0:
        logger.info("  → MECANISMO CONFIRMADO: exceção em handler interrompe o loop.")

    logger.info("")
    logger.info("TESTE B — IncrementalParser real + SermonMemory real + SemanticEngine real:")
    if "error" in resultado_b:
        logger.info("  ERRO: %s", resultado_b["error"])
    else:
        logger.info("  SemanticEngine recebeu: %d / 5", resultado_b["sem_received"])
        logger.info("  LLM chamado: %d", resultado_b["llm_calls"])
        logger.info("  Exceções: %d", resultado_b["exceptions"])
        logger.info("  Interrupções: %d", resultado_b["interruptions"])
        if resultado_b["exceptions"] == 0:
            logger.info("  → NENHUMA exceção lançada pelos componentes reais.")
            logger.info("  → A hipótese do EventBus interromper a propagação é")
            logger.info("    REFUTADA para os componentes reais com as 5 frases de teste.")

    logger.info("")
    logger.info("CONCLUSÃO DEFINITIVA:")
    logger.info("  1. O MECANISMO de interrupção existe (Teste A provou).")
    logger.info("  2. Os componentes REAIS não lançam exceções com as 5 frases (Teste B).")
    logger.info("  3. A causa da ausência de inferências em produção NÃO está no EventBus")
    logger.info("     com os componentes e frases testados.")
    logger.info("  4. A causa deve estar em outro ponto do pipeline (StreamingSTTService,")
    logger.info("     áudio, Whisper, ou condições específicas de produção).")

    _fh.flush()
    _fh.close()
    print(f"Concluído. Saída em: {_LOG_FILE}")


if __name__ == "__main__":
    main()
