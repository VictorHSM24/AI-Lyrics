"""Diagnostico live pipeline - valida pipeline completo com hardware real.

Fluxo validado:
    Microfone -> MicrophoneCapture -> SpeechSegment -> STT -> Parser
    -> Search -> DecisionEngine -> HolyricsClient -> Console

Este script NAO e um teste unitario. E uma ferramenta de diagnostico manual
que usa hardware real (microfone + CPU/GPU + Holyrics) para validar a
integracao completa entre todos os modulos do pipeline.

Uso:
    python tools/diagnostics/test_live_pipeline.py
    python tools/diagnostics/test_live_pipeline.py --device 0
    python tools/diagnostics/test_live_pipeline.py --device "Headset USB"
    python tools/diagnostics/test_live_pipeline.py --list-only
    python tools/diagnostics/test_live_pipeline.py --timeout 120
    python tools/diagnostics/test_live_pipeline.py --model large-v3-turbo --stt-device cuda
    python tools/diagnostics/test_live_pipeline.py --dry-run  # nao chama Holyrics

Frases sugeridas para teste (casos obrigatorios):
    Referencias diretas:
      - "Hebreus capitulo 11 versiculo 2"
      - "Romanos 8 28"
    Navegacao:
      - "proximo"
      - "mais dois"
      - "volta um"
    Busca textual (action=search):
      - "aquele texto que diz que todas as coisas cooperam para o bem"

Regras importantes:
    - Se outcome != "execute": NAO chamar Holyrics.
    - Se SearchResult.ambiguous: imprimir "confirmacao necessaria".
    - Se parser retornar uncertain: imprimir "encaminhar para LLM".
    - NAO implementa LLM, interface grafica, embeddings nem persistencia.

Restricoes:
    - NAO modifica codigo de producao.
    - NAO cria novos DTOs nem contratos publicos.
    - Reutiliza exclusivamente modulos existentes.

Requer:
    - sounddevice instalado.
    - faster-whisper instalado.
    - Microfone fisico conectado.
    - Holyrics rodando em http://127.0.0.1:3000/api (ou --dry-run).
    - config/books.json e data/bible.pt-br.sqlite (FTS5).
    - HOLYRICS_TOKEN environment variable (ou --dry-run).
"""

from __future__ import annotations

import argparse
import io
import os
import signal
import sys
import time
from pathlib import Path

# Forcar UTF-8 no stdout/stderr para evitar crash em Windows cp1252
# quando transcricoes ou nomes de livros contem acentos.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

# Garantir que a raiz do projeto esta no sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from busca import Searcher, SearchResult
from busca.exceptions import SearchError
from config import load_books, load_config
from config.models import AudioConfig, STTConfig, VadConfig
from core.decision import DecisionEngine
from core.exceptions import (
    AudioError,
    DecisionError,
    STTError,
)
from core.types import Decision, Intent, VerseRef
from estado.state import BibleStateManager, BibleState, load_bible_structure
from integracao_holyrics import HolyricsClient, HolyricsError
from microfone import DeviceInfo, MicrophoneCapture, SpeechSegment
from parser import Parser, ParserBookTable
from transcricao import STT, FasterWhisperBackend, STTResult


# ---------------------------------------------------------------------------
# Listagem de dispositivos
# ---------------------------------------------------------------------------


def list_devices() -> list[DeviceInfo]:
    """Lista dispositivos de entrada disponiveis via MicrophoneCapture."""
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
            marker = " (padrao)" if d.is_default else ""
            print(f"{d.index} - {d.name}{marker}")
    print("-" * 40)


def find_default(devices: list[DeviceInfo]) -> DeviceInfo | None:
    """Retorna o dispositivo padrao, se houver."""
    for d in devices:
        if d.is_default:
            return d
    return None


# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------


def resolve_device(
    cli_device: str | None,
    config_audio: AudioConfig | None,
) -> str:
    """Resolve o dispositivo: CLI > config.yaml > padrao."""
    if cli_device is not None:
        return cli_device
    if config_audio is not None:
        return config_audio.input_device
    return "0"


def build_audio_config(
    device: str,
    config_audio: AudioConfig | None,
) -> AudioConfig:
    """Construi AudioConfig com o dispositivo selecionado."""
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
    """Construi STTConfig com overrides de CLI sobre config.yaml.

    Cadeia de resolucao do modelo:
      1. --model <valor>          (CLI, maior precedencia)
      2. config.yaml -> stt.model (large-v3-turbo)
      3. fallback hardcoded       (large-v3-turbo)
    """
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
# Inicializacao de modulos
# ---------------------------------------------------------------------------


