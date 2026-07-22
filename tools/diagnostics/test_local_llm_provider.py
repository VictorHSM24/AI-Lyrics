"""Sprint 21.2 — Diagnóstico Isolado do LocalLLMProvider.

Executa o LocalLLMProvider exatamente como em produção, sem passar pelo
StreamingSTT, EventBus, SemanticEngine, Frontend, Holyrics ou
ReferenceResolver.

Para cada consulta registra:
  1. Prompt completo enviado ao modelo.
  2. Payload HTTP (JSON enviado ao Ollama).
  3. Tempo da requisição (HTTP e total).
  4. Resposta HTTP (status code, tempo, mensagens de erro).
  5. Resposta bruta do modelo (antes de qualquer sanitização).
  6. Resultado após o ThinkingSanitizer.
  7. JSON extraído.
  8. Resultado final retornado pelo LocalLLMProvider.
  9. Classificação da falha (se houver).

Restrições (Sprint 21.2):
  - NÃO corrigir nada.
  - NÃO alterar prompts, timeout, retries, parser, sanitizer, SemanticEngine.
  - Objetivo: apenas produzir evidências.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Any

# Garantir que o diretório raiz do projeto está no sys.path para imports.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Desativar AI_LYRICS_TEST_MODE para usar o provider real.
os.environ.pop("AI_LYRICS_TEST_MODE", None)

logger = logging.getLogger("sprint21_2")


# ---------------------------------------------------------------------------
# Estruturas de evidência
# ---------------------------------------------------------------------------


@dataclass
class QueryEvidence:
    """Evidência coletada para uma consulta individual."""
    query: str
    expected: str  # referência esperada (para comparação)

    # Prompt + payload enviado.
    system_prompt: str = ""
    user_prompt: str = ""
    payload_sent: dict[str, Any] = field(default_factory=dict)
    think_in_payload: bool = False

    # Resposta HTTP.
    http_status: int = 0
    http_error: str = ""
    http_response_raw: str = ""
    http_time_ms: float = 0.0

    # Resposta bruta do modelo (antes de sanitização).
    raw_content: str = ""

    # Após ThinkingSanitizer.
    sanitized_content: str = ""
    had_thinking: bool = False
    thinking_patterns: tuple[str, ...] = ()

    # JSON extraído.
    json_extracted: bool = False
    json_parse_error: str = ""
    json_data: dict[str, Any] = field(default_factory=dict)

    # Resultado final retornado pelo provider.
    final_intent: str = ""
    final_candidates: list[dict[str, Any]] = field(default_factory=list)
    final_inference_ms: float = 0.0

    # Classificação.
    success: bool = False
    failure_category: str = ""  # timeout, http, json, schema, sanitizer, parser, prompt, llm, none
    failure_detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Truncar campos longos para o relatório.
        for k in ("system_prompt", "user_prompt", "http_response_raw",
                  "raw_content", "sanitized_content"):
            if isinstance(d.get(k), str) and len(d[k]) > 500:
                d[k] = d[k][:500] + "... [TRUNCATED]"
        return d


# ---------------------------------------------------------------------------
# Provider instrumentado (wrapper não-intrusivo).
# ---------------------------------------------------------------------------


class InstrumentedLocalLLMProvider:
    """Wrapper do LocalLLMProvider que captura evidências sem alterar código.

    Sprint 21.3: intercepta a interface LLMBackend injetada.
    Intercepta:
      - backend.build_payload: captura payload enviado.
      - backend.send_request: captura status, tempo, resposta bruta.
      - backend.parse_response: captura content extraído.
      - _sanitizer.sanitize: captura resultado da sanitização.
      - _parse_and_validate: captura resultado do parser.
      - infer: captura resultado final.
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider
        self._evidence: QueryEvidence | None = None
        self._t0_http: float = 0.0

        # Sprint 21.3 — interceptar o backend injetado.
        backend = provider._backend
        self._backend = backend
        self._orig_build_payload = backend.build_payload
        self._orig_send_request = backend.send_request
        self._orig_parse_response = backend.parse_response
        self._orig_sanitizer_sanitize = provider._sanitizer.sanitize
        self._orig_parse_and_validate = provider._parse_and_validate

        # Substituir por versões instrumentadas.
        backend.build_payload = self._inst_build_payload
        backend.send_request = self._inst_send_request
        backend.parse_response = self._inst_parse_response
        provider._sanitizer.sanitize = self._inst_sanitizer_sanitize
        provider._parse_and_validate = self._inst_parse_and_validate

    def start_query(self, query: str, expected: str) -> None:
        self._evidence = QueryEvidence(query=query, expected=expected)

    def get_evidence(self) -> QueryEvidence | None:
        return self._evidence

    # --- Instrumentações ---

    def _inst_build_payload(self, request: Any) -> dict[str, Any]:
        payload = self._orig_build_payload(request)
        if self._evidence is not None:
            # Capturar prompts vindos do request padronizado.
            self._evidence.system_prompt = request.system_prompt
            self._evidence.user_prompt = request.user_prompt
            # Cópia rasa para não capturar bytes.
            self._evidence.payload_sent = dict(payload)
            self._evidence.think_in_payload = "think" in payload
        return payload

    def _inst_send_request(self, payload: dict[str, Any], timeout_s: float) -> Any:
        self._t0_http = time.monotonic()
        try:
            backend_resp = self._orig_send_request(payload, timeout_s)
            elapsed_ms = (time.monotonic() - self._t0_http) * 1000.0
            if self._evidence is not None:
                self._evidence.http_status = backend_resp.http_status
                self._evidence.http_response_raw = backend_resp.raw_response
                self._evidence.http_time_ms = elapsed_ms
            return backend_resp
        except Exception as e:
            elapsed_ms = (time.monotonic() - self._t0_http) * 1000.0
            if self._evidence is not None:
                self._evidence.http_time_ms = elapsed_ms
                self._evidence.http_error = str(e)
                # Extrair status code de SemanticError se presente.
                import re
                m = re.search(r"HTTP (\d+)", str(e))
                if m:
                    self._evidence.http_status = int(m.group(1))
                else:
                    self._evidence.http_status = 0
            raise

    def _inst_parse_response(self, raw: str) -> Any:
        backend_resp = self._orig_parse_response(raw)
        if self._evidence is not None:
            self._evidence.raw_content = backend_resp.content
            if not backend_resp.content:
                if not self._evidence.failure_category:
                    self._evidence.failure_category = "http"
                    self._evidence.failure_detail = "empty content from backend"
        return backend_resp

    def _inst_sanitizer_sanitize(self, content: str) -> Any:
        result = self._orig_sanitizer_sanitize(content)
        if self._evidence is not None:
            self._evidence.sanitized_content = result.content
            self._evidence.had_thinking = result.had_thinking
            self._evidence.thinking_patterns = result.patterns_matched
        return result

    def _inst_parse_and_validate(self, content: str) -> Any:
        result = self._orig_parse_and_validate(content)
        if self._evidence is not None:
            # Tentar parsear o JSON manualmente para registrar o resultado.
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines).strip()
            try:
                data = json.loads(text)
                self._evidence.json_extracted = True
                self._evidence.json_data = data if isinstance(data, dict) else {}
            except json.JSONDecodeError as e:
                self._evidence.json_extracted = False
                self._evidence.json_parse_error = str(e)
        return result

    def restore(self) -> None:
        """Restaura os métodos originais do backend/provider."""
        b = self._backend
        b.build_payload = self._orig_build_payload
        b.send_request = self._orig_send_request
        b.parse_response = self._orig_parse_response
        self._provider._sanitizer.sanitize = self._orig_sanitizer_sanitize
        self._provider._parse_and_validate = self._orig_parse_and_validate


