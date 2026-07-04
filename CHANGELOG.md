# Changelog

Tutte le modifiche rilevanti a Translator Lower Third for vMix sono elencate qui.

Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) e il
progetto adotta il [Versionamento Semantico](https://semver.org/lang/it/).

## [Non rilasciato]

### Aggiunto

- **Registro dei provider** (`app/providers/registry.py`): i provider di
  traduzione sono dichiarati in un unico punto con id, nome e se richiedono una
  chiave API. Base per aggiungere provider futuri senza toccare GUI o servizi.
- **Selettore provider** nelle Impostazioni, con **modalità Demo** esplicita:
  ora si può scegliere il provider a mano (OpenAI o Demo senza API) invece di
  dedurlo solo dalla presenza della chiave.
- **Interfacce separate `SpeechProvider` e `TranslationProvider`** con un
  adattatore `ComposedRealtimeProvider` che le combina rispettando l'interfaccia
  usata dalla pipeline. Base per pipeline future (Google Speech → DeepL,
  Faster-Whisper → MarianMT). Incluse implementazioni finte e un provider demo
  "speech + traduzione separati".
- **`DeepLTranslationProvider`** (traduzione testo via API DeepL) come
  `TranslationProvider`, con registro dei provider di traduzione separato.
  Da usare dentro un provider composto insieme a uno SpeechProvider (in arrivo).
- **`GoogleSpeechProvider` e `AzureSpeechProvider`** (riconoscimento vocale
  cloud) come `SpeechProvider`, con motore SDK iniettabile (dipendenze opzionali,
  import lazy), registro degli SpeechProvider e factory `create_composed_provider`
  per combinarli con un traduttore (es. Google/Azure Speech → DeepL).
- `ComposedRealtimeProvider` ora rimanda le traduzioni al loop asyncio in modo
  thread-safe: gli SDK vocali invocano le callback su thread propri.

## [0.1.0] — 2026-07-04

Prima release MVP: dall'audio dal vivo al sottopancia tradotto in vMix.

### Aggiunto

- **GUI in italiano** (PySide6): semafori di stato Audio / API / vMix,
  anteprima del sottotitolo, pulsanti START, STOP, Test Audio, Test API,
  Test vMix, Impostazioni, Apri Log e Info.
- **Wizard di prima esecuzione** in 6 passi: ingresso audio, chiave API,
  test API, configurazione vMix, test vMix, salva e avvia.
- **Configurazione** non sensibile in `%APPDATA%\TranslatorLowerThird\config.yaml`
  con recupero automatico da file mancante o danneggiato.
- **Chiave API** salvata in modo sicuro nel Windows Credential Manager
  (mai in file di testo, mai nei log).
- **Logging rotante** in `%LOCALAPPDATA%\TranslatorLowerThird\logs\` con
  mascheramento dei segreti (anche nei traceback).
- **Ingresso audio**: elenco dei dispositivi Windows, misuratore di livello
  per il Test Audio, cattura PCM16 16 kHz mono.
- **Provider di traduzione OpenAI Realtime** (WebSocket) con riconnessione
  automatica e arresto pulito; **provider demo** integrato per l'uso senza
  chiave API.
- **SubtitleFormatter** anti-sfarfallio: aggregazione dei parziali, massimo
  due righe, deduplicazione, pulizia dopo silenzio.
- **Uscita vMix** via HTTP API (`SetText`) con encoding corretto, timeout
  breve e retry leggero; pulsante Test vMix.
- **Sezione Info/diagnostica**: versione app, provider, lingue e percorsi di
  configurazione e log.
- **Packaging** con PyInstaller (one-folder, senza console) e **installer**
  Inno Setup (shortcut Start Menu, Desktop opzionale, disinstallazione che
  preserva la configurazione utente).

### Note

- Non è richiesto Python sul PC dell'operatore: tutto è incluso nell'installer.
- I driver audio virtuali (es. VB-Cable) non sono inclusi né obbligatori.

[0.1.0]: https://example.invalid/translator-lower-third-vmix/releases/tag/v0.1.0
