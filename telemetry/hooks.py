"""Sprint 21.9 — Hooks de telemetria específicos por componente.

Funções utilitárias que encapsulam a extração de campos relevantes de
cada componente do pipeline e o registro no TelemetryRecorder.

Estas funções NÃO alteram o comportamento dos componentes. São chamadas
em pontos estratégicos (após decisões já tomadas, antes/after de chamadas
externas) apenas para observação.

Cada hook recebe os objetos já existentes (eventos, contextos, resultados)
e extrai apenas os campos relevantes para auditoria.

Organização:
- stt_hooks: StreamingSTTService (transcrições, RMS, confiança)
- streaming_hooks: SpeechPartial / SpeechPartialUpdated
- parser_hooks: IncrementalBiblicalParser (candidatos, completude)
- sermon_hooks: SermonMemoryEngine (mudanças de estado)
- semantic_hooks: SemanticEngine + LocalLLMProvider (prompts, respostas)
- resolver_hooks: ReferenceResolver (escolha de candidato)
- presentation_hooks: VersePresentationService (Holyrics)

Todos os hooks são no-op se a telemetria estiver desabilitada.
"""
from __future__ import annotations

import json
import time
from typing import Any

from .recorder import record, is_enabled


# ---------------------------------------------------------------------
# STT — StreamingSTTService
# ---------------------------------------------------------------------

def stt_window(
    *,
    correlation_id: str | None,
    audio_duration_ms: int,
    rms: float,
    skipped_silence: bool = False,
    skipped_low_confidence: bool = False,
    skipped_empty: bool = False,
    skipped_no_change: bool = False,
    transcribed: bool = False,
    text: str = "",
    confidence: float = 0.0,
    latency_ms: int = 0,
    language: str = "",
) -> None:
    """Registra uma janela de áudio processada pelo StreamingSTT."""
    if not is_enabled():
        return
    record("stt", {
        "correlation_id": correlation_id or "",
        "audio_duration_ms": audio_duration_ms,
        "rms": round(rms, 6),
        "skipped_silence": skipped_silence,
        "skipped_low_confidence": skipped_low_confidence,
        "skipped_empty": skipped_empty,
        "skipped_no_change": skipped_no_change,
        "transcribed": transcribed,
        "text": text,
        "confidence": round(confidence, 4),
        "latency_ms": latency_ms,
        "language": language,
    })


def stt_partial_published(
    *,
    correlation_id: str,
    text: str,
    confidence: float,
    latency_ms: int,
    audio_duration_ms: int,
    language: str,
    is_update: bool = False,
    appended_text: str = "",
    full_text: str = "",
    growth_chars: int = 0,
) -> None:
    """Registra publicação de SpeechPartial ou SpeechPartialUpdated."""
    if not is_enabled():
        return
    record("streaming", {
        "correlation_id": correlation_id,
        "event_type": "SpeechPartialUpdated" if is_update else "SpeechPartial",
        "text": text,
        "appended_text": appended_text,
        "full_text": full_text,
        "growth_chars": growth_chars,
        "confidence": round(confidence, 4),
        "latency_ms": latency_ms,
        "audio_duration_ms": audio_duration_ms,
        "language": language,
    })


# ---------------------------------------------------------------------
# IncrementalBiblicalParser
# ---------------------------------------------------------------------

def parser_event(
    *,
    correlation_id: str,
    text_processed: str,
    expecting: str,
    completeness: str,
    book: str = "",
    chapter: int = 0,
    verse: int = 0,
    confidence: float = 0.0,
    decision: str = "",
    published_event: str = "",
    latency_ms: int = 0,
) -> None:
    """Registra decisão do IncrementalBiblicalParser."""
    if not is_enabled():
        return
    record("parser", {
        "correlation_id": correlation_id,
        "text_processed": text_processed,
        "expecting": expecting,
        "completeness": completeness,
        "book": book,
        "chapter": chapter,
        "verse": verse,
        "confidence": round(confidence, 4),
        "decision": decision,
        "published_event": published_event,
        "latency_ms": latency_ms,
    })


# ---------------------------------------------------------------------
# SermonMemoryEngine
# ---------------------------------------------------------------------

def sermon_state_change(
    *,
    correlation_id: str,
    reason: str,
    previous_book: str,
    previous_chapter: int,
    new_book: str,
    new_chapter: int,
    probable_theme: str,
    num_entities: int,
    num_topics: int,
    num_references: int,
    confidence: float,
    source: str = "",
    reference_active: str = "",
    total_updates: int = 0,
) -> None:
    """Registra mudança de estado do SermonMemoryEngine."""
    if not is_enabled():
        return
    record("sermon_memory", {
        "correlation_id": correlation_id,
        "reason": reason,
        "previous_book": previous_book,
        "previous_chapter": previous_chapter,
        "new_book": new_book,
        "new_chapter": new_chapter,
        "probable_theme": probable_theme,
        "num_entities": num_entities,
        "num_topics": num_topics,
        "num_references": num_references,
        "confidence": round(confidence, 4),
        "source": source,
        "reference_active": reference_active,
        "total_updates": total_updates,
    })