# ---------------------------------------------------------------------------
# Consultas de teste (10 consultas)
# ---------------------------------------------------------------------------


# Cada consulta: (descrição, texto_falado, referência_esperada)
TEST_QUERIES: list[tuple[str, str, str]] = [
    ("João 3:16 (explícita)",
     "João 3:16",
     "João 3:16"),
    ("Porque Deus amou o mundo",
     "Porque Deus amou o mundo de tal maneira.",
     "João 3:16"),
    ("Tudo posso naquele que me fortalece",
     "Tudo posso naquele que me fortalece.",
     "Filipenses 4:13"),
    ("O Senhor é o meu pastor",
     "O Senhor é o meu pastor.",
     "Salmos 23"),
    ("Ainda que eu ande pelo vale",
     "Ainda que eu ande pelo vale da sombra da morte.",
     "Salmos 23:4"),
    ("No princípio criou Deus",
     "No princípio criou Deus.",
     "Gênesis 1:1"),
    ("A passagem do bom pastor",
     "A passagem do bom pastor.",
     "João 10"),
    ("O filho pródigo",
     "O filho pródigo.",
     "Lucas 15"),
    ("Nicodemos",
     "Nicodemos.",
     "João 3"),
    ("A armadura de Deus",
     "A armadura de Deus.",
     "Efésios 6"),
]


