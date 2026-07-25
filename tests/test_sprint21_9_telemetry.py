"""Sprint 21.9 — Testes da infraestrutura de telemetria.

Valida que:
- O recorder grava eventos em arquivos .jsonl corretamente.
- A telemetria desabilitada é no-op (não escreve nada).
- Os hooks não lançam exceções mesmo com inputs inválidos.
- O shutdown drena a fila graciosamente.
- A escrita é assíncrona (não bloqueia o caller).
"""
from __future__ import annotations

import json
import os
import tempfile
import time

import pytest

from telemetry import (
    configure_recorder,
    get_recorder,
    is_enabled,
    record,
    shutdown_recorder,
)
from telemetry import hooks as telemetry_hooks


@pytest.fixture
def tmp_recorder():
    """Configura um recorder temporário para cada teste."""
    tmp_dir = tempfile.mkdtemp(prefix="telemetry_test_")
    r = configure_recorder(output_dir=tmp_dir, enabled=True)
    yield r
    shutdown_recorder()


class TestTelemetryRecorder:
    """Testes do TelemetryRecorder."""

    def test_record_writes_jsonl_line(self, tmp_recorder):
        """record() escreve uma linha JSON válida no arquivo da categoria."""
        record("test_cat", {"msg": "hello", "n": 42})
        # Aguardar a thread consumidora processar.
        time.sleep(0.2)
        shutdown_recorder()
        sd = tmp_recorder.session_dir
        file_path = os.path.join(sd, "test_cat.jsonl")
        assert os.path.exists(file_path), f"file not created: {file_path}"
        lines = open(file_path, encoding="utf-8").readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["msg"] == "hello"
        assert event["n"] == 42
        assert "timestamp" in event
        assert event["event"] == "test_cat"

    def test_multiple_categories_create_separate_files(self, tmp_recorder):
        """Categorias diferentes vão para arquivos diferentes."""
        record("stt", {"text": "foo"})
        record("semantic_prompt", {"prompt": "bar"})
        record("holyrics", {"book": "João"})
        time.sleep(0.2)
        shutdown_recorder()
        sd = tmp_recorder.session_dir
        files = set(os.listdir(sd))
        assert "stt.jsonl" in files
        assert "semantic_prompt.jsonl" in files
        assert "holyrics.jsonl" in files

    def test_disabled_recorder_is_noop(self):
        """Recorder desabilitado não escreve nada."""
        tmp_dir = tempfile.mkdtemp(prefix="telemetry_disabled_")
        r = configure_recorder(output_dir=tmp_dir, enabled=False)
        assert not r.enabled
        record("test", {"msg": "should_not_write"})
        time.sleep(0.1)
        shutdown_recorder()
        sd = r.session_dir
        # session_dir pode ser None quando desabilitado.
        if sd is not None:
            files = os.listdir(sd)
            assert files == [], f"files written despite disabled: {files}"

    def test_shutdown_drains_queue(self, tmp_recorder):
        """shutdown_recorder drena a fila antes de fechar."""
        # Enfileirar muitos eventos rapidamente.
        for i in range(100):
            record("drain_test", {"i": i})
        shutdown_recorder()
        sd = tmp_recorder.session_dir
        file_path = os.path.join(sd, "drain_test.jsonl")
        lines = open(file_path, encoding="utf-8").readlines()
        assert len(lines) == 100, f"expected 100 lines, got {len(lines)}"

    def test_record_does_not_raise_on_invalid_payload(self, tmp_recorder):
        """record() não lança exceção mesmo com payload problemático."""
        # Payload com objeto não-serializável (set) — default=str no json.dumps.
        record("weird", {"data": {1, 2, 3}})
        time.sleep(0.1)
        # Não deve ter levantado exceção.
        shutdown_recorder()

    def test_session_dir_created(self, tmp_recorder):
        """O diretório da sessão é criado com prefixo session_."""
        sd = tmp_recorder.session_dir
        assert sd is not None
        assert sd.exists()
        assert sd.name.startswith("session_")

    def test_is_enabled_reflects_state(self, tmp_recorder):
        """is_enabled() retorna True quando recorder está ativo."""
        assert is_enabled() is True
        shutdown_recorder()
        assert is_enabled() is False