def init_parser() -> Parser:
    """Inicializa Parser com a tabela de livros canonica de config/books.json."""
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


def init_stt(stt_config: STTConfig) -> STT:
    """Inicializa STT, exibindo informacoes do modelo e hardware."""
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
        print("Possiveis causas:")
        print("  - faster-whisper nao instalado: pip install faster-whisper")
        print("  - Modelo nao baixado: o primeiro uso baixa do HuggingFace")
        print("  - CUDA nao disponivel: use --stt-device cpu --compute-type int8")
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


def init_searcher(cfg) -> Searcher | None:
    """Inicializa Searcher com a base FTS5."""
    print()
    print("-" * 40)
    print("Inicializando Searcher...")
    fts5_db = str(_PROJECT_ROOT / cfg.search.fts5_db)
    print(f"  FTS5 DB: {fts5_db}")
    if not Path(fts5_db).exists():
        print(f"  AVISO: base FTS5 nao encontrada - busca desabilitada")
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
        print("  Busca desabilitada.")
        print("-" * 40)
        return None


def init_state_manager(cfg) -> BibleStateManager:
    """Inicializa BibleStateManager com a estrutura da Biblia."""
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
        structure=structure,
        book_names=book_names,
        persist_path=None,  # nao persistir em diagnostico
        default_version=cfg.state.default_version,
    )
    print(f"  Estrutura carregada: {len(structure.chapter_counts)} livros")
    print(f"  Versao padrao: {cfg.state.default_version}")
    print("-" * 40)
    return state_mgr


def init_holyrics(cfg, dry_run: bool) -> HolyricsClient | None:
    """Inicializa HolyricsClient e testa conexao."""
    print()
    print("-" * 40)
    print("Inicializando HolyricsClient...")
    if dry_run:
        print("  --dry-run: Holyrics NAO sera chamado")
        print("-" * 40)
        return None
    token = cfg.holyrics.token
    if not token or token == "dummy":
        print("  AVISO: HOLYRICS_TOKEN nao configurado")
        print("  Use --dry-run ou configure HOLYRICS_TOKEN")
        print("-" * 40)
        return None
    try:
        client = HolyricsClient(
            base_url=cfg.holyrics.base_url,
            token=token,
            timeout_s=cfg.holyrics.timeout_ms / 1000.0,
        )
        print(f"  base_url={cfg.holyrics.base_url}")
        print(f"  timeout={cfg.holyrics.timeout_ms} ms")
        # Testar conexao
        print("  Testando conexao...")
        if client.test_connection():
            print("  Conexao: OK")
        else:
            print("  Conexao: FALHOU (Holyrics offline ou token invalido)")
            print("  Continuando em modo dry-run...")
            print("-" * 40)
            return None
        print("-" * 40)
        return client
    except Exception as e:
        print(f"  Erro ao conectar: {e}")
        print("  Continuando em modo dry-run...")
        print("-" * 40)
        return None


def init_decision_engine(
    cfg,
    state_mgr: BibleStateManager,
    holyrics: HolyricsClient | None,
) -> DecisionEngine:
    """Inicializa DecisionEngine."""
    print()
    print("-" * 40)
    print("Inicializando DecisionEngine...")
    print(f"  mode={cfg.mode}")
    print(f"  min_execute={cfg.confidence.min_execute}")
    print(f"  min_confirm={cfg.confidence.min_confirm}")
    print(f"  stt_min={cfg.confidence.stt_min}")
    engine = DecisionEngine(
        confidence_config=cfg.confidence,
        state_manager=state_mgr,
        holyrics_client=holyrics,
        mode=cfg.mode,
    )
    print(f"  holyrics={'conectado' if holyrics is not None else 'dry-run'}")
    print("-" * 40)
    return engine


# ---------------------------------------------------------------------------
# Processamento de segmento (pipeline completo)
# ---------------------------------------------------------------------------


