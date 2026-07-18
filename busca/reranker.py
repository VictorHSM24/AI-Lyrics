"""Reranking por LLM — envia top candidatos ao LLM para seleção final.

Responsabilidade:
  - Quando há múltiplos candidatos relevantes, enviar os top N ao LLM
    para que ele escolha o mais coerente com a query original.
  - O reranking é opcional, controlado por configuração.
  - Se o LLM falhar ou estiver offline, retornar o ranking original.

Limites explícitos:
  - Não faz busca.
  - Não modifica SearchResult.
  - Não chama Holyrics.
  - Não reexecuta Parser.

Design:
  - LLMReranker recebe um LLMClient (reutilizado).
  - rerank() recebe a query original e lista de SearchResult.
  - Retorna lista reordenada de SearchResult (mesmos objetos, nova ordem).
  - Se o LLM falhar, retorna a lista original inalterada.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from busca.searcher import SearchResult
    from llm.client import LLMClient

logger = logging.getLogger(__name__)


# Número máximo de candidatos a enviar ao LLM (para limitar tokens)
_MAX_CANDIDATES = 10

# Máximo de caracteres do texto de cada candidato no prompt
_MAX_TEXT_CHARS = 200


class LLMReranker:
    """Reranking de candidatos via LLM.

    Example:
        >>> reranker = LLMReranker(llm_client)
        >>> reranked = reranker.rerank("quem nao tiver pecado", results)
        >>> if reranked:
        ...     print(f"Top: {reranked[0].reference}")
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    def rerank(
        self,
        query: str,
        results: list[SearchResult],
        max_candidates: int = _MAX_CANDIDATES,
    ) -> list[SearchResult]:
        """Reordena resultados usando o LLM para escolher o melhor candidato.

        Args:
            query: query original do usuário.
            results: lista de SearchResult (ordenada por score).
            max_candidates: máximo de candidatos a enviar ao LLM.

        Returns:
            Lista reordenada de SearchResult (mesmos objetos, nova ordem).
            Se o LLM falhar, retorna a lista original inalterada.
        """
        if not results or len(results) <= 1:
            return results

        candidates = results[:max_candidates]
        if len(candidates) <= 1:
            return results

        t0 = time.monotonic()

        # Construir prompt de reranking
        prompt = self._build_rerank_prompt(query, candidates)

        # Chamar LLM
        try:
            choice = self._call_llm_for_rerank(prompt, len(candidates))
        except Exception as e:
            logger.warning("rerank: LLM call failed: %s — using original order", e)
            return results

        if choice is None:
            logger.info("rerank: LLM returned no valid choice — using original order")
            return results

        # choice é 1-based index
        if choice < 1 or choice > len(candidates):
            logger.warning("rerank: LLM returned invalid index %d — using original order", choice)
            return results

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "rerank: query=%r chose=%d/%d ref=%s time=%.1fms",
            query[:60],
            choice,
            len(candidates),
            candidates[choice - 1].reference,
            elapsed_ms,
        )

        # Reordenar: escolhido primeiro, restante na ordem original
        chosen = candidates[choice - 1]
        remaining = [r for i, r in enumerate(candidates) if i != choice - 1]
        reranked_top = [chosen] + remaining
        # Adicionar resultados que não foram enviados ao LLM
        not_sent = results[max_candidates:]
        return reranked_top + not_sent

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _build_rerank_prompt(
        query: str,
        candidates: list[SearchResult],
    ) -> str:
        """Constrói o prompt de reranking para o LLM."""
        lines = [
            f"Consulta do usuário: \"{query}\"",
            "",
            "Foram encontrados os seguintes versículos candidatos:",
            "",
        ]
        for i, r in enumerate(candidates):
            text = r.text[:_MAX_TEXT_CHARS]
            if len(r.text) > _MAX_TEXT_CHARS:
                text += "..."
            lines.append(f"{i + 1}. {r.reference} [{r.version}]")
            lines.append(f'   "{text}"')
            lines.append("")

        lines.extend([
            "Qual versículo corresponde melhor à consulta do usuário?",
            "Responda APENAS com o número (1 a "
            f"{len(candidates)}). Sem texto adicional.",
        ])
        return "\n".join(lines)

    def _call_llm_for_rerank(
        self,
        prompt: str,
        num_candidates: int,
    ) -> int | None:
        """Chama o LLM e retorna o índice 1-based escolhido, ou None."""
        import requests

        payload = {
            "model": self._llm._config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Você é um assistente que escolhe o versículo mais "
                        "relevante para uma consulta. Responda APENAS com "
                        "um número."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "options": {
                "num_predict": 10,
                "temperature": 0.0,
            },
        }

        try:
            resp = self._llm._session.post(
                f"{self._llm._base_url}/api/chat",
                json=payload,
                timeout=self._llm._timeout_s,
            )
        except requests.exceptions.RequestException as e:
            logger.warning("rerank: request failed: %s", e)
            return None

        if resp.status_code != 200:
            logger.warning("rerank: HTTP %d", resp.status_code)
            return None

        try:
            body = resp.json()
            content = body.get("message", {}).get("content", "")
        except (ValueError, KeyError):
            return None

        # Extrair número da resposta
        import re
        match = re.search(r'\b(\d+)\b', content.strip())
        if match:
            return int(match.group(1))
        return None
