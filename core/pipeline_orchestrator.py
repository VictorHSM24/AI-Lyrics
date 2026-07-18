"""Orquestrador do pipeline (submódulo interno de core/pipeline.py).

Responsabilidade: processar uma utterance completa, chamando os stages
na ordem correta, decidindo quais stages executar, construindo LogEntry
e atualizando PipelineMetrics.

Este módulo é interno ao pipeline. Módulos externos não devem importá-lo
diretamente — a API pública do pipeline está em core/pipeline.py.

Fluxo obrigatório (Blueprint §14):
    texto → parser → search (se necessário) → decision.evaluate()
    → decision.execute() (se outcome == "execute")

Limites explícitos (o que este módulo NÃO faz):
  - Não implementa lifecycle (start/stop/healthcheck).
  - Não gerencia threads, filas ou loops asyncio.
  - Não captura áudio nem executa STT.
  - Não chama LLM diretamente quando llm_client é None (sinalizado via
    decision.outcome == "forward_to_llm"). Quando llm_client é fornecido,
    chama LLM apenas se intent.action == "uncertain".
  - Não persiste logs (apenas constrói LogEntry; persistência é do
    módulo logs/).

Design:
  - process_utterance() é o ponto único de entrada.
  - Cada stage é chamado via pipeline_stages (run_parser, run_search,
    run_decision, execute_decision).
  - Erros em qualquer stage são capturados, registrados em
    PipelineMetrics, e a execução continua (não derruba o pipeline).
  - LogEntry é sempre construído, mesmo em caso de erro (campos de
    stages não executados ficam vazios).
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from core.confirmation import (
    CandidateList,
    CandidateSelector,
    ConfirmationPolicy,
    ProcessResult,
)
from core.exceptions import PipelineError
from core.pipeline_metrics import PipelineMetrics, StageTiming
from core.pipeline_stages import (
    execute_decision,
    run_decision,
    run_llm,
    run_parser,
    run_search,
)
from core.types import Decision, Intent, LogEntry, Utterance, VerseRef

if TYPE_CHECKING:
    from busca.knowledge_enricher import KnowledgeEnricher
    from busca.query_planner import QueryPlan, QueryPlanner
    from busca.reranker import LLMReranker
    from busca.searcher import SearchResult, Searcher
    from core.decision import DecisionEngine
    from estado.state import BibleStateManager
    from llm.client import LLMClient
    from parser.parser import Parser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PipelineOrchestrator
# ---------------------------------------------------------------------------


class PipelineOrchestrator:
    """Orquestra o processamento de uma utterance pelo pipeline.

    Recebe as dependências via construtor (injeção explícita). Cada
    chamada a process_utterance() executa o fluxo completo de stages
    para uma utterance e retorna a LogEntry correspondente.

    Args:
        parser: instância de Parser.
        searcher: instância de Searcher (pode ser None se busca não
            estiver disponível).
        decision_engine: instância de DecisionEngine.
        state_manager: BibleStateManager para obter estado atual.
        metrics: PipelineMetrics a atualizar (criado internamente se
            não fornecido).
        llm_client: instância de LLMClient (opcional; se None,
            uncertain → forward_to_llm sem chamar LLM).

    Example:
        >>> orch = PipelineOrchestrator(parser, searcher, engine, state)
        >>> entry = orch.process_utterance(utterance)
    """

    def __init__(
        self,
        parser: Parser,
        searcher: Searcher | None,
        decision_engine: DecisionEngine,
        state_manager: BibleStateManager,
        metrics: PipelineMetrics | None = None,
        llm_client: LLMClient | None = None,
        reranker: LLMReranker | None = None,
        knowledge_enricher: KnowledgeEnricher | None = None,
    ) -> None:
        self._parser = parser
        self._searcher = searcher
        self._engine = decision_engine
        self._state = state_manager
        self._metrics = metrics or PipelineMetrics()
        self._llm_client = llm_client
        self._reranker = reranker
        self._knowledge_enricher = knowledge_enricher
        # QueryPlanner é stateless — instanciar uma vez
        # enable_semantic=True apenas se Searcher tem EmbeddingSearcher ativo
        from busca.query_planner import QueryPlanner
        has_embeddings = searcher is not None and searcher.has_embeddings
        self._query_planner = QueryPlanner(enable_semantic=has_embeddings)

    @property
    def metrics(self) -> PipelineMetrics:
        """Métricas acumuladas do pipeline."""
        return self._metrics

    # ------------------------------------------------------------------
    # Processamento principal
    # ------------------------------------------------------------------

    def process_utterance(self, utterance: Utterance) -> LogEntry:
        """Processa uma utterance completa pelo pipeline.

        Fluxo:
            1. parser.parse(text, state) → Intent
            2. Se action == "uncertain" e llm_client disponível:
               llm_client.interpret(text, state) → Intent (substitui)
            3. Se action == "search": searcher.search(query) → results
            4. decision_engine.evaluate(intent, c_stt, results) → Decision
            5. Se outcome == "execute": engine.execute(decision, results)
            6. Construir LogEntry com timing de cada stage

        Erros em qualquer stage são capturados, registrados em metrics,
        e não derrubam o pipeline. A LogEntry é sempre retornada.

        Args:
            utterance: Utterance com text, c_stt, audio_ms.

        Returns:
            LogEntry com timing e resultado de cada stage.
        """
        return self.process_utterance_detailed(utterance).log_entry

    def process_utterance_detailed(self, utterance: Utterance) -> "ProcessResult":
        """Processa uma utterance e retorna ProcessResult com todos os objetos.

        Idêntico a process_utterance() em lógica, mas retorna um ProcessResult
        que expõe LogEntry, Decision, search_results e candidates (quando
        ambíguo) para a interface decidir o próximo passo.

        Args:
            utterance: Utterance com text, c_stt, audio_ms.

        Returns:
            ProcessResult com log_entry, decision, search_results,
            candidates e requires_confirmation.
        """
        t0 = time.monotonic()
        self._metrics.record_utterance()

        exec_id = uuid.uuid4().hex[:12]
        ts = datetime.now(timezone.utc).isoformat()

        # Timings coletados durante a execução
        parser_timing: StageTiming | None = None
        llm_timing: StageTiming | None = None
        search_timing: StageTiming | None = None
        decision_timing: StageTiming | None = None
        holyrics_timing: StageTiming | None = None

        intent: Intent | None = None
        llm_intent: Intent | None = None  # Intent retornado pelo LLM (para log)
        search_results: list[SearchResult] | None = None
        decision: Decision | None = None
        ref: VerseRef | None = None

        # 1. Parser
        try:
            intent, parser_timing = run_parser(
                self._parser, utterance.text, self._state.current()
            )
        except PipelineError as e:
            parser_timing = e.stage_timing or StageTiming(
                "parser", 0.0, False, str(e)
            )
            self._metrics.record(parser_timing)
            logger.error("parser stage failed: %s", e)
            return ProcessResult(
                log_entry=self._build_log_entry(
                    ts, exec_id, utterance, t0,
                    parser_timing, None, None, None, None,
                    intent=None, llm_intent=None, search_results=None,
                    decision=None, ref=None,
                ),
            )
        self._metrics.record(parser_timing)

        # 1b. LLM (apenas se parser retornar uncertain e llm_client disponível)
        if intent.action == "uncertain" and self._llm_client is not None:
            try:
                llm_intent, llm_timing = run_llm(
                    self._llm_client, utterance.text, self._state.current()
                )
            except PipelineError as e:
                llm_timing = e.stage_timing or StageTiming(
                    "llm", 0.0, False, str(e)
                )
                logger.error("llm stage failed: %s", e)
                llm_intent = Intent(
                    action="none", confidence=0.0, source="llm",
                    raw=utterance.text,
                )
            self._metrics.record(llm_timing)

            # Log estruturado do LLM
            logger.info(
                "LLM: available=True latency_ms=%.1f action=%s confidence=%.2f%s",
                llm_timing.duration_ms,
                llm_intent.action,
                llm_intent.confidence,
                f' query="{llm_intent.query}"' if llm_intent.query else "",
            )

            # Anti-loop: se LLM retornar uncertain, converter para none
            if llm_intent.action == "uncertain":
                logger.warning(
                    "llm returned uncertain — converting to none to avoid loop"
                )
                llm_intent = Intent(
                    action="none",
                    confidence=llm_intent.confidence,
                    source="llm",
                    raw=utterance.text,
                )

            # Substituir intent pelo do LLM
            intent = llm_intent
        elif intent.action == "uncertain" and self._llm_client is None:
            # LLM não disponível — manter comportamento atual (forward_to_llm)
            logger.info("LLM: skipped=True reason=llm_not_available")
        elif intent.action != "uncertain" and self._llm_client is not None:
            # Parser resolveu — LLM não é chamado
            logger.info("LLM: skipped=True reason=parser_resolved")

        # 2. Search (se necessário)
        if intent.action == "search" and self._searcher is not None:
            try:
                # Se o Intent tem enrichment (do LLM), usar QueryPlanner
                # + search_with_plan (múltiplas estratégias + ranking composto).
                # Caso contrário, usar search() tradicional (compatibilidade).
                if intent.enrichment is not None:
                    search_results, search_timing = self._run_search_with_plan(
                        intent, utterance,
                    )
                else:
                    search_results, search_timing = run_search(
                        self._searcher,
                        intent.query or utterance.text,
                        state=self._state.current(),
                    )
                # Reranking opcional por LLM (se habilitado e há candidatos)
                if (
                    self._reranker is not None
                    and search_results is not None
                    and len(search_results) > 1
                ):
                    search_results = self._run_reranking(
                        intent.query or utterance.text,
                        search_results,
                    )
            except PipelineError as e:
                search_timing = e.stage_timing or StageTiming(
                    "search", 0.0, False, str(e)
                )
                logger.error("search stage failed: %s", e)
                # Continua com search_results=None — decision vai tratar
        elif intent.action == "search" and self._searcher is None:
            # Busca não disponível — registrar como erro de search
            search_timing = StageTiming(
                "search", 0.0, False, "searcher not available"
            )
            logger.warning("search stage skipped: searcher not available")

        if search_timing is not None:
            self._metrics.record(search_timing)

        # 3. Decision.evaluate
        try:
            decision, decision_timing = run_decision(
                self._engine, intent, utterance.c_stt, search_results
            )
        except PipelineError as e:
            decision_timing = e.stage_timing or StageTiming(
                "decision", 0.0, False, str(e)
            )
            self._metrics.record(decision_timing)
            logger.error("decision stage failed: %s", e)
            return ProcessResult(
                log_entry=self._build_log_entry(
                    ts, exec_id, utterance, t0,
                    parser_timing, llm_timing, search_timing, decision_timing, None,
                    intent=intent, llm_intent=llm_intent, search_results=search_results,
                    decision=None, ref=None,
                ),
                search_results=search_results,
            )
        self._metrics.record(decision_timing)

        # 4. Execute (se outcome == "execute")
        if decision.outcome == "execute":
            try:
                ref, holyrics_timing = execute_decision(
                    self._engine, decision, search_results
                )
                self._metrics.record_execute()
            except PipelineError as e:
                holyrics_timing = e.stage_timing or StageTiming(
                    "holyrics", 0.0, False, str(e)
                )
                logger.error("execute stage failed: %s", e)
        # outcome == "confirm" → não executa (UI trata confirmação)
        # outcome == "ignore" → nada a fazer
        # outcome == "forward_to_llm" → llm_client is None; log only

        if holyrics_timing is not None:
            self._metrics.record(holyrics_timing)

        log_entry = self._build_log_entry(
            ts, exec_id, utterance, t0,
            parser_timing, llm_timing, search_timing, decision_timing, holyrics_timing,
            intent=intent, llm_intent=llm_intent, search_results=search_results,
            decision=decision, ref=ref,
        )

        # Construir candidates se ambíguo com >= 2 resultados
        candidates: CandidateList | None = None
        requires_confirmation = False
        if decision is not None:
            # Política de confirmação: hoje apenas encapsula
            # decision.outcome == "confirm" → ambiguous=True.
            # Futuramente pode incorporar score_gap, top_k, confidence, etc.
            policy = ConfirmationPolicy()
            ambiguous = decision.outcome == "confirm"
            total_results = len(search_results) if search_results else 0
            requires_confirmation = policy.requires_confirmation(
                ambiguous=ambiguous,
                total_results=total_results,
            )
            if (
                search_results is not None
                and len(search_results) >= 2
                and search_results[0].ambiguous
            ):
                query = intent.query if intent else None
                selector = CandidateSelector(self._engine)
                candidates = selector.build_candidates(search_results, query=query)

        return ProcessResult(
            log_entry=log_entry,
            decision=decision,
            search_results=search_results,
            candidates=candidates,
            requires_confirmation=requires_confirmation,
        )

    # ------------------------------------------------------------------
    # Search com QueryPlanner (múltiplas estratégias + ranking composto)
    # ------------------------------------------------------------------

    def _run_search_with_plan(
        self,
        intent: Intent,
        utterance: Utterance,
    ) -> tuple[list[SearchResult] | None, StageTiming]:
        """Executa busca usando QueryPlanner + search_with_plan.

        Fluxo:
            1. KnowledgeEnricher: enriquecer Intent com conhecimento bíblico.
            2. Construir QueryPlan a partir do Intent + KnowledgeMatch.
            3. Chamar searcher.search_with_plan(plan).
            4. Medir tempo e construir StageTiming.
        """
        t0 = time.monotonic()
        try:
            # Knowledge enrichment (entre LLM e QueryPlanner)
            knowledge_match = None
            if self._knowledge_enricher is not None:
                knowledge_match = self._knowledge_enricher.enrich(intent)
                if knowledge_match.is_found:
                    logger.info(
                        "knowledge_enricher: concept=%r books=%s chapters=%s",
                        knowledge_match.concept,
                        knowledge_match.books,
                        knowledge_match.chapters,
                    )

            plan = self._query_planner.plan(intent, knowledge=knowledge_match)
            results = self._searcher.search_with_plan(
                plan,
                state=self._state.current(),
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            kb_info = (
                f" kb={knowledge_match.concept}" if knowledge_match and knowledge_match.is_found else ""
            )
            timing = StageTiming(
                "search", elapsed_ms, True,
                f"plan: keywords={len(plan.keywords)} "
                f"strategies={plan.search_modes} results={len(results)}{kb_info}",
            )
            logger.info(
                "search_with_plan: keywords=%d strategies=%s results=%d "
                "time=%.1fms%s",
                len(plan.keywords),
                plan.search_modes,
                len(results),
                elapsed_ms,
                kb_info,
            )
            return results, timing
        except Exception as e:
            elapsed_ms = (time.monotonic() - t0) * 1000
            timing = StageTiming(
                "search", elapsed_ms, False, f"plan failed: {e}",
            )
            logger.error("search_with_plan failed: %s", e)
            return None, timing

    def _run_reranking(
        self,
        query: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """Executa reranking por LLM (opcional, com fallback)."""
        if self._reranker is None or not results or len(results) <= 1:
            return results
        t0 = time.monotonic()
        try:
            reranked = self._reranker.rerank(query, results)
            elapsed_ms = (time.monotonic() - t0) * 1000
            if reranked is not results:
                logger.info(
                    "rerank: query=%r time=%.1fms top_changed=%s",
                    query[:60],
                    elapsed_ms,
                    reranked[0].reference != results[0].reference,
                )
            return reranked
        except Exception as e:
            logger.warning("rerank failed: %s — using original order", e)
            return results

    # ------------------------------------------------------------------
    # Construção de LogEntry
    # ------------------------------------------------------------------

    def _build_log_entry(
        self,
        ts: str,
        exec_id: str,
        utterance: Utterance,
        t0: float,
        parser_timing: StageTiming | None,
        llm_timing: StageTiming | None,
        search_timing: StageTiming | None,
        decision_timing: StageTiming | None,
        holyrics_timing: StageTiming | None,
        *,
        intent: Intent | None,
        llm_intent: Intent | None,
        search_results: list[SearchResult] | None,
        decision: Decision | None,
        ref: VerseRef | None,
    ) -> LogEntry:
        """Constrói LogEntry com timing e resultado de cada stage.

        Stages não executados ou que falharam têm campos preenchidos
        com o que estiver disponível (duration_ms=0, error=...).
        """
        total_ms = int((time.monotonic() - t0) * 1000.0)

        # LLM dict
        llm_dict: dict = {}
        if llm_timing is not None:
            llm_dict["duration_ms"] = llm_timing.duration_ms
            llm_dict["success"] = llm_timing.success
            if llm_timing.error_msg:
                llm_dict["error"] = llm_timing.error_msg
        if llm_intent is not None:
            llm_dict["action"] = llm_intent.action
            llm_dict["confidence"] = llm_intent.confidence
            llm_dict["source"] = llm_intent.source
            if llm_intent.query:
                llm_dict["query"] = llm_intent.query
            if llm_intent.book:
                llm_dict["book"] = llm_intent.book
            if llm_intent.chapter is not None:
                llm_dict["chapter"] = llm_intent.chapter
        elif intent is not None and intent.action != "uncertain" and self._llm_client is not None:
            # LLM disponível mas não chamado (parser resolveu)
            llm_dict["skipped"] = True
            llm_dict["reason"] = "parser_resolved"
        elif self._llm_client is None and intent is not None and intent.action == "uncertain":
            # LLM não disponível e parser retornou uncertain
            llm_dict["skipped"] = True
            llm_dict["reason"] = "llm_not_available"

        # Parser dict
        parser_dict: dict = {}
        if parser_timing is not None:
            parser_dict["duration_ms"] = parser_timing.duration_ms
            parser_dict["success"] = parser_timing.success
            if parser_timing.error_msg:
                parser_dict["error"] = parser_timing.error_msg
        if intent is not None:
            parser_dict["action"] = intent.action
            parser_dict["confidence"] = intent.confidence
            parser_dict["raw"] = intent.raw[:500]  # truncar (Blueprint §13)

        # Search dict
        search_dict: dict = {}
        if search_timing is not None:
            search_dict["duration_ms"] = search_timing.duration_ms
            search_dict["success"] = search_timing.success
            if search_timing.error_msg:
                search_dict["error"] = search_timing.error_msg
        if search_results is not None:
            search_dict["results_count"] = len(search_results)
            if search_results:
                top = search_results[0]
                search_dict["top_reference"] = top.reference
                search_dict["top_score"] = top.score
                search_dict["ambiguous"] = top.ambiguous

        # Decision dict
        decision_dict: dict = {}
        if decision_timing is not None:
            decision_dict["duration_ms"] = decision_timing.duration_ms
            decision_dict["success"] = decision_timing.success
            if decision_timing.error_msg:
                decision_dict["error"] = decision_timing.error_msg
        if decision is not None:
            decision_dict["outcome"] = decision.outcome
            decision_dict["confidence"] = decision.confidence
            decision_dict["reason"] = decision.reason

        # Holyrics dict
        holyrics_dict: dict = {}
        if holyrics_timing is not None:
            holyrics_dict["duration_ms"] = holyrics_timing.duration_ms
            holyrics_dict["success"] = holyrics_timing.success
            if holyrics_timing.error_msg:
                holyrics_dict["error"] = holyrics_timing.error_msg
        if ref is not None:
            holyrics_dict["ref"] = ref.reference
            holyrics_dict["version"] = ref.version

        # Confidence dict
        confidence_dict: dict = {
            "c_stt": utterance.c_stt,
        }
        if intent is not None:
            confidence_dict["c_intent"] = intent.confidence
        if search_results:
            confidence_dict["c_search"] = search_results[0].c_search
        if decision is not None and decision.confidence_breakdown is not None:
            cb = decision.confidence_breakdown
            confidence_dict["c_stt"] = cb.c_stt
            confidence_dict["c_intent"] = cb.c_intent
            confidence_dict["c_search"] = cb.c_search
            confidence_dict["c_final"] = cb.c_final
        elif decision is not None:
            confidence_dict["c_final"] = decision.confidence

        return LogEntry(
            ts=ts,
            id=exec_id,
            audio_ms=utterance.audio_ms,
            stt={
                "c_stt": utterance.c_stt,
                "audio_ms": utterance.audio_ms,
            },
            parser=parser_dict,
            llm=llm_dict,
            search=search_dict,
            confidence=confidence_dict,
            decision=decision_dict,
            holyrics=holyrics_dict,
            cache={},  # Cache não implementado
            total_ms=total_ms,
        )
