# Changelog

Tutte le modifiche rilevanti a Traduttore Live sono elencate qui.

Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) e il
progetto adotta il [Versionamento Semantico](https://semver.org/lang/it/).

## [Non rilasciato]

### Corretto

- **Provider locale (Faster-Whisper → MarianMT) di nuovo funzionante e
  collaudato end-to-end su CPU** (parlato italiano reale → trascrizione →
  traduzione inglese corretta e in ordine):
  - compatibilità con **transformers 5** (che ha rimosso il task
    `pipeline("translation")` usato per MarianMT): il traduttore ora usa
    direttamente `AutoTokenizer`/`AutoModelForSeq2SeqLM`, funziona con
    transformers 4.x e 5.x;
  - i **sottotitoli finali escono nell'ordine del parlato**: due traduzioni in
    volo potevano completarsi invertite (il testo più corto traduce prima) e le
    frasi si scambiavano in onda; ora i finali sono serializzati;
  - il **modello di traduzione viene costruito una sola volta** anche con più
    traduzioni concorrenti al primo avvio (prima: build multiple in parallelo,
    centinaia di MB ciascuna);
  - gli errori del traduttore locale ora finiscono nei log **con il traceback
    reale** (prima solo "Traduzione locale fallita", indiagnosticabile);
  - aggiunto `sentencepiece` ai requisiti opzionali (necessario al tokenizer
    dei modelli Helsinki-NLP/opus-mt-*).

## [0.2.2] — 2026-07-06

Sottotitoli a schermo e titolo vMix ora funzionano insieme: collaudato l'uso
contemporaneo di overlay e uscita Fullscreen di vMix.

### Corretto

- **Sottotitoli a schermo nascosti dall'uscita Fullscreen di vMix**: anche
  l'uscita a schermo intero di vMix è una finestra "sempre in primo piano", e
  tra due finestre di quel tipo vince l'ultima mostrata: aperto il fullscreen di
  vMix dopo l'overlay, i sottotitoli continuavano a essere disegnati ma
  restavano coperti. Ora l'overlay **si riporta in cima a ogni nuovo testo** e
  con un controllo periodico (~1,5 s) finché è visibile — senza rubare il focus
  e senza sfarfallio. Nota: i sottotitoli a schermo restano visibili solo sul
  monitor fisico; **non entrano** nel programma/streaming/registrazione di vMix
  (per quello si usa il titolo vMix).
- **L'overlay poteva allargarsi oltre il bordo del monitor**: con una riga molto
  lunga la finestra dell'overlay poteva crescere oltre lo schermo (fino a
  sconfinare sul monitor accanto) per colpa di un minimo di layout non
  aggiornato. Ora la superficie ha **dimensione fissa pari allo schermo scelto**
  e il testo viene adattato dal ridimensionamento automatico del font.
- **Sottotitoli vecchi riprodotti in ritardo con vMix lento/irraggiungibile**:
  la coda verso vMix accumulava gli aggiornamenti (ogni tentativo fallito ~4 s)
  e poi li riproduceva in sequenza, in ritardo. Ora viene inviato solo il
  sottotitolo **più recente**.

## [0.2.1] — 2026-07-06

Correzioni dopo il primo rilascio pubblico: un crash su configurazioni
multi-monitor e la latenza di avvio del sottotitolo.

### Corretto

- **Crash nativo (Qt6Gui, access violation in `QScreen::geometry`)**: l'overlay
  sottotitoli veniva piazzato su un monitor specifico e ne conservava il
  riferimento; a un cambio di configurazione dei display (monitor in standby,
  cambio risoluzione, disconnessione/riconnessione) quello schermo diventava
  non valido e la sua geometria veniva dereferenziata, chiudendo l'app senza
  messaggio (spesso cliccando i pulsanti di test). Ora l'overlay è una finestra
  di primo livello **senza genitore** (disaccoppiata dal churn della finestra
  principale), ogni accesso alla geometria è validato contro l'elenco schermi
  attivo, e l'app **reagisce ai cambi di monitor** ri-posizionando o nascondendo
  l'overlay. Aggiunta diagnostica: hook per eccezioni nei thread e non
  recuperabili, flush dei log e registrazione del layout schermi all'avvio.
