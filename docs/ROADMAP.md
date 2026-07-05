# ROADMAP.md

# Translator Lower Third for vMix — Roadmap

## Product Goal

Build a Windows desktop application that captures live speech audio, translates it in near real time, and sends the translated text to a vMix lower-third/title field.

Primary scenario:

```text
Spanish live audio → Italian subtitles/lower-third → vMix
```

The operator should not need technical knowledge. The app must be installable, configurable from a GUI, and usable with a simple `START` / `STOP` workflow.

---

## Strategic Direction

The product must start simple but be designed as a reusable platform.

Initial MVP:

```text
Audio input → OpenAI realtime translation → Subtitle formatter → vMix HTTP API
```

Future platform:

```text
Audio input
   ↓
Speech provider or realtime translation provider
   ↓
Translation provider
   ↓
Subtitle formatter
   ↓
Multiple outputs: vMix, OBS, TXT, SRT, WebSocket, browser overlay
```

Important architectural choice:

- v1 can use one provider.
- The code must still be structured around provider interfaces.
- No provider-specific logic should be embedded in the GUI.

---

# Milestones

## Milestone 0 — Repository Bootstrap

> **Status: ✅ completed 2026-07-03**

### Goal

Create a clean project foundation before implementation begins.

### Deliverables

```text
app/
tests/
docs/
scripts/
installer/
assets/
README.md
CLAUDE.md
docs/ROADMAP.md
pyproject.toml
requirements.txt
requirements-dev.txt
.gitignore
```

### Tasks

- Create repository structure.
- Create application entry point skeleton.
- Create placeholder packages.
- Create initial documentation.
- Create test skeleton.
- Configure lint/test tools.

### Acceptance Criteria

- Repository structure exists.
- `python -m pytest` runs, even if only skeleton tests exist.
- README explains project purpose.
- Architecture documentation exists.
- Claude Code has clear project instructions.

---

## Milestone 1 — Configuration and Logging

> **Status: ✅ completed 2026-07-03**

### Goal

Implement reliable config handling and safe logging.

### Deliverables

```text
app/config/models.py
app/config/manager.py
app/config/secrets.py
app/logging/setup.py
tests/test_config.py
```

### Features

- Load default config.
- Save user config.
- Create user directories automatically.
- Store API key securely.
- Mask secrets in logs and errors.
- Configure rotating logs.

### Suggested Config Paths

```text
%APPDATA%\TranslatorLowerThird\config.yaml
%LOCALAPPDATA%\TranslatorLowerThird\logs\
```

### Acceptance Criteria

- App creates config/log directories automatically.
- Config loads even when no previous config exists.
- Invalid config produces a clear recoverable error.
- API key is not stored in plain text in `config.yaml`.
- API key is never printed in logs.
- Tests cover config load/save and secret masking.

---

## Milestone 2 — GUI Base

> **Status: ✅ completed 2026-07-03** (wired to MockAppServices; the
> packaged-mode "no console" check happens in Milestone 8)

### Goal

Create the first usable Windows GUI shell.

### Deliverables

```text
app/gui/main_window.py
app/gui/settings_dialog.py
app/gui/first_run_wizard.py
app/gui/widgets.py
```

### Main Window

Required controls:

```text
Status Audio
Status API
Status vMix
Preview translated subtitle
START
STOP
Test Audio
Test API
Test vMix
Settings
Open Logs
```

### Settings Dialog

Required settings:

```text
Provider
API key
Source language
Target language
Audio input device
vMix host
vMix port
vMix input/title
vMix text field
Subtitle line length
Subtitle max lines
Minimum update interval
Hold duration
Clear-after-silence duration
```

### Acceptance Criteria

- App opens without console in packaged mode.
- GUI is in Italian.
- GUI does not freeze when buttons are clicked.
- Settings are loaded from config.
- Settings are saved to config.
- Buttons can be wired to fake services.

---

## Milestone 3 — Audio Input

> **Status: ✅ completed 2026-07-04** (real device enumeration + live level
> meter; capture streams to providers from Milestone 6 onward)

### Goal

Allow the operator to select and test an audio input source.

### Deliverables

```text
app/audio/devices.py
app/audio/input.py
app/audio/levels.py
tests/test_audio_mock.py
```

### Features

- Enumerate Windows audio input devices.
- Select audio device from GUI.
- Capture live audio chunks.
- Show audio level/activity meter.
- Start and stop capture cleanly.

### Defaults

```text
sample_rate: 16000
channels: 1
format: PCM-compatible stream for provider
```

### Acceptance Criteria

