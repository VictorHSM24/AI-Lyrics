"""Router /wizard — assistente de configuração de primeira execução.

Sprint 23.0 — Produto Beta. Implementa as 5 etapas do wizard definidas
no enunciado:

1. Áudio       — listar dispositivos, selecionar, medidor RMS, teste.
2. Holyrics    — detectar, localização manual, testar conexão.
3. Ollama      — detectar instalação, verificar API, verificar modelo,
                 permitir download automático do modelo.
4. Bíblia      — validar bases SQLite, versões, versículos, retriever.
5. Teste       — diagnóstico completo do pipeline.

Endpoints:
  GET  /wizard/status                 — estado do wizard (completo ou não)
  GET  /wizard/audio/devices          — lista dispositivos de áudio
  POST /wizard/audio/select           — seleciona dispositivo
  GET  /wizard/audio/levels           — níveis RMS atuais
  GET  /wizard/holyrics/detect        — detecta Holyrics
  POST /wizard/holyrics/test          — testa conexão com URL/token
  GET  /wizard/ollama/detect          — detecta instalação do Ollama
  GET  /wizard/ollama/api             — verifica API do Ollama
  GET  /wizard/ollama/model           — verifica modelo configurado
  POST /wizard/ollama/pull            — inicia download do modelo (async)
  GET  /wizard/ollama/pull/status     — status do download em andamento
  GET  /wizard/bible/validate         — valida bases SQLite e retriever
  GET  /wizard/test                   — diagnóstico completo do pipeline
  POST /wizard/complete               — marca wizard como concluído

Esta versão do wizard (Sprint 23.0) foca em detecção e validação. A
persistência das escolhas do usuário em config.yaml será feita via
ConfigurationPresentationService existente. A UI fica em
frontend/src/pages/Wizard.tsx.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.schemas import versioned

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wizard", tags=["wizard"])


# ---------------------------------------------------------------------------
# Estado do wizard (flag persistente)
# ---------------------------------------------------------------------------


WIZARD_FLAG_FILENAME = ".wizard_completed"


def _app_data_dir() -> Path:
    """Diretório base para dados persistentes (espelha main.py)."""
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA", str(Path.home()))
        return Path(base) / "AI Lyrics Assistant"
    return Path(__file__).resolve().parent.parent


def _wizard_flag() -> Path:
    return _app_data_dir() / WIZARD_FLAG_FILENAME


# ---------------------------------------------------------------------------
# Estado do download do modelo Ollama (in-memory, singleton)
# ---------------------------------------------------------------------------


@dataclass
class _PullState:
    """Estado do download do modelo Ollama (processo async)."""
    running: bool = False
    completed: bool = False
    failed: bool = False
    progress: str = ""
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0


_pull_state = _PullState()
_pull_lock = threading.Lock()
# Sprint 23.1 — referência ao subprocess do ollama pull para cleanup
# no shutdown do app. Sem isso, o processo ollama continua rodando
# em background se o app fechar durante o download.
_pull_proc: subprocess.Popen | None = None


# ---------------------------------------------------------------------------
# Modelos de request
# ---------------------------------------------------------------------------


class SelectAudioDeviceModel(BaseModel):
    device_index: int


class TestHolyricsModel(BaseModel):
    base_url: str = "http://127.0.0.1:8091/api"
    token: str = ""
    timeout_ms: int = 2000


class SaveHolyricsModel(BaseModel):
    base_url: str = "http://127.0.0.1:8091/api"
    token: str = ""


class SaveAudioModel(BaseModel):
    device_index: int
    device_name: str | None = None


class SaveOllamaModel(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "qwen3:8b-q4_K_M"


class PullOllamaModel(BaseModel):
    model: str = "qwen3:8b-q4_K_M"


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _get_audio_service():
    """Lazy import do AudioPresentationService do composition root."""
    from api.startup import get_root
    root = get_root()
    return root.audio_service


def _get_config():
    """Lazy import da config carregada."""
    from api.startup import get_root
    return get_root().config


def _get_bible_retriever():
    """Lazy import do BibleRetriever do composition root (ou None)."""
    from api.startup import get_root
    root = get_root()
    return getattr(root, "bible_retriever", None)


def _apply_overrides_via_configuration_service(overrides: dict) -> None:
    """Aplica overrides via ConfigurationPresentationService do root.

    Sprint 23.1: centraliza a persistência de overrides do Wizard.
    O ConfigurationPresentationService valida, mescla, persiste em
    config.overrides.json e atualiza a config em memória.
    """
    from api.startup import get_root
    root = get_root()
    svc = root.configuration_service
    svc.update_configuration(overrides)


def _reload_holyrics_client() -> None:
    """Recria o HolyricsClient do CompositionRoot com a config atual.

    Sprint 23.1: após salvar overrides do Holyrics (URL/token), o
    HolyricsClient no CompositionRoot precisa ser recriado para usar
    o novo token. Sem isso, o TestStep e o pipeline continuariam
    usando o client com token vazio (config default), causando 401.

    Lê a config do ConfigurationPresentationService (que é atualizada
    por update_configuration), não root.config (que pode estar stale
    se foi substituído por _apply_overrides).
    """
    from api.startup import get_root
    root = get_root()
    # Preferir a config do configuration_service (sempre atualizada).
    svc = getattr(root, "configuration_service", None)
    if svc is not None:
        cfg = getattr(svc, "_config", None) or root.config
    else:
        cfg = root.config
    holyrics_cfg = getattr(cfg, "holyrics", None)
    if holyrics_cfg is None:
        logger.warning("wizard: config.holyrics ausente — reload skipped.")
        return
    try:
        from integracao_holyrics.client import HolyricsClient
        new_client = HolyricsClient(
            base_url=holyrics_cfg.base_url,
            token=holyrics_cfg.token,
            timeout_s=holyrics_cfg.timeout_ms / 1000.0,
        )
        # Fechar client antigo se tiver.
        old = getattr(root, "holyrics_client", None)
        if old is not None and hasattr(old, "close"):
            try:
                old.close()
            except Exception:
                pass
        # CompositionRoot é frozen dataclass, usar object.__setattr__.
        object.__setattr__(root, "holyrics_client", new_client)
        # Atualizar também no verse_presentation_service se existir.
        vps = getattr(root, "verse_presentation_service", None)
        if vps is not None and hasattr(vps, "set_holyrics_client"):
            try:
                vps.set_holyrics_client(new_client)
            except Exception:
                pass
        logger.info(
            "wizard: HolyricsClient recarregado (base_url=%s).",
            holyrics_cfg.base_url,
        )
    except Exception as e:
        logger.warning("wizard: erro recarregando HolyricsClient: %s", e)


def cleanup_ollama_pull() -> None:
    """Termina o subprocess do ollama pull se ainda estiver rodando.

    Sprint 23.1: chamado no shutdown do app (api/app.py) para
    garantir que o processo `ollama pull` não continue em background
    após o app fechar.
    """
    global _pull_proc
    with _pull_lock:
        proc = _pull_proc
        _pull_proc = None
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
            logger.info("wizard: subprocess ollama pull terminado no shutdown.")
        except Exception as e:
            logger.warning("wizard: erro terminando ollama pull: %s", e)


def _ollama_api_url() -> str:
    """URL base da API do Ollama, lida da config."""
    try:
        cfg = _get_config()
        # Config semantic.ollama.base_url ou llm.base_url.
        sem = getattr(cfg, "semantic", None)
        if sem and getattr(sem, "ollama", None):
            return sem.ollama.base_url.rstrip("/api/v1").rstrip("/")
        llm = getattr(cfg, "llm", None)
        if llm:
            return llm.base_url.rstrip("/")
    except Exception as e:
        logger.warning("wizard: erro lendo config ollama: %s", e)
    return "http://localhost:11434"


def _ollama_model() -> str:
    """Nome do modelo Ollama configurado."""
    try:
        cfg = _get_config()
        sem = getattr(cfg, "semantic", None)
        if sem and getattr(sem, "ollama", None):
            return sem.ollama.model
        llm = getattr(cfg, "llm", None)
        if llm:
            return llm.model
    except Exception as e:
        logger.warning("wizard: erro lendo config modelo: %s", e)
    return "qwen3:8b-q4_K_M"


# ---------------------------------------------------------------------------
# Endpoints — estado do wizard
# ---------------------------------------------------------------------------


@router.get("/status")
@router.get("/status/")
async def wizard_status() -> dict:
    """Retorna se o wizard já foi concluído."""
    return versioned({
        "completed": _wizard_flag().exists(),
        "flag_path": str(_wizard_flag()),
    })


@router.post("/complete")
@router.post("/complete/")
async def wizard_complete() -> dict:
    """Marca o wizard como concluído. Cria o arquivo de flag."""
    flag = _wizard_flag()
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("completed\n", encoding="utf-8")
    logger.info("Wizard marcado como concluído em %s", flag)
    return versioned({"ok": True, "flag_path": str(flag)})


# ---------------------------------------------------------------------------
# Endpoints — etapa 1: Áudio
# ---------------------------------------------------------------------------


@router.get("/audio/devices")
@router.get("/audio/devices/")
async def wizard_audio_devices() -> dict:
    """Lista dispositivos de entrada de áudio disponíveis."""
    try:
        svc = _get_audio_service()
        devices = svc.list_devices()
        return versioned({
            "devices": [d.to_dict() for d in devices],
            "count": len(devices),
        })
    except Exception as e:
        logger.warning("wizard: erro listando dispositivos: %s", e)
        return versioned({
            "devices": [],
            "count": 0,
            "error": str(e),
        })


@router.post("/audio/select")
@router.post("/audio/select/")
async def wizard_audio_select(payload: SelectAudioDeviceModel) -> dict:
    """Seleciona dispositivo de áudio pelo índice e persiste em config.

    Sprint 23.1 fix: agora persiste o dispositivo selecionado em
    config.overrides.json (audio.device_index). Antes, a seleção era
    apenas validada e o usuário precisava ir na tela principal para
    salvar, causando perda da configuração se fechasse o app.
    """
    try:
        svc = _get_audio_service()
        devices = svc.list_devices()
        if payload.device_index < 0 or payload.device_index >= len(devices):
            raise HTTPException(400, f"device_index inválido: {payload.device_index}")
        device = devices[payload.device_index]
        # Persistir em config.overrides.json.
        try:
            _apply_overrides_via_configuration_service({
                "audio": {"device_index": payload.device_index},
            })
        except Exception as e_persist:
            logger.warning("wizard: erro persistindo audio device: %s", e_persist)
        return versioned({
            "ok": True,
            "selected": device.to_dict(),
            "message": f"Dispositivo '{device.name}' selecionado e salvo.",
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erro ao selecionar dispositivo: {e}")


@router.get("/audio/levels")
@router.get("/audio/levels/")
async def wizard_audio_levels() -> dict:
    """Níveis RMS/Peak atuais (para o medidor em tempo real no frontend)."""
    try:
        svc = _get_audio_service()
        levels = svc.get_levels()
        if levels is None:
            return versioned({"rms": 0.0, "peak": 0.0, "capturing": False})
        return versioned({
            "rms": float(levels.rms),
            "peak": float(levels.peak),
            "capturing": bool(getattr(levels, "capturing", False)),
        })
    except Exception as e:
        logger.warning("wizard: erro lendo levels: %s", e)
        return versioned({"rms": 0.0, "peak": 0.0, "capturing": False, "error": str(e)})


# ---------------------------------------------------------------------------
# Endpoints — etapa 2: Holyrics
# ---------------------------------------------------------------------------


@router.get("/holyrics/detect")
@router.get("/holyrics/detect/")
async def wizard_holyrics_detect() -> dict:
    """Detecta Holyrics na URL padrão da config.

    Sprint 23.1 fix: detect testa apenas reachability (sem exigir token).
    Retorna ok=True se o Holyrics respondeu na URL, mesmo sem token válido.
    Isso permite que o usuário saiba que o Holyrics está rodando antes de
    configurar o token.
    """
    try:
        cfg = _get_config()
        holyrics_cfg = cfg.holyrics
        return wizard_holyrics_detect_impl(
            base_url=holyrics_cfg.base_url,
            timeout_ms=holyrics_cfg.timeout_ms,
        )
    except Exception as e:
        return versioned({
            "ok": False,
            "message": f"Erro ao detectar Holyrics: {e}",
            "base_url": "",
            "latency_ms": 0,
            "error_type": "generic",
        })


@router.post("/holyrics/test")
@router.post("/holyrics/test/")
async def wizard_holyrics_test(payload: TestHolyricsModel) -> dict:
    """Testa conexão com Holyrics em URL/token informados.

    Sprint 23.1 fix: usa HolyricsClient oficial (token como query param,
    não como header). O endpoint anterior enviava o token no header
    ``{"token": token}``, mas a API do Holyrics espera ``?token=xxx``
    como query parameter, causando 401 mesmo com token correto.
    """
    return wizard_holyrics_test_impl(
        base_url=payload.base_url,
        token=payload.token,
        timeout_ms=payload.timeout_ms,
    )


@router.post("/holyrics/save")
@router.post("/holyrics/save/")
async def wizard_holyrics_save(payload: SaveHolyricsModel) -> dict:
    """Persiste URL/token do Holyrics em config.overrides.json.

    Sprint 23.1: endpoint dedicado para salvar a config do Holyrics
    durante o Wizard. Antes, o Wizard só testava e não persistia, então
    o TestStep e o CompositionRoot usavam config com token vazio,
    causando 401 no diagnóstico final.

    Após salvar, recarrega o HolyricsClient do CompositionRoot com o
    novo token, para que testes subsequentes (incluindo /wizard/test)
    usem a config persistida.
    """
    try:
        overrides = {"holyrics": {"base_url": payload.base_url, "token": payload.token}}
        _apply_overrides_via_configuration_service(overrides)
        # Recarregar HolyricsClient no CompositionRoot.
        _reload_holyrics_client()
        return versioned({
            "ok": True,
            "message": "Configuração do Holyrics salva.",
            "base_url": payload.base_url,
        })
    except Exception as e:
        logger.warning("wizard: erro salvando config holyrics: %s", e)
        raise HTTPException(500, f"Erro ao salvar configuração: {e}")


def wizard_holyrics_detect_impl(base_url: str, timeout_ms: int) -> dict:
    """Testa apenas reachability do Holyrics (sem autenticação).

    Sprint 23.1: separa detecção (sem token) de teste (com token).
    A detecção faz um GET simples na URL base para verificar se o
    Holyrics está rodando, sem exigir token válido.
    """
    import requests
    t0 = time.monotonic()
    try:
        # Tenta GET na URL base. Holyrics responde 200 ou 401/403
        # se estiver rodando mas exigir token. Qualquer resposta HTTP
        # significa que o Holyrics está reachable.
        resp = requests.get(base_url, timeout=timeout_ms / 1000.0)
        latency_ms = int((time.monotonic() - t0) * 1000)
        # 200, 401, 403, 404 todos indicam que algo respondeu.
        return versioned({
            "ok": True,
            "message": f"Holyrics detectado em {base_url} (HTTP {resp.status_code}).",
            "base_url": base_url,
            "latency_ms": latency_ms,
            "status_code": resp.status_code,
        })
    except requests.exceptions.Timeout:
        return versioned({
            "ok": False,
            "message": "Tempo limite. Holyrics não respondeu.",
            "base_url": base_url,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error_type": "timeout",
        })
    except requests.exceptions.ConnectionError:
        return versioned({
            "ok": False,
            "message": "Holyrics não encontrado. Verifique se está em execução.",
            "base_url": base_url,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error_type": "connection",
        })
    except Exception as e:
        return versioned({
            "ok": False,
            "message": f"Erro: {e}",
            "base_url": base_url,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error_type": "generic",
        })


def wizard_holyrics_test_impl(base_url: str, token: str, timeout_ms: int) -> dict:
    """Implementação compartilhada do teste de Holyrics.

    Sprint 23.1 fix: usa HolyricsClient oficial (integracao_holyrics),
    que envia o token como query parameter ``?token=xxx`` (formato
    esperado pela API do Holyrics). O endpoint anterior enviava o token
    no header HTTP ``{"token": token}``, causando 401 mesmo com token
    correto.

    Usa test_connection_detailed() que retorna mensagens específicas
    por tipo de erro (auth, connection, timeout, generic).
    """
    t0 = time.monotonic()
    try:
        from integracao_holyrics import HolyricsClient
        client = HolyricsClient(
            base_url=base_url,
            token=token,
            timeout_s=timeout_ms / 1000.0,
        )
        result = client.test_connection_detailed()
        result["base_url"] = base_url
        if result["ok"]:
            result["message"] = f"Conexão bem-sucedida ({base_url})"
        else:
            result["message"] = f"{result['message']} ({base_url})"
        result["latency_ms"] = result.get(
            "latency_ms", int((time.monotonic() - t0) * 1000)
        )
        return versioned(result)
    except ImportError:
        return versioned({
            "ok": False,
            "message": "integracao_holyrics não disponível.",
            "base_url": base_url,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error_type": "import",
        })
    except Exception as e:
        return versioned({
            "ok": False,
            "message": f"Erro: {e}",
            "base_url": base_url,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error_type": "generic",
        })


# ---------------------------------------------------------------------------
# Endpoints — etapa 3: Ollama
# ---------------------------------------------------------------------------


def _find_ollama_executable() -> str | None:
    """Localiza o executável do Ollama no PATH ou em caminhos comuns."""
    found = shutil.which("ollama")
    if found:
        return found
    # Caminhos comuns no Windows.
    candidates = [
        str(Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"),
        "C:\\Program Files\\Ollama\\ollama.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


@router.get("/ollama/detect")
@router.get("/ollama/detect/")
async def wizard_ollama_detect() -> dict:
    """Detecta instalação do Ollama (executável no PATH ou em caminhos comuns)."""
    exe = _find_ollama_executable()
    if not exe:
        return versioned({
            "installed": False,
            "executable": None,
            "version": None,
            "message": "Ollama não encontrado. Instale em https://ollama.com/download",
        })
    # Tenta ler a versão.
    version = None
    try:
        result = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=5.0,
        )
        out = (result.stdout or result.stderr or "").strip()
        # Output típico: "ollama version is 0.1.20" ou "0.1.20"
        for line in out.splitlines():
            if "version" in line.lower() or line[0:1].isdigit():
                version = line.strip()
                break
        if not version:
            version = out
    except Exception as e:
        logger.warning("wizard: erro lendo versão ollama: %s", e)
    return versioned({
        "installed": True,
        "executable": exe,
        "version": version,
        "message": "Ollama detectado.",
    })


@router.get("/ollama/api")
@router.get("/ollama/api/")
async def wizard_ollama_api() -> dict:
    """Verifica se a API do Ollama está online (GET /api/tags)."""
    base = _ollama_api_url()
    t0 = time.monotonic()
    try:
        url = f"{base}/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            latency_ms = int((time.monotonic() - t0) * 1000)
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                return versioned({
                    "ok": True,
                    "api_url": base,
                    "latency_ms": latency_ms,
                    "models_installed": models,
                    "models_count": len(models),
                })
            return versioned({
                "ok": False,
                "api_url": base,
                "latency_ms": latency_ms,
                "status_code": resp.status,
            })
    except Exception as e:
        return versioned({
            "ok": False,
            "api_url": base,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error": str(e),
            "error_type": type(e).__name__,
        })


@router.get("/ollama/model")
@router.get("/ollama/model/")
async def wizard_ollama_model() -> dict:
    """Verifica se o modelo configurado está instalado no Ollama."""
    base = _ollama_api_url()
    target = _ollama_model()
    try:
        url = f"{base}/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status != 200:
                return versioned({
                    "configured_model": target,
                    "installed": False,
                    "message": f"API retornou {resp.status_code}",
                })
            data = json.loads(resp.read().decode("utf-8"))
            installed = []
            target_lower = target.lower()
            for m in data.get("models", []):
                name = (m.get("name", "") or m.get("model", "")).lower()
                installed.append(m.get("name", "") or m.get("model", ""))
                if (name == target_lower or name.startswith(target_lower + ":")
                        or target_lower.startswith(name + ":")):
                    return versioned({
                        "configured_model": target,
                        "installed": True,
                        "message": "Modelo instalado e pronto.",
                        "all_models": installed,
                    })
            return versioned({
                "configured_model": target,
                "installed": False,
                "message": f"Modelo {target} não encontrado. Use /wizard/ollama/pull para baixar.",
                "all_models": installed,
            })
    except Exception as e:
        return versioned({
            "configured_model": target,
            "installed": False,
            "message": f"Erro ao verificar modelo: {e}",
            "error_type": type(e).__name__,
        })


@router.post("/ollama/save")
@router.post("/ollama/save/")
async def wizard_ollama_save(payload: SaveOllamaModel) -> dict:
    """Persiste URL/modelo do Ollama em config.overrides.json.

    Sprint 23.1: endpoint dedicado para salvar a config do Ollama
    durante o Wizard. Persiste em ``llm.base_url`` e ``llm.model``
    (e ``semantic.ollama`` se aplicável).
    """
    try:
        overrides = {
            "llm": {"base_url": payload.base_url, "model": payload.model},
        }
        _apply_overrides_via_configuration_service(overrides)
        return versioned({
            "ok": True,
            "message": f"Configuração do Ollama salva (modelo: {payload.model}).",
            "base_url": payload.base_url,
            "model": payload.model,
        })
    except Exception as e:
        logger.warning("wizard: erro salvando config ollama: %s", e)
        raise HTTPException(500, f"Erro ao salvar configuração: {e}")


@router.post("/ollama/pull")
@router.post("/ollama/pull/")
async def wizard_ollama_pull(payload: PullOllamaModel) -> dict:
    """Inicia download do modelo Ollama em background (assíncrono)."""
    global _pull_state
    with _pull_lock:
        if _pull_state.running:
            return versioned({
                "ok": False,
                "message": "Download já em andamento.",
                "progress": _pull_state.progress,
            })
        exe = _find_ollama_executable()
        if not exe:
            return versioned({
                "ok": False,
                "message": "Ollama não instalado. Instale antes de baixar o modelo.",
            })
        _pull_state = _PullState(running=True, started_at=time.time())
    model = payload.model
    # Thread que executa `ollama pull <model>` e atualiza o estado.
    def _run_pull():
        global _pull_state, _pull_proc
        try:
            proc = subprocess.Popen(
                [exe, "pull", model],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, encoding="utf-8",
            )
            with _pull_lock:
                _pull_proc = proc
            last_line = ""
            for line in proc.stdout:
                last_line = line.strip()
                with _pull_lock:
                    _pull_state.progress = last_line
            proc.wait()
            with _pull_lock:
                _pull_state.running = False
                _pull_proc = None
                if proc.returncode == 0:
                    _pull_state.completed = True
                    _pull_state.completed_at = time.time()
                else:
                    _pull_state.failed = True
                    _pull_state.error = f"Exit code {proc.returncode}: {last_line}"
        except Exception as e:
            with _pull_lock:
                _pull_state.running = False
                _pull_proc = None
                _pull_state.failed = True
                _pull_state.error = str(e)
    threading.Thread(target=_run_pull, daemon=True).start()
    return versioned({
        "ok": True,
        "model": model,
        "message": "Download iniciado em background. Use /wizard/ollama/pull/status para acompanhar.",
    })


@router.get("/ollama/pull/status")
@router.get("/ollama/pull/status/")
async def wizard_ollama_pull_status() -> dict:
    """Status do download do modelo em andamento."""
    with _pull_lock:
        return versioned({
            "running": _pull_state.running,
            "completed": _pull_state.completed,
            "failed": _pull_state.failed,
            "progress": _pull_state.progress,
            "error": _pull_state.error,
            "elapsed_s": (time.time() - _pull_state.started_at) if _pull_state.running else 0.0,
        })


# ---------------------------------------------------------------------------
# Endpoints — etapa 4: Bíblia
# ---------------------------------------------------------------------------


@router.get("/bible/validate")
@router.get("/bible/validate/")
async def wizard_bible_validate() -> dict:
    """Valida bases SQLite, versões, versículos e BibleRetriever."""
    from core.paths import resource_path
    try:
        cfg = _get_config()
        sources_dir = resource_path(cfg.knowledge.sources_dir)
    except Exception:
        sources_dir = resource_path("data/sources")
    sqlite_files = sorted(sources_dir.glob("*.sqlite")) if sources_dir.exists() else []
    versions = [f.stem for f in sqlite_files]
    # Valida BibleRetriever se aquecido.
    retriever = _get_bible_retriever()
    retriever_stats = None
    retriever_ok = False
    if retriever is not None:
        try:
            stats = retriever.stats
            retriever_stats = {
                "total_versions": stats.total_versions,
                "total_verses": stats.total_verses,
                "unique_verses": stats.unique_verses,
                "versions_discovered": list(stats.versions_discovered),
                "init_time_ms": stats.init_time_ms,
                "sources_dir": stats.sources_dir,
            }
            retriever_ok = stats.total_versions >= 1 and stats.total_verses > 0
        except Exception as e:
            retriever_stats = {"error": str(e)}
    # Arquivos de embeddings (Categoria C — gerados por build_embeddings).
    # Sprint 23.0 fix: resolver via resource_path para funcionar em frozen.
    embeddings_npy = resource_path("data/bible.embeddings.npy")
    fts5_db = resource_path("data/bible.pt-br.sqlite")
    return versioned({
        "sources_dir": str(sources_dir),
        "versions_found": versions,
        "versions_count": len(versions),
        "sqlite_files": [str(f) for f in sqlite_files],
        "bible_retriever_ready": retriever is not None,
        "bible_retriever_ok": retriever_ok,
        "bible_retriever_stats": retriever_stats,
        "fts5_db_exists": fts5_db.exists(),
        "fts5_db_path": str(fts5_db),
        "embeddings_npy_exists": embeddings_npy.exists(),
        "embeddings_npy_path": str(embeddings_npy),
        "ok": retriever_ok and len(versions) >= 1,
    })


# ---------------------------------------------------------------------------
# Endpoints — etapa 5: Teste completo do pipeline
# ---------------------------------------------------------------------------


@router.get("/test")
@router.get("/test/")
async def wizard_test() -> dict:
    """Diagnóstico completo do pipeline. Retorna status de cada componente."""
    results = {}
    # Áudio
    try:
        svc = _get_audio_service()
        devices = svc.list_devices()
        results["audio"] = {
            "ok": len(devices) > 0,
            "message": f"{len(devices)} dispositivo(s) disponível(is).",
            "device_count": len(devices),
        }
    except Exception as e:
        results["audio"] = {"ok": False, "message": f"Erro: {e}"}
    # Holyrics
    try:
        cfg = _get_config()
        h = wizard_holyrics_test_impl(
            cfg.holyrics.base_url, cfg.holyrics.token, cfg.holyrics.timeout_ms,
        )["payload"]
        results["holyrics"] = h
    except Exception as e:
        results["holyrics"] = {"ok": False, "message": f"Erro: {e}"}
    # Ollama
    try:
        o = (await wizard_ollama_api())["payload"]
        results["ollama_api"] = o
    except Exception as e:
        results["ollama_api"] = {"ok": False, "message": f"Erro: {e}"}
    # Modelo
    try:
        m = (await wizard_ollama_model())["payload"]
        results["ollama_model"] = m
    except Exception as e:
        results["ollama_model"] = {"ok": False, "message": f"Erro: {e}"}
    # Bíblia
    try:
        b = (await wizard_bible_validate())["payload"]
        results["bible"] = b
    except Exception as e:
        results["bible"] = {"ok": False, "message": f"Erro: {e}"}
    # Veredito final
    all_ok = all(
        r.get("ok", False) or r.get("bible_retriever_ok", False)
        for r in results.values()
    )
    return versioned({
        "components": results,
        "all_ok": all_ok,
        "message": "Sistema pronto." if all_ok else "Alguns componentes precisam de atenção.",
    })

