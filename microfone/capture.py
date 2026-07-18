"""Captura de áudio do microfone com VAD (Voice Activity Detection).

Escolha de bibliotecas (justificativa técnica):
  - **sounddevice** sobre pyaudio: API mais limpa, suporte nativo a numpy
    arrays, streaming callback-based, mesma engine PortAudio por baixo.
    Melhor para Windows com baixa latência (WDM/KS).
  - **pysilero-vad** sobre webrtcvad: wheels pré-compiladas cp39-abi3
    (compatível com Python 3.9–3.14+), sem necessidade de Visual C++
    Build Tools no cliente final. Modelo Silero VAD v6 em formato ggml
    (~2MB) embutido no wheel. Estado interno (contexto entre chunks)
    para maior precisão. Latência < 1ms por chunk em CPU. Sem PyTorch.
    Fallback automático para RMS-based VAD se a biblioteca não estiver
    disponível.
  - **numpy**: manipulação eficiente de buffers de áudio PCM.

Pipeline:
  1. sounddevice captura PCM 16kHz mono em chunks de chunk_ms.
  2. pysilero-vad classifica chunks de 512 samples (32ms) como fala/silêncio.
     Chunks de captura (30ms) são bufferizados para alimentar o VAD no
     tamanho correto — transparente para o consumidor.
  3. Se fala: acumula no buffer.
  4. Se silêncio após fala e pausa >= max_silence_ms: finaliza segmento.
  5. Segmento com duração >= min_speech_ms é emitido como SpeechSegment.
  6. Buffer > max_segment_ms: flush forçado (evita OOM e Whisper timeout).

Tolerância a desconexão/reconexão:
  - Se o stream interrompe (PortAudioError), loga warning e tenta reabrir
    o dispositivo com backoff exponencial (100ms, 200ms, 400ms, ...).
  - Se o dispositivo some permanentemente, AudioError após max_retries.

Dispositivo "CODEC USB":
  - Nome genérico que o Windows atribui a dispositivos USB Audio Class
    (incluindo interfaces Behringer com driver genérico).
  - A resolução por nome faz match parcial case-insensitive.
  - Sem limitações conhecidas — PortAudio acessa via WDM/KS normalmente.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from config.models import AudioConfig
from core.exceptions import AudioError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_PCM_DTYPE = "int16"
_BYTES_PER_SAMPLE = 2  # 16-bit
_MAX_RECONNECT_RETRIES = 10
_RECONNECT_BASE_MS = 100

# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceInfo:
    """Informação de um dispositivo de áudio de entrada."""

    index: int
    name: str
    channels: int
    sample_rate: float
    is_default: bool


@dataclass(frozen=True)
class SpeechSegment:
    """Segmento completo de fala detectado pelo VAD.

    Atributos:
        audio: PCM 16kHz mono 16-bit little-endian (bytes).
        start_time: timestamp (time.time()) do início da fala.
        end_time: timestamp (time.time()) do fim da fala.
        duration_ms: duração total em milissegundos.
        chunk_count: número de chunks acumulados.
    """

    audio: bytes
    start_time: float
    end_time: float
    duration_ms: int
    chunk_count: int


@dataclass
class CaptureMetrics:
    """Métricas de captura para monitoramento.

    Acumuladas desde o início da captura ou desde o último reset.
    """

    total_chunks: int = 0
    speech_chunks: int = 0
    silence_chunks: int = 0
    segments_emitted: int = 0
    segments_discarded: int = 0  # abaixo de min_speech_ms
    total_speech_ms: int = 0
    total_silence_ms: int = 0
    reconnect_count: int = 0
    errors: int = 0


# ---------------------------------------------------------------------------
# VAD Segmenter (lógica pura, testável sem hardware)
# ---------------------------------------------------------------------------


class VadSegmenter:
    """Segmentador de fala baseado em VAD.

    Lógica pura (sem I/O de hardware), testável independentemente.
    Processa chunks PCM e produz SpeechSegments quando a fala termina.

    Args:
        sample_rate: taxa de amostragem (ex.: 16000).
        chunk_ms: duração do chunk em ms (10/20/30 para webrtcvad).
        min_speech_ms: duração mínima de fala para emitir segmento.
        max_silence_ms: silêncio máximo dentro da fala antes de finalizar.
        vad_mode: aggressividade do webrtcvad (0=menos, 3=mais).
        max_segment_ms: duração máxima antes de flush forçado.
        vad: instância do VAD (criada internamente se omitida).
            Deve ter método ``is_speech(pcm: bytes, sample_rate: int) -> bool``.
            Opcionalmente pode ter ``chunk_bytes() -> int`` para indicar
            o tamanho requerido de chunk (ex.: Silero VAD precisa de 1024 bytes).
    """

    def __init__(
        self,
        sample_rate: int,
        chunk_ms: int,
        min_speech_ms: int,
        max_silence_ms: int,
        vad_mode: int = 3,
        max_segment_ms: int = 30_000,
        vad: Any | None = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._chunk_ms = chunk_ms
        self._min_speech_ms = min_speech_ms
        self._max_silence_ms = max_silence_ms
        self._max_segment_ms = max_segment_ms
        self._vad = vad if vad is not None else _create_vad(vad_mode)

        # Validações
        if chunk_ms not in (10, 20, 30, 32):
            raise AudioError(
                f"chunk_ms must be 10, 20, 30, or 32, got {chunk_ms}"
            )
        if not (0 <= vad_mode <= 3):
            raise AudioError(f"vad_mode must be 0..3, got {vad_mode}")

        # Estado interno
        self._buffer: bytearray = bytearray()
        self._in_speech: bool = False
        self._speech_start: float = 0.0
        self._silence_ms: int = 0
        self._speech_ms: int = 0
        self._chunk_count: int = 0

        # Buffer para VAD que requer chunk de tamanho fixo (ex.: Silero 512 samples)
        self._vad_chunk_bytes: int | None = None
        self._vad_buffer: bytearray = bytearray()
        self._last_vad_speech: bool = False
        if hasattr(self._vad, "chunk_bytes"):
            try:
                self._vad_chunk_bytes = int(self._vad.chunk_bytes())
            except Exception:
                pass

    def process_chunk(self, pcm: bytes, timestamp: float) -> SpeechSegment | None:
        """Processa um chunk PCM e retorna um SpeechSegment se a fala terminou.

        Args:
            pcm: bytes PCM 16kHz mono 16-bit LE.
            timestamp: timestamp do chunk (time.time()).

        Returns:
            SpeechSegment se a fala terminou e >= min_speech_ms,
            ou None se ainda acumulando / em silêncio.
        """
        self._chunk_count += 1

        # Verificar se o chunk tem o tamanho esperado
        expected_bytes = self._samples_per_chunk() * _BYTES_PER_SAMPLE
        if len(pcm) == 0:
            # Chunk vazio (microfone muto) — tratar como silêncio
            is_speech = False
        elif self._vad_chunk_bytes is not None:
            # VAD requer chunk de tamanho fixo (ex.: Silero 512 samples)
            # Bufferizar chunks de captura até atingir o tamanho requerido
            is_speech = self._detect_speech_buffered(pcm)
        else:
            # VAD que aceita qualquer tamanho (ex.: webrtcvad)
            is_speech = self._detect_speech(pcm)

        if is_speech:
            if not self._in_speech:
                # Início de fala
                self._in_speech = True
                self._speech_start = timestamp
                self._speech_ms = 0
                self._silence_ms = 0
                logger.debug("VAD: speech started at %.3f", timestamp)

            self._buffer.extend(pcm)
            self._speech_ms += self._chunk_ms
            self._silence_ms = 0

            # Flush forçado se buffer muito longo
            if self._speech_ms >= self._max_segment_ms:
                logger.info(
                    "VAD: forced flush (segment >= %d ms)",
                    self._max_segment_ms,
                )
                return self._flush(timestamp)
        else:
            # Silêncio
            if self._in_speech:
                self._buffer.extend(pcm)  # incluir o chunk de silêncio
                self._silence_ms += self._chunk_ms

                if self._silence_ms >= self._max_silence_ms:
                    # Fala terminou
                    logger.debug(
                        "VAD: speech ended (silence=%d ms, speech=%d ms)",
                        self._silence_ms,
                        self._speech_ms,
                    )
                    return self._flush(timestamp)

        return None

    def force_flush(self, timestamp: float | None = None) -> SpeechSegment | None:
        """Força a finalização do segmento atual (se houver fala em andamento).

        Usado ao parar a captura para não perder o último segmento.
        """
        if self._in_speech and len(self._buffer) > 0:
            return self._flush(timestamp or time.time())
        return None

    def reset(self) -> None:
        """Reseta o estado do segmentador."""
        self._buffer = bytearray()
        self._in_speech = False
        self._speech_start = 0.0
        self._silence_ms = 0
        self._speech_ms = 0
        self._chunk_count = 0

    @property
    def in_speech(self) -> bool:
        """True se está atualmente acumulando fala."""
        return self._in_speech

    @property
    def buffer_ms(self) -> int:
        """Duração atual do buffer em milissegundos."""
        return self._speech_ms

    def _flush(self, end_timestamp: float) -> SpeechSegment | None:
        """Finaliza o segmento atual e retorna se >= min_speech_ms."""
        if not self._in_speech or len(self._buffer) == 0:
            self._reset_state()
            return None

        duration_ms = self._speech_ms
        chunk_count = self._chunk_count

        # Verificar duração mínima
        if duration_ms < self._min_speech_ms:
            logger.debug(
                "VAD: segment discarded (duration=%d ms < min=%d ms)",
                duration_ms,
                self._min_speech_ms,
            )
            self._reset_state()
            return None

        segment = SpeechSegment(
            audio=bytes(self._buffer),
            start_time=self._speech_start,
            end_time=end_timestamp,
            duration_ms=duration_ms,
            chunk_count=chunk_count,
        )

        self._reset_state()
        return segment

    def _reset_state(self) -> None:
        """Reseta o estado de fala (mas mantém chunk_count acumulado)."""
        self._buffer = bytearray()
        self._in_speech = False
        self._speech_start = 0.0
        self._silence_ms = 0
        self._speech_ms = 0

    def _detect_speech(self, pcm: bytes) -> bool:
        """Executa VAD no chunk PCM. Retorna True se for fala.

        Suporta duas interfaces de VAD:
        - webrtcvad: ``is_speech(pcm, sample_rate) -> bool``
        - pysilero-vad: ``__call__(pcm) -> float`` (probabilidade >= 0.5)
        """
        if len(pcm) == 0:
            return False
        try:
            if hasattr(self._vad, "is_speech"):
                return bool(self._vad.is_speech(pcm, self._sample_rate))
            # pysilero-vad: callable que retorna probabilidade [0, 1]
            if callable(self._vad):
                prob = float(self._vad(pcm))
                return prob >= 0.5
            return False
        except Exception as e:
            # VAD falhou no chunk — tratar como silêncio e logar
            logger.warning("VAD error on chunk: %s — treating as silence", e)
            return False

    def _detect_speech_buffered(self, pcm: bytes) -> bool:
        """Bufferiza chunks de captura até atingir o tamanho requerido pelo VAD.

        Silero VAD requer chunks de 512 samples (1024 bytes) — mas o
        chunk de captura é 30ms = 480 samples (960 bytes). Bufferizamos
        até ter 1024 bytes, processamos, e mantemos o resto.

        Retorna True se o último chunk VAD processado foi fala.
        """
        self._vad_buffer.extend(pcm)

        is_speech = self._last_vad_speech  # default: manter último estado

        while len(self._vad_buffer) >= self._vad_chunk_bytes:
            chunk = bytes(self._vad_buffer[:self._vad_chunk_bytes])
            del self._vad_buffer[:self._vad_chunk_bytes]
            try:
                if hasattr(self._vad, "is_speech"):
                    is_speech = bool(self._vad.is_speech(chunk, self._sample_rate))
                elif callable(self._vad):
                    prob = float(self._vad(chunk))
                    is_speech = prob >= 0.5
                else:
                    is_speech = False
                self._last_vad_speech = is_speech
            except Exception as e:
                logger.warning("VAD error on buffered chunk: %s — treating as silence", e)
                is_speech = False
                self._last_vad_speech = False

        return is_speech

    def _samples_per_chunk(self) -> int:
        """Número de samples por chunk."""
        return int(self._sample_rate * self._chunk_ms / 1000)


def _create_vad(mode: int) -> Any:
    """Cria uma instância do VAD preferencial.

    Ordem de preferência:
    1. **pysilero-vad**: wheels pré-compiladas cp39-abi3 (Python 3.9–3.14+),
       sem Visual C++ Build Tools. Modelo Silero VAD v6 (~2MB) embutido.
       Alta precisão, estado interno entre chunks, latência < 1ms.
    2. **webrtcvad-wheels**: wheels pré-compiladas para Windows (cp313).
       Não suporta Python 3.14 ainda. Frame-based 10/20/30ms.
    3. **Fallback RMS**: se nenhuma biblioteca VAD estiver disponível,
       usa amplitude threshold (RMS). Menos preciso mas zero dependências.

    Args:
        mode: aggressividade (0=menos, 3=mais). Ignorado por Silero VAD.

    Returns:
        Instância de VAD com interface ``is_speech(pcm, sr)`` ou callable.
    """
    # 1. pysilero-vad (preferencial — wheels cp39-abi3, sem compilação)
    try:
        from pysilero_vad import SileroVoiceActivityDetector

        vad = SileroVoiceActivityDetector()
        logger.info(
            "VAD: pysilero-vad loaded (chunk_bytes=%d)", vad.chunk_bytes()
        )
        return vad
    except ImportError:
        pass
    except Exception as e:
        logger.warning("pysilero-vad failed to load: %s — trying fallback", e)

    # 2. webrtcvad-wheels (fallback — não suporta Python 3.14 ainda)
    try:
        import webrtcvad

        vad = webrtcvad.Vad(mode)
        logger.info("VAD: webrtcvad loaded (mode=%d)", mode)
        return vad
    except ImportError:
        pass
    except Exception as e:
        logger.warning("webrtcvad failed to load: %s — trying fallback", e)

    # 3. RMS fallback (zero dependências)
    logger.warning(
        "VAD: no VAD library available (pysilero-vad, webrtcvad) — "
        "using RMS amplitude fallback (less accurate)"
    )
    return _RmsVadFallback()


class _RmsVadFallback:
    """VAD fallback baseado em amplitude RMS.

    Usado apenas quando nem pysilero-vad nem webrtcvad estão disponíveis.
    Menos preciso que VAD baseado em ML, mas zero dependências.
    """

    def __init__(self, threshold: float = 100.0) -> None:
        self._threshold = threshold

    def is_speech(self, pcm: bytes, sample_rate: int) -> bool:
        import numpy as np

        if len(pcm) == 0:
            return False
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
        rms = np.sqrt(np.mean(samples ** 2)) if len(samples) > 0 else 0.0
        return bool(rms > self._threshold)


# ---------------------------------------------------------------------------
# MicrophoneCapture (I/O de hardware)
# ---------------------------------------------------------------------------


class MicrophoneCapture:
    """Captura áudio do microfone com VAD e produz SpeechSegments.

    Args:
        config: AudioConfig com configurações de captura.
        segmenter: VadSegmenter (criado internamente se omitido).
    """

    def __init__(
        self,
        config: AudioConfig,
        segmenter: VadSegmenter | None = None,
    ) -> None:
        self._config = config
        self._metrics = CaptureMetrics()
        self._stopped = False

        if not config.vad_enabled:
            # VAD desativado — criar segmenter que sempre detecta fala
            self._segmenter = segmenter or _NoOpSegmenter(
                sample_rate=config.sample_rate,
                chunk_ms=config.chunk_ms,
                min_speech_ms=config.min_speech_ms,
                max_silence_ms=config.max_silence_ms,
                max_segment_ms=config.max_segment_ms,
            )
        else:
            self._segmenter = segmenter or VadSegmenter(
                sample_rate=config.sample_rate,
                chunk_ms=config.chunk_ms,
                min_speech_ms=config.min_speech_ms,
                max_silence_ms=config.max_silence_ms,
                vad_mode=config.vad_mode,
                max_segment_ms=config.max_segment_ms,
            )

    # ------------------------------------------------------------------
    # Listagem e seleção de dispositivos
    # ------------------------------------------------------------------

    @staticmethod
    def list_input_devices() -> list[DeviceInfo]:
        """Lista dispositivos de entrada de áudio disponíveis.

        Returns:
            Lista de DeviceInfo dos dispositivos de entrada.
        """
        import sounddevice as sd

        devices = sd.query_devices()
        # DeviceList é iterável mas não é list; normalizar para list
        if not isinstance(devices, list):
            devices = list(devices)
        default_input = sd.default.device[0] if sd.default.device else None

        result: list[DeviceInfo] = []
        for i, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                result.append(
                    DeviceInfo(
                        index=i,
                        name=dev.get("name", f"Device {i}"),
                        channels=dev.get("max_input_channels", 0),
                        sample_rate=dev.get("default_samplerate", 0.0),
                        is_default=(i == default_input),
                    )
                )
        return result

    def find_device(self, name_or_index: str | int) -> int:
        """Localiza o dispositivo de entrada pelo nome ou índice.

        Args:
            name_or_index: nome do dispositivo (match parcial
                case-insensitive) ou índice inteiro.

        Returns:
            Índice do dispositivo no PortAudio.

        Raises:
            AudioError: dispositivo não encontrado.
        """
        devices = self.list_input_devices()

        # Tentar por índice
        if isinstance(name_or_index, int):
            for d in devices:
                if d.index == name_or_index:
                    return d.index
            raise AudioError(
                f"input device index {name_or_index} not found. "
                f"Available: {self._format_devices(devices)}"
            )

        # Tentar por índice como string
        if name_or_index.strip().isdigit():
            idx = int(name_or_index.strip())
            for d in devices:
                if d.index == idx:
                    return d.index
            raise AudioError(
                f"input device index {idx} not found. "
                f"Available: {self._format_devices(devices)}"
            )

        # Match parcial case-insensitive por nome
        target = name_or_index.lower().strip()
        for d in devices:
            if target in d.name.lower():
                logger.info(
                    "Found input device: '%s' (index=%d, ch=%d, sr=%.0f)",
                    d.name,
                    d.index,
                    d.channels,
                    d.sample_rate,
                )
                return d.index

        raise AudioError(
            f"input device '{name_or_index}' not found. "
            f"Available: {self._format_devices(devices)}"
        )

    @staticmethod
    def _format_devices(devices: list[DeviceInfo]) -> str:
        """Formata lista de dispositivos para mensagem de erro."""
        return "; ".join(f"[{d.index}] {d.name}" for d in devices)

    # ------------------------------------------------------------------
    # Captura
    # ------------------------------------------------------------------

    def run(self) -> Iterator[SpeechSegment]:
        """Loop de captura contínua. Generator que produz SpeechSegments.

        Bloqueia até que stop() seja chamado ou o dispositivo falhe
        permanentemente. Tolerante a desconexão/reconexão.

        Yields:
            SpeechSegment para cada segmento de fala detectado.
        """
        import sounddevice as sd
        import numpy as np

        config = self._config
        device_idx = self.find_device(config.input_device)
        samples_per_chunk = int(config.sample_rate * config.chunk_ms / 1000)

        logger.info(
            "Starting capture: device=%d, sr=%d, ch=%d, chunk_ms=%d, vad=%s",
            device_idx,
            config.sample_rate,
            config.channels,
            config.chunk_ms,
            config.vad_enabled,
        )

        stream: sd.InputStream | None = None
        retry_delay_ms = _RECONNECT_BASE_MS

        while not self._stopped:
            try:
                if stream is None:
                    stream = sd.InputStream(
                        device=device_idx,
                        samplerate=config.sample_rate,
                        channels=config.channels,
                        dtype=_PCM_DTYPE,
                        blocksize=samples_per_chunk,
                        latency="low",
                    )
                    stream.start()
                    retry_delay_ms = _RECONNECT_BASE_MS
                    logger.info("Capture stream started on device %d", device_idx)

                # Ler um chunk
                chunk = stream.read(samples_per_chunk)[0]
                pcm = np.ascontiguousarray(chunk).tobytes()
                timestamp = time.time()

                self._metrics.total_chunks += 1

                # Processar VAD
                segment = self._segmenter.process_chunk(pcm, timestamp)
                if segment is not None:
                    self._metrics.segments_emitted += 1
                    self._metrics.total_speech_ms += segment.duration_ms
                    logger.info(
                        "Speech segment: duration=%d ms, chunks=%d",
                        segment.duration_ms,
                        segment.chunk_count,
                    )
                    yield segment
                else:
                    if self._segmenter.in_speech:
                        self._metrics.speech_chunks += 1
                    else:
                        self._metrics.silence_chunks += 1
                        self._metrics.total_silence_ms += config.chunk_ms

            except Exception as e:
                self._metrics.errors += 1
                logger.warning("Capture error: %s", e)

                # Fechar stream se aberto
                if stream is not None:
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass
                    stream = None

                if self._stopped:
                    break

                # Tentar reconectar
                self._metrics.reconnect_count += 1
                if self._metrics.reconnect_count > _MAX_RECONNECT_RETRIES:
                    raise AudioError(
                        f"max reconnect retries ({_MAX_RECONNECT_RETRIES}) "
                        f"exceeded for device '{config.input_device}'"
                    ) from e

                logger.warning(
                    "Reconnecting in %d ms (attempt %d/%d)...",
                    retry_delay_ms,
                    self._metrics.reconnect_count,
                    _MAX_RECONNECT_RETRIES,
                )
                time.sleep(retry_delay_ms / 1000.0)
                retry_delay_ms = min(retry_delay_ms * 2, 5000)

                # Re-encontrar dispositivo (pode ter mudado de índice)
                try:
                    device_idx = self.find_device(config.input_device)
                except AudioError:
                    logger.warning("Device not found during reconnect, retrying...")

        # Cleanup
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        # Flush final
        final = self._segmenter.force_flush()
        if final is not None:
            self._metrics.segments_emitted += 1
            yield final

        logger.info(
            "Capture stopped: chunks=%d, segments=%d, reconnects=%d",
            self._metrics.total_chunks,
            self._metrics.segments_emitted,
            self._metrics.reconnect_count,
        )

    def stop(self) -> None:
        """Sinaliza para o loop de captura parar."""
        self._stopped = True
        logger.info("Capture stop requested")

    # ------------------------------------------------------------------
    # Métricas
    # ------------------------------------------------------------------

    @property
    def metrics(self) -> CaptureMetrics:
        """Métricas acumuladas de captura."""
        return self._metrics


# ---------------------------------------------------------------------------
# No-op segmenter (VAD desativado)
# ---------------------------------------------------------------------------


class _NoOpSegmenter:
    """Segmenter que trata todos os chunks como fala (VAD desativado).

    Usa amplitude threshold simples para detectar silêncio (RMS < threshold).
    """

    def __init__(
        self,
        sample_rate: int,
        chunk_ms: int,
        min_speech_ms: int,
        max_silence_ms: int,
        max_segment_ms: int = 30_000,
        rms_threshold: float = 100.0,
    ) -> None:
        self._sample_rate = sample_rate
        self._chunk_ms = chunk_ms
        self._min_speech_ms = min_speech_ms
        self._max_silence_ms = max_silence_ms
        self._max_segment_ms = max_segment_ms
        self._rms_threshold = rms_threshold
        self._buffer: bytearray = bytearray()
        self._in_speech = False
        self._speech_start = 0.0
        self._silence_ms = 0
        self._speech_ms = 0
        self._chunk_count = 0

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    @property
    def buffer_ms(self) -> int:
        return self._speech_ms

    def process_chunk(self, pcm: bytes, timestamp: float) -> SpeechSegment | None:
        import numpy as np

        self._chunk_count += 1

        if len(pcm) == 0:
            is_speech = False
        else:
            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
            rms = np.sqrt(np.mean(samples ** 2)) if len(samples) > 0 else 0.0
            is_speech = rms > self._rms_threshold

        if is_speech:
            if not self._in_speech:
                self._in_speech = True
                self._speech_start = timestamp
                self._speech_ms = 0
                self._silence_ms = 0
            self._buffer.extend(pcm)
            self._speech_ms += self._chunk_ms
            self._silence_ms = 0
            if self._speech_ms >= self._max_segment_ms:
                return self._flush(timestamp)
        else:
            if self._in_speech:
                self._buffer.extend(pcm)
                self._silence_ms += self._chunk_ms
                if self._silence_ms >= self._max_silence_ms:
                    return self._flush(timestamp)

        return None

    def force_flush(self, timestamp: float | None = None) -> SpeechSegment | None:
        if self._in_speech and len(self._buffer) > 0:
            return self._flush(timestamp or time.time())
        return None

    def reset(self) -> None:
        self._buffer = bytearray()
        self._in_speech = False
        self._speech_start = 0.0
        self._silence_ms = 0
        self._speech_ms = 0
        self._chunk_count = 0

    def _flush(self, end_timestamp: float) -> SpeechSegment | None:
        if not self._in_speech or len(self._buffer) == 0:
            self._reset_state()
            return None
        duration_ms = self._speech_ms
        chunk_count = self._chunk_count
        if duration_ms < self._min_speech_ms:
            self._reset_state()
            return None
        segment = SpeechSegment(
            audio=bytes(self._buffer),
            start_time=self._speech_start,
            end_time=end_timestamp,
            duration_ms=duration_ms,
            chunk_count=chunk_count,
        )
        self._reset_state()
        return segment

    def _reset_state(self) -> None:
        self._buffer = bytearray()
        self._in_speech = False
        self._speech_start = 0.0
        self._silence_ms = 0
        self._speech_ms = 0
