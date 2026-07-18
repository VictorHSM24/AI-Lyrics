"""Executores de stages do pipeline (submódulo interno de core/pipeline.py).

Responsabilidade: encapsular a chamada a cada stage individual, medir
duração, capturar exceções e produzir StageTiming imutável. Exceções
de domínio são convertidas em PipelineError contextualizado.

Este módulo é interno ao pipeline. Módulos externos não devem importá-lo
diretamente — a API pública do pipeline está em core/pipeline.py.

Limites explícitos (o que este módulo NÃO faz):
  - Não orquestra a sequência de stages.
  - Não implementa lifecycle (start/stop).
  - Não gerencia threads, filas ou loops.
  - Não constrói LogEntry.
  - Não toma decisões de fluxo (execute vs confirm vs ignore).

Design:
  - Cada função recebe as dependências necessárias (injeção explícita).
  - Cada função retorna (resultado, StageTiming).
  - Exceções de domínio (AILyricsError e subclasses) são capturadas e
    convertidas em PipelineError com contexto do stage.
  - Exceções não-domínio são capturadas e wrapping em PipelineError.
  - StageTiming é sempre produzido, mesmo em caso de erro.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from core.exceptions import AILyricsError, PipelineError
from core.pipeline_metrics import StageTiming
from core.types import Decision, Intent, VerseRef

if TYPE_CHECKING:
    from busca.searcher import SearchResult, Searcher
    from core.decision import DecisionEngine
    from estado.state import BibleState, BibleStateManager
    from llm.client import LLMClient
    from parser.parser import Parser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper interno
# ---------------------------------------------------------------------------


def _measure(stage: str, fn, *args, **kwargs):
    """Executa fn, mede duração e produz StageTiming.

    Captura exceções de domínio (AILyricsError) e não-domínio, envolvendo
    em PipelineError contextualizado. O StageTiming é anexado ao
    PipelineError via atributo ``stage_timing`` para que o orquestrador
    possa registrá-lo mesmo em caso de falha.

    Args:
        stage: nome do stage para StageTiming.
        fn: callable a executar.
        *args, **kwargs: argumentos para fn.

    Returns:
        Tuple (result, StageTiming) em caso de sucesso.

    Raises:
        PipelineError: se fn levanta qualquer exceção. O erro carrega
            ``stage_timing`` com success=False e error_msg preenchido.
    """
    t0 = time.monotonic()
    try:
        result = fn(*args, **kwargs)
        duration_ms = (time.monotonic() - t0) * 1000.0
        timing = StageTiming(
            stage=stage,
            duration_ms=duration_ms,
            success=True,
            error_msg=None,
        )
        return result, timing
    except AILyricsError as e:
        duration_ms = (time.monotonic() - t0) * 1000.0
        timing = StageTiming(
            stage=stage,
            duration_ms=duration_ms,
            success=False,
            error_msg=str(e),
        )
        raise PipelineError(
            f"stage {stage!r} failed: {type(e).__name__}: {e}",
            stage_timing=timing,
        ) from e
    except Exception as e:
        duration_ms = (time.monotonic() - t0) * 1000.0
        timing = StageTiming(
            stage=stage,
            duration_ms=duration_ms,
            success=False,
            error_msg=str(e),
        )
        raise PipelineError(
            f"stage {stage!r} failed (unexpected): {type(e).__name__}: {e}",
            stage_timing=timing,
        ) from e


# ---------------------------------------------------------------------------
# Stages públicos
# ---------------------------------------------------------------------------


def run_parser(
    parser: Parser,
    text: str,
    state: BibleState | None = None,
) -> tuple[Intent, StageTiming]:
    """Executa o parser sobre o texto transcrito.

    Args:
        parser: instância de Parser.
        text: texto transcrito (saída do STT).
        state: estado atual da Bíblia (read-only, para contexto).

    Returns:
        Tuple (Intent, StageTiming).

    Raises:
        PipelineError: se o parser levanta qualquer exceção.
    """
    logger.debug("run_parser: text=%r", text[:80] if text else "")
    return _measure("parser", parser.parse, text, state)


def run_llm(
    llm_client: LLMClient,
    text: str,
    state: BibleState | None = None,
) -> tuple[Intent, StageTiming]:
    """Executa o LLM sobre o texto transcrito (fallback do parser uncertain).

    Args:
        llm_client: instância de LLMClient.
        text: texto transcrito (saída do STT).
        state: estado atual da Bíblia (read-only, para contexto).

    Returns:
        Tuple (Intent, StageTiming). O Intent sempre tem source="llm".
        Se o LLM estiver offline, retorna Intent(action="none", confidence=0.0).

    Raises:
        PipelineError: se o LLM levanta qualquer exceção.
    """
    logger.debug("run_llm: text=%r", text[:80] if text else "")
    return _measure("llm", llm_client.interpret, text, state)


def run_search(
    searcher: Searcher,
    query: str,
    *,
    top_k: int | None = None,
    version: str | None = None,
    state: BibleState | None = None,
) -> tuple[list[SearchResult], StageTiming]:
    """Executa a busca por query textual.

    Args:
        searcher: instância de Searcher.
        query: texto de busca.
        top_k: número máximo de resultados (opcional).
        version: versão bíblica (opcional).
        state: BibleState para busca contextual (opcional).

    Returns:
        Tuple (list[SearchResult], StageTiming).

    Raises:
        PipelineError: se o searcher levanta qualquer exceção.
    """
    logger.debug("run_search: query=%r", query[:80] if query else "")
    return _measure(
        "search",
        searcher.search,
        query,
        top_k=top_k,
        version=version,
        state=state,
    )


def run_decision(
    engine: DecisionEngine,
    intent: Intent,
    c_stt: float = 1.0,
    search_results: list[SearchResult] | None = None,
) -> tuple[Decision, StageTiming]:
    """Executa a avaliação do motor de decisão (pure logic, sem side effects).

    Args:
        engine: instância de DecisionEngine.
        intent: Intent do parser ou LLM.
        c_stt: confiança da transcrição [0.0, 1.0].
        search_results: resultados de busca (se action == "search").

    Returns:
        Tuple (Decision, StageTiming).

    Raises:
        PipelineError: se o motor de decisão levanta qualquer exceção.
    """
    logger.debug(
        "run_decision: action=%s c_stt=%.2f results=%d",
        intent.action,
        c_stt,
        len(search_results) if search_results else 0,
    )
    return _measure(
        "decision",
        engine.evaluate,
        intent,
        c_stt,
        search_results,
    )


def execute_decision(
    engine: DecisionEngine,
    decision: Decision,
    search_results: list[SearchResult] | None = None,
) -> tuple[VerseRef | None, StageTiming]:
    """Executa a decisão (side effects: Holyrics + State).

    Só deve ser chamado se decision.outcome == "execute".

    Args:
        engine: instância de DecisionEngine.
        decision: Decision com outcome == "execute".
        search_results: resultados de busca (se action == "search").

    Returns:
        Tuple (VerseRef | None, StageTiming). VerseRef é None se a
        decisão não pôde ser resolvida para uma referência.

    Raises:
        PipelineError: se a execução levanta qualquer exceção.
    """
    logger.debug(
        "execute_decision: action=%s outcome=%s",
        decision.intent.action,
        decision.outcome,
    )
    return _measure(
        "holyrics",
        engine.execute,
        decision,
        search_results,
    )
