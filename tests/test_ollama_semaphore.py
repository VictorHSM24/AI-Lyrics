"""Testes do OllamaBackend semaphore (Sprint 28).

Valida que o semaphore de concorrência máxima 1 serializa acesso ao Ollama.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from semantic.ollama_backend import OllamaBackend
from semantic.types import SemanticError


class TestOllamaSemaphore:
    """Testes do semaphore de concorrência do OllamaBackend."""

    def test_semaphore_serializes_concurrent_requests(self):
        """2 requisições concorrentes são serializadas pelo semaphore."""
        backend = OllamaBackend(max_concurrency=1)

        call_order: list[str] = []
        call_lock = threading.Lock()

        def mock_send_impl(payload, timeout_s):
            # Registrar início e simular demora.
            with call_lock:
                call_order.append(f"start-{threading.current_thread().name}")
            time.sleep(0.2)
            with call_lock:
                call_order.append(f"end-{threading.current_thread().name}")
            resp = MagicMock()
            resp.http_status = 200
            resp.http_time_ms = 200.0
            resp.raw_response = "{}"
            resp.used_think_parameter = False
            return resp

        backend._send_request_impl = mock_send_impl

        results: list = []
        threads: list[threading.Thread] = []

        def run_request(idx: int):
            try:
                r = backend.send_request({"model": "test"}, timeout_s=5.0)
                results.append(("ok", idx))
            except Exception as e:
                results.append(("err", idx, e))

        for i in range(2):
            t = threading.Thread(target=run_request, args=(i,), name=f"thread-{i}")
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # Ambas devem completar.
        assert len(results) == 2
        # Verificar serialização: start-1 deve vir APÓS end-0 (ou vice-versa).
        # Com semaphore=1, não há sobreposição de start/end.
        starts = [e for e in call_order if e.startswith("start-")]
        ends = [e for e in call_order if e.startswith("end-")]
        # A primeira thread inicia, termina, depois a segunda inicia.
        # Ou seja: starts[0] < ends[0] < starts[1] < ends[1]
        assert len(starts) == 2
        assert len(ends) == 2
        # O índice do primeiro end deve ser menor que o índice do segundo start.
        first_end_idx = call_order.index(ends[0])
        second_start_idx = call_order.index(starts[1])
        assert first_end_idx < second_start_idx, \
            f"Semaphore não serializou: {call_order}"

    def test_telemetry_includes_semaphore_metrics(self):
        """get_telemetry inclui métricas de semaphore."""
        backend = OllamaBackend(max_concurrency=1)
        telemetry = backend.get_telemetry()
        assert telemetry["max_concurrency"] == 1
        assert telemetry["current_in_flight"] == 0
        assert telemetry["total_acquired"] == 0
        assert telemetry["total_released"] == 0

    def test_semaphore_released_on_error(self):
        """Semaphore é liberado mesmo se a requisição falhar."""
        backend = OllamaBackend(max_concurrency=1)

        def failing_send_impl(payload, timeout_s):
            raise SemanticError("simulated error")

        backend._send_request_impl = failing_send_impl

        # Chamar send_request — deve falhar mas liberar semaphore.
        with pytest.raises(SemanticError):
            backend.send_request({"model": "test"}, timeout_s=1.0)

        # Semaphore deve estar liberado (total_released == total_acquired).
        telemetry = backend.get_telemetry()
        assert telemetry["total_acquired"] == 1
        assert telemetry["total_released"] == 1
        assert telemetry["current_in_flight"] == 0
