"""Scheduler tests: concurrency limits, budget skipping, error isolation."""

from __future__ import annotations

import pytest

from product_image_batch.core.budget import BudgetManager
from product_image_batch.core.config import ProviderConfig
from product_image_batch.core.metadata import MetadataWriter, read_jsonl
from product_image_batch.core.models import GenerationTask
from product_image_batch.core.scheduler import GlobalScheduler
from probe import ProbeProvider, make_tasks


async def test_provider_semaphore_limits_concurrency(probe_config, tmp_path):
    tasks = make_tasks(12)
    async with GlobalScheduler(probe_config, env={}) as sched:
        res = await sched.run_batch("t", tasks, tmp_path, metadata_writer=MetadataWriter(tmp_path))
    assert res.succeeded == 12
    assert ProbeProvider.peak <= 3, f"peak {ProbeProvider.peak} exceeded max_concurrent=3"


async def test_global_cap_limits_concurrency(probe_config, tmp_path):
    probe_config.providers["probe"].max_concurrent = 50
    probe_config.global_max_concurrent = 4
    tasks = make_tasks(16)
    async with GlobalScheduler(probe_config, env={}) as sched:
        await sched.run_batch("t", tasks, tmp_path, metadata_writer=MetadataWriter(tmp_path))
    assert ProbeProvider.peak <= 4


async def test_budget_cap_skips_tasks(probe_config, tmp_path):
    # cost 0.01/img, cap 0.05 => only 5 succeed, rest skipped.
    budget = BudgetManager(max_total_cost=0.05)
    tasks = make_tasks(20)
    writer = MetadataWriter(tmp_path)
    async with GlobalScheduler(probe_config, budget=budget, env={}) as sched:
        res = await sched.run_batch("t", tasks, tmp_path, metadata_writer=writer)
    assert res.succeeded == 5
    assert res.skipped == 15
    md = read_jsonl(tmp_path / "metadata.jsonl")
    assert sum(1 for r in md if r["status"] == "skipped") == 15


async def test_one_provider_failure_does_not_block_batch(probe_config, tmp_path):
    probe_config.providers["flaky"] = ProviderConfig(
        name="flaky", enabled=True, max_concurrent=2, default_model="f", models=["f"]
    )
    probe_config.retry.max_retries = 1
    tasks = make_tasks(4, provider="probe") + [
        GenerationTask(task_id=f"f-{i}", prompt_id=f"f{i}", prompt_text="x",
                       provider="flaky", model="f", tab_id="t")
        for i in range(3)
    ]
    async with GlobalScheduler(probe_config, env={}) as sched:
        res = await sched.run_batch("t", tasks, tmp_path, metadata_writer=MetadataWriter(tmp_path))
    assert res.succeeded == 4   # probe tasks all succeed
    assert res.failed == 3      # flaky tasks fail but don't abort the batch
    errs = read_jsonl(tmp_path / "errors.jsonl")
    assert all(e["error_type"] == "ProviderRateLimitError" for e in errs)


async def test_acceptance_two_refs_three_prompts_three_providers(probe_config, tmp_path, ref_image, second_ref_image):
    """Acceptance: 2 refs × 3 prompts × 3 providers => 9 tasks."""
    from product_image_batch.core.prompting import PromptVariant
    from product_image_batch.core.scheduler import build_generation_tasks

    # three probe-like providers
    for name in ("probe", "probe2", "probe3"):
        if name not in probe_config.providers:
            probe_config.providers[name] = ProviderConfig(
                name=name, enabled=True, max_concurrent=5, default_model="probe-v1",
                models=["probe-v1"],
            )
        from product_image_batch.core.providers import registry
        registry.PROVIDER_CLASSES[name] = ProbeProvider

    variants = [PromptVariant(f"p{i:03d}", "b", f"prompt {i}") for i in range(1, 4)]
    tasks = build_generation_tasks(
        prompts=variants,
        provider_models=[("probe", "probe-v1"), ("probe2", "probe-v1"), ("probe3", "probe-v1")],
        reference_images=[ref_image, second_ref_image],
        images_per_prompt=1,
        tab_id="t",
    )
    assert len(tasks) == 9
    async with GlobalScheduler(probe_config, env={}) as sched:
        res = await sched.run_batch("t", tasks, tmp_path, metadata_writer=MetadataWriter(tmp_path))
    assert res.succeeded == 9
