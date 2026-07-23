# Alle Befehle — Spickzettel

Windows/PowerShell zuerst. Projektordner unten überall `$HOME\Documents\image-gen`
(bei dir ggf. anpassen). macOS/Linux: `python3` statt `python`, `source .venv/bin/activate`.

---

## 0. Einmalige Einrichtung

```powershell
# Python prüfen (muss 3.11+ sein). Fehlt es: von python.org installieren, "Add to PATH" anhaken.
python --version

# Projekt holen
cd $HOME\Documents
git clone https://github.com/reioken/image-gen.git
cd image-gen
git checkout claude/product-image-generation-desktop-b1yys4

# Abhängigkeiten installieren
python -m pip install -r requirements.txt
```

## 1. Updates holen (immer zuerst, wenn ich was geändert habe)

```powershell
cd $HOME\Documents\image-gen
git pull
```

---

## 2. Desktop-App (GUI)

```powershell
# Starten
python -m product_image_batch.gui.app

# Oder per Doppelklick: start_app.bat   (installiert Abhängigkeiten + startet)
```

---

## 3. Kommandozeile (CLI)

```powershell
# Hilfe / alle Optionen anzeigen
python -m product_image_batch --help

# Einfachster Lauf: 1 Referenzbild + 1 Prompt (Mock = ohne Key/Netzwerk, zum Testen)
python -m product_image_batch --reference .\produkt.png --prompt "Studio packshot on beige" --providers mock --out .\outputs\test

# Trockenlauf: nur Plan + Kostenschätzung, KEINE API-Calls
python -m product_image_batch --reference .\produkt.png --prompts .\prompts.txt --providers openai,fal --dry-run

# Echter Lauf: mehrere Prompts aus Datei, mehrere Provider, mit Konsistenz-Regeln
python -m product_image_batch `
  --reference .\produkt_front.png --reference .\produkt_seite.png `
  --prompts .\prompts.txt `
  --providers openai,fal,replicate `
  --images-per-prompt 1 `
  --default-master-prompt --rewrite-prompts `
  --out .\outputs\run1 `
  --max-total-cost 25.00

# Prompts automatisch aus einem Briefing erzeugen (z.B. 20 Varianten)
python -m product_image_batch --reference .\produkt.png --brief .\briefing.md --generate-prompts 20 --providers openai --out .\outputs\kampagne

# Eigener Master-Prompt (Konsistenzregel für alle)
python -m product_image_batch --reference .\produkt.png --prompt "White packshot" --providers openai --master-prompt "Keep the exact bottle and label; only change background."

# Master-Prompt aus Datei
python -m product_image_batch --reference .\produkt.png --prompts .\prompts.txt --providers openai --master-prompt-file .\master.txt

# Bestimmte Modelle erzwingen (provider:modell)
python -m product_image_batch --reference .\produkt.png --prompt "hero shot" --models openai:gpt-image-2,fal:fal-ai/image-apps-v2/product-photography --out .\outputs\x
```

**Wichtige CLI-Flags:** `--reference` (mehrfach), `--reference-dir`, `--mask`,
`--prompt`, `--prompts`, `--brief` + `--generate-prompts N`, `--rewrite-prompts`,
`--master-prompt` / `--master-prompt-file` / `--default-master-prompt`,
`--providers`, `--models`, `--images-per-prompt`, `--size`, `--quality`,
`--seed`, `--out`, `--dry-run`, `--max-total-cost`, `--verbose`.

---

## 4. Windows-.exe bauen (portabel, ohne Python auf dem Zielrechner)

```powershell
cd $HOME\Documents\image-gen
.\build_exe.bat
# Ergebnis:
#   dist\ProductImageBatch\ProductImageBatch.exe   (App)
#   dist\ProductImageBatch.zip                     (zum Mitnehmen / Google Drive)
```

---

## 5. Browser-Version (Web)

```powershell
# Web-Abhängigkeiten installieren
python -m pip install -r requirements.txt -r requirements-web.txt

# Pflicht-Umgebungsvariablen setzen (PowerShell)
$env:WEB_APP_PASSWORD="deinPasswort"
$env:WEB_APP_SECRET="ein-langer-zufallswert"
$env:OPENAI_API_KEY="sk-..."      # und/oder andere Provider-Keys
# optional Budget-Deckel:
$env:WEB_BUDGET_CAP_USD="20"

# Server lokal starten -> http://localhost:8000
uvicorn web.server:app --reload --port 8000
```

macOS/Linux Variablen:

```bash
export WEB_APP_PASSWORD=deinPasswort WEB_APP_SECRET=zufall OPENAI_API_KEY=sk-...
uvicorn web.server:app --reload --port 8000
```

Mit Docker:

```bash
docker build -t product-image-batch-web .
docker run -p 8000:8000 -e WEB_APP_PASSWORD=changeme -e WEB_APP_SECRET=$(openssl rand -hex 32) -e OPENAI_API_KEY=sk-... product-image-batch-web
```

---

## 6. Tests

```powershell
python -m pip install -r requirements.txt   # falls noch nicht geschehen
python -m pytest -q                          # alle Tests
python -m pytest tests\test_web.py -q         # nur die Web-Tests
```

---

## 7. Git (Änderungen holen / Stand prüfen)

```powershell
cd $HOME\Documents\image-gen
git pull                 # neueste Änderungen holen
git log --oneline -10    # letzte Commits ansehen
git status               # Arbeitsstand
git stash; git pull      # wenn "local changes" das Pull blockieren
```

---

## 8. API-Keys eintragen

- **Desktop / Web:** über den **Settings-Dialog** (Desktop) bzw. Umgebungsvariablen
  (Web, siehe Abschnitt 5). Keys landen bei der Desktop-App in
  `%APPDATA%\ProductImageBatch\.env`.
- **CLI:** Datei `.env` im Projektordner (Vorlage: `.env.example` kopieren):
  ```powershell
  Copy-Item .env.example .env
  notepad .env
  ```

---

## 9. Wo liegen die Ergebnisse?

```powershell
# Ausgabeordner öffnen (nach einem Lauf)
explorer .\outputs
```

Struktur pro Lauf: `outputs\<zeitstempel>_<name>\images\…`, plus
`metadata.jsonl`, `metadata.csv`, `run_config.yaml`, `prompts.resolved.json`.

---

## 10. Schnelle Fehlerdiagnose

```powershell
# "pip nicht erkannt" -> immer python -m pip nutzen:
python -m pip install -r requirements.txt

# "No module named product_image_batch" -> falscher Ordner. Prüfen:
dir requirements.txt      # muss die Datei zeigen; sonst in den image-gen-Ordner wechseln

# GUI-Abhängigkeit fehlt:
python -m pip install PySide6

# Web-Log (Desktop/.exe):  %APPDATA%\ProductImageBatch\logs\app.log
```
