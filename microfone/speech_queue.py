"""SpeechQueue — fila thread-safe para SpeechSegments (Sprint 16).

Fila produtor-consumidor entre o VAD (produtor) e o SpeechWorker (consumidor).
Usa queue.Queue (thread-safe, lock-free via deque interno).

O produtor (VAD thread) chama put() para enfileirar um SpeechSegment.
O consumidor (SpeechWorker thread) chama get() para desenfileirar.

Características:
  - Thread-safe (queue.Queue usa Lock internamente).
  - Bounded: tamanho máximo configurável (evita OOM se Whisper travar).
  - Non-blocking: put_nowait() e get_nowait() disponíveis.
  - Métricas: tamanho atual, total enfileirado, total desenfileirado.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any

from microfone.capture import SpeechSegment

logger = logging.getLogger(__name__)


@dataclass
class SpeechQueueMetrics:
    """Métricas da fila para monitoramento."""

    total_enqueued: int = 0
    total_dequeued: int = 0
    total_dropped: int = 0  # descartados por fila cheia
    current_size: int = 0
    max_size_reached: int = 0


class SpeechQueue:
    """Fila thread-safe para SpeechSegments.

    Produtor: VAD thread (put).
    Consumidor: SpeechWorker thread (get).

    Args:
        maxsize: tamanho máximo da fila (0 = ilimitado).
            Default: 10 — se Whisper travar, descarta segmentos antigos
            em vez de acumular memória indefinidamente.
    """

    def __init__(self, maxsize: int = 10) -> None:
        self._queue: queue.Queue[SpeechSegment] = queue.Queue(maxsize=maxsize)
        self._metrics = SpeechQueueMetrics()
        self._lock = threading.Lock()

    def put(self, segment: SpeechSegment) -> bool:
        """Enfileira um SpeechSegment.

        Returns:
            True se enfileirado, False se a fila estava cheia (descartado).
        """
        try:
            self._queue.put_nowait(segment)
            with self._lock:
                self._metrics.total_enqueued += 1
                self._metrics.current_size = self._queue.qsize()
                if self._metrics.current_size > self._metrics.max_size_reached:
                    self._metrics.max_size_reached = self._metrics.current_size
            return True
        except queue.Full:
            with self._lock:
                self._metrics.total_dropped += 1
            logger.warning(
                "SpeechQueue full — dropping segment (duration=%d ms)",
                segment.duration_ms,
            )
            return False

    def get(self, timeout: float | None = None) -> SpeechSegment | None:
        """Desenfileira um SpeechSegment.

        Args:
            timeout: tempo máximo de espera em segundos. None = bloqueia indefinidamente.

        Returns:
            SpeechSegment ou None se timeout.
        """
        try:
            segment = self._queue.get(timeout=timeout)
            with self._lock:
                self._metrics.total_dequeued += 1
                self._metrics.current_size = self._queue.qsize()
            return segment
        except queue.Empty:
            return None

    def get_nowait(self) -> SpeechSegment | None:
        """Desenfileira sem bloquear. Retorna None se vazia."""
        try:
            segment = self._queue.get_nowait()
            with self._lock:
                self._metrics.total_dequeued += 1
                self._metrics.current_size = self._queue.qsize()
            return segment
        except queue.Empty:
            return None

    def qsize(self) -> int:
        """Tamanho atual da fila."""
        return self._queue.qsize()

    def empty(self) -> bool:
        """True se a fila está vazia."""
        return self._queue.empty()

    def clear(self) -> int:
        """Limpa a fila e retorna quantos itens foram removidos."""
        count = 0
        while True:
            try:
                self._queue.get_nowait()
                count += 1
            except queue.Empty:
                break
        with self._lock:
            self._metrics.current_size = 0
        return count

    @property
    def metrics(self) -> SpeechQueueMetrics:
        """Métricas atuais da fila."""
        with self._lock:
            return SpeechQueueMetrics(
                total_enqueued=self._metrics.total_enqueued,
                total_dequeued=self._metrics.total_dequeued,
                total_dropped=self._metrics.total_dropped,
                current_size=self._queue.qsize(),
                max_size_reached=self._metrics.max_size_reached,
            )
