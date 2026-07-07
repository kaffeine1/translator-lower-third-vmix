# Builds the local-provider runtime pack (see app/local_runtime.py).
#
# The pack is a zip of a fresh `pip install --target` tree with the heavy
# local-provider packages, built with the SAME Python version/platform as the
# frozen app. Publish it as a GitHub release asset named
#   local-runtime-<PACK_VERSION>.zip
# under the tag local-runtime-<PACK_VERSION>, then update PACK_SHA256 and
# PACK_SIZE_BYTES in app/local_runtime.py with the values printed here.
#
# Usage:  .\scripts\build_local_runtime.ps1 [-PackVersion py314-cpu-1]

param([string]$PackVersion = "py314-cpu-1")

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "venv non trovato: $python" }

$tree = "build\local_runtime_pack"
if (-not (Test-Path $tree)) {
    Write-Host "Installo i pacchetti in $tree (puo' richiedere minuti)..."
    & $python -m pip install --quiet --target $tree faster-whisper transformers torch sentencepiece
    if ($LASTEXITCODE -ne 0) { throw "pip install fallita (exit $LASTEXITCODE)" }
}

# prune caches: __pycache__ triples the entry count for zero value
Get-ChildItem $tree -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

$zip = "dist\local-runtime-$PackVersion.zip"
New-Item -ItemType Directory -Force (Split-Path $zip) | Out-Null
if (Test-Path $zip) { Remove-Item $zip -Force }
Write-Host "Comprimo $tree -> $zip ..."
# python zipfile: Compress-Archive fails on >2GB trees and long paths
& $python -c @"
import os, zipfile
tree = r'$tree'
with zipfile.ZipFile(r'$zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for root, _dirs, files in os.walk(tree):
        for name in files:
            full = os.path.join(root, name)
            zf.write(full, os.path.relpath(full, tree))
print('zip scritto')
"@
if ($LASTEXITCODE -ne 0) { throw "compressione fallita" }

$fi = Get-Item $zip
$sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
Write-Host ""
Write-Host "== Valori per app/local_runtime.py =="
Write-Host ("PACK_VERSION    = " + $PackVersion)
Write-Host ("PACK_SHA256     = " + $sha)
Write-Host ("PACK_SIZE_BYTES = " + $fi.Length)
Write-Host ("asset: " + $zip + "  (" + [math]::Round($fi.Length/1MB, 1) + " MB)")
