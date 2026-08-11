"""Investigação da cadeia semântica — LLM not triggering.

Instrumenta o caminho completo:
  SpeechPartial → EventBus → IncrementalParser → SermonMemoryEngine
  → SemanticEngine → ContextEngine → LocalLLMProvider → OllamaBackend
  → Ollama → resposta RAW → JSON parser → SemanticResult
  → IntentCandidate → ReferenceResolver → ReferenceDetected

Fases:
  1. Teste do Ollama independente (FASE 5)
  2. Teste da cadeia sem EventBus (FASE 4)
  3. Teste do EventBus com falha isolada (FASE 3)
  4. Teste controlado A-E com trace completo (FASE 2)
  5. Matriz de evidências (FASE 8)

Uso:
    python tools/internal/_diag_llm_chain_investigation.py
"""
from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from typing import Any

# -----------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------
_LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "_diag_llm_chain_output.txt",
)
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

# -----------------------------------------------------------------------
# Imports do projeto
# -----------------------------------------------------------------------
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    SpeechPartial,
    SpeechPartialUpdated,
    SemanticInferenceCompleted,
    IntentCandidate,
    ReferenceDetected,
    SemanticResolutionCompleted,
)
from pipeline.metadata import EventMetadata
from semantic.cache import SemanticCache
from semantic.context_engine import ContextEngine
from semantic.engine import SemanticEngine
from semantic.local_provider import LocalLLMProvider, _SYSTEM_PROMPT
from semantic.backend_factory import create_backend, normalize_base_url_for_backend
from semantic.types import SemanticContext, SemanticResult, SemanticCandidate
from semantic.resolver import ReferenceResolver
from sermon import SermonMemoryEngine

# -----------------------------------------------------------------------
# Config (lê do config.yaml real)
# -----------------------------------------------------------------------
_BASE_URL = "http://localhost:11434"
_MODEL = "qwen3:8b-q4_K_M"
_TIMEOUT_S = 30.0

# -----------------------------------------------------------------------
# EventBus instrumentado
# -----------------------------------------------------------------------
class InstrumentedEventBus(PipelineEventBus):
    """PipelineEventBus com trace de execução por handler."""

    def __init__(self, store=None):
        super().__init__(store)
        self._handler_names: dict[int, str] = {}
        self._trace: list[dict] = []

    def subscribe(self, event_type, handler):
        super().subscribe(event_type, handler)
        name = getattr(handler, "__self__", None)
        label = ""
        if name is not None:
            label = type(name).__name__ + "." + handler.__name__
        else:
            label = getattr(handler, "__name__", str(handler))
        self._handler_names[id(handler)] = f"{event_type.__name__}→{label}"

    def publish(self, event):
        event_type = type(event)
        type_name = event_type.__name__
        handlers = list(self._subscriptions.get(event_type, []))
        corr = getattr(getattr(event, "meta", None), "correlation_id", "")

        for i, handler in enumerate(handlers):
            hname = self._handler_names.get(id(handler), str(handler))
            entry = {
                "event_type": type_name,
                "handler": hname,
                "index": i,
                "correlation_id": corr,
                "status": "STARTED",
                "error": None,
            }
            t0 = time.monotonic()
            try:
                handler(event)
                entry["status"] = "COMPLETED"
                entry["elapsed_ms"] = (time.monotonic() - t0) * 1000
            except Exception as e:
                entry["status"] = "EXCEPTION"
                entry["error"] = f"{type(e).__name__}: {e}"
                entry["traceback"] = traceback.format_exc()
                entry["elapsed_ms"] = (time.monotonic() - t0) * 1000
                self._trace.append(entry)
                logger.error(
                    "  [BUS] %s handler[%d] %s → EXCEPTION: %s",
                    type_name, i, hname, entry["error"],
                )
                # Re-raise para preservar comportamento original.
                raise
            self._trace.append(entry)
            logger.info(
                "  [BUS] %s handler[%d] %s → %s (%.1fms)",
                type_name, i, hname, entry["status"],
                entry.get("elapsed_ms", 0),
            )

        # Armazenar no EventStore (apenas OperationalEvents).
        from pipeline.events import TelemetryEvent
        if not isinstance(event, TelemetryEvent):
            self._store.append(event)


