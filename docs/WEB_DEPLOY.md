# Browser-Version deployen (Cloudflare + Python-Host)

Die Web-Version besteht aus zwei Teilen:

- **Frontend** — statische Dateien (`web/static/`), laufen überall.
- **Backend** — ein kleiner **Python-Server** (`web/server.py`, FastAPI), der die
  API-Keys hält und die Bild-APIs aufruft. **Muss auf einem Host laufen, der
  Python ausführt** (Cloudflare Workers können das nicht).

> **Wichtig zu Cloudflare:** Cloudflare Pages hostet nur *statische* Seiten und
> Workers laufen nur JavaScript — beides kann das Python-Backend **nicht**
> ausführen. Cloudflare dient hier als **DNS + Proxy** vor einem echten
> Python-Host. Das Backend selbst läuft z. B. auf Render, Railway, Fly.io oder
> deinem eigenen VPS.

Es gibt zwei Wege. **Weg A ist der einfachste** und wird empfohlen.

---

## Weg A — Alles auf einem Python-Host, Cloudflare nur als Domain  ⭐ empfohlen

Das Backend liefert die statische Oberfläche gleich mit (`web/static/` wird unter
`/` ausgeliefert). Du brauchst also nur **einen** Dienst.

### 1. Backend deployen (Beispiel: Render.com)

