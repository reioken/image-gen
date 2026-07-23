"""Live thumbnail gallery — appends a thumbnail as each image finishes.

Thumbnails are downscaled with Pillow so rendering many results stays smooth;
the original full-resolution file on disk is never modified. Double-clicking a
thumbnail opens the original in the OS image viewer.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.utils.logging import get_logger

log = get_logger(__name__)


class _ClickableThumb(QLabel):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.setToolTip(path.name)
        self.setFixedSize(QSize(132, 132))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("QLabel { border: 1px solid #555; border-radius: 6px; }")
        pm = QPixmap(str(path))
        if not pm.isNull():
            self.setPixmap(
                pm.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self.setText(path.name)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))


class _FlowRow(QWidget):
    """A simple wrapping flow container (row that wraps into new rows)."""

    def __init__(self) -> None:
        super().__init__()
        from PySide6.QtWidgets import QGridLayout

        self._grid = QGridLayout(self)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._count = 0
        self._cols = 6

    def add(self, widget: QWidget) -> None:
        r, c = divmod(self._count, self._cols)
        self._grid.addWidget(widget, r, c)
        self._count += 1

    def clear(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._count = 0


class ThumbnailGallery(QScrollArea):
    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        self._flow = _FlowRow()
        layout.addWidget(self._flow)
        layout.addStretch(1)
        self.setWidget(host)
        self.setMinimumHeight(160)

    def add_image(self, path: Path) -> None:
        try:
            self._flow.add(_ClickableThumb(Path(path)))
        except Exception:  # noqa: BLE001
            log.exception("failed to add thumbnail for %s", path)

    def clear(self) -> None:
        self._flow.clear()