# -----------------------------------------------------------------------
# Instrumentação do LocalLLMProvider
# -----------------------------------------------------------------------
def instrument_provider(provider: LocalLLMProvider) -> dict:
    evidence: dict = {"inferences": []}
    original_infer = provider.infer
    original_build_user = provider._build_user_prompt
    original_parse = provider._parse_and_validate
    original_build_payload = provider._backend.build_payload
    original_send_request = provider._backend.send_request
    current: dict = {}

    def patched_build_user(context):
        prompt = original_build_user(context)
        current["user_prompt"] = prompt
        current["context"] = {
            "current_text": context.current_text,
            "recent_text": context.recent_text,
            "last_book": context.last_book,
            "last_chapter": context.last_chapter,
            "last_reference": context.last_reference,
            "sermon_book": context.sermon_book,
            "sermon_chapter": context.sermon_chapter,
            "sermon_theme": context.sermon_theme,
            "sermon_entities": list(context.sermon_entities) if context.sermon_entities else [],
            "sermon_confidence": context.sermon_confidence,
        }
        logger.info("  ── CONTEXTO ENVIADO ──")
        for k, v in current["context"].items():
            logger.info("    %s: %r", k, v)
        logger.info("  ── USER PROMPT ──")
        for line in prompt.splitlines():
            logger.info("    %s", line)
        return prompt

    def patched_build_payload(request):
        payload = original_build_payload(request)
        current["payload"] = payload
        current["endpoint"] = provider._backend.endpoint
        logger.info("  ── PAYLOAD HTTP ──")
        logger.info("    Endpoint: %s", current["endpoint"])
        payload_display = json.loads(json.dumps(payload))
        if "messages" in payload_display:
            for m in payload_display["messages"]:
                if m["role"] == "system":
                    m["content"] = "[SYSTEM PROMPT — %d chars]" % len(m["content"])
        for line in json.dumps(payload_display, indent=2, ensure_ascii=False).splitlines():
            logger.info("      %s", line)
        return payload

    def patched_send_request(payload, timeout_s):
        t0 = time.monotonic()
        resp = original_send_request(payload, timeout_s)
        elapsed = (time.monotonic() - t0) * 1000
        current["http_elapsed_ms"] = elapsed
        raw_content = getattr(resp, "content", "") or ""
        current["raw_response"] = raw_content
        logger.info("  ── RESPOSTA RAW ──")
        logger.info("    Tempo HTTP: %.0fms", elapsed)
        try:
            raw_json = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
            for line in json.dumps(raw_json, indent=2, ensure_ascii=False).splitlines():
                logger.info("    %s", line)
        except Exception:
            for line in raw_content.splitlines() if isinstance(raw_content, str) else [str(raw_content)]:
                logger.info("    %s", line)
        return resp

    def patched_parse(content):
        logger.info("  ── PARSER (entrada) ──")
        for line in content.splitlines():
            logger.info("      %s", line)
        result = original_parse(content)
        current["parsed_result"] = {
            "intent": result.intent,
            "candidates": [
                {"book": c.book, "chapter": c.chapter, "verse": c.verse,
                 "confidence": c.confidence, "reason": c.reason}
                for c in result.candidates
            ],
        }
        logger.info("  ── RESULTADO DO PARSER ──")
        logger.info("    intent: %s", result.intent)
        logger.info("    candidates: %d", len(result.candidates))
        for i, c in enumerate(result.candidates):
            logger.info("      [%d] book=%r chapter=%d verse=%d conf=%.2f reason=%r",
                        i, c.book, c.chapter, c.verse, c.confidence, c.reason)
        return result

    def patched_infer(context, timeout_ms=5000):
        current.clear()
        current["text"] = context.current_text
        logger.info("  ══ INFERÊNCIA INICIADA ══")
        logger.info("    Texto: %r", context.current_text[:80])
        t0 = time.monotonic()
        try:
            result = original_infer(context, timeout_ms)
            elapsed = (time.monotonic() - t0) * 1000
            current["total_inference_ms"] = result.inference_ms
            current["final_intent"] = result.intent
            current["final_candidates"] = [
                {"book": c.book, "chapter": c.chapter, "verse": c.verse,
                 "confidence": c.confidence, "reason": c.reason}
                for c in result.candidates
            ]
            logger.info("  ══ INFERÊNCIA CONCLUÍDA (%.0fms) ══", elapsed)
            logger.info("    intent: %s, candidates: %d", result.intent, len(result.candidates))
            evidence["inferences"].append(dict(current))
            return result
        except Exception as e:
            logger.info("  ══ INFERÊNCIA FALHOU: %s: %s ══", type(e).__name__, e)
            current["error"] = str(e)
            evidence["inferences"].append(dict(current))
            raise

    provider.infer = patched_infer
    provider._build_user_prompt = patched_build_user
    provider._parse_and_validate = patched_parse
    provider._backend.build_payload = patched_build_payload
    provider._backend.send_request = patched_send_request
    return evidence