- Neues **Web Service** aus deinem GitHub-Repo `reioken/image-gen`.
- **Build Command:** `pip install -r requirements.txt -r requirements-web.txt`
- **Start Command:** `uvicorn web.server:app --host 0.0.0.0 --port $PORT`
- **Environment Variables** setzen (siehe [Tabelle unten](#umgebungsvariablen)):
  - `WEB_APP_PASSWORD` (Pflicht — sonst startet der Server nicht)
  - `WEB_APP_SECRET` (langer Zufallswert)
  - Provider-Keys: `OPENAI_API_KEY`, `FAL_KEY`, … (nur die, die du nutzt)
  - optional `WEB_BUDGET_CAP_USD` (z. B. `20`)

(Alternativ mit Docker: das Repo enthält ein `Dockerfile` — funktioniert bei
Railway/Fly.io/VPS genauso.)

Nach dem Deploy hast du eine URL wie `https://xyz.onrender.com`. Öffne sie →
Login-Seite erscheint.

### 2. Cloudflare-Domain darauf zeigen

In deinem Cloudflare-Dashboard (dort, wo `dennisbf.design` liegt):

- **DNS → Record hinzufügen:**
  - Typ **CNAME**, Name **`app`** (ergibt `app.dennisbf.design`),
    Ziel = deine Render-URL (`xyz.onrender.com`), **Proxy an (orange Wolke)**.
- Bei Render/Railway zusätzlich die **Custom Domain** `app.dennisbf.design`
  im Dienst hinterlegen (dort „Add custom domain") — der Anbieter stellt das
  HTTPS-Zertifikat automatisch aus.

Fertig: **https://app.dennisbf.design** zeigt die App. Frontend und Backend sind
dieselbe Herkunft, das Feld „Server-URL" im Login bleibt **leer**.

> Unterseite als Pfad (`dennisbf.design/app`) statt Subdomain? Geht über
> Cloudflare **Origin-Rules/Workers-Routes**, ist aber fummeliger. Für den Start
> ist die Subdomain `app.dennisbf.design` deutlich einfacher.

---

## Weg B — Frontend auf Cloudflare Pages, Backend separat

Nur nötig, wenn du das Frontend unbedingt bei Cloudflare Pages hosten willst.

1. **Backend** wie in Weg A deployen, aber unter eigener Subdomain, z. B.
   `api.dennisbf.design` (CNAME auf den Python-Host).
   - Setze `WEB_CORS_ORIGINS` auf die Frontend-URL, z. B.
     `https://app.dennisbf.design` (damit der Browser Cross-Origin zugreifen darf).
2. **Frontend** auf **Cloudflare Pages**: als Projekt den Ordner `web/static/`
   veröffentlichen (Pages → „Direct Upload" oder Git-Integration mit Output-Verzeichnis `web/static`).
   - Domain `app.dennisbf.design` dem Pages-Projekt zuweisen.
3. Beim ersten Login im Browser unter **„Erweitert: Server-URL"** die Backend-URL
   eintragen: `https://api.dennisbf.design`. Wird im Browser gespeichert.

---

## Lokal testen (vor dem Deploy)

```bash
pip install -r requirements.txt -r requirements-web.txt

# Windows PowerShell:
$env:WEB_APP_PASSWORD="test"; $env:OPENAI_API_KEY="sk-..."
# macOS/Linux:
export WEB_APP_PASSWORD=test OPENAI_API_KEY=sk-...

uvicorn web.server:app --reload --port 8000
```

Dann im Browser `http://localhost:8000` öffnen, mit dem Passwort einloggen.
Ohne echte Keys kannst du zum Testen einen Agenten mit Provider **`mock`** anlegen
(erzeugt lokale Platzhalterbilder, kein Netzwerk).

---

## Umgebungsvariablen

| Variable | Pflicht | Zweck |
|---|:---:|---|
| `WEB_APP_PASSWORD` | ✅ | Login-Passwort. **Ohne diese startet der Server nicht** (Schutz vor versehentlich offenem Server). |
| `WEB_APP_SECRET` | empfohlen | Zufälliger langer Wert zum Signieren der Login-Tokens. Bei mehreren Instanzen zwingend gleich setzen. |
| `WEB_CORS_ORIGINS` | nur Weg B | Erlaubte Frontend-Herkunft/Herkünfte (Komma-getrennt), z. B. `https://app.dennisbf.design`. Standard `*`. |
| `WEB_BUDGET_CAP_USD` | optional | Hartes Gesamt-Budget-Limit in USD über alle Runs. |
| `OPENAI_API_KEY`, `FAL_KEY`, `REPLICATE_API_TOKEN`, … | je nach Nutzung | Provider-Keys. Nur die setzen, die du verwendest. Provider ohne Key erscheinen im UI als „(kein Key)". |

Die Provider-Key-Namen sind identisch zur Desktop-Version (siehe `.env.example`).

---

## Sicherheit & Betrieb

- **Keys bleiben serverseitig** — der Browser bekommt sie nie. Er spricht nur mit
  deinem Backend.
- **Passwortschutz** ist Pflicht. Für zusätzliche Härtung kannst du davor
  **Cloudflare Access** (Zero-Trust) legen — dann kommt man gar nicht erst an die
  Seite, ohne autorisiert zu sein.
- **Kostenkontrolle:** `WEB_BUDGET_CAP_USD` setzen, damit auch bei Missbrauch die
  Ausgaben gedeckelt sind.
- **Bilder** werden auf dem Server unter `outputs/<run>/` gespeichert. Auf
  flüchtigen Hosts (Render Free) verschwinden sie beim Neustart — für dauerhafte
  Ablage ein Volume mounten (Docker: `-v pib_out:/app/outputs`).
- **Skalierung:** Der globale Scheduler hält die Provider-Rate-Limits ein. Bei
  vielen gleichzeitigen Nutzern die Provider-Concurrency in `config/providers.yaml`
  bewusst setzen.

---

## Kurz-Checkliste (Weg A)

1. Repo bei Render/Railway als Web Service verbinden.
2. Build: `pip install -r requirements.txt -r requirements-web.txt`
3. Start: `uvicorn web.server:app --host 0.0.0.0 --port $PORT`
4. Env: `WEB_APP_PASSWORD`, `WEB_APP_SECRET`, Provider-Keys, optional `WEB_BUDGET_CAP_USD`.
5. Cloudflare: CNAME `app` → Host-URL (Proxy an); Custom Domain im Host hinterlegen.
6. `https://app.dennisbf.design` öffnen, einloggen, loslegen.
