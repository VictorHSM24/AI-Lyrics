"""Diagnóstico live LLM — valida Microfone + STT + Parser + LLM + Search + Console.

Fluxo validado:
    Microfone → MicrophoneCapture → SpeechSegment → STT → Parser
    → LLM (se uncertain) → Search (se search) → Console

SEM Holyrics inicialmente.

Este script NÃO é um teste unitário. É uma ferramenta de diagnóstico manual
que usa hardware real (microfone + CPU/GPU + Ollama) para validar a
integração completa entre STT, Parser, LLM e Searcher.

Uso:
    python tools/diagnostics/test_llm_live.py
    python tools/diagnostics/test_llm_live.py --device 0
    python tools/diagnostics/test_llm_live.py --device "Headset USB"
    python tools/diagnostics/test_llm_live.py --list-only
    python tools/diagnostics/test_llm_live.py --timeout 120
    python tools/diagnostics/test_llm_live.py --model large-v3-turbo --stt-device cuda
    python tools/diagnostics/test_llm_live.py --text "aquele texto que diz que todas as coisas cooperam para o bem"
    python tools/diagnostics/test_llm_live.py --no-mic  # usa --text em vez de microfone

Frases sugeridas para teste (casos obrigatórios):
    Busca semântica (action=search via LLM):
      - "aquele texto que diz que todas as coisas cooperam para o bem"
      - "o versículo sobre a fé ser a certeza das coisas que se esperam"
      - "o salmo do vale da sombra da morte"
      - "tudo posso naquele que me fortalece"
    Referências diretas (LLM NÃO deve ser chamado):
      - "Hebreus 11:1"
      - "próximo"
      - "mais dois"

Regras importantes:
    - Se parser retornar uncertain: chamar LLM.
    - Se LLM retornar search: chamar Searcher.
    - Se LLM retornar show/next/previous/jump: seguir fluxo normal.
    - Se LLM retornar none: encerrar segmento.
    - Se Ollama offline: não bloquear, retornar action="none".
    - NÃO chama Holyrics.

Restrições:
    - Não modifica código de produção.
    - Não cria novos DTOs nem contratos públicos.
    - Reutiliza exclusivamente módulos existentes.

Requer:
    - sounddevice instalado (se usar microfone).
    - faster-whisper instalado.
    - Microfone físico conectado (se usar microfone).
    - Ollama rodando em http://127.0.0.1:11434 com modelo qwen3:8b-q4_k_m.
    - config/books.json e data/bible.pt-br.sqlite (FTS5).
"""

from __future__ import annotations

import argparse
import io
import signal
import sys
import time
from pathlib import Path

# Forcar UTF-8 no stdout/stderr para evitar crash em Windows cp1252
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from busca import Searcher, SearchResult
from config import load_books, load_config
from config.models import AudioConfig, STTConfig, VadConfig
from core.exceptions import AudioError, STTError
from core.types import Intent, Utterance
from estado.state import BibleStateManager, BibleState, load_bible_structure
from llm import LLMClient
from microfone import DeviceInfo, MicrophoneCapture, SpeechSegment
from parser import Parser, ParserBookTable
from transcricao import STT, FasterWhisperBackend, STTResult


# ---------------------------------------------------------------------------
# Listagem de dispositivos
# ---------------------------------------------------------------------------


def list_devices() -> list[DeviceInfo]:
    return MicrophoneCapture.list_input_devices()


def print_devices(devices: list[DeviceInfo]) -> None:
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
    if cli_device is not None:
        return cli_device
    if config_audio is not None:
        return config_audio.input_device
    return "0"


def build_audio_config(
    device: str,
    config_audio: AudioConfig | None,
) -> AudioConfig:
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
    base = config_stt
    if base is None:
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
        model=model, device=device, compute_type=compute_type,
        language=base.language, chunk_length_s=base.chunk_length_s,
        vad=base.vad, backend=base.backend, beam_size=base.beam_size,
        vad_filter=base.vad_filter,
    )


# ---------------------------------------------------------------------------
# Inicialização de módulos
# ---------------------------------------------------------------------------


def init_parser() -> Parser:
    print()
    print("-" * 40)
    print("Inicializando Parser...")
    books_path = str(_PROJECT_ROOT / "config" / "books.json")
    book_table = load_books(books_path)
    all_books = book_table.all_books()
    parser = Parser(ParserBookTable(all_books))
    print(f"  Livros carregados: {len(all_books)}")
    print("-" * 40)
    return parser


