# Bluesky scraper

Strumento didattico/di ricerca per scaricare post da Bluesky tramite le API ufficiali (AT Protocol).

## Versione browser (per gli studenti) — `docs/index.html`
Un unico file HTML, nessuna installazione: tutto gira nel browser dello studente,
che accede con il **proprio** account e la **propria** app password (inviate solo a Bluesky).

- **Ricerca per termine/hashtag** (richiede l'accesso)
- **Tutti i post di un utente** (funziona anche senza accesso, per profili pubblici)
- Raccolte salvate nel browser (IndexedDB): si possono interrompere e riprendere
- Esportazione in CSV (Excel), JSONL (dati completi) e profili

Il modo più affidabile è servirla via http(s): per esempio pubblicandola su
GitHub Pages / sito del corso, oppure in locale con
`python3 -m http.server 8765 --directory docs` e aprendo http://localhost:8765.

## Versione a riga di comando (Python)

### Installazione
```bash
pip3 install -r requirements.txt
cp .env.example .env   # poi inserisci handle e app password
```
L'app password si crea in Bluesky > Impostazioni > Privacy e sicurezza > App password.

### Ricerca per termine o hashtag
```bash
python3 -m bsky_scraper search "intelligenza artificiale"
python3 -m bsky_scraper search "#elezioni" --since 2026-01-01 --until 2026-06-30 --lang it
```
Output in `data/search_<query>/`:
- `posts.jsonl` – post completi così come restituiti dall'API (tutti i metadati)
- `profiles.jsonl` – profili completi degli autori (follower, bio, ...)
- `posts.csv` – tabella pronta per Excel/pandas
- `state.json` – stato per riprendere una ricerca interrotta (basta rilanciare il comando)

La ricerca segue la sintassi di Bluesky: `"frase esatta"`, `from:handle`, `lang:it`, `#tag`.

## Note
- Rispetta automaticamente i rate limit (HTTP 429 e header `RateLimit-*`).
- La sessione è salvata in `.session.json` e riusata, per non superare i limiti di login.
- I dati raccolti sono dati personali (GDPR): conservali in modo sicuro e cancella i post rimossi dagli utenti.
