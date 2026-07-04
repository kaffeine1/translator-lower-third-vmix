# Architecture — Translator Lower Third for vMix

## Overview

Windows desktop application that captures live speech audio, translates it in near real time
through a pluggable provider, formats the translated text as a broadcast-safe subtitle, and
pushes it to a vMix lower-third/title field over the vMix HTTP API.

Runtime pipeline:

```text
Windows audio input
        ↓
AudioInput                (app/audio)
        ↓  PCM chunks (16 kHz mono by default)
RealtimeTranslationProvider (app/providers)
        ↓  partial/final translated text events
SubtitleFormatter         (app/subtitles)
        ↓  stable, deduplicated, max-2-line text
VmixOutput                (app/outputs)
        ↓  HTTP GET /api/?Function=SetText&...
vMix Title / Lower Third
```

The GUI (`app/gui`) orchestrates the pipeline lifecycle (START/STOP, tests, status lights) but
contains **no** provider-, audio-, or vMix-specific business logic.

## Module Map

```text
app/
├─ main.py        # entry point: config + logging bootstrap, first-run wizard, main window
├─ services.py    # AppServices interface + MockAppServices — the only surface the GUI calls
├─ gui/           # PySide6 windows, dialogs, widgets — Italian UI
├─ config/        # models.py (dataclasses), manager.py (YAML I/O + paths), secrets.py (keyring)
├─ audio/         # devices.py (enumeration), input.py (capture), levels.py (meter)
├─ providers/     # base.py (interface), fake.py (dev/demo), openai_realtime.py (v1 real)
├─ subtitles/     # events.py (text events), formatter.py (anti-flicker, line reflow)
├─ outputs/       # vmix.py (HTTP API client)
└─ logging/       # setup.py (rotating logs, secret masking)
```

### Service layer (`app/services.py`)

The GUI never talks to audio, providers, or vMix directly: it calls
`AppServices` (`start_audio_monitor()`/`stop_audio_monitor()`, `test_api()`,
`test_vmix()`, `start_translation()`, `stop_translation()`,
`list_audio_devices()`), each returning a `ServiceResult(ok, message)` with an
operator-readable Italian message. `MockAppServices` fakes everything for
tests/demo; `LiveAudioAppServices` (Milestone 3) wires real audio while API
and vMix stay mocked until their milestones — no GUI changes required.
Subtitle text and audio levels reach the GUI through listener callbacks that
emit Qt signals, so audio/provider threads never touch widgets directly.

The Test Audio button is a toggle: it starts a live monitor (RMS meter driven
from the PortAudio callback), auto-stops after 5 seconds, and reports
"Audio rilevato" (green) or "Nessun audio in ingresso" (red) based on the
observed peak.

Dialogs (`SettingsDialog`, `FirstRunWizard`) are pure: they build an
`AppConfig` via `result_config()` and expose the typed API key via
`entered_api_key()`; the caller persists both. Saved API keys are never
pre-filled into the password field.

## Key Interfaces

### AudioInput (`app/audio/input.py`)

- `list_devices() -> list[AudioDevice]`
- `start(device_id, sample_rate, channels)` / `stop()` / `is_running()`
- Emits normalized PCM chunks (default 16 kHz mono) via callback.
- Capture runs on a worker thread; never blocks the GUI thread.

### RealtimeTranslationProvider (`app/providers/base.py`)

- `async connect(config)` / `async send_audio(chunk)` / `async close()`
- `on_partial_text(cb)` / `on_final_text(cb)` / `on_error(cb)`
- v1 implementation: `OpenAIRealtimeTranslationProvider` (Milestone 7) —
  streams PCM16 over a WebSocket to the OpenAI Realtime API, configures the
  session to translate source→target and emits the translated text as
  partial/final events. **All** OpenAI-specific logic lives in
  `app/providers/openai_realtime.py`; the WebSocket connector is injectable so
  tests run without network. The API key is read from the `SecretStore` (never
  from `config.yaml`) and never appears in logs or error messages. The first
  `connect()` is synchronous so auth/network failures surface immediately; a
  background task then handles receive plus auto-reconnect with exponential
  backoff, and `close()` cancels it cleanly. `check_api_key()` validates a key
  by opening and closing a session without sending audio (no token cost).
  `LiveAppServices._make_provider()` picks this provider when a key is saved
  and falls back to `FakeTranslationProvider` otherwise — the GUI is unchanged.