- Audio device dropdown is populated.
- `Test Audio` shows level movement when audio is present.
- Starting/stopping audio does not leave hanging threads.
- Missing device produces a clear GUI error.
- Audio mock tests pass.

---

## Milestone 4 — vMix Output

> **Status: ✅ completed 2026-07-04** (Test vMix writes the test phrase through
> the real HTTP API; the live pipeline wires in at Milestone 6)

### Goal

Send text to a configured vMix title/lower-third field.

### Deliverables

```text
app/outputs/vmix.py
tests/test_vmix_output.py
```

### Features

- Test vMix API connection.
- Send `SetText` command.
- Clear title text.
- Encode URL parameters safely.
- Handle timeout and unreachable vMix.

### Default Settings

```text
host: 127.0.0.1
port: 8088
selected_name: Headline.Text
```

### Endpoint Shape

```text
http://HOST:PORT/api/?Function=SetText&Input=INPUT&SelectedName=FIELD&Value=TEXT
```

### Acceptance Criteria

- `Test vMix` writes `Test sottopancia` to the configured vMix title.
- Accented characters are transmitted correctly.
- vMix unavailable does not crash the app.
- HTTP errors are shown in the GUI.
- URL construction tests pass.

---

## Milestone 5 — Subtitle Formatter

> **Status: ✅ completed 2026-07-04** (wired into the live pipeline at
> Milestone 6)

### Goal

Convert raw partial/final provider output into stable subtitles suitable for live lower-thirds.

### Deliverables

```text
app/subtitles/events.py
app/subtitles/formatter.py
tests/test_subtitle_formatter.py
```

### Features

- Clean repeated spaces.
- Reflow text into lines.
- Enforce max two lines.
- Enforce max characters per line.
- Avoid repeated identical updates.
- Avoid updates on every word.
- Support partial and final text events.
- Clear subtitle after silence.

### Default Rules

```text
max_chars_per_line: 42
max_lines: 2
min_update_interval_ms: 1200
hold_seconds: 5
clear_after_silence_seconds: 8
```

### Acceptance Criteria

- Long text is split into maximum two lines.
- Duplicate updates are suppressed.
- Partial text is throttled.
- Final text is emitted promptly.
- Subtitle clears after configured silence.
- Formatter tests pass.

---

## Milestone 6 — Fake Provider End-to-End Demo

> **Status: ✅ completed 2026-07-04** (START runs FakeTranslationProvider →
> formatter → vMix + GUI preview with no paid API; OpenAI swaps in at M7)

### Goal

Create a full demo pipeline without using paid APIs.

### Deliverables

```text
app/providers/base.py
app/providers/fake.py
tests/test_fake_provider.py
```

### Demo Pipeline

```text
FakeTranslationProvider
        ↓
SubtitleFormatter
        ↓
VmixOutput
        ↓
vMix title
```

### Features

- Fake provider emits partial text.
- Fake provider emits final text.
- Fake provider can simulate errors.
- GUI can run in fake/demo mode.

### Acceptance Criteria

- Full app can be tested without OpenAI key.
- Fake provider updates GUI preview.
- Fake provider can update vMix through configured output.
- Demo mode is useful for development and customer testing.

---

## Milestone 7 — OpenAI Realtime Translation Provider

> **Status: ✅ completed 2026-07-04** (isolated provider, key from secure
> storage, auto-reconnect, clean stop; live tests gated on
> `OPENAI_API_KEY` + `RUN_LIVE_TESTS=1`, otherwise a mocked WebSocket)

### Goal

Implement the real online provider for MVP.

### Deliverables

```text
app/providers/openai_realtime.py
app/providers/provider_registry.py
```

### Features

- Connect to OpenAI realtime translation service.
- Stream audio chunks.
- Receive translated Italian text.
- Emit partial/final events.
- Handle API key errors.
- Handle network errors.
- Stop cleanly.

### Requirements

- All OpenAI-specific code must live inside the provider module.
- GUI must only call provider interface methods.
- Provider must read API key from secure storage.
- Live tests must be opt-in.

### Live Test Gate

```text
OPENAI_API_KEY must be set
RUN_LIVE_TESTS=1 must be set
```

### Acceptance Criteria

- Spanish speech audio produces Italian text.
- GUI preview receives translated text.
- vMix receives formatted translated text.
- API/network errors are shown clearly.
- Stop closes websocket/session/audio pipeline cleanly.

---

## Milestone 8 — Packaging with PyInstaller

> **Status: ✅ completed 2026-07-04** (`TranslatorLowerThird.spec` one-folder
> build; the packaged exe launches without a console and writes its startup log
> — verified on the build machine. A clean-VM check remains for release.)

### Goal

Generate a Windows executable that does not require Python on the target machine.

