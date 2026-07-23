# Product Image Batch — Vollständige Dokumentation

> Diese Datei ist als **eigenständige Wissensbasis** geschrieben: Sie erklärt das
> gesamte Projekt so, dass ein Mensch **oder ein KI-Assistent (z. B. Perplexity)**
> jede Frage dazu beantworten kann, ohne den Quellcode zu kennen. Befehle sind in
> Codeblöcken, Konzepte auf Deutsch.

**Was ist das?** Ein lokales Programm (Windows/macOS/Linux), das aus **einem oder
mehreren Produkt-Referenzbildern** und **vielen verschiedenen Prompts** parallel
**Produktbild-Varianten** über **viele Bild-APIs gleichzeitig** erzeugt. Es gibt
eine **Kommandozeile (CLI)** und eine **Desktop-App mit Tabs (GUI)**, die zu einer
eigenständigen Windows-`.exe` gebaut werden kann.

**Kernidee (wichtig):** Es geht **nicht** um „ein Prompt an viele Modelle". Der
Kern-Workflow ist:

> **gleiches Produkt-Referenzbild + viele verschiedene Prompts + mehrere
> Provider/Modelle → parallele Produktbild-Varianten.**

---

## Inhaltsverzeichnis

1. [Grundbegriffe / Glossar](#1-grundbegriffe--glossar)
2. [Wie es im Prinzip funktioniert](#2-wie-es-im-prinzip-funktioniert)
3. [Architektur](#3-architektur)
4. [Installation (Windows, Schritt für Schritt)](#4-installation-windows-schritt-für-schritt)
5. [API-Keys besorgen (Direktlinks)](#5-api-keys-besorgen-direktlinks)
6. [Unterstützte Provider & Modelle](#6-unterstützte-provider--modelle)
7. [Die Desktop-GUI bedienen](#7-die-desktop-gui-bedienen)
8. [Der Master-Prompt (Konsistenz-Regel für alle)](#8-der-master-prompt-konsistenz-regel-für-alle)
9. [Konsistenz maximieren — Praxis-Tipps](#9-konsistenz-maximieren--praxis-tipps)
10. [Die Kommandozeile (CLI)](#10-die-kommandozeile-cli)
11. [Prompt-Rewriting & Brief-Generierung](#11-prompt-rewriting--brief-generierung)
12. [Nebenläufigkeit, Rate-Limits & Budget](#12-nebenläufigkeit-rate-limits--budget)
13. [Ausgabe-Ordner & Metadaten](#13-ausgabe-ordner--metadaten)
14. [Konfigurationsdateien](#14-konfigurationsdateien)
15. [Die Windows-.exe bauen](#15-die-windows-exe-bauen)
16. [Fehlerbehebung (Troubleshooting)](#16-fehlerbehebung-troubleshooting)
17. [FAQ](#17-faq)

---

## 1. Grundbegriffe / Glossar

| Begriff | Bedeutung |
|---|---|
| **Referenzbild** | Ein Foto des Produkts, das als Identitäts-Vorlage mitgeschickt wird. Alle Generierungen sollen dasselbe Produkt zeigen. Formate: PNG, JPG, JPEG, WEBP. |
| **Maske** | Optionale PNG-Datei (mit Transparenz), die angibt, welcher Bildbereich verändert werden darf (Inpainting). Nur für Provider, die das können (OpenAI, Recraft, Ideogram, Stability). |
| **Prompt** | Textbeschreibung des gewünschten Zielbildes (Szene, Licht, Hintergrund, Kamerawinkel). |
| **Master-Prompt** | Eine **globale Regel pro Tab**, die **jedem** Prompt automatisch vorangestellt wird (Konsistenz, Setting, Stil). Siehe [Abschnitt 8](#8-der-master-prompt-konsistenz-regel-für-alle). |
| **Agent / Agent-Zeile** | Eine Zeile in einem Tab = **1 Prompt + 1 Provider + 1 Modell + Anzahl Bilder** (+ Größe, Seed, Strength). Alle Agenten eines Tabs laufen gleichzeitig. |
| **Tab** | Eine unabhängige Run-Konfiguration: eigener Name, eigene Referenzbilder/Maske, eigener Master-Prompt, eigene Agenten-Liste. |
| **Provider** | Ein Bild-API-Anbieter (OpenAI, Google, fal, Replicate, …). |
| **Task** | Die kleinste Arbeitseinheit: genau **1 Bild** einer bestimmten (Provider, Modell, Prompt)-Kombination. Ein Agent mit „Bilder = 3" erzeugt 3 Tasks. |
| **Scheduler** | Der zentrale Motor, der alle Tasks parallel, aber rate-limit-sicher ausführt. |
| **Concurrency** | Wie viele Anfragen gleichzeitig laufen (global und pro Provider einstellbar). |

---

## 2. Wie es im Prinzip funktioniert

1. Du gibst **Referenzbild(er)** an (Drag & Drop in der GUI oder `--reference` in der CLI).
2. Du gibst **Prompts** an — direkt getippt (Agent-Zeilen), aus einer Textdatei,
   oder automatisch aus einem **Briefing** erzeugt.
3. Optional definierst du einen **Master-Prompt** mit Konsistenz-/Setting-Regeln,
   der für **alle** Prompts gilt.
4. Du wählst **Provider und Modelle** aus (pro Agent in der GUI, oder `--providers` in der CLI).
5. Das Programm bildet alle **Tasks** = `Provider/Modell × Prompt × Anzahl Bilder`,
   schickt bei **jedem** Task dieselben Referenzbilder mit und lässt sie **parallel** laufen.
6. Ergebnisse werden sofort heruntergeladen und in einem sauber strukturierten
   **Ausgabe-Ordner** gespeichert; jede Generierung wird in `metadata.jsonl` protokolliert.

Beispiel: 2 Referenzbilder + 3 Prompts + 3 Provider ⇒ **9 Tasks**, die gleichzeitig
laufen und 9 Produktbild-Varianten liefern.

---

## 3. Architektur

Drei Schichten mit **strikt einseitiger** Abhängigkeit:

```
  cli.py (Kommandozeile)          gui/ (PySide6-Desktop-App)
        \                                /
         \        baut Tasks, ruft      /
          \       dieselbe Engine      /
           v                          v
     ┌──────────────────────────────────────────┐
     │  core/  — die Engine (async, KEINE GUI)   │
     │  config · models · assets · prompting ·   │
     │  budget · metadata · scheduler · providers│
     └──────────────────────────────────────────┘
```

- **`core/`** enthält die gesamte Logik und importiert **nie** GUI-Code. Dadurch
  ist die Engine unabhängig testbar, und CLI und GUI teilen sich denselben Code.
- **Provider-Adapter-Muster:** Jeder Provider kapselt Auth, Request-Format,
  Datei-Upload, Job-Polling, Download und Fehler-Normalisierung hinter einer
  kleinen einheitlichen Schnittstelle. Neue Provider hinzufügen = eine neue
  Adapter-Datei + Registry-Eintrag.
- **Ein globaler Scheduler:** Auch wenn viele Tabs gleichzeitig laufen, gibt es
  **genau einen** Scheduler mit **einem Semaphor-Set pro Provider**. So
  vervierfacht das Öffnen von 4 Tabs **nicht** die Anfragerate pro Provider —
  wichtig, um Rate-Limits/Sperren zu vermeiden.
- **Async-Bridge (GUI):** Ein eigener Hintergrund-Thread führt die asyncio-Engine
  aus; Ergebnisse kommen über Qt-Signals zurück in den UI-Thread. Deshalb
  **friert die GUI während der Generierung nie ein**.

Details siehe `docs/ARCHITECTURE.md` im Repository.

---

## 4. Installation (Windows, Schritt für Schritt)

Voraussetzung: **Python 3.11 oder neuer** (getestet bis 3.14).

**PowerShell** öffnen und blockweise ausführen:

```powershell
# 1) Python prüfen. Falls Fehler: von python.org installieren
#    und beim Installer "Add python.exe to PATH" anhaken.
python --version

# 2) Projekt holen und hineinwechseln
cd $HOME\Documents
git clone https://github.com/reioken/image-gen.git
cd image-gen
git checkout claude/product-image-generation-desktop-b1yys4

# 3) Abhängigkeiten installieren (python -m pip ist zuverlässiger als bloßes pip)
python -m pip install -r requirements.txt

# 4) GUI starten
python -m product_image_batch.gui.app
```

Prüfen, ob man im richtigen Ordner ist: `dir requirements.txt` muss die Datei zeigen.

> Hinweis: Warnungen wie „pyside6-designer.exe … is not on PATH" sind **harmlos** —
> die App startet über `python -m`, nicht über diese Hilfs-Tools.

Neueste Änderungen später holen: im Projektordner `git pull`, dann App neu starten.

macOS/Linux identisch, nur venv aktivieren mit `source .venv/bin/activate`.

---

## 5. API-Keys besorgen (Direktlinks)

Keys werden **nie** im Code oder in der `.exe` gespeichert. In der GUI trägst du sie
im **Settings-Dialog** ein (gespeichert in `%APPDATA%\ProductImageBatch\.env`).
Neben jedem Provider stehen anklickbare Links **🔑 Get key** und **💲 Pricing**.

| Provider | Umgebungsvariable | Key holen | Preise |
|---|---|---|---|
| OpenAI GPT Image | `OPENAI_API_KEY` | platform.openai.com/api-keys | openai.com/api/pricing |
| Google Gemini / Imagen | `GOOGLE_API_KEY` | aistudio.google.com/apikey | ai.google.dev/pricing |
| Black Forest Labs (FLUX) | `BFL_API_KEY` | dashboard.bfl.ai | docs.bfl.ai/pricing |
| Stability AI | `STABILITY_API_KEY` | platform.stability.ai/account/keys | platform.stability.ai/pricing |
| fal.ai | `FAL_KEY` | fal.ai/dashboard/keys | fal.ai/pricing |
| Replicate | `REPLICATE_API_TOKEN` | replicate.com/account/api-tokens | replicate.com/pricing |
| Ideogram | `IDEOGRAM_API_KEY` | ideogram.ai/manage-api | developer.ideogram.ai/…/pricing |
| Recraft | `RECRAFT_API_TOKEN` | recraft.ai/profile/api | recraft.ai/docs |
| Leonardo.Ai | `LEONARDO_API_KEY` | app.leonardo.ai/api-access | leonardo.ai/api |
| Freepik / Magnific (optional) | `FREEPIK_API_KEY` | freepik.com/developers | freepik.com/api |

Provider **ohne Key werden automatisch übersprungen** (protokolliert als
`skipped_missing_key`). Du brauchst nur die Keys der Provider, die du nutzen willst.

---

## 6. Unterstützte Provider & Modelle

| Provider | Referenzbilder | Masken | Beispiel-Modelle |
|---|:---:|:---:|---|
| **OpenAI GPT Image** | ✅ bis 16 | ✅ | `gpt-image-2` (Standard), `gpt-image-1.5`, `gpt-image-1`, `gpt-image-1-mini` |
| **Google Gemini / Imagen** | ✅ mehrere | — | `gemini-2.5-flash-image` (Nano Banana), `gemini-3-pro-image`, `imagen-4.0-generate-001` |
| **Black Forest Labs (FLUX)** | ✅ bis 8 | — | `flux-2-pro`, `flux-2-flex`, `flux-kontext-pro`, `flux-kontext-max` |
| **Stability AI** | ✅ | ✅ | `stable-image-ultra`, `sd3.5-large`, `sd3.5-large-turbo`, `core` |
| **fal.ai** | ✅ | — | `fal-ai/image-apps-v2/product-photography`, `fal-ai/flux-pro/kontext`, `fal-ai/nano-banana/edit` |
| **Replicate** | ✅ | — | `black-forest-labs/flux-kontext-pro`, `…/flux-kontext-max`, `…/flux-1.1-pro` |
| **Ideogram** | ✅ | ✅ | `V_3` (Standard), `V_2`, `V_2_TURBO` |
| **Recraft** | ✅ | ✅ | `recraftv3`, `recraftv2` |
| **Leonardo.Ai** | ✅ | — | `leonardo-phoenix` |
| **Freepik / Magnific** | ⚠️ Gerüst | — | standardmäßig aus; benötigt eigene Account-Doku |
| **Midjourney** | ❌ | — | **nicht implementiert** (keine offizielle öffentliche API) |

Zusätzlich gibt es einen eingebauten **`mock`**-Provider (kein Netzwerk) für
`--dry-run`-Demos und Tests.

**Wichtig:** Das Modell-Feld in jeder Agent-Zeile ist **editierbar** — du kannst
jede Modell-ID direkt eintippen, auch wenn sie nicht in der Liste steht. Sie wird
1:1 an die API geschickt. Ist eine ID für deinen Account nicht freigeschaltet,
kommt eine klare `403`/`422`-Meldung (kein Absturz).

---

## 7. Die Desktop-GUI bedienen

Layout eines Fensters:

```
[+ New tab] [Settings] [Start all tabs] [Stop all]          Budget: $--
[ Run A ][ Run B ][ Run C ][+]
  Master prompt (globale Regel für alle Agenten dieses Tabs)
    [ PRODUCT CONSISTENCY: … SETTING & STYLE: … QUALITY: … ]  [Reset] [Clear]
  Reference images (Drag & Drop oder Browse)     [Mask: optional]
  Agents (jede Zeile läuft parallel):
    Agent 1  Provider:[openai ▾] Modell:[gpt-image-2 ▾]  Bilder:[2]
    Prompt 1: [ Studio-Shot auf beigem Hintergrund… ]     Status: running (1/2)
    Agent 2  Provider:[fal ▾]    Modell:[product-photography ▾]  Bilder:[3]
    Prompt 2: [ Outdoor-Lifestyle-Shot bei Dämmerung… ]   Status: done (3/3)
    [+ Add agent]
  [▶ Start this tab] [■ Stop] [⧉ Duplicate tab] [📁 Open folder] [Close tab]
  Results (Live-Thumbnails, Doppelklick öffnet): 🖼️ 🖼️ 🖼️ …
```

**Toolbar (oben):**
- **+ New tab** — neuer, leerer Tab.
- **Settings** — globale Einstellungen: Concurrency, Budget, Provider aktivieren,
  API-Keys eintragen (siehe [Abschnitt 12](#12-nebenläufigkeit-rate-limits--budget)).
- **Start all tabs** — startet alle noch nicht laufenden Tabs gleichzeitig.
- **Stop all** — bricht alle laufenden Tabs ab.
- **Budget: $…** — laufend geschätzte Kosten.

**Pro Tab:**
- **Master prompt** (oben) — globale Konsistenz-Regel, siehe [Abschnitt 8](#8-der-master-prompt-konsistenz-regel-für-alle).
- **Reference images** — Produktbilder per Drag & Drop aus dem Explorer oder über
  **Browse…** hinzufügen. Jedes zeigt ein Thumbnail mit **✕ remove**.
- **Mask (optional)** — PNG-Maske für Inpainting.
- **Agents** — beliebig viele Agent-Zeilen via **+ Add agent**. Jede Zeile: Provider,
  Modell, Prompt, Bilder-Anzahl, Größe, Seed, Strength, plus Live-Status/Fortschritt.
- **▶ Start this tab** — startet diesen Tab. Mehrfach klickbar; jeder Klick erzeugt
  einen **neuen Unterordner** mit Zeitstempel (alte Ergebnisse bleiben erhalten).
- **■ Stop** — bricht **nur diesen** Tab ab.
- **⧉ Duplicate tab** — kopiert die **komplette** Konfiguration (Referenzbilder,
  Master-Prompt, alle Agenten) in einen neuen Tab, den du parallel starten kannst.
- **📁 Open folder** — öffnet den Ausgabe-Ordner dieses Runs.
- **Results** — Thumbnails erscheinen **sofort nach Fertigstellung** jedes Bildes;
  Doppelklick öffnet die Datei im Standard-Bildbetrachter.

**Mehrere Runs gleichzeitig:** Öffne mehrere Tabs (neu oder dupliziert) und starte
sie einzeln oder über **Start all tabs**. Der globale Scheduler hält alles schnell,
ohne Provider-Limits zu sprengen.

---

## 8. Der Master-Prompt (Konsistenz-Regel für alle)

Der **Master-Prompt** ist ein Textfeld oben in jedem Tab. Sein Inhalt wird
**jedem** Agenten dieses Tabs automatisch **vorangestellt** — über alle Prompts und
alle Provider hinweg. So teilen sich sämtliche Varianten dieselbe Grundregel für
Produkt-Identität, Setting, Licht und Qualität.

**Reihenfolge im finalen Prompt, der an die API geht:**

```
[ Master-Prompt ]          ← globale Regeln, führen jedes Bild an
[ Provider-Hinweis ]       ← providerspezifische Formulierung
[ Prompt der Agent-Zeile ] ← die konkrete Szene dieses Shots
[ Preservation-Reminder ]  ← automatische „Produkt exakt erhalten"-Erinnerung
```

**Standard-Vorlage** (frei editierbar, Button „Reset to default"):

```text
PRODUCT CONSISTENCY (applies to every image):
- Keep the exact same product in every image: identical shape, proportions,
  size ratios, materials, colors, textures and finish.
- Preserve all branding exactly — logo, label text, typography, icons and their
  placement. Do not alter, translate, reflow, blur or invent any text.
- Do not add, remove, duplicate or swap any product part (cap, lid, nozzle,
  seams, labels).
- Only the scene may change: background, surface, lighting, camera angle,
  styling and props.

SETTING & STYLE:
- Photorealistic, high-end commercial product photography.
- Clean studio-grade lighting with soft, believable shadows and accurate reflections.
- Neutral, true-to-life color balance; product tack-sharp; realistic, shallow depth of field.
- Consistent camera height, distance and framing across shots unless a prompt
  explicitly says otherwise.

QUALITY:
- High resolution, crisp detail. No artifacts, no watermarks, no extra text,
  no warped geometry, no distortions.
```

Du kannst die Vorlage überschreiben — z. B. konkrete Marke, Materialbeschreibung,
Hintergrundfarbe, Lichtsetup, Seitenverhältnis. Alles darin gilt für **alle**
Agenten des Tabs.

**In der CLI:** `--default-master-prompt` (eingebaute Vorlage), `--master-prompt "…"`
(eigener Text) oder `--master-prompt-file pfad.txt` (aus Datei).

Beim **Tab duplizieren** wird der Master-Prompt mitkopiert.

---

## 9. Konsistenz maximieren — Praxis-Tipps

Der Master-Prompt macht Konsistenz **deutlich wahrscheinlicher**, aber kein Modell
garantiert sie zu 100 %. So holst du das Maximum heraus:

1. **Gute Referenzbilder:** scharf, gut ausgeleuchtet, Produkt freigestellt oder
   auf neutralem Grund; ggf. mehrere Ansichten (Front + Seite) als zusätzliche
   Identitäts-Referenzen.
2. **Fester Seed:** In der Agent-Zeile das Feld **Seed** auf einen festen Wert
   setzen. Dann bleibt bei erneutem Lauf mehr gleich; nur die Szene variiert.
3. **Strength bewusst wählen** (bei image-to-image: Stability, Recraft):
   - **niedrig** (z. B. 0.3–0.45) = Produkt bleibt stärker erhalten, weniger Szenenwechsel;
   - **hoch** = mehr kreative Freiheit, aber Risiko, dass sich das Produkt verändert.
4. **Editing-starke Modelle bevorzugen** für Produkttreue: OpenAI GPT Image,
   Google Gemini 2.5 Flash Image (Nano Banana), BFL FLUX Kontext, fal Product-Photography.
5. **Referenzen im Prompt benennen** (macht der Rewriter automatisch), z. B.
   „Image 1 is the product identity reference".
6. **Maske nutzen**, wenn nur der Hintergrund geändert werden soll: dann bleibt das
   Produkt unangetastet (Provider mit Masken-Support: OpenAI, Recraft, Ideogram, Stability).
7. **Negative Prompts** werden automatisch gesetzt (verhindert verzerrtes Logo,
   geänderten Text, zusätzliche Produkte, Watermarks) — bei Providern, die sie unterstützen.

---

## 10. Die Kommandozeile (CLI)

Aufruf: `python -m product_image_batch [OPTIONEN]`

Vollständiges Beispiel:

```bash
python -m product_image_batch \
  --reference ./input/product_front.png \
  --reference ./input/product_side.png \
  --prompts ./prompts/product_shots.txt \
  --providers openai,fal,replicate \
  --images-per-prompt 1 \
  --default-master-prompt \
  --rewrite-prompts \
  --out ./outputs/run_2026_07_23 \
  --max-total-cost 25.00
```

**Wichtigste Optionen:**

| Option | Bedeutung |
|---|---|
| `--reference PATH` | Referenzbild (mehrfach nutzbar). |
| `--reference-dir PATH` | Ganzer Ordner mit Referenzbildern. |
| `--mask PATH` | Optionale PNG-Maske (Inpainting). |
| `--prompt "TEXT"` | Ein einzelner Prompt. |
| `--prompts PATH` | Prompt-Datei (`.txt` = ein Prompt pro Zeile, oder `.json`). |
| `--brief PATH` | Basis-Briefing für automatische Prompt-Erzeugung. |
| `--generate-prompts N` | N Prompt-Varianten aus dem Briefing erzeugen. |
| `--rewrite-prompts` | Fügt Produkt-Erhaltungs- und providerspezifische Formulierungen hinzu. |
| `--master-prompt "TEXT"` | Globale Regel vor jeden Prompt. |
| `--master-prompt-file PATH` | Master-Prompt aus Datei. |
| `--default-master-prompt` | Eingebaute starke Konsistenz-Vorlage verwenden. |
| `--providers a,b,c` | Provider-Liste (überschreibt „enabled" aus der Config). |
| `--models openai:gpt-image-2,fal:…` | Explizite provider:modell-Paare. |
| `--images-per-prompt N` | Bilder pro Prompt. |
| `--size`, `--quality`, `--output-format`, `--seed` | Bild-Parameter. |
| `--out PATH` | Ausgabe-Ordner. |
| `--dry-run` | Nur Plan + Kostenschätzung, **keine** API-Calls. |
| `--max-total-cost FLOAT` | Hartes Budget-Limit (bricht neue Jobs ab, wenn überschritten). |
| `--config PATH` | Eigene `providers.yaml`. |
| `--verbose` | Ausführliche Logs. |

Hilfe anzeigen: `python -m product_image_batch --help`.

**Validierung:** Mindestens ein Referenzbild und mindestens ein Prompt (oder ein
Briefing mit `--generate-prompts`) sind erforderlich. Provider ohne Key oder ohne
Referenzbild-Support werden übersprungen.

---

## 11. Prompt-Rewriting & Brief-Generierung

Das Rewriting-Modul erzeugt aus deinen Prompts **provider-spezifische** Varianten
mit **Produkt-Erhaltungs-Anweisungen**. Es läuft standardmäßig **offline** und
deterministisch — **kein** LLM-Key nötig.

- **`--rewrite-prompts`**: Hängt an jeden Prompt Erhaltungsregeln
  („Preserve the exact product shape, proportions, logo, label text, color,
  material and packaging geometry.") und einen providerspezifischen Hinweis an.
- **`--brief briefing.md --generate-prompts 20`**: Erzeugt 20 Szenen-Varianten aus
  einem Briefing (verschiedene Hintergründe, Licht, Kamerawinkel), jeweils mit
  Erhaltungsregeln. Ein Beispiel-Briefing liegt unter `examples/briefing.md`.

Die tatsächlich gesendeten Prompts werden pro Run in `prompts.resolved.json`
gespeichert (nachvollziehbar, was an jede API ging).

---

## 12. Nebenläufigkeit, Rate-Limits & Budget

Einstellbar im **Settings-Dialog** (GUI) bzw. `config/providers.yaml` (CLI):

- **Globales Concurrency-Limit** — max. gleichzeitige Anfragen über **alle**
  Provider (Sicherheitsdeckel, Standard 20).
- **Pro-Provider-Concurrency** — eigener Wert je Provider. Konservative Defaults:
  OpenAI 2, Stability 6, Replicate 10, fal 2, Ideogram 8. Höher stellen, wenn dein
  Account-Tier es erlaubt.
- **Max. gleichzeitig laufende Tabs** (optional).
- **Auto-Retry An/Aus** + **Max. Retries** (Standard 3). Wiederholt bei
  429/5xx/Timeouts mit exponentiellem Backoff und respektiert `Retry-After`.
- **Budget-Cap gesamt** und **pro Tab** (USD). Bei Überschreitung werden neue Tasks
  **nicht** gestartet (als „skipped" protokolliert).

**Warum ein globaler Scheduler?** Weil sonst 4 gleichzeitige Tabs die Anfragerate
pro Provider vervierfachen und 429-Fehler/Sperren auslösen würden. Es gibt genau
**einen** Semaphor-Satz pro Provider, den sich alle Tabs teilen.

**Fehlerbehandlung:**
- **Auth-Fehler (401/403)** deaktivieren den Provider für den Rest des Runs
  (ein falscher Key wird nicht endlos wiederholt).
- **Content-Policy-Ablehnungen** werden **nicht** wiederholt.
- **Rate-Limits (429)** → warten und erneut versuchen.
- Ein fehlerhafter Provider **blockiert nie** den ganzen Batch.

---

## 13. Ausgabe-Ordner & Metadaten

Struktur pro Run:

```
outputs/
  20260723T221430Z_Run_A/
    run_config.yaml            # exakte Konfiguration dieses Runs
    prompts.resolved.json      # die tatsächlich gesendeten Prompts
    metadata.jsonl             # eine Zeile pro Bild/Fehler (inkrementell)
    metadata.csv               # am Ende aus der JSONL erzeugt
    errors.jsonl               # normalisierte Fehler
    images/
      openai_gpt-image-2_a01_20260723T221501Z_0001.png
      fal_fal-ai_image-apps-v2_product-photography_a02_20260723T221508Z_0001.webp
    refs/                      # Kopien der verwendeten Referenzbilder
    masks/                     # Kopie der Maske (falls vorhanden)
```

**Dateinamen:** `{provider}_{modell}_{prompt-id}_{utc-zeitstempel}_{index}.{ext}`,
bereinigt auf `[a-zA-Z0-9._-]` (`/` und `:` werden zu `_`), mit
Kollisions-Suffixen.

**Jede `metadata.jsonl`-Zeile** enthält Status, Provider/Modell, Prompt (roh +
umgeschrieben), Negativ-Prompt, Referenzbilder, Parameter (Größe, Seed, Qualität),
Ausgabedateien, Latenz, geschätzte/tatsächliche Kosten und ggf. Fehler. Ein Absturz
mitten im Lauf hinterlässt trotzdem eine **gültige, bis dahin vollständige** Datei.

---

## 14. Konfigurationsdateien

- **`config/providers.yaml`** — Provider-Defaults: `enabled`, `max_concurrent`,
  Rate-Limits, Modell-Listen. Konservativ und rate-limit-sicher voreingestellt.
- **`config/prompt_rewrite.yaml`** — Erhaltungs-Anweisungen, Provider-Hinweise,
  Standard-Negativ-Prompt für den Rewriter.
- **`config/settings.default.json`** — Vorlage für die benutzereigene
  `settings.json`.

**Benutzer-Dateien** (außerhalb des Programms, pro Nutzer):
- Windows: `%APPDATA%\ProductImageBatch\.env` (API-Keys) und `settings.json`
  (Einstellungen) und `logs\app.log` (Log).
- Diese werden beim ersten Start automatisch aus den Vorlagen angelegt.

**Sicherheit:** API-Keys werden nie ins Repository committet und nie in die `.exe`
eingebacken. Die `.env` und der `outputs/`-Ordner sind git-ignoriert.

---

## 15. Die Windows-.exe bauen

> PyInstaller kann **nicht** cross-kompilieren: Eine Windows-`.exe` muss **auf
> Windows** gebaut werden (nicht von Linux/macOS aus).

Auf einem Windows-PC, im Projektordner:

```bat
build_exe.bat
```

Das erstellt eine venv, installiert Abhängigkeiten + PyInstaller und baut mit
`build\product_image_batch.spec`. Ergebnis:

```
dist\ProductImageBatch\ProductImageBatch.exe
```

Den ganzen Ordner `dist\ProductImageBatch\` weitergeben (oder zippen).

- **One-Dir statt One-File** (bewusst): One-File entpackt sich bei jedem Start neu
  und ist langsamer; One-Dir startet am schnellsten.
- **Keine Keys eingebacken:** Nur Vorlagen (`config/`, `.env.example`) sind
  enthalten; echte Keys liegen zur Laufzeit in `%APPDATA%\ProductImageBatch\.env`.
- **Kein Konsolenfenster** (`console=False`); Logs gehen nach
  `%APPDATA%\ProductImageBatch\logs\app.log`.

Beim ersten Start der `.exe`: **Settings** öffnen, API-Keys eintragen, speichern,
dann Referenzbild reinziehen und **Start this tab**.

---

## 16. Fehlerbehebung (Troubleshooting)

| Symptom | Ursache & Lösung |
|---|---|
| `pip` wird nicht erkannt | Python nicht installiert / nicht im PATH. Von python.org installieren, „Add to PATH" anhaken, PowerShell neu öffnen. `python -m pip` statt `pip` verwenden. |
| `No module named product_image_batch` | Du bist nicht im Projektordner. `cd` in den `image-gen`-Ordner (dort, wo `requirements.txt` liegt). |
| `401` / `ProviderAuthError` | Key fehlt/falsch. In Settings prüfen. Der Provider wird nach Auth-Fehler für den Run deaktiviert. |
| `403` | Key hat keinen Zugriff auf dieses Modell/Endpoint oder Account nicht freigeschaltet. |
| `422` / `ProviderInvalidInputError` | Falsche Parameter oder nicht unterstütztes Modell/Format. Modell-ID prüfen. |
| `429` / `ProviderRateLimitError` | Rate-Limit. Das Tool wartet und wiederholt. Bei Dauerproblem Concurrency dieses Providers senken. |
| Timeouts | Netzwerk/langsamer Job. Wird mit Backoff wiederholt. |
| Content-Policy-Ablehnung | Prompt anpassen (wird nicht wiederholt). |
| Provider übersprungen | Kein Key (`skipped_missing_key`) oder kein Referenzbild-Support. |
| GUI startet nicht | `pip install PySide6` bzw. `pip install .[gui]`. |
| `.exe`-Build scheitert auf Linux/Mac | Erwartet — auf Windows bauen (kein Cross-Compile). |
| Warnung „…exe is not on PATH" | Harmlos, ignorieren. |

Logs: Konsole (CLI) und `%APPDATA%\ProductImageBatch\logs\app.log` (GUI/.exe).

---

## 17. FAQ

**F: Kann ich mit einem Klick alle Provider auf denselben Prompt loslassen?**
A: Ja — lege pro gewünschtem Provider eine Agent-Zeile mit demselben Prompt an
(oder dupliziere eine Zeile) und starte den Tab. Für „ein Prompt, viele Provider"
ist das der Weg. Der eigentliche Kern-Workflow ist aber „ein Produkt, viele Prompts".

**F: Wie lasse ich dieselbe Konfiguration mehrfach gleichzeitig laufen?**
A: **⧉ Duplicate tab** so oft wie nötig, dann **Start all tabs**. Alle laufen
parallel und teilen sich die rate-limit-sicheren Provider-Pools.

**F: Werden Referenzbilder bei jedem Prompt mitgeschickt?**
A: Ja. Bei jedem Task gehen dieselben Referenzbilder mit; nur der Prompt variiert.

**F: Kostet ein Fehlversuch Geld?**
A: Unterschiedlich je Provider. Serverfehler (5xx) sind meist kostenlos;
Client-Fehler können je nach bereits verbrauchter Rechenzeit berechnet werden.
Das Tool protokolliert Kosten, garantiert aber keine Abrechnungsdetails.

**F: Wo sehe ich die genaue Kostenschätzung vor dem Start?**
A: `--dry-run` (CLI) zeigt Plan + geschätzte Kosten ohne API-Calls. In der GUI zeigt
die Toolbar laufend die geschätzten Kosten; Budget-Caps setzt du in Settings.

**F: Warum ist Midjourney nicht dabei?**
A: Es gibt keine offizielle öffentliche Midjourney-API. Automatisierung ginge nur
über inoffizielle Drittanbieter mit ToS-/Zuverlässigkeitsrisiko — daher bewusst
deaktiviert.

**F: Kann ich eigene Provider/Modelle hinzufügen?**
A: Ja. Modelle: einfach die ID ins editierbare Modell-Feld tippen oder in
`config/providers.yaml` ergänzen. Neuer Provider: eine Adapter-Datei unter
`core/providers/` anlegen und in `registry.py` registrieren.

**F: Läuft das komplett lokal?**
A: Das Programm läuft lokal auf deinem PC. Die Bild-Generierung passiert bei den
jeweiligen Cloud-APIs (dorthin gehen Referenzbild + Prompt). Ohne Provider-Keys
kannst du nur den eingebauten `mock`-Provider / `--dry-run` nutzen.

---

*Projekt-Repository: `reioken/image-gen` · Branch
`claude/product-image-generation-desktop-b1yys4`. Weitere technische Details:
`README.md` und `docs/ARCHITECTURE.md`.*
