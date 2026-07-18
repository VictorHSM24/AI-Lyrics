"""Cliente LLM para interpretação semântica de comandos bíblicos.

Conecta ao servidor Ollama (OpenAI-compatible) e interpreta texto
transcrito que o parser determinístico não conseguiu resolver
(``action="uncertain"``).

Backend: Ollama ``/api/chat`` (Qwen3 8B Q4_K_M).

Fluxo (Blueprint §4.4, linhas 804-811):
  1. Se ``lazy_load`` e não carregado: primeira chamada dispara load.
  2. Montar messages via ``build_messages(text, state)``.
  3. POST ``/api/chat`` com ``response_format="json"``.
  4. Parsear JSON da resposta.
  5. Validar contra schema (``validate_response``).
  6. Se inválido: retry 1x com prompt de correção.
  7. Se ainda inválido: ``Intent(action="none", confidence=0.0, source="llm")``.
  8. Mapear para ``Intent`` com ``source="llm"``, ``confidence=c_llm``
     (campo da resposta ou 0.7 default).

Limites explícitos:
  - Não chama Holyrics.
  - Não chama Searcher.
  - Não modifica estado.
  - Não implementa cache.
  - Apenas produz ``Intent``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from config.books import BookTable
from config.models import LLMConfig
from core.exceptions import AILyricsError
from core.types import Intent
from estado.state import BibleState
from llm.prompts import build_correction_messages, build_messages, validate_response

logger = logging.getLogger(__name__)

# Confiança default quando o LLM não inclui o campo na resposta.
_DEFAULT_CONFIDENCE: float = 0.7


class LLMError(AILyricsError):
    """Erro do módulo LLM (conexão, timeout, resposta inválida)."""


class LLMClient:
    """Cliente para interpretação semântica via LLM (Ollama/Qwen3).

    Args:
        config: configuração do LLM (base_url, model, timeout, etc.).
        book_table: tabela de livros canônicos para resolver nomes.

    Attributes:
        is_available: True se o servidor Ollama está reachável.
    """

    def __init__(
        self,
        config: LLMConfig,
        book_table: BookTable,
    ) -> None:
        self._config = config
        self._book_table = book_table
        self._base_url = config.base_url.rstrip("/")
        self._timeout_s = config.timeout_ms / 1000.0
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._loaded = False
        # lazy_load=False → carregar imediatamente (warmup)
        if not config.lazy_load:
            self.warmup()

    # ------------------------------------------------------------------
    # Operações públicas
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Verifica se o servidor Ollama está reachável.

        Usa ``GET /api/tags`` (endpoint leve do Ollama que lista modelos).
        Retorna ``True`` se conectou, ``False`` caso contrário.
        """
        try:
            resp = self._session.get(
                f"{self._base_url}/api/tags",
                timeout=min(self._timeout_s, 2.0),
            )
            return resp.status_code == 200
        except requests.exceptions.RequestException as e:
            logger.debug("is_available: connection failed: %s", e)
            return False

    def warmup(self) -> None:
        """Pré-carrega o modelo no servidor Ollama (lazy load bypass).

        Envia uma requisição mínima para forçar o carregamento do modelo
        na VRAM. Se falhar, apenas loga — não levanta erro.
        """
        if self._loaded:
            return
        try:
            logger.info("warmup: loading model %s...", self._config.model)
            resp = self._session.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._config.model,
                    "messages": [{"role": "user", "content": "ok"}],
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": 1},
                },
                timeout=self._timeout_s,
            )
            if resp.status_code == 200:
                self._loaded = True
                logger.info("warmup: model loaded successfully")
            else:
                logger.warning(
                    "warmup: HTTP %d — model not loaded", resp.status_code
                )
        except requests.exceptions.RequestException as e:
            logger.warning("warmup: failed: %s", e)

    def interpret(
        self,
        text: str,
        state: BibleState | None = None,
    ) -> Intent:
        """Interpreta texto transcrito e produz ``Intent``.

        Fluxo:
          1. Se lazy_load e não carregado: warmup.
          2. Montar messages (system + few-shot + user).
          3. POST /api/chat com response_format json.
          4. Parsear e validar JSON.
          5. Se inválido: retry 1x com prompt de correção.
          6. Se ainda inválido: Intent(action="none", confidence=0.0).
          7. Mapear para Intent com source="llm".

        Args:
            text: texto transcrito pelo STT.
            state: estado atual da navegação (opcional, para contexto).

        Returns:
            ``Intent`` com ``source="llm"`` e ``confidence=c_llm``.
        """
        if not text or not text.strip():
            return Intent(
                action="none",
                confidence=0.0,
                source="llm",
                raw=text or "",
            )

        # Lazy load: carregar modelo na primeira chamada
        if self._config.lazy_load and not self._loaded:
            self.warmup()

        messages = build_messages(text, state)

        # Primeira tentativa
        json_obj = self._call_llm(messages)
        if json_obj is not None and validate_response(json_obj):
            return self._map_to_intent(json_obj, text)

        # Retry com prompt de correção
        logger.warning("interpret: first attempt invalid, retrying with correction prompt")
        correction_messages = build_correction_messages(messages)
        json_obj = self._call_llm(correction_messages)
        if json_obj is not None and validate_response(json_obj):
            return self._map_to_intent(json_obj, text)

        # Fallback: Intent(action="none")
        logger.warning("interpret: retry failed, returning Intent(action='none')")
        return Intent(
            action="none",
            confidence=0.0,
            source="llm",
            raw=text,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _call_llm(
        self,
        messages: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        """Executa POST /api/chat e retorna JSON parseado.

        Args:
            messages: lista de messages no formato Ollama.

        Returns:
            Dict parseado do JSON da resposta, ou None se falhou.
        """
        payload = {
            "model": self._config.model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "think": False,
            "options": {
                "num_predict": self._config.max_tokens,
                "temperature": 0.1,
            },
        }

        try:
            resp = self._session.post(
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=self._timeout_s,
            )
        except requests.exceptions.Timeout as e:
            logger.warning("_call_llm: timeout after %.1fs: %s", self._timeout_s, e)
            return None
        except requests.exceptions.ConnectionError as e:
            logger.warning("_call_llm: connection refused: %s", e)
            return None
        except requests.exceptions.RequestException as e:
            logger.warning("_call_llm: request error: %s", e)
            return None

        if resp.status_code != 200:
            logger.warning(
                "_call_llm: HTTP %d — %s",
                resp.status_code,
                resp.text[:200],
            )
            return None

        # Parsear resposta do Ollama
        try:
            body = resp.json()
        except ValueError as e:
            logger.warning("_call_llm: invalid JSON in response: %s", e)
            return None

        # Ollama /api/chat retorna {"message": {"content": "..."}, ...}
        message = body.get("message")
        if not isinstance(message, dict):
            logger.warning("_call_llm: no 'message' field in response")
            return None

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            logger.warning("_call_llm: empty content in message")
            return None

        # Parsear o JSON dentro de content
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("_call_llm: content is not valid JSON: %s", e)
            return None

        return parsed

    def _map_to_intent(
        self,
        json_obj: dict[str, Any],
        raw_text: str,
    ) -> Intent:
        """Mapeia JSON validado para ``Intent``.

        Args:
            json_obj: JSON validado pelo ``validate_response``.
            raw_text: texto original transcrito.

        Returns:
            ``Intent`` com ``source="llm"``.
        """
        action = str(json_obj.get("action", "none"))
        confidence = float(json_obj.get("confidence", _DEFAULT_CONFIDENCE))
        # Clamp confidence to [0.0, 1.0]
        confidence = max(0.0, min(1.0, confidence))

        book = json_obj.get("book")
        book_id = None
        chapter = json_obj.get("chapter")
        verse = json_obj.get("verse")
        amount = json_obj.get("amount")
        query = json_obj.get("query")

        # Resolver book_id via BookTable se book foi informado
        if book and isinstance(book, str):
            match = self._book_table.resolve(book)
            if match is not None:
                book_id = match.book.id
                book = match.book.canonical
            else:
                logger.warning(
                    "_map_to_intent: book %r not found in BookTable", book
                )

        # Converter tipos numéricos
        if chapter is not None:
            try:
                chapter = int(chapter)
            except (ValueError, TypeError):
                chapter = None
        if verse is not None:
            try:
                verse = int(verse)
            except (ValueError, TypeError):
                verse = None
        if amount is not None:
            try:
                amount = int(amount)
            except (ValueError, TypeError):
                amount = None

        return Intent(
            action=action,
            book=book if isinstance(book, str) and book.strip() else None,
            book_id=book_id,
            chapter=chapter,
            verse=verse,
            amount=amount,
            query=query if isinstance(query, str) and query.strip() else None,
            confidence=confidence,
            source="llm",
            raw=raw_text,
            enrichment=self._extract_enrichment(json_obj),
        )

    def _extract_enrichment(self, json_obj: dict[str, Any]) -> dict | None:
        """Extrai campos de enrichment do JSON do LLM.

        Retorna um dict com keywords, tema, evento, personagens,
        livros_sugeridos, sinonimos, conceitos — ou None se nenhum
        campo de enrichment estiver presente.
        """
        enrichment_fields = (
            "keywords", "tema", "evento", "personagens",
            "livros_sugeridos", "sinonimos", "conceitos",
        )
        enrichment: dict[str, Any] = {}
        for field in enrichment_fields:
            value = json_obj.get(field)
            if value is not None:
                enrichment[field] = value
        return enrichment if enrichment else None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Fecha a sessão HTTP."""
        self._session.close()

    def __enter__(self) -> "LLMClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