### Deliverables

```text
scripts/build_exe.ps1
TranslatorLowerThird.spec
```

### Features

- PyInstaller one-folder build.
- Include PySide6 assets.
- Include sounddevice/PortAudio dependencies.
- Include app icon.
- Hide console window in release build.

### Acceptance Criteria

- Executable launches on a clean Windows machine or VM.
- GUI opens correctly.
- Config/log directories are created.
- Audio device list works.
- Fake provider demo works.
- vMix test works if vMix is running.

---

## Milestone 9 — Installer with Inno Setup

> **Status: ✅ completed 2026-07-04** (`installer/inno_setup.iss` +
> `build_installer.ps1` finalized: per-machine install, Start Menu shortcut,
> optional Desktop shortcut, uninstaller, user data preserved. Compiling the
> setup requires Inno Setup 6 on the build machine — not installed here, so the
> actual `.exe` compile is the remaining release step.)

### Goal

Create a simple Windows installer for non-technical users.

### Deliverables

```text
installer/inno_setup.iss
scripts/build_installer.ps1
TranslatorLowerThird-Setup.exe
```

### Installer Features

- Install app under `Program Files`.
- Create Start Menu shortcut.
- Optional Desktop shortcut.
- Include uninstaller.
- Do not require Python.
- Do not install virtual audio drivers in v1.

### Acceptance Criteria

- Installer runs normally on Windows.
- Application starts from Start Menu.
- Optional desktop icon works.
- Uninstall removes application files.
- User config/logs are preserved unless explicitly removed by user.

---

## Milestone 10 — MVP Polish

> **Status: ✅ completed 2026-07-04** (CHANGELOG, TROUBLESHOOTING, finalized
> USER_GUIDE, Info/diagnostics section in the GUI, generated app icon bundled
> into the build. Remaining before release: compile the Inno Setup installer,
> clean-VM test, and a real OpenAI key end-to-end run.)

### Goal

Make the application ready for first real-world use.

### Deliverables

```text
docs/USER_GUIDE.md
docs/TROUBLESHOOTING.md
CHANGELOG.md
```

### Features

- Improved error messages.
- Diagnostics screen.
- Open log folder button.
- App version display.
- Icon.
- User guide.
- Troubleshooting guide.

### Acceptance Criteria

- Non-technical operator can configure the app using the guide.
- Common failure states are clear:
  - no audio
  - invalid API key
  - no internet
  - vMix unreachable
  - wrong vMix title field
- MVP can be installed, configured, started, stopped, and uninstalled cleanly.

---

# Release Roadmap

## v1.0 — MVP Release

### Scope

```text
GUI Windows
Audio input selection
OpenAI realtime translation provider
Subtitle formatter
vMix HTTP API output
Secure API key storage
Logging
PyInstaller executable
Inno Setup installer
```

### Out of Scope

```text
Offline local models
Google/Azure/DeepL providers
OBS support
SRT export
Glossary
Multi-language output
Automatic VB-Cable installation
```

---

## v1.1 — Provider Architecture Upgrade

> **In progress (2026-07-04):** provider registry (`app/providers/registry.py`),
> GUI provider selector with explicit Demo mode, and the separate
> `SpeechProvider`/`TranslationProvider` interfaces with a
> `ComposedRealtimeProvider` adapter (`app/providers/composed.py`) are done.
> Still to do: provider-specific settings panels, then the v1.2 cloud providers.

### Goal

Make provider expansion clean and configurable.

### Features

```text
Provider registry
Provider selector in GUI
Separate SpeechProvider interface
Separate TranslationProvider interface
Combined RealtimeTranslationProvider support
Provider-specific settings panels
```

### Acceptance Criteria

- New providers can be added without touching GUI logic.
- Provider settings are validated consistently.
- Fake provider remains available for testing.

---

## v1.2 — Alternative Cloud Providers

> **In progress (2026-07-04):** `DeepLTranslationProvider` (translation),
> `GoogleSpeechProvider` and `AzureSpeechProvider` (cloud STT) implemented —
> vendor SDKs behind injectable engine factories (optional deps, lazy import),
> mocked tests, live gated on their API keys + `RUN_LIVE_TESTS=1`. Composed
> pipelines (e.g. Google/Azure Speech → DeepL) are buildable via
> `create_composed_provider`. **Remaining:** GUI multi-credential settings +
> exposing the composed cloud pipelines in the provider selector so an operator
> can actually pick and run them; real end-to-end validation with vendor keys.

### Goal

Reduce vendor lock-in and allow cost optimization.

### Candidate Providers

```text
Google Speech-to-Text
Google Translate
Azure Speech
Azure Translator
DeepL for text translation
```

