"""conftest.py — configuração global para os testes do AI Lyrics.

Sprint 21.1: seta AI_LYRICS_TEST_MODE=1 para evitar que create_composition_root()
carregue componentes pesados (STT faster-whisper, embeddings, SemanticEngine,
SermonMemoryEngine, etc.) durante testes que apenas validam endpoints REST.

Testes que precisam de componentes reais devem usar mocks próprios ou
unsetar esta env var explicitamente.

Sprint 24: autouse fixture mocka save_overrides/load_overrides para evitar
que testes que chamam POST /wizard/*/save ou PUT /configuration poluam o
arquivo real config/config.overrides.json com tokens de teste.
"""

import os

# Setar antes de qualquer import do api.startup.
os.environ["AI_LYRICS_TEST_MODE"] = "1"

import pytest


@pytest.fixture(autouse=True)
def _isolate_overrides_file(tmp_path, monkeypatch):
    """Redireciona save_overrides/load_overrides para paths temporários.

    Sem este fixture, testes que chamam endpoints de save (Wizard,
    Configuration) gravam no arquivo real config/config.overrides.json,
    poluindo a config de produção com tokens de teste (ex: "versioned-test").

    Estratégia: writes/reads cujo path resolve para o path real do projeto
    (config/config.overrides.json) são redirecionados silenciosamente para
    um arquivo temporário. Paths customizados (ex: testes que setam
    _overrides_path para um temp dir próprio) são respeitados.
    """
    import json
    import os as _os
    import config.persistence as persistence

    default_overrides = tmp_path / "config.overrides.json"
    # Path real que queremos proteger de poluição.
    real_path = _os.path.abspath("config/config.overrides.json")

    def _resolve(path):
        """Retorna o path efetivo: redireciona o path real para o temp."""
        if not path:
            return str(default_overrides)
        # Normalizar para comparar: se aponta para o arquivo real do projeto,
        # redirecionar para o temp.
        try:
            abs_path = _os.path.abspath(path)
        except Exception:
            abs_path = str(path)
        if abs_path == real_path:
            return str(default_overrides)
        return path

    def _fake_save_overrides(overrides, path=None):
        resolved = _resolve(path)
        d = _os.path.dirname(resolved) or "."
        _os.makedirs(d, exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            json.dump(overrides, f, indent=2, ensure_ascii=False, sort_keys=True)

    def _fake_load_overrides(path=None):
        resolved = _resolve(path)
        if _os.path.isfile(resolved):
            try:
                return json.loads(open(resolved, encoding="utf-8").read())
            except Exception:
                return {}
        return {}

    monkeypatch.setattr(persistence, "save_overrides", _fake_save_overrides)
    monkeypatch.setattr(persistence, "load_overrides", _fake_load_overrides)
