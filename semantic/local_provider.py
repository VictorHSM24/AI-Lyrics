"""semantic/local_provider.py — Provider LLM local (Sprint 20).

Responsabilidade:
  - Implementar SemanticProvider via HTTP para servidor local compatível
    com a API OpenAI (/v1/chat/completions).
  - Funciona com: Ollama (http://localhost:11434/v1), LM Studio
    (http://localhost:1234/v1), llama.cpp server, vLLM, etc.
  - Forçar saída em JSON estruturado (schema SemanticResult).
  - Validar rigorosamente o schema (Etapa 7 — Segurança).

Arquitetura:
  - Usa urllib (stdlib) para evitar dependência de requests/openai.
  - Prompt system instrui o modelo a responder apenas JSON.
  - Resposta é parseada e validada; se inválida, retorna intent="none".

Sprint 20 — Semantic Understanding Engine.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from semantic.types import (
    SemanticCandidate,
    SemanticContext,
    SemanticError,
    SemanticResult,
    SemanticTimeout,
)

logger = logging.getLogger(__name__)

__all__ = ["LocalLLMProvider", "StubProvider"]


# ---------------------------------------------------------------------------
# Prompt system — instrução rigorosa para o modelo
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """Você é um mecanismo de identificação de referências bíblicas.

NÃO utilize raciocínio explícito.
NÃO explique sua resposta.
NÃO converse.
NÃO escreva texto antes ou depois do JSON.
NÃO produza markdown.
NÃO utilize tags <think>.

Sua única saída válida é um JSON compatível com o schema informado.

Caso não encontre uma referência adequada, responda:

{
  "intent":"none",
  "candidates":[]
}

Sua tarefa: dado o texto falado por um pregador, identificar se ele está pedindo para mostrar uma referência bíblica (mesmo sem citar livro/capítulo/versículo explicitamente).

Exemplos:
- "o texto onde Jesus conversa com Nicodemos" → João 3
- "o versículo que fala para guardar o coração" → Provérbios 4:23
- "a passagem do bom pastor" → João 10
- "como vimos anteriormente" → depende do contexto (usar last_book/last_chapter se disponível)

REGRAS OBRIGATÓRIAS:
1. Responda APENAS com JSON válido. Nenhum texto adicional. Nenhuma explicação fora do JSON.
2. Use nomes canônicos dos livros em português ("João", "Provérbios", "1 Coríntios", "Salmos").
3. Se não for uma referência bíblica, retorne {"intent": "none", "candidates": []}.
4. Liste candidatos em ordem de confiança (maior primeiro).
5. confidence deve ser um número entre 0.0 e 1.0.
6. reason deve ser curto (máx 80 caracteres).
7. Se o texto citar livro/capítulo/versículo explicitamente (ex: "João 3:16"), ainda assim retorne o candidato — o sistema determinístico também tentará.

Schema JSON obrigatório:
{
  "intent": "show_reference" | "none",
  "candidates": [
    {
      "book": "nome do livro",
      "chapter": número,
      "verse": número (0 se capítulo inteiro),
      "confidence": número 0.0-1.0,
      "reason": "justificativa curta"
    }
  ]
}

