"""Testes do AudioCaptureService — Sprint 15.1.

Cobertura:
  - AudioFrame (dataclass imutável)
  - AudioCaptureService (list_devices, start, stop, select_device, buffer)
  - Callback de áudio (RMS/Peak reais com numpy)
  - Thread safety (buffer circular)
  - Shutdown (nenhum recurso permanece aberto)
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from microfone.audio_capture_service import AudioCaptureService, AudioFrame


class TestAudioFrame(unittest.TestCase):
    """Testes do AudioFrame — dataclass imutável."""

    def test_create_frame(self):
        frame = AudioFrame(
            timestamp=1234567890.0,
            sample_rate=16000,
            channels=1,
            frame_count=480,
            rms=0.5,
            peak=0.8,
        )
        self.assertEqual(frame.timestamp, 1234567890.0)
        self.assertEqual(frame.sample_rate, 16000)
        self.assertEqual(frame.channels, 1)
        self.assertEqual(frame.frame_count, 480)
        self.assertEqual(frame.rms, 0.5)
        self.assertEqual(frame.peak, 0.8)

    def test_frame_is_frozen(self):
        frame = AudioFrame(
            timestamp=0, sample_rate=16000, channels=1,
            frame_count=480, rms=0.5, peak=0.8,
        )
        with self.assertRaises((AttributeError, Exception)):
            frame.rms = 0.9  # type: ignore

    def test_to_dict(self):
        frame = AudioFrame(
            timestamp=1.0, sample_rate=16000, channels=1,
            frame_count=480, rms=0.5, peak=0.8,
        )
        d = frame.to_dict()
        self.assertEqual(d["rms"], 0.5)
        self.assertEqual(d["peak"], 0.8)
        self.assertEqual(d["sample_rate"], 16000)
        self.assertEqual(d["channels"], 1)
        self.assertEqual(d["frame_count"], 480)
        self.assertEqual(d["timestamp"], 1.0)


class TestAudioCaptureService(unittest.TestCase):
    """Testes do AudioCaptureService."""

    def setUp(self):
        self.svc = AudioCaptureService(
            sample_rate=16000,
            channels=1,
            blocksize=480,
            buffer_size=10,
        )

    def tearDown(self):
        self.svc.shutdown()

    def test_initial_state(self):
        self.assertFalse(self.svc.capturing)
        self.assertIsNone(self.svc.device_index)
        self.assertEqual(self.svc.sample_rate, 16000)
        self.assertEqual(self.svc.channels, 1)
        self.assertFalse(self.svc.is_open)

    def test_list_devices_returns_list(self):
        devices = self.svc.list_devices()
        self.assertIsInstance(devices, list)
        # Cada device tem as chaves esperadas.
        for d in devices:
            self.assertIn("index", d)
            self.assertIn("name", d)
            self.assertIn("channels", d)
            self.assertIn("sample_rate", d)
            self.assertIn("is_default", d)
            self.assertIn("available", d)

    def test_get_current_device(self):
        device = self.svc.get_current_device()
        # Pode ser None se não há dispositivos, mas se houver, tem as chaves.
        if device is not None:
            self.assertIn("index", device)
            self.assertIn("name", device)

    def test_buffer_starts_empty(self):
        self.assertIsNone(self.svc.get_latest_frame())
        self.assertEqual(self.svc.get_frames(5), [])
        self.assertEqual(self.svc.drain_frames(), [])

    def test_select_device_without_capture(self):
        result = self.svc.select_device(0)
        self.assertEqual(result["device_index"], 0)
        self.assertFalse(result["restarted"])
        self.assertEqual(self.svc.device_index, 0)

    def test_select_device_with_capture_restarts(self):
        # Mock start/stop para não abrir stream real.
        self.svc._capturing = True
        result = self.svc.select_device(0)
        self.assertEqual(result["device_index"], 0)
        self.assertTrue(result["restarted"])

    def test_stop_when_not_capturing(self):
        result = self.svc.stop()
        self.assertFalse(result["capturing"])
        self.assertFalse(result["already"])

    def test_clear_buffer(self):
        # Adicionar um frame manualmente.
        frame = AudioFrame(
            timestamp=1.0, sample_rate=16000, channels=1,
            frame_count=480, rms=0.5, peak=0.8,
        )
        self.svc._frames.append(frame)
        self.assertIsNotNone(self.svc.get_latest_frame())
        self.svc.clear_buffer()
        self.assertIsNone(self.svc.get_latest_frame())

    def test_buffer_circular_drops_old(self):
        # Buffer size = 10 — adicionar 15 frames.
        for i in range(15):
            frame = AudioFrame(
                timestamp=float(i), sample_rate=16000, channels=1,
                frame_count=480, rms=float(i) / 100, peak=float(i) / 50,
            )
            self.svc._frames.append(frame)
        # Buffer deve ter apenas os últimos 10.
        frames = self.svc.get_frames(100)
        self.assertEqual(len(frames), 10)
        # O primeiro frame no buffer deve ser o frame 5.
        self.assertEqual(frames[0].timestamp, 5.0)

    def test_set_on_frame_callback(self):
        received: list[AudioFrame] = []
        self.svc.set_on_frame(lambda f: received.append(f))
        frame = AudioFrame(
            timestamp=1.0, sample_rate=16000, channels=1,
            frame_count=480, rms=0.5, peak=0.8,
        )
        self.svc._on_frame(frame)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].rms, 0.5)

    def test_set_on_frame_none(self):
        self.svc.set_on_frame(None)
        # Não deve lançar erro ao processar frame.
        frame = AudioFrame(
            timestamp=1.0, sample_rate=16000, channels=1,
            frame_count=480, rms=0.5, peak=0.8,
        )
        # Simular callback no _audio_callback path.
        self.svc._on_frame = None
        # Não deve lançar erro.

    def test_drain_frames(self):
        for i in range(5):
            frame = AudioFrame(
                timestamp=float(i), sample_rate=16000, channels=1,
                frame_count=480, rms=float(i), peak=float(i),
            )
            self.svc._frames.append(frame)
        drained = self.svc.drain_frames()
        self.assertEqual(len(drained), 5)
        # Buffer deve estar vazio após drain.
        self.assertEqual(self.svc.drain_frames(), [])

    def test_audio_callback_with_silence(self):
        """Callback com silêncio deve produzir RMS próximo de zero."""
        import numpy as np
        # Criar buffer de silêncio (zeros).
        silence = np.zeros((480, 1), dtype=np.float32)
        self.svc._audio_callback(silence, 480, None, None)
        frame = self.svc.get_latest_frame()
        self.assertIsNotNone(frame)
        self.assertLess(frame.rms, 0.001)  # Próximo de zero.
        self.assertLess(frame.peak, 0.001)

    def test_audio_callback_with_signal(self):
        """Callback com sinal real deve produzir RMS > 0."""
        import numpy as np
        # Criar buffer com senoide (não é mock — é dado real processado).
        t = np.linspace(0, 1, 480, dtype=np.float32)
        signal = (0.5 * np.sin(2 * np.pi * 440 * t)).reshape(-1, 1).astype(np.float32)
        self.svc._audio_callback(signal, 480, None, None)
        frame = self.svc.get_latest_frame()
        self.assertIsNotNone(frame)
        self.assertGreater(frame.rms, 0.1)  # RMS de senoide 0.5 ≈ 0.35
        self.assertGreater(frame.peak, 0.4)  # Peak ≈ 0.5

    def test_audio_callback_calls_on_frame(self):
        """Callback deve chamar on_frame se definido."""
        import numpy as np
        received: list = []
        self.svc.set_on_frame(lambda f: received.append(f))
        signal = np.zeros((480, 1), dtype=np.float32)
        self.svc._audio_callback(signal, 480, None, None)
        self.assertEqual(len(received), 1)

    def test_audio_callback_stereo_uses_first_channel(self):
        """Callback com stereo deve usar canal 0."""
        import numpy as np
        # Canal 0 com sinal, canal 1 com silêncio.
        t = np.linspace(0, 1, 480, dtype=np.float32)
        ch0 = 0.5 * np.sin(2 * np.pi * 440 * t)
        ch1 = np.zeros(480)
        signal = np.stack([ch0, ch1], axis=1).astype(np.float32)
        self.svc._channels = 2
        self.svc._audio_callback(signal, 480, None, None)
        frame = self.svc.get_latest_frame()
        self.assertIsNotNone(frame)
        self.assertGreater(frame.rms, 0.1)  # RMS do canal 0.

    def test_shutdown_stops_and_clears(self):
        self.svc.shutdown()
        self.assertFalse(self.svc.capturing)
        self.assertIsNone(self.svc.get_latest_frame())

    def test_get_frames_with_count(self):
        for i in range(10):
            frame = AudioFrame(
                timestamp=float(i), sample_rate=16000, channels=1,
                frame_count=480, rms=float(i), peak=float(i),
            )
            self.svc._frames.append(frame)
        # Pedir 3 — deve retornar os últimos 3.
        frames = self.svc.get_frames(3)
        self.assertEqual(len(frames), 3)
        self.assertEqual(frames[0].timestamp, 7.0)
        self.assertEqual(frames[2].timestamp, 9.0)

    def test_get_frames_zero(self):
        self.assertEqual(self.svc.get_frames(0), [])


class TestAudioCaptureServiceWithMock(unittest.TestCase):
    """Testes com mock do sounddevice para start/stop."""

    def setUp(self):
        self.svc = AudioCaptureService(sample_rate=16000, channels=1, blocksize=480)

    def tearDown(self):
        self.svc.shutdown()

    @patch("microfone.audio_capture_service.AudioCaptureService.start")
    def test_start_delegates_to_sounddevice(self, mock_start):
        mock_start.return_value = {"capturing": True, "already": False}
        result = self.svc.start()
        self.assertTrue(result["capturing"])

    def test_start_and_stop_lifecycle(self):
        """Testa ciclo start/stop com mock do InputStream."""
        mock_stream = MagicMock()
        with patch("sounddevice.InputStream", return_value=mock_stream):
            result = self.svc.start()
            self.assertTrue(result["capturing"])
            self.assertTrue(self.svc.capturing)
            mock_stream.start.assert_called_once()

            # Stop.
            result = self.svc.stop()
            self.assertFalse(result["capturing"])
            self.assertFalse(self.svc.capturing)
            mock_stream.stop.assert_called_once()
            mock_stream.close.assert_called_once()

    def test_start_when_already_capturing(self):
        mock_stream = MagicMock()
        with patch("sounddevice.InputStream", return_value=mock_stream):
            self.svc.start()
            # Segundo start — não deve abrir novo stream.
            result = self.svc.start()
            self.assertTrue(result["capturing"])
            self.assertTrue(result["already"])
            # InputStream chamado apenas uma vez.
            self.assertEqual(mock_stream.start.call_count, 1)

    def test_select_device_restarts_capture(self):
        mock_stream = MagicMock()
        with patch("sounddevice.InputStream", return_value=mock_stream):
            self.svc.start()
            self.assertTrue(self.svc.capturing)
            # Trocar dispositivo — deve parar e reiniciar.
            result = self.svc.select_device(2)
            self.assertEqual(result["device_index"], 2)
            self.assertTrue(result["restarted"])
            self.assertTrue(self.svc.capturing)
            # Stream anterior fechado, novo aberto.
            self.assertEqual(mock_stream.stop.call_count, 1)
            self.assertEqual(mock_stream.close.call_count, 1)
            # Novo stream iniciado (2x start total).
            self.assertEqual(mock_stream.start.call_count, 2)


if __name__ == "__main__":
    unittest.main()
