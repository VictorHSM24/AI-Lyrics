"""Testes Sprint 21.1.1 — Hardening do LocalLLMProvider.

Parte 1: ThinkingSanitizer + CapabilityCache (componentes isolados).

Cobre:
  - ThinkingSanitizer: detecção e remoção de blocos de thinking.
  - CapabilityCache: detecção por capacidade, cache, idempotência.
  - is_think_rejection_error: heurísticas de rejeição.
"""

from __future__ import annotations

import json
import pytest

from semantic.thinking_sanitizer import ThinkingSanitizer, SanitizationResult
from semantic.capability_cache import (
    CapabilityCache,
    CapabilityState,
    CapabilityResult,
    is_think_rejection_error,
)


# ---------------------------------------------------------------------------
# ThinkingSanitizer
# ---------------------------------------------------------------------------


class TestThinkingSanitizer:
    """Testes do sanitizador genérico de blocos de thinking."""

    def test_no_thinking_unchanged(self):
        """Resposta sem thinking permanece inalterada."""
        sanitizer = ThinkingSanitizer()
        content = '{"intent":"none","candidates":[]}'
        result = sanitizer.sanitize(content)
        assert result.had_thinking is False
        assert result.content == content
        assert result.patterns_matched == ()

    def test_think_block_removed(self):
        """Bloco  /// é removido, JSON preservado."""
        sanitizer = ThinkingSanitizer()
        content = '<think>raciocinio longo aqui</think>\n{"intent":"show_reference","candidates":[]}'
        result = sanitizer.sanitize(content)
        assert result.had_thinking is True
        assert result.content == '{"intent":"show_reference","candidates":[]}'
        assert len(result.patterns_matched) > 0

    def test_thinking_block_removed(self):
        """Bloco <thinking>...</thinking> é removido."""
        sanitizer = ThinkingSanitizer()
        content = '<thinking>analise do texto</thinking>\n{"intent":"none","candidates":[]}'
        result = sanitizer.sanitize(content)
        assert result.had_thinking is True
        assert result.content == '{"intent":"none","candidates":[]}'
        assert len(result.patterns_matched) > 0

    def test_multiline_thinking_removed(self):
        """Blocos de thinking multiline são removidos."""
        sanitizer = ThinkingSanitizer()
        content = (
            "<think>\n"
            "Linha 1 do raciocinio\n"
            "Linha 2 do raciocinio\n"
            "Linha 3 do raciocinio\n"
            "</think>\n"
            '{"intent":"show_reference","candidates":[{"book":"Joao","chapter":3}]}'
        )
        result = sanitizer.sanitize(content)
        assert result.had_thinking is True
        assert result.content == '{"intent":"show_reference","candidates":[{"book":"Joao","chapter":3}]}'

    def test_pipe_thinking_removed(self):
        """Blocos <|thinking|>...<|/thinking|> são removidos."""
        sanitizer = ThinkingSanitizer()
        content = '<|thinking|>analise<|/thinking|>\n{"intent":"none","candidates":[]}'
        result = sanitizer.sanitize(content)
        assert result.had_thinking is True
        assert result.content == '{"intent":"none","candidates":[]}'

    def test_bracket_thinking_removed(self):
        """Blocos [thinking]...[/thinking] são removidos."""
        sanitizer = ThinkingSanitizer()
        content = '[thinking]analise[/thinking]\n{"intent":"none","candidates":[]}'
        result = sanitizer.sanitize(content)
        assert result.had_thinking is True
        assert result.content == '{"intent":"none","candidates":[]}'

    def test_empty_content(self):
        """Conteúdo vazio retorna vazio sem thinking."""
        sanitizer = ThinkingSanitizer()
        result = sanitizer.sanitize("")
        assert result.had_thinking is False
        assert result.content == ""
        assert result.original_length == 0
        assert result.cleaned_length == 0

    def test_has_thinking_fast_check(self):
        """has_thinking() é mais eficiente que sanitize() para detecção."""
        sanitizer = ThinkingSanitizer()
        assert sanitizer.has_thinking("<think>x</think>") is True
        assert sanitizer.has_thinking("<thinking>x</thinking>") is True
        assert sanitizer.has_thinking('{"intent":"none"}') is False
        assert sanitizer.has_thinking("") is False

    def test_extra_patterns(self):
        """Padrões extras são adicionados via construtor."""
        sanitizer = ThinkingSanitizer(extra_patterns=[
            (r"<reasoning>.*?</reasoning>", "custom reasoning block"),
        ])
        content = '<reasoning>analise</reasoning>\n{"intent":"none","candidates":[]}'
        result = sanitizer.sanitize(content)
        assert result.had_thinking is True
        assert result.content == '{"intent":"none","candidates":[]}'
        assert "custom reasoning block" in result.patterns_matched

    def test_unterminated_think_block(self):
        """Bloco  /// aberto sem fechamento é removido (caso de truncamento)."""
        sanitizer = ThinkingSanitizer()
        content = '<think>raciocinio sem fechamento aqui'
        result = sanitizer.sanitize(content)
        assert result.had_thinking is True
        assert result.content == ""

    def test_multiple_thinking_blocks(self):
        """Múltiplos blocos de thinking são removidos."""
        sanitizer = ThinkingSanitizer()
        content = (
            "<think>bloco 1</think>\n"
            "texto intermediario\n"
            "<think>bloco 2</think>\n"
            '{"intent":"none","candidates":[]}'
        )
        result = sanitizer.sanitize(content)
        assert result.had_thinking is True
        # O texto intermediario deve ser removido junto com os blocos
        # porque o regex DOTALL captura tudo entre <think> e </think>.
        # Mas blocos separados sao removidos independentemente.
        assert '{"intent":"none","candidates":[]}' in result.content

    def test_case_insensitive(self):
        """Padrões são case-insensitive."""
        sanitizer = ThinkingSanitizer()
        content = '<THINK>analise</THINK>\n{"intent":"none","candidates":[]}'
        result = sanitizer.sanitize(content)
        assert result.had_thinking is True
        assert result.content == '{"intent":"none","candidates":[]}'


