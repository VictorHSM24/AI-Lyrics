"""BackendFallbackManager — fallback GPU→CPU com retry (Sprint 19.1).

Responsabilidade:
  - Envolver o backend ativo (GPU) e monitorar falhas de inferência.
  - Após N falhas consecutivas, recarregar backend CPU e continuar.
  - Sem reiniciar a aplicação, sem perder eventos.

Sprint 19.1 — GPU Runtime & Hardware Acceleration:
  Política: retry-then-fallback (N falhas consecutivas).
  - Se a GPU falhar (OOM, driver crash, etc.), a transcrição atual falha.
  - As próximas N-1 transcrições ainda tentam a GPU (falhas transitórias).
  - Após N falhas consecutivas, recarregar backend CPU automaticamente.
  - Logar cada falha com motivo.
  - Publicar evento BackendFallbackApplied para observabilidade.

  O BackendFallbackManager implementa a interface InferenceBackend,
  delegando ao backend ativo. Quando fallback ocorre, troca o backend
  ativo internamente — o STT não percebe a troca.

Thread Safety:
  - O STTExecutor serializa acesso (Lock), então não há concorrência.
  - Mesmo assim, usamos Lock interno para proteção futura.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from transcricao.inference_backend import InferenceBackend

logger = logging.getLogger(__name__)

__all__ = ["BackendFallbackManager", "BackendFallbackError"]


class BackendFallbackError(Exception):
    """Erro fatal — backend GPU e CPU ambos falharam."""


class BackendFallbackManager:
    """Envolve InferenceBackend com política de fallback GPU→CPU.

    Implementa a interface InferenceBackend (Protocol).

    Args:
        gpu_backend: backend GPU ativo (DirectML, CUDA, ROCm).
        cpu_backend_factory: callable que cria um novo CPUBackend
            (chamado apenas se fallback for disparado).
        max_consecutive_failures: N falhas consecutivas antes de
            fazer fallback (default: 3).
        on_fallback: callback opcional chamado quando fallback ocorre
            (para publicar evento, métricas, etc.).

    Uso:
        gpu = DirectMLBackend(model_name="large-v3-turbo")
        gpu.load()

        manager = BackendFallbackManager(
            gpu_backend=gpu,
            cpu_backend_factory=lambda: FasterWhisperBackend(cpu_config),
            max_consecutive_failures=3,
        )

        # STT usa manager como se fosse InferenceBackend.
        text, lang, prob, segs = manager.transcribe(...)
    """

    def __init__(
        self,
        gpu_backend: InferenceBackend,
        cpu_backend_factory: Callable[[], InferenceBackend],
        max_consecutive_failures: int = 3,
        on_fallback: Callable[[str], None] | None = None,
    ) -> None:
        self._gpu_backend = gpu_backend
        self._cpu_backend_factory = cpu_backend_factory
        self._cpu_backend: InferenceBackend | None = None
        self._max_failures = max_consecutive_failures
        self._on_fallback = on_fallback

        self._active_backend: InferenceBackend = gpu_backend
        self._consecutive_failures = 0
        self._fallback_active = False
        self._fallback_reason = ""
        self._lock = threading.Lock()

        # Métricas.
        self._total_transcriptions = 0
        self._total_failures = 0
        self._total_fallbacks = 0
        self._last_failure_reason = ""

        logger.info(
            "BackendFallbackManager: initialized "
            "(gpu=%s, max_failures=%d)",
            gpu_backend.backend_name, max_consecutive_failures,
        )

    # ------------------------------------------------------------------
    # Interface InferenceBackend
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Carrega o backend GPU ativo."""
        self._active_backend.load()

    def transcribe(
        self,
        audio: Any,
        language: str,
        beam_size: int,
        vad_filter: bool,
        chunk_length: int,
    ) -> tuple[str, str, float, tuple[Any, ...]]:
        """Transcreve áudio com fallback automático GPU→CPU.

        Política:
        1. Tentar backend ativo (GPU ou CPU após fallback).
        2. Se falhar e ainda em GPU, incrementar contador.
        3. Se contador >= N, disparar fallback para CPU.
        4. Se em CPU e falhar, propagar erro (não há mais fallback).

        Raises:
            BackendFallbackError: se CPU também falhar.
            Exception: erro do backend ativo.
        """
        with self._lock:
            self._total_transcriptions += 1
            try:
                result = self._active_backend.transcribe(
                    audio, language, beam_size, vad_filter, chunk_length
                )
                # Sucesso — resetar contador se estávamos em GPU.
                if not self._fallback_active:
                    self._consecutive_failures = 0
                return result

            except Exception as e:
                self._total_failures += 1
                self._last_failure_reason = str(e)
                logger.warning(
                    "BackendFallbackManager: transcribe failed on %s "
                    "(consecutive=%d/%d): %s",
                    self._active_backend.backend_name,
                    self._consecutive_failures + 1,
                    self._max_failures,
                    e,
                )

                # Se já estamos em CPU, propagar erro.
                if self._fallback_active:
                    logger.error(
                        "BackendFallbackManager: CPU backend also failed — "
                        "no more fallback available: %s", e
                    )
                    raise

                # Incrementar contador de falhas.
                self._consecutive_failures += 1

                # Se ainda não atingiu N, propagar erro (transcrição
                # atual falha, mas próximas ainda tentam GPU).
                if self._consecutive_failures < self._max_failures:
                    raise

                # Atingiu N falhas — disparar fallback.
                logger.error(
                    "BackendFallbackManager: %d consecutive failures on %s — "
                    "triggering fallback to CPU",
                    self._consecutive_failures,
                    self._active_backend.backend_name,
                )
                self._trigger_fallback(f"consecutive failures: {e}")
                # Não retentar a transcrição atual — propagar erro.
                # A próxima transcrição usará o backend CPU.
                raise

    def unload(self) -> None:
        """Libera ambos os backends."""
        with self._lock:
            try:
                self._active_backend.unload()
            except Exception as e:
                logger.warning("unload active backend failed: %s", e)
            if self._cpu_backend is not None and self._cpu_backend is not self._active_backend:
                try:
                    self._cpu_backend.unload()
                except Exception as e:
                    logger.warning("unload cpu backend failed: %s", e)
            try:
                self._gpu_backend.unload()
            except Exception as e:
                logger.warning("unload gpu backend failed: %s", e)

    def close(self) -> None:
        """Alias para unload() — compatibilidade com STTBackend Protocol."""
        self.unload()

    # ------------------------------------------------------------------
    # Propriedades (interface InferenceBackend)
    # ------------------------------------------------------------------

    @property
    def actual_device(self) -> str:
        return self._active_backend.actual_device

    @property
    def actual_compute_type(self) -> str:
        return self._active_backend.actual_compute_type

    @property
    def backend_name(self) -> str:
        return self._active_backend.backend_name

    @property
    def is_loaded(self) -> bool:
        return self._active_backend.is_loaded

    @property
    def fallback_reason(self) -> str:
        return self._fallback_reason or self._active_backend.fallback_reason

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _trigger_fallback(self, reason: str) -> None:
        """Dispara fallback: cria CPU backend, descarrega GPU, troca ativo."""
        self._fallback_reason = reason
        self._total_fallbacks += 1

        logger.warning(
            "BackendFallbackManager: triggering fallback to CPU "
            "(reason=%s)", reason
        )

        # Criar e carregar CPU backend.
        try:
            cpu = self._cpu_backend_factory()
            cpu.load()
        except Exception as e:
            logger.error(
                "BackendFallbackManager: failed to create/load CPU backend: "
                "%s", e
            )
            raise BackendFallbackError(
                f"failed to fallback to CPU: {e}"
            ) from e

        # Descarregar GPU backend (libera VRAM).
        try:
            self._gpu_backend.unload()
        except Exception as e:
            logger.warning(
                "BackendFallbackManager: failed to unload GPU backend "
                "during fallback: %s", e
            )

        # Trocar backend ativo.
        self._cpu_backend = cpu
        self._active_backend = cpu
        self._fallback_active = True
        self._consecutive_failures = 0

        logger.info(
            "BackendFallbackManager: fallback complete — now using %s",
            cpu.backend_name,
        )

        # Callback opcional (publicar evento, métricas).
        if self._on_fallback is not None:
            try:
                self._on_fallback(reason)
            except Exception as e:
                logger.warning(
                    "BackendFallbackManager: on_fallback callback failed: "
                    "%s", e
                )

    # ------------------------------------------------------------------
    # Métricas
    # ------------------------------------------------------------------

    @property
    def total_transcriptions(self) -> int:
        return self._total_transcriptions

    @property
    def total_failures(self) -> int:
        return self._total_failures

    @property
    def total_fallbacks(self) -> int:
        return self._total_fallbacks

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def is_fallback_active(self) -> bool:
        return self._fallback_active

    @property
    def last_failure_reason(self) -> str:
        return self._last_failure_reason

    def reset_failure_counter(self) -> None:
        """Reseta o contador de falhas consecutivas.

        Útil se o operador quiser tentar GPU novamente após fallback.
        """
        with self._lock:
            self._consecutive_failures = 0
