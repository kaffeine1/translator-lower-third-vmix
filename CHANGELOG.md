# Changelog

Tutte le modifiche rilevanti a Traduttore Live sono elencate qui.

Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) e il
progetto adotta il [Versionamento Semantico](https://semver.org/lang/it/).

## [0.3.2] — 2026-07-08

### Migliorato

- **Barra di avanzamento chiara per il download dei modelli.** Come per i
  componenti, il download dei modelli mostra ora una **barra determinata** che
  avanza (MB scaricati sul totale) invece di un semplice indicatore "occupato";
  l'etichetta indica quale modello si sta scaricando. Riflette correttamente
  anche una ripresa (parte dai MB già presenti su disco).

### Corretto

- **Download dei modelli grandi più affidabile.** Scaricare i modelli più pesanti
  (`medium` ~1,5 GB, `large-v3` ~3 GB) su connessioni lente o instabili spesso si
  interrompeva, mentre i piccoli (`small`) riuscivano. Ora il download ha un
  **timeout più ampio** e **riprova automaticamente** in caso di interruzione,
  **riprendendo** dal punto in cui si era fermato invece di ricominciare (fino a
  4 tentativi, con avviso «riprovo…»).

## [0.3.1] — 2026-07-08

### Aggiunto

- **Guida integrata per ottenere le chiavi API.** Quando selezioni un provider
  cloud, sotto ogni campo credenziale compare una riga con una **spiegazione
  breve** e un **link cliccabile** che apre la pagina giusta della console del
  fornitore (OpenAI, Google Cloud, Azure) direttamente nel browser. Vale sia
  nelle Impostazioni sia nella procedura guidata iniziale, ed è leggibile sia in
  tema chiaro sia in **modalità scura** di Windows.
- **Traduzione nativa Google e Azure (un solo fornitore).** Le pipeline cloud ora
  sono **«Google Speech → Google Translate»** e **«Azure Speech → Azure
  Translator»**: basta un unico account/chiave per fornitore. Google Translate usa
  una **chiave API** (in aggiunta al file JSON del riconoscimento vocale); Azure
  Translator riusa la **stessa chiave e regione** di Azure Speech (risorsa
  multiservizio). I nuovi provider di traduzione sono chiamate REST leggere.

### Rimosso

- **Pipeline miste con DeepL** («Google Speech → DeepL» e «Azure Speech → DeepL»)
  rimosse dal selettore, sostituite dalle pipeline a fornitore unico qui sopra.

## [0.3.0] — 2026-07-08

### Aggiunto

- **Provider locali su GPU NVIDIA**: scegliendo **Dispositivo = «GPU (CUDA)»** il
  pulsante scarica un **pacchetto componenti GPU** separato (~1,2 GB) che include
  le librerie CUDA (cuBLAS, cuDNN, runtime) — così Faster-Whisper gira su GPU
  senza installare CUDA a parte. Il pacchetto CPU e quello GPU convivono (cambio
  dispositivo senza riscaricare). Il selettore dispositivo è ora anche nel
  wizard. Se i componenti/driver GPU mancano, la traduzione mostra un messaggio
  chiaro con l'invito a scaricare il pacchetto GPU, aggiornare i driver o usare
  la CPU (prima falliva in silenzio).
- **Gestione dello spazio dei modelli locali**: durante il download dei modelli
  lo stato mostra i **MB scaricati in tempo reale** (un modello grande come
  `large-v3`, ~3 GB, prima sembrava bloccato dietro una barra senza progresso);
  lo stato indica se i modelli per la selezione corrente sono **già scaricati o
  da scaricare**, e il nuovo pulsante **"Libera spazio: rimuovi i modelli
  scaricati…"** li elimina dopo l'uso (con conferma e spazio liberato;
  riscaricabili in qualsiasi momento). Il **wizard** ora chiede anche lingua
  sorgente/destinazione e, per il provider Locale, il modello vocale — e scarica
  esattamente quella selezione.