### Possible Pipelines

```text
Google Speech → Google Translate → vMix
Azure Speech → Azure Translator → vMix
Google Speech → DeepL → vMix
OpenAI realtime → vMix
```

### Acceptance Criteria

- Operator can select provider from GUI.
- Provider-specific credentials are stored securely.
- Cost-sensitive deployments can choose cheaper provider combinations.

---

## v1.3 — Local Provider Mode

> **Started (2026-07-04):** `FasterWhisperSpeechProvider` (local STT) and
> `LocalMarianTranslationProvider` (local MT) implemented with injectable
> model factories, lazy optional imports, and mocked tests. Registered as the
> composed realtime pipeline "Locale (Faster-Whisper → MarianMT)" (no
> credentials). Model/device are configurable in Settings with a hardware note.
> Remaining: real end-to-end validation on a GPU machine, and a latency
> benchmark tool.

### Goal

Support offline or private processing on adequate hardware.

### Candidate Models

```text
Faster-Whisper for speech-to-text
MarianMT for ES → IT translation
NLLB for multilingual translation
M2M100 as optional translation model
```

### Important Constraint

Local mode is only realistic on adequate hardware. For live use, a workstation with a proper NVIDIA GPU is strongly recommended. CPU-only mode may work for tests but can introduce high latency.

### Acceptance Criteria

- GUI warns if local hardware is insufficient.
- Benchmark tool estimates latency.
- Local provider can be enabled only after model download/configuration.
- Cloud mode remains the default for v1.x.

---

## v2.0 — Self-hosted Provider

### Goal

Allow a lightweight vMix PC to use a private GPU server for transcription and translation.

### Architecture

```text
vMix PC
  ↓ local app
Self-hosted server over LAN/VPN
  ↓
Whisper / Faster-Whisper
  ↓
MarianMT / NLLB / other translation engine
  ↓
translated text back to app
  ↓
vMix
```

### Features

```text
REST/WebSocket server
Authentication token
GPU server health check
Latency monitor
Multi-client support
Server logs
```

### Acceptance Criteria

- vMix client app can use self-hosted endpoint as a provider.
- Server can serve one or more clients.
- Provider behaves like other providers from the GUI perspective.

---

## v2.5 — Professional Live Production Features

### Goal

Make the tool more useful for real events.

### Features

```text
Custom glossary
Proper-name correction
Event-specific terminology
Speaker names
Phrase replacement rules
Transcript export
SRT export
Session history
Preset profiles per event
```

### Acceptance Criteria

- Operator can load an event profile.
- Glossary improves translation consistency.
- Transcript/SRT export works after event.

---

## v3.0 — Output Expansion

### Goal

Support production workflows beyond vMix.

### Outputs

```text
OBS Studio
Live TXT file
Browser overlay
WebSocket output
REST webhook
SRT file
```

### Acceptance Criteria

- Output modules follow a common interface.
- Multiple outputs can be active at once.
- vMix output remains fully supported.

---

# Engineering Notes

## Development Order

Recommended order:

```text
1. Bootstrap
2. Config/logging
3. GUI shell
4. Audio device list and test meter
5. vMix output
6. Subtitle formatter
7. Fake provider E2E
8. OpenAI provider
9. Packaging
10. Installer and polish
```

Do not start with OpenAI integration. Build the internal pipeline first using fake data.

---

## Risk Register

### Risk: Provider API changes

Mitigation:

- Isolate provider code.
- Keep provider tests separate.
- Consult official provider documentation before implementation.

### Risk: vMix field misconfiguration

Mitigation:

- Provide `Test vMix` button.
- Use clear error messages.
- In future, load vMix inputs/fields from API where possible.

### Risk: Audio device confusion

Mitigation:

- Provide audio level meter.
- Show selected input clearly.
- Document VB-Cable as optional.

### Risk: API cost surprises

Mitigation:

- Show provider in use.
- Add future usage/cost estimate.
- Use fake provider for testing.

### Risk: User has no internet

Mitigation:

- Show clear error in v1.
- Add local/self-hosted providers in future versions.

### Risk: Low-end PC cannot handle local models

Mitigation:

- Keep cloud default.
- Add benchmark and hardware warning for local mode.

---

# MVP Success Criteria

The MVP is successful when a non-technical live operator can:

```text
1. Install the application.
2. Open it from Start Menu.
3. Choose audio input.
4. Enter API key.
5. Configure vMix host/input/text field.
6. Test audio.
7. Test vMix.
8. Press START.
9. See Italian translated text in vMix.
10. Press STOP.
11. Read understandable logs if something fails.
```
