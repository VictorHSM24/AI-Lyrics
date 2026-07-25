"""Sprint 21.5.4 — Auditoria da Inferência Semântica (Teste Controlado).

Injeção controlada de texto, sem microfone/Whisper/StreamingSTT.
Valida a cadeia completa:
  SpeechPartial → SemanticEngine → PromptBuilder → LocalLLMProvider
  → Ollama → Resposta RAW → JSON Parser → IntentCandidate
  → ReferenceResolver

Para cada inferência registra:
  1. Entrada (correlation, texto bruto, normalizado)
  2. Contexto enviado (histórico, memória, janela)
  3. Prompt (SYSTEM + USER + final, sem truncar)
  4. Payload HTTP (JSON completo enviado ao Ollama)
  5. Resposta RAW (antes de qualquer processamento)
  6. Parser (JSON encontrado, erros, campos ausentes)
  7. IntentCandidate (todos os campos)
  8. ReferenceResolver (entrada, decisão, referência encontrada ou motivo)

Uso:
    python _diag_sprint21_5_4.py
"""
from __future__ import annotations

import json
import logging
import time
import threading
from typing import Any

_LOG_FILE = r"C:\Users\USER\Documents\AI Lyrics\_diag_sprint21_5_4_output.txt"
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
    IntentCandidate, ReferenceDetected, SemanticResolutionCompleted,
)
from pipeline.metadata import EventMetadata
from semantic.cache import SemanticCache
from semantic.context_engine import ContextEngine
from semantic.engine import SemanticEngine
from semantic.local_provider import LocalLLMProvider, _SYSTEM_PROMPT
from semantic.backend_factory import create_backend, normalize_base_url_for_backend
from semantic.types import SemanticResult, SemanticCandidate
from semantic.resolver import ReferenceResolver
from sermon import SermonMemoryEngine


# ---------------------------------------------------------------------
# Instrumentação do LocalLLMProvider
# ---------------------------------------------------------------------
def instrument_provider(provider: LocalLLMProvider) -> dict:
    """Envolve infer() e _build_user_prompt e _parse_and_validate com logs."""
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
            "sermon_entities": list(context.sermon_entities),
            "sermon_confidence": context.sermon_confidence,
        }
        logger.info("")
        logger.info("  ── CONTEXTO ENVIADO ──")
        for k, v in current["context"].items():
            logger.info("    %s: %r", k, v)
        logger.info("")
        logger.info("  ── USER PROMPT (completo) ──")
        for line in prompt.splitlines():
            logger.info("    %s", line)
        return prompt

    def patched_build_payload(request):
        payload = original_build_payload(request)
        current["payload"] = payload
        logger.info("")
        logger.info("  ── PAYLOAD HTTP (JSON completo enviado ao Ollama) ──")
        logger.info("    Endpoint: POST %s/api/chat", provider._backend._base_url)
        logger.info("    Payload:")
        # Logar payload formatado, mas truncar system_prompt para legibilidade
        payload_display = json.loads(json.dumps(payload))
        if "messages" in payload_display:
            for m in payload_display["messages"]:
                if m["role"] == "system":
                    m["content"] = "[SYSTEM PROMPT — ver abaixo, %d chars]" % len(m["content"])
        for line in json.dumps(payload_display, indent=2, ensure_ascii=False).splitlines():
            logger.info("      %s", line)
        logger.info("")
        logger.info("  ── SYSTEM PROMPT (completo, sem truncar) ──")
        for line in _SYSTEM_PROMPT.splitlines():
            logger.info("    %s", line)
        return payload

    def patched_send_request(payload, timeout_s):
        t0 = time.monotonic()
        resp = original_send_request(payload, timeout_s)
        elapsed = (time.monotonic() - t0) * 1000
        current["http_elapsed_ms"] = elapsed
        # Capturar resposta RAW.
        raw_content = ""
        if hasattr(resp, "content"):
            raw_content = resp.content
        elif isinstance(resp, dict):
            raw_content = json.dumps(resp, ensure_ascii=False)
        else:
            raw_content = str(resp)
        current["raw_response"] = raw_content
        logger.info("")
        logger.info("  ── RESPOSTA RAW (antes de qualquer processamento) ──")
        logger.info("    Tempo HTTP: %.0fms", elapsed)
        # Tentar formatar como JSON.
        try:
            raw_json = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
            for line in json.dumps(raw_json, indent=2, ensure_ascii=False).splitlines():
                logger.info("    %s", line)
        except Exception:
            for line in raw_content.splitlines() if isinstance(raw_content, str) else [str(raw_content)]:
                logger.info("    %s", line)
        return resp

    def patched_parse(content):
        logger.info("")
        logger.info("  ── PARSER (entrada para _parse_and_validate) ──")
        logger.info("    Conteúdo recebido pelo parser:")
        for line in content.splitlines():
            logger.info("      %s", line)
        try:
            result = original_parse(content)
            current["parsed_result"] = {
                "intent": result.intent,
                "candidates": [
                    {
                        "book": c.book,
                        "chapter": c.chapter,
                        "verse": c.verse,
                        "confidence": c.confidence,
                        "reason": c.reason,
                    }
                    for c in result.candidates
                ],
            }
            logger.info("")
            logger.info("  ── RESULTADO DO PARSER ──")
            logger.info("    intent: %s", result.intent)
            logger.info("    candidates: %d", len(result.candidates))
            for i, c in enumerate(result.candidates):
                logger.info("      [%d] book=%r chapter=%d verse=%d confidence=%.2f reason=%r",
                            i, c.book, c.chapter, c.verse, c.confidence, c.reason)
            return result
        except Exception as e:
            current["parse_error"] = str(e)
            logger.info("    ✗ PARSER ERRO: %s: %s", type(e).__name__, e)
            raise

    def patched_infer(context, timeout_ms=5000):
        corr = "n/a"
        current.clear()
        current["text"] = context.current_text
        logger.info("")
        logger.info("  ════════════════════════════════════════════════════")
        logger.info("  ══ INFERÊNCIA INICIADA ══")
        logger.info("  ══ Texto: %r", context.current_text[:80])
        logger.info("  ════════════════════════════════════════════════════")
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
            logger.info("")
            logger.info("  ══ INFERÊNCIA CONCLUÍDA (%.0fms) ══", elapsed)
            logger.info("    intent: %s", result.intent)
            logger.info("    candidates: %d", len(result.candidates))
            logger.info("    inference_ms: %d", result.inference_ms)
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


