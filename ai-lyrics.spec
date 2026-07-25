# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec para AI Lyrics Assistant (Sprint 23.0 — OneDir Beta).
#
# Build: pyinstaller ai-lyrics.spec
#
# Empacota em modo OneDir (diretório dist/ai-lyrics/) para melhor
# inicialização e menor taxa de falsos positivos de antivírus que
# OneFile. Inclui:
#   - Python runtime + dependências (torch CPU-only, faster-whisper,
#     pysilero-vad, sounddevice/PortAudio, sentence-transformers).
#   - Dados da Bíblia (data/sources/*.sqlite, bible_source.json,
#     bible.pt-br.sqlite, bible.embeddings.npy, embeddings.json).
#   - Configuração padrão (config/*.yaml, *.json).
#   - Frontend buildado (frontend/dist/) servido pela API.
#   - Entry point main.py (wizard de primeira execução + uvicorn).
#
# Exclui:
#   - tools/internal/ (ferramentas dev — item 16 do enunciado).
#   - tests/ (suíte de testes — não necessária em runtime).
#   - scripts _diag_*, _bench_*, _smoke_* (já movidos para tools/internal).
#   - matplotlib, tkinter, webrtcvad (não usados).

import os
import sys
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

block_cipher = None

# -------------------------------------------------------------------
# Coletar dados e libs de extensões nativas
# -------------------------------------------------------------------

# pysilero-vad (modelo ggml-silero-v6.2.0.bin embutido no wheel)
pysilero_datas = collect_data_files('pysilero_vad')
pysilero_libs = collect_dynamic_libs('pysilero_vad')

# sounddevice (PortAudio.dll)
sounddevice_datas = collect_data_files('sounddevice')
sounddevice_libs = collect_dynamic_libs('sounddevice')

# sentence-transformers (config do modelo HuggingFace baixado no build)
try:
    st_datas = collect_data_files('sentence_transformers')
except Exception:
    st_datas = []

# -------------------------------------------------------------------
# Dados do projeto (Categoria A — versionados + Categoria C gerada no build)
# -------------------------------------------------------------------

project_datas = []

# Configuração padrão (Categoria A).
for f in ['config/books.json', 'config/config.yaml', 'config/knowledge_base.json',
          'config/config.overrides.json']:
    if os.path.exists(f):
        project_datas.append((f, 'config'))

# Bases SQLite do BibleRetriever (Categoria A — 7 versões).
for sqlite in ['ACF', 'ARA', 'ARC', 'JFAA', 'NAA', 'NTLH', 'NVT']:
    p = f'data/sources/{sqlite}.sqlite'
    if os.path.exists(p):
        project_datas.append((p, 'data/sources'))

# Fonte bíblica canônica + embeddings JSON (Categoria A).
for f in ['data/bible_source.json', 'data/bible.embeddings.json']:
    if os.path.exists(f):
        project_datas.append((f, 'data'))

# Sample de áudio (Categoria A — usado por testes de STT).
if os.path.exists('data/stt_benchmark_sample.wav'):
    project_datas.append(('data/stt_benchmark_sample.wav', 'data'))

# Base FTS5 e embeddings .npy (Categoria C — gerados por build_embeddings.py).
# Devem ser gerados ANTES de rodar pyinstaller (build_installer.py orquestra).
for f in ['data/bible.pt-br.sqlite', 'data/bible.embeddings.npy']:
    if os.path.exists(f):
        project_datas.append((f, 'data'))

# Frontend buildado (Categoria C — gerado por `npm run build`).
# Incluído como árvore completa sob frontend/dist.
frontend_dist = 'frontend/dist'
if os.path.exists(frontend_dist):
    for root, dirs, files in os.walk(frontend_dist):
        for fn in files:
            src = os.path.join(root, fn)
            dst = os.path.relpath(root, '.')
            project_datas.append((src, dst))

# -------------------------------------------------------------------
# Coleta automática de submódulos do projeto (Sprint 23.0 fix)
# -------------------------------------------------------------------
# Em vez de manter uma lista manual de hiddenimports por pacote, usa
# collect_submodules() para descobrir automaticamente TODOS os
# submódulos de cada pacote do projeto. Isso garante que novos
# módulos adicionados no futuro sejam incluídos no bundle sem
# necessidade de editar este .spec.
#
# "api.app" é incluído automaticamente por collect_submodules("api"),
# mas é listado explicitamente abaixo como garantia adicional, já
# que é o ponto de entrada da aplicação FastAPI importado por main.py.

project_hiddenimports = (
    collect_submodules('api')
    + collect_submodules('busca')
    + collect_submodules('config')
    + collect_submodules('context')
    + collect_submodules('core')
    # estado: collect_submodules falha por import circular pré-existente
    # (estado/__init__.py importa de estado.state que reimporta o pacote).
    # Listado manualmente — apenas 2 módulos no pacote.
    + ['estado', 'estado.state']
    + collect_submodules('evaluation')
    + collect_submodules('feedback')
    + collect_submodules('integracao_holyrics')
    + collect_submodules('intelligence')
    + collect_submodules('knowledge')
    + collect_submodules('llm')
    + collect_submodules('microfone')
    + collect_submodules('parser')
    + collect_submodules('pipeline')
    + collect_submodules('presentation')
    + collect_submodules('semantic')
    + collect_submodules('sermon')
    + collect_submodules('telemetry')
    + collect_submodules('transcricao')
)

# -------------------------------------------------------------------
# Analysis
# -------------------------------------------------------------------

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=pysilero_libs + sounddevice_libs,
    datas=pysilero_datas + sounddevice_datas + st_datas + project_datas,
    hiddenimports=[
        # Extensões nativas e dependências críticas.
        'pysilero_vad',
        'pysilero_vad.silero_vad',
        'sounddevice',
        '_sounddevice_data',
        'numpy',
        'yaml',
        'requests',
        'json',
        'sqlite3',
        # uvicorn: submódulos necessários para uvicorn.run(app, ...).
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # FastAPI + Pydantic.
        'fastapi',
        'pydantic',
        # Ponto de entrada da aplicação FastAPI (importado explicitamente
        # por main.py via `from api.app import app`). Incluído também via
        # collect_submodules("api") acima, mas repetido aqui como garantia
        # explícita para evitar o erro "Could not import module api.app".
        'api.app',
    ] + project_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # torch/torchaudio/torchvision NÃO são excluídos — sentence-transformers
        # requer torch em runtime. A versão CPU-only (~200MB) é instalada por
        # padrão via pyproject.toml; a GPU/CUDA é oferecida pelo wizard se
        # NVIDIA for detectada (decisão da Sprint 23.0).
        'webrtcvad',
        'matplotlib',
        'tkinter',
        'pytest',
        # Ferramentas internas não entram no instalador (item 16).
        'tools',
        # Testes não entram no runtime.
        'tests',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# -------------------------------------------------------------------
# EXE + COLLECT (OneDir)
# -------------------------------------------------------------------

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ai-lyrics',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ai-lyrics',
)
