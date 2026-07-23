"""Server-side run manager: one shared scheduler, per-run SSE event queues.

Unlike the desktop GUI (which needs a background thread because Qt owns the main
loop), the web server already runs on an asyncio loop, so the ``GlobalScheduler``
runs directly on it. Each browser "run" gets an ``asyncio.Queue`` of progress
events that the SSE endpoint streams to the client. Tasks carry ``tab_id =
run_id`` so the single scheduler's callbacks route events to the right queue.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from product_image_batch.core.budget import BudgetManager
from product_image_batch.core.config import AppConfig, load_config, load_settings
from product_image_batch.core.metadata import MetadataWriter, utc_timestamp_compact
from product_image_batch.core.models import GenerationTask
from product_image_batch.core.prompting import PromptRewriter, PromptVariant, load_rewrite_config
from product_image_batch.core.scheduler import (
    GlobalScheduler,
    SchedulerCallbacks,
    build_generation_tasks,
)
from product_image_batch.core.utils.files import sanitize_component
from product_image_batch.core.utils.logging import get_logger

log = get_logger("web.runmanager")


@dataclass
class RunState:
    run_id: str
    out_dir: Path
    queue: "asyncio.Queue[dict[str, Any]]" = field(default_factory=asyncio.Queue)
    done: bool = False
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


class RunManager:
    """Owns the shared scheduler and all active runs."""

    def __init__(self, output_root: Path | None = None) -> None:
        self.config: AppConfig = load_config()
        self.config.apply_settings(load_settings())
        self.rewriter = PromptRewriter(load_rewrite_config())
        self.output_root = output_root or (Path.cwd() / "outputs")
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.budget = BudgetManager(
            max_total_cost=_env_float("WEB_BUDGET_CAP_USD"),
        )
        self._runs: dict[str, RunState] = {}
        self._scheduler: GlobalScheduler | None = None

    async def start(self) -> None:
        if self._scheduler is None:
            callbacks = SchedulerCallbacks(
                on_task_started=self._on_started,
                on_task_succeeded=self._on_succeeded,
                on_task_failed=self._on_failed,
                on_task_skipped=self._on_skipped,
                on_progress=lambda msg: None,
            )
            self._scheduler = GlobalScheduler(
                self.config, budget=self.budget, env=dict(os.environ), callbacks=callbacks
            )
            await self._scheduler.start()

    async def close(self) -> None:
        if self._scheduler is not None:
            await self._scheduler.close()
            self._scheduler = None

    # --- config for the UI -------------------------------------------------
    def providers_info(self) -> list[dict[str, Any]]:
        from product_image_batch.core.config import PROVIDER_ENV_KEYS

        out = []
        for name, prov in self.config.providers.items():
            key_var = PROVIDER_ENV_KEYS.get(name, "")
            has_key = name == "mock" or bool(os.environ.get(key_var, "").strip())
            out.append({
                "name": name,
                "models": prov.models or [prov.resolve_model(None)],
                "default_model": prov.resolve_model(None),
                "has_key": has_key,
                "supports_masks": prov.supports_masks,
                "supports_reference_images": prov.supports_reference_images,
            })
        return out

    # --- run lifecycle -----------------------------------------------------
    def _new_run_id(self, name: str) -> str:
        stamp = utc_timestamp_compact()
        return f"{stamp}_{sanitize_component(name) or 'run'}"

    async def start_run(
        self,
        *,
        name: str,
        master_prompt: str,
        agents: list[dict[str, Any]],
        reference_paths: list[Path],
        mask_path: Path | None,
    ) -> RunState:
        """Build tasks from the posted config and launch them on the scheduler."""
        await self.start()
        assert self._scheduler is not None

        run_id = self._new_run_id(name)
        out_dir = self.output_root / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # Copy refs/mask into the run dir (so metadata points next to outputs).
        from product_image_batch.core.assets import copy_into_run, validate_assets

        validate_assets(reference_paths, mask_path)
        copied_refs, copied_mask = copy_into_run(reference_paths, mask_path, out_dir)

        tasks: list[GenerationTask] = []
        for i, agent in enumerate(agents, start=1):
            prompt_text = (agent.get("prompt") or "").strip()
            if not prompt_text:
                continue
            provider = agent.get("provider", "openai")
            model = agent.get("model") or None
            images = int(agent.get("images", 1))
            size = agent.get("size") or "1024x1024"
            seed = agent.get("seed")
            seed = int(seed) if (seed not in (None, "", "random")) else None
            prompt_id = f"a{i:02d}"

            variant = PromptVariant(prompt_id=prompt_id, base_intent=f"agent{i}", text=prompt_text)
            variant = self.rewriter.rewrite_variant(
                variant, [provider], with_mask=copied_mask is not None,
                master_prompt=master_prompt,
            )
            agent_tasks = build_generation_tasks(
                prompts=[variant],
                provider_models=[(provider, model)],
                reference_images=copied_refs,
                mask=copied_mask,
                images_per_prompt=images,
                size=size,
                seed=seed,
                tab_id=run_id,
            )
            params = {}
            if agent.get("strength") not in (None, ""):
                try:
                    params["strength"] = float(agent["strength"])
                except (ValueError, TypeError):
                    pass
            for t in agent_tasks:
                t.provider_params.update(params)
            tasks.extend(agent_tasks)

        state = RunState(run_id=run_id, out_dir=out_dir, total=len(tasks))
        self._runs[run_id] = state

        if not tasks:
            state.done = True
            await state.queue.put({"type": "error", "message": "No agents with a prompt."})
            await state.queue.put({"type": "done", "succeeded": 0, "failed": 0, "skipped": 0})
            return state

        writer = MetadataWriter(out_dir)
        asyncio.ensure_future(self._run(state, tasks, writer))
        return state

    async def _run(self, state: RunState, tasks, writer: MetadataWriter) -> None:
        assert self._scheduler is not None
        try:
            result = await self._scheduler.run_batch(
                state.run_id, tasks, state.out_dir, metadata_writer=writer
            )
            state.succeeded, state.failed, state.skipped = (
                result.succeeded, result.failed, result.skipped
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("run %s failed", state.run_id)
            await state.queue.put({"type": "error", "message": str(exc)})
        finally:
            try:
                writer.finalize_csv()
            except Exception:  # noqa: BLE001
                pass
            state.done = True
            await state.queue.put({
                "type": "done",
                "succeeded": state.succeeded,
                "failed": state.failed,
                "skipped": state.skipped,
                "budget": self.budget.summary(),
            })

    def get_run(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)

    def cancel_run(self, run_id: str) -> bool:
        if self._scheduler is None:
            return False
        n = self._scheduler.cancel_tab(run_id)
        return n > 0

    # --- scheduler callbacks (route to the run's queue) --------------------
    def _put(self, run_id: str, event: dict[str, Any]) -> None:
        state = self._runs.get(run_id)
        if state is not None:
            try:
                state.queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover — unbounded queue
                pass

    def _on_started(self, task) -> None:
        self._put(task.tab_id, {"type": "started", "prompt_id": task.prompt_id})

    def _on_succeeded(self, task, saved, record) -> None:
        images = [
            {"prompt_id": task.prompt_id, "file": Path(s.path).name, "run_id": task.tab_id}
            for s in saved
        ]
        self._put(task.tab_id, {
            "type": "image",
            "prompt_id": task.prompt_id,
            "provider": task.provider,
            "model": task.model,
            "images": images,
            "budget": self.budget.summary(),
        })

    def _on_failed(self, task, err) -> None:
        self._put(task.tab_id, {
            "type": "failed", "prompt_id": task.prompt_id,
            "error": err.error_type, "message": err.message,
        })

    def _on_skipped(self, task, reason) -> None:
        self._put(task.tab_id, {"type": "skipped", "prompt_id": task.prompt_id, "reason": reason})


def _env_float(name: str) -> float | None:
    val = os.environ.get(name, "").strip()
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None
