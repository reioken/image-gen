# App mitnehmen: auf einen anderen PC (z. B. Arbeitsrechner)

Es gibt zwei Wege. **Weg A (.exe)** ist der beste für einen gesperrten
Arbeitsrechner — dort wird **kein Python** benötigt.

---

## Weg A — Portable `.exe` (kein Python auf dem Zielrechner nötig)  ⭐ empfohlen

Einmal auf deinem **Windows-PC mit Python** (dein jetziger Rechner) bauen, dann
mitnehmen. Eine Windows-`.exe` muss auf Windows gebaut werden — nicht von Mac/Linux.

**1. Bauen (auf dem PC mit Python), im Projektordner:**

```bat
build_exe.bat
```

Ergebnis:
- `dist\ProductImageBatch\ProductImageBatch.exe`  (die App)
- `dist\ProductImageBatch.zip`  (fertig gepackt zum Mitnehmen)

**2. Auf Google Drive laden:** die Datei `dist\ProductImageBatch.zip` in Google
Drive hochladen (oder auf einen USB-Stick kopieren).

**3. Auf dem Arbeitsrechner:** ZIP herunterladen → Rechtsklick → **Alle
extrahieren** → in den entpackten Ordner gehen → **`ProductImageBatch.exe`**
doppelklicken. Fertig, kein Python nötig.

**4. Erster Start dort:** oben **Settings** → API-Keys einfügen → **Save**, dann
Referenzbild reinziehen und **Start this tab**.

> Hinweise:
> - Die API-Keys landen pro Nutzer in `%APPDATA%\ProductImageBatch\.env` — sie
>   sind **nicht** in der ZIP enthalten, du gibst sie am Zielrechner neu ein.
> - Manche Firmen-Rechner blockieren unbekannte `.exe` (SmartScreen/Antivirus).
>   Dann ggf. „Weitere Informationen → Trotzdem ausführen", oder mit der IT klären.
> - Internet-Zugang wird zur Laufzeit gebraucht (die Bild-APIs liegen in der Cloud).

---

## Weg B — Quellcode (wenn der Zielrechner Python hat)

Auf dem Zielrechner Python 3.11+ installiert? Dann reicht der Quellcode.

**Variante B1 — direkt herunterladen:**

```powershell
cd $HOME\Documents
git clone https://github.com/reioken/image-gen.git
cd image-gen
git checkout claude/product-image-generation-desktop-b1yys4
python -m pip install -r requirements.txt
python -m product_image_batch.gui.app
```

**Variante B2 — Ordner mitnehmen (ohne git):** den Projektordner (ohne `.venv`,
`outputs`, `__pycache__`) zippen, auf Google Drive laden, am Zielrechner
entpacken, dann **`start_app.bat`** doppelklicken (installiert Abhängigkeiten
automatisch und startet die App).

---

## Was liegt wo?

| Datei / Ordner | Zweck |
|---|---|
| `build_exe.bat` | Baut die portable `.exe` + `dist\ProductImageBatch.zip`. |
| `start_app.bat` | Doppelklick-Start der Quellcode-Version (braucht Python). |
| `dist\ProductImageBatch.zip` | Das mitnehmbare Paket (entsteht beim Build). |
| `%APPDATA%\ProductImageBatch\.env` | Deine API-Keys (pro Nutzer/Rechner, nie im Paket). |