- Dev implementation: `FakeTranslationProvider` (Milestone 6) — no paid API usage.
- Split (v1.1, `app/providers/composed.py`): `SpeechProvider` (audio → source
  text) and `TranslationProvider` (source text → translated text) are separate
  interfaces; `ComposedRealtimeProvider` combines them and satisfies
  `RealtimeTranslationProvider`, so pipelines like Google Speech → DeepL or
  Faster-Whisper → MarianMT compose without GUI/pipeline changes. Both providers
  and the combined one share the `TextEventEmitter` mixin. The composed adapter
  drops translations of superseded partials (sequence guard) to avoid flicker
  from slow/out-of-order translators. Fakes (`FakeSpeechProvider`,
  `FakeTranslationTextProvider`) and a `demo-composed` registry entry allow
  testing/demoing the split with no API usage.
- Provider registry (`app/providers/registry.py`, v1.1): the single place where
  providers are declared (id, display name, whether they need an API key). The
  Settings dialog builds its provider selector from it and `LiveAppServices`
  creates the provider through `create_provider()`. `config.provider` selects
  which one runs; a provider that needs a key but has none falls back to the
  demo (fake) provider so the GUI stays usable. Adding a future provider means
  registering it here — no GUI or service changes.

### SubtitleFormatter (`app/subtitles/formatter.py`)

Anti-flicker rules (defaults from config):

```text
max_chars_per_line: 42
max_lines: 2
min_update_interval_ms: 1200
hold_seconds: 5
clear_after_silence_seconds: 8
```

- Publishes final segments promptly; partials when stable for the configured
  interval, or at that cadence during long utterances (so a 10-second sentence
  still reaches the screen without per-word flicker).
- Never emits identical consecutive updates.
- Reflows text to at most two lines, keeping the LAST lines on overflow
  (recent words matter on a live lower third).
- Clears the title after prolonged silence, never sooner than `hold_seconds`
  from the last publish.
- Driven externally: `feed_partial`/`feed_final` from the provider thread,
  `tick()` every ~250 ms from the pipeline; injectable clock makes the tests
  fully deterministic. The publish callback must be fast — vMix I/O is queued
  by the pipeline (Milestone 6), never done inside the formatter.

### VmixOutput (`app/outputs/vmix.py`)

- `test_connection()` (parses the vMix version from the `/api` XML),
  `set_text(text)`, `clear_text()`, context-manager support.
- Endpoint: `http://HOST:PORT/api/?Function=SetText&Input=INPUT&SelectedName=FIELD&Value=TEXT`
- URL parameters are encoded by httpx, never string-concatenated.
- 2 s timeout, one retry on transport errors only (an HTTP error status is
  never retried); failures raise `VmixError` with an Italian operator message.
- GUI callers go through `MainWindow._call_service_async`, which runs the
  operation on a worker thread and marshals the result back via a Qt signal —
  Test API/Test vMix never freeze the GUI and their buttons disable while a
  call is in flight.

### Configuration (`app/config`)

- `models.py` — typed dataclasses with tolerant `from_dict` parsing: unknown keys are ignored,
  invalid values fall back to defaults so a hand-edited or corrupt config never crashes the app.
- `manager.py` — `ConfigManager` loads/saves `%APPDATA%\TranslatorLowerThird\config.yaml`.
  A corrupt file is backed up to `config.yaml.bak` and replaced with defaults; the recovery is
  reported through `load_warning` so the GUI can show a readable message.
- `secrets.py` — API keys go through `SecretStore` implementations:
  `KeyringSecretStore` (Windows Credential Manager via `keyring`) in production,
  `InMemorySecretStore` in tests. Keys never touch `config.yaml`, logs, or exception text —
  `mask_secret()` is used anywhere a key could be echoed.

### Logging (`app/logging/setup.py`)

