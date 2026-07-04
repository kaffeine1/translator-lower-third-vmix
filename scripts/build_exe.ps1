# Build dell'eseguibile Windows con PyInstaller (modalità one-folder).
# Usa TranslatorLowerThird.spec, che gestisce hidden import e DLL (PortAudio,
# backend keyring, provider OpenAI caricato in modo lazy).
#
# Prerequisiti: ambiente virtuale con le dipendenze runtime + dev installate:
#   python -m venv .venv
#   .\.venv\Scripts\Activate.ps1
#   python -m pip install -r requirements.txt -r requirements-dev.txt
#
# Output: dist\TranslatorLowerThird\TranslatorLowerThird.exe

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

& $python -m PyInstaller --noconfirm --clean TranslatorLowerThird.spec
if ($LASTEXITCODE -ne 0) { throw "Build PyInstaller fallita (exit $LASTEXITCODE)" }

$exe = "dist\TranslatorLowerThird\TranslatorLowerThird.exe"
if (-not (Test-Path $exe)) { throw "Eseguibile non trovato: $exe" }
Write-Host "Build completata: $exe"