# ---------------------------------------------------------------------------
# CapabilityCache
# ---------------------------------------------------------------------------


class TestCapabilityCache:
    """Testes do cache de capacidades do backend."""

    def test_initial_state_unknown(self):
        """Estado inicial é UNKNOWN."""
        cache = CapabilityCache()
        assert cache.get_state("think") == CapabilityState.UNKNOWN
        assert cache.should_try("think") is True

    def test_record_supported(self):
        """Após registrar SUPPORTED, estado é SUPPORTED."""
        cache = CapabilityCache()
        cache.record_detection("think", CapabilityState.SUPPORTED, detection_ms=42.5)
        assert cache.get_state("think") == CapabilityState.SUPPORTED
        assert cache.should_try("think") is False

    def test_record_unsupported(self):
        """Após registrar UNSUPPORTED, estado é UNSUPPORTED."""
        cache = CapabilityCache()
        cache.record_detection(
            "think", CapabilityState.UNSUPPORTED, error_message="unknown field",
        )
        assert cache.get_state("think") == CapabilityState.UNSUPPORTED
        assert cache.should_try("think") is False

    def test_idempotent(self):
        """Registrar duas vezes não sobrescreve o primeiro resultado."""
        cache = CapabilityCache()
        cache.record_detection("think", CapabilityState.SUPPORTED, detection_ms=10.0)
        # Tentar sobrescrever com UNSUPPORTED — deve ser ignorado.
        cache.record_detection("think", CapabilityState.UNSUPPORTED)
        assert cache.get_state("think") == CapabilityState.SUPPORTED

    def test_detection_attempts_count(self):
        """Contagem de tentativas é incrementada apenas uma vez."""
        cache = CapabilityCache()
        assert cache.get_detection_attempts("think") == 0
        cache.record_detection("think", CapabilityState.SUPPORTED)
        assert cache.get_detection_attempts("think") == 1
        # Tentar registrar novamente — não incrementa.
        cache.record_detection("think", CapabilityState.SUPPORTED)
        assert cache.get_detection_attempts("think") == 1

    def test_get_result(self):
        """get_result retorna o resultado completo."""
        cache = CapabilityCache()
        cache.record_detection(
            "think", CapabilityState.UNSUPPORTED,
            detection_ms=15.0, error_message="unknown field think",
        )
        result = cache.get_result("think")
        assert result is not None
        assert result.state == CapabilityState.UNSUPPORTED
        assert result.detection_ms == 15.0
        assert "unknown field" in result.error_message

    def test_get_result_none_if_not_detected(self):
        """get_result retorna None se não detectada."""
        cache = CapabilityCache()
        assert cache.get_result("think") is None

    def test_metrics(self):
        """metrics() retorna estrutura para telemetria."""
        cache = CapabilityCache()
        cache.record_detection("think", CapabilityState.SUPPORTED, detection_ms=42.0)
        m = cache.metrics()
        assert "capabilities" in m
        assert "think" in m["capabilities"]
        assert m["capabilities"]["think"]["state"] == "supported"
        assert m["capabilities"]["think"]["detection_ms"] == 42.0
        assert m["capabilities"]["think"]["attempts"] == 1
        assert m["total_capabilities_tracked"] == 1

    def test_reset(self):
        """reset() limpa o cache."""
        cache = CapabilityCache()
        cache.record_detection("think", CapabilityState.SUPPORTED)
        assert cache.get_state("think") == CapabilityState.SUPPORTED
        cache.reset()
        assert cache.get_state("think") == CapabilityState.UNKNOWN
        assert cache.get_detection_attempts("think") == 0

    def test_multiple_capabilities(self):
        """Cache suporta múltiplas capacidades independentes."""
        cache = CapabilityCache()
        cache.record_detection("think", CapabilityState.SUPPORTED)
        cache.record_detection("json_schema", CapabilityState.UNSUPPORTED)
        assert cache.get_state("think") == CapabilityState.SUPPORTED
        assert cache.get_state("json_schema") == CapabilityState.UNSUPPORTED
        assert cache.metrics()["total_capabilities_tracked"] == 2


