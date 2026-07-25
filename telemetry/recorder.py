"""Sprint 21.9 — Recorder assíncrono de telemetria em JSON Lines.

Infraestrutura desacoplada para gravação de eventos em arquivos .jsonl.

Características:
- Fila assíncrona (queue.Queue) consumida por thread dedicada.
- Cada evento é uma linha JSON em arquivo .jsonl.
- Um arquivo por sessão (timestamp no nome).
- Thread-safe (vários produtores, um consumidor).
- Pode ser desabilitado via configure_recorder(enabled=False).
- Shutdown gracioso via shutdown_recorder().
- Não lança exceções para o caller (falhas de IO são logadas, não propagadas).

Layout de arquivos:
    <output_dir>/
        session_<timestamp>/
            stt.jsonl
            streaming.jsonl
            parser.jsonl
            sermon_memory.jsonl
            semantic_engine.jsonl
            semantic_prompt.jsonl
            semantic_result.jsonl
            resolver.jsonl
            holyrics.jsonl
            pipeline.jsonl  (eventos genéricos do pipeline)

Cada linha é um JSON object com pelo menos:
    {"timestamp": "...", "event": "...", ...}

Não há acoplamento com componentes do pipeline. O recorder apenas
recebe dicionários e os escreve em disco.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Diretório padrão para gravação (pode ser sobrescrito via configure_recorder).
_DEFAULT_OUTPUT_DIR = os.environ.get(
    "AILYRICS_TELEMETRY_DIR",
    os.path.join(os.path.expanduser("~"), "AI_Lyrics_telemetry"),
)

# Singleton global (configurado uma vez por sessão).
_recorder: "TelemetryRecorder | None" = None
_recorder_lock = threading.Lock()


def _utc_now_iso() -> str:
    """Retorna timestamp UTC em formato ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


