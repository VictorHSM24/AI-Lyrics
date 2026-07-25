"""Orquestra o build completo do instalador AI Lyrics (Sprint 23.0).

Pipeline:
  1. npm run build        — builda frontend (frontend/dist/)
  2. python build_embeddings.py — gera data/bible.pt-br.sqlite + .npy
  3. pyinstaller ai-lyrics.spec — empacota em dist/ai-lyrics/ (OneDir)
  4. iscc installer/ai-lyrics.iss — gera dist-installer/ai-lyrics-setup-*.exe

Cada etapa é verificada: se falhar, aborta com mensagem clara.
Etapas opcionais podem ser puladas com flags --skip-frontend,
--skip-embeddings, --skip-pyinstaller, --skip-installer.

Uso:
  python build_installer.py
  python build_installer.py --skip-embeddings  # se bible.pt-br.sqlite já existe
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> int:
    """Executa comando, imprime saída em tempo real, retorna exit code."""
    print(f"\n$ {' '.join(cmd)}", flush=True)
    if cwd:
        print(f"  (cwd: {cwd})", flush=True)
    t0 = time.monotonic()
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    elapsed = time.monotonic() - t0
    print(f"  → exit {result.returncode} em {elapsed:.1f}s", flush=True)
    if check and result.returncode != 0:
        raise SystemExit(f"Falha: {' '.join(cmd)} (exit {result.returncode})")
    return result.returncode


def _require_tool(name: str, hint: str) -> str:
    """Verifica que uma ferramenta está no PATH; retorna caminho ou aborta."""
    found = shutil.which(name)
    if not found:
        print(f"ERRO: '{name}' não encontrado no PATH.", file=sys.stderr)
        print(f"  {hint}", file=sys.stderr)
        raise SystemExit(1)
    return found


# ---------------------------------------------------------------------------
# Etapas do build
# ---------------------------------------------------------------------------


def step_frontend() -> None:
    """1. Builda o frontend React (vite build → frontend/dist/)."""
    print("\n=== Etapa 1/4: Frontend (npm run build) ===", flush=True)
    npm = _require_tool("npm", "Instale Node.js 18+ de https://nodejs.org")
    frontend = ROOT / "frontend"
    # npm install se node_modules não existir.
    if not (frontend / "node_modules").exists():
        _run([npm, "install", "--no-audit", "--no-fund"], cwd=frontend)
    _run([npm, "run", "build"], cwd=frontend)
    dist = frontend / "dist"
    if not dist.exists():
        raise SystemExit(f"Frontend build não produziu {dist}")
    print(f"  ✓ {dist} gerado ({sum(f.stat().st_size for f in dist.rglob('*') if f.is_file()) / 1024:.0f} KB)")


def step_embeddings() -> None:
    """2. Gera data/bible.pt-br.sqlite + data/bible.embeddings.npy."""
    print("\n=== Etapa 2/4: Embeddings (build_embeddings.py) ===", flush=True)
    fts5 = ROOT / "data" / "bible.pt-br.sqlite"
    npy = ROOT / "data" / "bible.embeddings.npy"
    if fts5.exists() and npy.exists():
        print(f"  ✓ {fts5.name} ({fts5.stat().st_size / 1024 / 1024:.1f} MB) e {npy.name} ({npy.stat().st_size / 1024 / 1024:.1f} MB) já existem — pulando.")
        return
    script = ROOT / "build_embeddings.py"
    if not script.exists():
        raise SystemExit(f"{script} não encontrado")
    _run([sys.executable, str(script)])
    if not fts5.exists() or not npy.exists():
        raise SystemExit(f"build_embeddings.py não produziu {fts5} ou {npy}")
    print(f"  ✓ {fts5.name} ({fts5.stat().st_size / 1024 / 1024:.1f} MB) e {npy.name} ({npy.stat().st_size / 1024 / 1024:.1f} MB) gerados.")


def step_pyinstaller() -> None:
    """3. Empacota com PyInstaller (OneDir → dist/ai-lyrics/)."""
    print("\n=== Etapa 3/4: PyInstaller (ai-lyrics.spec) ===", flush=True)
    # Garante que pyinstaller está instalado.
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("  PyInstaller não instalado — instalando...", flush=True)
        _run([sys.executable, "-m", "pip", "install", "pyinstaller"])
    spec = ROOT / "ai-lyrics.spec"
    if not spec.exists():
        raise SystemExit(f"{spec} não encontrado")
    # Limpa build/ e dist/ anteriores para evitar resíduos.
    for d in [ROOT / "build", ROOT / "dist"]:
        if d.exists() and d.name == "build":
            shutil.rmtree(d, ignore_errors=True)
    _run([sys.executable, "-m", "PyInstaller", str(spec), "--noconfirm", "--clean"])
    out = ROOT / "dist" / "ai-lyrics"
    if not out.exists():
        raise SystemExit(f"PyInstaller não produziu {out}")
    exe = out / "ai-lyrics.exe"
    if not exe.exists():
        raise SystemExit(f"ai-lyrics.exe não encontrado em {out}")
    # Tamanho total do OneDir.
    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"  ✓ {out} gerado ({total / 1024 / 1024:.0f} MB)")


def step_installer() -> None:
    """4. Gera o instalador Inno Setup (dist-installer/ai-lyrics-setup-*.exe)."""
    print("\n=== Etapa 4/4: Inno Setup (installer/ai-lyrics.iss) ===", flush=True)
    # Tenta localizar iscc.exe em caminhos comuns.
    iscc = shutil.which("iscc")
    if not iscc:
        candidates = [
            r"C:\Program Files (x86)\Inno Setup 6\iscc.exe",
            r"C:\Program Files\Inno Setup 6\iscc.exe",
        ]
        for c in candidates:
            if Path(c).exists():
                iscc = c
                break
    if not iscc:
        print("ERRO: iscc.exe (Inno Setup Compiler) não encontrado.", file=sys.stderr)
        print("  Instale Inno Setup 6+ de https://jrsoftware.org/isdl.php", file=sys.stderr)
        print("  Pulando etapa de instalador. PyInstaller output em dist/ai-lyrics/.", file=sys.stderr)
        return
    iss = ROOT / "installer" / "ai-lyrics.iss"
    if not iss.exists():
        raise SystemExit(f"{iss} não encontrado")
    _run([iscc, str(iss)])
    out_dir = ROOT / "dist-installer"
    if not out_dir.exists():
        raise SystemExit(f"Inno Setup não produziu {out_dir}")
    exes = list(out_dir.glob("ai-lyrics-setup-*.exe"))
    if not exes:
        raise SystemExit(f"Nenhum ai-lyrics-setup-*.exe em {out_dir}")
    print(f"  ✓ Instalador gerado: {exes[0]} ({exes[0].stat().st_size / 1024 / 1024:.0f} MB)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Build do instalador AI Lyrics (Sprint 23.0)")
    parser.add_argument("--skip-frontend", action="store_true", help="Pular build do frontend")
    parser.add_argument("--skip-embeddings", action="store_true", help="Pular build_embeddings.py")
    parser.add_argument("--skip-pyinstaller", action="store_true", help="Pular PyInstaller")
    parser.add_argument("--skip-installer", action="store_true", help="Pular Inno Setup")
    args = parser.parse_args()

    print("AI Lyrics — Build do instalador (Sprint 23.0)", flush=True)
    print(f"Root: {ROOT}", flush=True)

    t0 = time.monotonic()
    try:
        if not args.skip_frontend:
            step_frontend()
        if not args.skip_embeddings:
            step_embeddings()
        if not args.skip_pyinstaller:
            step_pyinstaller()
        if not args.skip_installer:
            step_installer()
    except SystemExit as e:
        print(f"\nBUILD FALHOU: {e}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - t0
    print(f"\n{'=' * 60}", flush=True)
    print(f"BUILD CONCLUÍDO em {elapsed:.0f}s", flush=True)
    print(f"{'=' * 60}", flush=True)
    if not args.skip_installer:
        print("Instalador: dist-installer/ai-lyrics-setup-*.exe", flush=True)
    if not args.skip_pyinstaller:
        print("PyInstaller output: dist/ai-lyrics/", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