# ---------------------------------------------------------------------------
# is_think_rejection_error
# ---------------------------------------------------------------------------


class TestIsThinkRejectionError:
    """Testes da heurística de detecção de rejeição do parâmetro think."""

    def test_unknown_field_400(self):
        assert is_think_rejection_error(400, '{"error":"unknown field think"}') is True

    def test_unknown_parameter_400(self):
        assert is_think_rejection_error(400, "unknown parameter 'think'") is True

    def test_invalid_parameter_422(self):
        assert is_think_rejection_error(422, "invalid parameter: think") is True

    def test_unsupported_argument_400(self):
        assert is_think_rejection_error(400, "unsupported argument think") is True

    def test_no_such_field_404(self):
        assert is_think_rejection_error(404, "no such field: think") is True

    def test_think_mentioned_with_field(self):
        assert is_think_rejection_error(400, "think is not a valid field") is True

    def test_non_rejection_500(self):
        """Erro 500 não é rejeição de parâmetro."""
        assert is_think_rejection_error(500, "internal server error") is False

    def test_non_rejection_200(self):
        """Status 200 não é erro."""
        assert is_think_rejection_error(200, "ok") is False

    def test_non_think_400(self):
        """Erro 400 sem menção a think não é rejeição de think."""
        assert is_think_rejection_error(400, "invalid model name") is False

    def test_extra_fields_422(self):
        """additional properties / extra fields indica rejeição."""
        assert is_think_rejection_error(
            422, "additional properties not allowed: think"
        ) is True


# ---------------------------------------------------------------------------
# LocalLLMProvider — Capability Detection (integração)
# ---------------------------------------------------------------------------


from semantic.local_provider import LocalLLMProvider
from semantic.types import SemanticContext


def _make_context(text: str = "Jesus conversa com Nicodemos") -> SemanticContext:
    """Cria um SemanticContext mínimo para testes."""
    return SemanticContext(
        current_text=text,
        recent_text="",
        last_book="",
        last_chapter=0,
        last_reference="",
    )


