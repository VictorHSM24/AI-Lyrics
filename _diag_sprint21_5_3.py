"""Sprint 21.5.3 — Validação da Integridade do EventBus.

Script INSTRUMENTADO de diagnóstico. Não modifica arquivos do projeto.
Usa monkey-patching para envolver EventBus.publish() e cada handler de
subscriber com logs detalhados.

Para cada publish() registra:
  - Tipo do evento, correlation_id, event_id
  - Lista de subscribers registrados (em ordem)
  - Antes/depois de cada subscriber com tempo
  - Exceções com stacktrace completo
  - Quais subscribers foram executados e quais não foram

Para cada subscriber registra (na primeira linha do handler):
  - SpeechPartial recebido
  - correlation_id, texto, thread, timestamp

Testes:
  1. "Provérbios 15:14" (referência explícita)
  2. "O Senhor é meu pastor." (implícita)
  3. "Porque Deus amou o mundo." (implícita)
  4. "Ainda que eu ande pelo vale da sombra da morte." (implícita)
  5. "Tudo posso naquele que me fortalece." (implícita)

Uso:
    python _diag_sprint21_5_3.py
"""
from __future__ import annotations

import logging
import sys
import time
import threading
import traceback
from typing import Any

# ---------------------------------------------------------------------
# Logging para arquivo (evita problemas de flush no Windows)
# ---------------------------------------------------------------------
_LOG_FILE = r"C:\Users\USER\Documents\AI Lyrics\_diag_sprint21_5_3_output.txt"
_fh = open(_LOG_FILE, "w", encoding="utf-8")
logging.basicConfig(
    level=logging.WARNING,  # WARNING para não duplicar logs dos módulos
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=_fh,
)
# Logger do diagnóstico em INFO (manual)
logger = logging.getLogger("diag")
logger.setLevel(logging.INFO)
_fh_handler = logging.StreamHandler(_fh)
_fh_handler.setLevel(logging.INFO)
_fh_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_fh_handler)
logger.propagate = False


# ---------------------------------------------------------------------
# Imports do projeto
# ---------------------------------------------------------------------
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    SpeechPartial,
    SpeechPartialUpdated,
    SemanticInferenceCompleted,
    IntentCandidate,
    ReferenceDetected,
    SermonContextUpdated,
)
from pipeline.metadata import EventMetadata
from semantic.cache import SemanticCache
from semantic.context_engine import ContextEngine
from semantic.engine import SemanticEngine
from semantic.types import SemanticResult
from sermon import SermonMemoryEngine


# ---------------------------------------------------------------------
# Provider de gravação
# ---------------------------------------------------------------------
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


