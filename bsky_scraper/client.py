"""Client XRPC minimale per Bluesky con gestione sessione e rate limit."""

import json
import os
import time
from pathlib import Path

import requests

ENTRYWAY = "https://bsky.social"
PUBLIC_APPVIEW = "https://public.api.bsky.app"
MAX_WAIT = 300  # oltre questa attesa (s) meglio fermarsi che bloccarsi
USER_AGENT = "bsky-scraper/0.1 (uso didattico/ricerca)"


class BskyError(Exception):
    def __init__(self, status, error, message):
        super().__init__(f"HTTP {status} {error}: {message}")
        self.status = status
        self.error = error


def load_dotenv(path=".env"):
    """Carica variabili KEY=VALUE da un file .env (senza dipendenze esterne)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


class BskyClient:
    """Gestisce login, refresh del token e chiamate con retry/backoff.

    La sessione viene salvata su disco e riusata: createSession è limitato
    a 30 chiamate ogni 5 minuti e 300 al giorno per account.
    """

    def __init__(self, handle=None, app_password=None, session_file=".session.json",
                 min_interval=0.35, max_retries=8):
        self.handle = handle
        self.app_password = app_password
        self.session_file = Path(session_file)
        self.min_interval = min_interval  # 3000 req / 5 min per IP ~ 10 req/s
        self.max_retries = max_retries
        self.http = requests.Session()
        self.http.headers["User-Agent"] = USER_AGENT
        self.session = None
        self._last_request = 0.0

    # ---------- sessione ----------

    @property
    def authenticated(self):
        return self.session is not None

    @property
    def service(self):
        return self.session.get("service", ENTRYWAY) if self.session else PUBLIC_APPVIEW

    def login(self):
        """Riusa la sessione salvata se valida, altrimenti ne crea una nuova."""
        if self.session_file.exists():
            try:
                saved = json.loads(self.session_file.read_text())
                if not self.handle or saved.get("handle") == self.handle or saved.get("did") == self.handle:
                    self.session = saved
                    self._refresh()
                    return self
            except (BskyError, ValueError, KeyError):
                self.session = None
        if not (self.handle and self.app_password):
            raise RuntimeError(
                "Credenziali mancanti: imposta BSKY_HANDLE e BSKY_APP_PASSWORD nel file .env")
        data = self._raw("POST", ENTRYWAY, "com.atproto.server.createSession",
                         json_body={"identifier": self.handle, "password": self.app_password})
        self._store_session(data)
        return self

    def _refresh(self):
        data = self._raw("POST", self.service, "com.atproto.server.refreshSession",
                         token=self.session["refreshJwt"])
        self._store_session(data)

    def _store_session(self, data):
        service = ENTRYWAY
        for svc in (data.get("didDoc") or {}).get("service", []):
            if svc.get("id") == "#atproto_pds":
                service = svc["serviceEndpoint"]
        self.session = {
            "did": data["did"],
            "handle": data["handle"],
            "accessJwt": data["accessJwt"],
            "refreshJwt": data["refreshJwt"],
            "service": service,
        }
        self.session_file.write_text(json.dumps(self.session))
        os.chmod(self.session_file, 0o600)

    # ---------- richieste ----------

    def get(self, nsid, params=None):
        """GET autenticato (se loggato) con refresh automatico del token."""
        try:
            return self._raw("GET", self.service, nsid, params=params,
                             token=self.session["accessJwt"] if self.session else None)
        except BskyError as e:
            if self.session and e.error in ("ExpiredToken", "InvalidToken"):
                self._refresh()
                return self._raw("GET", self.service, nsid, params=params,
                                 token=self.session["accessJwt"])
            raise

    def _throttle(self):
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _raw(self, method, base, nsid, params=None, json_body=None, token=None):
        url = f"{base}/xrpc/{nsid}"
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                r = self.http.request(method, url, params=params, json=json_body,
                                      headers=headers, timeout=30)
            except requests.RequestException as e:
                delay = min(2 ** attempt, 60)
                print(f"  ! errore di rete ({e.__class__.__name__}), riprovo tra {delay}s")
                time.sleep(delay)
                continue

            if r.status_code == 429:
                delay = self._seconds_to_reset(r) or min(2 ** attempt * 5, 300)
                if delay > MAX_WAIT:
                    resume_at = time.strftime("%H:%M del %d/%m", time.localtime(time.time() + delay))
                    raise BskyError(429, "RateLimitExceeded",
                                    f"limite per {nsid} esaurito, riprova dopo le {resume_at}")
                print(f"  ! rate limit raggiunto (429), attendo {delay}s")
                time.sleep(delay)
                continue
            if r.status_code >= 500:
                delay = min(2 ** attempt, 60)
                print(f"  ! errore server {r.status_code}, riprovo tra {delay}s")
                time.sleep(delay)
                continue
            if r.status_code >= 400:
                try:
                    body = r.json()
                except ValueError:
                    body = {"error": "HTTPError", "message": r.text[:200]}
                raise BskyError(r.status_code, body.get("error"), body.get("message"))
            self._respect_ratelimit_headers(r)
            return r.json()
        raise BskyError(0, "MaxRetries", f"troppi tentativi falliti per {nsid}")

    @staticmethod
    def _seconds_to_reset(r):
        """ratelimit-reset di Bluesky è un timestamp Unix assoluto."""
        try:
            return max(int(r.headers["ratelimit-reset"]) - int(time.time()), 1)
        except (KeyError, ValueError):
            return None

    def _respect_ratelimit_headers(self, r):
        """Se restano poche richieste in una finestra breve, rallenta fino al reset.

        Le finestre lunghe (es. il limite giornaliero sui login) vengono ignorate:
        se si esauriscono, il 429 successivo interrompe con un messaggio chiaro.
        """
        try:
            remaining = int(r.headers["ratelimit-remaining"])
        except (KeyError, ValueError):
            return
        delay = self._seconds_to_reset(r)
        if remaining < 10 and delay and delay <= MAX_WAIT:
            print(f"  ~ quasi al limite ({remaining} rimaste), pausa di {delay}s")
            time.sleep(delay)