def process_segment(
    stt: STT,
    parser: Parser,
    searcher: Searcher | None,
    engine: DecisionEngine,
    state_mgr: BibleStateManager,
    segment: SpeechSegment,
    count: int,
    holyrics_active: bool,
) -> None:
    """Processa um segmento pelo pipeline completo: STT -> Parser -> Search -> Decision -> Holyrics."""
    print()
    print("=" * 60)
    print(f"SEGMENTO #{count}")
    print("=" * 60)
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
        return

    _print_stt(stt_result, stt)

    # Texto vazio -> nada a fazer
    if not stt_result.text.strip():
        print("  (transcricao vazia - provavel silencio/ruido)")
        print()
        return

    # 2. Parser
    parse_start = time.monotonic()
    intent = parser.parse(stt_result.text, state_mgr.current())
    parse_ms = int((time.monotonic() - parse_start) * 1000)

    _print_parser(intent, parse_ms)

    # Parser retornou uncertain -> encaminhar para LLM
    if intent.action == "uncertain":
        print()
        print("  >>> encaminhar para LLM")
        print()
        return

    # action == "none" -> nao e comando
    if intent.action == "none":
        print()
        print("  >>> nao e comando (action=none)")
        print()
        return

    # 3. Search (se action == "search")
    search_results: list[SearchResult] | None = None
    if intent.action == "search" and searcher is not None:
        search_start = time.monotonic()
        try:
            search_results = searcher.search(
                intent.query or stt_result.text,
                state=state_mgr.current(),
            )
        except SearchError as e:
            print(f"  SEARCH ERROR: {e}")
            print()
            return
        search_ms = int((time.monotonic() - search_start) * 1000)
        _print_search(search_results, search_ms)

        # SearchResult ambiguo -> confirmacao necessaria
        if search_results and search_results[0].ambiguous:
            print()
            print("  >>> confirmacao necessaria")
            print()
            return

        # Resultados vazios
        if not search_results:
            print()
            print("  >>> nenhum resultado encontrado")
            print()
            return
    elif intent.action == "search" and searcher is None:
        print()
        print("  >>> busca indisponivel (Searcher nao inicializado)")
        print()
        return

    # 4. Decision.evaluate
    try:
        decision = engine.evaluate(
            intent,
            c_stt=stt_result.confidence,
            search_results=search_results,
        )
    except DecisionError as e:
        print(f"  DECISION ERROR: {e}")
        print()
        return

    _print_decision(decision)

    # 5. Execute (se outcome == "execute")
    if decision.outcome == "execute":
        try:
            ref = engine.execute(decision, search_results)
            _print_holyrics(ref, decision, holyrics_active)
        except DecisionError as e:
            print()
            print(f"  HOLYRICS ERROR: {e}")
            print()
        except HolyricsError as e:
            print()
            print(f"  HOLYRICS ERROR: {e}")
            print()
    elif decision.outcome == "confirm":
        print()
        print("  >>> confirmacao necessaria (outcome=confirm)")
        print()
    elif decision.outcome == "forward_to_llm":
        print()
        print("  >>> encaminhar para LLM (outcome=forward_to_llm)")
        print()
    elif decision.outcome == "ignore":
        print()
        print(f"  >>> ignorado (outcome=ignore)")
        print(f"  reason: {decision.reason}")
        print()


# ---------------------------------------------------------------------------
# Impressao de resultados por stage
# ---------------------------------------------------------------------------


def _print_stt(stt_result: STTResult, stt: STT) -> None:
    """Imprime bloco STT."""
    backend = stt.backend
    if isinstance(backend, FasterWhisperBackend):
        device = backend.actual_device
        compute_type = backend.actual_compute_type
    else:
        device = "unknown"
        compute_type = "unknown"

    print("-" * 40)
    print("STT:")
    if stt_result.text:
        print(f"  {stt_result.text}")
    else:
        print(f"  (transcricao vazia)")
    print(f"  latency_ms={stt_result.processing_ms}")
    print(f"  confidence={stt_result.confidence:.2f}")
    print(f"  language={stt_result.language}")
    print(f"  device={device}")
    print(f"  compute_type={compute_type}")
    print(f"  model={stt._config.model}")
    print()


def _print_parser(intent: Intent, parse_ms: int) -> None:
    """Imprime bloco Parser."""
    print("-" * 40)
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
    print()


def _print_search(results: list[SearchResult], search_ms: int) -> None:
    """Imprime bloco Search."""
    print("-" * 40)
    print("Search:")
    print(f"  results={len(results)}")
    print(f"  search_ms={search_ms}")
    if results:
        top = results[0]
        print(f"  resolved={top.reference}")
        print(f"  book={top.book}")
        print(f"  chapter={top.chapter}")
        if top.verse is not None:
            print(f"  verse={top.verse}")
        print(f"  confidence={top.c_search:.2f}")
        print(f"  ambiguous={top.ambiguous}")
        print(f"  match_type={top.match_type}")
        if len(results) > 1:
            print(f"  (top-2: {results[1].reference} score={results[1].score:.3f})")
    print()


