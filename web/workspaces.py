"""Server-side saved projects ("workspaces").

Lets an authenticated client save a whole setup — master prompt, agents and the
reference/mask images — under a name and load it back from any device. Stored as
a small JSON file plus the image files on disk under one directory per project.

Durability note: on ephemeral hosting (e.g. a free-tier container) this disk is
lost on restart just like ``outputs/``. Attach a persistent disk for permanent,
cross-device projects.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from product_image_batch.core.metadata import utc_now_iso
from product_image_batch.core.utils.files import sanitize_component


class WorkspaceStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, wid: str) -> Path:
        # wid is generated/sanitized here, but guard against traversal anyway.
        return self.root / Path(wid).name

    def list(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not self.root.exists():
            return out
        for d in self.root.iterdir():
            f = d / "workspace.json"
            if not f.is_file():
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            out.append({
                "id": data.get("id", d.name),
                "name": data.get("name", d.name),
                "updated_at": data.get("updated_at", ""),
                "agents": len(data.get("agents", [])),
                "refs": len(data.get("refs", [])),
            })
        # newest first
        out.sort(key=lambda w: w.get("updated_at", ""), reverse=True)
        return out

    def get(self, wid: str) -> dict[str, Any] | None:
        f = self._dir(wid) / "workspace.json"
        if not f.is_file():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def save(
        self,
        *,
        name: str,
        master_prompt: str,
        agents: list[dict[str, Any]],
        ref_files: list[tuple[str, bytes]],
        mask_file: tuple[str, bytes] | None,
        wid: str | None = None,
    ) -> dict[str, Any]:
        wid = (Path(wid).name if wid else None) or f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
        d = self._dir(wid)
        refs_dir = d / "refs"
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        refs_dir.mkdir(parents=True, exist_ok=True)

        ref_names: list[str] = []
        for i, (fname, data) in enumerate(ref_files):
            safe = f"{i:02d}_{sanitize_component(Path(fname).stem)}{Path(fname).suffix.lower() or '.png'}"
            (refs_dir / safe).write_bytes(data)
            ref_names.append(safe)

        mask_name: str | None = None
        if mask_file is not None:
            fname, data = mask_file
            mask_name = f"mask{Path(fname).suffix.lower() or '.png'}"
            (d / mask_name).write_bytes(data)

        record = {
            "id": wid,
            "name": name or "Projekt",
            "updated_at": utc_now_iso(),
            "master_prompt": master_prompt or "",
            "agents": agents or [],
            "refs": ref_names,
            "mask": mask_name,
        }
        (d / "workspace.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    def ref_path(self, wid: str, name: str) -> Path | None:
        p = self._dir(wid) / "refs" / Path(name).name
        return p if p.is_file() else None

    def mask_path(self, wid: str) -> Path | None:
        data = self.get(wid)
        if not data or not data.get("mask"):
            return None
        p = self._dir(wid) / Path(str(data["mask"])).name
        return p if p.is_file() else None

    def delete(self, wid: str) -> bool:
        d = self._dir(wid)
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            return True
        return False
