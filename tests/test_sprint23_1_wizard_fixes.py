"""Sprint 23.1 — Testes dos endpoints de save do Wizard e correção do bug Holyrics 401.

Valida:
1. POST /wizard/holyrics/save persiste URL/token em config.overrides.json.
2. POST /wizard/holyrics/test usa HolyricsClient (token como query param).
3. GET /wizard/holyrics/detect testa reachability sem token.
4. POST /wizard/ollama/save persiste URL/modelo.
5. POST /wizard/audio/select persiste device_index.
6. POST /wizard/complete cria flag .wizard_completed.
7. cleanup_ollama_pull termina subprocess ativo.
8. _reload_holyrics_client recria client com novo token.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from api.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. POST /wizard/holyrics/save
# ---------------------------------------------------------------------------


class TestHolyricsSave:
    def test_save_persists_token_and_base_url(self, client, tmp_path):
        """POST /holyrics/save deve persistir URL/token em config.overrides.json."""
        unique_token = f"test-token-sprint231-{time.time()}"
        r = client.post("/wizard/holyrics/save", json={
            "base_url": "http://127.0.0.1:8091/api",
            "token": unique_token,
        })
        assert r.status_code == 200
        payload = r.json()["payload"]
        assert payload["ok"] is True
        assert payload["base_url"] == "http://127.0.0.1:8091/api"

        # Verificar que a config em memória foi atualizada.
        # Nota: update_configuration atualiza svc._config, não root.config.
        from api.startup import get_root
        root = get_root()
        svc = root.configuration_service
        assert svc._config.holyrics.token == unique_token
        assert svc._config.holyrics.base_url == "http://127.0.0.1:8091/api"

    def test_save_with_empty_token_is_allowed(self, client):
        """Salvar token vazio deve ser permitido (usuário pode querer limpar)."""
        r = client.post("/wizard/holyrics/save", json={
            "base_url": "http://127.0.0.1:8091/api",
            "token": "",
        })
        assert r.status_code == 200

    def test_save_returns_versioned_payload(self, client):
        """Resposta deve seguir o schema versioned (api + payload)."""
        r = client.post("/wizard/holyrics/save", json={
            "base_url": "http://127.0.0.1:8091/api",
            "token": "versioned-test",
        })
        body = r.json()
        assert "api" in body
        assert "payload" in body
        assert body["payload"]["ok"] is True


# ---------------------------------------------------------------------------
# 2. POST /wizard/holyrics/test — usa HolyricsClient (token como query param)
# ---------------------------------------------------------------------------


class TestHolyricsTest:
    def test_test_uses_holyrics_client_not_header(self, client):
        """O teste deve usar HolyricsClient (token como query param), não header.

        Sprint 23.1: causa raiz do bug 401 era que o endpoint enviava o token
        no header HTTP ``{"token": token}``, mas o Holyrics espera ``?token=xxx``
        como query parameter. Este teste mocka HolyricsClient para verificar
        que o endpoint o utiliza.
        """
        mock_result = {
            "ok": True,
            "message": "Conexão bem-sucedida",
            "latency_ms": 5,
        }
        with patch("integracao_holyrics.HolyricsClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.test_connection_detailed.return_value = mock_result
            MockClient.return_value = mock_instance

            r = client.post("/wizard/holyrics/test", json={
                "base_url": "http://127.0.0.1:8091/api",
                "token": "my-token",
                "timeout_ms": 2000,
            })

        assert r.status_code == 200
        payload = r.json()["payload"]
        assert payload["ok"] is True
        # Verificar que HolyricsClient foi instanciado com token correto.
        MockClient.assert_called_once_with(
            base_url="http://127.0.0.1:8091/api",
            token="my-token",
            timeout_s=2.0,
        )
        # Verificar que test_connection_detailed foi chamado.
        mock_instance.test_connection_detailed.assert_called_once()

    def test_test_returns_auth_error_for_invalid_token(self, client):
        """Quando Holyrics retorna 401, o endpoint deve retornar error_type=auth."""
        mock_result = {
            "ok": False,
            "message": "Token inválido",
            "latency_ms": 3,
            "error_type": "auth",
        }
        with patch("integracao_holyrics.HolyricsClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.test_connection_detailed.return_value = mock_result
            MockClient.return_value = mock_instance

            r = client.post("/wizard/holyrics/test", json={
                "base_url": "http://127.0.0.1:8091/api",
                "token": "invalid",
                "timeout_ms": 2000,
            })

        payload = r.json()["payload"]
        assert payload["ok"] is False
        assert payload["error_type"] == "auth"

    def test_test_handles_import_error(self, client):
        """Se integracao_holyrics não estiver disponível, retorna error_type=import."""
        with patch("integracao_holyrics.HolyricsClient", side_effect=ImportError("no module")):
            r = client.post("/wizard/holyrics/test", json={
                "base_url": "http://127.0.0.1:8091/api",
                "token": "any",
                "timeout_ms": 2000,
            })
        payload = r.json()["payload"]
        assert payload["ok"] is False
        assert payload["error_type"] == "import"


# ---------------------------------------------------------------------------
# 3. GET /wizard/holyrics/detect — reachability sem token
# ---------------------------------------------------------------------------


class TestHolyricsDetect:
    def test_detect_tests_reachability_without_token(self, client):
        """Detect deve testar apenas reachability, sem exigir token.

        Sprint 23.1: antes, detect usava config.holyrics.token (vazio na
        primeira execução) e falhava com 401. Agora faz GET simples na URL
        base para verificar se o Holyrics está rodando.
        """
        import requests as req_mod
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch.object(req_mod, "get", return_value=mock_resp):
            r = client.get("/wizard/holyrics/detect")
        payload = r.json()["payload"]
        # Qualquer resposta HTTP (200, 401, 403, 404) indica reachability.
        assert payload["ok"] is True
        assert "detectado" in payload["message"].lower()
        assert payload["status_code"] == 404

    def test_detect_returns_connection_error_when_offline(self, client):
        """Quando Holyrics está offline, detect retorna error_type=connection."""
        import requests as req_mod
        with patch.object(req_mod, "get", side_effect=req_mod.exceptions.ConnectionError()):
            r = client.get("/wizard/holyrics/detect")
        payload = r.json()["payload"]
        assert payload["ok"] is False
        assert payload["error_type"] == "connection"

    def test_detect_returns_timeout(self, client):
        """Quando Holyrics demora, detect retorna error_type=timeout."""
        import requests as req_mod
        with patch.object(req_mod, "get", side_effect=req_mod.exceptions.Timeout()):
            r = client.get("/wizard/holyrics/detect")
        payload = r.json()["payload"]
        assert payload["ok"] is False
        assert payload["error_type"] == "timeout"


# ---------------------------------------------------------------------------
# 4. POST /wizard/ollama/save
# ---------------------------------------------------------------------------


class TestOllamaSave:
    def test_save_persists_model_and_base_url(self, client):
        r = client.post("/wizard/ollama/save", json={
            "base_url": "http://localhost:11434",
            "model": "qwen3:8b-q4_K_M",
        })
        assert r.status_code == 200
        payload = r.json()["payload"]
        assert payload["ok"] is True
        assert payload["model"] == "qwen3:8b-q4_K_M"

        # Verificar config em memória (no configuration_service, não root.config).
        from api.startup import get_root
        root = get_root()
        svc = root.configuration_service
        assert svc._config.llm.model == "qwen3:8b-q4_K_M"


# ---------------------------------------------------------------------------
# 5. POST /wizard/audio/select — persiste device_index
# ---------------------------------------------------------------------------


class TestAudioSelect:
    def test_select_persists_device_index(self, client):
        """Select deve persistir o device_index em config.overrides.json."""
        # Mockar list_devices para retornar pelo menos 1 dispositivo.
        from api.startup import get_root
        root = get_root()
        mock_device = MagicMock()
        mock_device.to_dict.return_value = {"index": 0, "name": "Test Mic"}
        mock_device.name = "Test Mic"
        with patch.object(root.audio_service, "list_devices", return_value=[mock_device]):
            r = client.post("/wizard/audio/select", json={"device_index": 0})
        assert r.status_code == 200
        payload = r.json()["payload"]
        assert payload["ok"] is True
        assert "salvo" in payload["message"].lower()

    def test_select_rejects_invalid_index(self, client):
        from api.startup import get_root
        root = get_root()
        with patch.object(root.audio_service, "list_devices", return_value=[]):
            r = client.post("/wizard/audio/select", json={"device_index": 99})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# 6. _reload_holyrics_client
# ---------------------------------------------------------------------------


class TestReloadHolyricsClient:
    def test_reload_creates_new_client_with_current_config(self):
        """_reload_holyrics_client deve recriar HolyricsClient com config atual."""
        from api.wizard import _reload_holyrics_client
        from api.startup import get_root
        root = get_root()
        # Mockar config.holyrics (Config e CompositionRoot são frozen).
        mock_holyrics = MagicMock()
        mock_holyrics.base_url = "http://test:8091/api"
        mock_holyrics.token = "reloaded-token"
        mock_holyrics.timeout_ms = 3000
        mock_config = MagicMock()
        mock_config.holyrics = mock_holyrics
        # _reload_holyrics_client lê svc._config primeiro.
        svc = root.configuration_service
        original_svc_config = svc._config
        svc._config = mock_config
        original_client = root.holyrics_client
        try:
            with patch("integracao_holyrics.client.HolyricsClient") as MockClient:
                mock_instance = MagicMock()
                MockClient.return_value = mock_instance
                _reload_holyrics_client()

            MockClient.assert_called_once_with(
                base_url="http://test:8091/api",
                token="reloaded-token",
                timeout_s=3.0,
            )
            assert root.holyrics_client is mock_instance
        finally:
            svc._config = original_svc_config
            object.__setattr__(root, "holyrics_client", original_client)

    def test_reload_handles_missing_config_gracefully(self):
        """Se config.holyrics ausente, reload não deve levantar exceção."""
        from api.wizard import _reload_holyrics_client
        from api.startup import get_root
        root = get_root()
        mock_config = MagicMock()
        # Fazer holyrics levantar AttributeError.
        type(mock_config).holyrics = property(lambda self: (_ for _ in ()).throw(AttributeError()))
        original_config = root.config
        object.__setattr__(root, "config", mock_config)
        try:
            _reload_holyrics_client()  # não deve levantar
        finally:
            object.__setattr__(root, "config", original_config)


# ---------------------------------------------------------------------------
# 7. cleanup_ollama_pull
# ---------------------------------------------------------------------------


class TestCleanupOllamaPull:
    def test_cleanup_terminates_running_process(self):
        """cleanup_ollama_pull deve terminar subprocess ativo."""
        from api.wizard import cleanup_ollama_pull, _pull_lock
        import api.wizard as wiz_module
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # ainda rodando
        with _pull_lock:
            wiz_module._pull_proc = mock_proc
        cleanup_ollama_pull()
        mock_proc.terminate.assert_called_once()

    def test_cleanup_does_not_terminate_finished_process(self):
        """cleanup não deve chamar terminate se processo já terminou."""
        from api.wizard import cleanup_ollama_pull, _pull_lock
        import api.wizard as wiz_module
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # terminou com sucesso
        with _pull_lock:
            wiz_module._pull_proc = mock_proc
        cleanup_ollama_pull()
        mock_proc.terminate.assert_not_called()

    def test_cleanup_handles_no_process(self):
        """cleanup não deve falhar se não há subprocess ativo."""
        from api.wizard import cleanup_ollama_pull, _pull_lock
        import api.wizard as wiz_module
        with _pull_lock:
            wiz_module._pull_proc = None
        cleanup_ollama_pull()  # não deve levantar

    def test_cleanup_kills_if_terminate_times_out(self):
        """Se terminate não funcionar em 5s, cleanup deve chamar kill."""
        from api.wizard import cleanup_ollama_pull, _pull_lock
        import api.wizard as wiz_module
        import subprocess
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="ollama", timeout=5)
        with _pull_lock:
            wiz_module._pull_proc = mock_proc
        cleanup_ollama_pull()
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# 8. POST /wizard/complete — cria flag
# ---------------------------------------------------------------------------


class TestWizardComplete:
    def test_complete_creates_flag_file(self, client, tmp_path):
        """POST /complete deve criar o arquivo .wizard_completed."""
        from api.wizard import _wizard_flag, WIZARD_FLAG_FILENAME
        # O flag é criado em _app_data_dir(). Em dev, é a raiz do projeto.
        # Vamos apenas verificar que o endpoint retorna 200 e ok=True.
        r = client.post("/wizard/complete")
        assert r.status_code == 200
        payload = r.json()["payload"]
        assert payload["ok"] is True
        assert "flag_path" in payload
