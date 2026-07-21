"""semantic/engine.py — SemanticEngine (Sprint 20, Etapa 2).

Responsabilidade única:
  texto → entendimento semântico → lista de candidatos

Regras:
  - Assina SpeechPartial e SpeechPartialUpdated (paralelo ao IncrementalParser).
  - Constrói contexto via ContextEngine.
  - Consulta cache antes de chamar o provider.
  - Chama SemanticProvider.infer() com timeout.
  - Valida rigorosamente o schema da resposta (Etapa 7 — Segurança).
  - Publica IntentCandidate (NUNCA ReferenceDetected).
  - Publica SemanticInferenceCompleted (telemetria para o frontend).
  - NUNCA consulta Holyrics, frontend, banco ou Searcher.
  - NUNCA publica ReferenceDetected.

Debounce:
  - Para evitar chamar o LLM a cada parcial (caro), aplica debounce de
    800ms após o último SpeechPartialUpdated. Se um novo parcial chega
    antes do debounce, reseta o timer.
  - Só invoca o LLM se o texto tiver >= 8 caracteres (evita ruído).

Sprint 20 — Semantic Understanding Engine.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from pipeline.events import (
    IntentCandidate,
    SemanticInferenceCompleted,
    SpeechPartial,
    SpeechPartialUpdated,
)
from pipeline.metadata import EventMetadata
from semantic.cache import SemanticCache
from semantic.context_engine import ContextEngine
from semantic.provider import SemanticProvider
from semantic.types import SemanticError, SemanticResult, SemanticTimeout

logger = logging.getLogger(__name__)

__all__ = ["SemanticEngine"]


# Mínimo de caracteres para considerar invocar o LLM.
_MIN_TEXT_LENGTH = 8

# Debounce default em ms (espera parar de falar antes de invocar).
_DEFAULT_DEBOUNCE_MS = 800


class SemanticEngine:
    """Camada de compreensão semântica.

    Assina SpeechPartial/Updated no EventBus, constrói contexto,
    consulta cache, chama provider, publica IntentCandidate.

    Args:
        bus: EventBus para assinar/publicar eventos.
        provider: SemanticProvider (LocalLLMProvider, StubProvider, etc.).
        context_engine: ContextEngine para construir contexto.
        cache: SemanticCache para evitar re-chamadas.
        session_id: ID da sessão atual.
        debounce_ms: debounce antes de invocar o LLM (default 800ms).
        timeout_ms: timeout da inferência (default 5000ms).
        enabled: se False, não processa nada (kill switch).
    """

    def __init__(
        self,
        bus: Any,
        provider: SemanticProvider,
        context_engine: ContextEngine,
        cache: SemanticCache,
        session_id: str,
        debounce_ms: int = _DEFAULT_DEBOUNCE_MS,
        timeout_ms: int = 5000,
        enabled: bool = True,
    ) -> None:
        self._bus = bus
        self._provider = provider
        self._context_engine = context_engine
        self._cache = cache
        self._session_id = session_id
        self._debounce_ms = debounce_ms
        self._timeout_ms = timeout_ms
        self._enabled = enabled

        # Estado do debounce.
        self._debounce_timer: threading.Timer | None = None
        self._pending_text: str = ""
        self._pending_meta: EventMetadata | None = None
        self._lock = threading.Lock()

        # Estatísticas.
        self._total_calls = 0
        self._total_errors = 0
        self._total_cache_hits = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inscreve-se nos eventos do EventBus."""
        if not self._enabled:
            logger.info("SemanticEngine: disabled, not subscribing")
            return
        self._bus.subscribe(SpeechPartial, self._on_partial)
        self._bus.subscribe(SpeechPartialUpdated, self._on_partial_updated)
        logger.info(
            "SemanticEngine: started (provider=%s, model=%s, debounce=%dms, timeout=%dms)",
            self._provider.name, self._provider.model_name,
            self._debounce_ms, self._timeout_ms,
        )

    def stop(self) -> None:
        """Para o engine e cancela debounce pendente."""
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
        try:
            self._bus.unsubscribe(SpeechPartial, self._on_partial)
            self._bus.unsubscribe(SpeechPartialUpdated, self._on_partial_updated)
        except Exception:
            pass
        logger.info("SemanticEngine: stopped")

    # ------------------------------------------------------------------
    # Handlers de eventos
    # ------------------------------------------------------------------

    def _on_partial(self, event: SpeechPartial) -> None:
        """Recebe SpeechPartial — inicia debounce se texto for suficiente."""
        self._schedule_debounce(event.text, event.meta)

    def _on_partial_updated(self, event: SpeechPartialUpdated) -> None:
        """Recebe SpeechPartialUpdated — reset debounce com texto atualizado."""
        self._schedule_debounce(event.text, event.meta)

    def _schedule_debounce(self, text: str, meta: EventMetadata) -> None:
        """Agenda invocação do LLM após debounce."""
        if not self._enabled:
            return
        text = text.strip()
        if len(text) < _MIN_TEXT_LENGTH:
            return

        with self._lock:
            # Cancelar debounce anterior.
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._pending_text = text
            self._pending_meta = meta
            # Agendar novo.
            self._debounce_timer = threading.Timer(
                self._debounce_ms / 1000.0,
                self._fire_inference,
            )
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    # ------------------------------------------------------------------
    # Inferência
    # ------------------------------------------------------------------

    def _fire_inference(self) -> None:
        """Executa inferência após debounce expirar."""
        with self._lock:
            text = self._pending_text
            meta = self._pending_meta
            self._debounce_timer = None
            self._pending_text = ""
            self._pending_meta = None

        if not text or meta is None:
            return

        try:
            self._run_inference(text, meta)
        except Exception as e:
            logger.exception("SemanticEngine: inference failed: %s", e)
            self._total_errors += 1
            self._publish_telemetry(
                meta=meta,
                intent="",
                num_candidates=0,
                inference_ms=0,
                cached=False,
                error=str(e),
                context_text=text,
                context_hash="",
            )

    def _run_inference(self, text: str, source_meta: EventMetadata) -> None:
        """Constrói contexto, consulta cache, chama provider, publica eventos."""
        self._total_calls += 1

        # 1. Construir contexto.
        context = self._context_engine.build(
            current_text=text,
            session_id=self._session_id,
            correlation_id=source_meta.correlation_id,
        )
        context_hash = context.context_hash()

        # 2. Consultar cache.
        cached_result = self._cache.get(context_hash)
        if cached_result is not None:
            self._total_cache_hits += 1
            logger.debug("SemanticEngine: cache hit (hash=%s)", context_hash)
            self._publish_telemetry(
                meta=source_meta,
                intent=cached_result.intent,
                num_candidates=len(cached_result.candidates),
                inference_ms=0,
                cached=True,
                error="",
                context_text=text,
                context_hash=context_hash,
            )
            if cached_result.has_candidates:
                self._publish_intent_candidate(
                    source_meta, cached_result, context_hash, cached=True
                )
            return

        # 3. Verificar se provider está disponível.
        if not self._provider.is_available():
            logger.warning("SemanticEngine: provider %s not available", self._provider.name)
            self._publish_telemetry(
                meta=source_meta,
                intent="",
                num_candidates=0,
                inference_ms=0,
                cached=False,
                error=f"provider {self._provider.name} not available",
                context_text=text,
                context_hash=context_hash,
            )
            return

        # 4. Chamar provider com timeout.
        try:
            result = self._provider.infer(context, timeout_ms=self._timeout_ms)
        except SemanticTimeout as e:
            self._total_errors += 1
            self._publish_telemetry(
                meta=source_meta,
                intent="",
                num_candidates=0,
                inference_ms=self._timeout_ms,
                cached=False,
                error=f"timeout: {e}",
                context_text=text,
                context_hash=context_hash,
            )
            return
        except SemanticError as e:
            self._total_errors += 1
            self._publish_telemetry(
                meta=source_meta,
                intent="",
                num_candidates=0,
                inference_ms=0,
                cached=False,
                error=f"provider error: {e}",
                context_text=text,
                context_hash=context_hash,
            )
            return

        # 5. Cachear resultado (mesmo se intent="none" — evita re-chamada).
        self._cache.put(context_hash, result)

        # 6. Publicar telemetria.
        self._publish_telemetry(
            meta=source_meta,
            intent=result.intent,
            num_candidates=len(result.candidates),
            inference_ms=result.inference_ms,
            cached=False,
            error="",
            context_text=text,
            context_hash=context_hash,
        )

        # 7. Publicar IntentCandidate se houver candidatos.
        if result.has_candidates:
            self._publish_intent_candidate(
                source_meta, result, context_hash, cached=False
            )

    # ------------------------------------------------------------------
    # Publicação de eventos
    # ------------------------------------------------------------------

    def _publish_intent_candidate(
        self,
        source_meta: EventMetadata,
        result: SemanticResult,
        context_hash: str,
        cached: bool,
    ) -> None:
        """Publica IntentCandidate no EventBus."""
        # Serializar candidatos para JSON.
        candidates_json = json.dumps(
            [c.to_dict() for c in result.candidates],
            ensure_ascii=False,
        )

        meta = EventMetadata.for_next(
            previous=source_meta,
            origin="SemanticEngine",
        )

        event = IntentCandidate(
            meta=meta,
            intent=result.intent,
            candidates_json=candidates_json,
            inference_ms=result.inference_ms,
            provider=result.provider,
            model=result.model,
            context_hash=context_hash,
            cached=cached,
        )
        self._bus.publish(event)

    def _publish_telemetry(
        self,
        meta: EventMetadata,
        intent: str,
        num_candidates: int,
        inference_ms: int,
        cached: bool,
        error: str,
        context_text: str,
        context_hash: str,
    ) -> None:
        """Publica SemanticInferenceCompleted (telemetria para o frontend)."""
        # Telemetria usa for_next para manter correlation_id.
        tele_meta = EventMetadata.for_next(
            previous=meta,
            origin="SemanticEngine",
        )
        event = SemanticInferenceCompleted(
            meta=tele_meta,
            intent=intent,
            num_candidates=num_candidates,
            inference_ms=inference_ms,
            provider=self._provider.name,
            model=self._provider.model_name,
            cached=cached,
            error=error,
            context_text=context_text[:200],  # limitar para depuração
            context_hash=context_hash,
        )
        self._bus.publish(event)

    # ------------------------------------------------------------------
    # Estatísticas
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Estatísticas do engine."""
        return {
            "total_calls": self._total_calls,
            "total_errors": self._total_errors,
            "total_cache_hits": self._total_cache_hits,
            "cache_stats": self._cache.stats(),
            "provider": self._provider.name,
            "model": self._provider.model_name,
            "enabled": self._enabled,
        }