- **Download e attivazione automatici dei componenti locali** dalle
  Impostazioni: l'installer resta leggero, ma chi vuole provare i provider
  locali (Faster-Whisper → MarianMT) ora ha un pulsante *"Scarica e attiva i
  componenti locali"* che scarica il pacchetto runtime (~235 MB, con verifica
  di integrità e barra di avanzamento), lo installa nel profilo utente e lo attiva
  subito — senza reinstallare l'app e senza riavviarla. Un secondo pulsante
  pre-scarica i **modelli** per le lingue configurate, così il primo START è
  immediato. Funziona anche nella versione installata (prima i provider locali
  richiedevano l'esecuzione dal sorgente).

### Corretto

- **Traduzione locale ora funziona davvero dall'app installata.** L'eseguibile non
  includeva alcuni moduli della libreria standard di Python che `torch` usa
  (es. `timeit`), quindi la traduzione con modelli locali (es. Spagnolo→Italiano)
  falliva sempre dall'exe installato con un errore fuorviante di "componenti non
  scaricati". Ora l'app include l'intera libreria standard e la traduzione locale
  parte. (La sottotitolazione senza traduzione funzionava già perché non usa
  `torch`.)
- **Componenti locali sempre ri-scaricabili (riparazione).** Se i file dei
  componenti locali (torch, transformers…) venivano rimossi da una pulizia disco
  o dall'antivirus mentre il segnaposto di "installazione completata" restava,
  l'app li credeva installati, **nascondeva il pulsante di download** e non c'era
  modo di rimediare dall'interfaccia. Ora il pulsante è **sempre presente**: se i
  componenti risultano installati diventa **«Ri-scarica i componenti locali
  (riparazione)»** e forza un nuovo download. Vale sia per le Impostazioni sia
  per il wizard.
- **Messaggio chiaro quando manca il modello di traduzione locale.** Passando da
  una sottotitolazione senza traduzione (stessa lingua, es. IT→IT) a una **con
  traduzione** (es. Spagnolo→Italiano), se il modello di traduzione per quella
  coppia di lingue non era ancora stato scaricato l'app mostrava un generico
  «Errore di traduzione». Ora indica esplicitamente di aprire **Impostazioni →
  «Scarica ora i modelli»** (con le lingue impostate e una connessione a
  Internet). Il messaggio specifico del provider non viene più sovrascritto da
  quello generico.
- **Provider locale su GPU e crash da trascrizioni sovrapposte**: su GPU la
  trascrizione poteva fallire perché cuDNN non trovava le proprie sotto-librerie
  (ora le cartelle CUDA sono aggiunte anche al PATH, non solo via
  `add_dll_directory`). Inoltre premere START/STOP in rapida sequenza lasciava
  due trascrizioni Faster-Whisper attive insieme, corrompendo la memoria
  (crash `0xc0000374`): ora l'uso di CTranslate2 è serializzato (una trascrizione
  alla volta). Infine, cambiare **Dispositivo (CPU/GPU)** nelle Impostazioni
  mostra un avviso a **riavviare l'app**, perché il componente giusto viene
  caricato all'avvio.
- **Finestra Impostazioni troppo stretta con scrollbar orizzontale** (evidente su
  Windows 10): un nome di dispositivo audio lungo e l'etichetta di stato dei
  modelli imponevano al contenuto una larghezza enorme (~1500 px). Ora le tendine
  possono restringersi (elidono il testo corrente; l'elenco mostra comunque le
  voci intere), l'etichetta di stato va a capo, e la finestra si apre abbastanza
  larga da mostrare tutti i campi senza barra orizzontale.

### Migliorato

- **GPU NVIDIA sfruttata meglio (più veloce, meno memoria).** Il modello vocale
  su GPU ora usa la precisione di calcolo **`int8_float16`** invece del `float16`
  predefinito. Sulle schede senza tensor core (es. GTX 1660) il `float16` non è
  accelerato, mentre l'INT8 sì: il risultato è una trascrizione **più veloce** e
  che occupa **circa metà della memoria video**, con accuratezza praticamente
  identica. Su GPU la cadenza dei parziali è stata anche ridotta (0,7 s → 0,5 s)
  perché la scheda è per lo più libera tra un aggiornamento e l'altro, così il
  sottotitolo compare prima. Nota: con lo streaming in tempo reale è **normale**
  vedere un utilizzo GPU basso — si trascrivono brevi spezzoni a raffica e la
  scheda resta ferma tra un colpo e l'altro; il modo di sfruttarla è scegliere un
  modello più grande (es. `medium`).
