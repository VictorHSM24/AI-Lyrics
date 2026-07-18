"""Diagnóstico de microfone — valida captura, VAD e segmentação com hardware real.

Este script NÃO é um teste unitário. É uma ferramenta de diagnóstico manual
que usa hardware real (microfone) para validar o módulo microfone/capture.py.

Uso:
    python tools/diagnostics/test_microphone.py
    python tools/diagnostics/test_microphone.py --device 0
    python tools/diagnostics/test_microphone.py --device "Headset USB"
    python tools/diagnostics/test_microphone.py --list-only
    python tools/diagnostics/test_microphone.py --timeout 30

Restrições:
    - Não utiliza STT, parser, pipeline nem Holyrics.
    - Apenas consume interfaces públicas de microfone/capture.py.
    - Não modifica código de produção.

Valida exclusivamente:
    - Listagem de dispositivos de entrada.
    - Identificação do dispositivo padrão.
    - Seleção de dispositivo pelo config.yaml ou CLI.
    - Início da captura via MicrophoneCapture.
    - Detecção de fala (VAD).
    - Segmentação (SpeechSegment emitido com duração, bytes, timestamp).

Requer:
    - sounddevice instalado.
    - Microfone físico conectado.
    - pysilero-vad (preferencial) ou webrtcvad ou fallback RMS.
"""

from __future__ import annotations

import argparse
import io
import os
import signal
import sys
import time
from pathlib import Path

# Forçar UTF-8 no stdout/stderr para evitar crash em Windows cp1252
# quando nomes de dispositivos contêm caracteres acentuados.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

# Garantir que a raiz do projeto está no sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import load_config
from config.models import AudioConfig
from core.exceptions import AudioError
from microfone import CaptureMetrics, DeviceInfo, MicrophoneCapture, SpeechSegment


# ---------------------------------------------------------------------------
# Listagem de dispositivos
# ---------------------------------------------------------------------------


def list_devices() -> list[DeviceInfo]:
    """Lista dispositivos de entrada disponíveis via MicrophoneCapture."""
    return MicrophoneCapture.list_input_devices()


def print_devices(devices: list[DeviceInfo]) -> None:
    """Imprime a lista de dispositivos no formato esperado."""
    print()
    print("-" * 40)
    print("Dispositivos encontrados:")
    if not devices:
        print("  (nenhum dispositivo de entrada encontrado)")
    else:
        for d in devices:
            marker = " (padrão)" if d.is_default else ""
            print(f"{d.index} - {d.name}{marker}")
    print("-" * 40)


def find_default(devices: list[DeviceInfo]) -> DeviceInfo | None:
    """Retorna o dispositivo padrão, se houver."""
    for d in devices:
        if d.is_default:
            return d
    return None


# ---------------------------------------------------------------------------
# Seleção de dispositivo
# ---------------------------------------------------------------------------


def resolve_device(
    cli_device: str | None,
    config_audio: AudioConfig | None,
) -> str:
    """Resolve o dispositivo a usar: CLI > config.yaml > padrão.

    Args:
        cli_device: dispositivo passado via --device (ou None).
        config_audio: AudioConfig do config.yaml (ou None).

    Returns:
        Nome ou índice do dispositivo para passar a MicrophoneCapture.
    """
    if cli_device is not None:
        return cli_device
    if config_audio is not None:
        return config_audio.input_device
    # Fallback: deixar o sounddevice usar o padrão do sistema
    return "0"


def build_audio_config(
    device: str,
    config_audio: AudioConfig | None,
) -> AudioConfig:
    """Constrói AudioConfig com o dispositivo selecionado.

    Usa os parâmetros do config.yaml se disponível; caso contrário, defaults.
    """
    if config_audio is not None:
        # Substituir apenas o input_device, manter o resto
        return AudioConfig(
            input_device=device,
            sample_rate=config_audio.sample_rate,
            channels=config_audio.channels,
            chunk_ms=config_audio.chunk_ms,
            vad_enabled=config_audio.vad_enabled,
            min_speech_ms=config_audio.min_speech_ms,
            max_silence_ms=config_audio.max_silence_ms,
            vad_mode=config_audio.vad_mode,
            max_segment_ms=config_audio.max_segment_ms,
        )
    # Defaults sensatos
    return AudioConfig(
        input_device=device,
        sample_rate=16000,
        channels=1,
        chunk_ms=30,
        vad_enabled=True,
        min_speech_ms=600,
        max_silence_ms=800,
        vad_mode=3,
        max_segment_ms=30_000,
    )


# ---------------------------------------------------------------------------
# Captura
# ---------------------------------------------------------------------------


