"""Configuração de DLLs CUDA para Windows (Sprint 27).

No Windows, ctranslate2/faster-whisper precisam das bibliotecas de runtime
CUDA (cublas, cudnn, nvrtc) para fazer inferência na GPU. Quando instaladas
via pip (nvidia-cublas-cu12, nvidia-cudnn-cu12, nvidia-cuda-nvrtc-cu12),
as DLLs ficam em subdiretórios de site-packages/nvidia/ que NÃO estão no
PATH do Windows por padrão.

Este módulo localiza essas DLLs e as registra via os.add_dll_directory()
e os.environ['PATH'] ANTES de qualquer import de ctranslate2 ou
faster_whisper. Deve ser o primeiro módulo importado pela aplicação.

Sem isto, o erro é:
    RuntimeError: Library cublas64_12.dll is not found or cannot be loaded

O modelo carrega na VRAM (ctranslate2 detecta a GPU via driver), mas a
inferência falha na primeira chamada de transcribe().
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["setup_cuda_dlls"]


def _find_site_packages() -> Path | None:
    """Localiza o diretório site-packages ativo."""
    # Python 3.12+: usa sys.path para encontrar site-packages.
    for p in sys.path:
        sp = Path(p)
        if sp.is_dir() and (sp / "nvidia").is_dir():
            return sp
    # Fallback: site.getsitepackages()
    try:
        import site
        for p in site.getsitepackages():
            sp = Path(p)
            if (sp / "nvidia").is_dir():
                return sp
    except Exception:
        pass
    return None


def setup_cuda_dlls() -> bool:
    """Registra os diretórios de DLLs CUDA no PATH e via add_dll_directory.

    Deve ser chamado ANTES de importar ctranslate2 ou faster_whisper.

    Returns:
        True se as DLLs foram encontradas e registradas, False caso contrário.
    """
    if not sys.platform.startswith("win"):
        return False  # No-op em Linux/macOS.

    sp = _find_site_packages()
    if sp is None:
        logger.debug("cuda_setup: site-packages with nvidia/ not found — skipping.")
        return False

    # Subdiretórios onde as DLLs CUDA ficam após pip install.
    cuda_lib_dirs = [
        sp / "nvidia" / "cublas" / "bin",
        sp / "nvidia" / "cudnn" / "bin",
        sp / "nvidia" / "cuda_nvrtc" / "bin",
        sp / "nvidia" / "cufft" / "bin",
        sp / "nvidia" / "curand" / "bin",
        sp / "nvidia" / "cusolver" / "bin",
        sp / "nvidia" / "cusparse" / "bin",
    ]

    added = 0
    for d in cuda_lib_dirs:
        if not d.is_dir():
            continue
        dir_str = str(d)
        # os.add_dll_directory — mecanismo preferencial (Python 3.8+).
        try:
            os.add_dll_directory(dir_str)
        except Exception as e:
            logger.debug("cuda_setup: add_dll_directory(%s) failed: %s", dir_str, e)
        # Também adicionar ao PATH (fallback para libs que usam LoadLibrary).
        if dir_str not in os.environ.get("PATH", ""):
            os.environ["PATH"] = dir_str + ";" + os.environ["PATH"]
        added += 1

    if added > 0:
        logger.info("cuda_setup: registered %d CUDA DLL directories from %s", added, sp)
    else:
        logger.debug("cuda_setup: no CUDA DLL directories found in %s", sp)

    return added > 0


# Auto-executar no import — garante que as DLLs estejam disponíveis
# antes de qualquer import de ctranslate2/faster_whisper.
setup_cuda_dlls()