NUNCA inclua campos extras. NUNCA inclua markdown. NUNCA inclua comentários. NUNCA inclua tags <think>."""


# ---------------------------------------------------------------------------
# LocalLLMProvider — via HTTP OpenAI-compatible
# ---------------------------------------------------------------------------


class LocalLLMProvider:
    """Provider LLM local via backends intercambiaveis (Sprint 21.3).

    Arquitetura (Strategy Pattern):
        LocalLLMProvider (orchestrator)
                |
                v
            LLMBackend (interface)
                |
                +- OllamaBackend    (endpoint nativo /api/chat, think: false)
                +- OpenAIBackend    (/v1/chat/completions, capability detection)
                +- futuros backends

    O provider nao conhece detalhes do protocolo - apenas consome a
    interface LLMBackend. A escolha do backend e feita via Factory
    (create_backend) ou injetada diretamente.

    Args:
        backend: instancia de LLMBackend (OllamaBackend, OpenAIBackend, etc.).
            Se None, cria OpenAIBackend padrao com base_url/model/api_key
            (retrocompatibilidade com Sprint 21.1).
        base_url: URL base do servidor (usado apenas se backend=None).
        model: nome do modelo (usado apenas se backend=None).
        temperature: temperatura da amostragem (0.0 = deterministico).
        max_tokens: maximo de tokens na resposta.
        request_timeout_s: timeout HTTP em segundos.
        api_key: API key (usado apenas se backend=None).
        top_p: nucleus sampling (0.0-1.0).
        disable_thinking: se True, instrui o backend a impedir thinking.
        max_retries: numero de retries em caso de timeout/erro/JSON invalido.
        retry_backoff_s: backoff base entre retries (dobra a cada tentativa).

    Sprint 21.3 - Arquitetura Multi-Backend:
        - Strategy Pattern: backend injetavel via construtor.
        - OllamaBackend usa endpoint nativo /api/chat (think: false respeitado).
        - OpenAIBackend preserva compatibilidade com OpenAI/LM Studio/vLLm.
        - Factory create_backend() seleciona backend por config.
        - Capability Detection apenas para backends OpenAI-compatible.
    """

    def __init__(
        self,
        backend: Any = None,
        base_url: str = "http://localhost:11434/v1",
        model: str = "llama3.2:3b",
        temperature: float = 0.0,
        max_tokens: int = 300,
        request_timeout_s: float = 10.0,
        api_key: str = "ollama",
        top_p: float = 1.0,
        disable_thinking: bool = True,
        max_retries: int = 2,
        retry_backoff_s: float = 0.2,
    ) -> None:
        # Sprint 21.3 - Strategy Pattern: aceitar backend injetado.
        if backend is None:
            # Retrocompatibilidade: criar OpenAIBackend padrao.
            from semantic.openai_backend import OpenAIBackend
            backend = OpenAIBackend(
                base_url=base_url,
                model=model,
                api_key=api_key,
            )
        self._backend = backend

        # Manter campos para retrocompatibilidade de telemetria/external API.
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._request_timeout_s = request_timeout_s
        self._api_key = api_key
        self._top_p = top_p
        self._disable_thinking = disable_thinking
        self._max_retries = max_retries
        self._retry_backoff_s = retry_backoff_s

        # Sprint 21.1.1 - ThinkingSanitizer (continua usado para OpenAI-compatible).
        # Para OllamaBackend nativo, thinking ja vem separado - sanitizer e defensivo.
        from semantic.thinking_sanitizer import ThinkingSanitizer
        self._sanitizer = ThinkingSanitizer()

        # Sprint 21.3 - CapabilityCache exposto para compatibilidade.
        # Para OllamaBackend, capability e estatica (True). Para OpenAIBackend,
        # e detectada por tentativa.
        from semantic.capability_cache import CapabilityCache, CapabilityState
        if hasattr(backend, "_capability_cache"):
            # Compartilhar o cache do OpenAIBackend.
            self._capability_cache = backend._capability_cache
        else:
            # OllamaBackend ou backend sem cache - criar cache virtual
            # marcando think como SUPPORTED (capacidade estatica).
            self._capability_cache = CapabilityCache()
            self._capability_cache.record_detection(
                "think", CapabilityState.SUPPORTED, detection_ms=0.0,
            )

        # Metricas (Sprint 21.1 - Etapa 9 + Sprint 21.1.1 + Sprint 21.3).
        self._metrics_lock = threading.Lock()
        self._metrics = {
            "total_calls": 0,
            "total_errors": 0,
            "total_timeouts": 0,
            "total_retries": 0,
            "total_thinking_violations": 0,
            "total_thinking_removed": 0,        # Sprint 21.1.1
            "total_thinking_recovered": 0,      # Sprint 21.1.1
            "total_schema_violations": 0,
            "total_discarded": 0,
            "total_success": 0,
            "inference_ms_list": [],  # rolling window (ultimas 200)
            # Sprint 21.3 - metricas de backend.
            "backend_endpoint": backend.endpoint,
            "backend_name": backend.name,
        }

    @property
    def _supports_thinking(self) -> bool:
        """Compatibilidade: retorna True se o backend suporta think.

        Sprint 21.3: delega ao backend (capacidade estatica conhecida).
        """
        return self._backend.supports_think_parameter()

    @property
    def backend(self) -> Any:
        """Expoe o backend (para telemetria/diagnostico)."""
        return self._backend

    @property
    def name(self) -> str:
        return "local-llm"

    @property
    def model_name(self) -> str:
        return self._model

    def is_available(self) -> bool:
        """Verifica se o servidor está online (delega ao backend).

        Sprint 21.3: delega ao backend injetado. Cada backend conhece
        o endpoint correto para verificação de disponibilidade.
        """
        return self._backend.is_available()

    def check_model_available(self) -> bool:
        """Verifica se o modelo está instalado (delega ao backend).

        Sprint 21.3: delega ao backend injetado. OllamaBackend usa
        GET /api/tags; OpenAIBackend usa GET /v1/models.
        """
        return self._backend.check_model_available()

    def infer(self, context: SemanticContext, timeout_ms: int = 5000) -> SemanticResult:
        """Executa inferencia via backend LLM (Sprint 21.3).

        Arquitetura:
          - Construi BackendRequest padronizado.
          - Delega ao backend (Strategy) para envio HTTP + parse.
          - Sanitiza thinking (defensivo, principalmente para OpenAIBackend).
          - Parse JSON + valida schema.
          - Retry com backoff exponencial.
          - Telemetria/metricas.

        Sprint 21.3:
          - Nao conhece detalhes do protocolo (delegado ao backend).
          - OllamaBackend retorna thinking em campo separado (vazio com think: false).
          - OpenAIBackend pode retornar thinking em message.reasoning.
        """
        from semantic.llm_backend import BackendRequest
        from semantic.capability_cache import (
            CapabilityState, is_think_rejection_error,
        )

        timeout_s = min(timeout_ms / 1000.0, self._request_timeout_s)
        user_prompt = self._build_user_prompt(context)

        # Sprint 21.3 - Capability detection apenas para OpenAIBackend.
        # OllamaBackend tem capacidade estatica (supports_think_parameter()=True).
        capability_detected_this_call = False
        is_openai_backend = hasattr(self._backend, "_capability_cache")
        if is_openai_backend and self._disable_thinking and \
                self._capability_cache.should_try("think"):
            capability_detected_this_call = True
            logger.debug(
                "LocalLLMProvider: capability detection started (OpenAI backend)"
            )

        last_error: Exception | None = None
        total_inference_ms = 0

        for attempt in range(self._max_retries + 1):
            t0 = time.monotonic()
            try:
                # Construir request padronizado.
                request = BackendRequest(
                    system_prompt=_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    model=self._model,
                    temperature=self._temperature,
                    top_p=self._top_p,
                    max_tokens=self._max_tokens,
                    disable_thinking=self._disable_thinking,
                    stream=False,
                )
                # Construir payload via backend.
                payload = self._backend.build_payload(request)
                # Forcar think: false se estamos detectando capability.
                if capability_detected_this_call and \
                        self._capability_cache.should_try("think"):
                    payload["think"] = False

                # Enviar requisicao via backend (retorna BackendResponse).
                backend_resp = self._backend.send_request(payload, timeout_s)
                attempt_ms = int(backend_resp.http_time_ms)
                total_inference_ms += attempt_ms

                # Se estavamos detectando capability e chegamos aqui, o
                # backend aceitou think: false.
                if capability_detected_this_call and \
                        self._capability_cache.should_try("think"):
                    det_ms = attempt_ms
                    self._capability_cache.record_detection(
                        "think", CapabilityState.SUPPORTED, detection_ms=det_ms,
                    )
                    logger.debug(
                        "LocalLLMProvider: OpenAI backend supports think parameter "
                        "(detection_ms=%.1f)", det_ms,
                    )

                # O backend ja extraiu content e thinking em campos separados.
                content = backend_resp.content
                if not content:
                    # Sem conteudo - pode ser thinking consumiu tudo ou erro.
                    if backend_resp.error:
                        self._record_metric("schema_violation")
                        last_error = SemanticError(backend_resp.error)
                        continue
                    self._record_metric("schema_violation")
                    last_error = SemanticError("empty content from backend")
                    continue

                # Sanitizacao defensiva (principalmente para OpenAIBackend
                # que pode ter thinking inline em message.content).
                sanitized = self._sanitizer.sanitize(content)
                if sanitized.had_thinking:
                    self._record_metric("thinking_removed")
                    logger.debug(
                        "LocalLLMProvider: thinking block removed "
                        "(patterns=%s, original=%d chars, cleaned=%d chars)",
                        sanitized.patterns_matched,
                        sanitized.original_length, sanitized.cleaned_length,
                    )

                cleaned_content = sanitized.content
                result = self._parse_and_validate(cleaned_content)

                if sanitized.had_thinking:
                    if result.intent != "none" or result.candidates:
                        self._record_metric("thinking_recovered")
                        logger.debug(
                            "LocalLLMProvider: recovered JSON after sanitization"
                        )
                    else:
                        self._record_metric("thinking_violation")
                        self._record_metric("discarded")
                        last_error = SemanticError(
                            "thinking sanitized but JSON still invalid"
                        )
                        continue

                final = SemanticResult(
                    intent=result.intent,
                    candidates=result.candidates,
                    inference_ms=total_inference_ms,
                    provider=self.name,
                    model=self._model,
                )
                self._record_metric("success", total_inference_ms)
                return final

            except SemanticTimeout as e:
                total_inference_ms += int((time.monotonic() - t0) * 1000)
                self._record_metric("timeout")
                last_error = e
                logger.warning(
                    "LocalLLMProvider: timeout on attempt %d/%d: %s",
                    attempt + 1, self._max_retries + 1, e,
                )
            except SemanticError as e:
                total_inference_ms += int((time.monotonic() - t0) * 1000)

                # Capability detection: detectar rejeicao do think (apenas OpenAI).
                if capability_detected_this_call and \
                        self._capability_cache.should_try("think"):
                    err_msg = str(e)
                    status_code = self._extract_status_code(err_msg)
                    if is_think_rejection_error(status_code, err_msg):
                        det_ms = total_inference_ms
                        self._capability_cache.record_detection(
                            "think", CapabilityState.UNSUPPORTED,
                            detection_ms=det_ms,
                            error_message=err_msg[:200],
                        )
                        logger.debug(
                            "LocalLLMProvider: OpenAI backend rejected think parameter "
                            "(detection_ms=%.1f, error=%r)",
                            det_ms, err_msg[:80],
                        )
                        # Refazer sem think: false (proximo iteration).
                        capability_detected_this_call = False
                        continue

                self._record_metric("error")
                last_error = e
                logger.warning(
                    "LocalLLMProvider: error on attempt %d/%d: %s",
                    attempt + 1, self._max_retries + 1, e,
                )
            except Exception as e:
                total_inference_ms += int((time.monotonic() - t0) * 1000)
                self._record_metric("error")
                last_error = SemanticError(f"unexpected: {e}")
                logger.warning(
                    "LocalLLMProvider: unexpected error on attempt %d/%d: %s",
                    attempt + 1, self._max_retries + 1, e,
                )

            # Backoff antes do proximo retry.
            if attempt < self._max_retries:
                self._record_metric("retry")
                backoff = self._retry_backoff_s * (2 ** attempt)
                time.sleep(min(backoff, 2.0))

        # Todos os retries falharam - retornar none sem propagar erro.
        # (Etapa 6 - jamais travar a apresentacao.)
        self._record_metric("discarded")
        logger.error(
            "LocalLLMProvider: all %d attempts failed - returning intent=none: %s",
            self._max_retries + 1, last_error,
        )
        return SemanticResult(
            intent="none",
            inference_ms=total_inference_ms,
            provider=self.name,
            model=self._model,
        )

    def close(self) -> None:
        """Nada a fazer — provider HTTP não mantém estado."""
        pass

    # ------------------------------------------------------------------
    # Métricas (Etapa 9)
    # ------------------------------------------------------------------

    def metrics(self) -> dict[str, Any]:
        """Retorna métricas operacionais do provider.

        Sprint 21.1.1 — adicionadas:
          - thinking_removed_total
          - thinking_recovered_total
          - backend_capability_detection_ms
          - backend_supports_thinking
          - capability_detection_attempts
        """
        with self._metrics_lock:
            times = list(self._metrics["inference_ms_list"])
            total = self._metrics["total_calls"]
            errors = self._metrics["total_errors"]
            timeouts = self._metrics["total_timeouts"]
            thinking_v = self._metrics["total_thinking_violations"]
            thinking_removed = self._metrics["total_thinking_removed"]
            thinking_recovered = self._metrics["total_thinking_recovered"]
            schema_v = self._metrics["total_schema_violations"]
            discarded = self._metrics["total_discarded"]
            success = self._metrics["total_success"]

        # Sprint 21.1.1 — métricas de capability cache.
        cap_result = self._capability_cache.get_result("think")
        cap_attempts = self._capability_cache.get_detection_attempts("think")
        cap_detection_ms = cap_result.detection_ms if cap_result else 0.0
        cap_state = cap_result.state.value if cap_result else "unknown"

        avg_ms = sum(times) / len(times) if times else 0.0
        # p95
        if times:
            sorted_t = sorted(times)
            idx = max(0, min(len(sorted_t) - 1, int(len(sorted_t) * 0.95)))
            p95_ms = sorted_t[idx]
        else:
            p95_ms = 0

        error_rate = (errors / total) if total > 0 else 0.0
        discarded_rate = (discarded / total) if total > 0 else 0.0
        thinking_rate = (thinking_v / total) if total > 0 else 0.0
        schema_rate = (schema_v / total) if total > 0 else 0.0
        thinking_removed_rate = (thinking_removed / total) if total > 0 else 0.0
        thinking_recovered_rate = (thinking_recovered / total) if total > 0 else 0.0

        return {
            "provider": self.name,
            "model": self._model,
            "supports_thinking": self._supports_thinking,
            "disable_thinking_sent": self._disable_thinking and self._supports_thinking,
            "total_calls": total,
            "total_success": success,
            "total_errors": errors,
            "total_timeouts": timeouts,
            "total_retries": self._metrics["total_retries"],
            "total_thinking_violations": thinking_v,
            "total_thinking_removed": thinking_removed,
            "total_thinking_recovered": thinking_recovered,
            "total_schema_violations": schema_v,
            "total_discarded": discarded,
            "avg_inference_ms": round(avg_ms, 2),
            "p95_inference_ms": p95_ms,
            "error_rate": round(error_rate, 4),
            "discarded_rate": round(discarded_rate, 4),
            "thinking_violation_rate": round(thinking_rate, 4),
            "thinking_removed_rate": round(thinking_removed_rate, 4),
            "thinking_recovered_rate": round(thinking_recovered_rate, 4),
            "schema_violation_rate": round(schema_rate, 4),
            # Sprint 21.1.1 — Capability cache metrics.
            "backend_supports_thinking": cap_state,
            "backend_capability_detection_ms": round(cap_detection_ms, 2),
            "capability_detection_attempts": cap_attempts,
        }

    def _record_metric(self, kind: str, inference_ms: int = 0) -> None:
        with self._metrics_lock:
            if kind == "success":
                self._metrics["total_calls"] += 1
                self._metrics["total_success"] += 1
                self._metrics["inference_ms_list"].append(inference_ms)
                # Rolling window — últimas 200 inferências.
                if len(self._metrics["inference_ms_list"]) > 200:
                    self._metrics["inference_ms_list"] = \
                        self._metrics["inference_ms_list"][-200:]
            elif kind == "timeout":
                self._metrics["total_calls"] += 1
                self._metrics["total_timeouts"] += 1
                self._metrics["total_errors"] += 1
            elif kind == "error":
                self._metrics["total_calls"] += 1
                self._metrics["total_errors"] += 1
            elif kind == "retry":
                self._metrics["total_retries"] += 1
            elif kind == "thinking_violation":
                self._metrics["total_thinking_violations"] += 1
            elif kind == "thinking_removed":
                self._metrics["total_thinking_removed"] += 1
            elif kind == "thinking_recovered":
                self._metrics["total_thinking_recovered"] += 1
            elif kind == "schema_violation":
                self._metrics["total_schema_violations"] += 1
            elif kind == "discarded":
                self._metrics["total_discarded"] += 1

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    # Sprint 21.3 — metodos _build_headers, _build_payload, _http_post,
    # _extract_content foram removidos (delegados ao backend injetado).
    # Mantidos apenas _extract_status_code (capability detection),
    # _build_user_prompt (prompt) e _parse_and_validate (JSON+schema).

    def _extract_status_code(self, err_msg: str) -> int:
        """Extrai o status code HTTP de uma mensagem de erro SemanticError.

        Sprint 21.1.1: usado para detectar rejeicao do parametro think.
        Formato esperado: "HTTP 400 error: ...".
        """
        m = re.search(r"HTTP (\d+)", err_msg)
        return int(m.group(1)) if m else 0

    def _build_user_prompt(self, context: SemanticContext) -> str:
        """Constrói o prompt do usuário com contexto (incluindo SermonContext — Sprint 21)."""
        lines = []
        # Sprint 21 — usar SermonContext (memória contínua) se disponível.
        if context.sermon_book:
            ref = context.sermon_book
            if context.sermon_chapter > 0:
                ref += f" {context.sermon_chapter}"
            lines.append(f"Contexto do sermão: pregando em {ref}.")
            if context.sermon_theme:
                lines.append(f"Tema atual: {context.sermon_theme}.")
            if context.sermon_entities:
                lines.append(
                    f"Entidades mencionadas: {', '.join(context.sermon_entities[:5])}."
                )
            if context.sermon_confidence > 0:
                lines.append(
                    f"Confiança da memória: {context.sermon_confidence:.0%}."
                )
        elif context.last_book:
            # Fallback: usar última referência do histórico (Sprint 20).
            lines.append(f"Contexto: o sermão está em {context.last_reference or context.last_book}.")
        if context.recent_text and context.recent_text != context.current_text:
            lines.append(f"Fala recente: {context.recent_text}")
        lines.append(f"Texto atual: {context.current_text}")
        lines.append("")
        lines.append("Responda apenas com JSON:")
        return "\n".join(lines)

    def _parse_and_validate(self, content: str) -> SemanticResult:
        """Parsea e valida rigorosamente o JSON retornado pelo modelo.

        Etapa 7 — Segurança: se o schema for inválido, descarta e
        retorna intent="none".
        """
        # Limpar markdown code fences se presentes.
        text = content.strip()
        if text.startswith("```"):
            # Remover ```json ... ``` ou ``` ... ```.
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("LocalLLMProvider: response is not valid JSON: %r", content[:200])
            return SemanticResult(intent="none")

        if not isinstance(data, dict):
            return SemanticResult(intent="none")

        # Validar intent.
        intent = data.get("intent", "none")
        if intent not in ("show_reference", "none"):
            logger.warning("LocalLLMProvider: invalid intent %r", intent)
            return SemanticResult(intent="none")

        if intent == "none":
            return SemanticResult(intent="none")

        # Validar candidates.
        raw_candidates = data.get("candidates", [])
        if not isinstance(raw_candidates, list):
            return SemanticResult(intent="none")

        candidates: list[SemanticCandidate] = []
        for raw in raw_candidates:
            cand = self._validate_candidate(raw)
            if cand is not None:
                candidates.append(cand)

        if not candidates:
            return SemanticResult(intent="none")

        return SemanticResult(
            intent="show_reference",
            candidates=tuple(candidates),
        )

    def _validate_candidate(self, raw: Any) -> SemanticCandidate | None:
        """Valida um candidato individual. Retorna None se inválido."""
        if not isinstance(raw, dict):
            return None

        book = raw.get("book", "")
        if not isinstance(book, str) or not book.strip():
            return None
        book = book.strip()[:40]  # limitar tamanho

        chapter = raw.get("chapter", 0)
        if not isinstance(chapter, (int, float)) or chapter < 0:
            return None
        chapter = int(chapter)

        verse = raw.get("verse", 0)
        if not isinstance(verse, (int, float)) or verse < 0:
            return None
        verse = int(verse)

        confidence = raw.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)):
            return None
        confidence = max(0.0, min(1.0, float(confidence)))

        reason = raw.get("reason", "")
        if not isinstance(reason, str):
            reason = ""
        reason = reason.strip()[:80]

        return SemanticCandidate(
            book=book,
            chapter=chapter,
            verse=verse,
            confidence=confidence,
            reason=reason,
        )


# ---------------------------------------------------------------------------
# StubProvider — para testes e desenvolvimento sem LLM real
# ---------------------------------------------------------------------------


class StubProvider:
    """Provider stub que retorna respostas pré-programadas.

    Útil para testes e desenvolvimento sem servidor LLM rodando.
    Mapeia textos comuns para respostas canônicas.

    Implementa SemanticProvider (Protocol).
    """

    # Mapeamento texto → candidatos (case-insensitive, substring match).
    _STUB_RESPONSES: list[tuple[str, list[dict[str, Any]]]] = [
        ("nicodemos", [
            {"book": "João", "chapter": 3, "verse": 0, "confidence": 0.82,
             "reason": "Jesus conversa com Nicodemos"},
            {"book": "João", "chapter": 3, "verse": 5, "confidence": 0.61,
             "reason": "Nascer da água e do espírito"},
        ]),
        ("guardar o coração", [
            {"book": "Provérbios", "chapter": 4, "verse": 23, "confidence": 0.88,
             "reason": "Guarda o teu coração"},
        ]),
        ("bom pastor", [
            {"book": "João", "chapter": 10, "verse": 0, "confidence": 0.85,
             "reason": "Eu sou o bom pastor"},
            {"book": "João", "chapter": 10, "verse": 11, "confidence": 0.78,
             "reason": "O bom pastor dá a vida pelas ovelhas"},
        ]),
        ("samaritano", [
            {"book": "Lucas", "chapter": 10, "verse": 0, "confidence": 0.80,
             "reason": "Parábola do bom samaritano"},
        ]),
        ("criação do mundo", [
            {"book": "Gênesis", "chapter": 1, "verse": 0, "confidence": 0.90,
             "reason": "Criação"},
        ]),
        ("dilúvio", [
            {"book": "Gênesis", "chapter": 6, "verse": 0, "confidence": 0.75,
             "reason": "Dilúvio"},
        ]),
        ("sermão do monte", [
            {"book": "Mateus", "chapter": 5, "verse": 0, "confidence": 0.87,
             "reason": "Sermão do Monte"},
        ]),
        ("águia", [
            {"book": "Isaías", "chapter": 40, "verse": 31, "confidence": 0.72,
             "reason": "Renovam-se as forças como a águia"},
        ]),
    ]

    def __init__(self, delay_ms: int = 0) -> None:
        self._delay_ms = delay_ms

    @property
    def name(self) -> str:
        return "stub"

    @property
    def model_name(self) -> str:
        return "stub-v1"

    def is_available(self) -> bool:
        return True

    def infer(self, context: SemanticContext, timeout_ms: int = 5000) -> SemanticResult:
        if self._delay_ms > 0:
            time.sleep(self._delay_ms / 1000.0)

        text_lower = context.current_text.lower()
        for pattern, candidates in self._STUB_RESPONSES:
            if pattern in text_lower:
                cands = tuple(
                    SemanticCandidate(
                        book=c["book"],
                        chapter=c["chapter"],
                        verse=c["verse"],
                        confidence=c["confidence"],
                        reason=c["reason"],
                    )
                    for c in candidates
                )
                return SemanticResult(
                    intent="show_reference",
                    candidates=cands,
                    inference_ms=self._delay_ms,
                    provider=self.name,
                    model=self.model_name,
                )

        return SemanticResult(
            intent="none",
            inference_ms=self._delay_ms,
            provider=self.name,
            model=self.model_name,
        )

    def close(self) -> None:
        pass