# ---------------------------------------------------------------------
# Instrumentação do EventBus.publish()
# ---------------------------------------------------------------------
def instrument_bus(bus: PipelineEventBus) -> dict:
    """Envolve publish() com logs detalhados de cada subscriber.

    Retorna um dict acumulando evidências.
    """
    original_publish = bus.publish
    evidence: dict[str, list[dict]] = {"publishes": []}

    def patched_publish(event: Any) -> None:
        event_type = type(event).__name__
        # Coletar metadados do evento.
        meta = getattr(event, "meta", None)
        corr_id = getattr(meta, "correlation_id", "?") if meta else "?"
        event_id = getattr(meta, "event_id", "?") if meta else "?"
        text = getattr(event, "text", "")
        appended = getattr(event, "appended_text", "")

        # Só logar detalhadamente SpeechPartial e SpeechPartialUpdated.
        if event_type not in ("SpeechPartial", "SpeechPartialUpdated"):
            original_publish(event)
            return

        # Snapshot dos handlers (em ordem de inscrição).
        event_type_cls = type(event)
        handlers = list(bus._subscriptions.get(event_type_cls, []))

        # Mapear handler → nome amigável.
        def handler_name(h):
            qual = getattr(h, "__qualname__", str(h))
            # _on_partial de IncrementalParser/SermonMemoryEngine/SemanticEngine
            if "IncrementalBiblicalParser" in qual or "incremental" in str(h).lower():
                return "IncrementalParser"
            if "SermonMemoryEngine" in qual or "sermon" in str(h).lower():
                return "SermonMemoryEngine"
            if "SemanticEngine" in qual or "semantic" in str(h).lower():
                return "SemanticEngine"
            if "fake_incremental" in qual:
                return "IncrementalParser(proxy)"
            return qual

        names = [handler_name(h) for h in handlers]

        logger.info("")
        logger.info("=" * 70)
        logger.info("EVENTO: %s", event_type)
        logger.info("  ID: %s", event_id)
        logger.info("  Correlation: %s", corr_id)
        logger.info("  Texto: %r", text[:80] if text else "")
        if appended:
            logger.info("  Appended: %r", appended[:60])
        logger.info("  Subscribers registrados: %d", len(handlers))
        for i, n in enumerate(names, 1):
            logger.info("    %d. %s", i, n)
        logger.info("=" * 70)

        # Executar handlers manualmente com instrumentação.
        # NÃO usar o publish original — replicamos o loop para instrumentar.
        # Mas precisamos armazenar no EventStore como o publish original faria.
        from pipeline.events import TelemetryEvent
        if not isinstance(event, TelemetryEvent):
            bus._store.append(event)

        executed: list[str] = []
        failed: list[dict] = []
        interrupted = False

        for i, (h, name) in enumerate(zip(handlers, names)):
            logger.info("")
            logger.info("→ Executando subscriber: %s", name)
            t0 = time.monotonic()
            try:
                h(event)
                elapsed_ms = (time.monotonic() - t0) * 1000.0
                logger.info("← %s concluído (tempo=%.2fms)", name, elapsed_ms)
                executed.append(name)
            except Exception as e:
                elapsed_ms = (time.monotonic() - t0) * 1000.0
                tb = traceback.format_exc()
                logger.info("✗ %s lançou EXCEÇÃO (tempo=%.2fms)", name, elapsed_ms)
                logger.info("  Tipo: %s", type(e).__name__)
                logger.info("  Mensagem: %s", str(e))
                logger.info("  Stacktrace:")
                for line in tb.splitlines():
                    logger.info("    %s", line)
                failed.append({
                    "subscriber": name,
                    "type": type(e).__name__,
                    "message": str(e),
                    "stacktrace": tb,
                })
                # Subscribers restantes.
                remaining = names[i + 1:]
                logger.info("  Subscribers restantes: %s", remaining or "NENHUM")
                logger.info("  ⚠️ LOOP INTERROMPIDO — subscribers restantes NÃO executarão")
                interrupted = True
                break

        logger.info("")
        logger.info("PUBLISH FINALIZADO")
        logger.info("  Subscribers executados: %s", executed or "NENHUM")
        if failed:
            logger.info("  Subscribers que falharam: %s",
                        [f["subscriber"] for f in failed])
        if interrupted:
            not_executed = [n for n in names if n not in executed]
            logger.info("  Subscribers NÃO executados: %s", not_executed)
        else:
            logger.info("  Todos os subscribers executaram com sucesso.")

        evidence["publishes"].append({
            "event_type": event_type,
            "correlation_id": corr_id,
            "text": text[:80],
            "subscribers": names,
            "executed": executed,
            "failed": failed,
            "interrupted": interrupted,
        })

    bus.publish = patched_publish
    return evidence


# ---------------------------------------------------------------------
# Instrumentação de handlers (wrap na primeira linha)
# ---------------------------------------------------------------------
def instrument_handler(obj: Any, method_name: str, label: str) -> None:
    """Envolve um handler para logar recebimento na primeira linha."""
    original = getattr(obj, method_name)

    def patched(event):
        corr = getattr(event.meta, "correlation_id", "?")
        text = getattr(event, "text", "")
        thread = threading.current_thread().name
        ts = time.time()
        logger.info("")
        logger.info("  [%s] %s RECEBIDO", label, label)
        logger.info("    correlation: %s", corr)
        logger.info("    texto: %r", text[:80] if text else "")
        logger.info("    thread: %s", thread)
        logger.info("    timestamp: %.3f", ts)
        logger.info("    [%s] Processando...", label)
        t0 = time.monotonic()
        try:
            result = original(event)
            elapsed = (time.monotonic() - t0) * 1000.0
            logger.info("    [%s] concluído (tempo=%.2fms)", label, elapsed)
            return result
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000.0
            logger.info("    [%s] EXCEÇÃO (tempo=%.2fms): %s: %s",
                        label, elapsed, type(e).__name__, e)
            raise

    setattr(obj, method_name, patched)


# ---------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------
TESTES = [
    ("Referência EXPLÍCITA", "Provérbios 15:14"),
    ("Referência IMPLÍCITA", "O Senhor é meu pastor."),
    ("Referência IMPLÍCITA", "Porque Deus amou o mundo."),
    ("Referência IMPLÍCITA", "Ainda que eu ande pelo vale da sombra da morte."),
    ("Referência IMPLÍCITA", "Tudo posso naquele que me fortalece."),
]


