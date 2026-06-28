# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('config.ini', '.')],
    hiddenimports=['pystray._win32', 'PIL.Image', 'PIL.ImageDraw', 'webview.platforms.winforms', 'core.registry', 'core.clipper', 'core.config', 'core.cache', 'core.logging_setup', 'data.builder', 'data.indicators', 'ui.tray', 'ui.panel', 'modules.prompt', 'modules.prompt.formula', 'core.alert_engine'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'pandas', 'matplotlib', 'scipy'],
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
    name='LingXi',
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
