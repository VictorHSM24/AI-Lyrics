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
import socket
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

_SYSTEM_PROMPT = """Você é um assistente especialista em Bíblia que identifica referências bíblicas implícitas em falas de um pregador.

Sua tarefa: dado o texto falado, identificar se o pregador está pedindo para mostrar uma referência bíblica (mesmo sem citar livro/capítulo/versículo explicitamente).

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

NUNCA inclua campos extras. NUNCA inclua markdown. NUNCA inclua comentários."""


# ---------------------------------------------------------------------------
# LocalLLMProvider — via HTTP OpenAI-compatible
# ---------------------------------------------------------------------------


class LocalLLMProvider:
    """Provider LLM local via API OpenAI-compatible (Ollama, LM Studio, etc.).

    Args:
        base_url: URL base do servidor (ex.: "http://localhost:11434/v1"
            para Ollama, "http://localhost:1234/v1" para LM Studio).
        model: nome do modelo ("llama3.2:3b", "qwen2.5:7b", etc.).
        temperature: temperatura da amostragem (0.0 = determinístico).
        max_tokens: máximo de tokens na resposta.
        request_timeout_s: timeout HTTP em segundos.

    Nota:
        Este provider NÃO carrega o modelo — ele assume que o servidor
        (Ollama, LM Studio) já está rodando com o modelo carregado.
        Use `is_available()` para verificar antes de chamar `infer()`.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "llama3.2:3b",
        temperature: float = 0.0,
        max_tokens: int = 300,
        request_timeout_s: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._request_timeout_s = request_timeout_s

    # ------------------------------------------------------------------
    # SemanticProvider interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "local-llm"

    @property
    def model_name(self) -> str:
        return self._model

    def is_available(self) -> bool:
        """Verifica se o servidor está online fazendo um GET /models."""
        try:
            url = f"{self._base_url}/models"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def infer(self, context: SemanticContext, timeout_ms: int = 5000) -> SemanticResult:
        """Executa inferência via HTTP POST /chat/completions."""
        timeout_s = min(timeout_ms / 1000.0, self._request_timeout_s)
        t0 = time.monotonic()

        # Construir prompt do usuário com contexto.
        user_prompt = self._build_user_prompt(context)

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": False,
        }

        body = json.dumps(payload).encode("utf-8")
        url = f"{self._base_url}/chat/completions"
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read().decode("utf-8")
        except socket.timeout as e:
            raise SemanticTimeout(f"HTTP timeout after {timeout_s}s") from e
        except urllib.error.URLError as e:
            if "timed out" in str(e).lower():
                raise SemanticTimeout(f"HTTP timeout: {e}") from e
            raise SemanticError(f"HTTP error: {e}") from e
        except Exception as e:
            raise SemanticError(f"unexpected error: {e}") from e

        inference_ms = int((time.monotonic() - t0) * 1000)

        # Parsear resposta OpenAI-compatible.
        try:
            resp_json = json.loads(raw)
            content = resp_json["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning("LocalLLMProvider: invalid response structure: %s", e)
            return SemanticResult(
                intent="none",
                inference_ms=inference_ms,
                provider=self.name,
                model=self._model,
            )

        # Parsear e validar o JSON do conteúdo.
        result = self._parse_and_validate(content)
        result = SemanticResult(
            intent=result.intent,
            candidates=result.candidates,
            inference_ms=inference_ms,
            provider=self.name,
            model=self._model,
        )
        return result

    def close(self) -> None:
        """Nada a fazer — provider HTTP não mantém estado."""
        pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
