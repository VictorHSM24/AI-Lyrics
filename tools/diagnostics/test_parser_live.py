"""Diagnóstico de parser live — valida Captura + STT + Parser com hardware real.

Fluxo validado:
    Microfone → MicrophoneCapture → SpeechSegment → STT → Parser → Console

Este script NÃO é um teste unitário. É uma ferramenta de diagnóstico manual
que usa hardware real (microfone + CPU/GPU) para validar a robustez do
parser determinístico diante de transcrições reais do Whisper.

Uso:
    python tools/diagnostics/test_parser_live.py
    python tools/diagnostics/test_parser_live.py --device 0
    python tools/diagnostics/test_parser_live.py --device "Headset USB"
    python tools/diagnostics/test_parser_live.py --list-only
    python tools/diagnostics/test_parser_live.py --timeout 60
    python tools/diagnostics/test_parser_live.py --model small --stt-device cpu --compute-type int8
    python tools/diagnostics/test_parser_live.py --model large-v3-turbo --stt-device cuda

Frases sugeridas para teste (casos obrigatórios):
    Referências diretas:
      - "João 3:16"
      - "Romanos 8:28"
      - "Filipenses 4:8"
      - "Carta aos Filipenses capítulo 4 versículo 8"
      - "Primeira carta aos Coríntios capítulo 13"
    Navegação:
      - "próximo"
      - "anterior"
      - "mais dois"
      - "volta três"

Restrições:
    - Não utiliza Search, Decision, Holyrics, LLM, embeddings.
    - Apenas consome interfaces públicas de microfone/capture.py,
      transcricao/stt.py e parser/parser.py.
    - Não modifica código de produção.

Valida exclusivamente:
    - Captura de áudio (MicrophoneCapture).
    - Segmentação VAD (SpeechSegment).
    - Transcrição STT (Faster-Whisper).
    - Parsing determinístico (Parser) diante de transcrições reais.
    - Robustez do parser a variações de fala (sotaque, pausas, ruído).

Requer:
    - sounddevice instalado.
    - faster-whisper instalado.
    - Microfone físico conectado.
    - config/books.json (tabela de livros canônica).
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
# quando transcrições ou nomes de livros contêm acentos.
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

from config import load_books, load_config
from config.models import AudioConfig, STTConfig, VadConfig
from core.exceptions import AudioError, STTError
from core.types import Intent
from estado.state import BibleState
from microfone import CaptureMetrics, DeviceInfo, MicrophoneCapture, SpeechSegment
from parser import Parser, ParserBookTable
from parser.books import load_parser_books
from transcricao import STT, FasterWhisperBackend, STTResult, STTMetrics


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
# Configuração
# ---------------------------------------------------------------------------


def resolve_device(
    cli_device: str | None,
    config_audio: AudioConfig | None,
) -> str:
    """Resolve o dispositivo: CLI > config.yaml > padrão."""
    if cli_device is not None:
        return cli_device
    if config_audio is not None:
        return config_audio.input_device
    return "0"


def build_audio_config(
    device: str,
    config_audio: AudioConfig | None,
) -> AudioConfig:
    """Constrói AudioConfig com o dispositivo selecionado."""
    if config_audio is not None:
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


def build_stt_config(
    cli_model: str | None,
    cli_device: str | None,
    cli_compute_type: str | None,
    config_stt: STTConfig | None,
) -> STTConfig:
    """Constrói STTConfig com overrides de CLI sobre config.yaml."""
    base = config_stt
    if base is None:
        # Fallback hardcoded (cadeia: CLI > config.yaml > fallback)
        base = STTConfig(
            model="large-v3-turbo",
            device="cpu",
            compute_type="int8",
            language="pt",
            chunk_length_s=30,
            vad=VadConfig(mode="silero", min_speech_ms=250, pause_threshold_ms=600),
        )
    model = cli_model if cli_model is not None else base.model
    device = cli_device if cli_device is not None else base.device
    compute_type = cli_compute_type if cli_compute_type is not None else base.compute_type
    return STTConfig(
        model=model,
        device=device,
        compute_type=compute_type,
        language=base.language,
        chunk_length_s=base.chunk_length_s,
        vad=base.vad,
        backend=base.backend,
        beam_size=base.beam_size,
        vad_filter=base.vad_filter,
    )


# ---------------------------------------------------------------------------
# Inicialização do Parser
# ---------------------------------------------------------------------------


def init_parser() -> Parser:
    """Inicializa Parser com a tabela de livros canônica de config/books.json.

    Returns:
        Instância de Parser pronta para uso.
    """
    print()
    print("-" * 40)
    print("Inicializando Parser...")
    books_path = str(_PROJECT_ROOT / "config" / "books.json")
    book_table = load_books(books_path)
    all_books = book_table.all_books()
    parser = Parser(ParserBookTable(all_books))
    print(f"  Livros carregados: {len(all_books)}")
    print(f"  Tabela: config/books.json")
    print("-" * 40)
    return parser


# ---------------------------------------------------------------------------
# Inicialização do STT
# ---------------------------------------------------------------------------


def init_stt(stt_config: STTConfig) -> STT:
    """Inicializa STT, exibindo informações do modelo e hardware."""
    print()
    print("-" * 40)
    print("Inicializando STT...")
    print(f"  backend=faster-whisper")
    print(f"  model={stt_config.model}")
    print(f"  device={stt_config.device}")
    print(f"  compute_type={stt_config.compute_type}")
    print(f"  language={stt_config.language}")
    print(f"  beam_size={stt_config.beam_size}")
    print(f"  vad_filter={stt_config.vad_filter}")
    print()

    load_start = time.monotonic()
    try:
        stt = STT(stt_config)
    except STTError as e:
        print(f"Erro ao carregar modelo STT: {e}")
        print()
        print("Possíveis causas:")
        print("  - faster-whisper não instalado: pip install faster-whisper")
        print("  - Modelo não baixado: o primeiro uso baixa do HuggingFace")
        print("  - CUDA não disponível: use --stt-device cpu --compute-type int8")
        raise

    load_ms = int((time.monotonic() - load_start) * 1000)
    print(f"Modelo carregado em {load_ms} ms")

    backend = stt.backend
    if isinstance(backend, FasterWhisperBackend):
        actual_device = backend.actual_device
        actual_compute_type = backend.actual_compute_type
        print(f"  backend=faster-whisper")
        print(f"  device={actual_device}")
        print(f"  compute_type={actual_compute_type}")
        if actual_device != stt_config.device:
            print(f"  (fallback: {stt_config.device} -> {actual_device})")
    else:
        print(f"  backend={type(backend).__name__}")

    if stt.metrics.gpu_fallback:
        print("  AVISO: GPU nao disponivel - usando CPU (int8)")

    print("-" * 40)
    return stt


# ---------------------------------------------------------------------------
# Captura + STT + Parser
# ---------------------------------------------------------------------------


def run_capture_stt_parser(
    audio_config: AudioConfig,
    stt: STT,
    parser: Parser,
    timeout_s: float | None,
) -> None:
    """Loop de captura + transcrição + parsing.

    Para cada segmento de fala:
      1. Captura e transcreve (STT).
      2. Parser interpreta o texto transcrito.
      3. Imprime texto STT, intent, parâmetros, confiança e latência.
    """
    capture = MicrophoneCapture(audio_config)

    # Estado simulado para o parser (navegação relativa precisa de contexto)
    # Mantemos um BibleState simples que atualizamos conforme o parser interpreta
    sim_state = BibleState()

    print()
    print(f"Dispositivo de captura: {audio_config.input_device}")
    print(
        f"sample_rate={audio_config.sample_rate}, "
        f"channels={audio_config.channels}, "
        f"chunk_ms={audio_config.chunk_ms}, "
        f"vad_enabled={audio_config.vad_enabled}, "
        f"min_speech_ms={audio_config.min_speech_ms}, "
        f"max_silence_ms={audio_config.max_silence_ms}"
    )
    print()
    print("-" * 40)
    print("Aguardando fala... (Ctrl+C para parar)")
    print("-" * 40)

    def _signal_handler(signum: int, frame: object) -> None:
        print("\nParando captura...")
        capture.stop()

    signal.signal(signal.SIGINT, _signal_handler)

    start_time = time.time()
    segment_count = 0

    try:
        for segment in capture.run():
            segment_count += 1
            sim_state = process_segment(stt, parser, segment, segment_count, sim_state)

            if timeout_s is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout_s:
                    print(f"\nTimeout de {timeout_s}s atingido. Parando...")
                    capture.stop()
                    break
    except AudioError as e:
        print(f"\nErro de audio: {e}")
        raise
    except STTError as e:
        print(f"\nErro de STT: {e}")
        raise
    finally:
        capture.stop()

    elapsed = time.time() - start_time
    _print_summary(stt, capture, segment_count, elapsed)


def process_segment(
    stt: STT,
    parser: Parser,
    segment: SpeechSegment,
    count: int,
    sim_state: BibleState,
) -> BibleState:
    """Transcreve e faz parse de um segmento. Imprime resultados.

    Returns:
        Estado atualizado (para contexto de navegação relativa).
    """
    print()
    print(f"Segmento detectado:")
    print(f"  duration_ms={segment.duration_ms}")
    print(f"  bytes={len(segment.audio)}")
    print(f"  timestamp={segment.start_time:.3f}")
    print()

    # 1. STT
    try:
        stt_result = stt.transcribe(segment)
    except STTError as e:
        print(f"  STT ERROR: {e}")
        print()
        return sim_state

    # 2. Parser
    parse_start = time.monotonic()
    intent = parser.parse(stt_result.text, sim_state)
    parse_ms = int((time.monotonic() - parse_start) * 1000)

    # 3. Imprimir resultados
    _print_results(stt_result, intent, parse_ms, stt)

    # 4. Atualizar estado simulado para navegação relativa
    new_state = _update_sim_state(sim_state, intent)
    return new_state


def _print_results(
    stt_result: STTResult,
    intent: Intent,
    parse_ms: int,
    stt: STT,
) -> None:
    """Imprime STT + Parser no formato esperado."""
    # Informações do backend
    backend = stt.backend
    if isinstance(backend, FasterWhisperBackend):
        device = backend.actual_device
        compute_type = backend.actual_compute_type
    else:
        device = "unknown"
        compute_type = "unknown"

    # STT
    print("-" * 40)
    print("STT:")
    if stt_result.text:
        print(f"  {stt_result.text}")
    else:
        print(f"  (transcricao vazia - provavel silencio/ruido)")
    print(f"  latency_ms={stt_result.processing_ms}")
    print(f"  confidence={stt_result.confidence:.2f}")
    print(f"  language={stt_result.language}")
    print(f"  device={device}")
    print(f"  compute_type={compute_type}")
    print()

    # Parser
    print("Parser:")
    print(f"  action={intent.action}")
    if intent.book is not None:
        print(f"  book={intent.book}")
    if intent.book_id is not None:
        print(f"  book_id={intent.book_id}")
    if intent.chapter is not None:
        print(f"  chapter={intent.chapter}")
    if intent.verse is not None:
        print(f"  verse={intent.verse}")
    if intent.amount is not None:
        print(f"  amount={intent.amount}")
    if intent.query is not None:
        print(f"  query={intent.query}")
    print(f"  confidence={intent.confidence:.2f}")
    print(f"  source={intent.source}")
    print(f"  parse_ms={parse_ms}")
    print("-" * 40)


def _update_sim_state(state: BibleState, intent: Intent) -> BibleState:
    """Atualiza estado simulado para navegação relativa.

    Mantém um BibleState simples para que comandos como "próximo"
    ou "volta um" tenham contexto. Não valida limites da Bíblia.
    """
    if intent.action == "show" and intent.book_id is not None:
        return BibleState(
            book_id=intent.book_id,
            chapter=intent.chapter,
            verse=intent.verse,
            version=state.version,
        )
    if intent.action == "next" and not state.is_empty():
        new_verse = (state.verse or 0) + (intent.amount or 1)
        return BibleState(
            book_id=state.book_id,
            chapter=state.chapter,
            verse=new_verse,
            version=state.version,
        )
    if intent.action == "previous" and not state.is_empty():
        new_verse = (state.verse or 1) - (intent.amount or 1)
        new_verse = max(1, new_verse)
        return BibleState(
            book_id=state.book_id,
            chapter=state.chapter,
            verse=new_verse,
            version=state.version,
        )
    return state


def _print_summary(
    stt: STT,
    capture: MicrophoneCapture,
    segment_count: int,
    elapsed_s: float,
) -> None:
    """Imprime resumo final com métricas de captura, STT e parser."""
    cap_metrics = capture.metrics
    stt_metrics = stt.metrics

    print()
    print("-" * 40)
    print("Resumo da sessao:")
    print(f"  Tempo total: {elapsed_s:.1f}s")
    print(f"  Segmentos processados: {segment_count}")
    print()
    print("Captura:")
    print(f"  Total de chunks: {cap_metrics.total_chunks}")
    print(f"  Chunks de fala: {cap_metrics.speech_chunks}")
    print(f"  Chunks de silencio: {cap_metrics.silence_chunks}")
    print(f"  Segmentos emitidos: {cap_metrics.segments_emitted}")
    print(f"  Segmentos descartados: {cap_metrics.segments_discarded}")
    print(f"  Tempo de fala: {cap_metrics.total_speech_ms / 1000:.1f}s")
    print(f"  Reconexoes: {cap_metrics.reconnect_count}")
    print(f"  Erros: {cap_metrics.errors}")
    print()
    print("STT:")
    print(f"  Transcricoes totais: {stt_metrics.total_transcriptions}")
    print(f"  Bem-sucedidas: {stt_metrics.successful}")
    print(f"  Falhas: {stt_metrics.failed}")
    print(f"  Texto vazio: {stt_metrics.empty_text}")
    print(f"  Latencia media: {stt_metrics.avg_processing_ms:.0f} ms")
    print(f"  Confianca media: {stt_metrics.avg_confidence:.2f}")
    print(f"  RTF: {stt_metrics.rtf:.2f}")
    if stt_metrics.gpu_fallback:
        print(f"  GPU fallback: SIM")
    print("-" * 40)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parsea argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        description=(
            "Diagnostico de parser live - valida Captura + STT + Parser "
            "com hardware real."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Frases sugeridas para teste (casos obrigatorios):\n"
            "  Referencias diretas:\n"
            '    "Joao 3:16"\n'
            '    "Romanos 8:28"\n'
            '    "Filipenses 4:8"\n'
            '    "Carta aos Filipenses capitulo 4 versiculo 8"\n'
            '    "Primeira carta aos Corintios capitulo 13"\n'
            "  Navegacao:\n"
            '    "proximo"\n'
            '    "anterior"\n'
            '    "mais dois"\n'
            '    "volta tres"\n'
            "\n"
            "Exemplos:\n"
            "  python tools/diagnostics/test_parser_live.py\n"
            "  python tools/diagnostics/test_parser_live.py --device 0\n"
            '  python tools/diagnostics/test_parser_live.py --device "Headset USB"\n'
            "  python tools/diagnostics/test_parser_live.py --model small --stt-device cpu\n"
            "  python tools/diagnostics/test_parser_live.py --model large-v3-turbo --stt-device cuda\n"
            "  python tools/diagnostics/test_parser_live.py --timeout 60\n"
        ),
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Dispositivo de entrada (indice ou nome parcial). "
        "Default: do config.yaml.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Apenas lista dispositivos e sai.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Tempo maximo de captura em segundos (default: ate Ctrl+C).",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/config.yaml",
        help="Caminho para config.yaml (default: config/config.yaml).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override do modelo STT (ex.: large-v3-turbo, medium, small). "
        "Default: do config.yaml (large-v3-turbo).",
    )
    parser.add_argument(
        "--stt-device",
        type=str,
        default=None,
        choices=["cpu", "cuda", "auto"],
        help="Override do device STT (cpu/cuda/auto).",
    )
    parser.add_argument(
        "--compute-type",
        type=str,
        default=None,
        help="Override do compute_type (int8, float16, int8_float16, float32).",
    )
    return parser.parse_args()


def main() -> int:
    """Entry point do diagnostico de parser live."""
    args = parse_args()

    # 1. Listar dispositivos
    try:
        devices = list_devices()
    except Exception as e:
        print(f"Erro ao listar dispositivos: {e}")
        print("Verifique se sounddevice esta instalado: pip install sounddevice")
        return 1

    print_devices(devices)

    default_dev = find_default(devices)
    if default_dev is not None:
        print(f"Dispositivo padrao: {default_dev.index} - {default_dev.name}")
    else:
        print("Nenhum dispositivo padrao identificado.")

    if args.list_only:
        return 0

    if not devices:
        print("\nNenhum dispositivo de entrada disponivel. Conecte um microfone.")
        return 1

    # 2. Carregar config.yaml
    config_audio: AudioConfig | None = None
    config_stt: STTConfig | None = None
    try:
        if "HOLYRICS_TOKEN" not in os.environ:
            os.environ["HOLYRICS_TOKEN"] = "dummy"
        cfg = load_config(args.config)
        config_audio = cfg.audio
        config_stt = cfg.stt
    except Exception as e:
        print(f"Aviso: nao foi possivel carregar config.yaml ({e}).")
        print("Usando defaults.")

    # 3. Resolver dispositivo de captura
    device = resolve_device(args.device, config_audio)
    print(f"\nDispositivo de captura selecionado: {device}")

    try:
        audio_config = build_audio_config(device, config_audio)
        capture = MicrophoneCapture(audio_config)
        capture.find_device(device)
    except AudioError as e:
        print(f"\nErro: {e}")
        print("\nDispositivos disponiveis:")
        for d in devices:
            marker = " (padrao)" if d.is_default else ""
            print(f"  {d.index} - {d.name}{marker}")
        return 1

    # 4. Inicializar Parser
    try:
        parser = init_parser()
    except Exception as e:
        print(f"Erro ao inicializar parser: {e}")
        return 1

    # 5. Construir config STT
    stt_config = build_stt_config(
        cli_model=args.model,
        cli_device=args.stt_device,
        cli_compute_type=args.compute_type,
        config_stt=config_stt,
    )

    # 6. Inicializar STT
    try:
        stt = init_stt(stt_config)
    except STTError:
        return 1
    except Exception as e:
        print(f"Erro inesperado ao inicializar STT: {e}")
        return 1

    # 7. Loop de captura + STT + parser
    try:
        run_capture_stt_parser(audio_config, stt, parser, args.timeout)
    except AudioError as e:
        print(f"\nErro durante captura: {e}")
        return 1
    except STTError as e:
        print(f"\nErro durante transcricao: {e}")
        return 1
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuario.")
    except Exception as e:
        print(f"\nErro inesperado: {e}")
        return 1
    finally:
        try:
            stt.close()
            print("Modelo STT liberado.")
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
