# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

_q_datas, _q_binaries, _q_hidden = collect_all('questionary')
_pt_datas, _pt_binaries, _pt_hidden = collect_all('prompt_toolkit')
_wc_datas, _wc_binaries, _wc_hidden = collect_all('wcwidth')
_qt_datas, _qt_binaries, _qt_hidden = collect_all('PySide6')

a = Analysis(
    ['src/lmu_ep_client/cli.py'],
    pathex=['src', 'vendor'],
    binaries=_q_binaries + _pt_binaries + _wc_binaries + _qt_binaries,
    datas=_q_datas + _pt_datas + _wc_datas + _qt_datas,
    hiddenimports=_q_hidden + _pt_hidden + _wc_hidden + _qt_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='lmu-ep-client',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Keep one executable usable for both CLI output and GUI launch; this also
    # means Windows double-clicks show a console alongside the GUI.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