def run_capture(
    audio_config: AudioConfig,
    timeout_s: float | None,
) -> CaptureMetrics:
    """Inicia MicrophoneCapture e imprime segmentos detectados.

    Args:
        audio_config: configuração de áudio com dispositivo selecionado.
        timeout_s: tempo máximo de captura (None = até Ctrl+C).

    Returns:
        CaptureMetrics acumuladas.
    """
    capture = MicrophoneCapture(audio_config)

    print()
    print(f"Dispositivo selecionado: {audio_config.input_device}")
    print(
        f"sample_rate={audio_config.sample_rate}, "
        f"channels={audio_config.channels}, "
        f"chunk_ms={audio_config.chunk_ms}, "
        f"vad_enabled={audio_config.vad_enabled}, "
        f"min_speech_ms={audio_config.min_speech_ms}, "
        f"max_silence_ms={audio_config.max_silence_ms}"
    )
    print()
    print("Aguardando fala... (Ctrl+C para parar)")
    print()

    # Handler para Ctrl+C limpo
    def _signal_handler(signum: int, frame: object) -> None:
        print("\nParando captura...")
        capture.stop()

    signal.signal(signal.SIGINT, _signal_handler)

    start_time = time.time()
    segment_count = 0

    try:
        for segment in capture.run():
            segment_count += 1
            _print_segment(segment, segment_count)

            if timeout_s is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout_s:
                    print(f"\nTimeout de {timeout_s}s atingido. Parando...")
                    capture.stop()
                    break
    except AudioError as e:
        print(f"\nErro de áudio: {e}")
        raise
    finally:
        # Garantir que o capture parou
        capture.stop()

    metrics = capture.metrics
    _print_summary(metrics, segment_count, time.time() - start_time)
    return metrics


def _print_segment(segment: SpeechSegment, count: int) -> None:
    """Imprime um segmento detectado no formato esperado."""
    print(f"Segmento detectado:")
    print(f"  duration_ms={segment.duration_ms}")
    print(f"  bytes={len(segment.audio)}")
    print(f"  timestamp={segment.start_time:.3f}")
    print(f"  chunks={segment.chunk_count}")
    print()


def _print_summary(
    metrics: CaptureMetrics,
    segment_count: int,
    elapsed_s: float,
) -> None:
    """Imprime resumo final da captura."""
    print()
    print("-" * 40)
    print("Resumo da captura:")
    print(f"  Tempo total: {elapsed_s:.1f}s")
    print(f"  Segmentos emitidos: {segment_count}")
    print(f"  Segmentos descartados: {metrics.segments_discarded}")
    print(f"  Total de chunks: {metrics.total_chunks}")
    print(f"  Chunks de fala: {metrics.speech_chunks}")
    print(f"  Chunks de silêncio: {metrics.silence_chunks}")
    print(f"  Tempo de fala: {metrics.total_speech_ms / 1000:.1f}s")
    print(f"  Tempo de silêncio: {metrics.total_silence_ms / 1000:.1f}s")
    print(f"  Reconexões: {metrics.reconnect_count}")
    print(f"  Erros: {metrics.errors}")
    print("-" * 40)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parsea argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        description="Diagnóstico de microfone — valida captura, VAD e segmentação.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  python tools/diagnostics/test_microphone.py\n"
            "  python tools/diagnostics/test_microphone.py --device 0\n"
            '  python tools/diagnostics/test_microphone.py --device "Headset USB"\n'
            "  python tools/diagnostics/test_microphone.py --list-only\n"
            "  python tools/diagnostics/test_microphone.py --timeout 30\n"
        ),
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Dispositivo de entrada (índice ou nome parcial). "
        "Default: do config.yaml.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Apenas lista dispositivos e sai (não inicia captura).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Tempo máximo de captura em segundos (default: até Ctrl+C).",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/config.yaml",
        help="Caminho para config.yaml (default: config/config.yaml).",
    )
    return parser.parse_args()


def main() -> int:
    """Entry point do diagnóstico de microfone."""
    args = parse_args()

    # 1. Listar dispositivos
    try:
        devices = list_devices()
    except Exception as e:
        print(f"Erro ao listar dispositivos: {e}")
        print("Verifique se sounddevice está instalado: pip install sounddevice")
        return 1

    print_devices(devices)

    default_dev = find_default(devices)
    if default_dev is not None:
        print(f"Dispositivo padrão: {default_dev.index} - {default_dev.name}")
    else:
        print("Nenhum dispositivo padrão identificado.")

    if args.list_only:
        return 0

    if not devices:
        print("\nNenhum dispositivo de entrada disponível. Conecte um microfone.")
        return 1

    # 2. Carregar config.yaml para parâmetros de áudio
    config_audio: AudioConfig | None = None
    try:
        # HOLYRICS_TOKEN pode não estar setado — setar dummy para evitar erro
        if "HOLYRICS_TOKEN" not in os.environ:
            os.environ["HOLYRICS_TOKEN"] = "dummy"
        cfg = load_config(args.config)
        config_audio = cfg.audio
    except Exception as e:
        print(f"Aviso: não foi possível carregar config.yaml ({e}).")
        print("Usando defaults de áudio.")

    # 3. Resolver dispositivo
    device = resolve_device(args.device, config_audio)
    print(f"\nDispositivo selecionado: {device}")

    # Validar que o dispositivo existe
    try:
        audio_config = build_audio_config(device, config_audio)
        # find_device valida a existência do dispositivo
        capture = MicrophoneCapture(audio_config)
        capture.find_device(device)
    except AudioError as e:
        print(f"\nErro: {e}")
        print("\nDispositivos disponíveis:")
        for d in devices:
            marker = " (padrão)" if d.is_default else ""
            print(f"  {d.index} - {d.name}{marker}")
        return 1

    # 4. Iniciar captura
    try:
        run_capture(audio_config, args.timeout)
    except AudioError as e:
        print(f"\nErro durante captura: {e}")
        return 1
    except Exception as e:
        print(f"\nErro inesperado: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