# -----------------------------------------------------------------------
# Instrumentação do SermonMemoryEngine
# -----------------------------------------------------------------------
def instrument_sermon(engine: SermonMemoryEngine) -> dict:
    evidence: dict = {"calls": 0, "exceptions": []}
    original_on_partial = engine._on_partial

    def patched_on_partial(event):
        evidence["calls"] += 1
        logger.info("  [SERMON] _on_partial recebido (call #%d)", evidence["calls"])
        try:
            original_on_partial(event)
            logger.info("  [SERMON] _on_partial concluído")
        except Exception as e:
            evidence["exceptions"].append({
                "type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc(),
            })
            logger.error("  [SERMON] _on_partial EXCEÇÃO: %s: %s", type(e).__name__, e)
            raise

    engine._on_partial = patched_on_partial
    return evidence


# -----------------------------------------------------------------------
# FASE 5 — Teste do Ollama independente
# -----------------------------------------------------------------------
def test_ollama_independent():
    logger.info("")
    logger.info("=" * 70)
    logger.info("FASE 5 — TESTE DO OLLAMA INDEPENDENTE")
    logger.info("=" * 70)

    # 1. Verificar se Ollama está online.
    try:
        url = f"{_BASE_URL}/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") or m.get("model", "") for m in data.get("models", [])]
            logger.info("  Ollama ONLINE. Modelos disponíveis: %s", models)
            model_found = any(_MODEL.lower() in m.lower() for m in models)
            logger.info("  Modelo %s disponível: %s", _MODEL, model_found)
    except Exception as e:
        logger.error("  Ollama OFFLINE: %s: %s", type(e).__name__, e)
        return False

    # 2. Chamada mínima.
    logger.info("")
    logger.info("  >> Chamada mínima ao Ollama...")
    payload = {
        "model": _MODEL,
        "messages": [
            {"role": "user", "content": "Responda apenas: OK"},
        ],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "num_predict": 10},
    }
    t0 = time.monotonic()
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{_BASE_URL}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8")
        elapsed = (time.monotonic() - t0) * 1000
        resp_data = json.loads(raw)
        content = resp_data.get("message", {}).get("content", "")
        logger.info("  Resposta mínima: %r (%.0fms)", content, elapsed)
        logger.info("  HTTP status: 200")
    except socket.timeout:
        logger.error("  TIMEOUT após %.1fs", _TIMEOUT_S)
        return False
    except Exception as e:
        logger.error("  Erro: %s: %s", type(e).__name__, e)
        return False

    # 3. Chamada com o prompt real do LocalLLMProvider.
    logger.info("")
    logger.info("  >> Chamada com prompt real do sistema...")
    payload2 = {
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": "Texto: As minhas ovelhas ouvem a minha voz e elas me seguem"},
        ],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.1, "top_p": 0.9, "num_predict": 300},
    }
    t0 = time.monotonic()
    try:
        body = json.dumps(payload2).encode("utf-8")
        req = urllib.request.Request(
            f"{_BASE_URL}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8")
        elapsed = (time.monotonic() - t0) * 1000
        resp_data = json.loads(raw)
        content = resp_data.get("message", {}).get("content", "")
        thinking = resp_data.get("message", {}).get("thinking", "")
        logger.info("  Resposta prompt real (%.0fms):", elapsed)
        logger.info("    content: %r", content[:300])
        logger.info("    thinking (primeiros 200 chars): %r", thinking[:200] if thinking else "(vazio)")
        # Tentar parsear JSON.
        try:
            parsed = json.loads(content)
            logger.info("    JSON válido: %s", json.dumps(parsed, ensure_ascii=False, indent=2))
        except json.JSONDecodeError as je:
            logger.error("    JSON INVÁLIDO: %s", je)
            logger.error("    Conteúdo raw: %r", content)
    except socket.timeout:
        logger.error("  TIMEOUT após %.1fs", _TIMEOUT_S)
        return False
    except Exception as e:
        logger.error("  Erro: %s: %s", type(e).__name__, e)
        return False

    return True


