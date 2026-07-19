"""DTOs de System, Audio e Info — Sprint 14.

Estes DTOs são imutáveis (frozen dataclass) e serializáveis.
Espelham a estrutura exposta pelos routers REST.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# AudioDeviceDTO — dispositivo de áudio de entrada.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AudioDeviceDTO:
    """DTO de um dispositivo de áudio de entrada.

    Atributos:
        index: índice PortAudio do dispositivo.
        name: nome do dispositivo (descrito pelo driver).
        channels: número máximo de canais de entrada.
        sample_rate: taxa de amostragem padrão (Hz).
        is_default: True se é o dispositivo padrão do sistema.
        available: True se está disponível para captura agora.
    """

    index: int
    name: str
    channels: int
    sample_rate: float
    is_default: bool
    available: bool = True

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "channels": self.channels,
            "sample_rate": self.sample_rate,
            "is_default": self.is_default,
            "available": self.available,
        }


# ---------------------------------------------------------------------------
# AudioLevelsDTO — níveis de áudio em tempo real.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AudioLevelsDTO:
    """DTO de níveis de áudio em tempo real (RMS / peak).

    Atributos:
        rms: nível RMS normalizado (0.0–1.0).
        peak: nível de pico normalizado (0.0–1.0).
        timestamp: timestamp da medição (time.time()).
    """

    rms: float
    peak: float
    timestamp: float

    def to_dict(self) -> dict:
        return {
            "rms": self.rms,
            "peak": self.peak,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# SystemInfoDTO — informações consolidadas do sistema.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SystemInfoDTO:
    """DTO de informações do sistema (hardware + software + runtime).

    Atributos:
        python_version: versão do Python em execução.
        os_name: nome do sistema operacional.
        os_version: versão do sistema operacional.
        architecture: arquitetura da CPU (ex.: 'x86_64').
        cpu_count: número de CPUs lógicas.
        cpu_percent: uso de CPU em porcentagem (0–100).
        memory_total_bytes: memória total (bytes).
        memory_available_bytes: memória disponível (bytes).
        disk_total_bytes: disco total do diretório de trabalho (bytes).
        disk_used_bytes: disco usado do diretório de trabalho (bytes).
        log_dir: caminho absoluto do diretório de logs.
        cache_dir: caminho absoluto do diretório de cache.
        data_dir: caminho absoluto do diretório de dados.
        gpu_name: nome da GPU (ou "" se não disponível).
        gpu_memory_total_bytes: memória total da GPU (bytes, ou 0).
        gpu_memory_used_bytes: memória usada da GPU (bytes, ou 0).
        torch_version: versão do PyTorch instalado (ou "" se ausente).
        faster_whisper_version: versão do faster-whisper (ou "" se ausente).
        sentence_transformers_version: versão do sentence-transformers (ou "" se ausente).
        sounddevice_version: versão do sounddevice (ou "" se ausente).
    """

    python_version: str
    os_name: str
    os_version: str
    architecture: str
    cpu_count: int
    cpu_percent: float
    memory_total_bytes: int
    memory_available_bytes: int
    disk_total_bytes: int
    disk_used_bytes: int
    log_dir: str
    cache_dir: str
    data_dir: str
    gpu_name: str = ""
    gpu_memory_total_bytes: int = 0
    gpu_memory_used_bytes: int = 0
    torch_version: str = ""
    faster_whisper_version: str = ""
    sentence_transformers_version: str = ""
    sounddevice_version: str = ""

    def to_dict(self) -> dict:
        return {
            "python_version": self.python_version,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "architecture": self.architecture,
            "cpu_count": self.cpu_count,
            "cpu_percent": self.cpu_percent,
            "memory_total_bytes": self.memory_total_bytes,
            "memory_available_bytes": self.memory_available_bytes,
            "disk_total_bytes": self.disk_total_bytes,
            "disk_used_bytes": self.disk_used_bytes,
            "log_dir": self.log_dir,
            "cache_dir": self.cache_dir,
            "data_dir": self.data_dir,
            "gpu_name": self.gpu_name,
            "gpu_memory_total_bytes": self.gpu_memory_total_bytes,
            "gpu_memory_used_bytes": self.gpu_memory_used_bytes,
            "torch_version": self.torch_version,
            "faster_whisper_version": self.faster_whisper_version,
            "sentence_transformers_version": self.sentence_transformers_version,
            "sounddevice_version": self.sounddevice_version,
        }


# ---------------------------------------------------------------------------
# InfoDTO — metadados da API + build.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InfoDTO:
    """DTO de metadados da API.

    Atributos:
        name: nome da aplicação.
        version: versão do backend (semver-like string).
        api_version: dict com major, minor, patch, pre.
        server_time: timestamp do servidor (time.time()).
        build_id: identificador de build (ou "" se não definido).
        commit: hash do commit Git (ou "" se não definido).
        build_date: data de build ISO (ou "" se não definida).
        frontend_version: versão esperada do frontend (ou "").
        sdk_compatibility: versão mínima do SDK compatível (ou "").
    """

    name: str
    version: str
    api_version: dict
    server_time: float
    build_id: str = ""
    commit: str = ""
    build_date: str = ""
    frontend_version: str = ""
    sdk_compatibility: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "api_version": dict(self.api_version),
            "server_time": self.server_time,
            "build_id": self.build_id,
            "commit": self.commit,
            "build_date": self.build_date,
            "frontend_version": self.frontend_version,
            "sdk_compatibility": self.sdk_compatibility,
        }
