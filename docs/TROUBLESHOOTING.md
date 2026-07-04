# Risoluzione dei problemi

Guida rapida per l'operatore. Ogni riquadro di stato in alto nella finestra è un
semaforo: **verde** = tutto ok, **giallo** = non ancora verificato, **rosso** =
problema. Il pulsante **Apri Log** mostra i dettagli tecnici; il pulsante
**Info** mostra versione e percorsi.

---

## Audio

### Nessun audio in ingresso
- **Cosa vedi:** dopo **Test Audio** il semaforo Audio è rosso e compare
  "Nessun audio in ingresso".
- **Causa:** nessun suono arriva al dispositivo selezionato, o è muto.
- **Soluzione:** parla o invia audio mentre premi Test Audio; controlla che il
  microfono/mixer sia collegato e non disattivato in Windows; alza il volume
  d'ingresso.

### Dispositivo audio sbagliato o scollegato
- **Cosa vedi:** "Impossibile aprire l'ingresso audio selezionato" oppure
  "L'ingresso audio salvato … non è più disponibile".
- **Causa:** il dispositivo scelto è stato scollegato o non esiste più.
- **Soluzione:** apri **Impostazioni** e scegli un altro **Ingresso audio**
  dall'elenco; ricollega il dispositivo e riprova.

---

## Chiave API

### API key mancante
- **Cosa vedi:** "Nessuna chiave API salvata. Inseriscila nelle Impostazioni."
- **Causa:** non è stata inserita alcuna chiave del provider di traduzione.
- **Soluzione:** apri **Impostazioni**, incolla la chiave API nel campo
  password e salva. Senza chiave l'app usa solo la modalità dimostrativa.

### API key non valida
- **Cosa vedi:** dopo **Test API** il semaforo API è rosso e compare
  "API key non valida".
- **Causa:** la chiave è errata, scaduta o non abilitata al servizio realtime.
- **Soluzione:** verifica la chiave sul portale del provider e reinseriscila
  nelle Impostazioni. Ricorda: un abbonamento ChatGPT non è una chiave API.

### Connessione Internet assente / provider non raggiungibile
- **Cosa vedi:** "Impossibile raggiungere OpenAI. Controlla la connessione
  Internet." oppure "OpenAI non ha risposto in tempo."
- **Causa:** manca la rete, oppure un firewall/proxy blocca la connessione.
- **Soluzione:** controlla la connessione a Internet; se sei in una rete
  aziendale, verifica che le connessioni sicure in uscita siano permesse.

### Connessione persa durante la diretta
- **Cosa vedi:** nella barra di stato "Connessione persa, riprovo…".
- **Causa:** caduta temporanea della rete o del servizio.
- **Soluzione:** nessuna azione richiesta: l'app riprova automaticamente. Se
  persiste, controlla la rete e, se serve, premi STOP e poi START.

---

## vMix

### vMix non raggiungibile
- **Cosa vedi:** dopo **Test vMix** il semaforo vMix è rosso e compare
  "vMix non raggiungibile su HOST:PORTA".
- **Causa:** vMix non è aperto, oppure il suo Web Controller / API è spento, o
  l'indirizzo/porta è errato.
- **Soluzione:** apri vMix e attiva il **Web Controller** (porta predefinita
  8088); nelle **Impostazioni** dell'app controlla **Host** (di norma
  `127.0.0.1`) e **Porta** (`8088`).

### Indirizzo vMix non valido
- **Cosa vedi:** "Indirizzo vMix non valido (…). Controlla i campi Host e Porta."
- **Causa:** nel campo **Host** è stata inserita anche la porta (es.
  `127.0.0.1:8088`).
- **Soluzione:** metti solo l'indirizzo nel campo Host e il numero nel campo
  Porta, separati.

### Nome del titolo o del campo vMix sbagliato
- **Cosa vedi:** "vMix ha risposto con un errore (HTTP …). Controlla il nome del
  titolo e del campo di testo." oppure il testo non appare nel sottopancia.
- **Causa:** il nome dell'**Input/Titolo** o del **Campo testo** non corrisponde
  a quello del progetto vMix.
- **Soluzione:** nelle Impostazioni imposta **Input/Titolo** con il nome (o
  numero) esatto del titolo in vMix e **Campo testo** con il nome del campo
  (predefinito `Headline.Text`). Usa Test vMix per confermare.

### vMix richiede una password
- **Cosa vedi:** "vMix richiede una password per il Web Controller (HTTP 401/403)."
- **Causa:** il Web Controller di vMix ha l'autenticazione attiva.
- **Soluzione:** disattiva la password nel Web Controller di vMix (questa
  versione dell'app non gestisce l'autenticazione vMix).

### Manca il nome del titolo
- **Cosa vedi:** "vMix raggiungibile, ma manca il nome del titolo."
- **Causa:** il campo **Input/Titolo** è vuoto.
- **Soluzione:** compila **Input/Titolo** nelle Impostazioni (o nella pagina
  vMix del wizard) con il nome del titolo da aggiornare.

---

## Aggiornamento del sottotitolo

### Il sottotitolo non si aggiorna o resta vuoto
- **Causa:** possibile problema di rete verso il provider, oppure il campo vMix
  non è corretto.
- **Soluzione:** controlla i semafori API e vMix con Test API e Test vMix; apri
  **Apri Log** per i dettagli; premi STOP e poi START per riavviare il flusso.

---

## Dove trovo i log e la configurazione

Premi **Info** nella finestra principale: mostra la versione e i percorsi
esatti. In genere:

```text
Configurazione: %APPDATA%\TranslatorLowerThird\config.yaml
Log:            %LOCALAPPDATA%\TranslatorLowerThird\logs\
```

I log non contengono mai la chiave API né l'audio.
