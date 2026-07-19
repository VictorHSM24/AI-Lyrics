"""Services de System, Audio e Info — Sprint 14.

Estes services seguem as mesmas regras dos demais services da
Presentation Layer:
  - NUNCA modificam estado do Core.
  - NUNCA executam regra de negócio.
  - Apenas consultam e adaptam via Mappers.

Services:
  - AudioPresentationService: dispositivos e níveis de áudio.
  - SystemPresentationService: informações de hardware/software.
  - InfoPresentationService: metadados da API + build.
"""

from __future__ import annotations

import os
import platform
import sys
import time
from typing import Any

from presentation.dtos_system import (
    AudioDeviceDTO,
    AudioLevelsDTO,
    InfoDTO,
    SystemInfoDTO,
)


# ---------------------------------------------------------------------------
# AudioPresentationService
# ---------------------------------------------------------------------------


class AudioPresentationService:
    """Service para dispositivos e níveis de áudio.

    Sprint 15.1: delega captura para AudioCaptureService.
    Nenhuma lógica de UI ou STT.

    Se um AudioCaptureService for fornecido, usa-o para captura
    contínua com callback. Caso contrário, faz captura pontual
    (fallback para compatibilidade).
    """

    def __init__(
        self,
        audio_config: Any | None = None,
        capture_service: Any | None = None,
    ) -> None:
        self._audio_config = audio_config
        self._capture = capture_service

    def list_devices(self) -> list[AudioDeviceDTO]:
        """Lista dispositivos de entrada de áudio disponíveis."""
        if self._capture is not None:
            devices = self._capture.list_devices()
            return [
                AudioDeviceDTO(
                    index=d["index"],
                    name=d["name"],
                    channels=d["channels"],
                    sample_rate=d["sample_rate"],
                    is_default=d["is_default"],
                    available=d.get("available", True),
                )
                for d in devices
            ]

        # Fallback: query direta (sem capture service).
        try:
            import sounddevice as sd
        except ImportError:
            return []

        try:
            devices = sd.query_devices()
            if not isinstance(devices, list):
                devices = list(devices)
        except Exception:
            return []

        default_input = sd.default.device[0] if sd.default.device else None
        result: list[AudioDeviceDTO] = []
        for i, dev in enumerate(devices):
            max_in = dev.get("max_input_channels", 0)
            if max_in <= 0:
                continue
            result.append(
                AudioDeviceDTO(
                    index=i,
                    name=dev.get("name", f"Device {i}"),
                    channels=int(max_in),
                    sample_rate=float(dev.get("default_samplerate", 0.0)),
                    is_default=(i == default_input),
                    available=True,
                )
            )
        return result

    def get_current_device(self) -> AudioDeviceDTO | None:
        """Retorna o dispositivo atualmente configurado."""
        if self._capture is not None:
            d = self._capture.get_current_device()
            if d is None:
                return None
            return AudioDeviceDTO(
                index=d["index"],
                name=d["name"],
                channels=d["channels"],
                sample_rate=d["sample_rate"],
                is_default=d["is_default"],
                available=d.get("available", True),
            )

        # Fallback sem capture service.
        devices = self.list_devices()
        if not devices:
            return None

        if self._audio_config is not None:
            target = getattr(self._audio_config, "input_device", "")
            if target:
                if isinstance(target, int) or (isinstance(target, str) and target.strip().isdigit()):
                    idx = int(target)
                    for d in devices:
                        if d.index == idx:
                            return d
                target_lower = target.lower().strip()
                for d in devices:
                    if target_lower in d.name.lower():
                        return d

        for d in devices:
            if d.is_default:
                return d
        return devices[0]

    def get_levels(self) -> AudioLevelsDTO:
        """Retorna níveis de áudio (RMS / peak) em tempo real.

        Se AudioCaptureService estiver ativo, lê o frame mais recente
        do buffer circular. Caso contrário, faz captura pontual.
        """
        if self._capture is not None:
            frame = self._capture.get_latest_frame()
            if frame is not None:
                return AudioLevelsDTO(
                    rms=frame.rms,
                    peak=frame.peak,
                    timestamp=frame.timestamp,
                )
            return AudioLevelsDTO(rms=0.0, peak=0.0, timestamp=time.time())

        # Fallback: captura pontual (200ms).
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError:
            return AudioLevelsDTO(rms=0.0, peak=0.0, timestamp=time.time())

        try:
            sr = 16000
            duration_ms = 200
            samples = int(sr * duration_ms / 1000)
            audio = sd.rec(samples, samplerate=sr, channels=1, dtype="float32")
            sd.wait()
            audio = audio.flatten()
            if len(audio) == 0:
                return AudioLevelsDTO(rms=0.0, peak=0.0, timestamp=time.time())
            rms = float(np.sqrt(np.mean(audio ** 2)))
            peak = float(np.max(np.abs(audio)))
            return AudioLevelsDTO(rms=rms, peak=peak, timestamp=time.time())
        except Exception:
            return AudioLevelsDTO(rms=0.0, peak=0.0, timestamp=time.time())

    # ------------------------------------------------------------------
    # Sprint 15.1 — controle de captura (delega para AudioCaptureService).
    # ------------------------------------------------------------------

    def start_capture(self) -> dict:
        """Inicia a captura de áudio."""
        if self._capture is None:
            raise RuntimeError("AudioCaptureService not available")
        return self._capture.start()

    def stop_capture(self) -> dict:
        """Para a captura de áudio."""
        if self._capture is None:
            raise RuntimeError("AudioCaptureService not available")
        return self._capture.stop()

    def select_device(self, device_index: int) -> dict:
        """Seleciona um dispositivo de entrada."""
        if self._capture is None:
            raise RuntimeError("AudioCaptureService not available")
        return self._capture.select_device(device_index)

    @property
    def is_capturing(self) -> bool:
        """True se a captura está ativa."""
        if self._capture is None:
            return False
        return self._capture.capturing