# ---------------------------------------------------------------------------
# Classificação de falhas
# ---------------------------------------------------------------------------


def classify_failure(ev: QueryEvidence) -> tuple[str, str]:
    """Classifica a falha com base nas evidências coletadas.

    Categorias:
      - timeout: HTTP timeout excedido.
      - http: erro HTTP (4xx/5xx) ou estrutura inválida.
      - json: JSON inválido após sanitização.
      - schema: JSON válido mas schema incorreto (intent inválido, etc.).
      - sanitizer: sanitizer removeu conteúdo indevido.
      - parser: parser rejeitou JSON válido.
      - prompt: prompt inadequado (resposta coerente com prompt mas errada).
      - llm: LLM respondeu incorretamente (erro semântico).
      - none: sem falha.
    """
    # Sem falha se intent != none e há candidatos.
    if ev.final_intent == "show_reference" and ev.final_candidates:
        return ("none", "")

    # 1. Timeout?
    if ev.http_status == 0 and "timeout" in ev.http_error.lower():
        return ("timeout", f"HTTP timeout: {ev.http_error}")
    if ev.http_status == 0 and ev.http_time_ms > 0 and not ev.http_response_raw:
        # Sem resposta — provável timeout.
        return ("timeout", f"no response after {ev.http_time_ms:.0f}ms: {ev.http_error}")

    # 2. Erro HTTP?
    if ev.http_status >= 400:
        return ("http", f"HTTP {ev.http_status}: {ev.http_error[:200]}")
    if ev.http_status == 0 and ev.http_error and not ev.raw_content:
        return ("http", f"HTTP error: {ev.http_error[:200]}")

    # 3. Estrutura HTTP inválida (sem choices[0].message.content)?
    if not ev.raw_content and ev.http_status == 200:
        return ("http", "response had no choices[0].message.content")

    # 4. Sanitizer removeu algo indevido?
    # Se o conteúdo bruto tinha JSON válido mas o sanitizer removeu, é falha.
    if ev.had_thinking and ev.raw_content:
        # Verificar se o JSON estava no conteúdo bruto.
        raw_has_json = _try_extract_json(ev.raw_content)
        if raw_has_json and not ev.json_extracted:
            return ("sanitizer",
                    f"sanitizer removed JSON content (patterns={ev.thinking_patterns})")

    # 5. JSON inválido após sanitização?
    if not ev.json_extracted and ev.sanitized_content:
        return ("json", f"invalid JSON after sanitization: {ev.json_parse_error}")

    # 6. Schema inválido?
    if ev.json_extracted and ev.json_data:
        intent = ev.json_data.get("intent", "none")
        if intent not in ("show_reference", "none"):
            return ("schema", f"invalid intent: {intent!r}")
        if intent == "none":
            # LLM disse none — pode ser prompt inadequado ou LLM não reconheceu.
            # Verificar se a referência esperada é clara.
            return ("llm", "LLM returned intent=none (did not recognize reference)")

    # 7. Parser rejeitou JSON válido?
    if ev.json_extracted and ev.json_data.get("intent") == "show_reference":
        raw_cands = ev.json_data.get("candidates", [])
        if not isinstance(raw_cands, list) or not raw_cands:
            return ("schema", "intent=show_reference but candidates empty/invalid")
        # Parser aceitou mas resultado final é none?
        if ev.final_intent == "none":
            return ("parser", "parser rejected valid candidates")

    # 8. Prompt inadequado?
    # Se a resposta do LLM tem candidates mas o livro/capítulo está errado,
    # é falha do LLM (não do prompt — o prompt é genérico).
    if ev.final_intent == "show_reference" and ev.final_candidates:
        first = ev.final_candidates[0] if ev.final_candidates else {}
        got_ref = f"{first.get('book','')} {first.get('chapter','')}".strip()
        # Comparar com esperado de forma fuzzy.
        if not _refs_match(got_ref, ev.expected):
            return ("llm", f"LLM returned wrong reference: got {got_ref!r}, expected {ev.expected!r}")
        return ("none", "")

    # Caso padrão.
    return ("llm", f"unexpected state: intent={ev.final_intent!r}")


