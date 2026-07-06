# Manuale d'uso — Traduttore Live

Traduttore Live è un'applicazione Windows che **ascolta l'audio di un evento dal
vivo**, lo **traduce quasi in tempo reale** e scrive il testo tradotto in un
**sottopancia/titolo di vMix**. È pensata per operatori di produzione dal vivo:
si installa, si configura una volta e si preme **START**. Non serve il terminale,
non serve modificare file di configurazione, non serve installare Python.

> Scenario tipico: parlato in **spagnolo** → sottotitolo in **italiano** →
> sottopancia (lower third) in vMix.

---

## Indice

1. [Come funziona](#1-come-funziona)
2. [Requisiti](#2-requisiti)
3. [Installazione](#3-installazione)
4. [Concetti chiave](#4-concetti-chiave)
5. [Prima configurazione (procedura guidata)](#5-prima-configurazione-procedura-guidata)
6. [La finestra principale](#6-la-finestra-principale)
7. [Impostazioni in dettaglio](#7-impostazioni-in-dettaglio)
8. [Configurare vMix](#8-configurare-vmix)
9. [Scegliere e configurare il provider](#9-scegliere-e-configurare-il-provider)
10. [Condurre una diretta](#10-condurre-una-diretta)
11. [Le regole dei sottotitoli](#11-le-regole-dei-sottotitoli)
12. [Log e diagnostica](#12-log-e-diagnostica)
13. [Sicurezza e privacy](#13-sicurezza-e-privacy)
14. [Risoluzione dei problemi](#14-risoluzione-dei-problemi)
15. [Disinstallazione](#15-disinstallazione)
16. [Domande frequenti](#16-domande-frequenti)
17. [Percorsi dei file](#17-percorsi-dei-file)

---

## 1. Come funziona

Il flusso interno, dall'audio al sottopancia, è questo:

```text
Ingresso audio di Windows
        ↓
Riconoscimento + traduzione (provider)
        ↓
Formattatore sottotitoli (anti-sfarfallio)
        ↓
API HTTP di vMix
        ↓
Titolo / sottopancia in vMix
```

Traduttore Live gira **sullo stesso PC di vMix**, oppure su un altro PC che
riesce a raggiungere l'API HTTP di vMix in rete.

---

## 2. Requisiti

- **Windows 10 o 11** (64 bit).
- **vMix** con il **Web Controller / API HTTP** attivo (porta predefinita `8088`).
- Un **ingresso audio** visibile a Windows da cui arriva il parlato: microfono,
  mixer, scheda audio, uscita di un'applicazione o **cavo audio virtuale**
  (es. VB-Cable). I driver audio virtuali non sono inclusi né obbligatori. In
  alternativa puoi catturare direttamente l'**uscita audio del PC** (loopback),
  utile per tradurre un video riprodotto sul computer senza cavi virtuali.
- (Facoltativo) Un **secondo schermo o proiettore** se vuoi mostrare i sottotitoli
  a video oltre che nel titolo vMix (funzione *Sottotitoli a schermo*).
- A seconda del provider scelto (vedi [§9](#9-scegliere-e-configurare-il-provider)):
  - una **chiave API** del servizio di traduzione (OpenAI, DeepL, Google, Azure), **oppure**
  - la **modalità Demo**, che non richiede alcuna chiave, **oppure**
  - i **provider locali** (offline), che richiedono componenti aggiuntivi e hardware adeguato.
- **Connessione a Internet** se usi un provider cloud (OpenAI/Google/Azure/DeepL).
  I provider locali funzionano offline.

Non è richiesto installare Python: tutto è incluso nell'installer.

---

## 3. Installazione

1. Esegui **`TranslatorLowerThird-Setup.exe`**.
2. Windows potrebbe mostrare l'avviso **SmartScreen "editore sconosciuto"**: è
   normale perché il pacchetto non è ancora firmato digitalmente. Fai clic su
   *Ulteriori informazioni → Esegui comunque*.
3. Completa la procedura (l'installazione richiede i privilegi di amministratore
   perché installa in *Programmi*). Il collegamento sul Desktop è opzionale.
4. Avvia **Traduttore Live** dal menu Start.

In alternativa, per provare senza installare, puoi eseguire direttamente
`TranslatorLowerThird.exe` dalla cartella dell'applicazione.

---

## 4. Concetti chiave

- **Provider**: il servizio che trasforma l'audio in testo tradotto. Si sceglie
  nelle Impostazioni. Puoi usare un provider **cloud** (a pagamento, con chiave
  API), la **modalità Demo** (gratuita, mostra testi di esempio) o i **provider
  locali** (offline).
- **Semafori di stato**: tre indicatori — **Audio**, **API**, **vMix** — che
  diventano **verdi** quando la parte corrispondente funziona, **gialli** durante
  una verifica e **rossi** in caso di problema.
- **Sottopancia / lower third (titolo vMix)**: il campo di testo di un input
  *Titolo/GT* di vMix in cui viene scritto il sottotitolo tradotto.
- **Modalità Demo**: se scegli un provider Demo, l'app mostra frasi di esempio
  senza usare alcuna API. Serve per collaudare audio e vMix senza spese.
- **Uscita di sistema (loopback)**: un tipo di ingresso audio che cattura ciò che
  il PC **riproduce** (es. un video in streaming), invece di un microfono.
- **Sottotitoli a schermo (overlay)**: una finestra trasparente, sempre in primo
  piano, che mostra il sottotitolo tradotto direttamente su un monitor scelto —
  in aggiunta (o in alternativa) al titolo vMix.

---

## 5. Prima configurazione (procedura guidata)

Al primo avvio parte una **procedura guidata** in 7 passi. È *consapevole del
provider*: i campi delle credenziali cambiano in base al provider scelto.

1. **Lingua e provider** — scegli la lingua dell'interfaccia e il provider di
   traduzione (vedi [§9](#9-scegliere-e-configurare-il-provider)).
2. **Credenziali** — compaiono solo i campi richiesti dal provider scelto
   (ad esempio la chiave OpenAI; oppure chiave Azure + regione + chiave DeepL;
   con la Demo o i provider locali non serve nulla). I valori vengono salvati
   subito in modo sicuro, così i passi di verifica successivi li usano davvero.
3. **Verifica provider** — controlla che le credenziali siano valide. Con la
   Demo conferma semplicemente che non serve alcuna chiave; con i provider
   locali segnala se mancano i componenti aggiuntivi.
4. **Ingresso audio** — scegli il dispositivo da cui arriva il parlato.
5. **vMix** — indirizzo (di norma `127.0.0.1`), porta (`8088`), nome dell'input
   Titolo e nome del campo di testo (predefinito `Headline.Text`).
6. **Verifica vMix** — scrive una frase di prova nel titolo configurato: se la
   vedi comparire in vMix, la connessione è corretta.
7. **Salva** — conclude e apre la finestra principale.

Puoi rifare o modificare tutto in qualsiasi momento dalle **Impostazioni**. Se
annulli la procedura guidata, ricomparirà al prossimo avvio.

---

## 6. La finestra principale

La finestra principale mostra i tre **semafori** (Audio / API / vMix),
l'**anteprima** dell'ultimo sottotitolo tradotto e i pulsanti di comando.

| Pulsante | Funzione |
|---|---|
| **START** | Avvia la cattura audio e la traduzione dal vivo. |
| **STOP** | Ferma tutto in modo pulito (audio e provider). |
| **Test Audio** | Ascolta alcuni secondi e mostra il livello: **verde** se rileva audio, rosso se non arriva nulla. |
| **Test API** | Verifica il provider di traduzione scelto (o conferma la modalità Demo). |
| **Test vMix** | Scrive una frase di prova nel titolo vMix configurato. |
| **Impostazioni** | Provider, credenziali, lingue, audio, vMix, provider locali, sottotitoli, overlay. |
| **Apri Log** | Apre la cartella dei log (dettagli tecnici, senza segreti). |
| **Info** | Nome e versione dell'app, provider attivo, lingue e percorsi di configurazione e log. |
| **Sottotitoli a schermo** | Interruttore rapido: mostra/nasconde l'overlay dei sottotitoli sul monitor scelto. |

L'anteprima mostra ciò che viene inviato a vMix. Se compaiono errori (API, rete,
vMix) vengono mostrati in modo chiaro, senza finestre modali che bloccano la
diretta.

---

## 7. Impostazioni in dettaglio

Le Impostazioni sono divise in gruppi. Se lo schermo è basso, la finestra scorre
in verticale e i pulsanti **Salva / Annulla** restano sempre visibili in fondo.

### Interfaccia
- **Lingua interfaccia**: lingua dei testi dell'applicazione. Al momento è
  disponibile l'**italiano**; la struttura è pronta per aggiungere altre lingue.

### Provider
- **Provider**: il servizio di traduzione (vedi [§9](#9-scegliere-e-configurare-il-provider)).
- **Lingua sorgente**: la lingua parlata nell'evento (predefinita **Spagnolo**).
- **Lingua di uscita**: la lingua del sottotitolo (predefinita **Italiano**).
  Lingue disponibili: Spagnolo, Italiano, Inglese, Francese, Portoghese.

### Credenziali
I campi cambiano in base al provider scelto (campi dinamici). I campi segreti
(chiavi API) sono nascosti. **I valori salvati non vengono mai ri-mostrati**: un
campo vuoto lascia invariato il valore già salvato, quindi non devi reinserire la
chiave ogni volta. Con la Demo o i provider locali questo gruppo è vuoto.

### Ingresso audio
- **Ingresso audio**: il dispositivo Windows da cui catturare il parlato. Puoi
  lasciare *predefinito di sistema* oppure scegliere un dispositivo specifico.
  L'app memorizza il **nome** del dispositivo, così resta valido anche se
  l'ordine dei dispositivi cambia dopo un ricollegamento.
- Nell'elenco compaiono anche le voci **"Uscita di sistema (loopback)"**: scegline
  una per tradurre **ciò che il PC sta riproducendo** (es. un video) invece di un
  microfono. Non serve alcun cavo audio virtuale.

### Sottotitoli a schermo (overlay)
Mostra il sottotitolo tradotto su un monitor, come una didascalia sempre in primo
piano (testo bianco su fondo grigio semitrasparente), senza rubare i clic a ciò
che c'è sotto. Utile per il pubblico in sala, un proiettore o un secondo schermo.

- **Attiva sottotitoli a schermo**: mostra/nasconde l'overlay (equivale
  all'interruttore rapido nella finestra principale).
- **Monitor**: su quale schermo mostrarlo, se ne hai più di uno.
- **Dimensione testo**: dimensione del carattere; se una riga è troppo larga per
  lo schermo, il carattere si rimpicciolisce automaticamente per farla stare
  (rispetta il numero di righe configurato, non va a capo da solo).
- **Opacità sfondo**: quanto è opaco il riquadro grigio dietro al testo.

L'overlay mostra lo **stesso testo** inviato a vMix e segue le stesse regole dei
[Sottotitoli](#11-le-regole-dei-sottotitoli). Se cambi la configurazione dei
monitor mentre l'app è aperta, l'overlay si ri-posiziona automaticamente su uno
schermo valido.

### vMix
- **Host**: indirizzo di vMix (di norma `127.0.0.1` se sullo stesso PC).
- **Porta**: porta dell'API HTTP di vMix (predefinita `8088`).
- **Input / Titolo**: nome (o numero) dell'input Titolo di vMix su cui scrivere.
- **Campo di testo**: nome del campo del titolo, predefinito `Headline.Text`.

### Provider locali (offline)
- **Modello locale**: dimensione del modello di riconoscimento vocale locale:
  `tiny`, `base`, `small` (predefinito), `medium`, `large-v3`. Modelli più grandi
  sono più accurati ma più lenti e richiedono più memoria.
- **Dispositivo**: `CPU` (predefinito) o `GPU (CUDA)`. La GPU è molto più veloce
  ma richiede una scheda NVIDIA compatibile.
- Queste opzioni hanno effetto solo se usi il provider **Locale** e i relativi
  componenti aggiuntivi sono installati. Un avviso ricorda i requisiti hardware.

### Sottotitoli
Regole di formattazione (spiegate in dettaglio in [§11](#11-le-regole-dei-sottotitoli)):

| Impostazione | Predefinito | Significato |
|---|---:|---|
| Massimo caratteri per riga | 42 | Larghezza massima di una riga di sottotitolo. |
| Massimo righe | 2 | Numero massimo di righe in onda contemporaneamente. |
| Intervallo minimo di aggiornamento | 1200 ms | Ogni quanto, al massimo, aggiornare il testo (anti-sfarfallio). |
| Mantieni sottotitolo | 5 s | Per quanto tempo tenere un sottotitolo dopo l'ultima frase. |
| Cancella dopo silenzio | 8 s | Dopo quanti secondi di silenzio svuotare il titolo. |

---

## 8. Configurare vMix

1. In vMix apri **Settings → Web Controller** e assicurati che sia **abilitato**
   (porta predefinita `8088`). Annota l'indirizzo mostrato.
2. Individua l'**input Titolo/GT** che userai come sottopancia e il **nome del
   campo di testo** al suo interno. Con i titoli GT standard il campo si chiama
   spesso `Headline.Text`.
3. In Traduttore Live, in *Impostazioni → vMix*, inserisci **Host**, **Porta**,
   **Input / Titolo** e **Campo di testo** corrispondenti.
4. Premi **Test vMix**: nel titolo deve comparire una frase di prova.

L'app invia il testo con una chiamata di questo tipo (il testo viene codificato
correttamente, non concatenato a mano):

```text
http://HOST:PORTA/api/?Function=SetText&Input=INPUT&SelectedName=CAMPO&Value=TESTO
```

Esempio:

```text
http://127.0.0.1:8088/api/?Function=SetText&Input=Sottopancia&SelectedName=Headline.Text&Value=Ciao%20mondo
```

I nomi **Input** e **Campo di testo** devono corrispondere esattamente a quelli
del progetto vMix in uso.

---

## 9. Scegliere e configurare il provider

Il provider si sceglie in *Impostazioni → Provider* (o nel primo passo della
procedura guidata). Le voci disponibili sono:

| Provider | Credenziali richieste | Note |
|---|---|---|
| **OpenAI Realtime** | Chiave API OpenAI | Traduzione in tempo reale via API OpenAI. |
| **Demo (senza API)** | Nessuna | Mostra frasi di esempio: ideale per collaudare audio e vMix senza spese. |
| **Demo (speech + traduzione separati)** | Nessuna | Come sopra, ma simula la pipeline "voce + traduzione" separate. |
| **Google Speech → DeepL** | Credenziali Google + chiave DeepL | Riconoscimento vocale Google, traduzione DeepL. |
| **Azure Speech → DeepL** | Chiave Azure + regione Azure + chiave DeepL | Riconoscimento vocale Azure, traduzione DeepL. |
| **Locale (Faster-Whisper → MarianMT)** | Nessuna | Offline: riconoscimento e traduzione sul tuo PC. Richiede componenti aggiuntivi e hardware adeguato. |

Dettagli sulle credenziali:

- **OpenAI**: incolla la chiave API (inizia con `sk-...`). Serve un **accesso API**
  con credito: un abbonamento ChatGPT Plus/Pro **non** è la stessa cosa (vedi FAQ).
- **DeepL**: chiave API DeepL (le chiavi gratuite terminano con `:fx`).
- **Google**: percorso del file JSON delle credenziali di un *service account*
  con accesso a Speech-to-Text.
- **Azure**: chiave del servizio *Speech* **e** la **regione** (es. `westeurope`).

> **Provider locali**: la parte software è presente, ma per usarli servono
> componenti aggiuntivi (elencati in `requirements-optional.txt`) e, per essere
> fluidi, una GPU. Finché non sono installati, la verifica del provider segnala
> in modo chiaro che mancano. Per un primo collaudo conviene partire da un
> provider cloud o dalla modalità Demo.

Se scegli un provider ma mancano le credenziali necessarie, l'app **ripiega
automaticamente sulla modalità Demo** e te lo segnala, così puoi comunque
provare il resto della catena.

---

## 10. Condurre una diretta

**Checklist prima dell'evento:**

1. Apri Traduttore Live.
2. Premi **Test Audio**: il semaforo **Audio** deve diventare verde mentre parli
   nella sorgente.
3. Premi **Test API**: il semaforo **API** deve diventare verde (o confermare la
   modalità Demo).
4. Premi **Test vMix**: il semaforo **vMix** deve diventare verde e in vMix deve
   comparire la frase di prova.

**Durante l'evento:**

5. Premi **START**. Il testo tradotto appare nell'anteprima e nel sottopancia di
   vMix.
6. Tieni d'occhio i semafori: se qualcosa diventa rosso, l'app mostra un
   messaggio comprensibile (vedi [§14](#14-risoluzione-dei-problemi)).

**A fine evento:**

7. Premi **STOP** per chiudere in modo pulito la cattura audio e il provider.

---

## 11. Le regole dei sottotitoli

Per evitare che il sottopancia "lampeggi" o cambi a ogni parola, il testo viene
elaborato prima di essere inviato a vMix:

- **Massimo caratteri per riga (42)** e **Massimo righe (2)**: il testo viene
  suddiviso in righe leggibili; le frasi troppo lunghe vengono riflusse o
  troncate mantenendo le ultime righe.
- **Intervallo minimo di aggiornamento (1200 ms)**: il testo non viene aggiornato
  a ogni parola. Le **prime parole di ogni frase compaiono subito** (passare da
  vuoto al testo non è sfarfallio); gli aggiornamenti *successivi all'interno
  della stessa frase* vengono inviati al massimo una volta per intervallo.
  Aggiornamenti identici consecutivi non vengono inviati. Nota: una parte del
  ritardo iniziale dipende dal servizio di traduzione, che attende una breve
  pausa del parlato prima di produrre il testo — è normale con la traduzione
  in tempo reale.
- **Mantieni sottotitolo (5 s)**: un sottotitolo resta in onda per questo tempo
  dopo l'ultima frase, così non sparisce troppo in fretta.
- **Cancella dopo silenzio (8 s)**: se non arriva più parlato per questo numero di
  secondi, il titolo viene svuotato. Imposta `0` per non cancellare mai
  automaticamente.

Valori più alti = testo più stabile ma meno reattivo; valori più bassi = più
reattivo ma con più rischio di sfarfallio. I valori predefiniti sono un buon
compromesso per il parlato dal vivo.

---

## 12. Log e diagnostica

- Il pulsante **Apri Log** apre la cartella dei log. I file principali sono
  `app.log` (applicazione), `provider.log` (traduzione) e `vmix.log` (uscita
  vMix). I log **non contengono chiavi API né audio**.
- Il pulsante **Info** mostra nome e versione dell'app, il provider attivo, le
  lingue e i percorsi di configurazione e log — utile da comunicare in caso di
  richiesta di assistenza.
- I log sono a rotazione: non crescono all'infinito.

---

## 13. Sicurezza e privacy

- Le **chiavi API sono salvate nel Gestione credenziali di Windows** (Windows
  Credential Manager), mai in file di testo e mai nei log.
- L'**audio non viene salvato su disco** durante il normale funzionamento.
- I messaggi di errore e i log **mascherano eventuali segreti**.
- Usando un provider **cloud**, l'audio/testo viene inviato al servizio scelto
  (OpenAI, Google, Azure, DeepL) per la traduzione: valuta i loro termini di
  servizio. Con i **provider locali** l'elaborazione resta sul tuo PC.

---

## 14. Risoluzione dei problemi

| Messaggio / sintomo | Cosa fare |
|---|---|
| **Nessun audio in ingresso** | Controlla il dispositivo selezionato e i cavi; verifica con **Test Audio** mentre parli nella sorgente. |
| **vMix non raggiungibile** | Verifica che vMix sia aperto e che il **Web Controller** (porta `8088`) sia attivo; controlla Host e Porta nelle Impostazioni. |
| **Manca il nome del titolo** | Compila il campo **Input / Titolo** nelle Impostazioni vMix. |
| **Chiave API non valida** | Reinserisci la chiave in *Impostazioni → Credenziali* e riprova con **Test API**. |
| **Connessione Internet assente** | I provider cloud richiedono Internet: controlla la rete. |
| **Pacchetti locali non installati** | Il provider **Locale** richiede i componenti di `requirements-optional.txt`: usa un provider cloud/Demo oppure installali. |
| **Indirizzo vMix non valido** | Controlla che nell'Host non sia inclusa la porta (Host e Porta sono campi separati). |
| **L'overlay non compare / è sul monitor sbagliato** | In *Impostazioni → Sottotitoli a schermo* attiva l'overlay e scegli il **Monitor** corretto; l'overlay appare quando arriva il primo sottotitolo. |
| **Il testo tradotto tarda ad apparire** | Un'attesa iniziale di 1–2 s è normale: il servizio attende una pausa del parlato prima di tradurre. Se il ritardo è molto maggiore, verifica la connessione e che l'audio arrivi (Test Audio). |

L'elenco completo dei messaggi con cause e soluzioni è in
[TROUBLESHOOTING.md](TROUBLESHOOTING.md). Per i dettagli tecnici usa **Apri Log**.

---

## 15. Disinstallazione

- Disinstalla da **Impostazioni di Windows → App** (voce *Traduttore Live*) oppure
  dalla cartella dell'app.
- La disinstallazione **non tocca** la tua configurazione né i log, che restano
  nel profilo utente (vedi [§17](#17-percorsi-dei-file)). Se vuoi rimuoverli
  del tutto, cancella manualmente quelle cartelle.
- Le **chiavi API** salvate restano nel Gestione credenziali di Windows: se vuoi
  eliminarle, rimuovile da lì.

---

## 16. Domande frequenti

**Un abbonamento ChatGPT Plus/Pro basta per usare OpenAI?**
No. L'app usa le **API** OpenAI, che richiedono un accesso API con credito, cosa
diversa da un abbonamento ChatGPT nel browser.

**Posso provare senza spendere?**
Sì: scegli un provider **Demo**. Mostra frasi di esempio e ti permette di
collaudare audio e connessione a vMix senza usare alcuna API a pagamento.

**Funziona senza Internet?**
Solo con i **provider locali** (offline). I provider cloud richiedono Internet.

**Devo reinserire la chiave ogni volta?**
No. La chiave è salvata in modo sicuro; nelle Impostazioni il campo resta vuoto
ma il valore salvato rimane valido finché non ne inserisci uno nuovo.

**Il sottopancia cambia troppo spesso o troppo poco.**
Regola le impostazioni dei **Sottotitoli** ([§11](#11-le-regole-dei-sottotitoli)):
aumenta l'intervallo minimo e "Mantieni sottotitolo" per più stabilità.

**Posso cambiare la lingua tradotta?**
Sì, in *Impostazioni → Provider* imposta **Lingua sorgente** e **Lingua di
uscita** tra quelle disponibili.

**Posso tradurre un video riprodotto sul PC?**
Sì: come ingresso audio scegli una voce **"Uscita di sistema (loopback)"** e
avvia. L'app tradurrà l'audio riprodotto dal computer, senza bisogno di cavi
audio virtuali.

**Posso mostrare i sottotitoli su uno schermo, senza vMix?**
Sì: attiva i **Sottotitoli a schermo** (interruttore nella finestra principale o
in *Impostazioni → Sottotitoli a schermo*) e scegli il monitor. L'overlay funziona
in aggiunta o in alternativa al titolo vMix.

---

## 17. Percorsi dei file

- **Configurazione**: `%APPDATA%\TranslatorLowerThird\config.yaml`
- **Log**: `%LOCALAPPDATA%\TranslatorLowerThird\logs\` (`app.log`, `provider.log`, `vmix.log`)

> Nota: la cartella interna resta `TranslatorLowerThird` anche se il nome
> visibile dell'app è "Traduttore Live".
