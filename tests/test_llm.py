"""Testes unitários do módulo llm/ (LLMClient + prompts).

Estratégia:
  - Todos os testes usam mocks para requests.Session — sem rede.
  - Testa availability, parse válido/inválido, retry, timeout,
    conexão recusada, JSON malformado, fallback, confidence, source.
  - 100% determinístico.

Cobertura:
  - LLMClient.__init__ (lazy_load True/False)
  - LLMClient.is_available()
  - LLMClient.warmup()
  - LLMClient.interpret() — fluxo completo
  - LLMClient._call_llm() — HTTP, timeout, connection error
  - LLMClient._map_to_intent() — mapeamento JSON → Intent
  - prompts.build_messages()
  - prompts.build_correction_messages()
  - prompts.validate_response()
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from config.books import Book, BookTable
from config.models import LLMConfig
from core.types import Intent
from estado.state import BibleState
from llm import (
    CORRECTION_PROMPT,
    FEW_SHOT_EXAMPLES,
    SYSTEM_PROMPT,
    VALID_ACTIONS,
    LLMClient,
    LLMError,
    build_correction_messages,
    build_messages,
    validate_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _llm_config(
    base_url: str = "http://127.0.0.1:11434",
    model: str = "qwen3:8b-q4_k_m",
    lazy_load: bool = True,
    timeout_ms: int = 5000,
    max_tokens: int = 200,
) -> LLMConfig:
    return LLMConfig(
        base_url=base_url,
        model=model,
        lazy_load=lazy_load,
        timeout_ms=timeout_ms,
        max_tokens=max_tokens,
    )


def _book_table() -> BookTable:
    """BookTable mínima com alguns livros para testes."""
    return BookTable([
        Book(id=1, canonical="Gênesis", aliases=["genesis", "gen", "gênesis"]),
        Book(id=19, canonical="Salmos", aliases=["salmos", "salmo", "sl"]),
        Book(id=43, canonical="João", aliases=["joao", "jo", "joão"]),
        Book(id=45, canonical="Romanos", aliases=["romanos", "rm", "ro"]),
        Book(id=49, canonical="Hebreus", aliases=["hebreus", "hb", "he"]),
        Book(id=58, canonical="Hebreus", aliases=["hebreus"], priority=1),
    ])


def _ollama_response(
    content: str,
    status_code: int = 200,
) -> MagicMock:
    """Cria um mock de Response do requests com body do Ollama /api/chat."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {
        "message": {"role": "assistant", "content": content},
        "done": True,
        "model": "qwen3:8b-q4_k_m",
    }
    resp.text = json.dumps(resp.json.return_value)
    return resp