class TelemetryRecorder:
    """Recorder assíncrono de telemetria.

    Mantém uma fila de eventos consumida por uma thread dedicada, que
    escreve cada evento em um arquivo .jsonl correspondente à sua
    categoria. Vários produtores podem chamar record() concorrentemente.

    Args:
        output_dir: diretório base para gravação. Será criada uma
            subpasta session_<timestamp> dentro dele.
        enabled: se False, record() é no-op (não enfileira nem escreve).
        queue_maxsize: tamanho máximo da fila. None = ilimitada.
            Recomendado deixar ilimitada para não bloquear o pipeline.
    """

    def __init__(
        self,
        output_dir: str | None = None,
        enabled: bool = True,
        queue_maxsize: int | None = None,
    ) -> None:
        self._enabled = enabled
        self._output_base = Path(output_dir or _DEFAULT_OUTPUT_DIR)
        self._session_dir: Path | None = None
        self._queue: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue(
            maxsize=queue_maxsize if queue_maxsize is not None else 0
        )
        self._worker: threading.Thread | None = None
        self._stopped = threading.Event()
        self._file_handles: dict[str, Any] = {}
        self._files_lock = threading.Lock()
        self._events_written = 0
        self._events_dropped = 0
        self._session_id: str = ""

        if enabled:
            self._start_session()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _start_session(self) -> None:
        """Cria diretório da sessão e inicia a thread consumidora."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_id = timestamp
        self._session_dir = self._output_base / f"session_{timestamp}"
        try:
            self._session_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("TelemetryRecorder: failed to create session dir %s: %s",
                           self._session_dir, e)
            self._enabled = False
            return

        # Iniciar thread consumidora.
        self._worker = threading.Thread(
            target=self._consume_loop,
            name="TelemetryRecorderWorker",
            daemon=True,
        )
        self._worker.start()
        logger.info(
            "TelemetryRecorder: session started at %s (session_id=%s)",
            self._session_dir, self._session_id,
        )

    def stop(self) -> None:
        """Sinaliza parada e aguarda a thread consumidora drenar a fila."""
        if not self._enabled or self._worker is None:
            return
        # Sinal de fim: enfileirar None.
        self._queue.put(None)
        # Aguardar thread consumidora (timeout gracioso de 5s).
        if self._worker.is_alive():
            self._worker.join(timeout=5.0)
        self._stopped.set()
        # Fechar todos os arquivos abertos.
        with self._files_lock:
            for fh in self._file_handles.values():
                try:
                    fh.flush()
                    fh.close()
                except Exception:
                    pass
            self._file_handles.clear()
        logger.info(
            "TelemetryRecorder: session stopped (events_written=%d, events_dropped=%d)",
            self._events_written, self._events_dropped,
        )

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def session_dir(self) -> Path | None:
        return self._session_dir

    def record(self, category: str, payload: dict[str, Any]) -> None:
        """Registra um evento na categoria dada.

        Args:
            category: categoria do evento (ex.: "stt", "semantic_prompt").
                Determina o arquivo .jsonl onde o evento será escrito.
            payload: dicionário com os campos do evento. Será serializado
                como uma linha JSON. Os campos "timestamp" e "event" são
                adicionados automaticamente se não estiverem presentes.

        Não lança exceções. Se a telemetria estiver desabilitada ou a fila
        estiver cheia (apenas se queue_maxsize for finito), o evento é
        descartado silenciosamente.
        """
        if not self._enabled or self._stopped.is_set():
            return
        # Garantir campos obrigatórios.
        event = dict(payload)  # cópia para não mutar o dict do caller
        event.setdefault("timestamp", _utc_now_iso())
        event.setdefault("event", category)
        try:
            self._queue.put_nowait((category, event))
        except queue.Full:
            self._events_dropped += 1
            logger.debug("TelemetryRecorder: queue full, event dropped")
        except Exception as e:
            # Nunca propagar exceções para o pipeline.
            logger.debug("TelemetryRecorder: failed to enqueue event: %s", e)

    # ------------------------------------------------------------------
    # Thread consumidora
    # ------------------------------------------------------------------

    def _consume_loop(self) -> None:
        """Loop principal da thread consumidora."""
        while True:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                if self._stopped.is_set():
                    break
                continue
            if item is None:
                # Sinal de parada.
                break
            category, event = item
            try:
                self._write_event(category, event)
            except Exception as e:
                self._events_dropped += 1
                logger.debug("TelemetryRecorder: failed to write event: %s", e)
            else:
                self._events_written += 1
            self._queue.task_done()

    def _write_event(self, category: str, event: dict[str, Any]) -> None:
        """Escreve um evento no arquivo .jsonl da categoria."""
        if self._session_dir is None:
            return
        # Normalizar nome do arquivo.
        safe_category = self._sanitize_category(category)
        file_path = self._session_dir / f"{safe_category}.jsonl"
        # Reusar handle aberto se existir.
        with self._files_lock:
            fh = self._file_handles.get(safe_category)
            if fh is None or fh.closed:
                fh = open(file_path, "a", encoding="utf-8", buffering=1)
                self._file_handles[safe_category] = fh
        # Serializar e escrever.
        line = json.dumps(event, ensure_ascii=False, default=str)
        fh.write(line + "\n")
        # flush automático via buffering=1 (line-buffered), mas garantir.
        fh.flush()

    @staticmethod
    def _sanitize_category(category: str) -> str:
        """Normaliza o nome da categoria para uso como nome de arquivo."""
        # Permitir apenas alfanuméricos, underscore e hífen.
        safe = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in category)
        if not safe:
            safe = "unknown"
        return safe


# ---------------------------------------------------------------------
# API de módulo (singleton)
# ---------------------------------------------------------------------

def configure_recorder(
    output_dir: str | None = None,
    enabled: bool = True,
    queue_maxsize: int | None = None,
) -> TelemetryRecorder:
    """Configura (ou reconfigura) o recorder global.

    Se já existe um recorder ativo, ele é parado antes de criar o novo.
    """
    global _recorder
    with _recorder_lock:
        if _recorder is not None:
            _recorder.stop()
        _recorder = TelemetryRecorder(
            output_dir=output_dir,
            enabled=enabled,
            queue_maxsize=queue_maxsize,
        )
        return _recorder


def get_recorder() -> TelemetryRecorder | None:
    """Retorna o recorder global, ou None se não configurado."""
    return _recorder


def is_enabled() -> bool:
    """Retorna True se a telemetria está habilitada."""
    r = _recorder
    return r is not None and r.enabled


def record(category: str, payload: dict[str, Any]) -> None:
    """Registra um evento no recorder global.

    No-op se a telemetria não estiver configurada ou habilitada.
    """
    r = _recorder
    if r is None or not r.enabled:
        return
    r.record(category, payload)


def shutdown_recorder() -> None:
    """Encerra o recorder global graciosamente."""
    global _recorder
    with _recorder_lock:
        if _recorder is not None:
            _recorder.stop()
            _recorder = None