# ---------------------------------------------------------------------
# SemanticEngine + LocalLLMProvider
# ---------------------------------------------------------------------

def semantic_input(
    *,
    correlation_id: str,
    text: str,
    recent_text: str,
    trigger: str,
    growth_chars: int = 0,
    append_words: int = 0,
    elapsed_ms: float = 0.0,
    cached: bool = False,
    context_hash: str = "",
) -> None:
    """Registra texto recebido pelo SemanticEngine e decisão de disparo."""
    if not is_enabled():
        return
    record("semantic_engine", {
        "correlation_id": correlation_id,
        "text": text,
        "recent_text": recent_text,
        "trigger": trigger,
        "growth_chars": growth_chars,
        "append_words": append_words,
        "elapsed_ms": round(elapsed_ms, 2),
        "cached": cached,
        "context_hash": context_hash,
    })


def semantic_prompt(
    *,
    correlation_id: str,
    system_prompt: str,
    user_prompt: str,
    context: dict[str, Any] | None = None,
    model: str = "",
    temperature: float = 0.0,
    top_p: float = 1.0,
    max_tokens: int = 300,
    disable_thinking: bool = True,
) -> None:
    """Registra prompt enviado ao LLM pelo LocalLLMProvider."""
    if not is_enabled():
        return
    record("semantic_prompt", {
        "correlation_id": correlation_id,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "context": context or {},
        "model": model,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "disable_thinking": disable_thinking,
    })


def semantic_llm_response(
    *,
    correlation_id: str,
    raw_content: str,
    cleaned_content: str,
    had_thinking: bool = False,
    http_ms: int = 0,
    attempt: int = 0,
    error: str = "",
) -> None:
    """Registra resposta RAW do LLM antes do parser."""
    if not is_enabled():
        return
    record("semantic_llm_response", {
        "correlation_id": correlation_id,
        "raw_content": raw_content,
        "cleaned_content": cleaned_content,
        "had_thinking": had_thinking,
        "http_ms": http_ms,
        "attempt": attempt,
        "error": error,
    })


def semantic_result(
    *,
    correlation_id: str,
    intent: str,
    candidates: list[dict[str, Any]],
    inference_ms: int,
    cached: bool = False,
    context_hash: str = "",
    error: str = "",
) -> None:
    """Registra resultado final da inferência semântica."""
    if not is_enabled():
        return
    record("semantic_result", {
        "correlation_id": correlation_id,
        "intent": intent,
        "candidates": candidates,
        "inference_ms": inference_ms,
        "cached": cached,
        "context_hash": context_hash,
        "error": error,
    })


# ---------------------------------------------------------------------
# ReferenceResolver
# ---------------------------------------------------------------------

def resolver_decision(
    *,
    correlation_id: str,
    candidates_in: list[dict[str, Any]],
    candidates_valid: list[dict[str, Any]],
    chosen: dict[str, Any] | None,
    reason: str,
    min_confidence: float,
    latency_ms: int = 0,
) -> None:
    """Registra decisão do ReferenceResolver."""
    if not is_enabled():
        return
    record("resolver", {
        "correlation_id": correlation_id,
        "candidates_in": candidates_in,
        "candidates_valid": candidates_valid,
        "chosen": chosen,
        "reason": reason,
        "min_confidence": min_confidence,
        "latency_ms": latency_ms,
    })


# ---------------------------------------------------------------------
# VersePresentationService (Holyrics)
# ---------------------------------------------------------------------

def holyrics_presentation(
    *,
    correlation_id: str,
    book: str,
    chapter: int,
    verse: int,
    version: str,
    quick_presentation: bool,
    success: bool,
    latency_ms: int,
    error: str = "",
    stage: str = "",
) -> None:
    """Registra apresentação no Holyrics."""
    if not is_enabled():
        return
    record("holyrics", {
        "correlation_id": correlation_id,
        "book": book,
        "chapter": chapter,
        "verse": verse,
        "version": version,
        "quick_presentation": quick_presentation,
        "success": success,
        "latency_ms": latency_ms,
        "error": error,
        "stage": stage,
    })


# ---------------------------------------------------------------------
# Pipeline (genérico — para eventos arbitrários do EventBus)
# ---------------------------------------------------------------------

