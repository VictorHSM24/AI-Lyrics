"""SlidingWindow — janela deslizante sobre o RingBuffer (Sprint 19).

Responsabilidade:
  - Extrair uma janela de áudio do RingBuffer a intervalos regulares.
  - Independente do VAD — existe continuamente, não depende de
    silêncio ou detecção de fala.
  - Dispara um callback a cada ``update_interval_ms`` com a janela
    atual (últimos ``window_seconds`` de áudio).

Design:
  - Roda em sua própria thread (``SlidingWindow-Extractor``).
  - A cada ``update_interval_ms`` (default 400ms), chama
    ``ring_buffer.read_last(window_seconds)`` e invoca o callback
    ``on_window(audio: np.ndarray, timestamp: float)``.
  - Não faz transcrição — apenas extrai e entrega o áudio.
  - A transcrição é responsabilidade do StreamingSTTService.

Sprint 19 — Streaming Speech Pipeline:
  A SlidingWindow alimenta o StreamingSTTService continuamente,
  permitindo que referências sejam detectadas ANTES do fim da fala.

Thread Safety:
  - Thread própria (``SlidingWindow-Extractor``).
  - RingBuffer é thread-safe (Lock interno).
  - Callback é invocado na thread da SlidingWindow.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import numpy as np

from microfone.ring_buffer import RingBuffer

logger = logging.getLogger(__name__)

__all__ = ["SlidingWindow"]

# Tipo do callback de janela.
OnWindowCallback = Callable[[np.ndarray, float], None]


class SlidingWindow:
    """Janela deslizante sobre um RingBuffer.

    Args:
        ring_buffer: RingBuffer de onde extrair áudio.
        window_seconds: duração da janela (ex.: 6.0).
        update_interval_ms: intervalo entre extrações (ex.: 400).
        on_window: callback chamado a cada extração.
            Assinatura: (audio: np.ndarray, timestamp: float) -> None.

    Uso:
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=20.0)
        window = SlidingWindow(
            ring_buffer=buf,
            window_seconds=6.0,
            update_interval_ms=400,
            on_window=lambda audio, ts: stt.transcribe(audio),
        )
        window.start()
        # ... áudio flui para o buf via buf.write(chunk) ...
        window.stop()
    """

    def __init__(
        self,
        ring_buffer: RingBuffer,
        window_seconds: float,
        update_interval_ms: int,
        on_window: OnWindowCallback,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(
                f"window_seconds must be > 0, got {window_seconds}"
            )
        if window_seconds > ring_buffer.duration_seconds:
            raise ValueError(
                f"window_seconds ({window_seconds}) cannot exceed "
                f"ring_buffer duration ({ring_buffer.duration_seconds})"
            )
        if update_interval_ms <= 0:
            raise ValueError(
                f"update_interval_ms must be > 0, got {update_interval_ms}"
            )
        if on_window is None:
            raise ValueError("on_window callback is required")

        self._buffer = ring_buffer
        self._window_seconds = window_seconds
        self._interval_s = update_interval_ms / 1000.0
        self._on_window = on_window

        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Métricas.
        self._total_extractions = 0
        self._total_empty = 0  # extrações com buffer vazio.

        logger.info(
            "SlidingWindow initialized: window=%.1fs interval=%dms",
            window_seconds,
            update_interval_ms,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inicia a thread de extração."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._extract_loop,
            name="SlidingWindow-Extractor",
            daemon=True,
        )
        self._thread.start()
        logger.info("SlidingWindow started — extractor thread running.")

    def stop(self) -> None:
        """Para a thread de extração."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        logger.info("SlidingWindow stopped.")

    # ------------------------------------------------------------------
    # Thread de extração
    # ------------------------------------------------------------------

    def _extract_loop(self) -> None:
        """Loop principal — extrai janela a cada intervalo."""
        logger.info("SlidingWindow extractor thread started.")
        while not self._stop_event.is_set():
            t0 = time.monotonic()

            try:
                audio = self._buffer.read_last(self._window_seconds)
                ts = time.time()
                self._total_extractions += 1
                if audio.size == 0:
                    self._total_empty += 1
                # Invocar callback mesmo com áudio vazio — permite que
                # o StreamingSTTService saiba que a janela foi extraída
                # (útil para métricas de latência).
                self._on_window(audio, ts)
            except Exception as e:
                logger.error("SlidingWindow extraction error: %s", e)

            # Esperar até o próximo intervalo.
            elapsed = time.monotonic() - t0
            wait = self._interval_s - elapsed
            if wait > 0:
                self._stop_event.wait(timeout=wait)

        logger.info("SlidingWindow extractor thread exiting.")

    # ------------------------------------------------------------------
    # Propriedades
    # ------------------------------------------------------------------

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    @property
    def update_interval_ms(self) -> int:
        return int(self._interval_s * 1000)

    @property
    def total_extractions(self) -> int:
        return self._total_extractions

    @property
    def total_empty(self) -> int:
        return self._total_empty
