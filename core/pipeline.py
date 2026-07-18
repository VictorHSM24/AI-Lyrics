"""Pipeline — fachada pública do orquestrador do sistema.

Responsabilidade exclusiva: lifecycle (start/stop/healthcheck) e
delegação de processamento ao orquestrador interno.

Este módulo é o **único** ponto de entrada do pipeline para módulos
externos. Os submódulos internos (pipeline_orchestrator, pipeline_stages,
pipeline_metrics) não devem ser importados diretamente.

Limites explícitos (o que este módulo NÃO faz):
  - Não contém lógica de stages, orquestração ou decisão.
  - Não gerencia threads, filas asyncio nem captura de áudio.
  - Não constrói LogEntry diretamente (delegado ao orquestrador).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from config import BookTable, Config, load_books, load_config
from core.confirmation import ProcessResult
from core.decision import DecisionEngine
from core.exceptions import PipelineError
from core.pipeline_metrics import PipelineMetrics
from core.pipeline_orchestrator import PipelineOrchestrator
from core.types import LogEntry, Utterance
from estado.state import BibleStateManager, load_bible_structure
from integracao_holyrics import HolyricsClient
from llm import LLMClient
from parser.books import ParserBookTable
from parser.parser import Parser
from busca.searcher import Searcher

logger = logging.getLogger(__name__)


@dataclass
class ApplicationContext:
    """Container de dependências do pipeline, criado durante start().

    Atributos:
        parser: parser de comandos bíblicos.
        searcher: mecanismo de busca (None se DB não disponível).
        decision_engine: motor de decisão.
        state_manager: gerenciador de estado da Bíblia.
        holyrics: cliente Holyrics.
        book_table: tabela de livros canônica.
        llm_client: cliente LLM (None se Ollama offline).
        reranker: reranker por LLM (None se não configurado).
    """

    parser: Parser
    searcher: Searcher | None
    decision_engine: DecisionEngine
    state_manager: BibleStateManager
    holyrics: HolyricsClient
    book_table: BookTable
    llm_client: LLMClient | None = None
    reranker: object | None = None  # LLMReranker (evita import circular)
    knowledge_enricher: object | None = None  # KnowledgeEnricher


class Pipeline:
    """Fachada pública do pipeline de processamento de comandos bíblicos.

    Lifecycle: Pipeline(config) → start() → process_utterance() → stop().

    Args:
        config: Config carregada ou path para config.yaml.
        book_table: BookTable opcional (carregada de config/books.json
            se omitida).

    Example:
        >>> pipeline = Pipeline("config/config.yaml")
        >>> pipeline.start()
        >>> entry = pipeline.process_utterance(utterance)
        >>> pipeline.stop()
    """

    def __init__(self, config: Config | str, book_table: BookTable | None = None) -> None:
        if isinstance(config, str):
            config = load_config(config)
        self._config = config
        self._book_table = book_table or load_books()
        self._ctx: ApplicationContext | None = None
        self._orchestrator: PipelineOrchestrator | None = None
        self._metrics = PipelineMetrics()
        self._started = False

    @property
    def started(self) -> bool:
        """True se start() foi chamado e stop() não."""
        return self._started

    @property
    def metrics(self) -> PipelineMetrics:
        """Métricas acumuladas do pipeline."""
        return self._metrics

    @property
    def context(self) -> ApplicationContext | None:
        """Contexto de aplicação ativo (None se não started)."""
        return self._ctx

    def start(self) -> None:
        """Inicializa o pipeline: wire dependências e cria orchestrator.

        Raises:
            PipelineError: se já started ou se wiring falha.
        """
        if self._started:
            raise PipelineError("pipeline already started")
        try:
            self._ctx = self._build_context()
            self._orchestrator = PipelineOrchestrator(
                parser=self._ctx.parser,
                searcher=self._ctx.searcher,
                decision_engine=self._ctx.decision_engine,
                state_manager=self._ctx.state_manager,
                metrics=self._metrics,
                llm_client=self._ctx.llm_client,
                reranker=self._ctx.reranker,
                knowledge_enricher=self._ctx.knowledge_enricher,
            )
            self._started = True
            logger.info("pipeline started")
        except Exception as e:
            raise PipelineError(f"start failed: {e}") from e

    def stop(self) -> None:
        """Encerra o pipeline: salva estado e limpa contexto. Idempotente."""
        if not self._started:
            return
        if self._ctx is not None:
            try:
                self._ctx.state_manager.save()
            except Exception as e:
                logger.warning("state save failed on stop: %s", e)
            if self._ctx.llm_client is not None:
                try:
                    self._ctx.llm_client.close()
                except Exception as e:
                    logger.warning("llm close failed on stop: %s", e)
        self._ctx = None
        self._orchestrator = None
        self._started = False
        logger.info("pipeline stopped")

    def healthcheck(self) -> dict[str, bool]:
        """Verifica status de cada componente (holyrics, search, state, parser, llm)."""
        if not self._started or self._ctx is None:
            return {
                "holyrics": False, "search": False, "state": False,
                "parser": False, "llm": False,
            }
        ctx = self._ctx
        return {
            "holyrics": self._check_holyrics(ctx.holyrics),
            "search": ctx.searcher is not None,
            "state": True,
            "parser": True,
            "llm": self._check_llm(ctx.llm_client),
        }

    def process_utterance(self, utterance: Utterance) -> LogEntry:
        """Processa uma utterance e retorna LogEntry. Delega ao orchestrator.

        Raises:
            PipelineError: se pipeline não started.
        """
        if not self._started or self._orchestrator is None:
            raise PipelineError("pipeline not started — call start() first")
        return self._orchestrator.process_utterance(utterance)

    def process_utterance_detailed(self, utterance: Utterance) -> ProcessResult:
        """Processa uma utterance e retorna ProcessResult com todos os objetos.

        Idêntico a process_utterance() em lógica, mas retorna ProcessResult
        expondo LogEntry, Decision, search_results e candidates (quando
        ambíguo) para a interface decidir o próximo passo.

        Raises:
            PipelineError: se pipeline não started.
        """
        if not self._started or self._orchestrator is None:
            raise PipelineError("pipeline not started — call start() first")
        return self._orchestrator.process_utterance_detailed(utterance)

    def _build_context(self) -> ApplicationContext:
        """Constrói ApplicationContext com todas as dependências."""
        cfg = self._config
        all_books = self._book_table.all_books()
        parser = Parser(ParserBookTable(all_books))
        structure = load_bible_structure(cfg.search.fts5_db)
        book_names = {b.id: b.canonical for b in all_books}
        state_mgr = BibleStateManager(
            structure=structure, book_names=book_names,
            persist_path=cfg.state.persist_path,
            default_version=cfg.state.default_version,
        )
        state_mgr.load()
        holyrics = HolyricsClient(
            base_url=cfg.holyrics.base_url, token=cfg.holyrics.token,
            timeout_s=cfg.holyrics.timeout_ms / 1000.0,
        )
        searcher: Searcher | None
        try:
            # EmbeddingSearcher (opcional — não impede inicialização se offline)
            embedding_searcher = None
            try:
                from busca.embedding_provider import SentenceTransformerProvider
                from busca.embedding_index import EmbeddingIndex
                from busca.embedding_searcher import EmbeddingSearcher

                provider = SentenceTransformerProvider(
                    model_name=cfg.search.embedding_model,
                    device=cfg.search.embedding_device,
                )
                # Caminhos para vetores e metadados
                import os
                vectors_path = cfg.search.embeddings_path
                meta_path = os.path.splitext(vectors_path)[0] + ".json"
                emb_index = EmbeddingIndex(vectors_path, meta_path)
                embedding_searcher = EmbeddingSearcher(provider, emb_index)
                if embedding_searcher.load():
                    logger.info(
                        "embedding searcher loaded: %d vectors, dim=%d",
                        emb_index.size, emb_index.dim,
                    )
                    # Warmup: primeira query é lenta (compilação de grafos)
                    embedding_searcher.warmup()
                else:
                    logger.info(
                        "embedding index not found — semantic search disabled "
                        "(run build_embeddings.py to create)"
                    )
                    embedding_searcher = None
            except Exception as e:
                logger.warning("embedding searcher init failed: %s", e)
                embedding_searcher = None

            searcher = Searcher(
                cfg.search, self._book_table, cfg.state.default_version,
                embedding_searcher=embedding_searcher,
            )
        except Exception as e:
            logger.warning("searcher init failed — search disabled: %s", e)
            searcher = None
        engine = DecisionEngine(cfg.confidence, state_mgr, holyrics, mode=cfg.mode)

        # LLM client (opcional — não impede inicialização se offline)
        llm_client: LLMClient | None = None
        try:
            llm_client = LLMClient(cfg.llm, self._book_table)
            if not llm_client.is_available():
                logger.warning("llm not available — LLM disabled (Ollama offline)")
                llm_client.close()
                llm_client = None
        except Exception as e:
            logger.warning("llm init failed — LLM disabled: %s", e)
            llm_client = None

        # Reranker por LLM (opcional — só se LLM disponível)
        reranker: object | None = None
        if llm_client is not None:
            try:
                from busca.reranker import LLMReranker
                reranker = LLMReranker(llm_client)
                logger.info("LLM reranker enabled")
            except Exception as e:
                logger.warning("reranker init failed: %s", e)
                reranker = None

        # KnowledgeEnricher (opcional — base de conhecimento bíblico local)
        knowledge_enricher: object | None = None
        try:
            from busca.knowledge_enricher import KnowledgeBase, KnowledgeEnricher
            import os
            kb_path = "config/knowledge_base.json"
            if os.path.isfile(kb_path):
                kb = KnowledgeBase(kb_path)
                if kb.is_loaded:
                    knowledge_enricher = KnowledgeEnricher(kb)
                    logger.info(
                        "knowledge enricher enabled: %d concepts", kb.size,
                    )
                else:
                    logger.warning("knowledge base empty — enricher disabled")
            else:
                logger.warning(
                    "knowledge_base.json not found — enricher disabled",
                )
        except Exception as e:
            logger.warning("knowledge enricher init failed: %s", e)
            knowledge_enricher = None

        return ApplicationContext(
            parser=parser, searcher=searcher, decision_engine=engine,
            state_manager=state_mgr, holyrics=holyrics, book_table=self._book_table,
            llm_client=llm_client,
            reranker=reranker,
            knowledge_enricher=knowledge_enricher,
        )

    @staticmethod
    def _check_holyrics(client: HolyricsClient) -> bool:
        """Verifica se Holyrics está reachável."""
        try:
            return client.test_connection()
        except Exception:
            return False

    @staticmethod
    def _check_llm(client: LLMClient | None) -> bool:
        """Verifica se o LLM (Ollama) está reachável."""
        if client is None:
            return False
        try:
            return client.is_available()
        except Exception:
            return False
