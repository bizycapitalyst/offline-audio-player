# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = []
hiddenimports = ['edge_tts', 'edge_tts.communicate', 'edge_tts.constants', 'edge_tts.drm', 'edge_tts.exceptions', 'edge_tts.list_voices', 'edge_tts.submaker', 'edge_tts.typing', 'edge_tts.util', 'edge_tts.tts_config', 'certifi', 'charset_normalizer', 'docx', 'pypdf', 'ebooklib', 'bs4', 'deep_translator', 'deep_translator.google', 'deep_translator.constants', 'deep_translator.exceptions']
datas += collect_data_files('certifi')
hiddenimports += collect_submodules('edge_tts')
hiddenimports += collect_submodules('docx')
hiddenimports += collect_submodules('pypdf')
hiddenimports += collect_submodules('ebooklib')
hiddenimports += collect_submodules('deep_translator')


a = Analysis(
    ['prerender_gui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TTS_Converter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