def _ollama_tags_response(
    status_code: int = 200,
) -> MagicMock:
    """Cria um mock de Response do GET /api/tags."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"models": [{"name": "qwen3:8b-q4_k_m"}]}
    return resp


def _make_client(
    config: LLMConfig | None = None,
    book_table: BookTable | None = None,
) -> LLMClient:
    """Cria LLMClient sem chamar warmup (lazy_load=True)."""
    cfg = config or _llm_config(lazy_load=True)
    bt = book_table or _book_table()
    return LLMClient(config=cfg, book_table=bt)


# ---------------------------------------------------------------------------
# Testes: prompts.build_messages
# ---------------------------------------------------------------------------


class TestBuildMessages:
    """Testa construção de messages para o endpoint /api/chat."""

    def test_build_messages_basic(self) -> None:
        msgs = build_messages("abre joão 3 16")
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == SYSTEM_PROMPT
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "abre joão 3 16"

    def test_build_messages_includes_few_shot(self) -> None:
        msgs = build_messages("teste")
        # system + few-shot (pares user/assistant) + user
        assert len(msgs) == 1 + len(FEW_SHOT_EXAMPLES) + 1
        # Verificar que few-shot está no meio
        few_shot_roles = [m["role"] for m in msgs[1:-1]]
        assert "user" in few_shot_roles
        assert "assistant" in few_shot_roles

    def test_build_messages_with_state(self) -> None:
        state = BibleState(book_id=43, chapter=3, verse=16, version="ACF")
        msgs = build_messages("próximo", state=state)
        # system + context(system) + few-shot + user
        assert len(msgs) == 1 + 1 + len(FEW_SHOT_EXAMPLES) + 1
        context_msg = msgs[1]
        assert context_msg["role"] == "system"
        assert "43" in context_msg["content"]
        assert "3" in context_msg["content"]
        assert "16" in context_msg["content"]

    def test_build_messages_with_empty_state(self) -> None:
        state = BibleState()  # is_empty() == True
        msgs = build_messages("teste", state=state)
        # Não deve adicionar mensagem de contexto
        assert len(msgs) == 1 + len(FEW_SHOT_EXAMPLES) + 1

    def test_build_messages_with_state_no_verse(self) -> None:
        state = BibleState(book_id=19, chapter=23, verse=None, version="ACF")
        msgs = build_messages("teste", state=state)
        context_msg = msgs[1]
        assert "19" in context_msg["content"]
        assert "23" in context_msg["content"]
        # verse=None não deve aparecer como "versículo=None"
        assert "versículo=None" not in context_msg["content"]


class TestBuildCorrectionMessages:
    """Testa construção de messages para retry."""

    def test_correction_adds_prompt(self) -> None:
        original = build_messages("teste")
        corrected = build_correction_messages(original)
        assert len(corrected) == len(original) + 1
        assert corrected[-1]["role"] == "system"
        assert corrected[-1]["content"] == CORRECTION_PROMPT

    def test_correction_preserves_original(self) -> None:
        original = build_messages("teste")
        original_len = len(original)
        _ = build_correction_messages(original)
        # Original não deve ser modificado
        assert len(original) == original_len


# ---------------------------------------------------------------------------
# Testes: prompts.validate_response
# ---------------------------------------------------------------------------


class TestValidateResponse:
    """Testa validação de JSON de resposta do LLM."""

    def test_valid_show(self) -> None:
        obj = {"action": "show", "book": "João", "chapter": 3, "verse": 16}
        assert validate_response(obj) is True

    def test_valid_search(self) -> None:
        obj = {"action": "search", "query": "deus amou o mundo"}
        assert validate_response(obj) is True

    def test_valid_next(self) -> None:
        obj = {"action": "next", "amount": 1}
        assert validate_response(obj) is True

    def test_valid_none(self) -> None:
        obj = {"action": "none"}
        assert validate_response(obj) is True

    def test_valid_with_confidence(self) -> None:
        obj = {"action": "show", "book": "João", "chapter": 3, "confidence": 0.95}
        assert validate_response(obj) is True

    def test_invalid_not_dict(self) -> None:
        assert validate_response("not a dict") is False
        assert validate_response(None) is False
        assert validate_response([]) is False

    def test_invalid_missing_action(self) -> None:
        assert validate_response({"book": "João"}) is False

    def test_invalid_action_value(self) -> None:
        assert validate_response({"action": "invalid"}) is False
        assert validate_response({"action": "execute"}) is False
        assert validate_response({"action": ""}) is False

    def test_invalid_show_without_book(self) -> None:
        assert validate_response({"action": "show", "chapter": 3}) is False
        assert validate_response({"action": "show", "book": ""}) is False
        assert validate_response({"action": "show", "book": "   "}) is False

    def test_invalid_search_without_query(self) -> None:
        assert validate_response({"action": "search"}) is False
        assert validate_response({"action": "search", "query": ""}) is False
        assert validate_response({"action": "search", "query": "   "}) is False

    def test_invalid_confidence_out_of_range(self) -> None:
        assert validate_response({"action": "none", "confidence": 1.5}) is False
        assert validate_response({"action": "none", "confidence": -0.1}) is False

    def test_invalid_confidence_wrong_type(self) -> None:
        assert validate_response({"action": "none", "confidence": "high"}) is False

    def test_all_valid_actions(self) -> None:
        for action in VALID_ACTIONS:
            obj: dict[str, Any] = {"action": action}
            if action == "show":
                obj["book"] = "João"
            elif action == "search":
                obj["query"] = "teste"
            assert validate_response(obj) is True, f"action={action} should be valid"


# ---------------------------------------------------------------------------
# Testes: LLMClient.__init__
# ---------------------------------------------------------------------------


class TestLLMClientInit:
    """Testa construção do LLMClient."""

    @patch("llm.client.requests.Session")
    def test_init_lazy_load_true(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        client = _make_client(_llm_config(lazy_load=True))
        # lazy_load=True → não chama warmup → não faz requests
        mock_session.post.assert_not_called()
        assert client._loaded is False

    @patch("llm.client.requests.Session")
    def test_init_lazy_load_false_calls_warmup(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response("ok")
        client = _make_client(_llm_config(lazy_load=False))
        # lazy_load=False → chama warmup no __init__
        mock_session.post.assert_called_once()
        assert client._loaded is True

    @patch("llm.client.requests.Session")
    def test_init_strips_trailing_slash(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        client = _make_client(_llm_config(base_url="http://127.0.0.1:11434/"))
        assert client._base_url == "http://127.0.0.1:11434"

    @patch("llm.client.requests.Session")
    def test_init_timeout_conversion(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        client = _make_client(_llm_config(timeout_ms=3000))
        assert client._timeout_s == 3.0


# ---------------------------------------------------------------------------
# Testes: LLMClient.is_available
# ---------------------------------------------------------------------------


class TestIsAvailable:
    """Testa verificação de disponibilidade do servidor."""

    @patch("llm.client.requests.Session")
    def test_available_true(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _ollama_tags_response(200)
        client = _make_client()
        assert client.is_available() is True
        mock_session.get.assert_called_once()

    @patch("llm.client.requests.Session")
    def test_available_false_http_error(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _ollama_tags_response(500)
        client = _make_client()
        assert client.is_available() is False

    @patch("llm.client.requests.Session")
    def test_available_false_connection_error(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.ConnectionError("refused")
        client = _make_client()
        assert client.is_available() is False

    @patch("llm.client.requests.Session")
    def test_available_false_timeout(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.Timeout("timed out")
        client = _make_client()
        assert client.is_available() is False


# ---------------------------------------------------------------------------
# Testes: LLMClient.warmup
# ---------------------------------------------------------------------------


class TestWarmup:
    """Testa pré-carregamento do modelo."""

    @patch("llm.client.requests.Session")
    def test_warmup_success(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response("ok")
        client = _make_client()
        client.warmup()
        assert client._loaded is True
        mock_session.post.assert_called_once()

    @patch("llm.client.requests.Session")
    def test_warmup_already_loaded(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response("ok")
        client = _make_client()
        client.warmup()
        client.warmup()  # segunda chamada
        # Só deve chamar post uma vez
        mock_session.post.assert_called_once()

    @patch("llm.client.requests.Session")
    def test_warmup_http_error(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response("error", status_code=500)
        client = _make_client()
        client.warmup()
        assert client._loaded is False

    @patch("llm.client.requests.Session")
    def test_warmup_connection_error(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.side_effect = requests.exceptions.ConnectionError("refused")
        client = _make_client()
        client.warmup()
        # Não levanta erro, apenas loga
        assert client._loaded is False


# ---------------------------------------------------------------------------
# Testes: LLMClient.interpret — parse válido
# ---------------------------------------------------------------------------


class TestInterpretValid:
    """Testa interpret() com respostas válidas do LLM."""

    @patch("llm.client.requests.Session")
    def test_parse_show(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        content = json.dumps({
            "action": "show",
            "book": "Hebreus",
            "chapter": 11,
            "verse": 1,
            "confidence": 0.98,
        })
        mock_session.post.return_value = _ollama_response(content)
        client = _make_client()
        intent = client.interpret("vamos abrir em hebreus 11 verso 1")
        assert intent.action == "show"
        assert intent.book == "Hebreus"
        assert intent.chapter == 11
        assert intent.verse == 1
        assert intent.confidence == 0.98
        assert intent.source == "llm"
        assert intent.raw == "vamos abrir em hebreus 11 verso 1"

    @patch("llm.client.requests.Session")
    def test_parse_search(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        content = json.dumps({
            "action": "search",
            "query": "todas as coisas cooperam para o bem",
            "confidence": 0.92,
        })
        mock_session.post.return_value = _ollama_response(content)
        client = _make_client()
        intent = client.interpret("aquele texto que diz que todas as coisas cooperam para o bem")
        assert intent.action == "search"
        assert intent.query == "todas as coisas cooperam para o bem"
        assert intent.confidence == 0.92
        assert intent.source == "llm"

    @patch("llm.client.requests.Session")
    def test_parse_next(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        content = json.dumps({"action": "next", "amount": 1, "confidence": 0.9})
        mock_session.post.return_value = _ollama_response(content)
        client = _make_client()
        intent = client.interpret("próximo versículo")
        assert intent.action == "next"
        assert intent.amount == 1
        assert intent.confidence == 0.9
        assert intent.source == "llm"

    @patch("llm.client.requests.Session")
    def test_parse_none(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        content = json.dumps({"action": "none", "confidence": 0.3})
        mock_session.post.return_value = _ollama_response(content)
        client = _make_client()
        intent = client.interpret("olá como vai")
        assert intent.action == "none"
        assert intent.confidence == 0.3
        assert intent.source == "llm"

    @patch("llm.client.requests.Session")
    def test_parse_without_confidence_uses_default(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        content = json.dumps({"action": "none"})
        mock_session.post.return_value = _ollama_response(content)
        client = _make_client()
        intent = client.interpret("teste")
        assert intent.confidence == 0.7  # _DEFAULT_CONFIDENCE

    @patch("llm.client.requests.Session")
    def test_parse_resolves_book_id(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        content = json.dumps({
            "action": "show",
            "book": "João",
            "chapter": 3,
            "verse": 16,
            "confidence": 0.95,
        })
        mock_session.post.return_value = _ollama_response(content)
        client = _make_client()
        intent = client.interpret("abre joão 3 16")
        assert intent.book_id == 43  # João = id 43 na BookTable de teste
        assert intent.book == "João"

    @patch("llm.client.requests.Session")
    def test_parse_book_not_in_table(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        content = json.dumps({
            "action": "show",
            "book": "Filemom",
            "chapter": 1,
            "verse": 1,
            "confidence": 0.8,
        })
        mock_session.post.return_value = _ollama_response(content)
        client = _make_client()
        intent = client.interpret("abre filemom 1 1")
        assert intent.action == "show"
        assert intent.book == "Filemom"
        assert intent.book_id is None  # não encontrado na BookTable de teste

    @patch("llm.client.requests.Session")
    def test_parse_empty_text(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        client = _make_client()
        intent = client.interpret("")
        assert intent.action == "none"
        assert intent.confidence == 0.0
        assert intent.source == "llm"
        mock_session.post.assert_not_called()

    @patch("llm.client.requests.Session")
    def test_parse_whitespace_text(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        client = _make_client()
        intent = client.interpret("   ")
        assert intent.action == "none"
        assert intent.confidence == 0.0
        mock_session.post.assert_not_called()

    @patch("llm.client.requests.Session")
    def test_parse_with_state(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        content = json.dumps({"action": "next", "amount": 1, "confidence": 0.9})
        mock_session.post.return_value = _ollama_response(content)
        client = _make_client()
        state = BibleState(book_id=43, chapter=3, verse=16, version="ACF")
        intent = client.interpret("próximo", state=state)
        assert intent.action == "next"
        # Verificar que o state foi passado no payload
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]
        messages = payload["messages"]
        # Deve ter uma mensagem de contexto com book_id=43
        context_msgs = [m for m in messages if "43" in m.get("content", "")]
        assert len(context_msgs) > 0


# ---------------------------------------------------------------------------
# Testes: LLMClient.interpret — retry e fallback
# ---------------------------------------------------------------------------


class TestInterpretRetry:
    """Testa retry quando JSON é inválido."""

    @patch("llm.client.requests.Session")
    def test_retry_succeeds_on_second_attempt(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        # Primeira: JSON inválido; segunda: JSON válido
        invalid = _ollama_response("not json at all")
        valid = _ollama_response(json.dumps({"action": "none", "confidence": 0.5}))
        mock_session.post.side_effect = [invalid, valid]
        client = _make_client()
        client._loaded = True  # pular warmup
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.5
        assert mock_session.post.call_count == 2

    @patch("llm.client.requests.Session")
    def test_retry_fails_returns_none_intent(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        # Ambas inválidas
        mock_session.post.side_effect = [
            _ollama_response("garbage"),
            _ollama_response("still garbage"),
        ]
        client = _make_client()
        client._loaded = True  # pular warmup
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.0
        assert intent.source == "llm"
        assert mock_session.post.call_count == 2

    @patch("llm.client.requests.Session")
    def test_retry_with_invalid_action(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        # action inválida na primeira, válida na segunda
        mock_session.post.side_effect = [
            _ollama_response(json.dumps({"action": "invalid_action"})),
            _ollama_response(json.dumps({"action": "none", "confidence": 0.4})),
        ]
        client = _make_client()
        client._loaded = True  # pular warmup
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.4

    @patch("llm.client.requests.Session")
    def test_retry_show_without_book_then_valid(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.side_effect = [
            _ollama_response(json.dumps({"action": "show", "chapter": 3})),
            _ollama_response(json.dumps({
                "action": "show", "book": "João", "chapter": 3, "confidence": 0.9
            })),
        ]
        client = _make_client()
        client._loaded = True  # pular warmup
        intent = client.interpret("abre joão 3")
        assert intent.action == "show"
        assert intent.book == "João"

    @patch("llm.client.requests.Session")
    def test_no_retry_on_valid_first_response(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response(
            json.dumps({"action": "none", "confidence": 0.5})
        )
        client = _make_client()
        client._loaded = True  # pular warmup
        intent = client.interpret("teste")
        assert intent.action == "none"
        # Só uma chamada — não deve retry
        assert mock_session.post.call_count == 1


# ---------------------------------------------------------------------------
# Testes: LLMClient.interpret — erros de conexão
# ---------------------------------------------------------------------------


class TestInterpretConnectionErrors:
    """Testa comportamento com erros de rede."""

    @patch("llm.client.requests.Session")
    def test_timeout_returns_none_intent(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.side_effect = requests.exceptions.Timeout("timed out")
        client = _make_client()
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.0
        assert intent.source == "llm"

    @patch("llm.client.requests.Session")
    def test_connection_refused_returns_none_intent(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.side_effect = requests.exceptions.ConnectionError("refused")
        client = _make_client()
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.0

    @patch("llm.client.requests.Session")
    def test_timeout_then_retry_succeeds(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.side_effect = [
            requests.exceptions.Timeout("timed out"),
            _ollama_response(json.dumps({"action": "none", "confidence": 0.5})),
        ]
        client = _make_client()
        client._loaded = True  # pular warmup
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.5
        assert mock_session.post.call_count == 2

    @patch("llm.client.requests.Session")
    def test_http_500_returns_none_intent(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response("error", status_code=500)
        client = _make_client()
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.0

    @patch("llm.client.requests.Session")
    def test_http_404_returns_none_intent(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response("not found", status_code=404)
        client = _make_client()
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.0


# ---------------------------------------------------------------------------
# Testes: JSON malformado
# ---------------------------------------------------------------------------


class TestMalformedJSON:
    """Testa parsing de JSON malformado na resposta do LLM."""

    @patch("llm.client.requests.Session")
    def test_content_not_json(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response("this is not json")
        client = _make_client()
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.0

    @patch("llm.client.requests.Session")
    def test_content_partial_json(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response('{"action": "show", "book":')
        client = _make_client()
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.0

    @patch("llm.client.requests.Session")
    def test_content_with_markdown_wrapper(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        # LLM às vezes envolve JSON em markdown
        mock_session.post.return_value = _ollama_response(
            '```json\n{"action": "none", "confidence": 0.5}\n```'
        )
        client = _make_client()
        intent = client.interpret("teste")
        # json.loads não consegue parsear com markdown → fallback
        assert intent.action == "none"
        assert intent.confidence == 0.0

    @patch("llm.client.requests.Session")
    def test_response_body_not_json(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("not json")
        resp.text = "not json"
        mock_session.post.return_value = resp
        client = _make_client()
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.0

    @patch("llm.client.requests.Session")
    def test_response_no_message_field(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"done": True}  # sem "message"
        resp.text = "{}"
        mock_session.post.return_value = resp
        client = _make_client()
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.0

    @patch("llm.client.requests.Session")
    def test_response_empty_content(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"message": {"content": ""}}
        resp.text = "{}"
        mock_session.post.return_value = resp
        client = _make_client()
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.0


# ---------------------------------------------------------------------------
# Testes: confidence e source
# ---------------------------------------------------------------------------


class TestConfidenceAndSource:
    """Testa que confidence e source são sempre corretos."""

    @patch("llm.client.requests.Session")
    def test_source_always_llm(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response(
            json.dumps({"action": "show", "book": "João", "chapter": 1, "confidence": 0.9})
        )
        client = _make_client()
        intent = client.interpret("abre joão 1")
        assert intent.source == "llm"

    @patch("llm.client.requests.Session")
    def test_source_llm_on_fallback(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response("invalid")
        client = _make_client()
        intent = client.interpret("teste")
        assert intent.source == "llm"
        assert intent.action == "none"

    @patch("llm.client.requests.Session")
    def test_confidence_clamped_high(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response(
            json.dumps({"action": "none", "confidence": 1.5})
        )
        client = _make_client()
        intent = client.interpret("teste")
        # validate_response rejeita confidence > 1.0 → retry → fallback
        assert intent.action == "none"
        assert intent.confidence == 0.0

    @patch("llm.client.requests.Session")
    def test_confidence_clamped_low(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response(
            json.dumps({"action": "none", "confidence": -0.5})
        )
        client = _make_client()
        intent = client.interpret("teste")
        assert intent.action == "none"
        assert intent.confidence == 0.0

    @patch("llm.client.requests.Session")
    def test_confidence_exact_boundaries(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        # 0.0 e 1.0 são válidos
        for conf in [0.0, 1.0]:
            mock_session.post.return_value = _ollama_response(
                json.dumps({"action": "none", "confidence": conf})
            )
            client = _make_client()
            intent = client.interpret("teste")
            assert intent.confidence == conf


# ---------------------------------------------------------------------------
# Testes: lazy load
# ---------------------------------------------------------------------------


class TestLazyLoad:
    """Testa comportamento de lazy load."""

    @patch("llm.client.requests.Session")
    def test_lazy_load_warmup_on_first_interpret(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        # warmup + interpret = 2 chamadas post
        mock_session.post.return_value = _ollama_response(
            json.dumps({"action": "none", "confidence": 0.5})
        )
        client = _make_client(_llm_config(lazy_load=True))
        assert client._loaded is False
        client.interpret("teste")
        # warmup (1) + interpret (1 ou 2) → pelo menos 2
        assert mock_session.post.call_count >= 2

    @patch("llm.client.requests.Session")
    def test_lazy_load_skipped_if_already_loaded(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response(
            json.dumps({"action": "none", "confidence": 0.5})
        )
        client = _make_client(_llm_config(lazy_load=True))
        client._loaded = True  # simular já carregado
        client.interpret("teste")
        # Só interpret (1 chamada), sem warmup
        assert mock_session.post.call_count == 1


# ---------------------------------------------------------------------------
# Testes: payload enviado ao Ollama
# ---------------------------------------------------------------------------


class TestPayload:
    """Testa que o payload enviado ao Ollama está correto."""

    @patch("llm.client.requests.Session")
    def test_payload_contains_model(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response(
            json.dumps({"action": "none", "confidence": 0.5})
        )
        client = _make_client(_llm_config(model="qwen3:8b-q4_k_m"))
        client._loaded = True
        client.interpret("teste")
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]
        assert payload["model"] == "qwen3:8b-q_m" or payload["model"] == "qwen3:8b-q4_k_m"

    @patch("llm.client.requests.Session")
    def test_payload_contains_format_json(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response(
            json.dumps({"action": "none", "confidence": 0.5})
        )
        client = _make_client()
        client._loaded = True
        client.interpret("teste")
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]
        assert payload["format"] == "json"
        assert payload["stream"] is False

    @patch("llm.client.requests.Session")
    def test_payload_contains_max_tokens(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response(
            json.dumps({"action": "none", "confidence": 0.5})
        )
        client = _make_client(_llm_config(max_tokens=150))
        client._loaded = True
        client.interpret("teste")
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]
        assert payload["options"]["num_predict"] == 150

    @patch("llm.client.requests.Session")
    def test_payload_endpoint_is_api_chat(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response(
            json.dumps({"action": "none", "confidence": 0.5})
        )
        client = _make_client()
        client._loaded = True
        client.interpret("teste")
        call_args = mock_session.post.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        assert "/api/chat" in url

    @patch("llm.client.requests.Session")
    def test_payload_contains_think_false(self, mock_session_cls: MagicMock) -> None:
        """Payload deve conter think=False no nível raiz (não em options)."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response(
            json.dumps({"action": "none", "confidence": 0.5})
        )
        client = _make_client()
        client._loaded = True
        client.interpret("teste")
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]
        assert payload["think"] is False
        # think deve estar no nível raiz, não dentro de options
        assert "think" not in payload.get("options", {})

    @patch("llm.client.requests.Session")
    def test_warmup_payload_contains_think_false(
        self, mock_session_cls: MagicMock
    ) -> None:
        """Payload do warmup também deve conter think=False."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value = _ollama_response(
            json.dumps({"action": "none", "confidence": 0.5})
        )
        client = _make_client(_llm_config(lazy_load=False))
        # warmup é chamado no __init__ quando lazy_load=False
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]
        assert payload["think"] is False


# ---------------------------------------------------------------------------
# Testes: close e context manager
# ---------------------------------------------------------------------------


class TestClose:
    """Testa fechamento da sessão HTTP."""

    @patch("llm.client.requests.Session")
    def test_close_calls_session_close(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        client = _make_client()
        client.close()
        mock_session.close.assert_called_once()

    @patch("llm.client.requests.Session")
    def test_context_manager(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        with _make_client() as client:
            assert client is not None
        mock_session.close.assert_called_once()


# ---------------------------------------------------------------------------
# Testes: LLMError
# ---------------------------------------------------------------------------


class TestLLMError:
    """Testa exceção LLMError."""

    def test_llm_error_is_ailyrics_error(self) -> None:
        from core.exceptions import AILyricsError
        err = LLMError("test error")
        assert isinstance(err, AILyricsError)
        assert isinstance(err, Exception)
        assert str(err) == "test error"

    def test_llm_error_raisable(self) -> None:
        with pytest.raises(LLMError, match="test"):
            raise LLMError("test error")


# ---------------------------------------------------------------------------
# Testes: Regra anti-inferência de referências bíblicas
# ---------------------------------------------------------------------------


class TestAntiInferenceRule:
    """Valida que o prompt e few-shot examples impedem o LLM de inventar
    referências bíblicas quando o usuário não citar livro/capítulo/versículo.

    Estes testes verificam o CONTEÚDO do prompt e dos exemplos few-shot,
    não chamam o LLM real. A garantia final depende do modelo, mas o prompt
    deve conter instruções claras e exemplos que reforçam a regra.
    """

    # --- System prompt contém a regra ---

    def test_system_prompt_contains_anti_inference_rule(self) -> None:
        """SYSTEM_PROMPT deve mencionar explicitamente a proibição de inventar."""
        prompt_lower = SYSTEM_PROMPT.lower()
        # Deve mencionar "invente" ou "inventar" ou proibição similar
        assert "invent" in prompt_lower or "nunca" in prompt_lower
        # Deve mencionar action="search" como obrigatório para descrições
        assert "search" in prompt_lower
        # Deve mencionar action="show" apenas com referência explícita
        assert "show" in prompt_lower

    def test_system_prompt_mentions_explicit_reference(self) -> None:
        """SYSTEM_PROMPT deve exigir referência explícita para action=show."""
        assert "explicit" in SYSTEM_PROMPT.lower()

    def test_system_prompt_contains_search_examples(self) -> None:
        """SYSTEM_PROMPT deve conter exemplos de action=search para descrições."""
        # Os 4 casos obrigatórios devem aparecer no prompt
        assert "todas as coisas cooperam" in SYSTEM_PROMPT.lower()
        assert "vale da sombra da morte" in SYSTEM_PROMPT.lower()
        assert "tudo posso naquele que me fortalece" in SYSTEM_PROMPT.lower()
        assert "fé" in SYSTEM_PROMPT.lower() and "certeza" in SYSTEM_PROMPT.lower()

    def test_system_prompt_contains_show_examples(self) -> None:
        """SYSTEM_PROMPT deve conter exemplos de action=show com referência."""
        assert "joão 3:16" in SYSTEM_PROMPT.lower() or "joão" in SYSTEM_PROMPT.lower()
        assert "hebreus" in SYSTEM_PROMPT.lower()

    def test_system_prompt_declares_extractor_role(self) -> None:
        """SYSTEM_PROMPT deve declarar que o LLM é extrator, não base de conhecimento."""
        assert "extrator" in SYSTEM_PROMPT.lower()

    def test_system_prompt_declares_search_as_source_of_truth(self) -> None:
        """SYSTEM_PROMPT deve declarar que a busca é a fonte da verdade."""
        prompt_lower = SYSTEM_PROMPT.lower()
        assert "fonte da verdade" in prompt_lower or "busca" in prompt_lower

    # --- Few-shot examples reforçam a regra ---

    def test_few_shot_contains_search_for_cooperam(self) -> None:
        """Few-shot deve ter exemplo de search para 'todas as coisas cooperam'."""
        contents = [e["content"] for e in FEW_SHOT_EXAMPLES]
        # User message com a frase
        user_msgs = [c for c in contents if "cooperam" in c.lower()]
        assert len(user_msgs) >= 1
        # Assistant response correspondente deve ser search
        assistant_msgs = [c for c in contents if "search" in c and "cooperam" in c.lower()]
        assert len(assistant_msgs) >= 1

    def test_few_shot_contains_search_for_vale_sombra(self) -> None:
        """Few-shot deve ter exemplo de search para 'vale da sombra da morte'."""
        contents = [e["content"] for e in FEW_SHOT_EXAMPLES]
        user_msgs = [c for c in contents if "vale da sombra" in c.lower()]
        assert len(user_msgs) >= 1
        assistant_msgs = [c for c in contents if "search" in c and "vale da sombra" in c.lower()]
        assert len(assistant_msgs) >= 1

    def test_few_shot_contains_search_for_tudo_posso(self) -> None:
        """Few-shot deve ter exemplo de search para 'tudo posso naquele que me fortalece'."""
        contents = [e["content"] for e in FEW_SHOT_EXAMPLES]
        user_msgs = [c for c in contents if "tudo posso" in c.lower()]
        assert len(user_msgs) >= 1
        assistant_msgs = [c for c in contents if "search" in c and "tudo posso" in c.lower()]
        assert len(assistant_msgs) >= 1

    def test_few_shot_contains_search_for_fe_certeza(self) -> None:
        """Few-shot deve ter exemplo de search para 'fé é a certeza'."""
        contents = [e["content"] for e in FEW_SHOT_EXAMPLES]
        user_msgs = [c for c in contents if "fé" in c.lower() and "certeza" in c.lower()]
        assert len(user_msgs) >= 1
        assistant_msgs = [
            c for c in contents
            if "search" in c and ("fé" in c.lower() or "certeza" in c.lower())
        ]
        assert len(assistant_msgs) >= 1

    def test_few_shot_contains_show_with_explicit_reference(self) -> None:
        """Few-shot deve ter exemplo de show com referência explícita (Hebreus 11:1)."""
        contents = [e["content"] for e in FEW_SHOT_EXAMPLES]
        # Hebreus 11:1
        show_msgs = [
            c for c in contents
            if "show" in c and "hebreus" in c.lower() and "11" in c
        ]
        assert len(show_msgs) >= 1

    def test_few_shot_show_examples_all_have_book_chapter(self) -> None:
        """Todos os exemplos few-shot com action=show devem ter book e chapter."""
        for example in FEW_SHOT_EXAMPLES:
            if example["role"] == "assistant":
                try:
                    obj = json.loads(example["content"])
                except json.JSONDecodeError:
                    continue
                if obj.get("action") == "show":
                    assert "book" in obj, f"show example missing book: {obj}"
                    assert "chapter" in obj, f"show example missing chapter: {obj}"

    def test_few_shot_search_examples_never_have_book(self) -> None:
        """Exemplos few-shot com action=search NUNCA devem ter book/chapter/verse."""
        for example in FEW_SHOT_EXAMPLES:
            if example["role"] == "assistant":
                try:
                    obj = json.loads(example["content"])
                except json.JSONDecodeError:
                    continue
                if obj.get("action") == "search":
                    assert "book" not in obj, f"search example has book: {obj}"
                    assert "chapter" not in obj, f"search example has chapter: {obj}"
                    assert "verse" not in obj, f"search example has verse: {obj}"

    def test_few_shot_has_at_least_4_search_examples(self) -> None:
        """Deve haver pelo menos 4 exemplos de search (casos obrigatórios)."""
        search_count = 0
        for example in FEW_SHOT_EXAMPLES:
            if example["role"] == "assistant":
                try:
                    obj = json.loads(example["content"])
                    if obj.get("action") == "search":
                        search_count += 1
                except json.JSONDecodeError:
                    pass
        assert search_count >= 4

    def test_few_shot_has_at_least_2_show_examples(self) -> None:
        """Deve haver pelo menos 2 exemplos de show com referência explícita."""
        show_count = 0
        for example in FEW_SHOT_EXAMPLES:
            if example["role"] == "assistant":
                try:
                    obj = json.loads(example["content"])
                    if obj.get("action") == "show":
                        show_count += 1
                except json.JSONDecodeError:
                    pass
        assert show_count >= 2

    # --- Correction prompt reforça a regra ---

    def test_correction_prompt_mentions_anti_inference(self) -> None:
        """CORRECTION_PROMPT deve mencionar a regra anti-inferência."""
        prompt_lower = CORRECTION_PROMPT.lower()
        assert "invent" in prompt_lower or "nunca" in prompt_lower
        assert "search" in prompt_lower
        assert "show" in prompt_lower

    def test_correction_prompt_mentions_explicit_reference(self) -> None:
        """CORRECTION_PROMPT deve mencionar referência explícita."""
        assert "explicit" in CORRECTION_PROMPT.lower()

    # --- build_messages inclui o prompt reforçado ---

    def test_build_messages_contains_anti_inference_rule(self) -> None:
        """build_messages deve incluir o SYSTEM_PROMPT com a regra."""
        msgs = build_messages("teste qualquer")
        system_msg = msgs[0]["content"]
        assert "invent" in system_msg.lower() or "nunca" in system_msg.lower()
        assert "extrator" in system_msg.lower()

    def test_build_messages_contains_all_4_search_examples(self) -> None:
        """build_messages deve incluir os 4 casos obrigatórios de search."""
        msgs = build_messages("teste")
        all_content = " ".join(m["content"] for m in msgs).lower()
        assert "todas as coisas cooperam" in all_content
        assert "vale da sombra da morte" in all_content
        assert "tudo posso naquele que me fortalece" in all_content
        assert "fé" in all_content and "certeza" in all_content


class TestFewShotIntegrity:
    """Valida integridade estrutural dos few-shot examples após mudanças."""

    def test_all_assistant_responses_are_valid_json(self) -> None:
        """Todos os assistant responses nos few-shot devem ser JSON válido."""
        for i, example in enumerate(FEW_SHOT_EXAMPLES):
            if example["role"] == "assistant":
                try:
                    json.loads(example["content"])
                except json.JSONDecodeError as e:
                    pytest.fail(
                        f"FEW_SHOT_EXAMPLES[{i}] assistant content is not valid JSON: {e}"
                    )

    def test_all_user_assistant_pairs_alternate(self) -> None:
        """Few-shot examples devem alternar user → assistant → user → assistant."""
        roles = [e["role"] for e in FEW_SHOT_EXAMPLES]
        for i in range(0, len(roles), 2):
            assert roles[i] == "user", f"Expected user at index {i}, got {roles[i]}"
            if i + 1 < len(roles):
                assert roles[i + 1] == "assistant", (
                    f"Expected assistant at index {i+1}, got {roles[i+1]}"
                )

    def test_few_shot_count_is_even(self) -> None:
        """Número de few-shot examples deve ser par (pares user/assistant)."""
        assert len(FEW_SHOT_EXAMPLES) % 2 == 0

    def test_all_assistant_responses_pass_validation(self) -> None:
        """Todos os assistant responses devem passar validate_response()."""
        for i, example in enumerate(FEW_SHOT_EXAMPLES):
            if example["role"] == "assistant":
                obj = json.loads(example["content"])
                assert validate_response(obj), (
                    f"FEW_SHOT_EXAMPLES[{i}] failed validation: {obj}"
                )
