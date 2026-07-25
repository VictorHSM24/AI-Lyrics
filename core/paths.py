"""Resolução centralizada de caminhos de recursos (Sprint 23.0 fix).

Problema: em desenvolvimento, os caminhos relativos como ``config/books.json``
e ``data/sources/ACF.sqlite`` funcionam porque o cwd é a raiz do projeto.
Em bundle PyInstaller (frozen), o cwd é tipicamente ``System32`` ou o
diretório do executável, e os recursos empacotados ficam sob
``sys._MEIPASS`` (OneDir) ou um diretório temporário (OneFile).

Esta função resolve qualquer caminho relativo de recurso de forma que
funciona em ambos os modos:

    >>> from core.paths import resource_path
    >>> p = resource_path("config/books.json")
    >>> p.is_file()  # True em dev e em frozen

Política de resolução (em ordem):

1. Se ``relative_path`` é absoluto e existe, retorna-o.
2. Se ``relative_path`` relativo ao cwd existe, retorna-o (preserva
   comportamento de dev quando o usuário roda da raiz do projeto).
3. Em modo frozen (``sys.frozen``), retorna
   ``Path(sys._MEIPASS) / relative_path``.
4. Em modo dev, retorna ``relative_path`` relativo à raiz do projeto
   (computada como ``Path(__file__).resolve().parent.parent``, já que
   este módulo está em ``core/paths.py`` na raiz).

A função nunca levanta exceção; retorna um ``Path`` que pode ou não
existir. O caller é responsável por verificar ``is_file()``/``exists()``
e dar mensagem de erro apropriada.

Compatível com Windows e Linux. Não depende de nenhuma biblioteca
externa, apenas da stdlib.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = ["resource_path", "is_frozen", "bundle_root", "writable_root", "writable_path"]


def is_frozen() -> bool:
    """Retorna True se o processo está rodando dentro de um bundle PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Diretório raiz dos recursos empacotados.

    Em frozen: ``sys._MEIPASS`` (PyInstaller OneDir ou OneFile).
    Em dev: raiz do projeto (computada via ``__file__``).
    """
    if is_frozen():
        # PyInstaller define sys._MEIPASS apontando para o diretório
        # onde os recursos foram extraídos (OneDir: diretório do app;
        # OneFile: diretório temporário _MEIxxxx).
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        # Fallback: diretório do executável.
        return Path(sys.executable).resolve().parent
    # Dev: este módulo é core/paths.py, então a raiz do projeto é
    # dois níveis acima.
    return Path(__file__).resolve().parent.parent


def resource_path(relative_path: str | os.PathLike[str]) -> Path:
    """Resolve um caminho relativo de recurso para um ``Path`` absoluto.

    Ver política de resolução no docstring do módulo.

    Args:
        relative_path: Caminho relativo (ex.: ``"config/books.json"``,
            ``"data/sources/ACF.sqlite"``, ``"frontend/dist/index.html"``).

    Returns:
        ``Path`` absoluto apontando para o recurso. O path pode ou não
        existir; o caller deve verificar com ``is_file()``/``exists()``.
    """
    p = Path(relative_path)

    # 1. Absoluto: retorna como está.
    if p.is_absolute():
        return p

    # 2. Relativo ao cwd que existe: preserva comportamento de dev
    #    quando o usuário roda da raiz do projeto (compatibilidade
    #    com testes existentes que assumem cwd=repo root).
    cwd_relative = Path.cwd() / p
    if cwd_relative.exists():
        return cwd_relative

    # 3. Relativo à raiz do bundle (frozen) ou à raiz do projeto (dev).
    return bundle_root() / p


def writable_root() -> Path:
    """Diretório raiz para dados graváveis pelo app.

    Em frozen: ``%APPDATA%/AI Lyrics Assistant`` (Windows) ou
    ``~/.local/share/AI Lyrics Assistant`` (Linux). O bundle PyInstaller
    é read-only, então qualquer arquivo que o app precise modificar em
    runtime (config.overrides.json, state.json, logs, etc.) deve ir aqui.

    Em dev: raiz do projeto (mesmo que ``bundle_root()``), para que
    ``config/config.overrides.json`` continue sendo gravado no repo.
    """
    if is_frozen():
        if sys.platform == "win32":
            base = os.environ.get("APPDATA", str(Path.home()))
        else:
            # Linux/macOS: seguir XDG Base Directory Spec.
            base = os.environ.get(
                "XDG_DATA_HOME",
                str(Path.home() / ".local" / "share"),
            )
        return Path(base) / "AI Lyrics Assistant"
    return bundle_root()


def writable_path(relative_path: str | os.PathLike[str]) -> Path:
    """Resolve um caminho relativo para um local gravável.

    Em frozen: ``writable_root() / relative_path``.
    Em dev: ``bundle_root() / relative_path`` (preserva comportamento
    de gravar no repo durante desenvolvimento).

    Cria o diretório pai se não existir.

    Args:
        relative_path: Caminho relativo (ex.: ``"config/config.overrides.json"``,
            ``"data/state.json"``, ``"logs/pipeline.jsonl"``).

    Returns:
        ``Path`` absoluto apontando para o local gravável.
    """
    p = Path(relative_path)
    if p.is_absolute():
        return p
    resolved = writable_root() / p
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved
