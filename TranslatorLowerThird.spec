# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — build one-folder di Translator Lower Third for vMix.

Costruisce dist/TranslatorLowerThird/TranslatorLowerThird.exe (nessuna console).
PySide6 è gestito dai hook ufficiali di PyInstaller; qui raccogliamo le
dipendenze meno ovvie: la DLL PortAudio di sounddevice, i backend di keyring e
i sottomoduli usati dinamicamente.

Build:  pyinstaller --noconfirm --clean TranslatorLowerThird.spec
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# --- percorsi ---------------------------------------------------------------
# SPECPATH è la cartella dello spec (radice del repository): serve perché
# l'entry point è app/main.py ma importa il pacchetto "app".
ROOT = os.path.abspath(SPECPATH)  # noqa: F821 (SPECPATH iniettato da PyInstaller)
ICON = os.path.join(ROOT, "assets", "icon.ico")
icon_arg = ICON if os.path.exists(ICON) else None

# --- dipendenze da raccogliere ---------------------------------------------
datas = []
binaries = []
hiddenimports = []

# icona come file dati: usata a runtime per l'icona della finestra (oltre che
# come icona dell'exe)
if os.path.exists(ICON):
    datas += [(ICON, "assets")]

# sounddevice porta con sé la DLL PortAudio (_sounddevice_data)
for _pkg in ("sounddevice",):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# keyring carica i backend a runtime tramite entry point / import dinamici
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += [
    "keyring.backends.Windows",
    "win32ctypes.core",
    "win32ctypes.pywin32.win32cred",
]

# websockets/httpx/yaml/numpy sono coperti dai loro hook o sono puri; il
# provider OpenAI è importato in modo lazy, quindi lo dichiariamo esplicito
hiddenimports += [
    "app.providers.openai_realtime",
    "app.providers.fake",
    "websockets",
]


a = Analysis(
    [os.path.join("app", "main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "ruff"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TranslatorLowerThird",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # app GUI: nessuna finestra console
    icon=icon_arg,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TranslatorLowerThird",
)
