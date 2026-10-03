"""Testes — botão retroceder do follow e versão bíblica global.

Sprint 32:
- POST /operator/follow/back delega a ReadingFollowService.back().
- POST /operator/version normaliza a versão, propaga para follow +
  detector + evento VersionChanged e persiste como
  ``state.default_version``.
- _default_version prefere a versão viva do follow service e faz
  fallback a ``state.default_version`` (seção ``state``, não ``verse``).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def root():
    from api.startup import create_composition_root, set_root

    r = create_composition_root()

    follow = MagicMock()
    follow.get_state.return_value = {
        "active": True,
        "book": "Mateus",
        "book_id": 40,
        "chapter": 7,
        "verse_start": 1,
        "verse_end": 3,
        "current_verse": 2,
        "version": "ACF",
        "match_version": "",
        "verse_progress": 0.0,
        "total_verses": 0,
        "verses_read": 0,
        "auto_follow_paused": False,
    }
    follow.back.return_value = True
    follow.set_version.return_value = True
    object.__setattr__(r, "reading_follow_service", follow)

    detector = MagicMock()
    object.__setattr__(r, "version_command_detector", detector)

    cfg = MagicMock()
    object.__setattr__(r, "configuration_service", cfg)

    set_root(r)
    yield r, follow, detector, cfg


@pytest.fixture()
def client(root):
    from api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# POST /operator/follow/back
# ---------------------------------------------------------------------------


class TestFollowBack:
    def test_back_delegates_to_service(self, client, root):
        _, follow, _, _ = root
        res = client.post("/operator/follow/back")
        assert res.status_code == 200
        body = res.json()["payload"]
        assert body["ok"] is True
        follow.back.assert_called_once()

    def test_back_returns_state(self, client):
        res = client.post("/operator/follow/back")
        body = res.json()["payload"]
        assert body["state"]["current_verse"] == 2
        assert body["state"]["version"] == "ACF"

    def test_back_failure_propagates_ok_false(self, client, root):
        _, follow, _, _ = root
        follow.back.return_value = False
        res = client.post("/operator/follow/back")
        body = res.json()["payload"]
        assert body["ok"] is False


# ---------------------------------------------------------------------------
# POST /operator/version — versão global
# ---------------------------------------------------------------------------


class TestSetVersion:
    def test_normalizes_and_propagates(self, client, root):
        r, follow, detector, _ = root
        res = client.post("/operator/version", json={"version": "ara"})
        assert res.status_code == 200
        body = res.json()["payload"]
        assert body["ok"] is True
        assert body["version"] == "ARA"
        follow.set_version.assert_called_once_with("ARA")
        detector.set_current_version.assert_called_once_with("ARA")

    def test_persists_default_version(self, client, root):
        _, _, _, cfg = root
        client.post("/operator/version", json={"version": "nvi"})
        cfg.update_configuration.assert_called_once_with(
            {"state": {"default_version": "NVI"}}
        )

    def test_publishes_version_changed(self, client, root):
        from pipeline.events import VersionChanged

        r, _, _, _ = root
        received = []
        r.bus.subscribe(VersionChanged, received.append)
        client.post("/operator/version", json={"version": "ARA"})
        assert len(received) == 1
        assert received[0].new_version == "ARA"
        assert received[0].source == "manual"

    def test_persistence_failure_does_not_break_set(
        self, client, root,
    ):
        _, follow, _, cfg = root
        cfg.update_configuration.side_effect = ValueError("inválido")
        res = client.post("/operator/version", json={"version": "ARA"})
        assert res.json()["payload"]["ok"] is True
        follow.set_version.assert_called_once_with("ARA")

    def test_failed_set_does_not_persist_or_publish(
        self, client, root,
    ):
        r, follow, detector, cfg = root
        follow.set_version.return_value = False
        res = client.post("/operator/version", json={"version": "ARA"})
        assert res.json()["payload"]["ok"] is False
        detector.set_current_version.assert_not_called()
        cfg.update_configuration.assert_not_called()


# ---------------------------------------------------------------------------
# _default_version — origem autoritativa
# ---------------------------------------------------------------------------


class TestDefaultVersion:
    def test_prefers_live_follow_version(self, root):
        from api.routers.operator import _default_version

        r, follow, _, _ = root
        follow.get_state.return_value["version"] = "ARA"
        assert _default_version(r) == "ARA"

    def test_fallback_to_state_section(self, root):
        from api.routers.operator import _default_version

        r, follow, _, _ = root
        follow.get_state.return_value["version"] = ""
        object.__setattr__(r.config.state, "default_version", "NVI")
        assert _default_version(r) == "NVI"

    def test_fallback_acf_when_nothing(self, root):
        from api.routers.operator import _default_version

        r, follow, _, _ = root
        follow.get_state.return_value["version"] = ""
        object.__setattr__(r.config.state, "default_version", "")
        assert _default_version(r) == "ACF"
