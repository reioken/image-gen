"""FastAPI backend for the browser version.

Endpoints (all under /api, all require a bearer token except /login):

* POST /api/login              {password}            -> {token}
* GET  /api/config                                    -> providers + default master prompt
* POST /api/run                (multipart)            -> {run_id, total}
* GET  /api/run/{id}/events    (SSE, ?token=)         -> progress stream
* POST /api/run/{id}/cancel                           -> {cancelled}
* GET  /api/run/{id}/image/{name} (?token=)           -> the generated image

The static browser UI is served from web/static/.

Security: the API password comes from the WEB_APP_PASSWORD env var. If it is not
set the server refuses to start (so it is never accidentally open). Tokens are
short-lived HMAC-signed strings; keys never leave the server.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.datastructures import UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from product_image_batch.core.prompting import DEFAULT_MASTER_PROMPT
from product_image_batch.core.utils import images as imgutil
from product_image_batch.core.utils.logging import get_logger, setup_logging
from .runmanager import RunManager
from .workspaces import WorkspaceStore

log = get_logger("web.server")

STATIC_DIR = Path(__file__).resolve().parent / "static"
TOKEN_TTL_SECONDS = 12 * 3600
# How often to emit an SSE keepalive comment when no real event is pending.
# Must stay well under typical proxy idle timeouts (Cloudflare ~100s, Render ~).
HEARTBEAT_SECONDS = 15

# --- auth helpers ----------------------------------------------------------

def _password() -> str:
    return os.environ.get("WEB_APP_PASSWORD", "").strip()


def _secret() -> bytes:
    # A stable per-deployment secret. If WEB_APP_SECRET is unset, derive one from
    # the password so tokens survive within a process but change if the password
    # changes. Set WEB_APP_SECRET in production for multi-instance deployments.
    s = os.environ.get("WEB_APP_SECRET", "").strip()
    if s:
        return s.encode("utf-8")
    return hashlib.sha256(("pib-secret::" + _password()).encode("utf-8")).digest()


def create_token() -> str:
    exp = str(int(time.time()) + TOKEN_TTL_SECONDS)
    sig = hmac.new(_secret(), exp.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def verify_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp, sig = token.rsplit(".", 1)
    expected = hmac.new(_secret(), exp.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        return int(exp) >= int(time.time())
    except ValueError:
        return False


def _token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # EventSource / <img> cannot set headers -> allow ?token= for those.
    return request.query_params.get("token")


async def require_auth(request: Request) -> None:
    if not verify_token(_token_from_request(request)):
        raise HTTPException(status_code=401, detail="unauthorized")


# --- app -------------------------------------------------------------------

def create_app() -> FastAPI:
    setup_logging(verbose=False, to_file=True)
    app = FastAPI(title="Product Image Batch — Web")
    manager = RunManager()
    ws_root = Path(os.environ.get("WEB_WORKSPACES_DIR", "").strip() or (Path.cwd() / "workspaces"))
    workspaces = WorkspaceStore(ws_root)

    origins = [o.strip() for o in os.environ.get("WEB_CORS_ORIGINS", "*").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _startup() -> None:
        if not _password():
            raise RuntimeError(
                "WEB_APP_PASSWORD is not set. Refusing to start an unprotected server. "
                "Set WEB_APP_PASSWORD (and ideally WEB_APP_SECRET) in the environment."
            )
        await manager.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await manager.close()

    # --- auth ---
    @app.post("/api/login")
    async def login(payload: dict) -> JSONResponse:
        pw = (payload or {}).get("password", "")
        # constant-time compare
        if not _password() or not hmac.compare_digest(str(pw), _password()):
            raise HTTPException(status_code=401, detail="wrong password")
        return JSONResponse({"token": create_token(), "expires_in": TOKEN_TTL_SECONDS})

    # --- config ---
    @app.get("/api/config")
    async def config(_: None = Depends(require_auth)) -> dict:
        return {
            "providers": manager.providers_info(),
            "default_master_prompt": DEFAULT_MASTER_PROMPT,
            "budget": manager.budget.summary(),
        }

    # --- start a run ---
    @app.post("/api/run")
    async def start_run(
        request: Request,
        _: None = Depends(require_auth),
    ) -> dict:
        form = await request.form()
        try:
            cfg = json.loads(form.get("config") or "{}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid config json")

        upload_dir = Path(tempfile.mkdtemp(prefix="pib_upload_"))
        ref_paths = await _save_uploads(form.getlist("references"), upload_dir, "ref")
        mask_files = form.getlist("mask")
        mask_path = None
        if mask_files:
            saved = await _save_uploads(mask_files, upload_dir, "mask")
            mask_path = saved[0] if saved else None

        if not ref_paths:
            raise HTTPException(status_code=400, detail="at least one reference image is required")

        try:
            state = await manager.start_run(
                name=cfg.get("name", "web-run"),
                master_prompt=cfg.get("master_prompt", ""),
                agents=cfg.get("agents", []),
                reference_paths=ref_paths,
                mask_path=mask_path,
            )
        except imgutil.ImageValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"run_id": state.run_id, "total": state.total}

    # --- SSE progress ---
    @app.get("/api/run/{run_id}/events")
    async def events(run_id: str, request: Request) -> StreamingResponse:
        if not verify_token(_token_from_request(request)):
            raise HTTPException(status_code=401, detail="unauthorized")
        state = manager.get_run(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail="unknown run")

        async def gen():
            yield _sse({"type": "hello", "run_id": run_id, "total": state.total})
            # Heartbeat: image generation can take a long time, during which no
            # progress event is produced. Without periodic bytes on the wire,
            # proxies/load balancers (Render, Cloudflare, …) close the idle
            # connection and the browser reports "connection lost". Send an SSE
            # comment line every few seconds so the stream never goes silent.
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(state.queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield _sse(event)
                if event.get("type") == "done":
                    break

        return StreamingResponse(gen(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    @app.post("/api/run/{run_id}/cancel")
    async def cancel(run_id: str, _: None = Depends(require_auth)) -> dict:
        return {"cancelled": manager.cancel_run(run_id)}

    # --- serve a generated image (full, or a lightweight thumbnail) ---
    @app.get("/api/run/{run_id}/image/{name}")
    async def image(run_id: str, name: str, request: Request, thumb: int = 0) -> FileResponse:
        if not verify_token(_token_from_request(request)):
            raise HTTPException(status_code=401, detail="unauthorized")
        state = manager.get_run(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail="unknown run")
        # Prevent path traversal: only a bare filename inside images/.
        safe = Path(name).name
        path = state.out_dir / "images" / safe
        if not path.exists():
            raise HTTPException(status_code=404, detail="image not found")
        headers = {"Cache-Control": "private, max-age=86400"}
        if thumb:
            # The results grid only needs small previews; serving full multi-MB
            # images there is slow on mobile. Generate a cached JPEG thumbnail
            # once (off the event loop) and reuse it. The lightbox still loads
            # the full-resolution original.
            tpath = state.out_dir / "thumbs" / (safe + ".jpg")
            if not tpath.exists():
                try:
                    await asyncio.to_thread(imgutil.make_thumbnail, path, tpath, 384)
                except Exception:  # noqa: BLE001 — fall back to the full image
                    return FileResponse(path, headers=headers)
            return FileResponse(tpath, headers=headers)
        return FileResponse(path, headers=headers)

    # --- download every image of a run as one ZIP ---
    @app.get("/api/run/{run_id}/download")
    async def download_zip(run_id: str, request: Request) -> FileResponse:
        if not verify_token(_token_from_request(request)):
            raise HTTPException(status_code=401, detail="unauthorized")
        state = manager.get_run(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail="unknown run")
        images_dir = state.out_dir / "images"
        all_files = sorted(p for p in images_dir.glob("*") if p.is_file()) if images_dir.exists() else []
        if not all_files:
            raise HTTPException(status_code=404, detail="no images yet")

        # Optional subset (e.g. only the favourites): ?files=name1,name2
        subset = request.query_params.get("files")
        if subset:
            wanted = {Path(n).name for n in subset.split(",") if n.strip()}
            sel = [p for p in all_files if p.name in wanted]
            if not sel:
                raise HTTPException(status_code=404, detail="none of the selected images exist")
            data = await asyncio.to_thread(_zip_bytes, sel)
            return Response(
                content=data, media_type="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="{run_id}-favoriten.zip"',
                    "Cache-Control": "no-store",
                },
            )

        zpath = state.out_dir / "all_images.zip"
        newest = max(p.stat().st_mtime for p in all_files)
        # Rebuild only when new images have arrived since the zip was built.
        if (not zpath.exists()) or zpath.stat().st_mtime < newest:
            await asyncio.to_thread(_build_zip, zpath, all_files)
        return FileResponse(
            zpath, media_type="application/zip", filename=f"{run_id}.zip",
            headers={"Cache-Control": "private, max-age=60"},
        )

    # --- saved projects / workspaces (cross-device) ---
    @app.get("/api/workspaces")
    async def ws_list(_: None = Depends(require_auth)) -> dict:
        return {"workspaces": workspaces.list()}

    @app.post("/api/workspaces")
    async def ws_save(request: Request, _: None = Depends(require_auth)) -> dict:
        form = await request.form()
        try:
            cfg = json.loads(form.get("config") or "{}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid config json")
        ref_files: list[tuple[str, bytes]] = []
        for f in form.getlist("references"):
            if isinstance(f, UploadFile):
                ref_files.append((f.filename or "ref.png", await f.read()))
        mask_file = None
        mfs = form.getlist("mask")
        if mfs and isinstance(mfs[0], UploadFile):
            mask_file = (mfs[0].filename or "mask.png", await mfs[0].read())
        rec = workspaces.save(
            name=cfg.get("name", "Projekt"),
            master_prompt=cfg.get("master_prompt", ""),
            agents=cfg.get("agents", []),
            ref_files=ref_files,
            mask_file=mask_file,
            wid=cfg.get("id"),
        )
        return {"id": rec["id"], "name": rec["name"], "updated_at": rec["updated_at"]}

    @app.get("/api/workspaces/{wid}")
    async def ws_get(wid: str, _: None = Depends(require_auth)) -> dict:
        data = workspaces.get(wid)
        if data is None:
            raise HTTPException(status_code=404, detail="unknown workspace")
        return data

    @app.get("/api/workspaces/{wid}/ref/{name}")
    async def ws_ref(wid: str, name: str, request: Request) -> FileResponse:
        if not verify_token(_token_from_request(request)):
            raise HTTPException(status_code=401, detail="unauthorized")
        p = workspaces.ref_path(wid, name)
        if p is None:
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(p, headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/workspaces/{wid}/mask")
    async def ws_mask(wid: str, request: Request) -> FileResponse:
        if not verify_token(_token_from_request(request)):
            raise HTTPException(status_code=401, detail="unauthorized")
        p = workspaces.mask_path(wid)
        if p is None:
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(p, headers={"Cache-Control": "private, max-age=3600"})

    @app.delete("/api/workspaces/{wid}")
    async def ws_del(wid: str, _: None = Depends(require_auth)) -> dict:
        return {"deleted": workspaces.delete(wid)}

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "auth_required": bool(_password())}

    # --- static UI (served last so /api wins) ---
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


async def _save_uploads(files: list, dest: Path, prefix: str) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for i, f in enumerate(files):
        if not isinstance(f, UploadFile):
            continue
        suffix = Path(f.filename or f"{prefix}{i}.png").suffix.lower() or ".png"
        if suffix not in imgutil.ACCEPTED_SUFFIXES and prefix == "ref":
            continue
        target = dest / f"{prefix}_{i:02d}_{Path(f.filename or 'file').stem}{suffix}"
        data = await f.read()
        target.write_bytes(data)
        out.append(target)
    return out


def _build_zip(zpath: Path, files: list[Path]) -> None:
    """Write ``files`` into a zip at ``zpath`` (run off the event loop)."""
    import zipfile

    tmp = zpath.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as zf:
        for p in files:
            zf.write(p, arcname=p.name)
    tmp.replace(zpath)  # atomic swap so a concurrent read never sees a half file


def _zip_bytes(files: list[Path]) -> bytes:
    """Build a zip of ``files`` in memory (used for small favourite subsets)."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for p in files:
            zf.write(p, arcname=p.name)
    return buf.getvalue()


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


# uvicorn entry point: `uvicorn web.server:app`
app = create_app()