# -----------------------------------------------------------------------
# FASE 4 — Teste da cadeia sem EventBus
# -----------------------------------------------------------------------
def test_semantic_engine_isolated(ollama_ok: bool):
    logger.info("")
    logger.info("=" * 70)
    logger.info("FASE 4 — TESTE DA CADEIA SEM EVENTBUS")
    logger.info("=" * 70)

    if not ollama_ok:
        logger.info("  PULADO — Ollama não disponível")
        return

    base_url_native = normalize_base_url_for_backend("ollama", f"{_BASE_URL}/v1")
    backend = create_backend(provider="ollama", base_url=base_url_native, model=_MODEL, api_key="ollama")
    provider = LocalLLMProvider(
        backend=backend, base_url=f"{_BASE_URL}/v1", model=_MODEL,
        temperature=0.1, max_tokens=300, request_timeout_s=_TIMEOUT_S,
        api_key="ollama", top_p=0.9, disable_thinking=True,
    )
    provider_evidence = instrument_provider(provider)

    ctx = SemanticContext(current_text="As minhas ovelhas ouvem a minha voz e elas me seguem", session_id="diag")
    logger.info("  >> Inferência direta (sem EventBus, sem debounce, sem filtros)...")
    try:
        result = provider.infer(ctx, timeout_ms=int(_TIMEOUT_S * 1000))
        logger.info("  Resultado: intent=%s, candidates=%d, ms=%d",
                    result.intent, len(result.candidates), result.inference_ms)
        for c in result.candidates:
            logger.info("    book=%r chapter=%d verse=%d conf=%.2f", c.book, c.chapter, c.verse, c.confidence)
    except Exception as e:
        logger.error("  FALHOU: %s: %s", type(e).__name__, e)


# -----------------------------------------------------------------------
# FASE 3 — Teste do EventBus com falha isolada
# -----------------------------------------------------------------------
def test_eventbus_exception_isolation():
    logger.info("")
    logger.info("=" * 70)
    logger.info("FASE 3 — TESTE DO EVENTBUS COM FALHA ISOLADA")
    logger.info("=" * 70)

    bus = InstrumentedEventBus()
    results: list[str] = []

    def handler_a(event):
        results.append("A")

    def handler_b_throws(event):
        results.append("B-start")
        raise ValueError("Simulated failure in handler B")

    def handler_c(event):
        results.append("C")

    bus.subscribe(SpeechPartial, handler_a)
    bus.subscribe(SpeechPartial, handler_b_throws)
    bus.subscribe(SpeechPartial, handler_c)

    meta = EventMetadata.for_initial(session_id="test", origin="test")
    event = SpeechPartial(meta=meta, text="teste", language="pt", confidence=0.9,
                          latency_ms=100, audio_duration_ms=1000, is_stable=False)

    logger.info("  Publicando SpeechPartial com 3 handlers (B lança exceção)...")
    try:
        bus.publish(event)
    except ValueError as e:
        logger.info("  Exceção propagada para o publicador: %s", e)

    logger.info("  Resultado da execução: %s", results)
    if "C" not in results:
        logger.error("  CONFIRMADO: handler C NÃO recebeu o evento devido a exceção em B")
        logger.error("  CAUSA RAIZ POTENCIAL: EventBus não isola exceções por subscriber")
    else:
        logger.info("  Handler C recebeu o evento — isolamento funciona")

    return "C" not in results


