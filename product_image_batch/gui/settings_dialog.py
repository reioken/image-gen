"""Global settings dialog: concurrency, budget, provider enablement + API keys.

Settings persist to ``settings.json`` under the per-user app-data dir; API keys
persist to the per-user ``.env`` (never committed, never baked into the .exe).
Changes to concurrency apply to newly started tasks immediately.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.config import (
    PROVIDER_ENV_KEYS,
    AppConfig,
    app_data_dir,
    ensure_user_env,
    load_settings,
    save_settings,
)


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip()
    return values


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    lines = ["# product-image-batch API keys — do not commit or share.", ""]
    for var in PROVIDER_ENV_KEYS.values():
        if var:
            lines.append(f"{var}={values.get(var, '')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.config = config
        self.settings = load_settings()
        self.env_path = ensure_user_env()
        self.env_values = _read_env_file(self.env_path)
        self.setMinimumWidth(560)

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        scroll.setWidget(host)
        outer.addWidget(scroll)

        # --- concurrency + budget ---
        gen = QGroupBox("Concurrency & budget")
        form = QFormLayout(gen)
        self.global_conc = QSpinBox()
        self.global_conc.setRange(1, 500)
        self.global_conc.setValue(int(self.settings.get("global_max_concurrent", 20)))
        form.addRow("Global max concurrent requests (all providers):", self.global_conc)

        self.max_tabs = QSpinBox()
        self.max_tabs.setRange(0, 100)
        self.max_tabs.setValue(int(self.settings.get("max_concurrent_tabs", 0)))
        form.addRow("Max concurrent running tabs (0 = unlimited):", self.max_tabs)

        self.auto_retry = QCheckBox("Auto-retry failed requests")
        self.auto_retry.setChecked(bool(self.settings.get("auto_retry", True)))
        form.addRow(self.auto_retry)

        self.max_retries = QSpinBox()
        self.max_retries.setRange(0, 10)
        self.max_retries.setValue(int(self.settings.get("max_retries", 3)))
        form.addRow("Max retries:", self.max_retries)

        self.budget_total = QDoubleSpinBox()
        self.budget_total.setRange(0.0, 100000.0)
        self.budget_total.setDecimals(2)
        self.budget_total.setValue(float(self.settings.get("budget_cap_total_usd", 0.0)))
        form.addRow("Total budget cap USD (0 = no cap):", self.budget_total)

        self.budget_per_tab = QDoubleSpinBox()
        self.budget_per_tab.setRange(0.0, 100000.0)
        self.budget_per_tab.setDecimals(2)
        self.budget_per_tab.setValue(float(self.settings.get("budget_cap_per_tab_usd", 0.0)))
        form.addRow("Per-tab budget cap USD (0 = no cap):", self.budget_per_tab)
        layout.addWidget(gen)

        # --- per-provider ---
        prov_box = QGroupBox("Providers (enable, per-provider concurrency, API keys)")
        prov_form = QFormLayout(prov_box)
        prov_form.addRow(QLabel(
            f"API keys are stored in:\n{self.env_path}\n(never committed / never baked into the .exe)"
        ))
        self.provider_widgets: dict[str, tuple[QCheckBox, QSpinBox, QLineEdit]] = {}
        per_conc = self.settings.get("per_provider_concurrency", {})
        enabled = self.settings.get("enabled_providers", {})
        for name, prov in config.providers.items():
            row = QHBoxLayout()
            chk = QCheckBox("enabled")
            chk.setChecked(bool(enabled.get(name, prov.enabled)))
            row.addWidget(chk)
            row.addWidget(QLabel("concurrency:"))
            spin = QSpinBox()
            spin.setRange(1, 200)
            spin.setValue(int(per_conc.get(name, prov.max_concurrent)))
            row.addWidget(spin)
            key_var = PROVIDER_ENV_KEYS.get(name, "")
            key_edit = QLineEdit(self.env_values.get(key_var, "") if key_var else "")
            key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            key_edit.setPlaceholderText(key_var or "(no key needed)")
            key_edit.setEnabled(bool(key_var))
            row.addWidget(key_edit)
            container = QWidget()
            container.setLayout(row)
            prov_form.addRow(f"{name}:", container)
            self.provider_widgets[name] = (chk, spin, key_edit)
        layout.addWidget(prov_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _save(self) -> None:
        per_conc: dict[str, int] = {}
        enabled: dict[str, bool] = {}
        for name, (chk, spin, key_edit) in self.provider_widgets.items():
            per_conc[name] = spin.value()
            enabled[name] = chk.isChecked()
            key_var = PROVIDER_ENV_KEYS.get(name, "")
            if key_var:
                self.env_values[key_var] = key_edit.text().strip()

        self.settings.update({
            "global_max_concurrent": self.global_conc.value(),
            "max_concurrent_tabs": self.max_tabs.value(),
            "auto_retry": self.auto_retry.isChecked(),
            "max_retries": self.max_retries.value(),
            "budget_cap_total_usd": self.budget_total.value(),
            "budget_cap_per_tab_usd": self.budget_per_tab.value(),
            "per_provider_concurrency": per_conc,
            "enabled_providers": enabled,
        })
        save_settings(self.settings)
        _write_env_file(self.env_path, self.env_values)
        self.accept()

    def result_settings(self) -> dict:
        return self.settings
