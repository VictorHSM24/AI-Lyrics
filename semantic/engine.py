"""semantic/engine.py — SemanticEngine (Sprint 20, Etapa 2 + Sprint 28).

Responsabilidade única:
  texto → entendimento semântico → lista de candidatos

Regras:
  - Assina SpeechCommittedWords (Sprint 28 — texto confiável, não partials).
  - Constrói contexto via ContextEngine.
  - Consulta cache antes de chamar o provider.
  - Chama SemanticProvider.infer() com timeout.
  - Valida rigorosamente o schema da resposta (Etapa 7 — Segurança).
  - Publica IntentCandidate (NUNCA ReferenceDetected).
  - Publica SemanticInferenceCompleted (telemetria para o frontend).
  - NUNCA consulta Holyrics, frontend, banco ou Searcher.
  - NUNCA publica ReferenceDetected.

Sprint 28 — Streaming First com LocalAgreement-2:
  O SemanticEngine agora consome SpeechCommittedWords (palavras confirmed
  por LocalAgreement-2) em vez de SpeechPartial/Updated. Committed words
  são texto confiável que não vai mudar mais — a inferência só dispara
  em texto estável, evitando resultados regressivos.

  Stale rejection: ao iniciar inferência, registrar correlation_id +
  timestamp. Ao completar, se correlation_id mudou (novo fluxo), o
  resultado é descartado.

Sprint 21.5 — Streaming Intelligence:
  Substitui a estratégia puramente temporal (debounce fixo) por uma
  política híbrida baseada em crescimento significativo + rate limit +
  debounce fallback.

  Gatilho de crescimento (durante fala contínua):
    - Dispara IMEDIATAMENTE quando o texto acumulou >= min_growth_chars
      (22) caracteres novos E >= min_append_words (3) palavras novas
      desde a última inferência, E >= min_interval_ms (1000ms) se
      passaram desde a última chamada.
    - Isto permite que "O Senhor é meu pastor..." gere inferência
      ANTES do silêncio, durante a fala contínua.

  Gatilho de debounce (fallback para pausa):
    - Se o gatilho de crescimento não dispara, agenda debounce
      (400ms). Se a pessoa para de falar, o timer expira e dispara
      a inferência com o texto acumulado.
    - Debounce reduzido de 800ms (Sprint 20) para 400ms (Sprint 21.5)
      pois agora o gatilho principal é o crescimento, não o debounce.

Sprint 20 — Semantic Understanding Engine.
Sprint 21.5 — Streaming Intelligence.
Sprint 28 — Streaming First com LocalAgreement-2.
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
    SpeechCommittedWords,
)
from pipeline.metadata import EventMetadata
from semantic.cache import SemanticCache
from semantic.context_engine import ContextEngine
from semantic.provider import SemanticProvider
from semantic.types import SemanticError, SemanticResult, SemanticTimeout
# Sprint 21.9 — Telemetria de observabilidade (não altera comportamento).
from telemetry import hooks as telemetry_hooks

logger = logging.getLogger(__name__)

__all__ = ["SemanticEngine"]


# Mínimo de caracteres para considerar invocar o LLM.
_MIN_TEXT_LENGTH = 8

# Debounce default em ms (espera parar de falar antes de invocar).
# Sprint 21.5 — reduzido de 800ms para 400ms. Agora o gatilho principal
# é o crescimento significativo (min_growth_chars + min_append_words),
# não o debounce. O debounce é apenas fallback para pausa na fala.
_DEFAULT_DEBOUNCE_MS = 400

# Sprint 21.5 — Streaming Intelligence.
# Gatilho de crescimento: dispara inferência durante fala contínua
# quando o texto acumulou conteúdo novo suficiente desde a última
# inferência. Conforme decisão do usuário:
#   - min_growth_chars = 20: captura "O Senhor é meu pastor" (21 chars)
#     e frases clássicas similares. Usuário pediu 20-24, escolhemos 20
#     para garantir que frases curtas mas identificáveis disparem.
#   - min_append_words = 3: filtra filler ("e", "né", "amém", "irmãos")
#   - min_interval_ms = 1000: máx 1 chamada/segundo (rate limit)
_DEFAULT_MIN_GROWTH_CHARS = 20
_DEFAULT_MIN_APPEND_WORDS = 3
_DEFAULT_MIN_INTERVAL_MS = 1000

# Sprint 23.1 — Command Trigger.
# Quando o pregador usa comandos imperativos ("coloca pra mim", "procura pra mim",
# etc.), o texto seguinte tem alta probabilidade de ser uma referência bíblica.
# Nestes casos, baixamos o threshold de growth para disparar a inferência
# mais cedo, sem esperar acumular 20 chars.
_COMMAND_PHRASES = frozenset({
    "coloca", "coloca pra mim", "coloca para mim",
    "procura", "procura pra mim", "procura para mim",
    "procura aí", "procura ai",
    "mostra", "mostra pra mim", "mostra para mim",
    "põe", "põe pra mim", "põe para mim", "poe", "poe pra mim",
    "bota", "bota pra mim", "bota para mim",
    "abre", "abre pra mim", "abre para mim",
    "joga", "joga pra mim", "joga para mim",
    "pula", "pula pra mim",
    "vai pra", "vai para",
})
_COMMAND_MIN_GROWTH_CHARS = 5
_COMMAND_MIN_APPEND_WORDS = 2
_COMMAND_MIN_INTERVAL_MS = 500


class SemanticEngine:
    """Camada de compreensão semântica.

    Assina SpeechCommittedWords no EventBus (Sprint 28 — texto confiável),
    constrói contexto, consulta cache, chama provider, publica IntentCandidate.

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
        # Sprint 21.5 — Streaming Intelligence.
        min_growth_chars: int = _DEFAULT_MIN_GROWTH_CHARS,
        min_append_words: int = _DEFAULT_MIN_APPEND_WORDS,
        min_interval_ms: int = _DEFAULT_MIN_INTERVAL_MS,
        # Sprint 22.0 — BibleRetriever (RAG Local). Opcional: se None,
        # o SemanticEngine opera no Modo Atual (LLM direto).
        bible_retriever: Any = None,
        rag_top_k: int = 20,
        rag_fallback_on_empty: bool = True,
        # Sprint 22.2 — ContextPolicy para priorização RAG. Opcional:
        # se None, o SemanticEngine usa o comportamento legado (sempre
        # inclui contexto do sermão no prompt RAG).
        context_policy: Any = None,
    ) -> None:
        self._bus = bus
        self._provider = provider
        self._context_engine = context_engine
        self._cache = cache
        self._session_id = session_id
        self._debounce_ms = debounce_ms
        self._timeout_ms = timeout_ms
        self._enabled = enabled
        # Sprint 21.5 — parâmetros da política de estabilidade.
        self._min_growth_chars = min_growth_chars
        self._min_append_words = min_append_words
        self._min_interval_ms = min_interval_ms
        # Sprint 22.0 — RAG Local.
        self._bible_retriever = bible_retriever
        self._rag_top_k = rag_top_k
        self._rag_fallback_on_empty = rag_fallback_on_empty
        # Sprint 22.2 — ContextPolicy.
        self._context_policy = context_policy

        # Estado do debounce.
        self._debounce_timer: threading.Timer | None = None
        self._pending_text: str = ""
        self._pending_meta: EventMetadata | None = None
        self._lock = threading.Lock()

        # Sprint 21.5 — estado da política de crescimento.
        # _last_inferred_text: texto enviado ao LLM na última inferência.
        #   Usado para calcular growth_chars e append_words do texto atual.
        # _last_inference_monotonic: timestamp monotônico da última
        #   inferência. Usado para rate limiting (min_interval_ms).
        # _growth_fired: flag temporária para distinguir se a inferência
        #   atual veio do gatilho de crescimento (True) ou do debounce
        #   (False). Setada em _schedule_inference, lida e limpa em
        #   _fire_inference.
        self._last_inferred_text: str = ""
        self._last_inference_monotonic: float = 0.0
        self._growth_fired: bool = False

        # Sprint 28 — stale rejection.
        # _inference_correlation_id: correlation_id da inferência em curso.
        #   Se mudar (novo fluxo) enquanto a inferência está rodando,
        #   o resultado é descartado ao completar.
        # _inference_in_progress: True se há inferência em curso.
        self._inference_correlation_id: str | None = None
        self._inference_in_progress: bool = False
        self._total_stale_rejected: int = 0

        # Estatísticas.
        self._total_calls = 0
        self._total_errors = 0
        self._total_cache_hits = 0
        # Sprint 21.5 — métricas da política de estabilidade.
        self._total_growth_triggers = 0
        self._total_debounce_triggers = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inscreve-se nos eventos do EventBus.

        Sprint 28 — inscreve em SpeechCommittedWords (não SpeechPartial/Updated).
        """
        if not self._enabled:
            logger.info("SemanticEngine: disabled, not subscribing")
            return
        self._bus.subscribe(SpeechCommittedWords, self._on_committed_words)
        logger.info(
            "SemanticEngine: started (provider=%s, model=%s, debounce=%dms, "
            "timeout=%dms, min_growth=%d chars, min_append=%d words, "
            "min_interval=%dms) — subscribed to SpeechCommittedWords",
            self._provider.name, self._provider.model_name,
            self._debounce_ms, self._timeout_ms,
            self._min_growth_chars, self._min_append_words,
            self._min_interval_ms,
        )

    def stop(self) -> None:
        """Para o engine e cancela debounce pendente."""
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
        try:
            self._bus.unsubscribe(SpeechCommittedWords, self._on_committed_words)
        except Exception:
            pass
        logger.info("SemanticEngine: stopped")

    # ------------------------------------------------------------------
    # Handlers de eventos
    # ------------------------------------------------------------------

    def _on_committed_words(self, event: SpeechCommittedWords) -> None:
        """Recebe SpeechCommittedWords — avalia política de disparo.

        Sprint 28 — usa full_committed_text (texto acumulado confiável)
        em vez de partial text. Committed words são estáveis por
        definição (LocalAgreement-2), então a inferência só dispara
        em texto que não vai mudar mais.
        """
        self._schedule_inference(event.full_committed_text, event.meta)

    def _schedule_inference(self, text: str, meta: EventMetadata) -> None:
        """Avalia política de disparo e agenda ou executa inferência.

        Sprint 21.5 — Streaming Intelligence.
        Política híbrida com dois gatilhos:

        1. Gatilho de crescimento (durante fala contínua):
           Dispara IMEDIATAMENTE quando:
             growth_chars >= min_growth_chars (22)
             AND append_words >= min_append_words (3)
             AND elapsed_ms >= min_interval_ms (1000)
           Onde:
             growth_chars = chars novos desde a última inferência
             append_words = palavras novas desde a última inferência
             elapsed_ms = ms desde a última inferência

        2. Gatilho de debounce (fallback para pausa na fala):
           Se o gatilho de crescimento não dispara, agenda debounce
           (400ms). Se a pessoa para de falar, o timer expira e
           dispara a inferência com o texto acumulado.
        """
        if not self._enabled:
            return
        text = text.strip()
        if len(text) < _MIN_TEXT_LENGTH:
            return

        with self._lock:
            # Cancelar debounce anterior (se houver).
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None

            # Sprint 21.5 — avaliar gatilho de crescimento.
            should_fire_now = self._should_fire_on_growth(text)

            # Guardar texto e meta para inferência.
            self._pending_text = text
            self._pending_meta = meta

            if should_fire_now:
                # Gatilho de crescimento — marcar para _fire_inference
                # saber que foi growth trigger (não debounce).
                self._growth_fired = True
                self._total_growth_triggers += 1
                logger.debug(
                    "SemanticEngine: growth trigger fired "
                    "(text=%d chars, last=%d chars, growth=%d, append_words=%d)",
                    len(text), len(self._last_inferred_text),
                    self._count_growth_chars(text),
                    self._count_append_words(text),
                )
                # Não agendar timer — executar fora do lock.
            else:
                # Gatilho de debounce — agendar fallback para pausa.
                self._debounce_timer = threading.Timer(
                    self._debounce_ms / 1000.0,
                    self._fire_inference,
                )
                self._debounce_timer.daemon = True
                self._debounce_timer.start()

        if should_fire_now:
            # Executar fora do lock para evitar deadlock com _fire_inference.
            self._fire_inference()

    def _should_fire_on_growth(self, text: str) -> bool:
        """Avalia se o gatilho de crescimento deve disparar (Sprint 21.5).

        Retorna True se:
          growth_chars >= min_growth_chars
          AND append_words >= min_append_words
          AND elapsed_ms >= min_interval_ms

        Sprint 23.1 — Command Trigger:
          Se o texto contém um comando imperativo ("coloca pra mim", etc.),
          usa thresholds reduzidos (5 chars, 2 palavras, 500ms) pois o
          texto seguinte tem alta probabilidade de ser uma referência.

        Deve ser chamado sob self._lock.
        """
        now = time.monotonic()

        # Sprint 23.1 — detectar comando imperativo para baixar thresholds.
        text_lower = text.lower()
        has_command = any(
            phrase in text_lower for phrase in _COMMAND_PHRASES
        )
        if has_command:
            min_growth = _COMMAND_MIN_GROWTH_CHARS
            min_words = _COMMAND_MIN_APPEND_WORDS
            min_interval = _COMMAND_MIN_INTERVAL_MS
        else:
            min_growth = self._min_growth_chars
            min_words = self._min_append_words
            min_interval = self._min_interval_ms

        # Calcular tempo desde a última inferência.
        if self._last_inference_monotonic == 0.0:
            # Nunca houve inferência — tratar como infinito (sempre passa).
            elapsed_ms = float("inf")
        else:
            elapsed_ms = (now - self._last_inference_monotonic) * 1000.0

        if elapsed_ms < min_interval:
            return False

        # Calcular crescimento em caracteres desde a última inferência.
        growth_chars = self._count_growth_chars(text)
        if growth_chars < min_growth:
            return False

        # Calcular palavras novas desde a última inferência.
        append_words = self._count_append_words(text)
        if append_words < min_words:
            return False

        return True

    def _count_growth_chars(self, text: str) -> int:
        """Conta caracteres novos desde a última inferência (Sprint 21.5).

        Se text começa com _last_inferred_text (prefixo estável — Whisper
        só adiciona ao final), growth = len(text) - len(last).
        Caso contrário (Whisper reescreveu), growth = len(text) — tratar
        como texto totalmente novo.

        Deve ser chamado sob self._lock.
        """
        if not self._last_inferred_text:
            return len(text)
        if text.startswith(self._last_inferred_text):
            return len(text) - len(self._last_inferred_text)
        # Whisper reescreveu o início — texto totalmente novo.
        return len(text)

    def _count_append_words(self, text: str) -> int:
        """Conta palavras novas desde a última inferência (Sprint 21.5).

        Se text começa com _last_inferred_text, append = text[len(last):].
        Caso contrário, append = text inteiro.

        Deve ser chamado sob self._lock.
        """
        if not self._last_inferred_text:
            return len(text.split())
        if text.startswith(self._last_inferred_text):
            appended = text[len(self._last_inferred_text):].strip()
            return len(appended.split()) if appended else 0
        # Whisper reescreveu — contar todas as palavras.
        return len(text.split())

    # ------------------------------------------------------------------
    # Inferência
    # ------------------------------------------------------------------

    def _fire_inference(self) -> None:
        """Executa inferência (após debounce expirar ou gatilho de crescimento).

        Sprint 21.5 — chamado de duas formas:
        1. Pelo timer de debounce (após pausa na fala).
        2. Diretamente por _schedule_inference (gatilho de crescimento).
        """
        with self._lock:
            text = self._pending_text
            meta = self._pending_meta
            self._debounce_timer = None
            self._pending_text = ""
            self._pending_meta = None
            # Sprint 21.5 — distinguir origem do disparo para métricas.
            if self._growth_fired:
                # Já contado em _schedule_inference.
                self._growth_fired = False
            else:
                self._total_debounce_triggers += 1
            # Sprint 21.5 — registrar estado para a política de crescimento.
            # Mesmo que a inferência falhe abaixo, o texto foi "consumido"
            # pela política — não queremos re-disparar para o mesmo texto.
            self._last_inferred_text = text
            self._last_inference_monotonic = time.monotonic()
            # Sprint 28 — stale rejection: registrar correlation_id da
            # inferência em curso para descartar se o fluxo mudar.
            self._inference_correlation_id = meta.correlation_id if meta else None
            self._inference_in_progress = True

        if not text or meta is None:
            with self._lock:
                self._inference_in_progress = False
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
        finally:
            with self._lock:
                self._inference_in_progress = False

    def _run_inference(self, text: str, source_meta: EventMetadata) -> None:
        """Constrói contexto, consulta cache, chama provider, publica eventos."""
        self._total_calls += 1

        # 1. Construir contexto.
        context = self._context_engine.build(
            current_text=text,
            session_id=self._session_id,
            correlation_id=source_meta.correlation_id,
        )

        # Sprint 22.0 — RAG Local: recuperar candidatos da Bíblia local
        # e injetá-los no contexto antes de consultar o cache/provider.
        # O retriever é opcional; se None, opera no Modo Atual.
        if self._bible_retriever is not None and self._bible_retriever.is_ready:
            try:
                rag_candidates = self._bible_retriever.retrieve(
                    text, top_k=self._rag_top_k
                )
            except Exception as e:
                logger.warning(
                    "SemanticEngine: BibleRetriever.retrieve failed: %s — "
                    "falling back to current mode", e,
                )
                rag_candidates = []
            if rag_candidates:
                # Sprint 22.2 — Aplicar ContextPolicy para decidir quanto
                # do contexto do sermão incluir no prompt.
                from dataclasses import replace as _dc_replace
                from knowledge.types import compute_retrieval_meta
                context_decision = None
                if self._context_policy is not None:
                    meta = compute_retrieval_meta(rag_candidates)
                    context_decision = self._context_policy.decide(
                        meta=meta,
                        sermon_book=context.sermon_book or None,
                        sermon_confidence=context.sermon_book_confidence,
                    )
                    # Sprint 22.2 — telemetria da decisão da ContextPolicy.
                    telemetry_hooks.context_policy_decision(
                        correlation_id=source_meta.correlation_id,
                        decision=context_decision.to_dict(),
                    )
                    logger.debug(
                        "SemanticEngine: ContextPolicy → level=%s include=%s "
                        "reason=%s (top1=%.2f gap=%.2f sermon_conf=%.2f)",
                        context_decision.level,
                        context_decision.include_context,
                        context_decision.reason,
                        context_decision.top1_score,
                        context_decision.gap,
                        context_decision.sermon_confidence,
                    )
                # Reconstruir contexto com candidatos RAG e decisão.
                context = _dc_replace(
                    context,
                    rag_candidates=tuple(rag_candidates),
                    correlation_id=source_meta.correlation_id,
                    context_decision=context_decision,
                )
            elif not self._rag_fallback_on_empty:
                # Sem candidatos e fallback desabilitado: publicar none.
                logger.debug(
                    "SemanticEngine: RAG returned 0 candidates, "
                    "fallback_on_empty=False → intent=none"
                )
                telemetry_hooks.bible_retriever_decision(
                    correlation_id=source_meta.correlation_id,
                    candidates_in=[],
                    chosen=None,
                    reason="no_candidates",
                    decision_ms=0.0,
                )
                return

        context_hash = context.context_hash()

        # Sprint 21.9 — telemetria: registrar input recebido pelo SemanticEngine.
        telemetry_hooks.semantic_input(
            correlation_id=source_meta.correlation_id,
            text=text,
            recent_text=getattr(context, "recent_text", "") or "",
            trigger="growth" if self._growth_fired else "debounce",
            growth_chars=self._count_growth_chars(text) if self._last_inferred_text else len(text),
            append_words=self._count_append_words(text) if self._last_inferred_text else len(text.split()),
            cached=False,
            context_hash=context_hash,
        )

        # 2. Consultar cache.
        cached_result = self._cache.get(context_hash)
        if cached_result is not None:
            self._total_cache_hits += 1
            logger.debug("SemanticEngine: cache hit (hash=%s)", context_hash)
            # Sprint 21.9 — telemetria: cache hit.
            telemetry_hooks.semantic_result(
                correlation_id=source_meta.correlation_id,
                intent=cached_result.intent,
                candidates=[c.to_dict() for c in cached_result.candidates],
                inference_ms=0,
                cached=True,
                context_hash=context_hash,
            )
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
            # Sprint 21.9 — telemetria: provider indisponível.
            telemetry_hooks.semantic_result(
                correlation_id=source_meta.correlation_id,
                intent="",
                candidates=[],
                inference_ms=0,
                cached=False,
                context_hash=context_hash,
                error=f"provider {self._provider.name} not available",
            )
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
            # Sprint 21.9 — telemetria: timeout.
            telemetry_hooks.semantic_result(
                correlation_id=source_meta.correlation_id,
                intent="",
                candidates=[],
                inference_ms=self._timeout_ms,
                cached=False,
                context_hash=context_hash,
                error=f"timeout: {e}",
            )
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
            # Sprint 21.9 — telemetria: erro do provider.
            telemetry_hooks.semantic_result(
                correlation_id=source_meta.correlation_id,
                intent="",
                candidates=[],
                inference_ms=0,
                cached=False,
                context_hash=context_hash,
                error=f"provider error: {e}",
            )
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

        # Sprint 28 — stale rejection: se o correlation_id mudou enquanto
        # a inferência estava em curso (novo fluxo começou), descartar o
        # resultado. O texto atual já é diferente do que foi inferido.
        # Nota: o plano §6.10 menciona "correlation_id mudou OU texto atual
        # difere". Com LocalAgreement-2, committed words são estáveis por
        # definição — se o correlation_id é o mesmo, o texto só cresce
        # (não reescreve), então a verificação de texto é redundante.
        with self._lock:
            current_corr = self._inference_correlation_id
            inference_corr = source_meta.correlation_id
        if current_corr is not None and current_corr != inference_corr:
            self._total_stale_rejected += 1
            logger.info(
                "SemanticEngine: stale inference rejected "
                "(inference_corr=%s, current_corr=%s, intent=%s)",
                inference_corr, current_corr, result.intent,
            )
            telemetry_hooks.semantic_result(
                correlation_id=source_meta.correlation_id,
                intent="",
                candidates=[],
                inference_ms=result.inference_ms,
                cached=False,
                context_hash=context_hash,
                error="stale_rejected",
            )
            return

        # 6. Publicar telemetria.
        # Sprint 21.9 — telemetria: resultado final da inferência.
        telemetry_hooks.semantic_result(
            correlation_id=source_meta.correlation_id,
            intent=result.intent,
            candidates=[c.to_dict() for c in result.candidates],
            inference_ms=result.inference_ms,
            cached=False,
            context_hash=context_hash,
        )
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
            # Sprint 21.5 — métricas da política de estabilidade.
            "total_growth_triggers": self._total_growth_triggers,
            "total_debounce_triggers": self._total_debounce_triggers,
            "min_growth_chars": self._min_growth_chars,
            "min_append_words": self._min_append_words,
            "min_interval_ms": self._min_interval_ms,
            # Sprint 28 — métricas de stale rejection.
            "total_stale_rejected": self._total_stale_rejected,
        }
