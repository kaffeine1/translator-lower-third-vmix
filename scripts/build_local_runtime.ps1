# Builds a local-provider runtime pack (see app/local_runtime.py).
#
# The pack is a zip of a fresh `pip install --target` tree with the heavy
# local-provider packages, built with the SAME Python version/platform as the
# frozen app. Two variants:
#   cpu  -> CPU-only (default)
#   cuda -> adds the NVIDIA CUDA libraries so faster-whisper runs on GPU
#           without a system CUDA install (cuBLAS + cuDNN + CUDA runtime)
#
# Publish it as a GitHub release asset named  local-runtime-<Version>.zip
# under the tag  local-runtime-<Version>, then paste the printed SHA-256 and
# size into PACKS[...] in app/local_runtime.py.
#
# Usage:  .\scripts\build_local_runtime.ps1 [-Variant cpu|cuda]

param([ValidateSet("cpu", "cuda")][string]$Variant = "cpu")

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# Pinned so the zip (and its SHA-256) is reproducible. The nvidia-* wheels ship
# the DLLs at nvidia\{cublas,cudnn,cuda_runtime}\bin\*.dll; torch stays the CPU
# build (CTranslate2 does the GPU work, not torch).
$packs = @{
    cpu  = @{
        Version = "py314-cpu-1"
        Pkgs    = @("faster-whisper", "transformers", "torch", "sentencepiece")
    }
    cuda = @{
        Version = "py314-cu124-1"
        Pkgs    = @("faster-whisper", "transformers", "torch", "sentencepiece",
            "nvidia-cublas-cu12==12.4.5.8",
            "nvidia-cudnn-cu12==9.5.0.50",
            "nvidia-cuda-runtime-cu12==12.4.127")
    }
}
$PackVersion = $packs[$Variant].Version

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "venv non trovato: $python" }

$tree = "build\local_runtime_pack_$Variant"
if (-not (Test-Path $tree)) {
    Write-Host "Installo i pacchetti ($Variant) in $tree (puo' richiedere minuti)..."
    & $python -m pip install --quiet --target $tree @($packs[$Variant].Pkgs)
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
Write-Host "== Valori per app/local_runtime.py (PACKS['$Variant']) =="
Write-Host ("PACK_VERSION    = " + $PackVersion)
Write-Host ("PACK_SHA256     = " + $sha)
Write-Host ("PACK_SIZE_BYTES = " + $fi.Length)
Write-Host ("asset: " + $zip + "  (" + [math]::Round($fi.Length / 1MB, 1) + " MB)")
