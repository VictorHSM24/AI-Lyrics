"""Testes unitários para config/persistence.py — Sprint 17.5.2.

Garante que valores inválidos NUNCA são persistidos em
config.overrides.json. Isto protege o backend de falhar no restart
após receber um PUT /configuration com valores inválidos do frontend.

Cobre:
- validate_overrides rejeita stt.backend inválido ("whisper").
- validate_overrides rejeita stt.device inválido.
- validate_overrides rejeita stt.compute_type inválido.
- validate_overrides rejeita stt.language inválido.
- validate_overrides rejeita stt.cpu_threads fora de range.
- validate_overrides rejeita stt.beam_size fora de range.
- validate_overrides rejeita audio.chunk_ms inválido.
- validate_overrides rejeita audio.vad_mode fora de range.
- validate_overrides rejeita audio.sample_rate não-positivo.
- validate_overrides rejeita audio.channels != 1 ou 2.
- validate_overrides aceita valores válidos.
- save_overrides NÃO é chamada se validate_overrides retorna erros
  (via ConfigurationPresentationService.update_configuration).
- Round-trip: salvar overrides válido → recarregar → validar.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.persistence import (
    load_overrides,
    merge_overrides,
    save_overrides,
    validate_overrides,
    VALID_STT_BACKENDS,
)


# ============================================================
# validate_overrides — rejeita valores inválidos.
# ============================================================


class TestValidateOverridesSttBackend:
    """Sprint 17.5.2 — stt.backend deve ser válido."""

    def test_rejects_whisper(self) -> None:
        """O valor "whisper" (causa raiz da regressão) deve ser rejeitado."""
        errors = validate_overrides({"stt": {"backend": "whisper"}})
        assert len(errors) == 1
        assert "invalid stt.backend" in errors[0]
        assert "whisper" in errors[0]

    def test_rejects_openai_whisper(self) -> None:
        errors = validate_overrides({"stt": {"backend": "openai-whisper"}})
        assert len(errors) == 1
        assert "invalid stt.backend" in errors[0]

    def test_rejects_empty_string(self) -> None:
        errors = validate_overrides({"stt": {"backend": ""}})
        assert len(errors) == 1
        assert "invalid stt.backend" in errors[0]

    def test_accepts_faster_whisper(self) -> None:
        errors = validate_overrides({"stt": {"backend": "faster-whisper"}})
        assert errors == []

    def test_accepts_absent_backend(self) -> None:
        """Se backend não está nos overrides, não valida (preserva o atual)."""
        errors = validate_overrides({"stt": {"model": "base"}})
        assert errors == []

    def test_all_valid_backends_accepted(self) -> None:
        for b in VALID_STT_BACKENDS:
            assert validate_overrides({"stt": {"backend": b}}) == []


class TestValidateOverridesSttDevice:
    def test_rejects_invalid_device(self) -> None:
        errors = validate_overrides({"stt": {"device": "tpu"}})
        assert len(errors) == 1
        assert "invalid stt.device" in errors[0]

    def test_accepts_cpu(self) -> None:
        assert validate_overrides({"stt": {"device": "cpu"}}) == []

    def test_accepts_cuda(self) -> None:
        assert validate_overrides({"stt": {"device": "cuda"}}) == []

    def test_accepts_auto(self) -> None:
        assert validate_overrides({"stt": {"device": "auto"}}) == []


class TestValidateOverridesSttComputeType:
    def test_rejects_invalid_compute_type(self) -> None:
        errors = validate_overrides({"stt": {"compute_type": "int4"}})
        assert len(errors) == 1
        assert "invalid stt.compute_type" in errors[0]

    def test_accepts_all_valid(self) -> None:
        for ct in ("int8", "int8_float16", "float16", "float32"):
            assert validate_overrides({"stt": {"compute_type": ct}}) == []


class TestValidateOverridesSttLanguage:
    def test_rejects_invalid_language(self) -> None:
        errors = validate_overrides({"stt": {"language": "klingon"}})
        assert len(errors) == 1
        assert "invalid stt.language" in errors[0]

    def test_accepts_pt_br_en_es_auto(self) -> None:
        for lang in ("pt", "en", "es", "auto"):
            assert validate_overrides({"stt": {"language": lang}}) == []


class TestValidateOverridesSttCpuThreads:
    def test_rejects_negative(self) -> None:
        errors = validate_overrides({"stt": {"cpu_threads": -1}})
        assert len(errors) == 1
        assert "out of range" in errors[0]

    def test_rejects_too_high(self) -> None:
        errors = validate_overrides({"stt": {"cpu_threads": 200}})
        assert len(errors) == 1
        assert "out of range" in errors[0]

    def test_rejects_bool(self) -> None:
        """bool é subtipo de int em Python — deve ser rejeitado."""
        errors = validate_overrides({"stt": {"cpu_threads": True}})
        assert len(errors) == 1
        assert "must be int" in errors[0]

    def test_accepts_zero(self) -> None:
        assert validate_overrides({"stt": {"cpu_threads": 0}}) == []

    def test_accepts_positive(self) -> None:
        assert validate_overrides({"stt": {"cpu_threads": 16}}) == []


class TestValidateOverridesSttBeamSize:
    def test_rejects_zero(self) -> None:
        errors = validate_overrides({"stt": {"beam_size": 0}})
        assert len(errors) == 1
        assert "out of range" in errors[0]

    def test_rejects_too_high(self) -> None:
        errors = validate_overrides({"stt": {"beam_size": 100}})
        assert len(errors) == 1
        assert "out of range" in errors[0]

    def test_accepts_valid(self) -> None:
        assert validate_overrides({"stt": {"beam_size": 1}}) == []
        assert validate_overrides({"stt": {"beam_size": 5}}) == []


class TestValidateOverridesAudio:
    def test_rejects_invalid_chunk_ms(self) -> None:
        errors = validate_overrides({"audio": {"chunk_ms": 25}})
        assert len(errors) == 1
        assert "audio.chunk_ms" in errors[0]

    def test_accepts_valid_chunk_ms(self) -> None:
        for v in (10, 20, 30):
            assert validate_overrides({"audio": {"chunk_ms": v}}) == []

    def test_rejects_vad_mode_out_of_range(self) -> None:
        errors = validate_overrides({"audio": {"vad_mode": 5}})
        assert len(errors) == 1
        assert "audio.vad_mode" in errors[0]

    def test_accepts_vad_mode_0_to_3(self) -> None:
        for v in (0, 1, 2, 3):
            assert validate_overrides({"audio": {"vad_mode": v}}) == []

    def test_rejects_non_positive_sample_rate(self) -> None:
        errors = validate_overrides({"audio": {"sample_rate": 0}})
        assert len(errors) == 1
        assert "audio.sample_rate" in errors[0]

    def test_rejects_invalid_channels(self) -> None:
        errors = validate_overrides({"audio": {"channels": 3}})
        assert len(errors) == 1
        assert "audio.channels" in errors[0]

    def test_accepts_mono_and_stereo(self) -> None:
        assert validate_overrides({"audio": {"channels": 1}}) == []
        assert validate_overrides({"audio": {"channels": 2}}) == []


class TestValidateOverridesTopLevel:
    def test_rejects_unknown_key(self) -> None:
        errors = validate_overrides({"unknown_key": 1})
        assert len(errors) == 1
        assert "unknown key" in errors[0]

    def test_rejects_invalid_mode(self) -> None:
        errors = validate_overrides({"mode": "invalid"})
        assert len(errors) == 1
        assert "invalid mode" in errors[0]

    def test_accepts_valid_mode(self) -> None:
        for m in ("auto", "confirm", "quick"):
            assert validate_overrides({"mode": m}) == []

    def test_accepts_empty_overrides(self) -> None:
        assert validate_overrides({}) == []


# ============================================================
# Integração — validate_overrides + save_overrides.
# ============================================================


class TestPersistenceIntegration:
    """Garante que salvar um override inválido NÃO persiste em disco."""

    def test_invalid_backend_not_persisted(self, tmp_path: Path) -> None:
        """Sprint 17.5.2 — Cenário exato da regressão: frontend envia
        "whisper" → backend deve rejeitar antes de salvar em disco."""
        overrides_path = tmp_path / "config.overrides.json"
        overrides = {"stt": {"backend": "whisper"}}

        errors = validate_overrides(overrides)
        assert len(errors) > 0

        # Simula o fluxo de ConfigurationPresentationService.update_configuration:
        # se há erros, NÃO chama save_overrides.
        if not errors:
            save_overrides(overrides, str(overrides_path))

        # Arquivo não deve existir.
        assert not overrides_path.exists()

    def test_valid_backend_persisted(self, tmp_path: Path) -> None:
        overrides_path = tmp_path / "config.overrides.json"
        overrides = {"stt": {"backend": "faster-whisper"}}

        errors = validate_overrides(overrides)
        assert errors == []

        save_overrides(overrides, str(overrides_path))
        assert overrides_path.exists()

        data = json.loads(overrides_path.read_text(encoding="utf-8"))
        assert data["stt"]["backend"] == "faster-whisper"

    def test_round_trip_valid_overrides(self, tmp_path: Path) -> None:
        """Salva overrides válido, recarrega, re-valida → ainda válido."""
        overrides_path = tmp_path / "config.overrides.json"
        overrides = {
            "stt": {
                "backend": "faster-whisper",
                "model": "base",
                "device": "cpu",
                "compute_type": "int8",
                "language": "pt",
                "cpu_threads": 4,
            },
            "audio": {
                "chunk_ms": 30,
                "vad_mode": 3,
                "sample_rate": 16000,
                "channels": 1,
            },
            "mode": "auto",
        }

        errors = validate_overrides(overrides)
        assert errors == []

        save_overrides(overrides, str(overrides_path))

        loaded = load_overrides(str(overrides_path))
        assert loaded == overrides

        # Re-valida o que foi carregado.
        errors2 = validate_overrides(loaded)
        assert errors2 == []

    def test_merge_preserves_valid_existing(self, tmp_path: Path) -> None:
        """Merge não deve corromper valores válidos existentes."""
        base = {"stt": {"backend": "faster-whisper", "model": "base"}}
        new = {"stt": {"cpu_threads": 8}}
        merged = merge_overrides(base, new)
        assert merged["stt"]["backend"] == "faster-whisper"
        assert merged["stt"]["model"] == "base"
        assert merged["stt"]["cpu_threads"] == 8

    def test_merge_overrides_invalid_value_rejected_after_merge(self) -> None:
        """Após merge, validar novamente deve pegar valores inválidos."""
        base = {"stt": {"backend": "faster-whisper"}}
        new = {"stt": {"backend": "whisper"}}
        merged = merge_overrides(base, new)
        errors = validate_overrides(merged)
        assert len(errors) == 1
        assert "invalid stt.backend" in errors[0]


# ============================================================
# Configuração completa — validar todos os campos de uma vez.
# ============================================================


class TestValidateFullSttOverride:
    """Valida um override completo de STT como o frontend envia."""

    def test_full_valid_stt_override(self) -> None:
        """Override completo com todos os campos válidos."""
        overrides = {
            "stt": {
                "backend": "faster-whisper",
                "model": "base",
                "device": "cpu",
                "compute_type": "int8",
                "language": "pt",
                "cpu_threads": 4,
                "beam_size": 1,
            },
        }
        assert validate_overrides(overrides) == []

    def test_full_invalid_stt_override_with_whisper(self) -> None:
        """Override completo mas com backend inválido — deve falhar."""
        overrides = {
            "stt": {
                "backend": "whisper",
                "model": "base",
                "device": "cpu",
                "compute_type": "int8",
                "language": "pt",
                "cpu_threads": 4,
            },
        }
        errors = validate_overrides(overrides)
        assert len(errors) == 1
        assert "invalid stt.backend" in errors[0]
        assert "whisper" in errors[0]

    def test_multiple_errors_reported(self) -> None:
        """Múltiplos campos inválidos → múltiplos erros."""
        overrides = {
            "stt": {
                "backend": "whisper",
                "device": "tpu",
                "compute_type": "int4",
                "language": "klingon",
                "cpu_threads": -1,
            },
        }
        errors = validate_overrides(overrides)
        assert len(errors) == 5


# ============================================================
# Integração — endpoint PUT /configuration rejeita "whisper".
# ============================================================


class TestPutConfigurationEndpointRejectsInvalid:
    """Sprint 17.5.2 — O endpoint PUT /configuration deve rejeitar
    valores inválidos com HTTP 400 ANTES de persistir em disco.

    Isto protege o backend de falhar no restart após receber um
    valor inválido do frontend.
    """

    def test_put_whisper_returns_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cenário exato da regressão: frontend envia "whisper" → 400."""
        from fastapi.testclient import TestClient
        from api.app import create_app
        from api.startup import reset_root, get_root
        from api.websocket import reset_ws_manager

        reset_root()
        reset_ws_manager()
        app = create_app()
        client = TestClient(app)

        # Redireciona o overrides_path da instância para tmp_path para
        # garantir que o teste não escreva no arquivo real.
        import tempfile
        tmp_dir = tempfile.mkdtemp()
        root = get_root()
        root.configuration_service._overrides_path = f"{tmp_dir}/config.overrides.json"

        r = client.put("/configuration", json={"stt": {"backend": "whisper"}})
        assert r.status_code == 400
        assert "invalid stt.backend" in r.json()["detail"]
        # Arquivo não deve ter sido persistido (validação falhou antes de salvar).
        import os
        assert not os.path.isfile(f"{tmp_dir}/config.overrides.json")

    def test_put_faster_whisper_returns_200(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastapi.testclient import TestClient
        from api.app import create_app
        from api.startup import reset_root, get_root
        from api.websocket import reset_ws_manager

        import tempfile, os
        tmp_dir = tempfile.mkdtemp()
        overrides_file = f"{tmp_dir}/config.overrides.json"

        reset_root()
        reset_ws_manager()
        app = create_app()
        client = TestClient(app)
        root = get_root()
        root.configuration_service._overrides_path = overrides_file

        r = client.put("/configuration", json={"stt": {"backend": "faster-whisper"}})
        assert r.status_code == 200
        payload = r.json()["payload"]
        assert payload["stt"]["backend"] == "faster-whisper"
        # Arquivo deve ter sido persistido com valor válido.
        assert os.path.isfile(overrides_file)
        data = json.loads(open(overrides_file, encoding="utf-8").read())
        assert data["stt"]["backend"] == "faster-whisper"

    def test_put_multiple_invalid_fields_returns_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastapi.testclient import TestClient
        from api.app import create_app
        from api.startup import reset_root, get_root
        from api.websocket import reset_ws_manager

        import tempfile, os
        tmp_dir = tempfile.mkdtemp()
        overrides_file = f"{tmp_dir}/config.overrides.json"

        reset_root()
        reset_ws_manager()
        app = create_app()
        client = TestClient(app)
        root = get_root()
        root.configuration_service._overrides_path = overrides_file

        r = client.put("/configuration", json={
            "stt": {
                "backend": "whisper",
                "device": "tpu",
                "compute_type": "int4",
            },
        })
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "invalid stt.backend" in detail
        assert "invalid stt.device" in detail
        assert "invalid stt.compute_type" in detail
        assert not os.path.isfile(overrides_file)
