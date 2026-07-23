"""Prove the single global scheduler shares one per-provider limit across tabs.

If each tab had its own scheduler, running N tabs at once would multiply the
per-provider concurrency by N. This runs two tabs concurrently against one
GlobalScheduler and asserts the observed peak never exceeds the single provider
semaphore — the whole reason the scheduler is global.
"""

from __future__ import annotations

import asyncio

from product_image_batch.core.metadata import MetadataWriter, read_jsonl
from product_image_batch.core.scheduler import GlobalScheduler
from probe import ProbeProvider, make_tasks


async def test_two_tabs_share_one_provider_limit(probe_config, tmp_path):
    ProbeProvider.reset()
    probe_config.providers["probe"].max_concurrent = 3
    probe_config.global_max_concurrent = 100

    async with GlobalScheduler(probe_config, env={}) as sched:
        out_a, out_b = tmp_path / "a", tmp_path / "b"
        res_a, res_b = await asyncio.gather(
            sched.run_batch("tabA", make_tasks(10, "tabA"), out_a, metadata_writer=MetadataWriter(out_a)),
            sched.run_batch("tabB", make_tasks(10, "tabB"), out_b, metadata_writer=MetadataWriter(out_b)),
        )

    assert res_a.succeeded == 10
    assert res_b.succeeded == 10
    # Across BOTH tabs, concurrency stayed within the single provider semaphore of 3.
    assert ProbeProvider.peak <= 3, f"peak {ProbeProvider.peak} — tabs did not share the limit"
    assert len(read_jsonl(out_a / "metadata.jsonl")) == 10
    assert len(read_jsonl(out_b / "metadata.jsonl")) == 10


async def test_cancel_tab_only_affects_that_tab(probe_config, tmp_path):
    ProbeProvider.reset()
    probe_config.providers["probe"].max_concurrent = 2

    async with GlobalScheduler(probe_config, env={}) as sched:
        fut_a = asyncio.ensure_future(
            sched.run_batch("tabA", make_tasks(30, "tabA"), tmp_path / "a",
                            metadata_writer=MetadataWriter(tmp_path / "a"))
        )
        fut_b = asyncio.ensure_future(
            sched.run_batch("tabB", make_tasks(4, "tabB"), tmp_path / "b",
                            metadata_writer=MetadataWriter(tmp_path / "b"))
        )
        await asyncio.sleep(0.02)
        cancelled = sched.cancel_tab("tabA")
        res_a = await fut_a
        res_b = await fut_b

    assert cancelled > 0
    assert res_b.succeeded == 4          # tab B unaffected
    assert res_a.succeeded < 30          # tab A cancelled mid-flight
