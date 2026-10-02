"""Testes do endpoint POST /recording/browse — seletor nativo de pastas.

O pick_folder real abre IFileOpenDialog via ctypes/COM — nos testes é
mockado para não abrir diálogo de verdade.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.startup import reset_root, set_root


class TestRecordingBrowseEndpoint(unittest.TestCase):
    """POST /recording/browse retorna o caminho escolhido no seletor."""

    def setUp(self):
        reset_root()
        # CompositionRoot mockado — o endpoint só precisa de
        # root.audit_recorder.output_dir para a pasta inicial.
        self.root = MagicMock()
        set_root(self.root)
        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self):
        reset_root()

    def test_browse_retorna_pasta_escolhida(self):
        with patch(
            "api.routers.recording.pick_folder",
            return_value=r"C:\Gravacoes\Cultos",
        ) as mock_pick:
            resp = self.client.post("/recording/browse")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()["payload"]
        self.assertEqual(payload["path"], r"C:\Gravacoes\Cultos")
        self.assertFalse(payload["cancelled"])
        _, kwargs = mock_pick.call_args
        self.assertEqual(kwargs["title"], "Selecionar pasta de gravação")

    def test_browse_cancelado_pelo_usuario(self):
        with patch("api.routers.recording.pick_folder", return_value=None):
            resp = self.client.post("/recording/browse")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()["payload"]
        self.assertIsNone(payload["path"])
        self.assertTrue(payload["cancelled"])

    def test_browse_indisponivel_retorna_501(self):
        # Ex.: plataforma não-Windows ou falha COM.
        with patch(
            "api.routers.recording.pick_folder",
            side_effect=RuntimeError("sem suporte"),
        ):
            resp = self.client.post("/recording/browse")

        self.assertEqual(resp.status_code, 501)

    def test_browse_sem_recorder_retorna_503(self):
        self.root.audit_recorder = None
        resp = self.client.post("/recording/browse")
        self.assertEqual(resp.status_code, 503)


if __name__ == "__main__":
    unittest.main()
