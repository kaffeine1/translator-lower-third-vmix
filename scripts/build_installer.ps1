# Genera TranslatorLowerThird-Setup.exe con Inno Setup 6.
#
# Prerequisiti:
#   1. Inno Setup 6 installato (https://jrsoftware.org/isdl.php) — fornisce ISCC.exe.
#   2. La build PyInstaller one-folder presente in dist\TranslatorLowerThird\
#      (esegui prima scripts\build_exe.ps1).
#
# Output: dist\installer\TranslatorLowerThird-Setup.exe

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# La build deve esistere, altrimenti l'installer conterrebbe una cartella vuota.
$exe = "dist\TranslatorLowerThird\TranslatorLowerThird.exe"
if (-not (Test-Path $exe)) {
    throw "Build mancante: $exe non trovato. Esegui prima scripts\build_exe.ps1."
}

# Trova ISCC.exe: percorsi standard di Inno Setup 6, poi PATH.
$candidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { $iscc = $cmd.Source }
}
if (-not $iscc) {
    Write-Error @"
Inno Setup 6 non trovato (ISCC.exe).
Installalo da https://jrsoftware.org/isdl.php e riprova,
oppure aggiungi la cartella di Inno Setup al PATH.
"@
    exit 1
}

Write-Host "Uso ISCC: $iscc"
& $iscc "installer\inno_setup.iss"
if ($LASTEXITCODE -ne 0) { throw "Compilazione installer fallita (exit $LASTEXITCODE)" }

$setup = "dist\installer\TranslatorLowerThird-Setup.exe"
if (-not (Test-Path $setup)) { throw "Installer non trovato: $setup" }
Write-Host "Installer generato: $setup"