def init_stt(stt_config: STTConfig) -> STT:
    print()
    print("-" * 40)
    print("Inicializando STT...")
    print(f"  backend=faster-whisper")
    print(f"  model={stt_config.model}")
    print(f"  device={stt_config.device}")
    print(f"  compute_type={stt_config.compute_type}")
    print(f"  language={stt_config.language}")
    print()
    load_start = time.monotonic()
    try:
        stt = STT(stt_config)
    except STTError as e:
        print(f"Erro ao carregar modelo STT: {e}")
        raise
    load_ms = int((time.monotonic() - load_start) * 1000)
    print(f"Modelo carregado em {load_ms} ms")
    backend = stt.backend
    if isinstance(backend, FasterWhisperBackend):
        print(f"  actual_device={backend.actual_device}")
        print(f"  actual_compute_type={backend.actual_compute_type}")
    print("-" * 40)
    return stt


def init_llm(cfg) -> LLMClient | None:
    """Inicializa LLMClient e verifica disponibilidade do Ollama."""
    print()
    print("-" * 40)
    print("Inicializando LLMClient...")
    print(f"  base_url={cfg.llm.base_url}")
    print(f"  model={cfg.llm.model}")
    print(f"  lazy_load={cfg.llm.lazy_load}")
    print(f"  timeout_ms={cfg.llm.timeout_ms}")
    print(f"  max_tokens={cfg.llm.max_tokens}")
    books_path = str(_PROJECT_ROOT / "config" / "books.json")
    book_table = load_books(books_path)
    try:
        client = LLMClient(cfg.llm, book_table)
    except Exception as e:
        print(f"  AVISO: falha ao criar LLMClient: {e}")
        print("  LLM desabilitado.")
        print("-" * 40)
        return None
    print("  Verificando Ollama...")
    if client.is_available():
        print("  Ollama: ONLINE")
    else:
        print("  Ollama: OFFLINE")
        print("  AVISO: LLM desabilitado. Comandos uncertain → forward_to_llm.")
        client.close()
        client = None
    print("-" * 40)
    return client


def init_searcher(cfg) -> Searcher | None:
    print()
    print("-" * 40)
    print("Inicializando Searcher...")
    fts5_db = str(_PROJECT_ROOT / cfg.search.fts5_db)
    print(f"  FTS5 DB: {fts5_db}")
    if not Path(fts5_db).exists():
        print(f"  AVISO: base FTS5 não encontrada - busca desabilitada")
        print("-" * 40)
        return None
    try:
        books_path = str(_PROJECT_ROOT / "config" / "books.json")
        book_table = load_books(books_path)
        searcher = Searcher(cfg.search, book_table, cfg.state.default_version)
        print(f"  Searcher inicializado (version={cfg.state.default_version})")
        print("-" * 40)
        return searcher
    except Exception as e:
        print(f"  AVISO: falha ao inicializar Searcher: {e}")
        print("-" * 40)
        return None


def init_state_manager(cfg) -> BibleStateManager:
    print()
    print("-" * 40)
    print("Inicializando StateManager...")
    fts5_db = str(_PROJECT_ROOT / cfg.search.fts5_db)
    structure = load_bible_structure(fts5_db)
    books_path = str(_PROJECT_ROOT / "config" / "books.json")
    book_table = load_books(books_path)
    all_books = book_table.all_books()
    book_names = {b.id: b.canonical for b in all_books}
    state_mgr = BibleStateManager(
        structure=structure, book_names=book_names,
        persist_path=None, default_version=cfg.state.default_version,
    )
    print(f"  Estrutura carregada: {len(structure.chapter_counts)} livros")
    print("-" * 40)
    return state_mgr


# ---------------------------------------------------------------------------
# Processamento
# ---------------------------------------------------------------------------