- **Riconoscimento locale molto più reattivo (streaming).** Prima un sottotitolo
  compariva solo a segmento concluso: in parlato continuo si aspettavano ~6-8
  secondi. Ora il testo viene mostrato **man mano che si parla**: il motore
  ri-trascrive l'audio in arrivo ogni ~0,7 s (GPU) / ~1,2 s (CPU) e mostra un
  **parziale stabilizzato** (mostra solo le parole confermate da due passaggi,
  in modo che il testo già visibile non venga mai riscritto → niente
  sfarfallio), poi "fissa" la frase alla pausa. Su prova: primo testo da ~8,7 s
  a ~3,4 s su CPU (`base`), atteso ~1,5-2 s su GPU. Per la bassa latenza usare
  **`small` o `medium`**; `large-v3` in tempo reale richiede una GPU potente.
- **Niente sfarfallio dei sottotitoli anche con i provider cloud (Google e
  Azure).** I loro risultati "interim/recognizing" sono provvisori: Google e
  Azure riscrivono le parole man mano che ascoltano, e prima quel testo instabile
  arrivava tale e quale al sottotitolo (le parole già a schermo cambiavano). Ora
  la stessa stabilizzazione append-only del riconoscimento locale è condivisa
  anche da Google e Azure: si mostra solo il prefisso di parole ormai stabile e
  una parola già mostrata non viene più riscritta. OpenAI Realtime era già a
  posto (invia testo append-only). La traduzione automatica (es→it) resta esclusa
  di proposito: tradurre una frase più lunga può riordinare le parole, quindi
  congelarle sarebbe sbagliato.
- **Riconoscimento locale: molte meno parole perse (parte 2).** In parlato
  continuo (video reali) i confini dei segmenti spezzavano le parole e Whisper
  finiva per inventare o perdere intere frasi. Ora i segmenti si **sovrappongono**
  di mezzo secondo (le parole di confine vengono ri-trascritte intere, con
  rimozione automatica dei doppioni), le soglie anti-allucinazione sono riportate
  a valori che **non scartano parole reali**, e su **GPU** si usano impostazioni
  di decodifica più accurate (beam search + fallback di temperatura) senza costo
  di latenza. Su un parlato italiano continuo di prova il recall delle parole è
  salito dall'87% al 96%, senza più frasi allucinate ai confini.
- **Riconoscimento locale: molte meno parole perse.** Il motore Faster-Whisper
  tagliava l'audio ogni 4 secondi fissi: le parole a cavallo del taglio venivano
  spezzate o perse a ogni confine. Ora i segmenti terminano **sulle pause del
  parlato** (rilevate via energia del segnale), con un tetto di 6 s durante il
  parlato continuo (tagliando comunque nel punto più silenzioso). In più: i
  segmenti di solo silenzio vengono scartati (eliminati i testi "allucinati"
  tipo *"Sottotitoli a cura di…"*) e la decodifica è tarata per il live su CPU
  (beam greedy, niente retry a temperatura alta, filtro VAD) — più veloce e
  senza loop di ripetizione. Sullo stesso audio di prova: prima 4 frammenti con
  parole storpiate ai confini, ora 3 sottotitoli che coincidono con le 3 frasi
  pronunciate.

### Aggiunto

- **Sottotitolazione senza traduzione** (provider composti): impostando la
  **stessa lingua** come sorgente e destinazione, il testo riconosciuto va in
  onda così com'è senza passare dal traduttore (es. parlato italiano →
  sottotitoli italiani con il provider Locale). Prima questo caso falliva
  (il modello di traduzione `it-it` non esiste).
- **Manuale**: chiarito che i provider locali funzionano solo eseguendo l'app
  dal sorgente (i componenti aggiuntivi non possono essere aggiunti alla
  versione installata).

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