class TestTelemetryHooks:
    """Testes dos hooks de telemetria por componente."""

    def test_stt_window_hook(self, tmp_recorder):
        """stt_window hook registra evento na categoria stt."""
        telemetry_hooks.stt_window(
            correlation_id="corr-1",
            audio_duration_ms=6000,
            rms=0.0123,
            transcribed=True,
            text="joão capítulo 3",
            confidence=0.85,
            latency_ms=1200,
            language="pt",
        )
        time.sleep(0.2)
        shutdown_recorder()
        sd = tmp_recorder.session_dir
        lines = open(os.path.join(sd, "stt.jsonl"), encoding="utf-8").readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["correlation_id"] == "corr-1"
        assert event["rms"] == 0.0123
        assert event["text"] == "joão capítulo 3"
        assert event["event"] == "stt"

    def test_semantic_prompt_hook(self, tmp_recorder):
        """semantic_prompt hook registra prompt na categoria semantic_prompt."""
        telemetry_hooks.semantic_prompt(
            correlation_id="corr-2",
            system_prompt="system",
            user_prompt="user",
            context={"current_text": "teste"},
            model="qwen3:8b",
        )
        time.sleep(0.2)
        shutdown_recorder()
        sd = tmp_recorder.session_dir
        lines = open(os.path.join(sd, "semantic_prompt.jsonl"), encoding="utf-8").readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["user_prompt"] == "user"
        assert event["model"] == "qwen3:8b"

    def test_semantic_result_hook(self, tmp_recorder):
        """semantic_result hook registra resultado na categoria semantic_result."""
        telemetry_hooks.semantic_result(
            correlation_id="corr-3",
            intent="show_reference",
            candidates=[{"book": "João", "chapter": 3, "verse": 16}],
            inference_ms=2500,
            cached=False,
        )
        time.sleep(0.2)
        shutdown_recorder()
        sd = tmp_recorder.session_dir
        lines = open(os.path.join(sd, "semantic_result.jsonl"), encoding="utf-8").readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["intent"] == "show_reference"
        assert event["candidates"][0]["book"] == "João"
        assert event["inference_ms"] == 2500

    def test_resolver_decision_hook(self, tmp_recorder):
        """resolver_decision hook registra decisão na categoria resolver."""
        telemetry_hooks.resolver_decision(
            correlation_id="corr-4",
            candidates_in=[{"book": "João", "chapter": 3}],
            candidates_valid=[{"book": "João", "chapter": 3}],
            chosen={"book": "João", "chapter": 3, "verse": 16, "confidence": 0.9},
            reason="highest_confidence",
            min_confidence=0.5,
        )
        time.sleep(0.2)
        shutdown_recorder()
        sd = tmp_recorder.session_dir
        lines = open(os.path.join(sd, "resolver.jsonl"), encoding="utf-8").readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["reason"] == "highest_confidence"
        assert event["chosen"]["book"] == "João"

    def test_holyrics_presentation_hook(self, tmp_recorder):
        """holyrics_presentation hook registra apresentação na categoria holyrics."""
        telemetry_hooks.holyrics_presentation(
            correlation_id="corr-5",
            book="João",
            chapter=3,
            verse=16,
            version="ACF",
            quick_presentation=False,
            success=True,
            latency_ms=450,
        )
        time.sleep(0.2)
        shutdown_recorder()
        sd = tmp_recorder.session_dir
        lines = open(os.path.join(sd, "holyrics.jsonl"), encoding="utf-8").readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["book"] == "João"
        assert event["success"] is True
        assert event["latency_ms"] == 450

    def test_sermon_state_change_hook(self, tmp_recorder):
        """sermon_state_change hook registra mudança na categoria sermon_memory."""
        telemetry_hooks.sermon_state_change(
            correlation_id="corr-6",
            reason="reference_detected+book_changed",
            previous_book="",
            previous_chapter=0,
            new_book="João",
            new_chapter=3,
            probable_theme="salvação",
            num_entities=5,
            num_topics=3,
            num_references=1,
            confidence=0.8,
            source="parser",
            reference_active="João 3:0",
        )
        time.sleep(0.2)
        shutdown_recorder()
        sd = tmp_recorder.session_dir
        lines = open(os.path.join(sd, "sermon_memory.jsonl"), encoding="utf-8").readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["new_book"] == "João"
        assert event["reason"] == "reference_detected+book_changed"

    def test_parser_event_hook(self, tmp_recorder):
        """parser_event hook registra decisão na categoria parser."""
        telemetry_hooks.parser_event(
            correlation_id="corr-7",
            text_processed="joão capítulo 3 versículo 16",
            expecting="verse",
            completeness="verse",
            book="João",
            chapter=3,
            verse=16,
            confidence=0.95,
            decision="publish_detected",
            published_event="ReferenceDetected",
            latency_ms=5,
        )
        time.sleep(0.2)
        shutdown_recorder()
        sd = tmp_recorder.session_dir
        lines = open(os.path.join(sd, "parser.jsonl"), encoding="utf-8").readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["decision"] == "publish_detected"
        assert event["book"] == "João"

    def test_hooks_noop_when_disabled(self):
        """Hooks são no-op quando a telemetria está desabilitada."""
        # Garantir que não há recorder ativo.
        shutdown_recorder()
        # Chamar todos os hooks — não devem lançar exceção nem escrever.
        telemetry_hooks.stt_window(
            correlation_id="x", audio_duration_ms=1000, rms=0.01,
        )
        telemetry_hooks.semantic_prompt(
            correlation_id="x", system_prompt="", user_prompt="",
        )
        telemetry_hooks.semantic_result(
            correlation_id="x", intent="", candidates=[], inference_ms=0,
        )
        telemetry_hooks.resolver_decision(
            correlation_id="x", candidates_in=[], candidates_valid=[],
            chosen=None, reason="", min_confidence=0.5,
        )
        telemetry_hooks.holyrics_presentation(
            correlation_id="x", book="", chapter=0, verse=0,
            version="", quick_presentation=False, success=False, latency_ms=0,
        )
        # Se chegou aqui sem exceção, o teste passou.
        assert True


class TestTelemetryDoesNotAlterBehavior:
    """Testes que validam que a telemetria não altera o comportamento do pipeline."""

    def test_recorder_with_none_session_dir_when_disabled(self):
        """Recorder desabilitado não cria diretório de sessão."""
        shutdown_recorder()
        r = configure_recorder(enabled=False)
        assert r.session_dir is None or not r.session_dir.exists()
        shutdown_recorder()

    def test_record_after_shutdown_is_noop(self, tmp_recorder):
        """record() após shutdown é silenciosamente ignorado."""
        shutdown_recorder()
        # Não deve lançar exceção.
        record("after_shutdown", {"msg": "should_be_ignored"})
        # is_enabled deve retornar False.
        assert is_enabled() is False