# ---------------------------------------------------------------------
# Instrumentação do ReferenceResolver
# ---------------------------------------------------------------------
def instrument_resolver(resolver: ReferenceResolver) -> dict:
    evidence: dict = {"resolutions": []}
    original_on_intent = resolver._on_intent_candidate

    def patched_on_intent(event: IntentCandidate):
        logger.info("")
        logger.info("  ── REFERENCE RESOLVER ──")
        logger.info("    Recebeu IntentCandidate:")
        logger.info("      intent: %s", event.intent)
        logger.info("      candidates_json: %s", event.candidates_json[:200])
        logger.info("      cached: %s", event.cached)
        logger.info("      context_hash: %s", event.context_hash[:16])
        try:
            result = original_on_intent(event)
            logger.info("    Resolver concluído.")
            evidence["resolutions"].append({
                "intent": event.intent,
                "candidates_json": event.candidates_json[:500],
            })
            return result
        except Exception as e:
            logger.info("    ✗ Resolver ERRO: %s: %s", type(e).__name__, e)
            raise

    resolver._on_intent_candidate = patched_on_intent
    return evidence


# ---------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------
TESTES = [
    ("IMPLÍCITA", "O Senhor é meu pastor."),
    ("IMPLÍCITA", "Porque Deus amou o mundo."),
    ("IMPLÍCITA", "Ainda que eu ande pelo vale da sombra da morte."),
    ("IMPLÍCITA", "Tudo posso naquele que me fortalece."),
    ("IMPLÍCITA", "A armadura de Deus."),
    ("CONTROLE EXPLÍCITA", "Provérbios 15:14"),
]