# -----------------------------------------------------------------------
# FASE 2 — Teste controlado A-E
# -----------------------------------------------------------------------
TESTES = [
    ("A", "IMPLÍCITA", "Quando Jesus fala sobre as suas ovelhas ouvirem a voz dele"),
    ("B", "EXPLÍCITA", "João 10:27"),
    ("C", "CONTEXTUAL", "As minhas ovelhas ouvem a minha voz e elas me seguem"),
    ("D", "NARRATIVA", "Quando Paulo fala que há tantas espécies de vozes no mundo"),
    ("E", "NÃO-BÍBLICA", "Vamos cantar agora o próximo louvor"),
]


def test_controlled_a_to_e(ollama_ok: bool):
    logger.info("")
    logger.info("=" * 70)
    logger.info("FASE 2 — TESTE CONTROLADO A-E (SEM microfone, SEM Whisper)")
    logger.info("=" * 70)

    if not ollama_ok:
        logger.info("  PULADO — Ollama não disponível")
        return []

    bus = InstrumentedEventBus()

    # 1. SermonMemoryEngine
    sermon_engine = SermonMemoryEngine(bus=bus, session_id="diag")
    sermon_evidence = instrument_sermon(sermon_engine)
    sermon_engine.start()
    logger.info("  SermonMemoryEngine iniciado.")

    # 2. ContextEngine
    ctx_engine = ContextEngine(
        history_fn=bus.history,
        sermon_context_fn=sermon_engine.get_context,
    )

    # 3. Cache
    cache = SemanticCache()

    # 4. LocalLLMProvider + OllamaBackend
    base_url_native = normalize_base_url_for_backend("ollama", f"{_BASE_URL}/v1")
    backend = create_backend(provider="ollama", base_url=base_url_native, model=_MODEL, api_key="ollama")
    provider = LocalLLMProvider(
        backend=backend, base_url=f"{_BASE_URL}/v1", model=_MODEL,
        temperature=0.1, max_tokens=300, request_timeout_s=_TIMEOUT_S,
        api_key="ollama", top_p=0.9, disable_thinking=True,
    )
    logger.info("  LocalLLMProvider criado. is_available: %s", provider.is_available())

    # Warmup
    logger.info("  >> Warmup do modelo...")
    warmup_ctx = SemanticContext(current_text="warmup", session_id="diag")
    try:
        wr = provider.infer(warmup_ctx, timeout_ms=int(_TIMEOUT_S * 1000))
        logger.info("  Warmup OK: intent=%s, ms=%d", wr.intent, wr.inference_ms)
    except Exception as e:
        logger.error("  Warmup FALHOU: %s: %s", type(e).__name__, e)

    provider_evidence = instrument_provider(provider)

    # 5. SemanticEngine
    engine = SemanticEngine(
        bus=bus, provider=provider, context_engine=ctx_engine,
        cache=cache, session_id="diag",
        debounce_ms=800, timeout_ms=int(_TIMEOUT_S * 1000),
        enabled=True,
        min_growth_chars=20, min_append_words=3, min_interval_ms=1000,
    )
    engine.start()
    logger.info("  SemanticEngine iniciado.")

    # 6. Searcher + ReferenceResolver
    resolver = None
    resolver_evidence = None
    try:
        from busca.searcher import Searcher
        from config.loader import load_books
        from config.models import SearchConfig
        book_table = load_books("config/books.json")
        search_config = SearchConfig(
            index_path="data/index", book_table_path="config/books.json",
            embedding_model="", embedding_dim=0, cache_dir="data/cache",
            fuzzy_threshold=70, min_confidence=0.0,
        )
        searcher = Searcher(config=search_config, book_table=book_table)
        resolver = ReferenceResolver(bus=bus, searcher=searcher, session_id="diag")
        resolver_evidence = {"resolutions": []}
        resolver.start()
        logger.info("  ReferenceResolver iniciado.")
    except Exception as e:
        logger.info("  ReferenceResolver não disponível: %s", e)

    # Capturar eventos
    telemetry: list = []
    resolutions: list = []
    references: list = []
    bus.subscribe(SemanticInferenceCompleted, lambda e: telemetry.append(e))
    if resolver:
        bus.subscribe(SemanticResolutionCompleted, lambda e: resolutions.append(e))
        bus.subscribe(ReferenceDetected, lambda e: references.append(e))

    # Executar testes
    all_results = []
    for test_id, test_type, frase in TESTES:
        logger.info("")
        logger.info("█" * 70)
        logger.info("█ TESTE %s (%s): %r", test_id, test_type, frase)
        logger.info("█" * 70)

        # Resetar estado do SemanticEngine
        with engine._lock:
            if engine._debounce_timer:
                engine._debounce_timer.cancel()
                engine._debounce_timer = None
            engine._pending_text = ""
            engine._pending_meta = None
            engine._last_inferred_text = ""
            engine._last_inference_monotonic = 0.0

        # Limpar cache entre testes
        cache._entries.clear() if hasattr(cache, "_entries") else None

        meta = EventMetadata.for_initial(session_id="diag", origin="StreamingSTTService")
        corr = meta.correlation_id
        logger.info("  Correlation ID: %s", corr)

        # Registrar estado antes
        sermon_calls_before = sermon_evidence["calls"]
        sermon_exceptions_before = len(sermon_evidence["exceptions"])
        provider_inferences_before = len(provider_evidence["inferences"])

        # Publicar SpeechPartial
        event = SpeechPartial(
            meta=meta, text=frase, language="pt", confidence=0.85,
            latency_ms=500, audio_duration_ms=6000, is_stable=False,
        )
        logger.info("  >> Publicando SpeechPartial...")
        bus.publish(event)

        # Aguardar inferência
        logger.info("  >> Aguardando 35s para inferência + resolução...")
        time.sleep(35)

        # Coletar resultados
        sermon_calls_after = sermon_evidence["calls"]
        sermon_exceptions_after = len(sermon_evidence["exceptions"])
        provider_inferences_after = len(provider_evidence["inferences"])

        # semantic_decision
        decision = {
            "test_id": test_id,
            "text": frase,
            "speech_partial_received": sermon_calls_after > sermon_calls_before,
            "sermon_received": sermon_calls_after > sermon_calls_before,
            "sermon_exception": sermon_exceptions_after > sermon_exceptions_before,
            "semantic_engine_received": provider_inferences_after > provider_inferences_before,
            "inference_started": provider_inferences_after > provider_inferences_before,
            "reason": "",
        }

        if provider_inferences_after > provider_inferences_before:
            inf = provider_evidence["inferences"][-1]
            decision["llm_called"] = True
            decision["raw_response"] = inf.get("raw_response", "")[:200]
            decision["json_parsed"] = "parsed_result" in inf
            decision["intent"] = inf.get("final_intent", "N/A")
            decision["candidates"] = inf.get("final_candidates", [])
            decision["inference_ms"] = inf.get("total_inference_ms", 0)
            decision["error"] = inf.get("error", "")

            if inf.get("final_intent") == "show_reference" and inf.get("final_candidates"):
                decision["intent_candidate_published"] = True
                # Verificar resolver
                if resolver_evidence is not None and len(resolutions) > 0:
                    r = resolutions[-1]
                    decision["resolver_received"] = True
                    decision["resolver_accepted"] = r.resolved
                    decision["resolver_reason"] = r.reason
                    if r.resolved:
                        decision["reference_detected"] = True
                        decision["chosen"] = f"{r.chosen_book} {r.chosen_chapter}:{r.chosen_verse}"
                    else:
                        decision["reference_detected"] = False
                else:
                    decision["resolver_received"] = False
                    decision["reference_detected"] = False
            else:
                decision["intent_candidate_published"] = False
                decision["reason"] = "llm_returned_none_or_no_candidates"
        else:
            decision["llm_called"] = False
            decision["reason"] = "semantic_engine_did_not_call_llm"
            # Verificar se SermonMemoryEngine teve exceção
            if sermon_exceptions_after > sermon_exceptions_before:
                decision["reason"] = "BLOCKED_BY_SERMON_EXCEPTION"
                exc = sermon_evidence["exceptions"][-1]
                decision["sermon_exception_detail"] = exc["message"]
            else:
                decision["reason"] = "FILTERED_OR_DEBOUNCED"

        # Classificar
        if decision.get("reference_detected"):
            decision["outcome"] = "EXECUTED"
        elif decision.get("llm_called") and decision.get("intent") == "none":
            decision["outcome"] = "EXECUTED"
        elif "BLOCKED" in decision.get("reason", ""):
            decision["outcome"] = "BLOCKED_BY_EXCEPTION"
        elif decision.get("llm_called") and decision.get("error"):
            decision["outcome"] = "PROVIDER_ERROR"
        elif not decision.get("llm_called"):
            decision["outcome"] = "FILTERED"
        else:
            decision["outcome"] = "UNKNOWN"

        all_results.append(decision)
        logger.info("")
        logger.info("  ── DECISÃO SEMÂNTICA ──")
        for k, v in decision.items():
            if k not in ("raw_response", "candidates"):
                logger.info("    %s: %s", k, v)

    # Parar
    engine.stop()
    sermon_engine.stop()
    if resolver:
        resolver.stop()

    return all_results