class _MockHTTPBackend:
    """Mock do backend HTTP para testar capability detection.

    Registra os payloads recebidos e retorna respostas programadas.
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        reject_think: bool = False,
        reject_status: int = 400,
        reject_body: str = '{"error":"unknown field think"}',
    ) -> None:
        self.received_payloads: list[dict] = []
        self._responses = responses or []
        self._response_idx = 0
        self.reject_think = reject_think
        self.reject_status = reject_status
        self.reject_body = reject_body

    def post(self, payload: dict, timeout_s: float) -> str:
        """Simula POST /chat/completions.

        Se reject_think e o payload contém think: false, levanta
        SemanticError com formato "HTTP 400 error: ..." para simular
        a rejeição do parâmetro think.
        """
        from semantic.types import SemanticError
        self.received_payloads.append(payload)
        # Se reject_think e o payload contém think: false, rejeitar.
        if self.reject_think and "think" in payload:
            raise SemanticError(
                f"HTTP {self.reject_status} error: {self.reject_body[:200]}"
            )
        # Retornar próxima resposta programada.
        if self._response_idx < len(self._responses):
            resp = self._responses[self._response_idx]
            self._response_idx += 1
            return resp
        # Fallback: resposta none.
        return json.dumps({
            "choices": [{"message": {"content": '{"intent":"none","candidates":[]}'}}]
        })


class TestLocalLLMProviderCapabilityDetection:
    """Testes de capability detection no LocalLLMProvider."""

    def test_capability_supported_on_first_call(self):
        """Backend que aceita think: false → SUPPORTED após primeira inferência."""
        # Mock que sempre aceita.
        backend = _MockHTTPBackend(responses=[
            json.dumps({"choices": [{"message": {"content": '{"intent":"none","candidates":[]}'}}]}),
        ])
        provider = LocalLLMProvider(
            model="qwen3:8b", disable_thinking=True, max_retries=0,
        )
        # Substituir _http_post pelo mock.
        provider._http_post = lambda payload, timeout_s: backend.post(payload, timeout_s)

        # Antes da primeira chamada: UNKNOWN.
        assert provider._capability_cache.get_state("think") == CapabilityState.UNKNOWN

        # Primeira inferência.
        result = provider.infer(_make_context())
        assert result.intent == "none"

        # Após a chamada: SUPPORTED.
        assert provider._capability_cache.get_state("think") == CapabilityState.SUPPORTED
        assert provider._supports_thinking is True

        # O payload enviado deve ter incluído think: false.
        assert "think" in backend.received_payloads[0]
        assert backend.received_payloads[0]["think"] is False

    def test_capability_unsupported_on_rejection(self):
        """Backend que rejeita think: false → UNSUPPORTED, refaz sem think."""
        # Mock que rejeita think na primeira, aceita na segunda.
        backend = _MockHTTPBackend(
            reject_think=True,
            reject_body='{"error":"unknown field think"}',
            responses=[
                # Segunda tentativa (sem think) — sucesso.
                json.dumps({"choices": [{"message": {"content": '{"intent":"none","candidates":[]}'}}]}),
            ],
        )
        provider = LocalLLMProvider(
            model="qwen3:8b", disable_thinking=True, max_retries=2,
        )
        provider._http_post = lambda payload, timeout_s: backend.post(payload, timeout_s)

        # Primeira inferência — deve detectar UNSUPPORTED e refazer.
        result = provider.infer(_make_context())
        assert result.intent == "none"

        # Após: UNSUPPORTED.
        assert provider._capability_cache.get_state("think") == CapabilityState.UNSUPPORTED
        assert provider._supports_thinking is False

        # Primeiro payload tinha think: false, segundo não.
        assert "think" in backend.received_payloads[0]
        assert backend.received_payloads[0]["think"] is False
        assert "think" not in backend.received_payloads[1]

    def test_capability_cache_avoids_retesting(self):
        """Após detecção, não testa novamente — usa cache."""
        backend = _MockHTTPBackend(responses=[
            json.dumps({"choices": [{"message": {"content": '{"intent":"none","candidates":[]}'}}]}),
            json.dumps({"choices": [{"message": {"content": '{"intent":"none","candidates":[]}'}}]}),
        ])
        provider = LocalLLMProvider(
            model="qwen3:8b", disable_thinking=True, max_retries=0,
        )
        provider._http_post = lambda payload, timeout_s: backend.post(payload, timeout_s)

        # Primeira chamada — detecta SUPPORTED.
        provider.infer(_make_context())
        assert provider._capability_cache.get_state("think") == CapabilityState.SUPPORTED
        assert provider._capability_cache.get_detection_attempts("think") == 1

        # Segunda chamada — não testa novamente.
        provider.infer(_make_context())
        assert provider._capability_cache.get_detection_attempts("think") == 1

        # Ambas as chamadas enviaram think: false (cache hit).
        assert "think" in backend.received_payloads[0]
        assert "think" in backend.received_payloads[1]

    def test_no_dependency_on_model_name(self):
        """Detecção não depende do nome do modelo.

        Modelo com nome desconhecido ainda detecta suporte via capacidade.
        """
        backend = _MockHTTPBackend(responses=[
            json.dumps({"choices": [{"message": {"content": '{"intent":"none","candidates":[]}'}}]}),
        ])
        # Nome de modelo totalmente customizado — não está em nenhuma lista.
        provider = LocalLLMProvider(
            model="my-custom-model-v2", disable_thinking=True, max_retries=0,
        )
        provider._http_post = lambda payload, timeout_s: backend.post(payload, timeout_s)

        # Antes: UNKNOWN (não assume False por nome).
        assert provider._capability_cache.get_state("think") == CapabilityState.UNKNOWN

        # Primeira chamada — detecta SUPPORTED.
        provider.infer(_make_context())
        assert provider._capability_cache.get_state("think") == CapabilityState.SUPPORTED
        # O payload enviou think: false mesmo com nome customizado.
        assert "think" in backend.received_payloads[0]


# ---------------------------------------------------------------------------
# LocalLLMProvider — Recovery (sanitização + JSON recuperado)
# ---------------------------------------------------------------------------


class TestLocalLLMProviderRecovery:
    """Testes de recovery — recupera JSON válido mesmo com thinking antes."""

    def test_thinking_block_removed_and_json_recovered(self):
        """Resposta com  /// antes do JSON é sanitizada e JSON é aceito."""
        # Resposta com bloco de thinking antes do JSON válido.
        # TODO o texto de raciocínio está dentro das tags  ///.
        content_with_thinking = (
            "\u003Cthink\u003E\n"
            "Vou analisar o texto sobre Nicodemos.\n"
            "A referencia correta e Joao 3.\n"
            "\u003C/think\u003E\n"
            '{"intent":"show_reference","candidates":['
            '{"book":"Joao","chapter":3,"verse":0,"confidence":0.85,"reason":"Nicodemos"}'
            ']}'
        )
        backend = _MockHTTPBackend(responses=[
            json.dumps({"choices": [{"message": {"content": content_with_thinking}}]}),
        ])
        provider = LocalLLMProvider(
            model="qwen3:8b", disable_thinking=True, max_retries=0,
        )
        provider._http_post = lambda payload, timeout_s: backend.post(payload, timeout_s)

        result = provider.infer(_make_context())
        # JSON recuperado — intent deve ser show_reference.
        assert result.intent == "show_reference"
        assert len(result.candidates) == 1
        assert result.candidates[0].book == "Joao"
        assert result.candidates[0].chapter == 3

        # Métricas: thinking removido e recuperado.
        m = provider.metrics()
        assert m["total_thinking_removed"] == 1
        assert m["total_thinking_recovered"] == 1

    def test_thinking_with_invalid_json_still_tries_retry(self):
        """thinking + JSON inválido → não recupera, tenta retry."""
        content_with_thinking = (
            "\u003Cthink\u003E\n"
            "Analise...\n"
            "\u003C/think\u003E\n"
            "isto nao e json valido"
        )
        backend = _MockHTTPBackend(responses=[
            json.dumps({"choices": [{"message": {"content": content_with_thinking}}]}),
            # Segunda tentativa — resposta limpa.
            json.dumps({"choices": [{"message": {"content": '{"intent":"none","candidates":[]}'}}]}),
        ])
        provider = LocalLLMProvider(
            model="qwen3:8b", disable_thinking=True, max_retries=2,
        )
        provider._http_post = lambda payload, timeout_s: backend.post(payload, timeout_s)

        result = provider.infer(_make_context())
        # Após retry, resposta limpa — intent none.
        assert result.intent == "none"

    def test_thinking_with_text_only_returns_none(self):
        """thinking + texto (sem JSON) → intent = none após retries."""
        content_with_thinking = (
            "\u003Cthink\u003E\n"
            "Apenas texto sem JSON\n"
            "\u003C/think\u003E\n"
            "mais texto aqui"
        )
        backend = _MockHTTPBackend(responses=[
            json.dumps({"choices": [{"message": {"content": content_with_thinking}}]}),
            json.dumps({"choices": [{"message": {"content": content_with_thinking}}]}),
            json.dumps({"choices": [{"message": {"content": content_with_thinking}}]}),
        ])
        provider = LocalLLMProvider(
            model="qwen3:8b", disable_thinking=True, max_retries=2,
        )
        provider._http_post = lambda payload, timeout_s: backend.post(payload, timeout_s)

        result = provider.infer(_make_context())
        assert result.intent == "none"

    def test_clean_response_no_thinking_metrics(self):
        """Resposta limpa não incrementa métricas de thinking."""
        backend = _MockHTTPBackend(responses=[
            json.dumps({"choices": [{"message": {"content": '{"intent":"none","candidates":[]}'}}]}),
        ])
        provider = LocalLLMProvider(
            model="qwen3:8b", disable_thinking=True, max_retries=0,
        )
        provider._http_post = lambda payload, timeout_s: backend.post(payload, timeout_s)

        provider.infer(_make_context())
        m = provider.metrics()
        assert m["total_thinking_removed"] == 0
        assert m["total_thinking_recovered"] == 0
        assert m["total_thinking_violations"] == 0


