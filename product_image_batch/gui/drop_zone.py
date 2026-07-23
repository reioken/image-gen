"""Reference-image (and mask) drop zones with drag & drop + browse fallback."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.utils import images as imgutil

ACCEPTED = imgutil.ACCEPTED_SUFFIXES


class _Thumb(QFrame):
    """A single reference thumbnail with a remove (x) button."""

    removed = Signal(object)  # emits self

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        pic = QLabel()
        pm = QPixmap(str(path))
        if not pm.isNull():
            pic.setPixmap(pm.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(pic)
        name = QLabel(path.name)
        name.setMaximumWidth(110)
        name.setWordWrap(True)
        lay.addWidget(name)
        rm = QPushButton("✕ remove")
        rm.clicked.connect(lambda: self.removed.emit(self))
        lay.addWidget(rm)


class ReferenceImageDropZone(QWidget):
    """Accepts image files via drag & drop or a browse button.

    Emits :attr:`changed` whenever the set of reference paths changes.
    """

    changed = Signal()

    def __init__(self, title: str = "Reference images", single: bool = False) -> None:
        super().__init__()
        self.single = single
        self._paths: list[Path] = []
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        self._title = QLabel(title)
        header.addWidget(self._title)
        header.addStretch(1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        header.addWidget(browse)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear)
        header.addWidget(clear)
        root.addLayout(header)

        self._hint = QLabel("Drag product images here (png / jpg / jpeg / webp)")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet(
            "QLabel { border: 2px dashed #888; border-radius: 8px; padding: 18px; color:#888; }"
        )
        root.addWidget(self._hint)

        self._thumbs_host = QWidget()
        self._thumbs = QHBoxLayout(self._thumbs_host)
        self._thumbs.setAlignment(Qt.AlignmentFlag.AlignLeft)
        root.addWidget(self._thumbs_host)

    # --- data --------------------------------------------------------------
    def paths(self) -> list[Path]:
        return list(self._paths)

    def set_paths(self, paths: list[Path]) -> None:
        self._paths = []
        for p in paths:
            self._add_path(Path(p), emit=False)
        self._rebuild()
        self.changed.emit()

    def clear(self) -> None:
        self._paths.clear()
        self._rebuild()
        self.changed.emit()

    def _add_path(self, path: Path, emit: bool = True) -> None:
        if path.suffix.lower() not in ACCEPTED:
            return
        try:
            imgutil.validate_reference(path)
        except imgutil.ImageValidationError:
            return
        if self.single:
            self._paths = [path]
        elif str(path.resolve()) not in {str(p.resolve()) for p in self._paths}:
            self._paths.append(path)
        if emit:
            self._rebuild()
            self.changed.emit()

    def _rebuild(self) -> None:
        while self._thumbs.count():
            item = self._thumbs.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for p in self._paths:
            thumb = _Thumb(p)
            thumb.removed.connect(self._remove_thumb)
            self._thumbs.addWidget(thumb)
        self._hint.setVisible(not self._paths)

    def _remove_thumb(self, thumb: _Thumb) -> None:
        self._paths = [p for p in self._paths if p != thumb.path]
        self._rebuild()
        self.changed.emit()

    def _browse(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select reference images", "",
            "Images (*.png *.jpg *.jpeg *.webp)"
        )
        for f in files:
            self._add_path(Path(f), emit=False)
        self._rebuild()
        self.changed.emit()

    # --- drag & drop -------------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        changed = False
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.suffix.lower() in ACCEPTED:
                self._add_path(p, emit=False)
                changed = True
        if changed:
            self._rebuild()
            self.changed.emit()
        event.acceptProposedAction()
