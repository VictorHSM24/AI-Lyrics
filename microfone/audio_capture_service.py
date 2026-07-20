"""AudioCaptureService — captura de áudio em tempo real (Sprint 15.1).

Serviço responsável exclusivamente por captura de áudio.
Nenhuma lógica de STT, parser, busca ou UI.

Responsabilidades:
  - abrir dispositivo
  - fechar dispositivo
  - trocar dispositivo
  - iniciar stream
  - parar stream
  - callback de áudio (sounddevice)
  - cálculo RMS
  - cálculo Peak
  - timestamp
  - sample rate
  - número de canais

Thread Safety:
  - Buffer circular thread-safe (lock-free via collections.deque).
  - Callback do sounddevice roda em thread própria (PortAudio).
  - Estado protegido por threading.Lock.
  - Nenhum recurso permanece aberto após stop().

Performance:
  - Latência da captura: < 10 ms (callback direto do PortAudio).
  - Cálculo RMS/Peak com numpy (vetorizado).
  - Buffer circular descarta frames antigos sob pressão.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AudioFrame — frame de áudio com níveis calculados.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AudioFrame:
    """Frame de áudio com níveis RMS e Peak calculados.

    Atributos:
        timestamp: time.time() do frame.
        sample_rate: taxa de amostragem (Hz).
        channels: número de canais.
        frame_count: número de samples no frame.
        rms: nível RMS normalizado (0.0–1.0).
        peak: nível de pico normalizado (0.0–1.0).
    """

    timestamp: float
    sample_rate: int
    channels: int
    frame_count: int
    rms: float
    peak: float

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "frame_count": self.frame_count,
            "rms": self.rms,
            "peak": self.peak,
        }


# ---------------------------------------------------------------------------
# AudioCaptureService
# ---------------------------------------------------------------------------


class AudioCaptureService:
    """Serviço de captura de áudio em tempo real.

    Usa sounddevice (PortAudio) com callback para captura contínua.
    Mantém um buffer circular thread-safe de AudioFrames.
    Nenhuma lógica de STT ou UI.

    Thread Safety:
        - O callback do sounddevice roda em uma thread própria do PortAudio.
        - O buffer circular usa deque (thread-safe para append/popleft).
        - O estado (capturing, device_index) é protegido por Lock.
        - Nenhum recurso permanece aberto após stop().
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        blocksize: int = 480,  # 30ms a 16kHz
        buffer_size: int = 100,
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._blocksize = blocksize
        self._buffer_size = buffer_size

        # Estado protegido por lock.
        self._lock = threading.Lock()
        self._capturing: bool = False
        self._device_index: int | None = None
        self._stream: Any | None = None  # sd.InputStream

        # Buffer circular thread-safe.
        self._frames: deque[AudioFrame] = deque(maxlen=buffer_size)

        # Callback de notificação (para WebSocket publisher).
        self._on_frame: Callable[[AudioFrame], None] | None = None

        # Callback de áudio raw (para VAD / SpeechPipeline).
        # Recebe (audio_data: np.ndarray float32, timestamp: float).
        self._on_audio_data: Callable[[Any, float], None] | None = None

        logger.info(
            "AudioCaptureService initialized: sr=%d ch=%d blocksize=%d buffer=%d",
            sample_rate, channels, blocksize, buffer_size,
        )

    # ------------------------------------------------------------------
    # Propriedades
    # ------------------------------------------------------------------

    @property
    def capturing(self) -> bool:
        with self._lock:
            return self._capturing

    @property
    def device_index(self) -> int | None:
        with self._lock:
            return self._device_index

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._stream is not None

    # ------------------------------------------------------------------
    # Callback de notificação — chamado a cada frame.
    # ------------------------------------------------------------------

    def set_on_frame(self, callback: Callable[[AudioFrame], None] | None) -> None:
        """Define callback chamado a cada frame capturado.

        Usado pelo AudioEventPublisher para enviar níveis via WebSocket.
        O callback é chamado na thread do PortAudio — deve ser rápido.
        """
        self._on_frame = callback

    def set_on_audio_data(self, callback: Callable[[Any, float], None] | None) -> None:
        """Define callback chamado a cada bloco de áudio capturado.

        Recebe (audio_data: np.ndarray float32, timestamp: float).
        Usado pelo SpeechPipelineService para alimentar o VAD.
        O callback é chamado na thread do PortAudio — deve ser rápido
        (apenas colocar dados em uma fila, sem processamento).
        """
        self._on_audio_data = callback

    # ------------------------------------------------------------------
    # Listar dispositivos — delega para sounddevice.
    # ------------------------------------------------------------------

    def list_devices(self) -> list[dict]:
        """Lista dispositivos de entrada disponíveis."""
        try:
            import sounddevice as sd
        except ImportError:
            return []

        try:
            devices = sd.query_devices()
            if not isinstance(devices, list):
                devices = list(devices)
        except Exception as e:
            logger.warning("Failed to query devices: %s", e)
            return []

        default_input = sd.default.device[0] if sd.default.device else None
        result: list[dict] = []
        for i, dev in enumerate(devices):
            max_in = dev.get("max_input_channels", 0)
            if max_in <= 0:
                continue
            result.append({
                "index": i,
                "name": dev.get("name", f"Device {i}"),
                "channels": int(max_in),
                "sample_rate": float(dev.get("default_samplerate", 0.0)),
                "is_default": (i == default_input),
                "available": True,
            })
        return result

    def get_current_device(self) -> dict | None:
        """Retorna o dispositivo atualmente selecionado."""
        devices = self.list_devices()
        if not devices:
            return None

        with self._lock:
            idx = self._device_index

        if idx is not None:
            for d in devices:
                if d["index"] == idx:
                    return d

        # Fallback: dispositivo padrão.
        for d in devices:
            if d["is_default"]:
                return d
        return devices[0]

    # ------------------------------------------------------------------
    # Selecionar dispositivo.
    # ------------------------------------------------------------------

    def select_device(self, device_index: int) -> dict:
        """Seleciona um dispositivo de entrada.

        Se a captura estiver ativa, interrompe, troca o dispositivo e
        reinicia automaticamente.

        Args:
            device_index: índice PortAudio do dispositivo.

        Returns:
            Dict com status da operação.

        Raises:
            ValueError: se o índice for inválido.
        """
        was_capturing = self.capturing

        if was_capturing:
            logger.info("Device switch — stopping capture first.")
            self.stop()

        with self._lock:
            self._device_index = device_index
        logger.info("Device selected: index=%d", device_index)

        if was_capturing:
            logger.info("Device switch — restarting capture.")
            self.start()

        return {
            "device_index": device_index,
            "restarted": was_capturing,
        }

    # ------------------------------------------------------------------
    # Iniciar captura.
    # ------------------------------------------------------------------

    def start(self) -> dict:
        """Inicia a captura de áudio.

        Abre um InputStream com callback e começa a capturar.
        Se já estiver capturando, não faz nada.

        Returns:
            Dict com status da captura.

        Raises:
            RuntimeError: se sounddevice não estiver disponível.
        """
        with self._lock:
            if self._capturing:
                return {"capturing": True, "already": True}
            if self._stream is not None:
                self._safe_close_stream()

        try:
            import sounddevice as sd
        except ImportError:
            raise RuntimeError("sounddevice not installed")

        device = self._device_index
        try:
            stream = sd.InputStream(
                device=device,
                samplerate=self._sample_rate,
                channels=self._channels,
                blocksize=self._blocksize,
                dtype="float32",
                callback=self._audio_callback,
            )
            stream.start()
        except Exception as e:
            logger.error("Failed to open audio stream: %s", e)
            raise RuntimeError(f"Failed to open audio stream: {e}")

        with self._lock:
            self._stream = stream
            self._capturing = True

        logger.info(
            "Capture started: device=%s sr=%d ch=%d blocksize=%d",
            device, self._sample_rate, self._channels, self._blocksize,
        )
        return {
            "capturing": True,
            "already": False,
            "device_index": device,
            "sample_rate": self._sample_rate,
            "channels": self._channels,
        }

    # ------------------------------------------------------------------
    # Parar captura.
    # ------------------------------------------------------------------

    def stop(self) -> dict:
        """Para a captura de áudio e fecha o stream.

        Nenhum recurso permanece aberto após esta chamada.

        Returns:
            Dict com status.
        """
        with self._lock:
            if not self._capturing and self._stream is None:
                return {"capturing": False, "already": False}
            self._capturing = False
            self._safe_close_stream_locked()

        logger.info("Capture stopped.")
        return {"capturing": False, "already": False}

    # ------------------------------------------------------------------
    # Obter frames do buffer.
    # ------------------------------------------------------------------

    def get_latest_frame(self) -> AudioFrame | None:
        """Retorna o frame mais recente, ou None se o buffer estiver vazio."""
        try:
            return self._frames[-1]
        except IndexError:
            return None

    def get_frames(self, count: int = 1) -> list[AudioFrame]:
        """Retorna os últimos N frames do buffer."""
        if count <= 0:
            return []
        frames = list(self._frames)
        return frames[-count:]

    def drain_frames(self) -> list[AudioFrame]:
        """Drena e retorna todos os frames do buffer."""
        frames = list(self._frames)
        self._frames.clear()
        return frames

    def clear_buffer(self) -> None:
        """Limpa o buffer de frames."""
        self._frames.clear()

    # ------------------------------------------------------------------
    # Callback do sounddevice — chamado pela thread do PortAudio.
    # ------------------------------------------------------------------

    def _audio_callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        """Callback do sounddevice — processa cada bloco de áudio.

        Calcula RMS e Peak do bloco e armazena no buffer circular.
        Chama o callback de notificação se definido.

        Executado na thread do PortAudio — deve ser rápido.
        """
        if status:
            logger.debug("Audio callback status: %s", status)

        try:
            import numpy as np

            # indata é um array numpy float32 shape (frames, channels).
            # Para mono, achatar; para stereo, usar canal 0 ou média.
            if self._channels > 1:
                audio_data = indata[:, 0]
            else:
                audio_data = indata.flatten()

            if len(audio_data) == 0:
                return

            # RMS: sqrt(mean(x^2))
            rms = float(np.sqrt(np.mean(audio_data ** 2)))
            # Peak: max(abs(x))
            peak = float(np.max(np.abs(audio_data)))

            frame = AudioFrame(
                timestamp=time.time(),
                sample_rate=self._sample_rate,
                channels=self._channels,
                frame_count=frames,
                rms=rms,
                peak=peak,
            )

            # Adicionar ao buffer circular (thread-safe via deque).
            self._frames.append(frame)

            # Notificar callback de áudio raw (VAD / SpeechPipeline).
            # Chamado ANTES do on_frame para minimizar latência do VAD.
            raw_cb = self._on_audio_data
            if raw_cb is not None:
                try:
                    raw_cb(audio_data, frame.timestamp)
                except Exception as e:
                    logger.debug("on_audio_data callback error: %s", e)

            # Notificar callback (WebSocket publisher).
            cb = self._on_frame
            if cb is not None:
                try:
                    cb(frame)
                except Exception as e:
                    logger.debug("on_frame callback error: %s", e)

        except Exception as e:
            logger.error("Audio callback error: %s", e)

    # ------------------------------------------------------------------
    # Internos — fechamento seguro de stream.
    # ------------------------------------------------------------------

    def _safe_close_stream(self) -> None:
        """Fecha o stream sem segurar o lock (assumindo já seguro)."""
        self._safe_close_stream_locked()

    def _safe_close_stream_locked(self) -> None:
        """Fecha o stream — chamado com lock já segurado."""
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception as e:
                logger.debug("Stream stop error: %s", e)
            try:
                stream.close()
            except Exception as e:
                logger.debug("Stream close error: %s", e)
            logger.info("Stream closed.")

    # ------------------------------------------------------------------
    # Cleanup — chamado no shutdown do processo.
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Para a captura e libera todos os recursos."""
        self.stop()
        self.clear_buffer()
        self._on_frame = None
        logger.info("AudioCaptureService shutdown complete.")