# ---------------------------------------------------------------------------
# LocalLLMProvider — Métricas (Sprint 21.1.1)
# ---------------------------------------------------------------------------


class TestLocalLLMProviderMetrics:
    """Testes das métricas adicionadas na Sprint 21.1.1."""

    def test_metrics_include_capability_fields(self):
        """metrics() inclui campos de capability cache."""
        provider = LocalLLMProvider(model="qwen3:8b", disable_thinking=True)
        m = provider.metrics()
        assert "backend_supports_thinking" in m
        assert "backend_capability_detection_ms" in m
        assert "capability_detection_attempts" in m
        assert m["backend_supports_thinking"] == "unknown"
        assert m["capability_detection_attempts"] == 0

    def test_metrics_include_thinking_recovery_fields(self):
        """metrics() inclui campos de thinking recovery."""
        provider = LocalLLMProvider(model="qwen3:8b", disable_thinking=True)
        m = provider.metrics()
        assert "total_thinking_removed" in m
        assert "total_thinking_recovered" in m
        assert "thinking_removed_rate" in m
        assert "thinking_recovered_rate" in m

    def test_capability_detection_attempts_expected_one(self):
        """Após detecção, capability_detection_attempts == 1."""
        backend = _MockHTTPBackend(responses=[
            json.dumps({"choices": [{"message": {"content": '{"intent":"none","candidates":[]}'}}]}),
            json.dumps({"choices": [{"message": {"content": '{"intent":"none","candidates":[]}'}}]}),
        ])
        provider = LocalLLMProvider(
            model="qwen3:8b", disable_thinking=True, max_retries=0,
        )
        provider._http_post = lambda payload, timeout_s: backend.post(payload, timeout_s)

        provider.infer(_make_context())
        provider.infer(_make_context())
        m = provider.metrics()
        # Critério de aceitação: capability_detection_attempts == 1.
        assert m["capability_detection_attempts"] == 1