- **Latenza di avvio del sottotitolo ridotta**: dopo START il testo tradotto
  compariva nell'headline vMix con molto ritardo. Il **primo sottotitolo di ogni
  frase** ora viene pubblicato **subito** (prima attendeva l'intero
  `min_update_interval_ms`, ~1,2 s di ritardo tutto nostro): passare da vuoto alle
  prime parole non è sfarfallio, e l'intervallo anti-sfarfallio ora limita solo
  gli aggiornamenti *interni* alla frase. Inoltre il provider **finalizza la frase
  al termine** (dopo una pausa): il formatter la "blocca" e le prime parole della
  frase successiva appaiono immediatamente invece di restare dietro la precedente.
  Tick del formatter più fine (250→100 ms). Nota: l'attesa del rilevamento
  fine-frase lato server OpenAI (~1–2 s) è **inerente** all'API di traduzione
  realtime (nessun parametro `turn_detection` è accettato) e non è eliminabile.

## [0.2.0] — 2026-07-06

Primo rilascio pubblico. Traduzione dal vivo dell'audio verso un sottopancia
vMix e/o sottotitoli a schermo, con provider OpenAI/cloud/locali, cattura
dell'audio di sistema, localizzazione, wizard consapevole del provider e
packaging (installer).

### Aggiunto

- **Sottotitoli a schermo (overlay)**: finestra translucida, sempre in primo
  piano e click-through, che mostra il sottotitolo tradotto (testo bianco su
  sfondo grigio trasparente) sul monitor scelto — utile per il pubblico su un
  secondo schermo o proiettore. Interruttore rapido nella finestra principale e
  impostazioni per monitor, dimensione testo e opacità. Rispetta il numero di
  righe configurato e rimpicciolisce automaticamente il font per farle stare,
  invece di andare a capo.
- **Cattura dell'audio di sistema (loopback WASAPI)**: si può scegliere "Uscita
  di sistema (loopback)" come ingresso e tradurre l'audio riprodotto dal PC (es.
  un video). Richiede il componente opzionale `soundcard`
  (`requirements-optional.txt`); senza, il menu mostra solo microfoni/line-in.
- **Impostazioni sottotitoli in tempo reale**: cambiare max righe/caratteri e i
  tempi si applica subito alla traduzione in corso, senza fermare e riavviare.
- **Diagnostica di crash**: `faulthandler` scrive lo stack di un eventuale crash
  nativo in `logs\crash.log` e le eccezioni non gestite finiscono nei log.
- **Notice licenze di terze parti** (`THIRD_PARTY_NOTICES.md`): dipendenze
  runtime, opzionali e di packaging, con nota su PySide6/Qt e LGPL. La build
  PyInstaller include `LICENSE` e `THIRD_PARTY_NOTICES.md`.

### Corretto

- **Provider OpenAI allineato alla Realtime Translation API (GA)**: endpoint
  `/v1/realtime/translations`, modello `gpt-realtime-translate`, audio inviato
  come `session.input_audio_buffer.append` (PCM16 24 kHz, con ricampionamento e
  downmix a mono). `session.update` configura **solo** `audio.output.language`:
  senza l'header beta e senza `input.format`, che l'API rifiutava con
  `beta_api_shape_disabled` chiudendo la sessione. Il testo tradotto arriva come
  delta append-only di `session.output_transcript.delta` (buffer con reset dopo
  silenzio e limite di lunghezza).
- **STOP ora ferma davvero la traduzione**: la chiusura del provider non si
  blocca più sull'handshake di chiusura del WebSocket (che poteva durare ~10 s e
  impedire l'arresto del loop, lasciando la traduzione attiva fino alla chiusura
  dell'app).
- **Semafori di stato**: salvando le Impostazioni si azzera a giallo solo il
  semaforo la cui configurazione è cambiata (Audio/API/vMix); modificare i
  sottotitoli o l'overlay non invalida più i risultati dei test già verdi.

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

[0.2.2]: https://github.com/kaffeine1/translator-lower-third-vmix/releases/tag/v0.2.2
[0.2.1]: https://github.com/kaffeine1/translator-lower-third-vmix/releases/tag/v0.2.1
[0.2.0]: https://github.com/kaffeine1/translator-lower-third-vmix/releases/tag/v0.2.0
[0.1.0]: https://github.com/kaffeine1/translator-lower-third-vmix
