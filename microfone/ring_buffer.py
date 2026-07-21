"""RingBuffer — buffer circular de áudio para streaming STT (Sprint 19).

Responsabilidade:
  - Manter os últimos N segundos de áudio em memória.
  - Atualização contínua a cada chunk do AudioCaptureService.
  - Thread-safe (escrito na thread PortAudio, lido na thread
    StreamingSTTService).
  - Reutiliza memória: usa numpy.ndarray pré-alocado e índices
    circulares (sem realocação, sem cópias desnecessárias).

Design:
  - Pré-aloca um ndarray float32 de tamanho fixo
    (sample_rate * duration_seconds * channels).
  - Mantém índice _head (próxima posição de escrita) e _filled
    (quantas amostras válidas existem).
  - write(): copia chunk para o buffer na posição _head, avança
    _head modularmente.
  - read_last(seconds): retorna os últimos N segundos de áudio
    como ndarray contíguo (copia apenas no read, não no write).

Sprint 19 — Streaming Speech Pipeline:
  Este buffer representa o "estado atual do sermão". A SlidingWindow
  extrai janelas dele a cada 400ms para alimentar o StreamingSTTService.

Thread Safety:
  - write() é chamado na thread PortAudio (callback de áudio).
  - read_last() é chamado na thread StreamingSTT.
  - Protegido por threading.Lock (granularidade fina — apenas
    índices, não o array inteiro).
  - O array é pré-alocado e nunca redimensionado, então não há
    risco de realocação durante leitura.
"""

from __future__ import annotations

import logging
import threading

import numpy as np

logger = logging.getLogger(__name__)

__all__ = ["RingBuffer"]


class RingBuffer:
    """Buffer circular de áudio float32 [-1.0, 1.0].

    Mantém os últimos ``duration_seconds`` de áudio em memória.
    Pré-aloca um ndarray de tamanho fixo — sem realocação durante
    operação.

    Args:
        sample_rate: taxa de amostragem (ex.: 16000).
        channels: número de canais (ex.: 1 para mono).
        duration_seconds: duração máxima armazenada (ex.: 20.0).

    Uso:
        buf = RingBuffer(sample_rate=16000, channels=1, duration_seconds=20.0)
        buf.write(chunk_float32)           # thread PortAudio
        audio = buf.read_last(6.0)         # thread StreamingSTT
    """

    def __init__(
        self,
        sample_rate: int,
        channels: int = 1,
        duration_seconds: float = 20.0,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be > 0, got {sample_rate}")
        if channels <= 0:
            raise ValueError(f"channels must be > 0, got {channels}")
        if duration_seconds <= 0:
            raise ValueError(
                f"duration_seconds must be > 0, got {duration_seconds}"
            )

        self._sample_rate = sample_rate
        self._channels = channels
        self._duration_seconds = duration_seconds

        # Capacidade total em amostras (frames).
        self._capacity = int(sample_rate * duration_seconds)

        # Pré-alocação: array float32 contíguo.
        # Shape: (capacity, channels) se multichannel, (capacity,) se mono.
        if channels == 1:
            self._buf = np.zeros(self._capacity, dtype=np.float32)
        else:
            self._buf = np.zeros((self._capacity, channels), dtype=np.float32)

        # Índice circular: próxima posição de escrita.
        self._head = 0
        # Quantas amostras válidas existem (cresce até capacity).
        self._filled = 0

        # Lock para proteger _head e _filled (índices).
        # O array em si não precisa de lock porque:
        # - write() só escreve em _head (região não lida se filled < capacity)
        # - read_last() copia regiões estáveis (já escritas)
        # O lock garante que _head/_filled são consistentes entre
        # write e read_last.
        self._lock = threading.Lock()

        logger.info(
            "RingBuffer initialized: sr=%d ch=%d duration=%.1fs "
            "capacity=%d samples (%.1f KB)",
            sample_rate,
            channels,
            duration_seconds,
            self._capacity,
            self._capacity * 4 / 1024,  # float32 = 4 bytes
        )

    # ------------------------------------------------------------------
    # Escrita (thread PortAudio)
    # ------------------------------------------------------------------

    def write(self, audio: np.ndarray) -> None:
        """Escreve um chunk de áudio no buffer.

        Args:
            audio: ndarray float32 [-1.0, 1.0]. Shape (N,) para mono
                   ou (N, channels) para multichannel.

        Thread-safe. Chamado na thread PortAudio (callback).
        Não bloqueia — se o chunk for maior que o buffer, escreve
        apenas os últimos ``capacity`` samples.
        """
        if audio is None or audio.size == 0:
            return

        # Garantir float32 e contiguidade.
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        n = audio.shape[0]
        if n == 0:
            return

        # Se o chunk é maior que o buffer inteiro, pegar apenas o final.
        if n >= self._capacity:
            audio = audio[-self._capacity:]
            n = self._capacity

        with self._lock:
            # Caso 1: cabe sem wrap-around.
            if self._head + n <= self._capacity:
                self._buf[self._head:self._head + n] = audio
            else:
                # Caso 2: precisa wrap-around.
                first_part = self._capacity - self._head
                self._buf[self._head:self._capacity] = audio[:first_part]
                second_part = n - first_part
                self._buf[0:second_part] = audio[first_part:]

            self._head = (self._head + n) % self._capacity
            self._filled = min(self._filled + n, self._capacity)

    # ------------------------------------------------------------------
    # Leitura (thread StreamingSTT)
    # ------------------------------------------------------------------

    def read_last(self, seconds: float) -> np.ndarray:
        """Retorna os últimos ``seconds`` de áudio como ndarray contíguo.

        Args:
            seconds: duração em segundos (ex.: 6.0).

        Returns:
            ndarray float32 [-1.0, 1.0] contíguo. Se o buffer tiver
            menos amostras que o solicitado, retorna o que estiver
            disponível. Se estiver vazio, retorna array vazio.

        Thread-safe. Chamado na thread StreamingSTT.
        Faz uma cópia (necessária para retornar array contíguo
        quando há wrap-around).
        """
        n_requested = int(self._sample_rate * seconds)
        if n_requested <= 0:
            return np.zeros(0, dtype=np.float32)

        with self._lock:
            available = self._filled
            n = min(n_requested, available)
            if n == 0:
                return np.zeros(0, dtype=np.float32)

            # Calcular posição de início: _head - n (modular).
            start = (self._head - n) % self._capacity

            if start + n <= self._capacity:
                # Sem wrap-around: copiar região contígua.
                return self._buf[start:start + n].copy()
            else:
                # Com wrap-around: concatenar duas partes.
                first_part = self._capacity - start
                result = np.empty(n, dtype=np.float32)
                result[:first_part] = self._buf[start:self._capacity]
                result[first_part:] = self._buf[0:n - first_part]
                return result

    # ------------------------------------------------------------------
    # Propriedades
    # ------------------------------------------------------------------

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def capacity(self) -> int:
        """Capacidade total em amostras."""
        return self._capacity

    @property
    def filled(self) -> int:
        """Número de amostras válidas atualmente no buffer."""
        with self._lock:
            return self._filled

    @property
    def duration_seconds(self) -> float:
        return self._duration_seconds

    @property
    def available_seconds(self) -> float:
        """Duração de áudio disponível no buffer (segundos)."""
        with self._lock:
            return self._filled / self._sample_rate

    def clear(self) -> None:
        """Limpa o buffer (zera índices)."""
        with self._lock:
            self._head = 0
            self._filled = 0
