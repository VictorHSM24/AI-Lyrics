"""PipelineAuditRecorder — gravação sob demanda do resultado do pipeline.

Propósito: auditoria completa de uma execução. Diferente da telemetria
(sempre ligada, categorizada por componente), a gravação de auditoria é
iniciada/parada pelo operador (POST /recording/start|stop) e produz um
pacote auto-contido por sessão de gravação:

    <output_dir>/gravacao_YYYYMMDD_HHMMSS/
        events.jsonl      — TODOS os OperationalEvents do EventBus
                            (wildcard "*"), com meta completo + payload.
        telemetry.jsonl   — TelemetryEvents (alta frequência) separados
                            para não poluir o fluxo operacional.
        errors.jsonl      — eventos de erro (PipelineError,
                            VersePresentationFailed, ReferenceInvalid, ...)
                            + registros de logging nível ERROR+ capturados
                            durante a gravação (ex.: exceções de handlers
                            que o EventBus engole e só loga).
        summary.json      — escrito no stop(): duração, contagens por
                            tipo, lista de erros — o índice da auditoria.

Diretório de saída:
    - Default: ~/Documents/AI-Lyrics/gravacoes (personalizável).
    - Personalização persistida em data/recording_prefs.json (via
      core.paths.writable_path — funciona em dev e em bundle frozen).

Falhas de gravação nunca propagam para o pipeline (mesmo contrato do
TelemetryRecorder): erros de IO são logados, não lançados.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from pipeline.auditing_event_store import AuditingEventStore

logger = logging.getLogger(__name__)

__all__ = ["PipelineAuditRecorder"]

# Eventos que contam como erro na auditoria (nome do tipo contém um
# destes sufixos/marcadores).
_ERROR_MARKERS = ("Error", "Failed", "Invalid", "Unavailable")

# Máximo de erros embutidos no summary.json (o errors.jsonl é completo).
_MAX_ERRORS_IN_SUMMARY = 100

# Nome do arquivo de preferências (diretório de saída persistido).
_PREFS_PATH = "data/recording_prefs.json"


def _utc_iso(ts: float | None = None) -> str:
    """Timestamp ISO 8601 UTC (ou local-aware) para linhas de auditoria."""
    return datetime.fromtimestamp(
        ts if ts is not None else time.time(), tz=timezone.utc,
    ).isoformat()


def _json_default(obj: Any) -> Any:
    """default= do json.dumps: bytes viram marcador de tamanho."""
    if isinstance(obj, (bytes, bytearray)):
        return f"<{len(obj)} bytes>"
    return str(obj)


class _AuditLogHandler(logging.Handler):
    """Handler de logging que grava registros ERROR+ no errors.jsonl.

    Necessário porque o PipelineEventBus captura exceções de handlers e
    apenas as loga (logger.exception) — sem este handler, essas falhas
    ficariam fora do arquivo de auditoria.
    """

    def __init__(self, write_line: Any) -> None:
        super().__init__(level=logging.ERROR)
        self._write_line = write_line

    def emit(self, record: logging.LogRecord) -> None:
        try:
            exc_text = ""
            if record.exc_info:
                exc_text = self.formatException(record.exc_info)
            self._write_line("errors", {
                "_record": "log",
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "exception": exc_text,
                "module": record.module,
                "line": record.lineno,
            })
        except Exception:
            pass  # nunca propagar — auditoria não pode derrubar o pipeline


class PipelineAuditRecorder:
    """Serviço de gravação de auditoria do pipeline.

    Args:
        bus: PipelineEventBus — a inscrição wildcard "*" só é feita
            durante a gravação (start → stop). Fora de uma gravação,
            custo zero.
        output_dir: diretório base inicial. None → lê preferência
            persistida; sem preferência → ~/Documents/AI-Lyrics/gravacoes.
        prefs_path: path do JSON de preferências (override para testes).
    """

    def __init__(
        self,
        bus: Any,
        output_dir: str | None = None,
        prefs_path: str | None = None,
    ) -> None:
        self._bus = bus
        self._lock = threading.Lock()
        self._prefs_path = prefs_path
        self._preferred_dir = output_dir or self._load_preferred_dir()

        # Estado da gravação ativa (None quando parado).
        self._session_dir: Path | None = None
        self._label = ""
        self._started_at: float = 0.0
        self._files: dict[str, TextIO] = {}
        self._seq = 0
        self._events_count = 0
        self._telemetry_count = 0
        self._errors_count = 0
        self._counts_by_type: dict[str, int] = {}
        self._errors: list[dict[str, Any]] = []
        self._last_error = ""
        self._log_handler: _AuditLogHandler | None = None
        self._last_summary: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Diretório de saída (default + preferência persistida)
    # ------------------------------------------------------------------

    @staticmethod
    def default_output_dir() -> Path:
        """Diretório padrão: ~/Documents/AI-Lyrics/gravacoes."""
        return Path.home() / "Documents" / "AI-Lyrics" / "gravacoes"

    @property
    def output_dir(self) -> Path:
        """Diretório base efetivo (preferido ou default)."""
        if self._preferred_dir:
            return Path(self._preferred_dir).expanduser()
        return self.default_output_dir()

    def _resolved_prefs_path(self) -> Path:
        if self._prefs_path:
            return Path(self._prefs_path)
        try:
            from core.paths import writable_path
            return writable_path(_PREFS_PATH)
        except Exception:
            return Path(_PREFS_PATH)

    def _load_preferred_dir(self) -> str:
        try:
            p = self._resolved_prefs_path()
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("output_dir"):
                    return str(data["output_dir"])
        except Exception as e:
            logger.debug("AuditRecorder: falha ao ler preferências: %s", e)
        return ""

    def set_output_dir(self, output_dir: str) -> Path:
        """Define e persiste o diretório base de gravação.

        Valida que o diretório pode ser criado/escrito antes de aceitar.
        Raises:
            ValueError: se o diretório não puder ser criado/escrito.
        """
        if not output_dir or not output_dir.strip():
            raise ValueError("output_dir vazio")
        target = Path(output_dir.strip()).expanduser()
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as e:
            raise ValueError(f"diretório não gravável: {target} ({e})")

        with self._lock:
            self._preferred_dir = str(target)
            try:
                prefs = self._resolved_prefs_path()
                prefs.parent.mkdir(parents=True, exist_ok=True)
                prefs.write_text(
                    json.dumps({"output_dir": str(target)},
                               ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as e:
                logger.warning(
                    "AuditRecorder: diretório salvo em memória mas falha "
                    "ao persistir preferência: %s", e,
                )
        return target

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        return self._session_dir is not None

    def start(self, output_dir: str | None = None, label: str = "") -> Path:
        """Inicia uma gravação de auditoria.

        Args:
            output_dir: override pontual do diretório base (não persiste;
                para persistir usar set_output_dir).
            label: rótulo livre incluído no header e no summary
                (ex.: "culto de domingo").

        Returns:
            Path do diretório da gravação criado.

        Raises:
            RuntimeError: se já está gravando.
            ValueError: se o diretório não puder ser criado/escrito.
        """
        with self._lock:
            if self._session_dir is not None:
                raise RuntimeError(
                    f"gravação já em andamento: {self._session_dir}"
                )
            base = (
                Path(output_dir).expanduser()
                if output_dir and output_dir.strip()
                else self.output_dir
            )
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_dir = base / f"gravacao_{stamp}"
            try:
                session_dir.mkdir(parents=True, exist_ok=False)
            except OSError as e:
                raise ValueError(
                    f"não foi possível criar diretório de gravação "
                    f"{session_dir}: {e}"
                )

            try:
                self._files = {
                    "events": open(
                        session_dir / "events.jsonl", "a",
                        encoding="utf-8", buffering=1,
                    ),
                    "errors": open(
                        session_dir / "errors.jsonl", "a",
                        encoding="utf-8", buffering=1,
                    ),
                    "telemetry": open(
                        session_dir / "telemetry.jsonl", "a",
                        encoding="utf-8", buffering=1,
                    ),
                }
            except OSError as e:
                for fh in self._files.values():
                    try:
                        fh.close()
                    except Exception:
                        pass
                self._files = {}
                raise ValueError(
                    f"não foi possível abrir arquivos em {session_dir}: {e}"
                )

            self._session_dir = session_dir
            self._label = label or ""
            self._started_at = time.time()
            self._seq = 0
            self._events_count = 0
            self._telemetry_count = 0
            self._errors_count = 0
            self._counts_by_type = {}
            self._errors = []
            self._last_error = ""

            # Header — metadados da gravação para contexto da auditoria.
            self._write_line("events", {
                "_record": "header",
                "label": self._label,
                "output_dir": str(base),
                "started_at": _utc_iso(self._started_at),
            })

            # Handler de logging ERROR+ (captura exceções engolidas pelo bus).
            self._log_handler = _AuditLogHandler(self._write_line)
            logging.getLogger().addHandler(self._log_handler)

            # Inscrição wildcard — recebe TODOS os eventos do bus.
            self._bus.subscribe("*", self._on_event)

        logger.info("AuditRecorder: gravação iniciada em %s", session_dir)
        return session_dir

    def stop(self) -> dict[str, Any]:
        """Para a gravação e escreve o summary.json.

        Returns:
            O summary da gravação (dict). Se não estava gravando,
            retorna dict com ok=False.
        """
        with self._lock:
            if self._session_dir is None:
                return {"ok": False, "message": "nenhuma gravação em andamento"}

            session_dir = self._session_dir
            stopped_at = time.time()

            # Desinscrever antes de fechar arquivos.
            try:
                self._bus.unsubscribe("*", self._on_event)
            except Exception:
                pass
            if self._log_handler is not None:
                try:
                    logging.getLogger().removeHandler(self._log_handler)
                except Exception:
                    pass
                self._log_handler = None

            self._write_line("events", {
                "_record": "footer",
                "stopped_at": _utc_iso(stopped_at),
            })

            for fh in self._files.values():
                try:
                    fh.flush()
                    fh.close()
                except Exception:
                    pass
            self._files = {}

            summary = {
                "ok": True,
                "label": self._label,
                "session_dir": str(session_dir),
                "output_dir": str(session_dir.parent),
                "started_at": _utc_iso(self._started_at),
                "started_at_ts": self._started_at,
                "stopped_at": _utc_iso(stopped_at),
                "duration_s": round(stopped_at - self._started_at, 3),
                "events_count": self._events_count,
                "telemetry_count": self._telemetry_count,
                "errors_count": self._errors_count,
                "counts_by_type": dict(
                    sorted(
                        self._counts_by_type.items(),
                        key=lambda kv: -kv[1],
                    )
                ),
                "errors": list(self._errors[:_MAX_ERRORS_IN_SUMMARY]),
                "files": ["events.jsonl", "errors.jsonl",
                          "telemetry.jsonl", "summary.json"],
            }
            try:
                (session_dir / "summary.json").write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2,
                               default=_json_default),
                    encoding="utf-8",
                )
            except OSError as e:
                logger.warning(
                    "AuditRecorder: falha ao escrever summary.json: %s", e,
                )

            self._session_dir = None
            self._last_summary = summary

        logger.info(
            "AuditRecorder: gravação encerrada (%s) — eventos=%d, "
            "telemetria=%d, erros=%d",
            session_dir, summary["events_count"],
            summary["telemetry_count"], summary["errors_count"],
        )
        return summary

    # ------------------------------------------------------------------
    # Status e listagem
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Estado atual do recorder para o endpoint /recording/status."""
        with self._lock:
            return {
                "recording": self.is_recording,
                "label": self._label,
                "output_dir": str(self.output_dir),
                "default_dir": str(self.default_output_dir()),
                "session_dir": (
                    str(self._session_dir) if self._session_dir else None
                ),
                "started_at": self._started_at or None,
                "elapsed_s": (
                    round(time.time() - self._started_at, 1)
                    if self._session_dir else 0.0
                ),
                "events_count": self._events_count,
                "telemetry_count": self._telemetry_count,
                "errors_count": self._errors_count,
                "last_error": self._last_error,
                "last_summary": self._last_summary,
            }

    def list_recordings(self, limit: int = 20) -> list[dict[str, Any]]:
        """Lista gravações anteriores (mais recentes primeiro).

        Lê summary.json de cada diretório gravacao_* quando disponível.
        """
        base = self.output_dir
        entries: list[dict[str, Any]] = []
        if not base.is_dir():
            return entries
        dirs = sorted(
            (d for d in base.iterdir()
             if d.is_dir() and d.name.startswith("gravacao_")),
            key=lambda d: d.name,
            reverse=True,
        )
        for d in dirs[:limit]:
            entry: dict[str, Any] = {
                "name": d.name,
                "path": str(d),
                "started_at": "",
                "duration_s": 0.0,
                "events_count": 0,
                "errors_count": 0,
                "label": "",
                "has_summary": False,
            }
            summary_file = d / "summary.json"
            if summary_file.is_file():
                try:
                    s = json.loads(summary_file.read_text(encoding="utf-8"))
                    entry.update({
                        "started_at": s.get("started_at", ""),
                        "duration_s": s.get("duration_s", 0.0),
                        "events_count": s.get("events_count", 0),
                        "errors_count": s.get("errors_count", 0),
                        "label": s.get("label", ""),
                        "has_summary": True,
                    })
                except (json.JSONDecodeError, OSError):
                    pass
            entries.append(entry)
        return entries

    # ------------------------------------------------------------------
    # Escrita (chamada pelo bus e pelo log handler)
    # ------------------------------------------------------------------

    def _on_event(self, event: Any) -> None:
        """Handler wildcard do EventBus — grava cada evento publicado."""
        try:
            data = AuditingEventStore._serialize(event)
        except Exception:
            data = {"event": type(event).__name__, "payload": {}}
        category = getattr(event, "category", "operational")
        if category not in ("operational", "telemetry"):
            category = "operational"
        is_error = any(m in data.get("event", "") for m in _ERROR_MARKERS)

        line = {
            "seq": 0,  # preenchido dentro do lock
            "iso": _utc_iso(),
            "category": category,
            **data,
        }

        with self._lock:
            if self._session_dir is None:
                return  # evento chegou entre stop() e unsubscribe
            self._seq += 1
            line["seq"] = self._seq
            if category == "telemetry":
                self._telemetry_count += 1
                target = "telemetry"
            else:
                self._events_count += 1
                self._counts_by_type[data["event"]] = (
                    self._counts_by_type.get(data["event"], 0) + 1
                )
                target = "events"
            self._write_line(target, line)
            if is_error:
                self._errors_count += 1
                err_entry = {
                    "seq": self._seq,
                    "iso": line["iso"],
                    "event": data["event"],
                    "message": self._extract_error_message(data),
                }
                self._errors.append(err_entry)
                self._last_error = f"{data['event']}: {err_entry['message']}"
                self._write_line("errors", {
                    "_record": "event_error", **err_entry,
                    "payload": data.get("payload"),
                })

    @staticmethod
    def _extract_error_message(data: dict[str, Any]) -> str:
        payload = data.get("payload") or {}
        if isinstance(payload, dict):
            for key in ("error_message", "message", "reason", "error_type"):
                val = payload.get(key)
                if val:
                    return str(val)
        return ""

    def _write_line(self, kind: str, record: dict[str, Any]) -> None:
        """Escreve uma linha JSON no arquivo da categoria (thread-safe).

        Chamado com self._lock já adquirido pelos caminhos de evento, e
        adquire o lock quando vem do log handler (thread externa).
        """
        fh = self._files.get(kind)
        if fh is None or fh.closed:
            return
        if "iso" not in record:
            record = {"iso": _utc_iso(), **record}
        try:
            fh.write(
                json.dumps(record, ensure_ascii=False,
                           default=_json_default) + "\n"
            )
        except Exception as e:
            logger.debug("AuditRecorder: falha ao gravar linha: %s", e)
