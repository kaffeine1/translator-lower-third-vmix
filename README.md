# Translator Lower Third for vMix

**Translator Lower Third for vMix** is a Windows desktop application that captures live speech audio, translates it in near real time, and sends the translated text to a vMix lower-third/title field.

Default scenario:

```text
Spanish live audio → Italian translated subtitle → vMix lower third
```

The application is designed for live production operators who should not need to use a terminal, edit JSON files, or understand API internals.

---

## What This App Does

The app runs on the same Windows machine as vMix, or on another machine that can reach the vMix HTTP API.

Runtime flow:

```text
Audio input
   ↓
Realtime translation provider
   ↓
Subtitle formatter
   ↓
vMix HTTP API
   ↓
Lower-third/title field
```

In the first release, the intended provider is OpenAI realtime translation. The architecture is modular so that Google, Azure, DeepL, local models, or a self-hosted translation server can be added later.

---

## Main Features Planned for v1.0

```text
Windows GUI in Italian
Audio input device selection
Audio test meter
OpenAI realtime translation provider
Spanish → Italian default translation
Subtitle anti-flicker buffer
Maximum two-line lower-third formatting
vMix HTTP API output
Test vMix button
Secure API key storage
Readable logs
PyInstaller executable
Inno Setup installer
```

---

## User Experience Goal

The final operator workflow should be:

```text
1. Install TranslatorLowerThird-Setup.exe
2. Open the app
3. Select audio input
4. Enter API key
5. Configure vMix
6. Press Test Audio
7. Press Test vMix
8. Press START
```

No terminal. No Python installation. No manual configuration files.

---

## Important Note About ChatGPT Subscriptions

A ChatGPT Plus/Pro subscription is not the same thing as API access.

For this application, provider access must be implemented through provider APIs and API keys. The app must not depend on a browser session or a normal ChatGPT subscription.

---

## vMix Requirements

vMix must have its web/API controller enabled and reachable.

Default connection values:

```text
Host: 127.0.0.1
Port: 8088
```

Default title text field:

```text
Headline.Text
```

Example vMix API call shape:

```text
http://127.0.0.1:8088/api/?Function=SetText&Input=Sottopancia&SelectedName=Headline.Text&Value=Test%20sottopancia
```

The actual `Input` and `SelectedName` must match the vMix title used in the production project.

---

## Audio Input Notes

The app should work with any Windows audio input device visible to the system:

```text
Microphone
Line input
USB audio device
Audio mixer output
Virtual audio cable
```

Virtual audio drivers such as VB-Cable can be useful when routing audio from vMix or another application, but they are not mandatory and should not be installed automatically in v1.

---

## Target Architecture

```text
app/
├─ gui/          # PySide6 windows, dialogs, widgets
├─ config/       # config files and secure secrets
├─ audio/        # device list, audio capture, audio levels
├─ providers/    # OpenAI, fake provider, future providers
├─ subtitles/    # subtitle formatting and anti-flicker logic
├─ outputs/      # vMix output and future outputs
└─ logging/      # log setup
```

Main pipeline:

```text
AudioInput
   ↓
RealtimeTranslationProvider
   ↓
SubtitleFormatter
   ↓
VmixOutput
```

The GUI must control the pipeline but must not contain provider-specific or vMix-specific business logic.

---

## Provider Strategy

The MVP can start with one provider:

```text
OpenAIRealtimeTranslationProvider
```

A fake provider must also exist for development and demos:

```text
FakeTranslationProvider
```

Future providers:

```text
Google Speech + Google Translate
Azure Speech + Azure Translator
DeepL text translation
Faster-Whisper local speech-to-text
MarianMT local translation
NLLB local translation
Self-hosted REST/WebSocket provider
```

Design rule:

```text
Do not hardcode provider logic into the GUI.
```

---

## Development Setup

Create a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

Run tests:

```powershell
python -m pytest
```

Run lint:

```powershell
python -m ruff check .
```

Run app in development mode:

```powershell
python -m app.main
```

---

## Build Executable

