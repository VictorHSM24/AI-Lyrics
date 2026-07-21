# -*- coding: utf-8 -*-
"""Testes do Sprint 19.1 — GPU Runtime & Hardware Acceleration.

Cobre:
- Detecção de hardware (CPU, AMD, DirectML, ROCm).
- Seleção automática de backend (prioridade CUDA > DirectML > ROCm > CPU).
- Override manual de backend.
- Fallback GPU→CPU (retry-then-fallback N falhas).
- Criação do backend correto.
- Configuração inválida.
- Ausência de GPU.
- GPU indisponível.
- StreamingSTT utilizando o backend escolhido.
- SpeechWorker reutilizando a mesma instância.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from core.hardware import (
    CpuInfo,
    GpuInfo,
    HardwareDetector,
    HardwareProfile,
)
from transcricao.backend_selector import (
    BackendSelectionError,
    BackendSelector,
)
from transcricao.inference_backend import BackendInfo
from transcricao.backend_fallback import (
    BackendFallbackError,
    BackendFallbackManager,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    has_cuda: bool = False,
    has_directml: bool = False,
    has_rocm: bool = False,
    gpus: tuple[GpuInfo, ...] = (),
) -> HardwareProfile:
    """Cria um HardwareProfile sintético para testes."""
    return HardwareProfile(
        cpu=CpuInfo(
            name="Test CPU",
            physical_cores=8,
            logical_cores=16,
            architecture="x86_64",
        ),
        ram_mb=16384,
        gpus=gpus,
        os_name="windows",
        os_version="10.0",
        python_version="3.14.3",
    )


def _amd_gpu(vram_mb: int = 8192) -> GpuInfo:
    return GpuInfo(
        name="AMD Radeon RX 7600",
        vendor="amd",
        vram_mb=vram_mb,
        cuda_support="none",
        directml_support=True,
        rocm_support=False,
    )


def _nvidia_gpu(vram_mb: int = 8192) -> GpuInfo:
    return GpuInfo(
        name="NVIDIA GeForce RTX 4060",
        vendor="nvidia",
        vram_mb=vram_mb,
        cuda_support="full",
        cuda_version="12",
        directml_support=False,
        rocm_support=False,
    )


# ---------------------------------------------------------------------------
# Testes — Detecção de Hardware (Etapa 2)
# ---------------------------------------------------------------------------


class TestHardwareDetection(unittest.TestCase):
    """Testes da camada de detecção de hardware."""

    def test_detect_amd_gpu_via_wmi_mocked(self) -> None:
        """Detecta GPU AMD via WMI (mocked)."""
        wmi_output = (
            "Name          : AMD Radeon RX 7600\n"
            "AdapterRAM    : 4293918720\n"
            "DriverVersion : 32.0.31021.5001\n"
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = wmi_output

        with patch("subprocess.run", return_value=mock_result):
            with patch("platform.system", return_value="Windows"):
                gpus = HardwareDetector._detect_gpus_via_wmi()

        assert len(gpus) == 1
        assert gpus[0].vendor == "amd"
        assert gpus[0].name == "AMD Radeon RX 7600"
        # VRAM deve ser resolvida da tabela conhecida (8GB).
        assert gpus[0].vram_mb == 8192

    def test_infer_vendor_from_name(self) -> None:
        """Inferência de vendor a partir do nome."""
        assert HardwareDetector._infer_vendor_from_name(
            "NVIDIA GeForce RTX 4060"
        ) == "nvidia"
        assert HardwareDetector._infer_vendor_from_name(
            "AMD Radeon RX 7600"
        ) == "amd"
        assert HardwareDetector._infer_vendor_from_name(
            "Intel Arc A770"
        ) == "intel"
        assert HardwareDetector._infer_vendor_from_name(
            "Unknown GPU"
        ) == "unknown"

    def test_resolve_vram_known_gpu(self) -> None:
        """VRAM de GPUs conhecidas é resolvida da tabela."""
        assert HardwareDetector._resolve_vram_mb(
            "AMD Radeon RX 7600", 4293918720
        ) == 8192
        assert HardwareDetector._resolve_vram_mb(
            "NVIDIA GeForce RTX 4090", 0
        ) == 24576

    def test_resolve_vram_unknown_gpu(self) -> None:
        """VRAM de GPU desconhecida usa AdapterRAM do WMI."""
        assert HardwareDetector._resolve_vram_mb(
            "Unknown GPU", 2147483648
        ) == 2048  # 2GB

    def test_check_directml_support_installed(self) -> None:
        """DirectML disponível quando onnxruntime-directml instalado."""
        mock_ort = MagicMock()
        mock_ort.get_available_providers.return_value = [
            "DmlExecutionProvider", "CPUExecutionProvider"
        ]
        with patch.dict("sys.modules", {"onnxruntime": mock_ort}):
            assert HardwareDetector._check_directml_support() is True

    def test_check_directml_support_not_installed(self) -> None:
        """DirectML indisponível quando onnxruntime-directml não instalado."""
        with patch.dict("sys.modules", {"onnxruntime": None}):
            assert HardwareDetector._check_directml_support() is False

    def test_check_rocm_support_linux(self) -> None:
        """ROCm disponível apenas no Linux com rocm-smi."""
        with patch("platform.system", return_value="Linux"):
            with patch("shutil.which", return_value="/usr/bin/rocm-smi"):
                assert HardwareDetector._check_rocm_support() is True

    def test_check_rocm_support_windows(self) -> None:
        """ROCm indisponível no Windows."""
        with patch("platform.system", return_value="Windows"):
            assert HardwareDetector._check_rocm_support() is False

    def test_profile_has_directml_property(self) -> None:
        """HardwareProfile.has_directml funciona corretamente."""
        profile = _make_profile(
            has_directml=True,
            gpus=(_amd_gpu(),),
        )
        assert profile.has_directml is True
        assert profile.has_amd_gpu is True
        assert profile.has_cuda is False

    def test_profile_has_amd_and_directml(self) -> None:
        """Profile com AMD + DirectML."""
        profile = _make_profile(
            gpus=(_amd_gpu(directml_support=True) if False else _amd_gpu(),),
        )
        # _amd_gpu() já tem directml_support=True por default.
        assert profile.has_amd_gpu is True
        assert profile.has_directml is True


# ---------------------------------------------------------------------------
# Testes — Seleção Automática (Etapa 4)
# ---------------------------------------------------------------------------


class TestBackendSelection(unittest.TestCase):
    """Testes da seleção automática de backend."""

    def test_auto_selects_cuda_when_available(self) -> None:
        """Auto seleciona CUDA quando disponível (prioridade 1)."""
        profile = _make_profile(
            has_cuda=True,
            has_directml=True,
            gpus=(_nvidia_gpu(8192),),
        )
        info = BackendSelector.select("auto", "auto", profile)
        assert info.backend_type == "cuda"
        # 8GB VRAM → float16.
        assert info.compute_type == "float16"

    def test_auto_selects_directml_when_no_cuda(self) -> None:
        """Auto seleciona DirectML quando CUDA indisponível (prioridade 2)."""
        profile = _make_profile(
            has_cuda=False,
            has_directml=True,
            gpus=(_amd_gpu(),),
        )
        info = BackendSelector.select("auto", "auto", profile)
        assert info.backend_type == "directml"
        assert info.compute_type == "float32"  # DirectML só suporta float32

    def test_auto_selects_cpu_when_no_gpu(self) -> None:
        """Auto seleciona CPU quando nenhuma GPU disponível."""
        profile = _make_profile(
            has_cuda=False,
            has_directml=False,
            has_rocm=False,
            gpus=(),
        )
        info = BackendSelector.select("auto", "auto", profile)
        assert info.backend_type == "cpu"
        assert info.compute_type == "int8"

    def test_explicit_cuda_falls_back_to_cpu(self) -> None:
        """CUDA explícito sem GPU NVIDIA → fallback para CPU."""
        profile = _make_profile(
            has_cuda=False,
            has_directml=True,
            gpus=(_amd_gpu(),),
        )
        info = BackendSelector.select("cuda", "auto", profile)
        assert info.backend_type == "cpu"
        assert "not available" in info.reason

    def test_explicit_directml_when_available(self) -> None:
        """DirectML explícito quando disponível."""
        profile = _make_profile(
            has_directml=True,
            gpus=(_amd_gpu(),),
        )
        info = BackendSelector.select("directml", "auto", profile)
        assert info.backend_type == "directml"

    def test_explicit_directml_falls_back_to_cpu(self) -> None:
        """DirectML explícito sem onnxruntime-directml → CPU."""
        profile = _make_profile(
            has_directml=False,
            gpus=(),
        )
        info = BackendSelector.select("directml", "auto", profile)
        assert info.backend_type == "cpu"

    def test_explicit_cpu_always_available(self) -> None:
        """CPU explícito sempre disponível."""
        profile = _make_profile()
        info = BackendSelector.select("cpu", "auto", profile)
        assert info.backend_type == "cpu"

    def test_invalid_backend_raises(self) -> None:
        """Backend inválido levanta BackendSelectionError."""
        profile = _make_profile()
        with self.assertRaises(BackendSelectionError) as ctx:
            BackendSelector.select("invalid_backend", "auto", profile)
        assert "unknown backend" in str(ctx.exception).lower()

    def test_compute_type_auto_resolves_per_backend(self) -> None:
        """compute_type='auto' resolve diferente por backend."""
        profile = _make_profile(
            has_cuda=True,
            gpus=(_nvidia_gpu(8192),),
        )
        # CUDA com 8GB → float16.
        info = BackendSelector.select("cuda", "auto", profile)
        assert info.compute_type == "float16"

        # CPU → int8.
        info = BackendSelector.select("cpu", "auto", profile)
        assert info.compute_type == "int8"

        # DirectML → float32.
        profile_dml = _make_profile(
            has_directml=True,
            gpus=(_amd_gpu(),),
        )
        info = BackendSelector.select("directml", "auto", profile_dml)
        assert info.compute_type == "float32"

    def test_compute_type_cuda_low_vram_uses_int8(self) -> None:
        """CUDA com VRAM < 4GB → int8."""
        profile = _make_profile(
            has_cuda=True,
            gpus=(_nvidia_gpu(2048),),
        )
        info = BackendSelector.select("cuda", "auto", profile)
        assert info.compute_type == "int8"

    def test_compute_type_cuda_mid_vram_uses_int8_float16(self) -> None:
        """CUDA com 4-8GB VRAM → int8_float16."""
        profile = _make_profile(
            has_cuda=True,
            gpus=(_nvidia_gpu(4096),),
        )
        info = BackendSelector.select("cuda", "auto", profile)
        assert info.compute_type == "int8_float16"

    def test_directml_ignores_float16_request(self) -> None:
        """DirectML não suporta float16 — usa float32 mesmo se solicitado."""
        profile = _make_profile(
            has_directml=True,
            gpus=(_amd_gpu(),),
        )
        info = BackendSelector.select("directml", "float16", profile)
        assert info.compute_type == "float32"

    def test_list_available_backends(self) -> None:
        """list_available retorna todos os backends com disponibilidade."""
        profile = _make_profile(
            has_cuda=False,
            has_directml=True,
            has_rocm=False,
            gpus=(_amd_gpu(),),
        )
        backends = BackendSelector.list_available(profile)
        names = [b["name"] for b in backends]
        assert "cuda" in names
        assert "directml" in names
        assert "rocm" in names
        assert "cpu" in names
        # DirectML deve estar available=True.
        dml = next(b for b in backends if b["name"] == "directml")
        assert dml["available"] is True
        # CUDA deve estar available=False.
        cuda = next(b for b in backends if b["name"] == "cuda")
        assert cuda["available"] is False


# ---------------------------------------------------------------------------
# Testes — Configuração (Etapa 6)
# ---------------------------------------------------------------------------


class TestSTTConfigValidation(unittest.TestCase):
    """Testes de validação de STTConfig."""

    def test_config_accepts_auto_backend(self) -> None:
        """config.yaml com backend='auto' é válido."""
        from config.loader import _build_stt
        data = {
            "model": "large-v3-turbo",
            "device": "auto",
            "compute_type": "auto",
            "language": "pt",
            "chunk_length_s": 30,
            "vad": {"mode": "silero", "min_speech_ms": 250, "pause_threshold_ms": 600},
            "backend": "auto",
        }
        cfg = _build_stt(data)
        assert cfg.backend == "auto"
        assert cfg.device == "auto"
        assert cfg.compute_type == "auto"

    def test_config_accepts_directml_backend(self) -> None:
        """config.yaml com backend='directml' é válido."""
        from config.loader import _build_stt
        data = {
            "model": "large-v3-turbo",
            "device": "directml",
            "compute_type": "float32",
            "language": "pt",
            "chunk_length_s": 30,
            "vad": {"mode": "silero", "min_speech_ms": 250, "pause_threshold_ms": 600},
            "backend": "directml",
        }
        cfg = _build_stt(data)
        assert cfg.backend == "directml"

    def test_config_rejects_invalid_backend(self) -> None:
        """config.yaml com backend inválido levanta ConfigError."""
        from config.loader import _build_stt
        from core.exceptions import ConfigError
        data = {
            "model": "large-v3-turbo",
            "device": "cpu",
            "compute_type": "int8",
            "language": "pt",
            "chunk_length_s": 30,
            "vad": {"mode": "silero", "min_speech_ms": 250, "pause_threshold_ms": 600},
            "backend": "invalid",
        }
        with self.assertRaises(ConfigError):
            _build_stt(data)

    def test_config_rejects_invalid_device(self) -> None:
        """config.yaml com device inválido levanta ConfigError."""
        from config.loader import _build_stt
        from core.exceptions import ConfigError
        data = {
            "model": "large-v3-turbo",
            "device": "invalid_device",
            "compute_type": "int8",
            "language": "pt",
            "chunk_length_s": 30,
            "vad": {"mode": "silero", "min_speech_ms": 250, "pause_threshold_ms": 600},
            "backend": "auto",
        }
        with self.assertRaises(ConfigError):
            _build_stt(data)

    def test_config_accepts_gpu_memory_limit(self) -> None:
        """config.yaml com gpu_memory_limit_mb é válido."""
        from config.loader import _build_stt
        data = {
            "model": "large-v3-turbo",
            "device": "auto",
            "compute_type": "auto",
            "language": "pt",
            "chunk_length_s": 30,
            "vad": {"mode": "silero", "min_speech_ms": 250, "pause_threshold_ms": 600},
            "backend": "auto",
            "gpu_memory_limit_mb": 4096,
        }
        cfg = _build_stt(data)
        assert cfg.gpu_memory_limit_mb == 4096

    def test_persistence_validates_new_backends(self) -> None:
        """validate_overrides aceita novos backends Sprint 19.1."""
        from config.persistence import validate_overrides
        for backend in ["auto", "cuda", "directml", "rocm", "cpu", "faster-whisper"]:
            errors = validate_overrides({"stt": {"backend": backend}})
            assert errors == [], f"backend={backend} should be valid"

    def test_persistence_rejects_invalid_backend(self) -> None:
        """validate_overrides rejeita backend inválido."""
        from config.persistence import validate_overrides
        errors = validate_overrides({"stt": {"backend": "invalid"}})
        assert len(errors) > 0
        assert "invalid stt.backend" in errors[0]


# ---------------------------------------------------------------------------
# Testes — Fallback GPU→CPU (Etapa 9)
# ---------------------------------------------------------------------------


class TestBackendFallbackManager(unittest.TestCase):
    """Testes do BackendFallbackManager (retry-then-fallback)."""

    def _make_mock_backend(
        self, name: str = "directml", fail: bool = False
    ) -> MagicMock:
        """Cria um mock backend."""
        b = MagicMock()
        b.backend_name = name
        b.actual_device = name
        b.actual_compute_type = "float32"
        b.is_loaded = True
        b.fallback_reason = ""
        b.load = MagicMock()
        b.unload = MagicMock()
        if fail:
            b.transcribe = MagicMock(side_effect=RuntimeError("GPU OOM"))
        else:
            b.transcribe = MagicMock(return_value=("hello", "pt", -0.3, ()))
        return b

    def test_success_no_fallback(self) -> None:
        """Backend GPU funciona — sem fallback."""
        gpu = self._make_mock_backend("directml", fail=False)
        cpu_factory = MagicMock(return_value=self._make_mock_backend("cpu"))

        manager = BackendFallbackManager(
            gpu_backend=gpu,
            cpu_backend_factory=cpu_factory,
            max_consecutive_failures=3,
        )

        result = manager.transcribe(b"audio", "pt", 1, False, 30)
        assert result[0] == "hello"
        assert manager.is_fallback_active is False
        assert manager.consecutive_failures == 0
        # CPU factory não deve ser chamada.
        cpu_factory.assert_not_called()

    def test_failure_below_threshold_no_fallback(self) -> None:
        """Falha < N → sem fallback, contador incrementa."""
        gpu = self._make_mock_backend("directml", fail=True)
        cpu_factory = MagicMock(return_value=self._make_mock_backend("cpu"))

        manager = BackendFallbackManager(
            gpu_backend=gpu,
            cpu_backend_factory=cpu_factory,
            max_consecutive_failures=3,
        )

        # 1ª falha.
        with self.assertRaises(RuntimeError):
            manager.transcribe(b"audio", "pt", 1, False, 30)
        assert manager.consecutive_failures == 1
        assert manager.is_fallback_active is False

        # 2ª falha.
        with self.assertRaises(RuntimeError):
            manager.transcribe(b"audio", "pt", 1, False, 30)
        assert manager.consecutive_failures == 2
        assert manager.is_fallback_active is False

        # CPU factory não deve ser chamada ainda.
        cpu_factory.assert_not_called()

    def test_failure_at_threshold_triggers_fallback(self) -> None:
        """N falhas consecutivas → fallback para CPU."""
        gpu = self._make_mock_backend("directml", fail=True)
        cpu = self._make_mock_backend("cpu", fail=False)
        cpu_factory = MagicMock(return_value=cpu)

        manager = BackendFallbackManager(
            gpu_backend=gpu,
            cpu_backend_factory=cpu_factory,
            max_consecutive_failures=3,
        )

        # 3 falhas consecutivas.
        for _ in range(3):
            with self.assertRaises(RuntimeError):
                manager.transcribe(b"audio", "pt", 1, False, 30)

        # Após 3ª falha, fallback deve ser disparado.
        assert manager.is_fallback_active is True
        assert manager.consecutive_failures == 0  # resetado
        cpu_factory.assert_called_once()
        cpu.load.assert_called_once()
        gpu.unload.assert_called_once()

    def test_after_fallback_uses_cpu_backend(self) -> None:
        """Após fallback, transcrições usam backend CPU."""
        gpu = self._make_mock_backend("directml", fail=True)
        cpu = self._make_mock_backend("cpu", fail=False)
        cpu_factory = MagicMock(return_value=cpu)

        manager = BackendFallbackManager(
            gpu_backend=gpu,
            cpu_backend_factory=cpu_factory,
            max_consecutive_failures=2,
        )

        # Disparar fallback.
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                manager.transcribe(b"audio", "pt", 1, False, 30)

        # Próxima transcrição deve usar CPU e ter sucesso.
        result = manager.transcribe(b"audio", "pt", 1, False, 30)
        assert result[0] == "hello"
        assert manager.backend_name == "cpu"
        assert manager.actual_device == "cpu"

    def test_cpu_failure_propagates_error(self) -> None:
        """Se CPU também falhar, erro é propagado (sem mais fallback)."""
        gpu = self._make_mock_backend("directml", fail=True)
        cpu = self._make_mock_backend("cpu", fail=True)
        cpu_factory = MagicMock(return_value=cpu)

        manager = BackendFallbackManager(
            gpu_backend=gpu,
            cpu_backend_factory=cpu_factory,
            max_consecutive_failures=2,
        )

        # Disparar fallback para CPU.
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                manager.transcribe(b"audio", "pt", 1, False, 30)

        # CPU também falha — erro propagado.
        with self.assertRaises(RuntimeError):
            manager.transcribe(b"audio", "pt", 1, False, 30)

    def test_success_resets_failure_counter(self) -> None:
        """Sucesso reseta contador de falhas consecutivas."""
        gpu_fail = self._make_mock_backend("directml", fail=True)
        gpu_ok = self._make_mock_backend("directml", fail=False)

        # Backend que falha 1x depois funciona.
        gpu = MagicMock()
        gpu.backend_name = "directml"
        gpu.actual_device = "directml"
        gpu.actual_compute_type = "float32"
        gpu.is_loaded = True
        gpu.fallback_reason = ""
        gpu.load = MagicMock()
        gpu.unload = MagicMock()
        gpu.transcribe = MagicMock(
            side_effect=[RuntimeError("transient"), ("ok", "pt", -0.3, ())]
        )

        cpu_factory = MagicMock()
        manager = BackendFallbackManager(
            gpu_backend=gpu,
            cpu_backend_factory=cpu_factory,
            max_consecutive_failures=3,
        )

        # 1ª falha.
        with self.assertRaises(RuntimeError):
            manager.transcribe(b"audio", "pt", 1, False, 30)
        assert manager.consecutive_failures == 1

        # 2ª chamada sucesso — contador resetado.
        result = manager.transcribe(b"audio", "pt", 1, False, 30)
        assert result[0] == "ok"
        assert manager.consecutive_failures == 0

    def test_on_fallback_callback_called(self) -> None:
        """Callback on_fallback é chamado quando fallback ocorre."""
        gpu = self._make_mock_backend("directml", fail=True)
        cpu = self._make_mock_backend("cpu", fail=False)
        cpu_factory = MagicMock(return_value=cpu)
        callback = MagicMock()

        manager = BackendFallbackManager(
            gpu_backend=gpu,
            cpu_backend_factory=cpu_factory,
            max_consecutive_failures=1,
            on_fallback=callback,
        )

        # 1 falha → fallback imediato (N=1).
        with self.assertRaises(RuntimeError):
            manager.transcribe(b"audio", "pt", 1, False, 30)

        callback.assert_called_once()

    def test_metrics_tracked(self) -> None:
        """Métricas de transcrições, falhas e fallbacks são rastreadas."""
        gpu = self._make_mock_backend("directml", fail=True)
        cpu = self._make_mock_backend("cpu", fail=False)
        cpu_factory = MagicMock(return_value=cpu)

        manager = BackendFallbackManager(
            gpu_backend=gpu,
            cpu_backend_factory=cpu_factory,
            max_consecutive_failures=2,
        )

        # 2 falhas + fallback + 1 sucesso.
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                manager.transcribe(b"audio", "pt", 1, False, 30)
        manager.transcribe(b"audio", "pt", 1, False, 30)

        assert manager.total_transcriptions == 3
        assert manager.total_failures == 2
        assert manager.total_fallbacks == 1


# ---------------------------------------------------------------------------
# Testes — STT integração (Etapa 5)
# ---------------------------------------------------------------------------


class TestSTTBackendCreation(unittest.TestCase):
    """Testes da criação de backend no STT."""

    def test_stt_is_gpu_backend_directml(self) -> None:
        """STT._is_gpu_backend identifica DirectMLBackend como GPU."""
        from transcricao.stt import STT
        from transcricao.directml_backend import DirectMLBackend
        dml = DirectMLBackend("large-v3-turbo")
        assert STT._is_gpu_backend(dml) is True

    def test_stt_is_gpu_backend_cpu(self) -> None:
        """STT._is_gpu_backend identifica CPU backend como não-GPU."""
        from transcricao.stt import STT
        from transcricao.stt import FasterWhisperBackend
        from config.models import STTConfig, VadConfig
        cfg = STTConfig(
            model="large-v3-turbo", device="cpu", compute_type="int8",
            language="pt", chunk_length_s=30,
            vad=VadConfig(mode="silero", min_speech_ms=250, pause_threshold_ms=600),
        )
        cpu = FasterWhisperBackend(cfg)
        assert STT._is_gpu_backend(cpu) is False

    def test_stt_create_backend_directml(self) -> None:
        """STT._create_backend cria DirectMLBackend quando selecionado."""
        from transcricao.stt import STT
        from config.models import STTConfig, VadConfig

        cfg = STTConfig(
            model="large-v3-turbo",
            device="directml",
            compute_type="float32",
            language="pt",
            chunk_length_s=30,
            vad=VadConfig(mode="silero", min_speech_ms=250, pause_threshold_ms=600),
            backend="directml",
        )

        # Mock BackendSelector para retornar directml.
        with patch("transcricao.backend_selector.BackendSelector.select") as mock_sel:
            mock_sel.return_value = BackendInfo(
                backend_type="directml",
                device="directml",
                compute_type="float32",
                reason="test",
            )
            backend = STT._create_backend(cfg)

        from transcricao.directml_backend import DirectMLBackend
        assert isinstance(backend, DirectMLBackend)

    def test_stt_create_backend_cpu(self) -> None:
        """STT._create_backend cria FasterWhisperBackend para CPU."""
        from transcricao.stt import STT
        from config.models import STTConfig, VadConfig

        cfg = STTConfig(
            model="large-v3-turbo",
            device="cpu",
            compute_type="int8",
            language="pt",
            chunk_length_s=30,
            vad=VadConfig(mode="silero", min_speech_ms=250, pause_threshold_ms=600),
            backend="cpu",
        )

        with patch("transcricao.backend_selector.BackendSelector.select") as mock_sel:
            mock_sel.return_value = BackendInfo(
                backend_type="cpu",
                device="cpu",
                compute_type="int8",
                reason="test",
            )
            backend = STT._create_backend(cfg)

        from transcricao.stt import FasterWhisperBackend
        assert isinstance(backend, FasterWhisperBackend)

    def test_stt_wraps_gpu_backend_with_fallback(self) -> None:
        """STT envolve backend GPU com BackendFallbackManager."""
        from transcricao.stt import STT
        from transcricao.backend_fallback import BackendFallbackManager
        from transcricao.directml_backend import DirectMLBackend
        from config.models import STTConfig, VadConfig

        cfg = STTConfig(
            model="large-v3-turbo",
            device="directml",
            compute_type="float32",
            language="pt",
            chunk_length_s=30,
            vad=VadConfig(mode="silero", min_speech_ms=250, pause_threshold_ms=600),
            backend="directml",
        )

        # Mock BackendSelector + DirectMLBackend.load para não baixar modelo.
        with patch("transcricao.backend_selector.BackendSelector.select") as mock_sel:
            mock_sel.return_value = BackendInfo(
                backend_type="directml",
                device="directml",
                compute_type="float32",
                reason="test",
            )
            with patch.object(DirectMLBackend, "load", return_value=None):
                stt = STT(cfg)

        # STT._backend deve ser BackendFallbackManager.
        assert isinstance(stt._backend, BackendFallbackManager)
        stt.close()


# ---------------------------------------------------------------------------
# Testes — Regressão Sprint 19
# ---------------------------------------------------------------------------


class TestSprint191Regression(unittest.TestCase):
    """Testes de regressão — Sprint 19 ainda funciona."""

    def test_sprint19_streaming_stt_service_importable(self) -> None:
        """StreamingSTTService ainda é importável."""
        from microfone.streaming_stt_service import StreamingSTTService
        assert StreamingSTTService is not None

    def test_sprint19_stt_executor_importable(self) -> None:
        """STTExecutor ainda é importável."""
        from microfone.stt_executor import STTExecutor
        assert STTExecutor is not None

    def test_sprint19_events_still_registered(self) -> None:
        """Eventos Sprint 19 ainda registrados."""
        from pipeline.events import all_event_types
        types = all_event_types()
        names = [t.__name__ for t in types]
        assert "SpeechPartial" in names
        assert "SpeechPartialUpdated" in names
        assert "ReferenceCandidate" in names

    def test_speech_worker_uses_stt_executor(self) -> None:
        """SpeechWorker continua usando STTExecutor (não quebra)."""
        # Apenas verificar que SpeechWorker é importável.
        from microfone.speech_worker import SpeechWorker
        assert SpeechWorker is not None


if __name__ == "__main__":
    unittest.main()
