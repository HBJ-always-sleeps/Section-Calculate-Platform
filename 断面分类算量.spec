# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['d:\\tunnel_build\\Code\\autoclassify_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('d:\\tunnel_build\\Code', 'Code')],
    hiddenimports=['ezdxf', 'pandas', 'shapely', 'shapely.geometry', 'shapely.ops'],
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
    name='断面分类算量',
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
