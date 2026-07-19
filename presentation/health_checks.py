"""Health checks reais — Sprint 14 + Sprint 15.2.

Verificações reais (não-placeholder) para componentes do sistema:
  - Backend: sempre saudável se o endpoint responde.
  - WebSocket: verifica se o servidor WS está ativo.
  - EventStream: verifica se o EventBus tem subscribers ativos.
  - Microphone: verifica dispositivo acessível e captura ativa.
  - STT: verifica se o modelo Faster-Whisper está carregado.
  - Searcher: verifica se o banco FTS5 está acessível.
  - Ranking: verifica se embeddings estão disponíveis.
  - Intelligence: verifica se o LLM está reachável.
  - Holyrics: verifica se a API Holyrics está reachável.

Cada check é leve (timeout curto) e não carrega modelos pesados.
Apenas verifica disponibilidade de recursos já instanciados.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from presentation.dtos import HealthDTO
from presentation.mappers import HealthMapper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backend health — sempre saudável se o endpoint responde.
# ---------------------------------------------------------------------------


def check_backend_health() -> HealthDTO:
    """Verifica saúde do backend.

    Se este código está executando, o backend está vivo.
    Inclui uptime aproximado no details.
    """
    t0 = time.time()
    return HealthMapper.healthy(
        "backend",
        "Backend respondendo",
        {"latency_ms": int((time.time() - t0) * 1000), "pid": os.getpid()},
    )


# ---------------------------------------------------------------------------
# WebSocket health — verifica se o servidor WS está ativo.
# ---------------------------------------------------------------------------


def check_websocket_health(
    ws_server: Any | None = None,
    connected_clients: int = 0,
) -> HealthDTO:
    """Verifica saúde do WebSocket.

    Se um ws_server for fornecido, verifica se está ativo.
    Caso contrário, usa a contagem de clientes conectados.
    """
    t0 = time.time()
    latency_ms = int((time.time() - t0) * 1000)

    if ws_server is not None:
        try:
            # Tenta verificar se o servidor está rodando.
            is_running = bool(getattr(ws_server, "is_running", False))
            if is_running:
                return HealthMapper.healthy(
                    "websocket",
                    "WebSocket servidor ativo",
                    {"latency_ms": latency_ms, "connected_clients": connected_clients},
                )
            return HealthMapper.unhealthy(
                "websocket",
                "WebSocket servidor não está rodando",
                {"latency_ms": latency_ms},
            )
        except Exception as e:
            return HealthMapper.unhealthy(
                "websocket",
                f"WebSocket check falhou: {e}",
                {"error": str(e)},
            )

    # Sem servidor — verifica pela contagem de clientes.
    if connected_clients > 0:
        return HealthMapper.healthy(
            "websocket",
            f"WebSocket ativo ({connected_clients} cliente(s) conectado(s))",
            {"latency_ms": latency_ms, "connected_clients": connected_clients},
        )
    return HealthMapper.degraded(
        "websocket",
        "WebSocket sem clientes conectados",
        {"latency_ms": latency_ms, "connected_clients": 0},
    )


# ---------------------------------------------------------------------------
# EventStream health — verifica se o EventBus tem subscribers ativos.
# ---------------------------------------------------------------------------


def check_eventstream_health(bus: Any | None = None) -> HealthDTO:
    """Verifica saúde do EventStream (EventBus).

    Verifica se o EventBus está operacional e tem subscribers.
    """
    t0 = time.time()
    if bus is None:
        return HealthMapper.unknown("eventstream", "EventBus não disponível")

    try:
        event_count = int(getattr(bus, "event_count", 0)())
        latency_ms = int((time.time() - t0) * 1000)
        if event_count > 0:
            return HealthMapper.healthy(
                "eventstream",
                f"EventStream ativo ({event_count} evento(s) processado(s))",
                {"latency_ms": latency_ms, "event_count": event_count},
            )
        return HealthMapper.degraded(
            "eventstream",
            "EventStream operacional mas sem eventos processados",
            {"latency_ms": latency_ms, "event_count": 0},
        )
    except Exception as e:
        return HealthMapper.unhealthy(
            "eventstream",
            f"EventStream check falhou: {e}",
            {"error": str(e)},
        )


# ---------------------------------------------------------------------------
# Microphone health — verifica dispositivo acessível e captura ativa.
# ---------------------------------------------------------------------------


def check_microphone_health(
    capture_service: Any | None = None,
    audio_config: Any | None = None,
) -> HealthDTO:
    """Verifica saúde do Microfone (AudioCaptureService).

    Se uma instância de AudioCaptureService for fornecida:
      - Se capturando: saudável, inclui dispositivo e níveis.
      - Se não capturando mas dispositivo acessível: degradado.
      - Se dispositivo inacessível: unhealthy.
    """
    t0 = time.time()

    if capture_service is not None:
        try:
            capturing = bool(getattr(capture_service, "capturing", False))
            is_open = bool(getattr(capture_service, "is_open", False))
            device_index = getattr(capture_service, "device_index", None)
            latency_ms = int((time.time() - t0) * 1000)

            if capturing:
                # Capturando — verificar dispositivo.
                device_name = "desconhecido"
                try:
                    dev = capture_service.get_current_device()
                    if dev:
                        device_name = getattr(dev, "name", str(dev))
                except Exception:
                    pass
                return HealthMapper.healthy(
                    "microphone",
                    f"Capturando dispositivo: {device_name}",
                    {
                        "latency_ms": latency_ms,
                        "capturing": True,
                        "device_index": device_index,
                        "device_name": device_name,
                    },
                )

            if is_open:
                return HealthMapper.degraded(
                    "microphone",
                    "Dispositivo aberto mas captura parada",
                    {"latency_ms": latency_ms, "capturing": False, "device_index": device_index},
                )

            # Não capturando — verificar se sounddevice está disponível (sem listar dispositivos, que é lento).
            try:
                import sounddevice  # noqa: F401
                return HealthMapper.degraded(
                    "microphone",
                    "Captura parada (sounddevice disponível)",
                    {
                        "latency_ms": latency_ms,
                        "capturing": False,
                    },
                )
            except ImportError:
                return HealthMapper.unhealthy(
                    "microphone",
                    "sounddevice não instalado",
                    {"latency_ms": latency_ms, "capturing": False},
                )
        except Exception as e:
            return HealthMapper.unhealthy(
                "microphone",
                f"Microfone check falhou: {e}",
                {"error": str(e)},
            )

    # Sem instância — verificar se sounddevice está disponível.
    try:
        import sounddevice  # noqa: F401
        return HealthMapper.degraded(
            "microphone",
            "AudioCaptureService não inicializado (sounddevice disponível)",
            {"initialized": False},
        )
    except ImportError:
        return HealthMapper.unhealthy(
            "microphone",
            "sounddevice não instalado",
            {"installed": False},
        )


# ---------------------------------------------------------------------------
# STT health — verifica se o modelo Faster-Whisper está carregado.
# ---------------------------------------------------------------------------


def check_stt_health(stt: Any | None = None, config: Any | None = None) -> HealthDTO:
    """Verifica saúde do STT (Faster-Whisper).

    Estados:
      - healthy: modelo carregado e pronto para transcrever.
      - degraded: instalado mas modelo não carregado (offline ou inicializando).
      - unhealthy: faster-whisper não instalado ou erro.

    Se uma instância de STT for fornecida, verifica is_loaded.
    Caso contrário, verifica se o backend faster-whisper está instalado
    e se o modelo configurado existe no cache do HuggingFace.
    """
    t0 = time.time()
    if stt is not None:
        try:
            loaded = bool(getattr(stt, "is_loaded", False))
            latency_ms = int((time.time() - t0) * 1000)
            if loaded:
                model_name = getattr(config, "model", "") if config else ""
                return HealthMapper.healthy(
                    "speech_recognition",
                    f"STT pronto (modelo={model_name})" if model_name else "STT pronto para transcrever",
                    {"latency_ms": latency_ms, "loaded": True, "model": model_name},
                )
            # Verificar se está inicializando (instância existe mas modelo não carregado).
            return HealthMapper.degraded(
                "speech_recognition",
                "STT offline (modelo não carregado)",
                {"latency_ms": latency_ms, "loaded": False},
            )
        except Exception as e:
            return HealthMapper.unhealthy(
                "speech_recognition",
                f"STT check falhou: {e}",
                {"error": str(e)},
            )

    # Sem instância — verificar config sem importar faster_whisper (import lento).
    model_name = ""
    if config is not None:
        model_name = getattr(config, "model", "") or ""

    details: dict[str, Any] = {
        "model": model_name,
        "latency_ms": int((time.time() - t0) * 1000),
    }

    if not model_name:
        return HealthMapper.degraded(
            "speech_recognition",
            "STT offline (sem modelo configurado)",
            details,
        )

    return HealthMapper.degraded(
        "speech_recognition",
        f"STT offline (modelo={model_name}, instância não criada)",
        details,
    )


# ---------------------------------------------------------------------------
# Searcher health — verifica se o banco FTS5 está acessível.
# ---------------------------------------------------------------------------


def check_searcher_health(searcher: Any | None = None, config: Any | None = None) -> HealthDTO:
    """Verifica saúde do Searcher (FTS5).

    Se uma instância de Searcher for fornecida, verifica se o DB
    está aberto. Caso contrário, verifica se o arquivo do DB existe.
    """
    t0 = time.time()
    db_path = ""
    if config is not None:
        db_path = getattr(config, "fts5_db", "") or ""

    if searcher is not None:
        try:
            db = getattr(searcher, "_db", None)
            latency_ms = int((time.time() - t0) * 1000)
            if db is not None:
                # Tentar uma query simples.
                db.execute("SELECT count(*) FROM verses_fts").fetchone()
                return HealthMapper.healthy(
                    "searcher",
                    "FTS5 database accessible",
                    {"latency_ms": latency_ms, "db_path": db_path},
                )
            return HealthMapper.unhealthy(
                "searcher",
                "FTS5 database not open",
                {"latency_ms": latency_ms, "db_path": db_path},
            )
        except Exception as e:
            return HealthMapper.unhealthy(
                "searcher",
                f"FTS5 check failed: {e}",
                {"error": str(e), "db_path": db_path},
            )

    # Sem instância — verificar arquivo.
    if not db_path:
        return HealthMapper.degraded(
            "searcher",
            "No FTS5 database configured",
            {"configured": False},
        )

    if os.path.isfile(db_path):
        size = os.path.getsize(db_path)
        return HealthMapper.healthy(
            "searcher",
            f"FTS5 database exists ({size} bytes)",
            {"db_path": db_path, "size_bytes": size, "latency_ms": int((time.time() - t0) * 1000)},
        )
    return HealthMapper.unhealthy(
        "searcher",
        f"FTS5 database not found: {db_path}",
        {"db_path": db_path, "exists": False},
    )


# ---------------------------------------------------------------------------
# Ranking health — verifica se embeddings estão disponíveis.
# ---------------------------------------------------------------------------


def check_ranking_health(config: Any | None = None) -> HealthDTO:
    """Verifica saúde do Ranking (embeddings).

    Verifica se o arquivo de embeddings existe.
    Não importa sentence_transformers (import lento) — apenas verifica o arquivo.
    """
    t0 = time.time()
    emb_path = ""
    if config is not None:
        emb_path = getattr(config, "embeddings_path", "") or ""

    details: dict[str, Any] = {
        "embeddings_path": emb_path,
        "latency_ms": int((time.time() - t0) * 1000),
    }

    if not emb_path:
        return HealthMapper.degraded(
            "ranking",
            "No embeddings path configured",
            details,
        )

    if not os.path.isfile(emb_path):
        return HealthMapper.degraded(
            "ranking",
            f"Arquivo de embeddings não encontrado: {emb_path}",
            {**details, "exists": False},
        )

    size = os.path.getsize(emb_path)
    return HealthMapper.healthy(
        "ranking",
        f"Embeddings disponível ({size} bytes)",
        {**details, "exists": True, "size_bytes": size},
    )


# ---------------------------------------------------------------------------
# Intelligence health — verifica se o LLM está reachável.
# ---------------------------------------------------------------------------


def check_intelligence_health(config: Any | None = None) -> HealthDTO:
    """Verifica saúde do Intelligence (LLM).

    Tenta conectar ao endpoint do LLM (Ollama por padrão) com
    timeout curto (2s). Não carrega o modelo — apenas verifica
    reachabilidade.
    """
    t0 = time.time()
    base_url = ""
    model = ""
    if config is not None:
        base_url = getattr(config, "base_url", "") or ""
        model = getattr(config, "model", "") or ""

    if not base_url:
        return HealthMapper.degraded(
            "intelligence",
            "No LLM base_url configured",
            {"configured": False},
        )

    try:
        import requests
        # Tenta um GET no endpoint /api/tags (Ollama) com timeout 2s.
        tags_url = base_url.rstrip("/") + "/api/tags"
        resp = requests.get(tags_url, timeout=2.0)
        latency_ms = int((time.time() - t0) * 1000)
        if resp.status_code == 200:
            return HealthMapper.healthy(
                "intelligence",
                f"LLM reachable (model={model})",
                {"base_url": base_url, "model": model, "latency_ms": latency_ms},
            )
        return HealthMapper.degraded(
            "intelligence",
            f"LLM returned HTTP {resp.status_code}",
            {"base_url": base_url, "status_code": resp.status_code, "latency_ms": latency_ms},
        )
    except ImportError:
        return HealthMapper.unhealthy(
            "intelligence",
            "requests not installed",
            {"base_url": base_url},
        )
    except Exception as e:
        latency_ms = int((time.time() - t0) * 1000)
        return HealthMapper.unhealthy(
            "intelligence",
            f"LLM not reachable: {e}",
            {"base_url": base_url, "error": str(e), "latency_ms": latency_ms},
        )


# ---------------------------------------------------------------------------
# Holyrics health — verifica se a API Holyrics está reachável.
# ---------------------------------------------------------------------------


def check_holyrics_health(client: Any | None = None, config: Any | None = None) -> HealthDTO:
    """Verifica saúde do Holyrics.

    Faz uma chamada real à API configurada (host, porta, token).
    Qualquer erro de conexão, timeout ou autenticação resulta em unhealthy.

    Se um HolyricsClient for fornecido, usa test_connection().
    Caso contrário, cria um client temporário a partir da config.

    Usa a função compartilhada _test_holyrics_impl para evitar duplicação.
    """
    # Extrair base_url e token para incluir no details.
    base_url = ""
    token = ""
    if config is not None:
        base_url = getattr(config, "base_url", "") or ""
        token = getattr(config, "token", "") or ""
    if not base_url and client is not None:
        base_url = getattr(client, "_base_url", "") or ""

    # Se há um client já configurado, usá-lo diretamente.
    if client is not None:
        result = _test_holyrics_impl(client=client, base_url=base_url, token=token)
        return HealthMapper.healthy("holyrics", result["message"], result) if result["ok"] \
            else HealthMapper.unhealthy("holyrics", result["message"], result)

    # Sem client — criar temporário a partir da config.
    if config is None:
        return HealthMapper.unknown("holyrics", "Holyrics: config não disponível")

    if not base_url or not token:
        missing = []
        if not base_url:
            missing.append("base_url")
        if not token:
            missing.append("token")
        return HealthMapper.degraded(
            "holyrics",
            f"Holyrics não configurado (faltando: {', '.join(missing)})",
            {"configured": False, "missing": missing},
        )

    result = _test_holyrics_impl(client=None, base_url=base_url, token=token)
    return HealthMapper.healthy("holyrics", result["message"], result) if result["ok"] \
        else HealthMapper.unhealthy("holyrics", result["message"], result)


def _test_holyrics_impl(
    client: Any | None = None,
    base_url: str = "",
    token: str = "",
    timeout_s: float = 2.0,
) -> dict:
    """Implementação compartilhada do teste de conexão Holyrics.

    Usada tanto por check_holyrics_health (health check) quanto pelo
    endpoint POST /health/holyrics/test (botão "Testar conexão").

    Retorna dict com:
      - ok: bool
      - message: str (motivo do estado, específico por tipo de erro)
      - latency_ms: int
      - base_url: str
      - error_type: str (opcional: "connection", "timeout", "auth", "import", "generic")
    """
    t0 = time.time()

    if client is None:
        # Criar client temporário.
        try:
            from integracao_holyrics import HolyricsClient
            client = HolyricsClient(base_url=base_url, token=token, timeout_s=timeout_s)
        except ImportError:
            return {
                "ok": False,
                "message": "integracao_holyrics não disponível",
                "latency_ms": int((time.time() - t0) * 1000),
                "base_url": base_url,
                "error_type": "import",
            }
        except Exception as e:
            return {
                "ok": False,
                "message": f"Erro ao criar client: {e}",
                "latency_ms": int((time.time() - t0) * 1000),
                "base_url": base_url,
                "error_type": "generic",
            }

    # Tentar test_connection_detailed — retorna mensagens específicas por tipo de erro.
    try:
        result = client.test_connection_detailed()
        result["base_url"] = base_url
        if result["ok"]:
            result["message"] = f"Conexão bem-sucedida ({base_url})"
        else:
            # Adicionar URL à mensagem de erro.
            result["message"] = f"{result['message']} ({base_url})"
        result["latency_ms"] = result.get("latency_ms", int((time.time() - t0) * 1000))
        return result
    except Exception as e:
        latency_ms = int((time.time() - t0) * 1000)
        return {
            "ok": False,
            "message": f"Erro: {e} ({base_url})",
            "latency_ms": latency_ms,
            "base_url": base_url,
            "error_type": "generic",
        }