def _print_decision(decision: Decision) -> None:
    """Imprime bloco Decision."""
    print("-" * 40)
    print("Decision:")
    print(f"  action={decision.action}")
    print(f"  outcome={decision.outcome}")
    print(f"  confidence={decision.confidence:.2f}")
    print(f"  requires_confirmation={decision.requires_confirmation}")
    print(f"  forward_to_llm={decision.forward_to_llm}")
    print(f"  ignore={decision.ignore}")
    print(f"  reason={decision.reason}")
    cb = decision.confidence_breakdown
    if cb is not None:
        print(f"  c_stt={cb.c_stt:.2f}")
        print(f"  c_intent={cb.c_intent:.2f}")
        print(f"  c_search={cb.c_search:.2f}")
    print()


def _print_holyrics(ref: VerseRef | None, decision: Decision, holyrics_active: bool) -> None:
    """Imprime bloco Holyrics.

    Args:
        ref: VerseRef resolvido (ou None).
        decision: Decision avaliada.
        holyrics_active: True se HolyricsClient real esta conectado e
            show_verse() foi realmente chamado. False se dry-run.
    """
    print("-" * 40)
    print("Holyrics:")
    if not holyrics_active:
        print(f"  dry_run=True")
        print(f"  request_not_sent=True")
        if ref is not None:
            print(f"  reference={ref.reference}")
            print(f"  book={ref.book}")
            print(f"  book_id={ref.book_id}")
            print(f"  chapter={ref.chapter}")
            if ref.verse is not None:
                print(f"  verse={ref.verse}")
            print(f"  version={ref.version}")
        else:
            print(f"  ref=none")
        print()
        return
    if ref is not None:
        print(f"  status=ok")
        print(f"  reference={ref.reference}")
        print(f"  book={ref.book}")
        print(f"  book_id={ref.book_id}")
        print(f"  chapter={ref.chapter}")
        if ref.verse is not None:
            print(f"  verse={ref.verse}")
        print(f"  version={ref.version}")
    else:
        print(f"  status=failed")
        print(f"  reason=ref not resolved")
    print()


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------


def run_live_pipeline(
    audio_config: AudioConfig,
    stt: STT,
    parser: Parser,
    searcher: Searcher | None,
    engine: DecisionEngine,
    state_mgr: BibleStateManager,
    timeout_s: float | None,
    holyrics_active: bool,
) -> None:
    """Loop de captura + pipeline completo."""
    capture = MicrophoneCapture(audio_config)

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
            process_segment(
                stt, parser, searcher, engine, state_mgr, segment, segment_count,
                holyrics_active,
            )

            if timeout_s is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout_s:
                    print(f"\nTimeout de {timeout_s}s atingido. Parando...")
                    capture.stop()
                    break
    except AudioError as e:
        print(f"\nErro de audio: {e}")
        raise
    finally:
        capture.stop()

    elapsed = time.time() - start_time
    _print_summary(stt, capture, engine, segment_count, elapsed)


