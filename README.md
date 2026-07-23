# Product Image Batch

Generate **many product-image variations in parallel** from one or more product
**reference images**, sending each job to as many programmatically-accessible
image APIs as you have keys for — all landing in one clean output folder.

The core workflow is **not** "one prompt to many models". It is:

> **same product reference image(s) + many different prompts + several
> providers/models → parallel product-image variants.**

It ships as both a **command-line tool** and a **PySide6 desktop GUI** with tabs,
drag-&-drop reference images, and per-tab "agents", packable to a standalone
**Windows `.exe`**.

> Kurzfassung (DE): Lokale App, die aus Produkt-Referenzbildern und vielen
> Prompts parallel Produktbild-Varianten über mehrere Bild-APIs erzeugt. CLI +
> Desktop-GUI mit Tabs; als eigenständige Windows-`.exe` baubar. Siehe
> [GUI-Bedienung](#desktop-gui) und [.exe bauen](#building-the-windows-exe).

---

## Table of contents

- [Architecture](#architecture)
- [Setup](#setup)
- [API keys](#api-keys)
- [Supported providers](#supported-providers)
- [Command-line usage](#command-line-usage)
  - [Example: product photo + prompt variants](#example-product-photo--prompt-variants)
  - [Example: prompt rewriting from a brief](#example-prompt-rewriting-from-a-brief)
  - [Example: dry-run and budget cap](#example-dry-run-and-budget-cap)
- [Desktop GUI](#desktop-gui)
- [Building the Windows .exe](#building-the-windows-exe)
- [Output layout](#output-layout)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Testing](#testing)

---

## Architecture

Three layers with a strict, one-way dependency direction:

```
product_image_batch/
  core/     the engine — async (httpx + asyncio), provider adapters, scheduler.
            NO GUI imports. Fully usable headless.
  cli.py    optional command-line front-end over the engine.
  gui/      PySide6 desktop front-end over the engine.
```

The GUI and CLI are thin clients; **all generation logic lives in `core/`**. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the detailed design (global
scheduler, async bridge, provider adapter pattern).

Key design points:

- **Async-first, but controlled.** One shared `httpx.AsyncClient` with connection
  pooling; `asyncio.Semaphore` per provider plus a global cap; a rate limiter per
  provider; retry with exponential backoff + jitter honoring `Retry-After`.
- **One global scheduler.** Even with many GUI tabs running at once, there is
  exactly **one** scheduler with **one semaphore set per provider**, so opening 4
  tabs does not quadruple your per-provider request rate.
- **Provider adapter pattern.** Each provider encapsulates auth, request format,
  asset-upload strategy, polling, download and error normalization behind a small
  interface.

---

## Setup

Requires **Python 3.11+**.

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # then edit .env with your keys
```

Or install the package with extras:

```bash
pip install -e ".[all]"              # engine + GUI + tests + build tools
pip install -e ".[gui]"             # engine + GUI only
```

---

## API keys

Never hard-code keys. Copy `.env.example` to `.env` and fill in only the
providers you use. The `.env` file is git-ignored.

When running the **packaged `.exe`**, the real `.env` lives **outside** the
executable at `%APPDATA%\ProductImageBatch\.env` and is created from the template
on first launch. Enter keys through the GUI **Settings** dialog — no command line
needed.

| Env var | Provider | Where to get it |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI GPT Image | platform.openai.com |
| `GOOGLE_API_KEY` | Google Gemini / Imagen | ai.google.dev (AI Studio) |
| `BFL_API_KEY` | Black Forest Labs (FLUX) | docs.bfl.ai |
| `STABILITY_API_KEY` | Stability AI | platform.stability.ai |
| `FAL_KEY` | fal.ai | fal.ai/dashboard |
| `REPLICATE_API_TOKEN` | Replicate | replicate.com/account |
| `IDEOGRAM_API_KEY` | Ideogram | developer.ideogram.ai |
| `RECRAFT_API_TOKEN` | Recraft | recraft.ai |
| `LEONARDO_API_KEY` | Leonardo.Ai | leonardo.ai |
| `FREEPIK_API_KEY` | Freepik / Magnific (optional) | freepik.com |

Providers **without a key are skipped automatically** and logged as
`skipped_missing_key`.

---

## Supported providers

| Provider | Reference images | Masks | Notes |
|---|:---:|:---:|---|
| **OpenAI GPT Image** | ✅ up to 16 | ✅ | Images Edit endpoint; `gpt-image-1` / `gpt-image-1.5`. Default **on**. |
| **Google Gemini / Imagen** | ✅ multi | — | Native image editing, multi-image fusion for product consistency. |
| **Black Forest Labs (FLUX.2 / Kontext)** | ✅ up to 8 | — | Multi-reference editing. |
| **Stability AI** | ✅ | ✅ | v2beta image-to-image (`strength`); stay under 150 req/10s. |
| **fal.ai** | ✅ | — | Includes `fal-ai/image-apps-v2/product-photography`. Queue API. |
| **Replicate** | ✅ | — | Meta-provider (FLUX, IP-Adapter, ControlNet…). Model list is config-driven. |
| **Ideogram** | ✅ | ✅ | Remix / character-reference; default ≤ 8 inflight (limit is 10). |
| **Recraft** | ✅ | ✅ | Image-to-image, custom styles. |
| **Leonardo.Ai** | ✅ | — | Upload → `init_image_id` → generation. |
| **Freepik / Magnific** | ⚠️ skeleton | — | Off by default; needs your account docs/schema. |
| **Midjourney** | ❌ | — | **Not implemented** — no official public API (see below). |

**Midjourney is default off**: as of current research there is no official public
Midjourney API. Automating it needs unofficial third-party bridges that carry ToS
and reliability risk, so this project intentionally leaves it disabled.

`mock` is a built-in, network-free provider used for `--dry-run` demos and tests.

---

## Command-line usage

```bash
python -m product_image_batch \
  --reference ./input/product_front.png \
  --reference ./input/product_side.png \
  --prompts ./prompts/product_shots.txt \
  --providers openai,fal,replicate \
  --images-per-prompt 1 \
  --out ./outputs/run_2026_07_23 \
  --max-total-cost 25.00 \
  --rewrite-prompts
```

Jobs are the cartesian product of `enabled provider/models × prompt variants ×
images-per-prompt`. The **same reference images** ride along with every job; only
the prompt differs.

### Example: product photo + prompt variants

`prompts/product_shots.txt` (one prompt per line; `#` lines are comments):

```text
# one line = one prompt
Premium studio product photo on warm beige background, soft shadows, hero angle, preserve exact product label and proportions.
Outdoor lifestyle product shot on wet stone after rain, cinematic dusk lighting, preserve the exact bottle design.
E-commerce white background packshot, 85mm lens, high-end catalog lighting, preserve product geometry and logo.
```

```bash
python -m product_image_batch \
  --reference ./product.png \
  --prompts ./prompts/product_shots.txt \
  --providers openai \
  --rewrite-prompts \
  --out ./outputs/hero_batch
```

### Example: prompt rewriting from a brief

Turn a base brief into N provider-specific prompts (offline, deterministic — no
LLM key required; each prompt gets strong product-preservation instructions):

```bash
python -m product_image_batch \
  --reference ./product.png \
  --brief ./briefing.md --generate-prompts 30 \
  --providers openai,fal \
  --out ./outputs/campaign
```

### Example: dry-run and budget cap

`--dry-run` makes **no API calls**; it prints the plan, per-provider task counts
and an estimated cost. A budget cap stops new jobs before they exceed the cap.

```bash
python -m product_image_batch \
  --reference ./product.png --prompts ./prompts.txt \
  --providers openai,fal,replicate \
  --max-total-cost 10.00 --dry-run
```

Full flag list: `python -m product_image_batch --help`.

---

## Desktop GUI

```bash
python -m product_image_batch.gui.app      # from source (needs PySide6)
```

Layout:

```
[+ New tab] [Settings] [Start all tabs] [Stop all]           Budget: $--
[ Run A ][ Run B ][ Run C ][+]
  Reference images (drag & drop or browse)   [Mask: optional]
  Agents (each row runs in parallel):
    Agent 1  Provider:[openai ▾] Model:[gpt-image-1.5 ▾]  Images:[2]
    Prompt 1: [ Studio shot on beige background… ]         Status: running (1/2)
    Agent 2  Provider:[fal ▾]    Model:[product-photography ▾]  Images:[3]
    Prompt 2: [ Outdoor lifestyle shot at dusk… ]          Status: done (3/3)
    [+ Add agent]
  [▶ Start this tab] [■ Stop] [⧉ Duplicate tab] [📁 Open folder]
  Results (live thumbnails): 🖼️ 🖼️ 🖼️ …
```

**Tab concept**

- Each **tab** is an independent run configuration: its own name, reference
  images/mask and list of **agent rows**.
- An **agent row** = one prompt + its provider + model + image count (+ size,
  seed, strength). All agent rows in a tab run **at the same time**.
- **⧉ Duplicate tab** copies the whole configuration into a new tab you can run
  in parallel with the original — this is how you "run the same config again" or
  fan out variations without touching the original.
- **▶ Start this tab** can be clicked repeatedly; each run gets its own
  timestamped output subfolder, so previous results are never overwritten.
- **Start all tabs** launches every idle tab at once.

**Never freezes.** A dedicated background thread runs the asyncio engine; results
come back to the UI thread via Qt signals, so the window stays responsive while
generating. Thumbnails appear the moment each image finishes; double-click one to
open it, or **📁 Open folder** to open the run directory.

**Configurable concurrency** (Settings dialog, persisted to
`settings.json`): a global cap across all providers, a per-provider concurrency
value each, max concurrent tabs, auto-retry + max retries, and total / per-tab
budget caps. Changes apply to newly started tasks immediately.

---

## Building the Windows .exe

> PyInstaller cannot cross-compile: a Windows `.exe` must be built **on Windows**.

On a Windows PC, from the project root:

```bat
build_exe.bat
```

This creates a venv, installs dependencies + PyInstaller, and builds using
`build\product_image_batch.spec`. Result:

```
dist\ProductImageBatch\ProductImageBatch.exe
```

Share the whole `dist\ProductImageBatch\` folder (or zip it).

- **One-dir, not one-file** (deliberate): one-file re-extracts to a temp dir on
  every launch and starts slower; one-dir starts fastest, which is what we want.
- **No keys are baked in.** Only the config templates and `.env.example` ship in
  the build; real keys are read at runtime from
  `%APPDATA%\ProductImageBatch\.env` (created from the template on first launch,
  edited via the Settings dialog).
- **No console window** (`console=False`); logs still go to
  `%APPDATA%\ProductImageBatch\logs\app.log` so failures remain diagnosable.

---

## Output layout

```
outputs/
  2026-07-23_2214_product_batch/
    run_config.yaml            # exact run configuration
    prompts.resolved.json      # rewritten, provider-specific prompts
    metadata.jsonl             # one line per output/error (incremental)
    metadata.csv               # generated from the JSONL at the end
    errors.jsonl               # normalized error records
    images/
      openai_gpt-image-1.5_p001_20260723T221501Z_0001.png
      fal_product-photography_p002_20260723T221508Z_0001.webp
    refs/                      # copies of the reference images used
    masks/                     # copy of the mask (if any)
```

File names are `{provider}_{model}_{prompt_id}_{timestamp_utc}_{index}.{ext}`,
sanitized to `[a-zA-Z0-9._-]` (so `fal-ai/…` and `openai:…` become `_`), with
collision-avoiding suffixes.

Each `metadata.jsonl` line records status, provider/model, prompts, parameters,
output files, latency, estimated/actual cost and any error — so a crash mid-run
still leaves a valid, complete-up-to-that-point ledger.

---

## Configuration

- `config/providers.yaml` — engine defaults: per-provider `enabled`,
  `max_concurrent`, rate limits and model lists. Conservative, rate-limit-safe
  defaults you can raise once you know your account tier.
- `config/prompt_rewrite.yaml` — preservation instructions, provider hints and
  the default negative prompt used by the rewriter.
- `config/settings.default.json` — template for the per-user `settings.json`.

Override from the CLI with `--config`, `--providers`, `--models`; or from the GUI
Settings dialog.

---

## Troubleshooting

| Symptom | Likely cause & fix |
|---|---|
| `401` / `ProviderAuthError` | Missing/invalid key. Check `.env` (or Settings). The provider is disabled for the rest of the run after an auth error. |
| `403` | Key lacks access to that model/endpoint, or account not enabled for it. |
| `422` / `ProviderInvalidInputError` | Bad params or unsupported input (e.g. wrong size, oversize reference). Not retried. |
| `429` / `ProviderRateLimitError` | Rate limited. The tool waits (honoring `Retry-After`) and retries. Lower that provider's concurrency in Settings if persistent. |
| Timeouts | Network/slow job. Retried with backoff; raise timeouts or lower concurrency. |
| Content-policy refusal | `ProviderContentPolicyError` — never retried (same refusal would recur). Adjust the prompt. |
| Provider skipped | No key (`skipped_missing_key`) or it doesn't support reference images. |
| GUI won't start | `pip install PySide6` (or `pip install .[gui]`). |
| `.exe` won't build on Linux/Mac | Expected — build on Windows (no cross-compile). |

Logs: console (CLI) and `%APPDATA%\ProductImageBatch\logs\app.log` (GUI/.exe).

---

## Testing

```bash
pip install -e ".[dev]"
pytest
```

The suite (51 tests) makes **no real API calls** — provider HTTP is mocked with
`respx` and an in-memory `mock`/`probe` provider exercises the full pipeline,
including the global-scheduler concurrency guarantees and per-tab cancellation.