# -----------------------------------------------------------------------
# Relatório final
# -----------------------------------------------------------------------
def produce_report(ollama_ok: bool, eventbus_isolation_broken: bool, results: list):
    logger.info("")
    logger.info("=" * 70)
    logger.info("RELATÓRIO FINAL — Investigação da Cadeia Semântica")
    logger.info("=" * 70)

    logger.info("")
    logger.info("1. OLLAMA INDEPENDENTE")
    logger.info("   Status: %s", "ONLINE" if ollama_ok else "OFFLINE")

    logger.info("")
    logger.info("2. EVENTBUS ISOLAMENTO DE EXCEÇÕES")
    logger.info("   Isolamento quebrado: %s", eventbus_isolation_broken)

    logger.info("")
    logger.info("3. MATRIZ DE EVIDÊNCIAS (Testes A-E)")
    logger.info("-" * 70)
    logger.info("  | ID | SpeechPartial | Sermon | Sermon Exc | LLM Called | Intent | Candidates | Resolver | RefDetected | Outcome |")
    logger.info("  |----|---------------|--------|------------|------------|--------|------------|----------|-------------|---------|")
    for d in results:
        logger.info("  | %s  | %s            | %s      | %s         | %s         | %s     | %d          | %s       | %s          | %s      |",
                    d.get("test_id", "?"),
                    d.get("speech_partial_received", False),
                    d.get("sermon_received", False),
                    d.get("sermon_exception", False),
                    d.get("llm_called", False),
                    d.get("intent", "N/A"),
                    len(d.get("candidates", [])),
                    d.get("resolver_received", False),
                    d.get("reference_detected", False),
                    d.get("outcome", "UNKNOWN"),
                    )

    logger.info("")
    logger.info("4. CAUSA RAIZ")
    if eventbus_isolation_broken:
        logger.info("   ROOT_CAUSE_EVENTBUS confirmado: EventBus não isola exceções por subscriber.")
        logger.info("   Se SermonMemoryEngine lançar exceção, SemanticEngine NÃO recebe o evento.")
    else:
        logger.info("   EventBus isolamento não testado ou não confirmado.")

    if results:
        blocked = [r for r in results if r.get("outcome") == "BLOCKED_BY_EXCEPTION"]
        filtered = [r for r in results if r.get("outcome") == "FILTERED"]
        executed = [r for r in results if r.get("outcome") == "EXECUTED"]
        errors = [r for r in results if r.get("outcome") in ("PROVIDER_ERROR", "UNKNOWN")]
        logger.info("   Executados: %d, Filtrados: %d, Bloqueados: %d, Erros: %d",
                    len(executed), len(filtered), len(blocked), len(errors))


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------
def main():
    logger.info("=" * 70)
    logger.info("Investigação da Cadeia Semântica — LLM Not Triggering")
    logger.info("Data: %s", time.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("Modelo: %s (Ollama local)", _MODEL)
    logger.info("=" * 70)

    # FASE 5
    ollama_ok = test_ollama_independent()

    # FASE 4
    test_semantic_engine_isolated(ollama_ok)

    # FASE 3
    eventbus_broken = test_eventbus_exception_isolation()

    # FASE 2
    results = test_controlled_a_to_e(ollama_ok)

    # Relatório
    produce_report(ollama_ok, eventbus_broken, results)

    _fh.flush()
    _fh.close()
    print(f"Diagnóstico concluído. Saída em: {_LOG_FILE}")


if __name__ == "__main__":
    main()
