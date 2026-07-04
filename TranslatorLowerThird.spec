# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — one-folder build of Translator Lower Third for vMix.

Builds dist/TranslatorLowerThird/TranslatorLowerThird.exe (no console).
PySide6 is handled by the official PyInstaller hooks; here we collect the
less obvious dependencies: sounddevice's PortAudio DLL, the keyring backends
and the dynamically used submodules.

Build:  pyinstaller --noconfirm --clean TranslatorLowerThird.spec
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# --- paths ------------------------------------------------------------------
# SPECPATH is the spec's folder (repository root): needed because the entry
# point is app/main.py but it imports the "app" package.
ROOT = os.path.abspath(SPECPATH)  # noqa: F821 (SPECPATH injected by PyInstaller)
ICON = os.path.join(ROOT, "assets", "icon.ico")
icon_arg = ICON if os.path.exists(ICON) else None

# --- dependencies to collect ------------------------------------------------
datas = []
binaries = []
hiddenimports = []

# icon as a data file: used at runtime for the window icon (as well as for
# the exe icon)
if os.path.exists(ICON):
    datas += [(ICON, "assets")]

# sounddevice ships the PortAudio DLL (_sounddevice_data)
for _pkg in ("sounddevice",):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# keyring loads its backends at runtime via entry points / dynamic imports
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += [
    "keyring.backends.Windows",
    "win32ctypes.core",
    "win32ctypes.pywin32.win32cred",
]

# websockets/httpx/yaml/numpy are covered by their hooks or are pure; the
# OpenAI provider is imported lazily, so we declare it explicitly
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
    console=False,  # GUI app: no console window
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