def _try_extract_json(text: str) -> bool:
    """Tenta encontrar JSON válido no texto."""
    text = text.strip()
    # Procurar primeiro { ... }.
    start = text.find("{")
    if start < 0:
        return False
    # Tentar parsear do início do {.
    try:
        json.loads(text[start:])
        return True
    except json.JSONDecodeError:
        pass
    # Tentar encontrar o último } e parsear o substring.
    end = text.rfind("}")
    if end > start:
        try:
            json.loads(text[start:end+1])
            return True
        except json.JSONDecodeError:
            pass
    return False


def _refs_match(got: str, expected: str) -> bool:
    """Comparação fuzzy de referências (case-insensitive, sem acentos)."""
    import unicodedata
    def normalize(s: str) -> str:
        s = unicodedata.normalize("NFKD", s.lower())
        return "".join(c for c in s if not unicodedata.combining(c)).strip()
    g = normalize(got)
    e = normalize(expected)
    # Match se um contém o outro.
    return g in e or e in g or g == e


# ---------------------------------------------------------------------------
# Instanciação do provider (reusa config do projeto)
# ---------------------------------------------------------------------------


def build_provider_from_config() -> tuple[Any, Any]:
    """Instancia o LocalLLMProvider exatamente como o CompositionRoot.

    Sprint 21.3: usa a Factory para criar o backend correto (OllamaBackend
    com endpoint nativo /api/chat).
    Retorna (provider, semantic_config).
    """
    from config.loader import load_config
    from semantic import LocalLLMProvider, create_backend
    from semantic.backend_factory import normalize_base_url_for_backend

    config = load_config("config/config.yaml")
    if config.semantic is None:
        raise RuntimeError("config.semantic is None — SemanticEngine not configured")
    sc = config.semantic
    if sc.provider != "ollama":
        raise RuntimeError(f"config.semantic.provider={sc.provider!r} — expected 'ollama'")
    oc = sc.ollama
    # Sprint 21.3 — criar backend via Factory.
    base_url_native = normalize_base_url_for_backend("ollama", oc.base_url)
    backend = create_backend(
        provider="ollama",
        base_url=base_url_native,
        model=oc.model,
        api_key=oc.api_key,
    )
    provider = LocalLLMProvider(
        backend=backend,
        base_url=oc.base_url,
        model=oc.model,
        temperature=oc.temperature,
        max_tokens=oc.max_tokens,
        request_timeout_s=oc.timeout_seconds,
        api_key=oc.api_key,
        top_p=oc.top_p,
        disable_thinking=oc.disable_thinking,
    )
    return provider, sc


# ---------------------------------------------------------------------------
# Execução de uma consulta isolada
# ---------------------------------------------------------------------------


def run_single_query(
    provider: Any,
    inst: InstrumentedLocalLLMProvider,
    description: str,
    text: str,
    expected: str,
    timeout_ms: int,
) -> QueryEvidence:
    """Executa uma consulta isolada e retorna evidência completa."""
    from semantic.types import SemanticContext

    inst.start_query(query=description, expected=expected)
    ev = inst.get_evidence()
    assert ev is not None

    context = SemanticContext(
        current_text=text,
        recent_text="",
        last_book="",
        last_chapter=0,
        last_reference="",
    )

    t0 = time.monotonic()
    try:
        result = provider.infer(context, timeout_ms=timeout_ms)
        ev.final_intent = result.intent
        ev.final_candidates = [
            {
                "book": c.book,
                "chapter": c.chapter,
                "verse": c.verse,
                "confidence": c.confidence,
                "reason": c.reason,
            }
            for c in result.candidates
        ]
        ev.final_inference_ms = result.inference_ms
        if result.intent == "show_reference" and result.candidates:
            ev.success = True
    except Exception as e:
        ev.final_intent = "none"
        ev.final_inference_ms = (time.monotonic() - t0) * 1000.0
        if not ev.failure_category:
            ev.failure_category = "http"
            ev.failure_detail = f"exception in infer(): {e}"

    # Classificar falha se não foi sucesso.
    if not ev.success:
        cat, detail = classify_failure(ev)
        ev.failure_category = cat
        ev.failure_detail = detail
        # Reavaliar sucesso (pode ter acertado a referência mesmo com categoria != none).
        if cat == "none":
            ev.success = True

    return ev


# ---------------------------------------------------------------------------
# Impressão de evidências
# ---------------------------------------------------------------------------


def _bar(s: str, char: str = "=", width: int = 78) -> str:
    return char * width


