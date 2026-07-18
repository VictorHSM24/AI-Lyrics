"""Diagnóstico full pipeline — valida o fluxo COMPLETO com hardware real.

Fluxo validado:
    Microfone → MicrophoneCapture → SpeechSegment → STT → Parser
    → LLM (se uncertain) → Search (se search) → DecisionEngine
    → HolyricsClient → BibleStateManager → Console

Este é o ÚNICO diagnóstico que integra LLM + DecisionEngine + Holyrics
simultaneamente. Os demais diagnósticos permanecem focados em camadas
isoladas:

    test_microphone.py    — Captura + VAD
    test_stt.py           — STT isolado
    test_parser_live.py   — Parser isolado
    test_live_pipeline.py — Pipeline sem LLM (Holyrics real)
    test_llm_live.py      — LLM + Search isolados (sem Holyrics)
    test_full_pipeline.py — Pipeline COMPLETO (este arquivo)

Uso:
    python tools/diagnostics/test_full_pipeline.py
    python tools/diagnostics/test_full_pipeline.py --device 0
    python tools/diagnostics/test_full_pipeline.py --device "Headset USB"
    python tools/diagnostics/test_full_pipeline.py --list-only
    python tools/diagnostics/test_full_pipeline.py --timeout 120
    python tools/diagnostics/test_full_pipeline.py --model large-v3-turbo --stt-device cuda
    python tools/diagnostics/test_full_pipeline.py --no-mic
    python tools/diagnostics/test_full_pipeline.py --text "João 3:16"
    python tools/diagnostics/test_full_pipeline.py --text "tudo posso naquele que me fortalece" --no-mic
    python tools/diagnostics/test_full_pipeline.py --dry-run

Frases sugeridas para teste (casos obrigatórios):
    Referência direta (LLM NÃO deve ser chamado):
      - "João 3:16"
      - "Hebreus 11:1"
      - "próximo"
      - "mais dois"
    Busca semântica (LLM → search → Holyrics):
      - "o texto que diz que todas as coisas cooperam para o bem"
      - "vale da sombra da morte"
      - "tudo posso naquele que me fortalece"
      - "fé é a certeza de coisas que se esperam"
    Não-comando (action=none, nada acontece):
      - "boa noite igreja"
      - "vamos orar"

Regras importantes:
    - Se parser retornar uncertain: chamar LLM.
    - Se LLM retornar search: chamar Searcher.
    - Se LLM retornar show/next/previous/jump: seguir fluxo normal.
    - Se LLM retornar none: encerrar segmento.
    - Se LLM retornar uncertain (anti-loop): converter para none.
    - Se Ollama offline: não bloquear, retornar action="none".
    - Se outcome == "execute": chamar engine.execute() → Holyrics + State.
    - Se outcome == "confirm": imprimir "confirmação necessária".
    - Se outcome == "ignore": imprimir motivo.
    - --dry-run: não chamar Holyrics, mas executar todo o restante.

Restrições:
    - Não modifica código de produção.
    - Não cria novos DTOs nem contratos públicos.
    - Reutiliza exclusivamente módulos existentes.

Requer:
    - sounddevice instalado (se usar microfone).
    - faster-whisper instalado.
    - Microfone físico conectado (se usar microfone).
    - Ollama rodando em http://127.0.0.1:11434 com modelo qwen3:8b-q4_k_m.
    - Holyrics rodando em http://127.0.0.1:3000/api (ou --dry-run).
    - HOLYRICS_TOKEN environment variable (ou --dry-run).
    - config/books.json e data/bible.pt-br.sqlite (FTS5).
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
    print(f"  Versão padrão: {cfg.state.default_version}")
    print("-" * 40)
    return state_mgr


def init_holyrics(cfg, dry_run: bool) -> HolyricsClient | None:
    """Inicializa HolyricsClient e testa conexão."""
    print()
    print("-" * 40)
    print("Inicializando HolyricsClient...")
    if dry_run:
        print("  --dry-run: Holyrics NÃO será chamado")
        print("-" * 40)
        return None
    token = cfg.holyrics.token
    if not token or token == "dummy":
        print("  AVISO: HOLYRICS_TOKEN não configurado")
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
        print("  Testando conexão...")
        if client.test_connection():
            print("  Conexão: OK")
        else:
            print("  Conexão: FALHOU (Holyrics offline ou token inválido)")
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
# Impressão de resultados por stage
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
        print(f"  (transcrição vazia)")
    print(f"  latency_ms={stt_result.processing_ms}")
    print(f"  confidence={stt_result.confidence:.2f}")
    print(f"  language={stt_result.language}")
    print(f"  device={device}")
    print(f"  compute_type={compute_type}")
    print(f"  model={stt._config.model}")
    print()


def _print_parser(intent: Intent, parse_ms: float) -> None:
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
    print(f"  parse_ms={parse_ms:.1f}")
    print()


def _print_llm(llm_intent: Intent, llm_ms: float) -> None:
    """Imprime bloco LLM."""
    print("-" * 40)
    print("LLM:")
    print(f"  action={llm_intent.action}")
    print(f"  confidence={llm_intent.confidence:.2f}")
    print(f"  source={llm_intent.source}")
    print(f"  latency_ms={llm_ms:.1f}")
    if llm_intent.query:
        print(f"  query=\"{llm_intent.query}\"")
    if llm_intent.book:
        print(f"  book={llm_intent.book} chapter={llm_intent.chapter} "
              f"verse={llm_intent.verse}")
    print()


def _print_search(results: list[SearchResult], search_ms: float) -> None:
    """Imprime bloco Search."""
    print("-" * 40)
    print("Search:")
    print(f"  results={len(results)}")
    print(f"  search_ms={search_ms:.1f}")
    if results:
        top = results[0]
        print(f"  resolved={top.reference}")
        print(f"  book={top.book}")
        print(f"  chapter={top.chapter}")
        if top.verse is not None:
            print(f"  verse={top.verse}")
        print(f"  version={top.version}")
        print(f"  confidence={top.c_search:.2f}")
        print(f"  ambiguous={top.ambiguous}")
        print(f"  match_type={top.match_type}")
        if len(results) > 1:
            print(f"  (top-2: {results[1].reference} score={results[1].score:.3f})")
        print()
        print("  Top 5:")
        for i, r in enumerate(results[:5]):
            amb = " [AMBIGUOUS]" if r.ambiguous else ""
            print(f"    {i+1}. {r.reference} (score={r.score:.3f} "
                  f"c_search={r.c_search:.2f}{amb}) [{r.version}]")
            print(f"       \"{r.text[:80]}...\"")
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
        print(f"  c_final={cb.c_final:.2f}")
    print()


def _print_holyrics(ref: VerseRef | None, holyrics_active: bool) -> None:
    """Imprime bloco Holyrics."""
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


def _print_state(state_mgr: BibleStateManager) -> None:
    """Imprime bloco State (estado atual após execução)."""
    print("-" * 40)
    print("State:")
    state = state_mgr.current()
    if state.book_id is not None:
        ref = state_mgr.current_ref()
        print(f"  book_id={state.book_id}")
        print(f"  book={ref.book if ref else '?'}")
        print(f"  chapter={state.chapter}")
        if state.verse is not None:
            print(f"  verse={state.verse}")
        print(f"  version={state.version}")
    else:
        print(f"  (vazio)")
    print()


# ---------------------------------------------------------------------------
# Processamento de texto (pipeline completo)
# ---------------------------------------------------------------------------


def process_text(
    text: str,
    c_stt: float,
    parser: Parser,
    llm_client: LLMClient | None,
    searcher: Searcher | None,
    engine: DecisionEngine,
    state_mgr: BibleStateManager,
    holyrics_active: bool,
) -> None:
    """Processa um texto completo: Parser → LLM → Search → Decision → Holyrics → State."""
    print()
    print("=" * 60)
    print(f"INPUT: \"{text}\" (c_stt={c_stt:.2f})")
    print("=" * 60)

    # 1. Parser
    t0 = time.monotonic()
    intent = parser.parse(text, state_mgr.current())
    parse_ms = (time.monotonic() - t0) * 1000
    _print_parser(intent, parse_ms)

    # 2. LLM (apenas se uncertain)
    if intent.action == "uncertain":
        if llm_client is not None:
            print(">>> Parser retornou uncertain — encaminhando ao LLM...")
            t0 = time.monotonic()
            llm_intent = llm_client.interpret(text, state_mgr.current())
            llm_ms = (time.monotonic() - t0) * 1000
            _print_llm(llm_intent, llm_ms)

            # Anti-loop: se LLM retornar uncertain, converter para none
            if llm_intent.action == "uncertain":
                print("  AVISO: LLM retornou uncertain — convertendo para none")
                llm_intent = Intent(
                    action="none", confidence=llm_intent.confidence,
                    source="llm", raw=text,
                )

            intent = llm_intent
        else:
            print(">>> LLM: Ollama offline — forward_to_llm")
            print()
            print("=" * 60)
            return

    # 3. Search (se action == "search")
    search_results: list[SearchResult] | None = None
    if intent.action == "search" and searcher is not None:
        query = intent.query or text
        print(f">>> Search: buscando \"{query}\"...")
        t0 = time.monotonic()
        try:
            search_results = searcher.search(query, state=state_mgr.current())
        except SearchError as e:
            print(f"  SEARCH ERROR: {e}")
            print()
            print("=" * 60)
            return
        search_ms = (time.monotonic() - t0) * 1000
        _print_search(search_results, search_ms)

        if search_results and search_results[0].ambiguous:
            print("  >>> confirmação necessária (resultado ambíguo)")
            print()
            print("=" * 60)
            return

        if not search_results:
            print("  >>> nenhum resultado encontrado")
            print()
            print("=" * 60)
            return
    elif intent.action == "search" and searcher is None:
        print(">>> Search: searcher não disponível")
        print()
        print("=" * 60)
        return

    # 4. Decision.evaluate
    try:
        decision = engine.evaluate(
            intent,
            c_stt=c_stt,
            search_results=search_results,
        )
    except DecisionError as e:
        print(f"  DECISION ERROR: {e}")
        print()
        print("=" * 60)
        return

    _print_decision(decision)

    # 5. Execute (se outcome == "execute")
    if decision.outcome == "execute":
        try:
            ref = engine.execute(decision, search_results)
            _print_holyrics(ref, holyrics_active)
            _print_state(state_mgr)
        except DecisionError as e:
            print(f"  HOLYRICS ERROR (DecisionError): {e}")
            print()
        except HolyricsError as e:
            print(f"  HOLYRICS ERROR (HolyricsError): {e}")
            print()
    elif decision.outcome == "confirm":
        print(">>> confirmação necessária (outcome=confirm)")
        print()
    elif decision.outcome == "forward_to_llm":
        print(">>> encaminhar para LLM (outcome=forward_to_llm)")
        print()
    elif decision.outcome == "ignore":
        print(f">>> ignorado (outcome=ignore)")
        print(f"    reason: {decision.reason}")
        print()

    print("=" * 60)


# ---------------------------------------------------------------------------
# Processamento de segmento de áudio
# ---------------------------------------------------------------------------


def process_segment(
    segment: SpeechSegment,
    stt: STT,
    parser: Parser,
    llm_client: LLMClient | None,
    searcher: Searcher | None,
    engine: DecisionEngine,
    state_mgr: BibleStateManager,
    holyrics_active: bool,
    count: int,
) -> None:
    """Processa um segmento de áudio: STT → Parser → LLM → Search → Decision → Holyrics."""
    print()
    print("#" * 60)
    print(f"SEGMENTO #{count}")
    print("#" * 60)
    print(f"  duration_ms={segment.duration_ms}")
    print(f"  bytes={len(segment.audio)}")
    print(f"  timestamp={segment.start_time:.3f}")

    # 1. STT
    t0 = time.monotonic()
    try:
        stt_result = stt.transcribe(segment)
    except STTError as e:
        print(f"  STT ERROR: {e}")
        return

    _print_stt(stt_result, stt)

    if not stt_result.text.strip():
        print("  (transcrição vazia — provável silêncio/ruído)")
        return

    # 2-5. Parser → LLM → Search → Decision → Holyrics
    process_text(
        stt_result.text, stt_result.confidence,
        parser, llm_client, searcher, engine, state_mgr, holyrics_active,
    )


# ---------------------------------------------------------------------------
# Modo texto (sem microfone)
# ---------------------------------------------------------------------------


def run_text_mode(
    texts: list[str],
    parser: Parser,
    llm_client: LLMClient | None,
    searcher: Searcher | None,
    engine: DecisionEngine,
    state_mgr: BibleStateManager,
    holyrics_active: bool,
) -> None:
    """Processa uma lista de textos sem usar microfone."""
    print()
    print("#" * 60)
    print("# MODO TEXTO (sem microfone)")
    print("#" * 60)
    for text in texts:
        process_text(
            text, 0.90, parser, llm_client, searcher,
            engine, state_mgr, holyrics_active,
        )


# ---------------------------------------------------------------------------
# Modo microfone
# ---------------------------------------------------------------------------


def run_mic_mode(
    audio_config: AudioConfig,
    stt: STT,
    parser: Parser,
    llm_client: LLMClient | None,
    searcher: Searcher | None,
    engine: DecisionEngine,
    state_mgr: BibleStateManager,
    holyrics_active: bool,
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
                segment, stt, parser, llm_client, searcher,
                engine, state_mgr, holyrics_active, segment_count,
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


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Diagnóstico full pipeline — valida fluxo COMPLETO: "
            "STT → Parser → LLM → Search → Decision → Holyrics → State"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Frases sugeridas para teste:\n"
            "  Referência direta (LLM NÃO chamado):\n"
            '    "João 3:16"\n'
            '    "Hebreus 11:1"\n'
            "  Busca semântica (LLM → search → Holyrics):\n"
            '    "o texto que diz que todas as coisas cooperam para o bem"\n'
            '    "vale da sombra da morte"\n'
            '    "tudo posso naquele que me fortalece"\n'
            "  Não-comando:\n"
            '    "boa noite igreja"\n'
            "\n"
            "Exemplos:\n"
            "  python tools/diagnostics/test_full_pipeline.py --dry-run --no-mic\n"
            "  python tools/diagnostics/test_full_pipeline.py --text 'João 3:16' --no-mic\n"
            "  python tools/diagnostics/test_full_pipeline.py --device 1\n"
            "  python tools/diagnostics/test_full_pipeline.py --dry-run --device 0\n"
        ),
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
                    help="Device STT: cpu | cuda | auto")
    ap.add_argument("--compute-type", type=str, default=None,
                    help="Compute type: int8 | float16 | float32")
    ap.add_argument("--text", type=str, default=None,
                    help="Processar texto fixo em vez de microfone")
    ap.add_argument("--no-mic", action="store_true",
                    help="Não usar microfone (requer --text ou usa lista padrão)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Não chamar Holyrics (apenas simula execução)")
    ap.add_argument("--config", type=str, default="config/config.yaml",
                    help="Caminho para config.yaml")
    args = ap.parse_args()

    # --list-only
    if args.list_only:
        devices = list_devices()
        print_devices(devices)
        return 0

    # Carregar config
    config_path = str(_PROJECT_ROOT / args.config)
    if "HOLYRICS_TOKEN" not in os.environ:
        os.environ["HOLYRICS_TOKEN"] = "dummy"
    try:
        cfg = load_config(config_path)
    except Exception as e:
        print(f"Erro ao carregar config.yaml: {e}")
        return 1

    # Ativar dry_run automaticamente se não houver token válido
    if not args.dry_run:
        has_yaml_token = bool(cfg.holyrics.token) and cfg.holyrics.token != "dummy"
        has_env_token = (
            bool(os.environ.get("HOLYRICS_TOKEN"))
            and os.environ.get("HOLYRICS_TOKEN") != "dummy"
        )
        if not has_yaml_token and not has_env_token:
            print("AVISO: nenhum token do Holyrics encontrado.")
            print("  Configure holyrics.token no config.yaml ou sete HOLYRICS_TOKEN.")
            print("  Continuando em modo --dry-run...")
            args.dry_run = True

    # Inicializar módulos
    try:
        parser = init_parser()
    except Exception as e:
        print(f"Erro ao inicializar parser: {e}")
        return 1

    try:
        state_mgr = init_state_manager(cfg)
    except Exception as e:
        print(f"Erro ao inicializar state manager: {e}")
        return 1

    llm_client = init_llm(cfg)
    searcher = init_searcher(cfg)
    holyrics = init_holyrics(cfg, args.dry_run)

    try:
        engine = init_decision_engine(cfg, state_mgr, holyrics)
    except Exception as e:
        print(f"Erro ao inicializar decision engine: {e}")
        return 1

    holyrics_active = holyrics is not None

    # Modo texto
    if args.no_mic or args.text:
        texts = [args.text] if args.text else [
            "João 3:16",
            "o texto que diz que todas as coisas cooperam para o bem",
            "vale da sombra da morte",
            "tudo posso naquele que me fortalece",
            "fé é a certeza de coisas que se esperam",
            "boa noite igreja",
            "próximo",
            "mais dois",
        ]
        run_text_mode(
            texts, parser, llm_client, searcher,
            engine, state_mgr, holyrics_active,
        )
        if llm_client is not None:
            llm_client.close()
        return 0

    # Modo microfone
    stt_config = build_stt_config(
        args.model, args.stt_device, args.compute_type, cfg.stt,
    )
    try:
        stt = init_stt(stt_config)
    except STTError:
        return 1
    except Exception as e:
        print(f"Erro inesperado ao inicializar STT: {e}")
        return 1

    devices = list_devices()
    print_devices(devices)
    default = find_default(devices)
    device = resolve_device(args.device, cfg.audio)
    audio_config = build_audio_config(device, cfg.audio)

    if default:
        print(f"Dispositivo padrão: {default.name}")
    print(f"Dispositivo selecionado: {device}")

    try:
        run_mic_mode(
            audio_config, stt, parser, llm_client, searcher,
            engine, state_mgr, holyrics_active, args.timeout,
        )
    except AudioError as e:
        print(f"\nErro durante captura: {e}")
        return 1
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
    finally:
        if llm_client is not None:
            llm_client.close()
        try:
            stt.close()
            print("Modelo STT liberado.")
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    sys.exit(main())