def pipeline_event(
    *,
    event_type: str,
    correlation_id: str = "",
    origin: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    """Registra evento genérico do pipeline (para auditoria de fluxo)."""
    if not is_enabled():
        return
    record("pipeline", {
        "event_type": event_type,
        "correlation_id": correlation_id,
        "origin": origin,
        "payload": payload or {},
    })


# ---------------------------------------------------------------------
# Sprint 22.0 — BibleRetriever (RAG Local)
# ---------------------------------------------------------------------

def bible_retriever_warmup(
    *,
    versions_discovered: list[str],
    total_versions: int,
    total_verses: int,
    unique_verses: int,
    init_time_ms: float,
    sources_dir: str,
) -> None:
    """Registra o warm-up do BibleRetriever (categoria bible_retriever)."""
    if not is_enabled():
        return
    record("bible_retriever", {
        "event": "warmup",
        "versions_discovered": versions_discovered,
        "total_versions": total_versions,
        "total_verses": total_verses,
        "unique_verses": unique_verses,
        "init_time_ms": round(init_time_ms, 2),
        "sources_dir": sources_dir,
    })


def bible_retriever_query(
    *,
    correlation_id: str | None,
    query: str,
    versions_searched: list[str],
    top_k_requested: int,
    candidates_found: int,
    candidates: list[dict[str, Any]],
    retrieve_ms: float,
    strategy: str,
) -> None:
    """Registra uma consulta ao BibleRetriever (categoria bible_retriever).

    Args:
        correlation_id: ID de correlação com o evento do pipeline.
        query: texto da consulta (transcrição parcial).
        versions_searched: versões pesquisadas nesta consulta.
        top_k_requested: número máximo de candidatos solicitados.
        candidates_found: quantidade de candidatos retornados.
        candidates: lista de candidatos em formato dict (BibleCandidate.to_dict()).
        retrieve_ms: tempo total da recuperação em milissegundos.
        strategy: estratégia de busca usada ("and", "or_fallback", "hybrid").
    """
    if not is_enabled():
        return
    record("bible_retriever", {
        "event": "retrieve",
        "correlation_id": correlation_id or "",
        "query": query,
        "versions_searched": versions_searched,
        "top_k_requested": top_k_requested,
        "candidates_found": candidates_found,
        "candidates": candidates,
        "retrieve_ms": round(retrieve_ms, 2),
        "strategy": strategy,
    })


def bible_retriever_decision(
    *,
    correlation_id: str | None,
    candidates_in: list[dict[str, Any]],
    chosen: dict[str, Any] | None,
    reason: str,
    decision_ms: float,
) -> None:
    """Registra a decisão do SemanticEngine sobre candidatos do retriever.

    Args:
        correlation_id: ID de correlação.
        candidates_in: candidatos recebidos do BibleRetriever.
        chosen: candidato escolhido pelo LLM (ou None se rejeitou).
        reason: motivo da decisão ("llm_chosen", "llm_none", "fallback",
            "no_candidates", "error").
        decision_ms: tempo da decisão em milissegundos.
    """
    if not is_enabled():
        return
    record("bible_retriever", {
        "event": "decision",
        "correlation_id": correlation_id or "",
        "candidates_in": candidates_in,
        "chosen": chosen,
        "reason": reason,
        "decision_ms": round(decision_ms, 2),
    })


# ---------------------------------------------------------------------
# Sprint 22.2 — ContextPolicy (priorização RAG)
# ---------------------------------------------------------------------

def context_policy_decision(
    *,
    correlation_id: str | None,
    decision: dict[str, Any],
) -> None:
    """Registra a decisão da ContextPolicy para uma inferência.

    Permite reconstruir exatamente por que determinado contexto foi
    ou não enviado ao prompt.

    Args:
        correlation_id: ID de correlação.
        decision: dict de ContextDecision.to_dict() com campos:
            level (alta_confianca/ambiguidade_moderada/alta_ambiguidade),
            include_context (omit/summary/full),
            reason (motivo curto),
            top1_score, top2_score, gap,
            sermon_confidence, sermon_book, num_candidates.
    """
    if not is_enabled():
        return
    record("context_policy", {
        "event": "decision",
        "correlation_id": correlation_id or "",
        **decision,
    })


def sermon_book_confidence_change(
    *,
    correlation_id: str | None,
    previous_book: str,
    new_book: str,
    previous_confidence: float,
    new_confidence: float,
    reason: str,
) -> None:
    """Sprint 22.2 — Registra mudança na confiança do current_book.

    Args:
        correlation_id: ID de correlação.
        previous_book: livro anterior (ou "" se nenhum).
        new_book: novo livro (ou "" se removido).
        previous_confidence: confiança anterior.
        new_confidence: nova confiança.
        reason: motivo ("reference_detected", "reference_confirmed",
            "book_changed", "cleared", etc.).
    """
    if not is_enabled():
        return
    record("sermon_memory", {
        "event": "book_confidence_change",
        "correlation_id": correlation_id or "",
        "previous_book": previous_book,
        "new_book": new_book,
        "previous_confidence": round(previous_confidence, 4),
        "new_confidence": round(new_confidence, 4),
        "reason": reason,
    })

