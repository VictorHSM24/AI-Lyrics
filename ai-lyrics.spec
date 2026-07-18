# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec para AI Lyrics Assistant
# Build: pyinstaller ai-lyrics.spec

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# Coletar dados do pysilero-vad (modelo ggml-silero-v6.2.0.bin)
pysilero_datas = collect_data_files('pysilero_vad')
pysilero_libs = collect_dynamic_libs('pysilero_vad')

# Coletar dados e libs do sounddevice (PortAudio)
sounddevice_datas = collect_data_files('sounddevice')
sounddevice_libs = collect_dynamic_libs('sounddevice')

# Coletar dados do config (books.json, config.yaml)
config_datas = [
    ('config/books.json', 'config'),
    ('config/config.yaml', 'config'),
]

# Coletar dados do data/ (Bíblia, embeddings, state)
data_files = []
if os.path.exists('data/bible.pt-br.sqlite'):
    data_files.append(('data/bible.pt-br.sqlite', 'data'))
if os.path.exists('data/bible.embeddings.npy'):
    data_files.append(('data/bible.embeddings.npy', 'data'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=pysilero_libs + sounddevice_libs,
    datas=pysilero_datas + sounddevice_datas + config_datas + data_files,
    hiddenimports=[
        'pysilero_vad',
        'pysilero_vad.silero_vad',
        'sounddevice',
        '_sounddevice_data',
        'numpy',
        'yaml',
        'requests',
        'json',
        'sqlite3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch',
        'torchaudio',
        'torchvision',
        'webrtcvad',
        'matplotlib',
        'tkinter',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
