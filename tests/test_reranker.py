"""Testes do LLMReranker.

Cobre:
  - rerank() com lista vazia ou 1 resultado
  - rerank() com múltiplos resultados (mock LLM)
  - Fallback quando LLM falha
  - Fallback quando LLM retorna índice inválido
  - Reordenação correta (escolhido primeiro, restante na ordem original)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from busca.reranker import LLMReranker
from busca.searcher import SearchResult


def _make_result(ref: str, text: str, score: float = 0.9) -> SearchResult:
    """Cria um SearchResult de teste."""
    parts = ref.split()
    book = parts[0]
    chap_verse = parts[1] if len(parts) > 1 else "1"
    if ":" in chap_verse:
        chapter, verse = chap_verse.split(":")
        chapter, verse = int(chapter), int(verse)
    else:
        chapter, verse = int(chap_verse), None
    return SearchResult(
        reference=ref,
        book=book,
        book_id=43,
        chapter=chapter,
        verse=verse,
        text=text,
        version="ACF",
        score=score,
        c_search=0.9,
        ambiguous=False,
        match_type="hybrid",
    )


class TestLLMReranker:
    """Testes do reranker por LLM."""

    def test_empty_results(self) -> None:
        llm = MagicMock()
        reranker = LLMReranker(llm)
        assert reranker.rerank("query", []) == []

    def test_single_result(self) -> None:
        llm = MagicMock()
        reranker = LLMReranker(llm)
        results = [_make_result("João 3:16", "texto")]
        assert reranker.rerank("query", results) == results

    def test_rerank_reorders(self) -> None:
        """LLM escolhe candidato 2 → deve ir para primeira posição."""
        llm = MagicMock()
        llm._config.model = "test"
        llm._base_url = "http://localhost"
        llm._timeout_s = 5.0
        llm._session = MagicMock()

        results = [
            _make_result("João 3:16", "Porque Deus amou", 0.9),
            _make_result("João 3:17", "Por Deus não enviou", 0.85),
            _make_result("João 3:18", "Quem crê nele", 0.80),
        ]

        # Mock: LLM retorna "2" (escolhe candidato 2)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "2"}
        }
        llm._session.post.return_value = mock_response

        reranker = LLMReranker(llm)
        reranked = reranker.rerank("query", results)

        # Candidato 2 (index 1) deve ser o primeiro
        assert reranked[0].reference == "João 3:17"
        # Candidato 1 deve ser o segundo
        assert reranked[1].reference == "João 3:16"
        # Candidato 3 deve ser o terceiro
        assert reranked[2].reference == "João 3:18"

    def test_rerank_llm_failure_returns_original(self) -> None:
        """Se LLM falha, retorna lista original inalterada."""
        llm = MagicMock()
        llm._config.model = "test"
        llm._base_url = "http://localhost"
        llm._timeout_s = 5.0
        llm._session = MagicMock()

        results = [
            _make_result("João 3:16", "texto 1", 0.9),
            _make_result("João 3:17", "texto 2", 0.85),
        ]

        # Mock: LLM falha (exception)
        llm._session.post.side_effect = Exception("connection error")

        reranker = LLMReranker(llm)
        reranked = reranker.rerank("query", results)

        # Deve retornar a lista original
        assert reranked == results
        assert reranked[0].reference == "João 3:16"

    def test_rerank_invalid_index_returns_original(self) -> None:
        """Se LLM retorna índice inválido, retorna lista original."""
        llm = MagicMock()
        llm._config.model = "test"
        llm._base_url = "http://localhost"
        llm._timeout_s = 5.0
        llm._session = MagicMock()

        results = [
            _make_result("João 3:16", "texto 1", 0.9),
            _make_result("João 3:17", "texto 2", 0.85),
        ]

        # Mock: LLM retorna "99" (inválido)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "99"}
        }
        llm._session.post.return_value = mock_response

        reranker = LLMReranker(llm)
        reranked = reranker.rerank("query", results)

        # Deve retornar a lista original
        assert reranked == results

    def test_rerank_http_error_returns_original(self) -> None:
        """Se LLM retorna HTTP não-200, retorna lista original."""
        llm = MagicMock()
        llm._config.model = "test"
        llm._base_url = "http://localhost"
        llm._timeout_s = 5.0
        llm._session = MagicMock()

        results = [
            _make_result("João 3:16", "texto 1", 0.9),
            _make_result("João 3:17", "texto 2", 0.85),
        ]

        mock_response = MagicMock()
        mock_response.status_code = 500
        llm._session.post.return_value = mock_response

        reranker = LLMReranker(llm)
        reranked = reranker.rerank("query", results)

        assert reranked == results

    def test_rerank_preserves_not_sent_results(self) -> None:
        """Resultados além de max_candidates são preservados no final."""
        llm = MagicMock()
        llm._config.model = "test"
        llm._base_url = "http://localhost"
        llm._timeout_s = 5.0
        llm._session = MagicMock()

        results = [
            _make_result(f"João 3:{i+1}", f"texto {i}", 0.9 - i * 0.05)
            for i in range(15)
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "1"}
        }
        llm._session.post.return_value = mock_response

        reranker = LLMReranker(llm)
        reranked = reranker.rerank("query", results, max_candidates=10)

        # Top 10 foram enviados ao LLM, 5 não foram
        # LLM escolheu 1 → primeiro continua sendo o primeiro
        assert reranked[0].reference == "João 3:1"
        # Resultados 11-15 devem estar no final, na ordem original
        assert reranked[10].reference == "João 3:11"
        assert len(reranked) == 15

    def test_build_prompt_includes_query_and_candidates(self) -> None:
        """Prompt de reranking deve incluir query e candidatos."""
        results = [
            _make_result("João 3:16", "Porque Deus amou o mundo"),
            _make_result("João 3:17", "Por Deus não enviou seu Filho"),
        ]
        prompt = LLMReranker._build_rerank_prompt("amor de Deus", results)
        assert "amor de Deus" in prompt
        assert "João 3:16" in prompt
        assert "João 3:17" in prompt
        assert "1." in prompt
        assert "2." in prompt
