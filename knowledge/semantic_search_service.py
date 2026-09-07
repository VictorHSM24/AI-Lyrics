"""knowledge/semantic_search_service.py — Busca semântica de versículos.

Componente responsável por buscar versículos bíblicos a partir de texto
livre (palavras-chave, paráfrases, temas), combinando:

1. BibleRetriever (FTS5 + BM25) — busca rápida em todas as versões.
2. OllamaBackend (LLM) — re-ranqueamento semântico dos candidatos.

Fluxo:
    query do operador
        ↓
    BibleRetriever.retrieve(query, top_k=N*2)  →  candidatos FTS5
        ↓
    OllamaBackend.send_request(prompt)  →  ranking semântico (JSON)
        ↓
    candidatos re-ranqueados por score semântico
        ↓
    list[SemanticSearchResult]

Fallback graceful:
    Se o Ollama estiver indisponível ou retornar JSON inválido,
    retorna os candidatos do FTS5 na ordem original (sem re-ranqueio),
    com fallback=True para o frontend informar o operador.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from knowledge.bible_retriever import BibleRetriever
from knowledge.types import BibleCandidate
from semantic.llm_backend import BackendRequest, LLMBackend
from semantic.types import SemanticError, SemanticTimeout

logger = logging.getLogger(__name__)

__all__ = [
    "SemanticSearchService",
    "SemanticSearchResult",
    "VersionText",
]


# ---------------------------------------------------------------------------
# Tipos de dados
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VersionText:
    """Texto de um versículo em uma versão específica."""

    version: str
    text: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "text": self.text,
            "score": round(self.score, 4),
        }


@dataclass(frozen=True)
class SemanticSearchResult:
    """Candidato re-ranqueado pela busca semântica.

    Atributos:
        book: nome canônico do livro ("João", "Salmos").
        book_id: book_reference_id (1..66).
        chapter: número do capítulo.
        verse: número do versículo.
        reference: referência legível ("João 3:16").
        semantic_score: score semântico do Ollama [0.0, 1.0].
            Se fallback, é o aggregated_score do FTS5.
        fts_rank: posição (1-based) no ranking original do FTS5.
        versions: lista de VersionText (texto em cada versão).
        best_text: texto da versão com maior score FTS5.
        best_version: código da versão com maior score FTS5.
    """

    book: str
    book_id: int
    chapter: int
    verse: int
    reference: str
    semantic_score: float
    fts_rank: int
    versions: tuple[VersionText, ...]
    best_text: str
    best_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "book": self.book,
            "book_id": self.book_id,
            "chapter": self.chapter,
            "verse": self.verse,
            "reference": self.reference,
            "semantic_score": round(self.semantic_score, 4),
            "fts_rank": self.fts_rank,
            "versions": [v.to_dict() for v in self.versions],
            "best_text": self.best_text,
            "best_version": self.best_version,
        }


# ---------------------------------------------------------------------------
# Prompt do Ollama
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """Você é um ranqueador de versículos bíblicos.

Dado uma consulta do usuário e uma lista de versículos candidatos (com referência e texto), você deve reordenar os candidatos por relevância semântica em relação à consulta.

REGRAS OBRIGATÓRIAS:
1. Responda APENAS com JSON válido. Nenhum texto adicional.
2. Não utilize raciocínio explícito. Não explique sua resposta.
3. Não produza markdown ou tags de thinking.
4. O JSON deve seguir exatamente este schema:
   {"ranked": [{"index": 0, "score": 0.95}, {"index": 1, "score": 0.80}, ...]}
5. "index" é a posição (0-based) do candidato na lista fornecida.
6. "score" é um número entre 0.0 e 1.0 indicando relevância semântica.
7. Ordene por score (maior primeiro).
8. Inclua TODOS os candidatos na resposta.
"""

_USER_PROMPT_TEMPLATE = """Consulta: "{query}"

Candidatos:
{candidates_list}