def print_evidence(ev: QueryEvidence, idx: int, total: int) -> None:
    """Imprime a evidência de uma consulta de forma legível."""
    print(f"\n{_bar('', '=')}")
    print(f"  CONSULTA {idx}/{total}: {ev.query}")
    print(f"  Texto falado: {ev.expected!r}")
    print(f"  Referência esperada: {ev.expected}")
    print(f"  Status: {'SUCESSO' if ev.success else 'FALHA'} "
          f"({ev.failure_category})")
    print(_bar('', '-'))

    # 1. Prompt enviado.
    print(f"\n  [1] PROMPT ENVIADO AO MODELO:")
    print(f"      System prompt (primeiros 200 chars):")
    print(f"      {ev.system_prompt[:200]!r}...")
    print(f"      User prompt: {ev.user_prompt!r}")

    # 2. Payload HTTP.
    print(f"\n  [2] PAYLOAD HTTP (JSON enviado ao Ollama):")
    payload_str = json.dumps(ev.payload_sent, ensure_ascii=False, indent=2)
    for line in payload_str.split("\n"):
        print(f"      {line}")
    print(f"      think in payload: {ev.think_in_payload}")

    # 3. Tempo da requisição.
    print(f"\n  [3] TEMPO DA REQUISIÇÃO:")
    print(f"      HTTP time: {ev.http_time_ms:.1f}ms")
    print(f"      Inference total (provider): {ev.final_inference_ms:.1f}ms")

    # 4. Resposta HTTP.
    print(f"\n  [4] RESPOSTA HTTP:")
    print(f"      Status code: {ev.http_status}")
    if ev.http_error:
        print(f"      Error: {ev.http_error[:300]!r}")
    raw_resp = ev.http_response_raw
    if len(raw_resp) > 400:
        raw_resp = raw_resp[:400] + "... [TRUNCATED]"
    print(f"      Body (primeiros 400 chars): {raw_resp!r}")

    # 5. Resposta bruta do modelo.
    print(f"\n  [5] RESPOSTA BRUTA DO MODELO (antes de sanitização):")
    raw_content = ev.raw_content
    if len(raw_content) > 500:
        raw_content = raw_content[:500] + "... [TRUNCATED]"
    print(f"      {raw_content!r}")

    # 6. Após ThinkingSanitizer.
    print(f"\n  [6] RESULTADO APÓS THINKINGSANITIZER:")
    print(f"      had_thinking: {ev.had_thinking}")
    print(f"      patterns: {ev.thinking_patterns}")
    sanitized = ev.sanitized_content
    if len(sanitized) > 500:
        sanitized = sanitized[:500] + "... [TRUNCATED]"
    print(f"      cleaned content: {sanitized!r}")

    # 7. JSON extraído.
    print(f"\n  [7] JSON EXTRAÍDO:")
    print(f"      json_extracted: {ev.json_extracted}")
    if ev.json_parse_error:
        print(f"      parse_error: {ev.json_parse_error}")
    if ev.json_data:
        print(f"      data: {json.dumps(ev.json_data, ensure_ascii=False)}")

    # 8. Resultado final.
    print(f"\n  [8] RESULTADO FINAL DO LOCALLLMPROVIDER:")
    print(f"      intent: {ev.final_intent!r}")
    print(f"      candidates: {json.dumps(ev.final_candidates, ensure_ascii=False)}")

    # 9. Classificação.
    print(f"\n  [9] CLASSIFICAÇÃO DA FALHA:")
    print(f"      category: {ev.failure_category}")
    print(f"      detail: {ev.failure_detail}")


