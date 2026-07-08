# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — one-folder build of Traduttore Live.

Builds dist/TranslatorLowerThird/TranslatorLowerThird.exe (no console).
PySide6 is handled by the official PyInstaller hooks; here we collect the
less obvious dependencies: sounddevice's PortAudio DLL, the keyring backends
and the dynamically used submodules.

Build:  pyinstaller --noconfirm --clean TranslatorLowerThird.spec
"""

import os
import re
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

# --- paths ------------------------------------------------------------------
# SPECPATH is the spec's folder (repository root): needed because the entry
# point is app/main.py but it imports the "app" package.
ROOT = os.path.abspath(SPECPATH)  # noqa: F821 (SPECPATH injected by PyInstaller)
ICON = os.path.join(ROOT, "assets", "icon.ico")
icon_arg = ICON if os.path.exists(ICON) else None

# --- version resource -------------------------------------------------------
# Read __version__ from app/__init__.py so the exe's file properties stay in
# sync with the single source of truth (no drift with the installer script).
with open(os.path.join(ROOT, "app", "__init__.py"), encoding="utf-8") as _f:
    _m = re.search(r'__version__\s*=\s*"([^"]+)"', _f.read())
_vstr = _m.group(1) if _m else "0.0.0"
_parts = [int(x) for x in _vstr.split(".")[:3]] + [0, 0, 0, 0]
_vtuple = tuple(_parts[:4])

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_vtuple, prodvers=_vtuple, mask=0x3F, flags=0x0,
                      OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Michele Dipace"),
            StringStruct("FileDescription", "Traduttore Live"),
            StringStruct("FileVersion", _vstr),
            StringStruct("InternalName", "TranslatorLowerThird"),
            StringStruct("LegalCopyright", "Copyright (C) 2026 Michele Dipace"),
            StringStruct("OriginalFilename", "TranslatorLowerThird.exe"),
            StringStruct("ProductName", "Traduttore Live"),
            StringStruct("ProductVersion", _vstr),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

# --- dependencies to collect ------------------------------------------------
datas = []
binaries = []
hiddenimports = []

# Keep project and third-party license notices in binary distributions.
for _notice in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
    _path = os.path.join(ROOT, _notice)
    if os.path.exists(_path):
        datas += [(_path, ".")]

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

# The downloadable runtime pack (torch, transformers, faster-whisper) imports
# standard-library modules that the app itself never references, so PyInstaller
# does not bundle them and the frozen app raises ModuleNotFoundError at runtime
# (observed: torch imports `timeit`). Bundle the whole stdlib so any module the
# pack needs is present; a few unwanted heavy/dev-only packages are left out and
# tkinter stays in `excludes` below.
_stdlib_skip = {
    "tkinter", "turtle", "turtledemo", "test", "idlelib", "lib2to3",
    "antigravity", "this", "ensurepip", "venv", "distutils", "pydoc_data",
}
hiddenimports += [m for m in sys.stdlib_module_names if m not in _stdlib_skip]


# The heavy local-provider packages ship via the downloadable runtime pack
# (see app/local_runtime.py), NOT inside the app bundle. They are installed in
# the dev venv for testing, and PyInstaller would otherwise follow the lazy
# function-level imports and balloon the build by gigabytes. Excluded modules
# still import fine at runtime from the activated pack on sys.path.
_local_runtime_excludes = [
    "torch",
    "torchgen",
    "functorch",
    "transformers",
    "faster_whisper",
    "ctranslate2",
    "sentencepiece",
    "onnxruntime",
    "av",
    "huggingface_hub",
    "hf_xet",
    "tokenizers",
    "safetensors",
    "sympy",
    "mpmath",
    "networkx",
    "jinja2",
    "fsspec",
    "filelock",
    "regex",
    "tqdm",
    "rich",
    "typer",
    "click",
    "shellingham",
    "markdown_it",
    "mdurl",
    "flatbuffers",
]

a = Analysis(
    [os.path.join("app", "main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "ruff"] + _local_runtime_excludes,
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
    version=version_info,  # embeds File/Product version + author in the exe
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TranslatorLowerThird",
)
