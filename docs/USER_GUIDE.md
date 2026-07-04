# Guida Utente — Translator Lower Third for vMix

## Cos'è

Translator Lower Third for vMix ascolta l'audio di un evento dal vivo (ad esempio un parlato in
spagnolo), lo traduce in italiano quasi in tempo reale e scrive il testo tradotto in un
sottopancia/titolo di vMix.

## Requisiti

- Windows 10/11
- vMix con Web Controller / API HTTP attiva (porta predefinita 8088)
- Una chiave API del provider di traduzione (OpenAI nella versione 1)
- Un ingresso audio visibile a Windows (microfono, mixer, scheda audio, cavo virtuale…)

## Installazione

1. Esegui `TranslatorLowerThird-Setup.exe`.
2. Segui la procedura guidata (collegamento sul Desktop opzionale).
3. Avvia l'app dal menu Start.

Non serve installare Python né usare il terminale.

## Prima configurazione

Alla prima apertura la procedura guidata chiede:

1. **Ingresso audio** — scegli il dispositivo da cui arriva il parlato.
2. **API key** — incolla la chiave del provider (viene salvata in modo sicuro in Windows,
   mai in file di testo).
3. **Test API** — verifica che la chiave funzioni.
4. **vMix** — indirizzo (di norma `127.0.0.1`), porta (`8088`), nome del titolo e del campo
   di testo (predefinito `Headline.Text`).
5. **Test vMix** — scrive una frase di prova nel titolo configurato.
6. **Salva e avvia.**

## Uso quotidiano

1. Apri l'app.
2. Prima dell'evento premi **Test Audio**, **Test API** e **Test vMix**: i tre
   semafori **Audio**, **API**, **vMix** devono diventare verdi.
3. Premi **START**.
4. Il testo tradotto appare nell'anteprima e nel sottopancia di vMix.
5. A fine evento premi **STOP**.

Se non hai ancora inserito una chiave API, l'app funziona in **modalità
dimostrativa**: mostra testi di esempio, utile per provare la connessione a vMix.

## Pulsanti della finestra principale

| Pulsante | Funzione |
|---|---|
| **START / STOP** | Avvia e ferma la traduzione dal vivo. |
| **Test Audio** | Ascolta alcuni secondi e mostra il livello: verde se rileva audio. |
| **Test API** | Verifica la chiave del provider di traduzione. |
| **Test vMix** | Scrive una frase di prova nel titolo vMix configurato. |
| **Impostazioni** | Provider, chiave API, lingue, audio, vMix, regole sottotitoli. |
| **Apri Log** | Apre la cartella dei log (dettagli tecnici, senza segreti). |
| **Info** | Versione dell'app e percorsi di configurazione e log. |

## Problemi comuni

| Messaggio | Cosa fare |
|---|---|
| Nessun audio in ingresso | Controlla il dispositivo selezionato e i cavi; usa **Test Audio**. |
| vMix non raggiungibile | Verifica che vMix sia aperto e che la porta API (8088) sia attiva. |
| API key non valida | Reinserisci la chiave nelle impostazioni; usa **Test API**. |
| Connessione Internet assente | Controlla la rete: il provider di traduzione richiede Internet. |

Per l'elenco completo dei messaggi con cause e soluzioni vedi
[TROUBLESHOOTING.md](TROUBLESHOOTING.md). I log dettagliati si aprono con il
pulsante **Apri Log**.