def main() -> None:
    logger.info("=" * 70)
    logger.info("Sprint 21.5.4 — Auditoria da Inferência Semântica")
    logger.info("Teste Controlado (sem microfone/Whisper/StreamingSTT)")
    logger.info("=" * 70)
    logger.info("Data: %s", time.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("Modelo: qwen3:8b-q4_K_M (Ollama local)")
    logger.info("")

    # -----------------------------------------------------------------
    # Configurar componentes reais
    # -----------------------------------------------------------------
    bus = PipelineEventBus()

    # 1. SermonMemoryEngine (real)
    sermon_engine = SermonMemoryEngine(bus=bus, session_id="diag")
    sermon_engine.start()
    logger.info("SermonMemoryEngine iniciado.")

    # 2. ContextEngine (real)
    ctx_engine = ContextEngine(
        history_fn=bus.history,
        sermon_context_fn=sermon_engine.get_context,
    )

    # 3. SemanticCache (real)
    cache = SemanticCache()

    # 4. LocalLLMProvider com OllamaBackend (real)
    base_url_native = normalize_base_url_for_backend("ollama", "http://localhost:11434/v1")
    backend = create_backend(
        provider="ollama",
        base_url=base_url_native,
        model="qwen3:8b-q4_K_M",
        api_key="ollama",
    )
    provider = LocalLLMProvider(
        backend=backend,
        base_url="http://localhost:11434/v1",
        model="qwen3:8b-q4_K_M",
        temperature=0.1,
        max_tokens=300,
        request_timeout_s=120,
        api_key="ollama",
        top_p=0.9,
        disable_thinking=True,
    )
    logger.info("LocalLLMProvider+OllamaBackend criado.")
    logger.info("  is_available: %s", provider.is_available())

    # Warmup do modelo (primeira chamada demora ~14s para carregar).
    logger.info("")
    logger.info(">> Warmup do modelo qwen3:8b-q4_K_M...")
    from semantic.types import SemanticContext
    warmup_ctx = SemanticContext(current_text="warmup", session_id="diag")
    try:
        wr = provider.infer(warmup_ctx, timeout_ms=120000)
        logger.info("   Warmup OK: intent=%s, ms=%d", wr.intent, wr.inference_ms)
    except Exception as e:
        logger.info("   Warmup FALHOU: %s: %s", type(e).__name__, e)

    # Instrumentar provider APÓS warmup (para não poluir logs de warmup).
    provider_evidence = instrument_provider(provider)

    # 5. SemanticEngine (real)
    engine = SemanticEngine(
        bus=bus, provider=provider, context_engine=ctx_engine,
        cache=cache, session_id="diag", debounce_ms=800,
        timeout_ms=120000,  # 120s para acomodar Ollama local frio
        enabled=True,
        min_growth_chars=20, min_append_words=3, min_interval_ms=1000,
    )
    engine.start()
    logger.info("SemanticEngine iniciado.")

    # 6. Searcher + ReferenceResolver (real)
    resolver_evidence = None
    resolver = None
    try:
        from busca.searcher import Searcher
        from config.loader import load_books
        from config.models import SearchConfig
        book_table = load_books("config/books.json")
        # SearchConfig mínimo.
        search_config = SearchConfig(
            index_path="data/index",
            book_table_path="config/books.json",
            embedding_model="",
            embedding_dim=0,
            cache_dir="data/cache",
            fuzzy_threshold=70,
            min_confidence=0.0,
        )
        searcher = Searcher(config=search_config, book_table=book_table)
        resolver = ReferenceResolver(
            bus=bus, searcher=searcher, session_id="diag",
        )
        resolver_evidence = instrument_resolver(resolver)
        resolver.start()
        logger.info("ReferenceResolver iniciado (com Searcher real).")
    except Exception as e:
        logger.info("⚠️ ReferenceResolver não pôde ser instanciado: %s", e)
        logger.info("   Teste continuará SEM ReferenceResolver.")

    # Capturar eventos de telemetria e resolução.
    telemetry: list[SemanticInferenceCompleted] = []
    resolutions: list[SemanticResolutionCompleted] = []
    references: list[ReferenceDetected] = []
    bus.subscribe(SemanticInferenceCompleted, lambda e: telemetry.append(e))
    if resolver:
        bus.subscribe(SemanticResolutionCompleted, lambda e: resolutions.append(e))
        bus.subscribe(ReferenceDetected, lambda e: references.append(e))

    # -----------------------------------------------------------------
    # Executar testes
    # -----------------------------------------------------------------
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

        # Simular publicação de SpeechPartial.
        meta = EventMetadata.for_initial(
            session_id="diag", origin="StreamingSTTService")
        corr = meta.correlation_id
        logger.info("")
        logger.info("  ── ENTRADA ──")
        logger.info("    Correlation ID: %s", corr)
        logger.info("    SpeechPartial recebido: True")
        logger.info("    Texto bruto: %r", frase)
        logger.info("    Texto normalizado: %r", frase.strip().lower())
        logger.info("    Thread: %s", threading.current_thread().name)
        logger.info("    Timestamp: %.3f", time.time())

        event = SpeechPartial(
            meta=meta, text=frase, language="pt", confidence=0.85,
            latency_ms=500, audio_duration_ms=6000, is_stable=False)
        bus.publish(event)

        # Aguardar inferência + debounce + resolução.
        logger.info("")
        logger.info("  >> Aguardando 30s para inferência + resolução...")
        time.sleep(30)

    # -----------------------------------------------------------------
    # Relatório final
    # -----------------------------------------------------------------
    logger.info("")
    logger.info("")
    logger.info("=" * 70)
    logger.info("RELATÓRIO FINAL — Sprint 21.5.4")
    logger.info("=" * 70)

    logger.info("")
    logger.info("1. RESUMO POR FRASE")
    logger.info("-" * 70)
    for i, (nome, frase) in enumerate(TESTES):
        inf = provider_evidence["inferences"][i] if i < len(provider_evidence["inferences"]) else {}
        logger.info("")
        logger.info("  Frase: %r (%s)", frase, nome)
        logger.info("    intent final: %s", inf.get("final_intent", "N/A"))
        cands = inf.get("final_candidates", [])
        logger.info("    candidates: %d", len(cands))
        for c in cands:
            logger.info("      book=%r chapter=%d verse=%d conf=%.2f reason=%r",
                        c["book"], c["chapter"], c["verse"], c["confidence"], c["reason"])
        logger.info("    inference_ms: %s", inf.get("total_inference_ms", "N/A"))
        if inf.get("parse_error"):
            logger.info("    parse_error: %s", inf["parse_error"])

    logger.info("")
    logger.info("2. TELEMETRIA (SemanticInferenceCompleted)")
    logger.info("-" * 70)
    logger.info("  Total: %d", len(telemetry))
    for t in telemetry:
        logger.info("    intent=%s cached=%s context=%r error=%r ms=%d",
                    t.intent, t.cached, t.context_text[:60], t.error, t.inference_ms)

    logger.info("")
    logger.info("3. REFERENCE RESOLVER")
    logger.info("-" * 70)
    if resolver_evidence:
        logger.info("  Resoluções processadas: %d", len(resolver_evidence["resolutions"]))
        logger.info("  SemanticResolutionCompleted: %d", len(resolutions))
        for r in resolutions:
            logger.info("    resolved=%s reason=%r chosen=%s %d:%d conf=%.2f",
                        r.resolved, r.reason, r.chosen_book, r.chosen_chapter,
                        r.chosen_verse, r.chosen_confidence)
        logger.info("  ReferenceDetected: %d", len(references))
        for r in references:
            logger.info("    book=%s chapter=%d verse=%d intent=%s",
                        r.book, r.chapter, r.verse_start, r.intent)
    else:
        logger.info("  ReferenceResolver não disponível.")

    logger.info("")
    logger.info("4. PRIMEIRO PONTO DE PERDA DE INFORMAÇÃO")
    logger.info("-" * 70)
    for i, (nome, frase) in enumerate(TESTES):
        inf = provider_evidence["inferences"][i] if i < len(provider_evidence["inferences"]) else {}
        intent = inf.get("final_intent", "N/A")
        cands = inf.get("final_candidates", [])
        raw = inf.get("raw_response", "")
        logger.info("")
        logger.info("  Frase: %r", frase)
        logger.info("    LLM respondeu intent=%s, candidates=%d", intent, len(cands))
        if intent == "none" and len(cands) == 0:
            # Verificar se a resposta RAW tem algo diferente.
            logger.info("    → LLM classificou como 'none' (sem referência)")
            logger.info("    → Possível perda: LLM não reconheceu a referência implícita")
        elif intent == "show_reference" and len(cands) > 0:
            logger.info("    → LLM identificou referência(s)")
            # Verificar se resolver aceitou.
            if resolver_evidence and i < len(resolutions):
                r = resolutions[i] if i < len(resolutions) else None
                if r:
                    if r.resolved:
                        logger.info("    → Resolver ACEITOU: %s %d:%d", r.chosen_book, r.chosen_chapter, r.chosen_verse)
                    else:
                        logger.info("    → Resolver REJEITOU: %r", r.reason)
                        logger.info("    → Possível perda: Searcher não validou a referência")

    logger.info("")
    logger.info("5. CONCLUSÃO")
    logger.info("-" * 70)
    total = len(TESTES)
    recognized = sum(1 for inf in provider_evidence["inferences"]
                     if inf.get("final_intent") == "show_reference" and inf.get("final_candidates"))
    logger.info("  Frases testadas: %d", total)
    logger.info("  Frases reconhecidas pelo LLM (intent=show_reference): %d", recognized)
    logger.info("  Frases NÃO reconhecidas (intent=none): %d", total - recognized)

    # Parar.
    engine.stop()
    sermon_engine.stop()
    if resolver:
        resolver.stop()
    _fh.flush()
    _fh.close()
    print(f"Diagnóstico concluído. Saída em: {_LOG_FILE}")


if __name__ == "__main__":
    main()