def process_text(
    text: str,
    c_stt: float,
    parser: Parser,
    llm_client: LLMClient | None,
    searcher: Searcher | None,
    state_mgr: BibleStateManager,
) -> None:
    """Processa um texto completo: Parser → LLM (se uncertain) → Search → Console."""
    print()
    print("=" * 60)
    print(f"STT: \"{text}\" (c_stt={c_stt:.2f})")

    # 1. Parser
    t0 = time.monotonic()
    intent = parser.parse(text, state_mgr.current())
    parser_ms = (time.monotonic() - t0) * 1000
    print(f"Parser: action={intent.action} confidence={intent.confidence:.2f} "
          f"source={intent.source} ({parser_ms:.1f} ms)")

    if intent.book:
        print(f"  book={intent.book} chapter={intent.chapter} verse={intent.verse}")

    # 2. LLM (apenas se uncertain)
    if intent.action == "uncertain":
        if llm_client is not None:
            print(f"LLM: parser retornou uncertain — encaminhando ao LLM...")
            t0 = time.monotonic()
            llm_intent = llm_client.interpret(text, state_mgr.current())
            llm_ms = (time.monotonic() - t0) * 1000
            print(f"LLM: action={llm_intent.action} confidence={llm_intent.confidence:.2f} "
                  f"source={llm_intent.source} ({llm_ms:.1f} ms)")
            if llm_intent.query:
                print(f"  query=\"{llm_intent.query}\"")
            if llm_intent.book:
                print(f"  book={llm_intent.book} chapter={llm_intent.chapter} "
                      f"verse={llm_intent.verse}")

            # Anti-loop
            if llm_intent.action == "uncertain":
                print("LLM: retornou uncertain — convertendo para none")
                llm_intent = Intent(
                    action="none", confidence=llm_intent.confidence,
                    source="llm", raw=text,
                )

            intent = llm_intent
        else:
            print("LLM: skipped (Ollama offline) — forward_to_llm")
            print("Decision: outcome=forward_to_llm")
            print("=" * 60)
            return

    # 3. Search (se action=search)
    search_results: list[SearchResult] | None = None
    if intent.action == "search" and searcher is not None:
        query = intent.query or text
        print(f"Search: buscando \"{query}\"...")
        t0 = time.monotonic()
        search_results = searcher.search(query, state=state_mgr.current())
        search_ms = (time.monotonic() - t0) * 1000
        print(f"Search: {len(search_results)} resultados ({search_ms:.1f} ms)")
        for i, r in enumerate(search_results[:5]):
            amb = " [AMBIGUOUS]" if r.ambiguous else ""
            print(f"  {i+1}. {r.reference} (score={r.score:.3f} "
                  f"c_search={r.c_search:.2f}{amb})")
            print(f"     \"{r.text[:80]}...\"")
    elif intent.action == "search" and searcher is None:
        print("Search: searcher não disponível")

    # 4. Resultado final
    if intent.action == "none":
        print("Decision: outcome=ignore (action=none)")
    elif intent.action == "search" and search_results:
        top = search_results[0]
        print(f"Decision: top_result={top.reference} "
              f"c_search={top.c_search:.2f} ambiguous={top.ambiguous}")
    elif intent.action in ("show", "next", "previous", "jump"):
        print(f"Decision: action={intent.action} "
              f"book={intent.book} chapter={intent.chapter} verse={intent.verse}")

    print("=" * 60)


def process_segment(
    segment: SpeechSegment,
    stt: STT,
    parser: Parser,
    llm_client: LLMClient | None,
    searcher: Searcher | None,
    state_mgr: BibleStateManager,
) -> None:
    """Processa um segmento de áudio: STT → Parser → LLM → Search → Console."""
    t0 = time.monotonic()
    try:
        result = stt.transcribe(segment)
    except STTError as e:
        print(f"STT Error: {e}")
        return

    stt_ms = (time.monotonic() - t0) * 1000
    if not result.text or not result.text.strip():
        print(f"\n[STT: silêncio/vazio em {stt_ms:.0f} ms]")
        return

    print(f"\n[STT: {stt_ms:.0f} ms]")
    process_text(
        result.text, result.confidence,
        parser, llm_client, searcher, state_mgr,
    )


# ---------------------------------------------------------------------------
# Modo texto (sem microfone)
# ---------------------------------------------------------------------------


def run_text_mode(
    texts: list[str],
    parser: Parser,
    llm_client: LLMClient | None,
    searcher: Searcher | None,
    state_mgr: BibleStateManager,
) -> None:
    """Processa uma lista de textos sem usar microfone."""
    print()
    print("#" * 60)
    print("# MODO TEXTO (sem microfone)")
    print("#" * 60)
    for text in texts:
        process_text(text, 0.90, parser, llm_client, searcher, state_mgr)