Reordene por relevância semântica e retorne o JSON."""


def _build_candidates_list(candidates: list[BibleCandidate]) -> str:
    """Constrói a lista de candidatos para o prompt do Ollama."""
    lines = []
    for i, c in enumerate(candidates):
        text = c.primary_text[:200]  # Limitar texto para não estourar contexto.
        lines.append(f'[{i}] {c.canonical_reference} — "{text}"')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parse da resposta do Ollama
# ---------------------------------------------------------------------------


def _parse_ollama_ranking(content: str, num_candidates: int) -> list[int] | None:
    """Extrai a lista de índices reordenados da resposta do Ollama.

    Returns:
        Lista de índices (0-based) ordenados por score, ou None se
        a resposta não puder ser parseada.
    """
    if not content or not content.strip():
        return None

    # Tentar parse direto do JSON.
    try:
        data = json.loads(content)
        ranked = data.get("ranked", [])
        if isinstance(ranked, list) and len(ranked) > 0:
            indices = []
            for item in ranked:
                idx = item.get("index")
                if isinstance(idx, int) and 0 <= idx < num_candidates:
                    indices.append(idx)
            if len(indices) == num_candidates:
                return indices
            # Se faltam índices, completar com os restantes.
            seen = set(indices)
            for i in range(num_candidates):
                if i not in seen:
                    indices.append(i)
            return indices
    except json.JSONDecodeError:
        pass

    # Fallback: tentar extrair JSON com regex (às vezes o modelo
    # envolve o JSON em texto ou markdown).
    json_match = re.search(r'\{[^{}]*"ranked"[^{}]*\[.*?\][^{}]*\}', content, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            ranked = data.get("ranked", [])
            if isinstance(ranked, list) and len(ranked) > 0:
                indices = []
                for item in ranked:
                    idx = item.get("index")
                    if isinstance(idx, int) and 0 <= idx < num_candidates:
                        indices.append(idx)
                if len(indices) == num_candidates:
                    return indices
                seen = set(indices)
                for i in range(num_candidates):
                    if i not in seen:
                        indices.append(i)
                return indices
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# SemanticSearchService
# ---------------------------------------------------------------------------


class SemanticSearchService:
    """Serviço de busca semântica de versículos.

    Combina BibleRetriever (FTS5) + OllamaBackend (re-ranqueamento)
    para buscar versículos a partir de texto livre.

    Args:
        bible_retriever: BibleRetriever aquecido (warmup() chamado).
        ollama_backend: LLMBackend (OllamaBackend) para re-ranqueamento.
        model: nome do modelo Ollama (ex.: "qwen3:8b-q4_K_M").
        timeout_s: timeout para a chamada do Ollama (segundos).
        temperature: temperatura do Ollama (0.0 para determinístico).
        max_tokens: limite de tokens de saída do Ollama.
    """

    def __init__(
        self,
        bible_retriever: BibleRetriever,
        ollama_backend: LLMBackend,
        model: str = "qwen3:8b-q4_K_M",
        timeout_s: float = 15.0,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> None:
        self._retriever = bible_retriever
        self._backend = ollama_backend
        self._model = model
        self._timeout_s = timeout_s
        self._temperature = temperature
        self._max_tokens = max_tokens

        # Métricas.
        self._total_searches = 0
        self._total_fallbacks = 0
        self._total_search_ms = 0.0

    @property
    def is_ready(self) -> bool:
        """True se o BibleRetriever está aquecido."""
        return self._retriever.is_ready

    @property
    def ollama_available(self) -> bool:
        """True se o Ollama está online."""
        try:
            return self._backend.is_available()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self, query: str, top_k: int = 20,
        skip_ollama: bool = False,
    ) -> tuple[list[SemanticSearchResult], bool, float]:
        """Busca versículos por texto livre com re-ranqueamento semântico.

        Args:
            query: texto livre do operador (palavras-chave, paráfrase, tema).
            top_k: número máximo de candidatos a retornar.
            skip_ollama: se True, pula o re-ranqueamento Ollama e usa
                apenas a ordem do FTS5/BM25. Usado quando o pipeline
                de transcrição está ativo para evitar competição de GPU.

        Returns:
            Tuplo (resultados, fallback, latency_ms).
            fallback=True se o Ollama não foi usado (indisponível/erro).
        """
        if not query or not query.strip():
            return [], False, 0.0

        t0 = time.monotonic()
        self._total_searches += 1

        # 1. Buscar no FTS5 (busca ampla para o Ollama ter opções).
        fts_k = min(top_k * 2, 40)
        candidates = self._retriever.retrieve(query, top_k=fts_k)

        if not candidates:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            self._total_search_ms += elapsed_ms
            return [], False, elapsed_ms

        # Limitar ao top_k para o prompt não ficar gigante.
        candidates = candidates[:top_k]

        # 2. Re-ranquear com Ollama (ou pular se solicitado).
        if skip_ollama:
            ranked_indices = list(range(len(candidates)))
            fallback = True
        else:
            ranked_indices, fallback = self._rerank_with_ollama(query, candidates)

        # 3. Construir resultados na ordem re-ranqueada.
        results = self._build_results(candidates, ranked_indices, fallback)

        elapsed_ms = (time.monotonic() - t0) * 1000.0
        self._total_search_ms += elapsed_ms

        if fallback:
            self._total_fallbacks += 1
            reason = "pipeline_active" if skip_ollama else "ollama_unavailable"
            logger.info(
                "SemanticSearchService: query=%r → %d candidates "
                "(fallback=%s, latency=%.0fms)",
                query[:60], len(results), reason, elapsed_ms,
            )
        else:
            logger.info(
                "SemanticSearchService: query=%r → %d candidates "
                "(ollama=ok, latency=%.0fms)",
                query[:60], len(results), elapsed_ms,
            )

        return results, fallback, elapsed_ms

    # ------------------------------------------------------------------
    # Re-ranqueamento Ollama
    # ------------------------------------------------------------------

    def _rerank_with_ollama(
        self, query: str, candidates: list[BibleCandidate],
    ) -> tuple[list[int], bool]:
        """Re-ranqueia candidatos com Ollama.

        Returns:
            Tuplo (ranked_indices, fallback).
            ranked_indices: lista de índices (0-based) ordenados.
            fallback: True se Ollama não foi usado.
        """
        n = len(candidates)
        default_order = list(range(n))

        # Verificar disponibilidade do Ollama.
        if not self.ollama_available:
            logger.info(
                "SemanticSearchService: Ollama unavailable — "
                "using FTS5 order (fallback)."
            )
            return default_order, True

        # Construir prompt.
        candidates_list = _build_candidates_list(candidates)
        user_prompt = _USER_PROMPT_TEMPLATE.format(
            query=query[:300],
            candidates_list=candidates_list,
        )

        request = BackendRequest(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=self._model,
            temperature=self._temperature,
            top_p=0.9,
            max_tokens=self._max_tokens,
            disable_thinking=True,
            stream=False,
        )

        try:
            payload = self._backend.build_payload(request)
            response = self._backend.send_request(payload, self._timeout_s)
        except SemanticTimeout:
            logger.warning(
                "SemanticSearchService: Ollama timeout (%.1fs) — "
                "using FTS5 order (fallback).",
                self._timeout_s,
            )
            return default_order, True
        except SemanticError as e:
            logger.warning(
                "SemanticSearchService: Ollama error: %s — "
                "using FTS5 order (fallback).",
                e,
            )
            return default_order, True
        except Exception as e:
            logger.warning(
                "SemanticSearchService: unexpected Ollama error: %s — "
                "using FTS5 order (fallback).",
                e,
            )
            return default_order, True

        if response.error:
            logger.warning(
                "SemanticSearchService: Ollama response error: %s — "
                "using FTS5 order (fallback).",
                response.error,
            )
            return default_order, True

        # Parsear ranking.
        ranked = _parse_ollama_ranking(response.content, n)
        if ranked is None:
            logger.warning(
                "SemanticSearchService: could not parse Ollama ranking "
                "(content=%r) — using FTS5 order (fallback).",
                response.content[:200],
            )
            return default_order, True

        return ranked, False

    # ------------------------------------------------------------------
    # Construção de resultados
    # ------------------------------------------------------------------

    def _build_results(
        self,
        candidates: list[BibleCandidate],
        ranked_indices: list[int],
        fallback: bool,
    ) -> list[SemanticSearchResult]:
        """Constrói SemanticSearchResult a partir dos candidatos re-ranqueados."""
        results: list[SemanticSearchResult] = []
        for rank_pos, idx in enumerate(ranked_indices):
            if idx < 0 or idx >= len(candidates):
                continue
            c = candidates[idx]

            # Versões do candidato.
            versions = tuple(
                VersionText(
                    version=v.version,
                    text=v.text,
                    score=v.score,
                )
                for v in c.versions
            )

            # Melhor versão (maior score FTS5).
            if c.versions:
                best = max(c.versions, key=lambda v: v.score)
                best_text = best.text
                best_version = best.version
            else:
                best_text = ""
                best_version = ""

            # Score semântico: se fallback, usar aggregated_score do FTS5.
            if fallback:
                semantic_score = c.aggregated_score
            else:
                # Score decrescente por posição no ranking (1.0 → 0.0).
                # O primeiro (rank_pos=0) recebe 1.0, o último recebe ~0.1.
                n = len(ranked_indices)
                if n > 1:
                    semantic_score = 1.0 - (rank_pos / n) * 0.9
                else:
                    semantic_score = 1.0
                # Combinar com aggregated_score do FTS5 (70% semântico + 30% FTS5).
                semantic_score = 0.7 * semantic_score + 0.3 * c.aggregated_score

            results.append(SemanticSearchResult(
                book=c.book,
                book_id=c.book_reference_id,
                chapter=c.chapter,
                verse=c.verse,
                reference=c.canonical_reference,
                semantic_score=semantic_score,
                fts_rank=idx + 1,
                versions=versions,
                best_text=best_text,
                best_version=best_version,
            ))

        return results

    # ------------------------------------------------------------------
    # Telemetria
    # ------------------------------------------------------------------

    def get_telemetry(self) -> dict[str, Any]:
        return {
            "total_searches": self._total_searches,
            "total_fallbacks": self._total_fallbacks,
            "total_search_ms": round(self._total_search_ms, 2),
            "avg_search_ms": round(
                self._total_search_ms / max(1, self._total_searches), 2,
            ),
            "model": self._model,
            "timeout_s": self._timeout_s,
            "ollama_available": self.ollama_available,
            "retriever_ready": self.is_ready,
        }
