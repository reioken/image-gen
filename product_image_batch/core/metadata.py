"""Incremental metadata + error logging (JSONL, then CSV at the end).

Records are written one line at a time as each task finishes so a crash mid-run
still leaves a valid, complete-up-to-that-point ``metadata.jsonl``. A ``.csv``
is produced from the JSONL at the end of a run (pandas if available, otherwise
the stdlib ``csv`` module).
"""

from __future__ import annotations

import asyncio
import csv
import datetime as _dt
import json
from pathlib import Path

from .models import ErrorRecord, MetadataRecord


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_timestamp_compact() -> str:
    """Compact UTC stamp for filenames, e.g. ``20260723T221501Z``."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class MetadataWriter:
    """Thread/async-safe incremental writer for a single run directory."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.out_dir / "metadata.jsonl"
        self.errors_path = self.out_dir / "errors.jsonl"
        self.csv_path = self.out_dir / "metadata.csv"
        self._lock = asyncio.Lock()
        self._records: list[MetadataRecord] = []
        self._error_count = 0
        self._success_count = 0

    @property
    def success_count(self) -> int:
        return self._success_count

    @property
    def error_count(self) -> int:
        return self._error_count

    async def write_record(self, record: MetadataRecord) -> None:
        if not record.created_at_utc:
            record.created_at_utc = utc_now_iso()
        line = record.model_dump_json()
        async with self._lock:
            self._records.append(record)
            if record.status == "success":
                self._success_count += 1
            with self.metadata_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    async def write_error(self, error: ErrorRecord) -> None:
        if not error.created_at_utc:
            error.created_at_utc = utc_now_iso()
        line = error.model_dump_json()
        async with self._lock:
            self._error_count += 1
            with self.errors_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    # Synchronous variants for the CLI / tests without a running loop.
    def write_record_sync(self, record: MetadataRecord) -> None:
        if not record.created_at_utc:
            record.created_at_utc = utc_now_iso()
        self._records.append(record)
        if record.status == "success":
            self._success_count += 1
        with self.metadata_path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json() + "\n")

    def write_error_sync(self, error: ErrorRecord) -> None:
        if not error.created_at_utc:
            error.created_at_utc = utc_now_iso()
        self._error_count += 1
        with self.errors_path.open("a", encoding="utf-8") as fh:
            fh.write(error.model_dump_json() + "\n")

    def finalize_csv(self) -> Path | None:
        """Write metadata.csv from the collected records. Returns the path."""
        records = self._records
        if not records:
            # Still emit an empty CSV with headers for consistency.
            records = []
        rows = [self._flatten(r) for r in records]
        fieldnames = list(MetadataRecord.model_fields.keys())
        try:
            import pandas as pd  # type: ignore

            pd.DataFrame(rows, columns=fieldnames).to_csv(self.csv_path, index=False)
        except Exception:  # noqa: BLE001 — pandas optional; fall back to stdlib
            with self.csv_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
        return self.csv_path

    @staticmethod
    def _flatten(record: MetadataRecord) -> dict:
        data = record.model_dump()
        # Collapse nested/list fields to JSON strings so CSV cells stay scalar.
        for key in ("reference_images", "output_files", "parameters"):
            if key in data and not isinstance(data[key], str):
                data[key] = json.dumps(data[key])
        return data


def read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file back into a list of dicts (skips blank/broken lines)."""
    out: list[dict] = []
    if not Path(path).exists():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