# ---------------------------------------------------------------------------
# SystemPresentationService
# ---------------------------------------------------------------------------


class SystemPresentationService:
    """Service para informações de sistema (hardware + software).

    Usa psutil (se disponível) para CPU/memória/disco.
    Usa platform para OS/arquitetura.
    Usa NVML (se disponível) para GPU.
    """

    def __init__(self, log_dir: str = "logs", cache_dir: str = "cache", data_dir: str = "data") -> None:
        self._log_dir = os.path.abspath(log_dir)
        self._cache_dir = os.path.abspath(cache_dir)
        self._data_dir = os.path.abspath(data_dir)

    def get_info(self) -> SystemInfoDTO:
        """Coleta e retorna informações consolidadas do sistema."""
        # --- Python / OS / Architecture ---
        python_version = sys.version.split()[0] if sys.version else ""
        os_name = platform.system() or ""
        os_version = platform.release() or ""
        architecture = platform.machine() or ""

        # --- CPU / Memory / Disk (psutil) ---
        cpu_count = os.cpu_count() or 0
        cpu_percent = 0.0
        memory_total = 0
        memory_available = 0
        disk_total = 0
        disk_used = 0

        try:
            import psutil
            cpu_percent = float(psutil.cpu_percent(interval=0.1))
            vm = psutil.virtual_memory()
            memory_total = int(vm.total)
            memory_available = int(vm.available)
            du = psutil.disk_usage(os.getcwd())
            disk_total = int(du.total)
            disk_used = int(du.used)
        except ImportError:
            pass
        except Exception:
            pass

        # --- GPU (NVML via torch or pynvml) ---
        gpu_name = ""
        gpu_mem_total = 0
        gpu_mem_used = 0
        try:
            import torch
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                props = torch.cuda.get_device_properties(0)
                gpu_mem_total = int(props.total_memory)
                gpu_mem_used = int(torch.cuda.memory_allocated(0))
        except ImportError:
            pass
        except Exception:
            pass

        # --- Versions ---
        torch_ver = _try_version(lambda: __import__("torch").__version__)
        fw_ver = _try_version(lambda: __import__("faster_whisper").__version__)
        st_ver = _try_version(lambda: __import__("sentence_transformers").__version__)
        sd_ver = _try_version(lambda: __import__("sounddevice").__version__)

        return SystemInfoDTO(
            python_version=python_version,
            os_name=os_name,
            os_version=os_version,
            architecture=architecture,
            cpu_count=cpu_count,
            cpu_percent=cpu_percent,
            memory_total_bytes=memory_total,
            memory_available_bytes=memory_available,
            disk_total_bytes=disk_total,
            disk_used_bytes=disk_used,
            log_dir=self._log_dir,
            cache_dir=self._cache_dir,
            data_dir=self._data_dir,
            gpu_name=gpu_name,
            gpu_memory_total_bytes=gpu_mem_total,
            gpu_memory_used_bytes=gpu_mem_used,
            torch_version=torch_ver,
            faster_whisper_version=fw_ver,
            sentence_transformers_version=st_ver,
            sounddevice_version=sd_ver,
        )


def _try_version(fn) -> str:
    """Tenta executar fn() para obter versão; retorna "" se falhar."""
    try:
        return str(fn())
    except ImportError:
        return ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# InfoPresentationService
# ---------------------------------------------------------------------------


class InfoPresentationService:
    """Service para metadados da API + build.

    Combina versão da API com informações de build (commit, data).
    """

    def __init__(
        self,
        api_version: Any,
        name: str = "AI Lyrics API",
        version: str = "",
        build_id: str = "",
        commit: str = "",
        build_date: str = "",
        frontend_version: str = "",
        sdk_compatibility: str = "",
    ) -> None:
        self._api_version = api_version
        self._name = name
        self._version = version
        self._build_id = build_id
        self._commit = commit
        self._build_date = build_date
        self._frontend_version = frontend_version
        self._sdk_compatibility = sdk_compatibility

    def get_info(self) -> InfoDTO:
        """Retorna InfoDTO com metadados da API."""
        if hasattr(self._api_version, "model_dump"):
            api_dict = self._api_version.model_dump(mode="json")
        elif hasattr(self._api_version, "__dict__"):
            api_dict = dict(self._api_version.__dict__)
        else:
            api_dict = {"major": 0, "minor": 1, "patch": 0}

        return InfoDTO(
            name=self._name,
            version=self._version,
            api_version=api_dict,
            server_time=time.time(),
            build_id=self._build_id,
            commit=self._commit,
            build_date=self._build_date,
            frontend_version=self._frontend_version,
            sdk_compatibility=self._sdk_compatibility,
        )
