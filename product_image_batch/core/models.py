"""Data models shared across the engine.

Runtime models (tasks, prepared assets, provider jobs/results) are lightweight
dataclasses — they carry ``Path`` objects and live only in memory.
``MetadataRecord`` is a pydantic model because it is serialized to JSONL/CSV and
benefits from validation.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class GenerationTask:
    """A single unit of work: one prompt + one provider/model + reference set.

    A GUI "agent row" with ``images=N`` expands into N of these tasks (index
    0..N-1), all sharing the same prompt/provider/model but distinct output
    indices and (optionally) seeds.
    """

    task_id: str
    prompt_id: str
    prompt_text: str
    provider: str
    model: str
    reference_images: list[Path] = field(default_factory=list)
    mask_path: Path | None = None
    negative_prompt: str | None = None
    seed: int | None = None
    aspect_ratio: str | None = None
    size: str = "1024x1024"
    quality: str = "high"
    output_format: str = "png"
    image_index: int = 1
    provider_params: dict[str, Any] = field(default_factory=dict)

    # Set by the caller (GUI) so the scheduler can route progress back to the
    # right tab. Empty string for CLI runs.
    tab_id: str = ""

    def output_basename(self, timestamp_utc: str) -> str:
        """Build the sanitized output file stem (extension added by the writer)."""
        from .utils.files import sanitize_component

        parts = [
            sanitize_component(self.provider),
            sanitize_component(self.model),
            sanitize_component(self.prompt_id),
            timestamp_utc,
            f"{self.image_index:04d}",
        ]
        return "_".join(parts)


@dataclass
class PreparedAssets:
    """Reference images + mask, pre-processed once and reused across tasks."""

    local_paths: list[Path] = field(default_factory=list)
    base64_data_urls: list[str] = field(default_factory=list)
    public_or_uploaded_urls: list[str] = field(default_factory=list)
    provider_file_ids: list[str] = field(default_factory=list)
    mask_local_path: Path | None = None
    mask_base64_data_url: str | None = None


@dataclass
class CostEstimate:
    """Estimated cost for a task. ``known=False`` means pricing is uncertain."""

    amount_usd: float
    known: bool = True
    note: str = ""


@dataclass
class ProviderJob:
    """Handle to an in-flight provider job (sync or async/polled)."""

    provider: str
    model: str
    job_id: str | None = None
    poll_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    # For providers that return the result immediately on submit.
    inline_result: "ProviderResult | None" = None


@dataclass
class RemoteImage:
    """One image the provider produced, described by how to fetch it."""

    url: str | None = None
    b64_data: str | None = None
    content_type: str = "image/png"
    suggested_ext: str = "png"


@dataclass
class ProviderResult:
    """Completed provider job, ready to download."""

    provider: str
    model: str
    images: list[RemoteImage] = field(default_factory=list)
    provider_job_id: str | None = None
    actual_cost_usd: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SavedImage:
    """A downloaded output image on disk."""

    path: Path
    provider: str
    model: str
    prompt_id: str
    task_id: str
    index: int
    tab_id: str = ""


class MetadataRecord(BaseModel):
    """One line in metadata.jsonl (serialized/validated)."""

    task_id: str
    status: str
    provider: str
    model: str
    prompt_id: str
    prompt_text: str
    rewritten_prompt: str | None = None
    negative_prompt: str | None = None
    reference_images: list[str] = Field(default_factory=list)
    mask: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_files: list[str] = Field(default_factory=list)
    provider_job_id: str | None = None
    latency_seconds: float | None = None
    estimated_cost_usd: float | None = None
    actual_cost_usd: float | None = None
    tab_id: str = ""
    created_at_utc: str = ""
    error: str | None = None


class ErrorRecord(BaseModel):
    """One line in errors.jsonl."""

    task_id: str
    provider: str
    model: str
    prompt_id: str
    error_type: str
    http_status: int | None = None
    message: str
    retryable: bool = False
    attempts: int = 1
    tab_id: str = ""
    created_at_utc: str = ""
