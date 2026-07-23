"""A single run tab: reference drop zones + agent rows + live results.

Each tab is an independent run configuration. Starting a tab builds one
``GenerationTask`` list from its agent rows and submits it to the shared
:class:`AsyncBridge`/``GlobalScheduler`` (never a tab-local scheduler), so all
tabs share one rate-limit-safe pool per provider.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.assets import copy_into_run, validate_assets
from ..core.config import AppConfig
from ..core.metadata import utc_timestamp_compact
from ..core.prompting import PromptRewriter, PromptVariant
from ..core.scheduler import build_generation_tasks
from ..core.utils import images as imgutil
from ..core.utils.logging import get_logger
from .agent_row import AgentConfig, AgentRow
from .drop_zone import ReferenceImageDropZone
from .thumbnail_gallery import ThumbnailGallery

log = get_logger(__name__)


class TabRunController(QWidget):
    """Owns one tab's widgets and drives its runs through the shared bridge."""

    request_close = Signal(object)  # self
    request_duplicate = Signal(object)  # AgentConfig snapshot payload
    status_changed = Signal()

    def __init__(self, config: AppConfig, bridge, tab_id: str, name: str,
                 rewriter: PromptRewriter, output_root: Path) -> None:
        super().__init__()
        self.config = config
        self.bridge = bridge
        self.tab_id = tab_id
        self.name = name
        self.rewriter = rewriter
        self.output_root = output_root
        self.current_out_dir: Path | None = None
        self._running = False
        self._agent_index = 0
        self._prompt_to_row: dict[str, AgentRow] = {}

        root = QVBoxLayout(self)

        # Reference + mask drop zones.
        self.refs = ReferenceImageDropZone("Reference images")
        root.addWidget(self.refs)
        self.mask = ReferenceImageDropZone("Mask (optional, PNG — for inpainting)", single=True)
        root.addWidget(self.mask)

        # Agent rows (scrollable).
        agents_label = QLabel("<b>Agents</b> — each row runs in parallel")
        root.addWidget(agents_label)
        self._agents_host = QWidget()
        self._agents_layout = QVBoxLayout(self._agents_host)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._agents_host)
        scroll.setMinimumHeight(240)
        root.addWidget(scroll)

        add_agent = QPushButton("➕ Add agent")
        add_agent.clicked.connect(lambda: self.add_agent())
        root.addWidget(add_agent)

        # Action buttons.
        actions = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start this tab")
        self.start_btn.clicked.connect(self.start)
        actions.addWidget(self.start_btn)
        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setEnabled(False)
        actions.addWidget(self.stop_btn)
        dup_btn = QPushButton("⧉ Duplicate tab")
        dup_btn.clicked.connect(lambda: self.request_duplicate.emit(self.snapshot()))
        actions.addWidget(dup_btn)
        open_btn = QPushButton("📁 Open folder")
        open_btn.clicked.connect(self._open_folder)
        actions.addWidget(open_btn)
        close_btn = QPushButton("Close tab")
        close_btn.clicked.connect(lambda: self.request_close.emit(self))
        actions.addWidget(close_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        # Results gallery.
        root.addWidget(QLabel("<b>Results</b> (live thumbnails — double-click to open)"))
        self.gallery = ThumbnailGallery()
        root.addWidget(self.gallery)

        self.tab_status = QLabel("idle")
        root.addWidget(self.tab_status)

        self.add_agent()  # start with one agent row

    # --- agents ------------------------------------------------------------
    def add_agent(self, agent: AgentConfig | None = None) -> AgentRow:
        self._agent_index += 1
        row = AgentRow(self.config, self._agent_index, agent)
        row.removed.connect(self._remove_agent)
        self._agents_layout.addWidget(row)
        return row

    def _remove_agent(self, row: AgentRow) -> None:
        row.setParent(None)
        row.deleteLater()

    def agent_rows(self) -> list[AgentRow]:
        rows = []
        for i in range(self._agents_layout.count()):
            w = self._agents_layout.itemAt(i).widget()
            if isinstance(w, AgentRow):
                rows.append(w)
        return rows

    # --- snapshot / duplicate ---------------------------------------------
    def snapshot(self) -> dict:
        return {
            "name": f"{self.name} copy",
            "references": [str(p) for p in self.refs.paths()],
            "mask": [str(p) for p in self.mask.paths()],
            "agents": [row.to_config() for row in self.agent_rows()],
        }

    def load_snapshot(self, snap: dict) -> None:
        self.refs.set_paths([Path(p) for p in snap.get("references", [])])
        self.mask.set_paths([Path(p) for p in snap.get("mask", [])])
        # Clear default agent, add from snapshot.
        for row in self.agent_rows():
            self._remove_agent(row)
        for agent in snap.get("agents", []):
            self.add_agent(agent)

    # --- run ---------------------------------------------------------------
    def _build_tasks(self):
        references = self.refs.paths()
        mask_paths = self.mask.paths()
        mask = mask_paths[0] if mask_paths else None
        validate_assets(references, mask)

        out_dir = self.output_root / f"{utc_timestamp_compact()}_{_safe(self.name)}"
        out_dir.mkdir(parents=True, exist_ok=True)
        copied_refs, copied_mask = copy_into_run(references, mask, out_dir)
        self.current_out_dir = out_dir

        tasks = []
        self._prompt_to_row = {}
        for i, row in enumerate(self.agent_rows(), start=1):
            cfg = row.to_config()
            if not cfg.prompt:
                row.set_status("skipped: empty prompt")
                continue
            prompt_id = f"a{i:02d}"
            variant = PromptVariant(prompt_id=prompt_id, base_intent=cfg.label, text=cfg.prompt)
            variant = self.rewriter.rewrite_variant(
                variant, [cfg.provider], with_mask=copied_mask is not None
            )
            row_tasks = build_generation_tasks(
                prompts=[variant],
                provider_models=[(cfg.provider, cfg.model or None)],
                reference_images=copied_refs,
                mask=copied_mask,
                images_per_prompt=cfg.images,
                size=cfg.size,
                seed=cfg.seed,
                tab_id=self.tab_id,
            )
            for t in row_tasks:
                t.provider_params.update(cfg.provider_params)
            tasks.extend(row_tasks)
            self._prompt_to_row[prompt_id] = row
            row.begin_run()
        return tasks, out_dir

    def start(self) -> None:
        if self._running:
            return
        try:
            tasks, out_dir = self._build_tasks()
        except imgutil.ImageValidationError as exc:
            self.tab_status.setText(f"cannot start: {exc}")
            return
        if not tasks:
            self.tab_status.setText("cannot start: add at least one agent with a prompt")
            return
        self.gallery.clear()
        self._running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.tab_status.setText(f"running {len(tasks)} task(s) → {out_dir}")
        self.status_changed.emit()
        self.bridge.run_batch(self.tab_id, tasks, out_dir)

    def stop(self) -> None:
        self.bridge.cancel_tab(self.tab_id)
        self.tab_status.setText("stopping…")

    def is_running(self) -> bool:
        return self._running

    def _open_folder(self) -> None:
        target = self.current_out_dir or self.output_root
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # --- signal handlers (called on the UI thread by MainWindow) -----------
    def handle_task_started(self, task) -> None:
        row = self._prompt_to_row.get(task.prompt_id)
        if row:
            row.set_status(f"running ({row._done}/{row._expected})")

    def handle_task_succeeded(self, task, saved, record) -> None:
        row = self._prompt_to_row.get(task.prompt_id)
        if row:
            row.tick(ok=True)
        for s in saved:
            self.gallery.add_image(s.path)

    def handle_task_failed(self, task, err) -> None:
        row = self._prompt_to_row.get(task.prompt_id)
        if row:
            row.tick(ok=False)
            row.set_status(f"error: {err.error_type}")

    def handle_task_skipped(self, task, reason) -> None:
        row = self._prompt_to_row.get(task.prompt_id)
        if row:
            row.tick(ok=False)
            row.set_status(f"skipped: {reason[:40]}")

    def handle_batch_finished(self, result) -> None:
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.tab_status.setText(
            f"done: {result.succeeded} ok, {result.failed} failed, "
            f"{result.skipped} skipped → {self.current_out_dir}"
        )
        self.status_changed.emit()


def _safe(name: str) -> str:
    from ..core.utils.files import sanitize_component

    return sanitize_component(name) or "run"