def simular_publicacao(bus: PipelineEventBus, frase: str, session_id: str,
                       confidence: float = 0.85) -> None:
    """Simula publicação de SpeechPartial pelo StreamingSTTService."""
    logger.info("")
    logger.info("#" * 70)
    logger.info("# STREAMING STT PUBLICANDO")
    logger.info("# SpeechPartial publicado")
    logger.info("#   texto: %r", frase)
    logger.info("#   timestamp: %.3f", time.time())
    logger.info("#" * 70)

    meta = EventMetadata.for_initial(
        session_id=session_id, origin="StreamingSTTService")
    event = SpeechPartial(
        meta=meta, text=frase, language="pt", confidence=confidence,
        latency_ms=500, audio_duration_ms=6000, is_stable=False)
    bus.publish(event)


def main() -> None:
    logger.info("=" * 70)
    logger.info("Sprint 21.5.3 — Validação da Integridade do EventBus")
    logger.info("=" * 70)
    logger.info("Data: %s", time.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("")

    bus = PipelineEventBus()

    # 1. IncrementalParser — proxy (não podemos instanciar o real sem books).
    #    O IncrementalParser real não lança exceções (apenas retorna early).
    incremental_received: list[dict] = []

    def incremental_proxy(event):
        corr = getattr(event.meta, "correlation_id", "?")
        text = getattr(event, "text", "")
        thread = threading.current_thread().name
        logger.info("")
        logger.info("  [IncrementalParser] SpeechPartial RECEBIDO")
        logger.info("    correlation: %s", corr)
        logger.info("    texto: %r", text[:80])
        logger.info("    thread: %s", thread)
        logger.info("    timestamp: %.3f", time.time())
        logger.info("    [IncrementalParser] Processando (proxy — não faz nada)...")
        logger.info("    [IncrementalParser] concluído (tempo=0.01ms)")
        incremental_received.append({"correlation": corr, "text": text})

    bus.subscribe(SpeechPartial, incremental_proxy)
    bus.subscribe(SpeechPartialUpdated, incremental_proxy)

    # 2. SermonMemoryEngine — REAL
    sermon_engine = SermonMemoryEngine(bus=bus, session_id="diag")
    # Instrumentar antes de start() para wrap dos handlers.
    instrument_handler(sermon_engine, "_on_partial", "SermonMemoryEngine")
    instrument_handler(sermon_engine, "_on_partial_updated", "SermonMemoryEngine")
    sermon_engine.start()
    logger.info("SermonMemoryEngine iniciado (instrumentado).")

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
    # Instrumentar handlers do SemanticEngine.
    instrument_handler(engine, "_on_partial", "SemanticEngine")
    instrument_handler(engine, "_on_partial_updated", "SemanticEngine")
    engine.start()
    logger.info("SemanticEngine iniciado (instrumentado).")

    # Instrumentar o EventBus.publish() — DEPOIS de todas as inscrições.
    evidence = instrument_bus(bus)

    # Telemetria.
    telemetry: list[SemanticInferenceCompleted] = []
    bus.subscribe(SemanticInferenceCompleted, lambda e: telemetry.append(e))

    # Verificar ordem de inscrição.
    handlers_sp = bus._subscriptions.get(SpeechPartial, [])
    logger.info("")
    logger.info("ORDEM DE INSCRIÇÃO SpeechPartial: %d handlers", len(handlers_sp))
    for i, h in enumerate(handlers_sp, 1):
        qual = getattr(h, "__qualname__", str(h))
        logger.info("  %d. %s", i, qual)

    # Executar testes.
    for nome, frase in TESTES:
        logger.info("")
        logger.info("")
        logger.info("█" * 70)
        logger.info("█ TESTE: %s", nome)
        logger.info("█ FRASE: %r", frase)
        logger.info("█" * 70)

        # Resetar estado do SemanticEngine entre testes.
        with engine._lock:
            if engine._debounce_timer:
                engine._debounce_timer.cancel()
                engine._debounce_timer = None
            engine._pending_text = ""
            engine._pending_meta = None
            engine._last_inferred_text = ""
            engine._last_inference_monotonic = 0.0

        simular_publicacao(bus, frase, "diag")

        # Aguardar debounce + margem.
        logger.info("")
        logger.info(">> Aguardando 1.5s para debounce expirar...")
        time.sleep(1.5)

    # -----------------------------------------------------------------
    # Relatório final
    # -----------------------------------------------------------------
    logger.info("")
    logger.info("")
    logger.info("=" * 70)
    logger.info("RELATÓRIO FINAL — Sprint 21.5.3")
    logger.info("=" * 70)

    logger.info("")
    logger.info("1. ORDEM REAL DE EXECUÇÃO DOS SUBSCRIBERS")
    logger.info("-" * 50)
    for pub in evidence["publishes"]:
        if pub["event_type"] != "SpeechPartial":
            continue
        logger.info("  Evento: %s | corr=%s | text=%r",
                    pub["event_type"], pub["correlation_id"][:12], pub["text"])
        logger.info("    Ordem: %s", pub["subscribers"])
        logger.info("    Executados: %s", pub["executed"])
        if pub["failed"]:
            logger.info("    FALHARAM: %s",
                        [f["subscriber"] for f in pub["failed"]])
            for f in pub["failed"]:
                logger.info("      %s: %s: %s",
                            f["subscriber"], f["type"], f["message"])
        logger.info("    Interrompido: %s", pub["interrupted"])

    logger.info("")
    logger.info("2. TEMPO GASTO POR CADA SUBSCRIBER")
    logger.info("-" * 50)
    # Os tempos estão nos logs acima; resumir aqui seria redundante.
    logger.info("  (ver logs detalhados acima)")

    logger.info("")
    logger.info("3. EVENTOS RECEBIDOS POR CADA COMPONENTE")
    logger.info("-" * 50)
    logger.info("  IncrementalParser (proxy) recebeu: %d eventos",
                len(incremental_received))
    for r in incremental_received:
        logger.info("    corr=%s text=%r", r["correlation"][:12], r["text"][:60])

    logger.info("")
    logger.info("4. CHAMADAS AO LLM (SemanticEngine)")
    logger.info("-" * 50)
    logger.info("  Total: %d", len(provider.calls))
    for c in provider.calls:
        logger.info("    %r", c[:80])

    logger.info("")
    logger.info("5. TELEMETRIA (SemanticInferenceCompleted)")
    logger.info("-" * 50)
    logger.info("  Total: %d", len(telemetry))
    for t in telemetry:
        logger.info("    intent=%s cached=%s context=%r error=%r",
                    t.intent, t.cached, t.context_text[:60], t.error)

    logger.info("")
    logger.info("6. EXCEÇÕES ENCONTRADAS")
    logger.info("-" * 50)
    total_exceptions = sum(len(p["failed"]) for p in evidence["publishes"])
    logger.info("  Total: %d", total_exceptions)
    if total_exceptions == 0:
        logger.info("  NENHUMA exceção encontrada em nenhum subscriber.")

    logger.info("")
    logger.info("7. EVIDÊNCIA DE INTERRUPÇÃO")
    logger.info("-" * 50)
    interruptions = [p for p in evidence["publishes"] if p["interrupted"]]
    logger.info("  Publicações interrompidas: %d / %d",
                len(interruptions), len(evidence["publishes"]))
    if not interruptions:
        logger.info("  NENHUMA interrupção detectada.")
        logger.info("  Todos os subscribers receberam todos os eventos.")

    logger.info("")
    logger.info("8. VALIDAÇÃO DA HIPÓTESE")
    logger.info("-" * 50)
    semantic_received = len(telemetry)  # proxy: se há telemetria, SemanticEngine recebeu
    logger.info("  Eventos SpeechPartial publicados: %d", len(TESTES))
    logger.info("  Eventos recebidos pelo SemanticEngine: %d", semantic_received)
    logger.info("  Eventos que chamaram o LLM: %d", len(provider.calls))
    if semantic_received == len(TESTES):
        logger.info("")
        logger.info("  CONCLUSÃO: O SemanticEngine recebeu TODOS os eventos.")
        logger.info("  A hipótese do EventBus interromper a propagação é REFUTADA")
        logger.info("  neste cenário de teste.")
    else:
        logger.info("")
        logger.info("  CONCLUSÃO: O SemanticEngine NÃO recebeu todos os eventos.")
        logger.info("  A hipótese do EventBus interromper a propagação é CONFIRMADA.")

    # Stats dos engines.
    logger.info("")
    logger.info("9. STATS DOS ENGINES")
    logger.info("-" * 50)
    stats = engine.stats()
    for k, v in stats.items():
        logger.info("  %s: %s", k, v)

    # Parar.
    engine.stop()
    sermon_engine.stop()
    _fh.flush()
    _fh.close()
    print(f"Diagnóstico concluído. Saída em: {_LOG_FILE}")


if __name__ == "__main__":
    main()