def _print_summary(
    stt: STT,
    capture: MicrophoneCapture,
    engine: DecisionEngine,
    segment_count: int,
    elapsed_s: float,
) -> None:
    """Imprime resumo final da sessao."""
    cap_metrics = capture.metrics
    stt_metrics = stt.metrics
    dec_metrics = engine.metrics

    print()
    print("=" * 60)
    print("RESUMO DA SESSAO")
    print("=" * 60)
    print(f"  Tempo total: {elapsed_s:.1f}s")
    print(f"  Segmentos processados: {segment_count}")
    print()
    print("Captura:")
    print(f"  Total de chunks: {cap_metrics.total_chunks}")
    print(f"  Chunks de fala: {cap_metrics.speech_chunks}")
    print(f"  Segmentos emitidos: {cap_metrics.segments_emitted}")
    print(f"  Reconexoes: {cap_metrics.reconnect_count}")
    print()
    print("STT:")
    print(f"  Transcricoes: {stt_metrics.total_transcriptions}")
    print(f"  Bem-sucedidas: {stt_metrics.successful}")
    print(f"  Latencia media: {stt_metrics.avg_processing_ms:.0f} ms")
    print(f"  Confianca media: {stt_metrics.avg_confidence:.2f}")
    print(f"  RTF: {stt_metrics.rtf:.2f}")
    print()
    print("Decision:")
    print(f"  Avaliacoes: {dec_metrics.total_evaluations}")
    print(f"  Execute: {dec_metrics.execute}")
    print(f"  Confirm: {dec_metrics.confirm}")
    print(f"  Ignore: {dec_metrics.ignore}")
    print(f"  Forward to LLM: {dec_metrics.forward_to_llm}")
    print(f"  Erros: {dec_metrics.errors}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parsea argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        description=(
            "Diagnostico live pipeline - valida pipeline completo "
            "(Captura + STT + Parser + Search + Decision + Holyrics)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Frases sugeridas para teste (casos obrigatorios):\n"
            "  Referencias diretas:\n"
            '    "Hebreus capitulo 11 versiculo 2"\n'
            '    "Romanos 8 28"\n'
            "  Navegacao:\n"
            '    "proximo"\n'
            '    "mais dois"\n'
            '    "volta um"\n'
            "  Busca textual:\n"
            '    "aquele texto que diz que todas as coisas cooperam para o bem"\n'
            "\n"
            "Exemplos:\n"
            "  python tools/diagnostics/test_live_pipeline.py\n"
            "  python tools/diagnostics/test_live_pipeline.py --device 0\n"
            '  python tools/diagnostics/test_live_pipeline.py --device "Headset USB"\n'
            "  python tools/diagnostics/test_live_pipeline.py --dry-run\n"
            "  python tools/diagnostics/test_live_pipeline.py --model large-v3-turbo --stt-device cuda\n"
            "  python tools/diagnostics/test_live_pipeline.py --timeout 120\n"
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nao chamar Holyrics (apenas simula execucao).",
    )
    return parser.parse_args()


def main() -> int:
    """Entry point do diagnostico live pipeline."""
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
    #    O token pode vir do config.yaml (holyrics.token) OU da variavel
    #    de ambiente HOLYRICS_TOKEN. A env var so e necessaria quando o
    #    config.yaml usa "${HOLYRICS_TOKEN}" (substituicao).
    try:
        if "HOLYRICS_TOKEN" not in os.environ:
            os.environ["HOLYRICS_TOKEN"] = "dummy"
        cfg = load_config(args.config)
    except Exception as e:
        print(f"Erro ao carregar config.yaml: {e}")
        return 1

    # Ativar dry_run automaticamente apenas se:
    #   - --dry-run nao foi informado
    #   - e nenhum token valido foi encontrado (nem config.yaml nem env)
    if not args.dry_run:
        has_yaml_token = bool(cfg.holyrics.token) and cfg.holyrics.token != "dummy"
        has_env_token = bool(os.environ.get("HOLYRICS_TOKEN")) and os.environ.get("HOLYRICS_TOKEN") != "dummy"
        if not has_yaml_token and not has_env_token:
            print("AVISO: nenhum token do Holyrics encontrado.")
            print("  Configure holyrics.token no config.yaml ou sete HOLYRICS_TOKEN.")
            print("  Continuando em modo --dry-run...")
            args.dry_run = True

    # 3. Resolver dispositivo de captura
    device = resolve_device(args.device, cfg.audio)
    print(f"\nDispositivo de captura selecionado: {device}")

    try:
        audio_config = build_audio_config(device, cfg.audio)
        capture = MicrophoneCapture(audio_config)
        capture.find_device(device)
    except AudioError as e:
        print(f"\nErro: {e}")
        print("\nDispositivos disponiveis:")
        for d in devices:
            marker = " (padrao)" if d.is_default else ""
            print(f"  {d.index} - {d.name}{marker}")
        return 1

    # 4. Inicializar modulos
    try:
        parser = init_parser()
    except Exception as e:
        print(f"Erro ao inicializar parser: {e}")
        return 1

    stt_config = build_stt_config(
        cli_model=args.model,
        cli_device=args.stt_device,
        cli_compute_type=args.compute_type,
        config_stt=cfg.stt,
    )

    try:
        stt = init_stt(stt_config)
    except STTError:
        return 1
    except Exception as e:
        print(f"Erro inesperado ao inicializar STT: {e}")
        return 1

    searcher = init_searcher(cfg)

    try:
        state_mgr = init_state_manager(cfg)
    except Exception as e:
        print(f"Erro ao inicializar state manager: {e}")
        return 1

    holyrics = init_holyrics(cfg, args.dry_run)

    engine = init_decision_engine(cfg, state_mgr, holyrics)

    # 5. Loop de captura + pipeline
    try:
        run_live_pipeline(
            audio_config, stt, parser, searcher, engine, state_mgr, args.timeout,
            holyrics is not None,
        )
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
