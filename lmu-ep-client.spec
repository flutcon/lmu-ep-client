# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

_q_datas, _q_binaries, _q_hidden = collect_all('questionary')
_pt_datas, _pt_binaries, _pt_hidden = collect_all('prompt_toolkit')
_wc_datas, _wc_binaries, _wc_hidden = collect_all('wcwidth')

# The GUI only uses QtCore, QtGui and QtWidgets. Collecting the whole of
# PySide6 bundled Qt WebEngine alone at ~290 MB (Qt6WebEngineCore.dll plus
# its .pak/ICU resources), as well as QtQuick/QML, Qt3D, QtMultimedia,
# QtPdf, etc. — none of which we use.
# Declaring just the three modules as hidden imports lets PyInstaller's
# per-module PySide6 hooks collect only what they need. They must be hidden
# imports because the actual imports are lazy (inside functions in gui.py /
# splash.py) and so are invisible to static analysis.
_qt_hidden = ['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets']

# Belt-and-suspenders: keep the heavy, unused Qt feature modules from being
# transitively pulled back in.
_qt_excludes = [
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineQuick',
    'PySide6.QtWebChannel',
    'PySide6.QtWebSockets',
    'PySide6.QtWebView',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuick3D',
    'PySide6.QtQuickControls2',
    'PySide6.QtQuickWidgets',
    'PySide6.Qt3DCore',
    'PySide6.Qt3DRender',
    'PySide6.Qt3DExtras',
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtCharts',
    'PySide6.QtDataVisualization',
    'PySide6.QtGraphs',
    'PySide6.QtDesigner',
    'PySide6.QtLocation',
    'PySide6.QtPositioning',
    'PySide6.QtSql',
    'PySide6.QtTest',
    'PySide6.QtSensors',
    'PySide6.QtSerialPort',
    'PySide6.QtSerialBus',
    'PySide6.QtBluetooth',
    'PySide6.QtNfc',
    'PySide6.QtRemoteObjects',
    'PySide6.QtScxml',
    'PySide6.QtStateMachine',
    'PySide6.QtTextToSpeech',
    'PySide6.QtVirtualKeyboard',
    'PySide6.QtHelp',
    'PySide6.QtNetworkAuth',
    'PySide6.QtSpatialAudio',
]

a = Analysis(
    ['src/lmu_ep_client/cli.py'],
    pathex=['src', 'vendor'],
    binaries=_q_binaries + _pt_binaries + _wc_binaries,
    datas=_q_datas + _pt_datas + _wc_datas,
    hiddenimports=_q_hidden + _pt_hidden + _wc_hidden + _qt_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_qt_excludes,
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
    # Windowed: double-click shows the splash + GUI with no black console.
    # CLI invocation reattaches to the parent terminal via AttachConsole at
    # startup (see stdio_setup.attach_parent_console).
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
