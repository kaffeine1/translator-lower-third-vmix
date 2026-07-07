@echo off
rem Traduttore Live: avvio dal sorgente con il venv del progetto (doppio clic).
rem Serve per i provider LOCALI, i cui pacchetti opzionali esistono solo nel
rem venv (non sono inclusi nella versione installata). pythonw = senza console.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Ambiente Python non trovato: .venv\Scripts\pythonw.exe
    echo Crea il venv e installa i requisiti come descritto nel README.
    pause
    exit /b 1
)
start "Traduttore Live" .venv\Scripts\pythonw.exe -m app.main
