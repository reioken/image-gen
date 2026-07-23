"""Command-line front-end over the core engine.

This is a thin client: it parses arguments, loads env/config/prompts, builds the
task list and hands it to the same :class:`GlobalScheduler` the GUI uses. No
generation logic lives here.

Example::

    python -m product_image_batch \\
      --reference ./input/product_front.png \\
      --prompts ./prompts/product_shots.txt \\
      --providers openai,mock \\
      --images-per-prompt 1 \\
      --out ./outputs/run_2026_07_23 \\
      --max-total-cost 25.00 --rewrite-prompts
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import os
import sys
from pathlib import Path

import yaml

from .core.assets import collect_reference_paths, copy_into_run, validate_assets
from .core.budget import BudgetManager
from .core.config import PROVIDER_ENV_KEYS, load_config, load_settings
from .core.metadata import MetadataWriter
from .core.prompting import (
    PromptRewriter,
    load_prompts,
    load_rewrite_config,
    resolved_prompts_to_json,
)
from .core.providers.registry import provider_supports_reference_images
from .core.scheduler import (
    GlobalScheduler,
    SchedulerCallbacks,
    build_generation_tasks,
)
from .core.utils.logging import setup_logging


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="product_image_batch",
        description="Parallel product-image generation from reference images across many APIs.",
    )
    p.add_argument("--reference", action="append", default=[], metavar="PATH",
                   help="Reference image (repeatable).")
    p.add_argument("--reference-dir", metavar="PATH", help="Directory of reference images.")
    p.add_argument("--mask", metavar="PATH", help="Optional inpainting mask (PNG).")
    p.add_argument("--prompt", metavar="TEXT", help="A single prompt.")
    p.add_argument("--prompts", metavar="PATH", help="Prompts file (.txt or .json).")
    p.add_argument("--brief", metavar="PATH", help="Base brief for prompt generation.")
    p.add_argument("--generate-prompts", type=int, default=0, metavar="N",
                   help="Generate N prompt variants from --brief.")
    p.add_argument("--rewrite-prompts", action="store_true",
                   help="Add product-preservation + provider-specific rewriting to each prompt.")
    p.add_argument("--master-prompt", metavar="TEXT",
                   help="Global rule prepended to every prompt (consistency, setting, style).")
    p.add_argument("--master-prompt-file", metavar="PATH",
                   help="Read the master prompt from a file.")
    p.add_argument("--default-master-prompt", action="store_true",
                   help="Use the built-in strong consistency master prompt for every prompt.")
    p.add_argument("--providers", default="", metavar="LIST",
                   help="Comma-separated provider list (overrides config 'enabled').")
    p.add_argument("--models", default="", metavar="LIST",
                   help="Comma-separated provider:model overrides, e.g. openai:gpt-image-1.5,fal:...")
    p.add_argument("--images-per-prompt", type=int, default=1)
    p.add_argument("--size", default="1024x1024")
    p.add_argument("--quality", default="high")
    p.add_argument("--output-format", default="png")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--out", default=None, metavar="PATH", help="Output run directory.")
    p.add_argument("--config", default=None, metavar="PATH", help="Provider config YAML.")
    p.add_argument("--dry-run", action="store_true", help="Plan only; make no API calls.")
    p.add_argument("--max-total-cost", type=float, default=None)
    p.add_argument("--require-confirmation-over", type=float, default=None)
    p.add_argument("--yes", action="store_true", help="Skip confirmation prompts.")
    p.add_argument("--verbose", action="store_true")
    return p


def _resolve_provider_models(args, config) -> list[tuple[str, str]]:
    """Determine which (provider, model) pairs to run."""
    # Explicit --models wins (provider:model,provider:model).
    if args.models:
        pairs: list[tuple[str, str]] = []
        for chunk in args.models.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if ":" in chunk:
                prov, model = chunk.split(":", 1)
            else:
                prov, model = chunk, config.provider(chunk).resolve_model(None)
            pairs.append((prov.strip(), model.strip()))
        return pairs

    if args.providers:
        names = [n.strip() for n in args.providers.split(",") if n.strip()]
    else:
        names = config.enabled_providers()

    pairs = []
    for name in names:
        if name not in config.providers:
            print(f"warning: unknown provider '{name}', skipping", file=sys.stderr)
            continue
        model = config.provider(name).resolve_model(None)
        pairs.append((name, model))
    return pairs


def _filter_providers(pairs, config, env, dry_run: bool):
    """Drop providers with no key / no reference-image support; report why."""
    kept: list[tuple[str, str]] = []
    for prov, model in pairs:
        if not provider_supports_reference_images(prov):
            print(f"skip {prov}: does not support reference images", file=sys.stderr)
            continue
        key_var = PROVIDER_ENV_KEYS.get(prov, "")
        has_key = prov == "mock" or bool(env.get(key_var, "").strip())
        if not has_key and not dry_run:
            print(f"skip {prov}: missing API key ({key_var}) — skipped_missing_key", file=sys.stderr)
            continue
        kept.append((prov, model))
    return kept


def _resolve_master_prompt(args) -> str:
    """Resolve the master prompt from flags (file > text > built-in default)."""
    from .core.prompting import DEFAULT_MASTER_PROMPT

    if args.master_prompt_file:
        return Path(args.master_prompt_file).read_text(encoding="utf-8").strip()
    if args.master_prompt:
        return args.master_prompt.strip()
    if args.default_master_prompt:
        return DEFAULT_MASTER_PROMPT
    return ""


def _default_out_dir() -> Path:
    stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    return Path("outputs") / f"{stamp}_product_batch"


async def _run(args) -> int:
    log = setup_logging(verbose=args.verbose)
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # noqa: BLE001
        pass
    env = dict(os.environ)

    config = load_config(args.config)
    config.apply_settings(load_settings())

    # References
    references = collect_reference_paths(
        [Path(r) for r in args.reference], Path(args.reference_dir) if args.reference_dir else None
    )
    mask = Path(args.mask) if args.mask else None
    if not references:
        print("error: at least one --reference or --reference-dir is required", file=sys.stderr)
        return 2
    try:
        validate_assets(references, mask)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Prompts
    variants = load_prompts(prompt=args.prompt, prompts_path=args.prompts)
    provider_models = _resolve_provider_models(args, config)
    provider_models = _filter_providers(provider_models, config, env, args.dry_run)
    if not provider_models:
        print("error: no runnable providers (check --providers and API keys)", file=sys.stderr)
        return 2
    provider_names = sorted({p for p, _ in provider_models})

    rewriter = PromptRewriter(load_rewrite_config())
    master_prompt = _resolve_master_prompt(args)
    if args.brief and args.generate_prompts > 0:
        brief_text = Path(args.brief).read_text(encoding="utf-8")
        variants = rewriter.generate_from_brief(
            brief_text, args.generate_prompts, provider_names,
            with_mask=mask is not None, master_prompt=master_prompt,
        )
    elif not variants:
        print("error: provide --prompt/--prompts or --brief with --generate-prompts", file=sys.stderr)
        return 2
    elif args.rewrite_prompts or master_prompt:
        variants = rewriter.rewrite_all(
            variants, provider_names, with_mask=mask is not None, master_prompt=master_prompt
        )

    # Output dir
    out_dir = Path(args.out) if args.out else _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    copied_refs, copied_mask = copy_into_run(references, mask, out_dir)

    # Build tasks
    tasks = build_generation_tasks(
        prompts=variants,
        provider_models=provider_models,
        reference_images=copied_refs,
        mask=copied_mask,
        images_per_prompt=args.images_per_prompt,
        size=args.size,
        quality=args.quality,
        output_format=args.output_format,
        seed=args.seed,
        tab_id="cli",
    )

    # Persist run config + resolved prompts.
    _write_run_config(out_dir, args, provider_models, references, mask)
    (out_dir / "prompts.resolved.json").write_text(
        json.dumps(resolved_prompts_to_json(variants), indent=2), encoding="utf-8"
    )

    budget = BudgetManager(
        max_total_cost=args.max_total_cost,
        require_confirmation_over=args.require_confirmation_over,
    )

    # Dry run: estimate and print, no API calls.
    if args.dry_run:
        return await _dry_run(tasks, provider_models, config, env, out_dir, budget)

    return await _execute(tasks, config, budget, env, out_dir)


async def _dry_run(tasks, provider_models, config, env, out_dir, budget) -> int:
    from .core.providers.registry import create_provider, resolve_api_key

    total = 0.0
    unknown = False
    per_provider: dict[str, int] = {}
    for task in tasks:
        per_provider[task.provider] = per_provider.get(task.provider, 0) + 1
        prov_cfg = config.providers.get(task.provider)
        adapter = create_provider(
            task.provider, prov_cfg, api_key=resolve_api_key(task.provider, env), model=task.model
        )
        est = await adapter.estimate_cost(task)
        total += est.amount_usd
        unknown = unknown or not est.known

    _print_plan(tasks, per_provider, provider_models, out_dir, total, unknown, budget)
    return 0


def _print_plan(tasks, per_provider, provider_models, out_dir, total, unknown, budget) -> None:
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title="Dry run — planned jobs (no API calls made)")
        table.add_column("Provider")
        table.add_column("Model")
        table.add_column("Tasks", justify="right")
        counts: dict[tuple[str, str], int] = {}
        for t in tasks:
            counts[(t.provider, t.model)] = counts.get((t.provider, t.model), 0) + 1
        for (prov, model), n in sorted(counts.items()):
            table.add_row(prov, model, str(n))
        console.print(table)
        cap = f"${budget.max_total_cost:.2f}" if budget.max_total_cost else "none"
        console.print(
            f"Total tasks: [bold]{len(tasks)}[/bold] · "
            f"Estimated cost: [bold]${total:.2f}[/bold]{' (some uncertain)' if unknown else ''} · "
            f"Budget cap: {cap} · Output: {out_dir}"
        )
    except Exception:  # noqa: BLE001 — rich optional
        print(f"Dry run: {len(tasks)} tasks, est ${total:.2f}, out={out_dir}")
        for k, v in per_provider.items():
            print(f"  {k}: {v} tasks")


async def _execute(tasks, config, budget, env, out_dir) -> int:
    progress_ctx = _make_progress(len(tasks))
    callbacks = SchedulerCallbacks()
    state = {"done": 0}

    if progress_ctx is not None:
        progress, task_bar = progress_ctx

        def _advance(*_):
            state["done"] += 1
            progress.update(task_bar, completed=state["done"])

        callbacks.on_task_succeeded = lambda t, s, r: _advance()
        callbacks.on_task_failed = lambda t, e: _advance()
        callbacks.on_task_skipped = lambda t, r: _advance()

    writer = MetadataWriter(out_dir)
    async with GlobalScheduler(config, budget=budget, env=env, callbacks=callbacks) as sched:
        if progress_ctx is not None:
            with progress_ctx[0]:
                result = await sched.run_batch("cli", tasks, out_dir, metadata_writer=writer)
        else:
            result = await sched.run_batch("cli", tasks, out_dir, metadata_writer=writer)
    writer.finalize_csv()

    print(
        f"\nDone: {result.succeeded} succeeded, {result.failed} failed, "
        f"{result.skipped} skipped. Output: {out_dir}"
    )
    print(f"Spend: {budget.summary()}")
    return 0 if result.failed == 0 else 1


def _make_progress(total: int):
    try:
        from rich.progress import (
            BarColumn,
            Progress,
            TextColumn,
            TimeElapsedColumn,
        )

        progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
        )
        bar = progress.add_task("Generating", total=total)
        return progress, bar
    except Exception:  # noqa: BLE001
        return None


def _write_run_config(out_dir: Path, args, provider_models, references, mask) -> None:
    data = {
        "created_at": _dt.datetime.now().isoformat(),
        "references": [str(r) for r in references],
        "mask": str(mask) if mask else None,
        "provider_models": [{"provider": p, "model": m} for p, m in provider_models],
        "images_per_prompt": args.images_per_prompt,
        "size": args.size,
        "quality": args.quality,
        "output_format": args.output_format,
        "seed": args.seed,
        "rewrite_prompts": args.rewrite_prompts,
        "max_total_cost": args.max_total_cost,
    }
    (out_dir / "run_config.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
