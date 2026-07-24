# „Labor / Experimente"-Element für dennisbf.design

Diese Datei enthält (1) ein **anklickbares Karten-Element** für dein Labor-Raster
und (2) die **Unterseite** dazu (`web/static/labor.html`). Auf der Unterseite ist
der **Button zur App**.

Ablauf: Karte in deine Labor-Sektion einfügen → Karte verlinkt auf die Unterseite
→ auf der Unterseite führt „App öffnen" zur laufenden App.

---

## 1. Karten-Element (in die Labor-Sektion einfügen)

Selbst-gestyltes, anklickbares Kärtchen (passt sich per `currentColor`/Verlauf ein).
`href` auf die Unterseite zeigen lassen (siehe Abschnitt 2 für die URL).

```html
<a class="lab-card" href="/labor/product-image-batch">
  <span class="lab-badge">Experiment</span>
  <h3>Product Image Batch</h3>
  <p>Parallele Produktbild-Generierung aus Referenzbildern über viele Bild-APIs.</p>
  <span class="lab-go">Ansehen →</span>
</a>

<style>
.lab-card{display:block;text-decoration:none;color:#eef0f6;background:rgba(255,255,255,.045);
  border:1px solid rgba(255,255,255,.09);border-radius:18px;padding:1.3rem;transition:.18s;
  -webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px)}
.lab-card:hover{border-color:#8b9cf5;transform:translateY(-2px)}
.lab-badge{display:inline-block;font-size:.72rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
  color:#8b9cf5;background:rgba(139,127,242,.14);border:1px solid rgba(139,127,242,.4);
  padding:.2rem .6rem;border-radius:999px}
.lab-card h3{margin:.8rem 0 .4rem;font-size:1.15rem}
.lab-card p{margin:0 0 1rem;color:#9aa3b8;font-size:.95rem}
.lab-go{font-weight:700;background:linear-gradient(120deg,#9b7ef2,#7aa8ff);
  -webkit-background-clip:text;background-clip:text;color:transparent}
</style>
```

> Falls dein Baukasten schon ein Karten-/Grid-Bauteil hat: einfach eine neue Karte
> mit Titel „Product Image Batch", Badge „Experiment" und Link auf die Unterseite
> anlegen — das obige Styling ist nur ein Vorschlag im Look deiner Seite.

---

## 2. Die Unterseite (`web/static/labor.html`)

Fertig gestylt im Look von dennisbf.design (dunkles Navy, Violett→Blau-Verlauf,
Großbuchstaben-Headline). Darauf: Beschreibung + Button **„App öffnen"**.

Hosten kannst du sie z. B. so:

- **Cloudflare Pages**: `labor.html` als `/labor/product-image-batch` veröffentlichen
  (Datei in dein Pages-Projekt legen, Pfad entsprechend benennen). Dann zeigt die
  Karte aus Abschnitt 1 mit `href="/labor/product-image-batch"` darauf.
- Oder auf demselben App-Server ausgeliefert: erreichbar unter
  `https://app.dennisbf.design/labor.html`.

**Wichtig — zwei Links anpassen** in `web/static/labor.html`:

1. `href="https://app.dennisbf.design"` → die echte URL deiner deployten App
   (siehe `docs/WEB_DEPLOY.md`). Solange die App noch nicht deployt ist, ist das
   ein Platzhalter.
2. `href="/"` beim „← zurück"-Link → deine Startseite.

---

## Reihenfolge zum Live-Gehen

1. App deployen (Backend auf Python-Host) → du bekommst z. B. `app.dennisbf.design`
   (Anleitung: `docs/WEB_DEPLOY.md`).
2. In `labor.html` den „App öffnen"-Link auf diese URL setzen.
3. `labor.html` als Unterseite hosten (`/labor/product-image-batch`).
4. Karte aus Abschnitt 1 in deine Labor-Sektion einfügen, `href` auf die Unterseite.