# ---------------------------------------------------------------------------
# Modo microfone
# ---------------------------------------------------------------------------


def run_mic_mode(
    audio_config: AudioConfig,
    stt: STT,
    parser: Parser,
    llm_client: LLMClient | None,
    searcher: Searcher | None,
    state_mgr: BibleStateManager,
    timeout: float,
) -> None:
    """Modo microfone: captura áudio continuamente e processa."""
    print()
    print("#" * 60)
    print("# MODO MICROFONE")
    print(f"# Timeout: {timeout:.0f}s")
    print("# Ctrl+C para parar")
    print("#" * 60)

    capture = MicrophoneCapture(audio_config)

    def _signal_handler(signum: int, frame: object) -> None:
        print("\nParando captura...")
        capture.stop()

    signal.signal(signal.SIGINT, _signal_handler)

    start = time.monotonic()
    segment_count = 0

    print(f"\nOuvindo... (timeout={timeout:.0f}s)")

    try:
        for segment in capture.run():
            segment_count += 1
            if time.monotonic() - start > timeout:
                print(f"\nTimeout de {timeout:.0f}s atingido. Parando...")
                capture.stop()
                break
            process_segment(
                segment, stt, parser, llm_client, searcher, state_mgr,
            )
            start = time.monotonic()  # reset timeout após cada segmento
    except AudioError as e:
        print(f"\nErro de áudio: {e}")
        raise
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
    finally:
        capture.stop()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Diagnóstico live LLM: Microfone → STT → Parser → LLM → Search → Console"
    )
    ap.add_argument("--device", type=str, default=None,
                    help="Índice ou nome do dispositivo de entrada")
    ap.add_argument("--list-only", action="store_true",
                    help="Apenas lista dispositivos de áudio")
    ap.add_argument("--timeout", type=float, default=120,
                    help="Timeout em segundos (default: 120)")
    ap.add_argument("--model", type=str, default=None,
                    help="Modelo STT (override config.yaml)")
    ap.add_argument("--stt-device", type=str, default=None,
                    help="Device STT: cpu | cuda")
    ap.add_argument("--compute-type", type=str, default=None,
                    help="Compute type: int8 | float16 | float32")
    ap.add_argument("--text", type=str, default=None,
                    help="Processar texto fixo em vez de microfone")
    ap.add_argument("--no-mic", action="store_true",
                    help="Não usar microfone (requer --text)")
    ap.add_argument("--config", type=str, default="config/config.yaml",
                    help="Caminho para config.yaml")
    args = ap.parse_args()

    # --list-only
    if args.list_only:
        devices = list_devices()
        print_devices(devices)
        return

    # Carregar config
    config_path = str(_PROJECT_ROOT / args.config)
    cfg = load_config(config_path)

    # Inicializar módulos
    parser = init_parser()
    state_mgr = init_state_manager(cfg)
    llm_client = init_llm(cfg)
    searcher = init_searcher(cfg)

    # Modo texto
    if args.no_mic or args.text:
        texts = [args.text] if args.text else [
            "aquele texto que diz que todas as coisas cooperam para o bem",
            "o versículo sobre a fé ser a certeza das coisas que se esperam",
            "o salmo do vale da sombra da morte",
            "tudo posso naquele que me fortalece",
            "Hebreus 11:1",
            "próximo",
            "mais dois",
        ]
        run_text_mode(texts, parser, llm_client, searcher, state_mgr)
        if llm_client is not None:
            llm_client.close()
        return

    # Modo microfone
    stt_config = build_stt_config(
        args.model, args.stt_device, args.compute_type, cfg.stt,
    )
    stt = init_stt(stt_config)

    devices = list_devices()
    print_devices(devices)
    default = find_default(devices)
    device = resolve_device(args.device, cfg.audio)
    audio_config = build_audio_config(device, cfg.audio)

    if default:
        print(f"Dispositivo padrão: {default.name}")
    print(f"Dispositivo selecionado: {device}")

    run_mic_mode(
        audio_config, stt, parser, llm_client, searcher, state_mgr, args.timeout,
    )

    if llm_client is not None:
        llm_client.close()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    main()
