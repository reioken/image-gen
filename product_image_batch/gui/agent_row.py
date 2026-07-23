"""One agent row = one prompt + provider + model + image count + status.

Each row corresponds to a ``GenerationTask`` generator: with ``images > 1`` it
expands into several tasks. Rows within a tab all run concurrently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from ..core.config import AppConfig


@dataclass
class AgentConfig:
    """Serializable state of one agent row (used for duplicate + persistence)."""

    label: str = "Agent 1"
    provider: str = "openai"
    model: str = ""
    prompt: str = ""
    images: int = 1
    size: str = "1024x1024"
    seed: int | None = None
    strength: float | None = None
    provider_params: dict = field(default_factory=dict)


class AgentRow(QFrame):
    """UI for a single agent row."""

    removed = Signal(object)  # self

    def __init__(self, config: AppConfig, index: int, agent: AgentConfig | None = None) -> None:
        super().__init__()
        self.config = config
        self.setFrameShape(QFrame.Shape.StyledPanel)
        agent = agent or AgentConfig(label=f"Agent {index}")

        grid = QGridLayout(self)
        grid.setContentsMargins(8, 8, 8, 8)

        self.label = QLabel(f"<b>{agent.label}</b>")
        grid.addWidget(self.label, 0, 0)

        grid.addWidget(QLabel("Provider:"), 0, 1)
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(list(config.providers.keys()))
        if agent.provider in config.providers:
            self.provider_combo.setCurrentText(agent.provider)
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        grid.addWidget(self.provider_combo, 0, 2)

        grid.addWidget(QLabel("Model:"), 0, 3)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        grid.addWidget(self.model_combo, 0, 4)

        grid.addWidget(QLabel("Images:"), 0, 5)
        self.images_spin = QSpinBox()
        self.images_spin.setRange(1, 100)
        self.images_spin.setValue(agent.images)
        grid.addWidget(self.images_spin, 0, 6)

        remove_btn = QPushButton("✕")
        remove_btn.setMaximumWidth(32)
        remove_btn.clicked.connect(lambda: self.removed.emit(self))
        grid.addWidget(remove_btn, 0, 7)

        grid.addWidget(QLabel("Prompt:"), 1, 0)
        self.prompt_edit = QPlainTextEdit(agent.prompt)
        self.prompt_edit.setPlaceholderText(
            "Describe the target image. Keep the exact product; change only scene, "
            "lighting, background, camera angle…"
        )
        self.prompt_edit.setFixedHeight(56)
        grid.addWidget(self.prompt_edit, 1, 1, 1, 7)

        grid.addWidget(QLabel("Size:"), 2, 1)
        self.size_edit = QLineEdit(agent.size)
        self.size_edit.setMaximumWidth(110)
        grid.addWidget(self.size_edit, 2, 2)

        grid.addWidget(QLabel("Seed:"), 2, 3)
        self.seed_edit = QLineEdit("" if agent.seed is None else str(agent.seed))
        self.seed_edit.setMaximumWidth(90)
        self.seed_edit.setPlaceholderText("random")
        grid.addWidget(self.seed_edit, 2, 4)

        grid.addWidget(QLabel("Strength:"), 2, 5)
        self.strength_edit = QLineEdit("" if agent.strength is None else str(agent.strength))
        self.strength_edit.setMaximumWidth(70)
        self.strength_edit.setPlaceholderText("auto")
        grid.addWidget(self.strength_edit, 2, 6)

        self.status = QLabel("idle")
        self.status.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self.status, 3, 0, 1, 3)
        self.progress = QProgressBar()
        self.progress.setRange(0, agent.images)
        self.progress.setValue(0)
        grid.addWidget(self.progress, 3, 3, 1, 5)

        self._populate_models(agent.provider, agent.model)

        # per-run counters, updated by the tab controller.
        self._expected = agent.images
        self._done = 0

    # --- model list --------------------------------------------------------
    def _on_provider_changed(self, provider: str) -> None:
        self._populate_models(provider, None)

    def _populate_models(self, provider: str, selected: str | None) -> None:
        self.model_combo.clear()
        prov = self.config.providers.get(provider)
        if prov:
            self.model_combo.addItems(prov.models or [prov.resolve_model(None)])
        if selected:
            self.model_combo.setCurrentText(selected)

    # --- config <-> ui -----------------------------------------------------
    def to_config(self) -> AgentConfig:
        seed_txt = self.seed_edit.text().strip()
        strength_txt = self.strength_edit.text().strip()
        params: dict = {}
        if strength_txt:
            try:
                params["strength"] = float(strength_txt)
            except ValueError:
                pass
        return AgentConfig(
            label=self.label.text().replace("<b>", "").replace("</b>", ""),
            provider=self.provider_combo.currentText(),
            model=self.model_combo.currentText(),
            prompt=self.prompt_edit.toPlainText().strip(),
            images=self.images_spin.value(),
            size=self.size_edit.text().strip() or "1024x1024",
            seed=int(seed_txt) if seed_txt.isdigit() else None,
            strength=params.get("strength"),
            provider_params=params,
        )

    # --- live status -------------------------------------------------------
    def begin_run(self) -> None:
        self._expected = self.images_spin.value()
        self._done = 0
        self.progress.setRange(0, self._expected)
        self.progress.setValue(0)
        self.set_status(f"waiting (0/{self._expected})")

    def tick(self, ok: bool = True) -> None:
        self._done += 1
        self.progress.setValue(min(self._done, self._expected))
        if self._done >= self._expected:
            self.set_status(f"done ({self._done}/{self._expected})")
        else:
            self.set_status(f"running ({self._done}/{self._expected})")

    def set_status(self, text: str) -> None:
        self.status.setText(text)
