# Changelog

Tutte le modifiche rilevanti a Traduttore Live sono elencate qui.

Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) e il
progetto adotta il [Versionamento Semantico](https://semver.org/lang/it/).

## [Non rilasciato]

### Aggiunto

- **Notice licenze di terze parti** (`THIRD_PARTY_NOTICES.md`): chiarisce le
  dipendenze runtime, opzionali e di packaging, con nota specifica su PySide6/Qt
  e LGPL. La build PyInstaller include ora `LICENSE` e
  `THIRD_PARTY_NOTICES.md` nella distribuzione binaria.

### Corretto

- **Provider OpenAI allineato alla Realtime Translation API attuale**: endpoint
  `/v1/realtime/translations`, modello `gpt-realtime-translate`, audio inviato
  come `session.input_audio_buffer.append`, lingua di uscita configurata via
  `session.audio.output.language`, testo tradotto ricevuto da
  `session.output_transcript.delta`/`.done` (la trascrizione sorgente
  `session.input_transcript.delta` è solo per debug, non va in onda). La chiusura
  invia `session.close` e attende `session.closed` o va in timeout prima di
  chiudere il socket. L'audio è ricampionato a 24 kHz mono (con downmix dei
  canali) come richiede la API. Correzioni di robustezza allo STOP: nessun errore
  "connessione persa" o riconnessione spuria durante l'arresto volontario.

Primo rilascio pubblico. Include l'architettura provider, i provider cloud e
locali, la localizzazione, il wizard consapevole del provider e il packaging.

### Modificato

- **Nome del programma semplificato in "Traduttore Live"**: cambia il nome
  visibile (titolo finestra, riquadro Info, collegamenti e voce
  nell'elenco programmi, Proprietà dell'eseguibile). Gli identificatori interni
  restano invariati (cartella `%APPDATA%\TranslatorLowerThird`, log, nome
  dell'eseguibile e servizio chiavi nel Credential Manager), così configurazione
  e chiavi già salvate continuano a funzionare.

### Aggiunto

- **Manuale d'uso dettagliato in italiano** (`docs/USER_GUIDE.md`): copre
  installazione, primo avvio, ogni impostazione, configurazione di vMix, scelta e
  configurazione dei provider (Demo, OpenAI, cloud, locali), conduzione della
  diretta, log, sicurezza, risoluzione problemi e disinstallazione.
- **Metadati di versione nei pacchetti**: l'eseguibile e l'installer ora
  riportano versione, autore e descrizione nelle Proprietà di Windows (la
  versione è letta da `app/__init__.py`, un'unica fonte). `build_installer.ps1`
  trova ISCC anche quando Inno Setup è installato per-utente (es. via winget in
  `%LOCALAPPDATA%`), oltre ai percorsi in Program Files.
- **Wizard di prima configurazione rinnovato**: ora è consapevole del provider.
  Passi: lingua + provider → credenziali dinamiche (i campi dipendono dal
  provider scelto e vengono salvati subito in modo sicuro, così i test
  funzionano) → verifica provider → ingresso audio → vMix → verifica vMix →
  salva. Prima gestiva solo la chiave OpenAI e i test non usavano le credenziali
  appena inserite.
- **Provider locali (offline)**: `FasterWhisperSpeechProvider` (riconoscimento
  vocale locale) e `LocalMarianTranslationProvider` (traduzione locale via
  MarianMT). Registrati come pipeline "Locale (Faster-Whisper → MarianMT)" nel
  selettore, senza credenziali. Le librerie pesanti sono opzionali (import lazy,
  vedi `requirements-optional.txt`); un errore leggibile avvisa se mancano.
  Modello (tiny/base/small/medium/large-v3) e dispositivo (CPU/GPU CUDA)
  configurabili nelle Impostazioni, con avviso sui requisiti hardware.
- **Pipeline cloud selezionabili dalla GUI**: le voci "Google Speech → DeepL" e
  "Azure Speech → DeepL" compaiono nel selettore Provider. Le Impostazioni ora
  mostrano **campi credenziali dinamici** in base al provider scelto (es. Azure
  → chiave + regione + chiave DeepL); ogni valore è salvato nel secure storage
  sotto il proprio account, i campi vuoti non sovrascrivono quelli già salvati.
- **Localizzazione (i18n)**: modulo `app/i18n.py` con `t("chiave", …)` e catalogo
  per lingua. Tutti i messaggi visibili all'operatore (GUI, servizi, provider,
  vMix, audio) passano dal catalogo. Per ora è presente solo l'italiano, ma la
  struttura è pronta per altre lingue (basta aggiungere un dizionario).
  Aggiunto il campo `ui_language` in configurazione, il selettore "Lingua
  interfaccia" nelle Impostazioni e l'attivazione della lingua all'avvio.

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

[0.2.0]: https://github.com/kaffeine1/translator-lower-third-vmix/releases/tag/v0.2.0
[0.1.0]: https://github.com/kaffeine1/translator-lower-third-vmix
