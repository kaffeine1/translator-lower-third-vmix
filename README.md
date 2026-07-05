# Traduttore Live

> Live speech translation to a vMix lower-third — a Windows desktop app for live-production operators.

![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)
![UI](https://img.shields.io/badge/GUI-PySide6-41CD52)
![License](https://img.shields.io/badge/license-MIT-green)

**Traduttore Live** captures live speech audio, translates it in near real time and
writes the translated text into a **vMix** lower-third/title field over the local
HTTP API. It is built for non-technical live-production operators: install,
configure once, press **START**. No terminal, no JSON editing, no Python install
required on the operator's PC.

```text
Spanish live audio  →  Italian subtitle  →  vMix lower third
```

> The application UI and the operator messages are in **Italian**. A detailed
> Italian user manual is in **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**.

---

## Features

- **Italian GUI** with Audio / API / vMix **status lights**, live subtitle preview
  and one-click tests (Test Audio, Test API, Test vMix).
- **Provider-aware first-run wizard**: language & provider → the credentials it
  actually needs → provider test → audio → vMix → vMix test → save.
- **Multiple translation providers**, selectable from Settings (see below).
- **Audio capture** from any Windows input device, with a level meter.
- **Secure API keys** stored in the Windows Credential Manager — never in files,
  never in logs.
- **Anti-flicker subtitles**: aggregates partials, max two lines, de-duplicates,
  holds and clears after silence.
- **vMix output** via the HTTP API (`SetText`) with correct URL encoding, short
  timeouts and a light retry.
- **Rotating logs** with secret masking; an **About/diagnostics** panel.
- **Localization (i18n) infrastructure** ready for more languages (Italian shipped).

## Providers

| Provider | Type | Credentials | Notes |
|---|---|---|---|
| **OpenAI Realtime** | Cloud, speech→translation | OpenAI API key | Realtime translation over WebSocket. |
| **Demo (senza API)** | Local, no cost | — | Sample subtitles: try audio + vMix without any API. |
| **Demo (speech + traduzione separati)** | Local, no cost | — | Same, simulating the split speech/translation pipeline. |
| **Google Speech → DeepL** | Cloud, composed | Google credentials + DeepL key | Google STT + DeepL translation. |
| **Azure Speech → DeepL** | Cloud, composed | Azure key + region + DeepL key | Azure STT + DeepL translation. |
| **Locale (Faster-Whisper → MarianMT)** | Offline | — | Runs on your PC. Needs the optional packages (`requirements-optional.txt`) and, for smooth use, a GPU. |

> A ChatGPT Plus/Pro subscription is **not** API access — the app uses provider
> **APIs and API keys**, not a browser session.

The architecture keeps providers behind interfaces (`SpeechProvider`,
`TranslationProvider`, `RealtimeTranslationProvider`) so new providers are added
in the registry without touching the GUI.

---

## Install (operators)

1. Download and run **`TranslatorLowerThird-Setup.exe`**.
2. The build is **not code-signed**, so Windows SmartScreen shows an
   "unknown publisher" warning: choose *More info → Run anyway*.
3. Launch **Traduttore Live** from the Start menu. The first-run wizard guides you
   through provider, audio and vMix setup.

See the **[Italian user manual](docs/USER_GUIDE.md)** for the full walkthrough,
including how to configure vMix and each provider.

## vMix setup (quick)

Enable vMix **Settings → Web Controller** (default port `8088`), then in
*Settings → vMix* set host, port, the **Input/Title** name and the **text field**
(default `Headline.Text`). The app sends:

```text
http://HOST:PORT/api/?Function=SetText&Input=INPUT&SelectedName=FIELD&Value=TEXT
```

---

## Build from source

Requirements: Windows, Python 3.11+ (developed on 3.14), and — for the installer —
[Inno Setup 6](https://jrsoftware.org/isdl.php).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt -r requirements-dev.txt

python -m pytest          # run the test suite
python -m ruff check .    # lint
python -m app.main        # run in development

.\scripts\build_exe.ps1        # -> dist\TranslatorLowerThird\TranslatorLowerThird.exe
.\scripts\build_installer.ps1  # -> dist\installer\TranslatorLowerThird-Setup.exe
```

The PyInstaller spec (one-folder, windowed) bundles the non-obvious dependencies
automatically: the PortAudio DLL via `sounddevice`, the Windows `keyring` backend
and the lazily-imported providers. The installer installs per-machine under
*Program Files*, adds Start-menu (and optional desktop) shortcuts and an
uninstaller; user config and logs live under the user profile and are preserved
on uninstall.

> Optional cloud/local provider SDKs are **not** bundled by default; install
> `requirements-optional.txt` to use Google/Azure speech or the local models.

---

## Architecture

```text
Windows audio input
        ↓
RealtimeTranslationProvider   (or SpeechProvider + TranslationProvider)
        ↓
SubtitleFormatter             (anti-flicker, max 2 lines, clear-after-silence)
        ↓
VmixOutput                    (HTTP SetText)
        ↓
vMix title / lower third
```

The GUI drives the pipeline but contains no provider/audio/vMix business logic.
Details in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**; plans in
**[docs/ROADMAP.md](docs/ROADMAP.md)**; changes in
**[CHANGELOG.md](CHANGELOG.md)**.

## Configuration & logs

- Config: `%APPDATA%\TranslatorLowerThird\config.yaml` (non-sensitive only)
- Logs: `%LOCALAPPDATA%\TranslatorLowerThird\logs\` (`app.log`, `provider.log`, `vmix.log`)
- API keys: Windows Credential Manager (never in config or logs)

> The visible app name is "Traduttore Live"; the internal identifier
> (`TranslatorLowerThird`) is kept stable for folders, the executable and the
> credential service.

## Security

API keys are never committed, logged or stored in plaintext; audio is not written
to disk in normal operation; live paid-API tests are opt-in (`RUN_LIVE_TESTS=1`
with the relevant key set) and never run in the default test suite.

## License

Released under the [MIT License](LICENSE). Copyright © 2026 Michele Dipace.
