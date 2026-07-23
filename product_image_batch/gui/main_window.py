"""Main window: toolbar + QTabWidget of run tabs, wired to the shared bridge."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QToolBar,
    QWidget,
)

from ..core.budget import BudgetManager
from ..core.config import AppConfig, load_config, load_settings
from ..core.prompting import PromptRewriter, load_rewrite_config
from ..core.utils.logging import app_data_dir, get_logger
from .async_bridge import AsyncBridge
from .settings_dialog import SettingsDialog
from .tab_widget import TabRunController

log = get_logger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Product Image Batch")
        self.resize(1100, 820)

        # Config + settings.
        self.config: AppConfig = load_config()
        self.settings = load_settings()
        self.config.apply_settings(self.settings)
        self.rewriter = PromptRewriter(load_rewrite_config())
        self.output_root = Path.cwd() / "outputs"
        self.output_root.mkdir(parents=True, exist_ok=True)

        # Budget from settings.
        cap = float(self.settings.get("budget_cap_total_usd", 0.0)) or None
        self.budget = BudgetManager(max_total_cost=cap)

        # Shared engine bridge (one scheduler for the whole app).
        self.bridge = AsyncBridge(self.config, budget=self.budget, env=dict(os.environ))
        self._connect_bridge()

        # Tabs.
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab_index)
        self.setCentralWidget(self.tabs)
        self._tab_counter = 0
        self._by_id: dict[str, TabRunController] = {}

        self._build_toolbar()
        self.add_tab()

        self.status = QLabel("ready")
        self.statusBar().addWidget(self.status)
        self._refresh_status()

    # --- toolbar -----------------------------------------------------------
    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        self.addToolBar(tb)
        tb.addAction("➕ New tab", self.add_tab)
        tb.addAction("⚙ Settings", self.open_settings)
        tb.addAction("▶ Start all tabs", self.start_all_tabs)
        tb.addAction("■ Stop all", self.stop_all_tabs)
        tb.addSeparator()
        self.budget_label = QLabel("  Budget: $0.00  ")
        tb.addWidget(self.budget_label)

    # --- bridge signals ----------------------------------------------------
    def _connect_bridge(self) -> None:
        b = self.bridge
        b.sig_task_started.connect(self._on_task_started)
        b.sig_task_succeeded.connect(self._on_task_succeeded)
        b.sig_task_failed.connect(self._on_task_failed)
        b.sig_task_skipped.connect(self._on_task_skipped)
        b.sig_batch_finished.connect(self._on_batch_finished)
        b.sig_budget_changed.connect(self._on_budget_changed)
        b.sig_progress.connect(lambda msg: self.status.setText(msg))

    def _tab(self, tab_id: str) -> TabRunController | None:
        return self._by_id.get(tab_id)

    def _on_task_started(self, task) -> None:
        tab = self._tab(task.tab_id)
        if tab:
            tab.handle_task_started(task)

    def _on_task_succeeded(self, task, saved, record) -> None:
        tab = self._tab(task.tab_id)
        if tab:
            tab.handle_task_succeeded(task, saved, record)
        self._refresh_status()

    def _on_task_failed(self, task, err) -> None:
        tab = self._tab(task.tab_id)
        if tab:
            tab.handle_task_failed(task, err)
        self._refresh_status()

    def _on_task_skipped(self, task, reason) -> None:
        tab = self._tab(task.tab_id)
        if tab:
            tab.handle_task_skipped(task, reason)

    def _on_batch_finished(self, tab_id, result) -> None:
        tab = self._tab(tab_id)
        if tab:
            tab.handle_batch_finished(result)
        self._refresh_status()

    def _on_budget_changed(self, summary: dict) -> None:
        est = summary.get("estimated_spend_usd", 0.0)
        cap = summary.get("max_total_cost_usd")
        cap_txt = f" / ${cap:.2f}" if cap else ""
        self.budget_label.setText(f"  Budget: ${est:.2f}{cap_txt}  ")

    # --- tabs --------------------------------------------------------------
    def add_tab(self, name: str | None = None) -> TabRunController:
        self._tab_counter += 1
        tab_id = f"tab{self._tab_counter}"
        name = name or f"Run {chr(64 + self._tab_counter)}" if self._tab_counter <= 26 else f"Run {self._tab_counter}"
        ctrl = TabRunController(
            self.config, self.bridge, tab_id, name, self.rewriter, self.output_root
        )
        ctrl.request_close.connect(self._close_tab_widget)
        ctrl.request_duplicate.connect(self._duplicate_from_snapshot)
        ctrl.status_changed.connect(self._refresh_status)
        self._by_id[tab_id] = ctrl
        idx = self.tabs.addTab(ctrl, name)
        self.tabs.setCurrentIndex(idx)
        return ctrl

    def _duplicate_from_snapshot(self, snap: dict) -> None:
        ctrl = self.add_tab(snap.get("name"))
        ctrl.load_snapshot(snap)

    def _close_tab_index(self, index: int) -> None:
        w = self.tabs.widget(index)
        if isinstance(w, TabRunController):
            self._close_tab_widget(w)

    def _close_tab_widget(self, ctrl: TabRunController) -> None:
        if ctrl.is_running():
            if QMessageBox.question(self, "Close tab", "This tab is running. Stop and close?") \
                    != QMessageBox.StandardButton.Yes:
                return
            ctrl.stop()
        idx = self.tabs.indexOf(ctrl)
        if idx >= 0:
            self.tabs.removeTab(idx)
        self._by_id.pop(ctrl.tab_id, None)
        ctrl.deleteLater()
        if self.tabs.count() == 0:
            self.add_tab()

    # --- run controls ------------------------------------------------------
    def start_all_tabs(self) -> None:
        max_tabs = int(self.settings.get("max_concurrent_tabs", 0) or 0)
        running = len(self.bridge.active_tabs())
        for ctrl in self._by_id.values():
            if ctrl.is_running():
                continue
            if max_tabs and running >= max_tabs:
                break
            ctrl.start()
            running += 1
        self._refresh_status()

    def stop_all_tabs(self) -> None:
        for ctrl in self._by_id.values():
            if ctrl.is_running():
                ctrl.stop()

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.config, self)
        if dlg.exec():
            self.settings = dlg.result_settings()
            self.config.apply_settings(self.settings)
            # Push new concurrency to the live scheduler.
            for name, prov in self.config.providers.items():
                self.bridge.update_provider_concurrency(name, prov.max_concurrent)
            cap = float(self.settings.get("budget_cap_total_usd", 0.0)) or None
            self.budget.max_total_cost = cap
            # Reload env so newly entered keys take effect.
            self._reload_env()
            self._refresh_status()

    def _reload_env(self) -> None:
        env_path = app_data_dir() / ".env"
        if env_path.exists():
            try:
                from dotenv import load_dotenv

                load_dotenv(env_path, override=True)
            except Exception:  # noqa: BLE001
                pass
            self.bridge.env = dict(os.environ)
            self.bridge._scheduler.env = dict(os.environ)
            self.bridge.reset_disabled_providers()

    def _refresh_status(self) -> None:
        active = len(self.bridge.active_tabs())
        summary = self.budget.summary()
        self.status.setText(
            f"{active} tab(s) active · est spend ${summary['estimated_spend_usd']:.2f}"
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.bridge.shutdown()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)
