"""_demo_sprint21_1.py — Demo Sprint 21.1.1 — Hardening do LocalLLMProvider.

Demonstra:
  1. CapabilityCache — detecção por capacidade, não por nome.
  2. ThinkingSanitizer — remoção de blocos de thinking.
  3. Recovery — recupera JSON válido mesmo com thinking antes.
  4. Telemetria — métricas de detection, removed, recovered.

Sprint 21.1.1 — Hardening do LocalLLMProvider.
"""

from __future__ import annotations

import json
import logging

from semantic.local_provider import LocalLLMProvider
from semantic.thinking_sanitizer import ThinkingSanitizer
from semantic.capability_cache import (
    CapabilityCache,
    CapabilityState,
    is_think_rejection_error,
)
from semantic.types import SemanticContext

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")


def _make_context(text: str = "Jesus conversa com Nicodemos") -> SemanticContext:
    return SemanticContext(current_text=text)


def _print_header(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def main():
    print("="*70)
    print("  SPRINT 21.1.1 — HARDENING DO LOCALLLMPROVIDER — DEMONSTRAÇÃO")
    print("="*70)

    # ------------------------------------------------------------------
    # 1. ThinkingSanitizer (isolado)
    # ------------------------------------------------------------------
    _print_header("1. THINKINGSANITIZER (isolado)")
    sanitizer = ThinkingSanitizer()

    # Caso 1: bloco  /// + JSON válido.
    content1 = (
        " \u003Cthink\u003E\n"
        "Analisando o texto sobre Nicodemos...\n"
        "A referencia correta e Joao 3.\n"
        "\u003C/think\u003E\n"
        '{"intent":"show_reference","candidates":['
        '{"book":"Joao","chapter":3,"verse":0,"confidence":0.85,"reason":"Nicodemos"}'
        ']}'
    )
    result1 = sanitizer.sanitize(content1)
    print(f"  Input:  {repr(content1[:80])}...")
    print(f"  had_thinking: {result1.had_thinking}")
    print(f"  patterns: {result1.patterns_matched}")
    print(f"  cleaned: {repr(result1.content[:80])}...")
    print(f"  JSON recuperado: {result1.content.startswith('{')}")

    # Caso 2: sem thinking.
    content2 = '{"intent":"none","candidates":[]}'
    result2 = sanitizer.sanitize(content2)
    print(f"\n  Input (sem thinking): {repr(content2)}")
    print(f"  had_thinking: {result2.had_thinking}")
    print(f"  cleaned: {repr(result2.content)}")

    # ------------------------------------------------------------------
    # 2. CapabilityCache (isolado)
    # ------------------------------------------------------------------
    _print_header("2. CAPABILITYCACHE (isolado)")
    cache = CapabilityCache()
    print(f"  Estado inicial: {cache.get_state('think').value}")
    print(f"  should_try: {cache.should_try('think')}")

    # Simular detecção SUPPORTED.
    cache.record_detection("think", CapabilityState.SUPPORTED, detection_ms=42.5)
    print(f"\n  Após record_detection(SUPPORTED):")
    print(f"    state: {cache.get_state('think').value}")
    print(f"    should_try: {cache.should_try('think')}")
    print(f"    attempts: {cache.get_detection_attempts('think')}")

    # Tentar sobrescrever — idempotente.
    cache.record_detection("think", CapabilityState.UNSUPPORTED)
    print(f"\n  Após tentar sobrescrever com UNSUPPORTED (idempotente):")
    print(f"    state: {cache.get_state('think').value} (deve ser ainda SUPPORTED)")
    print(f"    attempts: {cache.get_detection_attempts('think')} (deve ser ainda 1)")

    # ------------------------------------------------------------------
    # 3. is_think_rejection_error (heurística)
    # ------------------------------------------------------------------
    _print_header("3. IS_THINK_REJECTION_ERROR (heurística)")
    test_cases = [
        (400, '{"error":"unknown field think"}', True),
        (422, "invalid parameter: think", True),
        (400, "unsupported argument think", True),
        (500, "internal server error", False),
        (200, "ok", False),
        (400, "invalid model name", False),
    ]
    for status, body, expected in test_cases:
        result = is_think_rejection_error(status, body)
        icon = "OK" if result == expected else "FAIL"
        print(f"  [{icon}] HTTP {status} {repr(body[:40])} → {result} (esperado {expected})")

    # ------------------------------------------------------------------
    # 4. LocalLLMProvider — Capability Detection (integração)
    # ------------------------------------------------------------------
    _print_header("4. LOCALLLMPROVIDER — CAPABILITY DETECTION (integração)")

    # Mock: backend que aceita think: false.
    class _AcceptBackend:
        def __init__(self):
            self.payloads = []
        def post(self, payload, timeout_s):
            self.payloads.append(payload)
            return json.dumps({"choices": [{"message": {"content": '{"intent":"none","candidates":[]}'}}]})

    backend_ok = _AcceptBackend()
    provider = LocalLLMProvider(model="my-custom-model-v2", disable_thinking=True, max_retries=0)
    provider._http_post = lambda p, t: backend_ok.post(p, t)

    print(f"  Modelo: {provider._model} (nome customizado — não está em nenhuma lista)")
    print(f"  Estado inicial: {provider._capability_cache.get_state('think').value}")

    # Primeira inferência — detecta SUPPORTED.
    provider.infer(_make_context())
    print(f"\n  Após 1a inferência:")
    print(f"    state: {provider._capability_cache.get_state('think').value}")
    print(f"    attempts: {provider._capability_cache.get_detection_attempts('think')}")
    print(f"    payload enviou think: {'think' in backend_ok.payloads[0]}")

    # Segunda inferência — usa cache, não testa novamente.
    provider.infer(_make_context())
    print(f"\n  Após 2a inferência (cache hit):")
    print(f"    attempts: {provider._capability_cache.get_detection_attempts('think')} (deve ser 1)")
    print(f"    payload enviou think: {'think' in backend_ok.payloads[1]}")

    # ------------------------------------------------------------------
    # 5. LocalLLMProvider — Recovery (sanitização + JSON recuperado)
    # ------------------------------------------------------------------
    _print_header("5. LOCALLLMPROVIDER — RECOVERY (sanitização + JSON recuperado)")

    # Mock: backend retorna resposta com bloco  /// antes do JSON.
    class _ThinkingBackend:
        def __init__(self, content):
            self.content = content
            self.payloads = []
        def post(self, payload, timeout_s):
            self.payloads.append(payload)
            return json.dumps({"choices": [{"message": {"content": self.content}}]})

    thinking_content = (
        " \u003Cthink\u003E\n"
        "Analisando: Jesus conversa com Nicodemos.\n"
        "Referencia: Joao 3.\n"
        "\u003C/think\u003E\n"
        '{"intent":"show_reference","candidates":['
        '{"book":"Joao","chapter":3,"verse":0,"confidence":0.85,"reason":"Nicodemos"}'
        ']}'
    )
    backend_thinking = _ThinkingBackend(thinking_content)
    provider2 = LocalLLMProvider(model="qwen3:8b", disable_thinking=False, max_retries=0)
    provider2._http_post = lambda p, t: backend_thinking.post(p, t)

    print(f"  Resposta do backend (com thinking):")
    print(f"    {repr(thinking_content[:100])}...")

    result = provider2.infer(_make_context())
    print(f"\n  Resultado após sanitização:")
    print(f"    intent: {result.intent}")
    print(f"    num_candidates: {len(result.candidates)}")
    if result.candidates:
        c = result.candidates[0]
        print(f"    book: {c.book}")
        print(f"    chapter: {c.chapter}")
        print(f"    confidence: {c.confidence}")

    m = provider2.metrics()
    print(f"\n  Métricas:")
    print(f"    total_thinking_removed: {m['total_thinking_removed']}")
    print(f"    total_thinking_recovered: {m['total_thinking_recovered']}")
    print(f"    total_thinking_violations: {m['total_thinking_violations']}")
    print(f"    total_success: {m['total_success']}")

    # ------------------------------------------------------------------
    # 6. Métricas finais
    # ------------------------------------------------------------------
    _print_header("6. MÉTRICAS FINAIS (provider 1 — capability detection)")
    m1 = provider.metrics()
    print(f"  provider: {m1['provider']}")
    print(f"  model: {m1['model']}")
    print(f"  backend_supports_thinking: {m1['backend_supports_thinking']}")
    print(f"  backend_capability_detection_ms: {m1['backend_capability_detection_ms']}")
    print(f"  capability_detection_attempts: {m1['capability_detection_attempts']}")
    print(f"  total_calls: {m1['total_calls']}")
    print(f"  total_success: {m1['total_success']}")
    print(f"  total_thinking_removed: {m1['total_thinking_removed']}")
    print(f"  total_thinking_recovered: {m1['total_thinking_recovered']}")

    # ------------------------------------------------------------------
    # Critérios de aceitação
    # ------------------------------------------------------------------
    _print_header("CRITÉRIOS DE ACEITAÇÃO")
    print(f"  Capability detection executada apenas uma vez:")
    print(f"    attempts == 1: {m1['capability_detection_attempts'] == 1}")
    print(f"  Cache funcionando:")
    print(f"    state == supported: {m1['backend_supports_thinking'] == 'supported'}")
    print(f"  Nenhuma dependência do nome do modelo:")
    print(f"    modelo customizado detectado: {m1['backend_supports_thinking'] == 'supported'}")
    print(f"  Blocos  /// removidos automaticamente:")
    print(f"    thinking_removed > 0: {m['total_thinking_removed'] > 0}")
    print(f"  JSON recuperado quando possível:")
    print(f"    thinking_recovered > 0: {m['total_thinking_recovered'] > 0}")
    print(f"  Nenhuma resposta válida descartada por conter thinking:")
    print(f"    result.intent == show_reference: {result.intent == 'show_reference'}")

    print(f"\n{'='*70}")
    print("  DEMONSTRAÇÃO CONCLUÍDA")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