def print_summary(evidences: list[QueryEvidence]) -> None:
    """Imprime um resumo tabular de todas as consultas."""
    print(f"\n{_bar('', '=')}")
    print("  RESUMO DE TODAS AS CONSULTAS")
    print(_bar('', '='))
    print(f"  {'#':>2}  {'Consulta':<40}  {'Status':<8}  {'Categoria':<12}  {'Intent':<15}  {'Ref obtida':<25}")
    print(f"  {_bar('', '-')}")
    for i, ev in enumerate(evidences, 1):
        status = "OK" if ev.success else "FAIL"
        ref = ""
        if ev.final_candidates:
            c = ev.final_candidates[0]
            ref = f"{c.get('book','')} {c.get('chapter','')}".strip()
        print(f"  {i:>2}  {ev.query[:40]:<40}  {status:<8}  {ev.failure_category:<12}  {ev.final_intent:<15}  {ref:<25}")

    # Estatísticas.
    total = len(evidences)
    successes = sum(1 for ev in evidences if ev.success)
    failures = total - successes
    print(f"\n  Total: {total}  Sucessos: {successes}  Falhas: {failures}")

    # Distribuição de categorias.
    cats: dict[str, int] = {}
    for ev in evidences:
        cats[ev.failure_category] = cats.get(ev.failure_category, 0) + 1
    print(f"\n  Distribuição por categoria:")
    for cat, count in sorted(cats.items()):
        print(f"    {cat}: {count}")

    # Tempos.
    http_times = [ev.http_time_ms for ev in evidences if ev.http_time_ms > 0]
    if http_times:
        print(f"\n  Tempo HTTP (ms):")
        print(f"    min: {min(http_times):.1f}")
        print(f"    max: {max(http_times):.1f}")
        print(f"    avg: {sum(http_times)/len(http_times):.1f}")
        print(f"    >5s: {sum(1 for t in http_times if t > 5000)}")
        print(f"    >10s: {sum(1 for t in http_times if t > 10000)}")
        print(f"    >15s: {sum(1 for t in http_times if t > 15000)}")

    # Timeout config vs tempos.
    timeouts = [ev for ev in evidences if ev.failure_category == "timeout"]
    if timeouts:
        print(f"\n  Timeouts: {len(timeouts)}/{total}")
        for ev in timeouts:
            print(f"    {ev.query}: {ev.http_time_ms:.1f}ms ({ev.failure_detail[:100]})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Executa o diagnóstico isolado do LocalLLMProvider."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    print(_bar('', '='))
    print("  SPRINT 21.2 — DIAGNÓSTICO ISOLADO DO LOCALLLMPROVIDER")
    print(_bar('', '='))

    # Carregar config e instanciar provider.
    try:
        provider, sc = build_provider_from_config()
    except Exception as e:
        print(f"\n  ERRO ao instanciar provider: {e}")
        return 1

    print(f"\n  Provider: {provider.name}")
    print(f"  Model: {provider.model_name}")
    print(f"  Backend: {provider.backend.name}")
    print(f"  Backend endpoint: {provider.backend.endpoint}")
    print(f"  Base URL: {provider._base_url}")
    print(f"  Request timeout (HTTP): {provider._request_timeout_s}s")
    print(f"  Engine timeout (infer): {sc.timeout_ms}ms")
    print(f"  disable_thinking: {provider._disable_thinking}")
    print(f"  Capability state: {provider._capability_cache.get_state('think').value}")
    print(f"  Supports think parameter: {provider.backend.supports_think_parameter()}")

    # Health check.
    print(f"\n  Health check (is_available)...")
    t0 = time.monotonic()
    available = provider.is_available()
    hc_ms = (time.monotonic() - t0) * 1000.0
    print(f"    is_available: {available} ({hc_ms:.1f}ms)")
    if not available:
        print(f"\n  PROVIDER NÃO DISPONÍVEL — abortando.")
        return 2

    # Instrumentar.
    inst = InstrumentedLocalLLMProvider(provider)

    # Executar consultas.
    evidences: list[QueryEvidence] = []
    timeout_ms = sc.timeout_ms
    total = len(TEST_QUERIES)
    print(f"\n  Executando {total} consultas isoladas (timeout_ms={timeout_ms})...")

    for i, (desc, text, expected) in enumerate(TEST_QUERIES, 1):
        print(f"\n  [{i}/{total}] {desc}: {text!r}")
        try:
            ev = run_single_query(provider, inst, desc, text, expected, timeout_ms)
        except Exception as e:
            # Capturar erro inesperado.
            ev = inst.get_evidence() or QueryEvidence(query=desc, expected=expected)
            ev.failure_category = "http"
            ev.failure_detail = f"unexpected exception: {e}"
        evidences.append(ev)
        print_evidence(ev, i, total)

    # Restaurar provider.
    inst.restore()

    # Salvar evidências em JSON.
    out_path = os.path.join(PROJECT_ROOT, "tools", "diagnostics",
                            "sprint21_2_evidence.json")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                [ev.to_dict() for ev in evidences],
                f, ensure_ascii=False, indent=2,
            )
        print(f"\n  Evidências salvas em: {out_path}")
    except Exception as e:
        print(f"\n  AVISO: não foi possível salvar evidências: {e}")

    # Resumo.
    print_summary(evidences)

    print(f"\n{_bar('', '=')}")
    print("  DIAGNÓSTICO CONCLUÍDO")
    print(_bar('', '='))
    return 0


if __name__ == "__main__":
    sys.exit(main())