- Rotating files under `%LOCALAPPDATA%\TranslatorLowerThird\logs\`:
  `app.log` (everything), `provider.log` (`app.providers.*`), `vmix.log` (`app.outputs.*`).
- Every handler carries a `SecretMaskingFilter` that redacts API-key-shaped strings
  (`sk-…`, `api_key=…`, `Bearer …`) before they reach disk.
- No raw audio and no full provider payloads are ever logged.

### TranslationPipeline (`app/pipeline.py`)

Owns the runtime lifecycle outside the GUI and wires provider → formatter →
outputs:

- a dedicated thread runs an asyncio loop hosting the provider
  (`connect`/`send_audio`/`close`);
- provider text events (partial/final) feed the `SubtitleFormatter`;
- a "tick" thread calls `formatter.tick()` every ~250 ms;
- the formatter's publish callback only enqueues; an "output" thread drains the
  queue and calls the (possibly blocking) vMix `set_text`, and the same text
  goes to the GUI preview via the subtitle listener.

`stop()` sets a stop event, stops audio, closes the provider on the loop,
stops/joins the loop thread, joins the tick and output threads, and resets the
formatter — no thread is left hanging (covered by a dedicated test). Audio is
optional: if capture fails the pipeline continues, so the fake-provider demo
runs without a microphone. Provider errors surface through an error listener
(`AppServices.set_error_listener`) that the GUI shows in the status bar and the
vMix light — never a modal dialog mid-event.

### Cloud speech providers (v1.2)

`GoogleSpeechProvider` (`app/providers/google_speech.py`) and
`AzureSpeechProvider` (`app/providers/azure_speech.py`) are `SpeechProvider`s
wrapping the vendor streaming SDKs behind an **injectable engine factory**: the
real SDK is lazy-imported (optional deps in `requirements-optional.txt`; a
missing package raises a readable error), and tests inject a fake engine so no
SDK or network is needed. Their SDK callbacks fire on the SDK's own threads;
`ComposedRealtimeProvider` captures the asyncio loop at `connect()` and marshals
each translation onto it (`create_task` when already on the loop thread, else
`run_coroutine_threadsafe`), so a cloud STT → DeepL pipeline is thread-safe.
Keys (and Azure region / Google credentials path) come from the `SecretStore`
under per-vendor account names and are never logged. A separate
`create_composed_provider(speech_id, translation_id, store)` builds these
pipelines programmatically; wiring them into the GUI selector (which needs
multi-credential settings) is the next increment.

### Translation providers (v1.2)

`TranslationProvider` implementations live alongside the split above.
`DeepLTranslationProvider` (`app/providers/deepl.py`) calls the DeepL REST API
via an injectable httpx client (free vs paid endpoint chosen from the key
suffix `:fx`; key read from the `SecretStore` under name `deepl`, never logged).
It is registered in a **separate translation-provider registry**
(`available_translation_providers` / `create_translation_provider`) — distinct
from the realtime provider selector shown in the GUI, because a text translator
alone produces no subtitles: it must be paired with a `SpeechProvider` inside a
`ComposedRealtimeProvider`. Tests use `httpx.MockTransport`; a live test is
gated on `DEEPL_API_KEY` + `RUN_LIVE_TESTS=1`.

## Threading Model

- GUI runs on the Qt main thread.
- Audio capture runs on a `sounddevice` callback/worker thread.
- Provider I/O runs on an asyncio loop in a dedicated thread.
- vMix HTTP calls run off the GUI thread with short timeouts.
- Cross-thread communication uses Qt signals/queues; STOP joins all workers cleanly.

## Error-Handling Philosophy

Every failure the operator can encounter maps to a simple Italian message in the GUI
("vMix non raggiungibile", "API key non valida", "Connessione Internet assente", …) while the
technical detail goes to the rotating logs. The app must stay open and recoverable through any
provider, network, or vMix failure.

## Packaging (`TranslatorLowerThird.spec`)

PyInstaller one-folder build driven by `scripts/build_exe.ps1`. PySide6 is
handled by PyInstaller's official hooks; the spec adds what the hooks miss:
`collect_all("sounddevice")` for the bundled PortAudio DLL, the `keyring`
Windows backend and `win32ctypes` hidden imports, and the OpenAI/fake providers
(imported lazily at runtime, so they must be declared explicitly). The exe is
windowed (`console=False`) so no terminal appears. `build/` and `dist/` are
git-ignored. The packaged exe has been verified to launch and write its startup
log on the build machine; a clean-VM check is the remaining release gate.

## Testing Strategy

- All external boundaries (audio, provider, vMix HTTP, keyring) have fakes/mocks.
- Default test runs consume no paid API credits; live provider tests require both
  `OPENAI_API_KEY` and `RUN_LIVE_TESTS=1`.
- See `tests/` — one module per subsystem, mirroring `app/`.