Install the dev dependencies (which include PyInstaller) into the virtual
environment, then run the build script:

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
.\scripts\build_exe.ps1
```

The script runs PyInstaller against `TranslatorLowerThird.spec` (one-folder,
windowed — no console). Expected output:

```text
dist/TranslatorLowerThird/TranslatorLowerThird.exe
```

The spec bundles the non-obvious dependencies automatically: the PortAudio DLL
via `sounddevice`, the Windows `keyring` backend, and the lazily-imported OpenAI
provider. If `assets/icon.ico` is present it is used as the app icon; otherwise
PyInstaller's default icon is used and the build still succeeds.

One-folder mode is used first: it is easier to debug with PySide6 and audio
dependencies than one-file. A clean-VM launch test is recommended before each
release.

---

## Build Installer

The installer is built with [Inno Setup 6](https://jrsoftware.org/isdl.php).
Install it first (it provides `ISCC.exe`), build the executable, then run the
installer script:

```powershell
.\scripts\build_exe.ps1          # produces dist\TranslatorLowerThird\
.\scripts\build_installer.ps1    # produces dist\installer\TranslatorLowerThird-Setup.exe
```

`build_installer.ps1` locates `ISCC.exe` (standard Inno Setup 6 install paths or
`PATH`) and compiles `installer\inno_setup.iss`. It fails with a clear message
if the PyInstaller build is missing or Inno Setup is not installed.

Expected output:

```text
dist\installer\TranslatorLowerThird-Setup.exe
```

The installer:

```text
Installs under Program Files (per-machine, requires admin)
Creates a Start Menu shortcut (+ uninstaller entry)
Optional Desktop shortcut (unchecked by default)
Includes an uninstaller
Does NOT require Python on the target PC (all bundled by PyInstaller)
Does NOT install virtual audio drivers
Italian installer UI
```

User configuration (`%APPDATA%\TranslatorLowerThird`) and logs
(`%LOCALAPPDATA%\TranslatorLowerThird\logs`) live under the user profile, so
uninstalling the app leaves them untouched.

---

## Configuration

User config should be stored here:

```text
%APPDATA%\TranslatorLowerThird\config.yaml
```

Logs should be stored here:

```text
%LOCALAPPDATA%\TranslatorLowerThird\logs\
```

Example non-sensitive config:

```yaml
provider: openai
source_language: es
target_language: it

audio:
  device_id: null
  sample_rate: 16000
  channels: 1

vmix:
  host: "127.0.0.1"
  port: 8088
  input: ""
  selected_name: "Headline.Text"

subtitles:
  max_chars_per_line: 42
  max_lines: 2
  min_update_interval_ms: 1200
  hold_seconds: 5
  clear_after_silence_seconds: 8
```

API keys must be stored securely using Windows secure storage or an equivalent mechanism. They must not be stored inside `config.yaml`.

---

## Security Rules

Mandatory rules:

```text
Never commit API keys.
Never log API keys.
Never store API keys in plaintext config.
Never save audio unless explicit debug mode is enabled.
Never run paid live API tests by default.
```

Recommended `.gitignore` entries:

```gitignore
.env
*.key
*.pem
config.local.yaml
logs/
dist/
build/
__pycache__/
.pytest_cache/
.ruff_cache/
```

---

## Testing Strategy

Use `pytest`.

Core tests:

```text
Config load/save
Secret masking
Subtitle formatting
vMix URL construction
vMix timeout handling
Fake provider events
Audio mock device list
Audio start/stop lifecycle
```

Live provider tests must be disabled by default and only run when explicitly enabled:

```text
OPENAI_API_KEY is set
RUN_LIVE_TESTS=1 is set
```

---

## First Implementation Target for Claude Code

Start with:

```text
Milestone 0 — Repository Bootstrap
Milestone 1 — Configuration and Logging
```

Do not start by implementing OpenAI.
Do not start by implementing real audio capture.
Do not start by implementing the full GUI.

First objective:

```text
Clean repository skeleton
Config manager
Secure secret storage wrapper
Logging setup
Basic tests
Documentation
```

---

## MVP Definition of Done

The MVP is done when:

```text
The app launches on Windows.
The user can select an audio input.
Test Audio shows activity.
The user can save an API key securely.
The user can configure vMix host, port, input and text field.
Test vMix writes a phrase into the title.
START begins the translation pipeline.
Translated text appears in GUI preview.
Translated text appears in vMix.
STOP shuts everything down cleanly.
Errors are readable.
Logs are accessible.
PyInstaller build works.
Inno Setup installer works.
Core tests pass.
```

---

## Troubleshooting Targets

The app should provide clear messages for:

```text
No audio input detected
Wrong audio device selected
API key missing
API key invalid
No internet connection
Provider unavailable
vMix not reachable
Wrong vMix input name
Wrong vMix text field
Subtitle update failed
```

Operator-facing messages should be simple and actionable.

---

## Future Roadmap Summary

```text
v1.0  MVP: OpenAI + vMix
v1.1  Provider registry and provider selector
v1.2  Google, Azure, DeepL providers
v1.3  Local models: Faster-Whisper, MarianMT, NLLB
v2.0  Self-hosted GPU server provider
v2.5  Glossary, names, event profiles, SRT export
v3.0  OBS, browser overlay, TXT/WebSocket outputs
```

See `docs/ROADMAP.md` for full details.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md). Current version: **0.1.0** (MVP).

## Troubleshooting

Operator-facing guidance (Italian) is in
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md); the in-app **Info** button
shows the version and the config/log paths.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Michele Dipace.
