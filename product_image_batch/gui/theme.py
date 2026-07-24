"""Sleek dark theme for the PySide6 desktop app.

Mirrors the web UI: near-black background, subtle panels, an indigo/violet accent,
rounded corners and a gradient on primary buttons (those with objectName
``"primary"``). Applied once at startup via :func:`apply_theme`.
"""

from __future__ import annotations

# --- palette (kept in sync with web/static/style.css) ----------------------
# Palette matched to dennisbf.design (violet -> periwinkle-blue on dark navy).
BG = "#0a0c15"
BG_2 = "#0e111c"
PANEL = "#141824"
PANEL_2 = "#181d2b"
BORDER = "#262b3a"
BORDER_STRONG = "#333b50"
TEXT = "#eef0f6"
MUTED = "#8a93a8"
ACCENT = "#8b9cf5"
ACCENT_2 = "#9b7ef2"
FIELD = "#121622"

QSS = f"""
* {{
    color: {TEXT};
    font-size: 13px;
    outline: none;
}}
QWidget {{ background: {BG}; }}
QMainWindow, QDialog {{ background: {BG}; }}

QLabel {{ background: transparent; color: {TEXT}; }}
QLabel[muted="true"] {{ color: {MUTED}; }}

/* Toolbar */
QToolBar {{
    background: {BG_2};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 8px;
    spacing: 6px;
}}
QToolBar QToolButton {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 6px 12px;
    color: {TEXT};
}}
QToolBar QToolButton:hover {{ border-color: {BORDER_STRONG}; background: {PANEL}; }}
QToolBar QToolButton:pressed {{ background: {BG_2}; }}

/* Tabs */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 12px;
    top: -1px;
    background: {BG};
}}
QTabBar::tab {{
    background: {PANEL_2};
    color: {MUTED};
    border: 1px solid {BORDER};
    border-bottom: none;
    padding: 8px 16px;
    margin-right: 4px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    background: {PANEL};
    border-color: {BORDER_STRONG};
}}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::close-button {{
    image: none;
    subcontrol-position: right;
}}

/* Buttons */
QPushButton {{
    background: {PANEL_2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 7px 14px;
    font-weight: 500;
}}
QPushButton:hover {{ border-color: {BORDER_STRONG}; background: {PANEL}; }}
QPushButton:pressed {{ background: {BG_2}; }}
QPushButton:disabled {{ color: {MUTED}; background: {PANEL_2}; }}

QPushButton#primary {{
    border: none;
    color: white;
    font-weight: 600;
    padding: 8px 18px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #9b7ef2, stop:0.5 #8b7ff2, stop:1 #7aa8ff);
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #a78ff5, stop:0.5 #9a8ff5, stop:1 #8fb6ff);
}}
QPushButton#primary:disabled {{ background: {PANEL_2}; color: {MUTED}; }}

/* Inputs */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {FIELD};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 6px 9px;
    selection-background-color: {ACCENT};
    selection-color: white;
}}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QSpinBox:hover,
QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {BORDER_STRONG}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit::placeholder {{ color: {MUTED}; }}

QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {PANEL};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    selection-background-color: {ACCENT};
    selection-color: white;
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; border: none; background: {PANEL_2}; }}

/* Frames / cards (agent rows, thumbnails) */
QFrame[frameShape="6"], QFrame[frameShape="5"] {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

/* Group boxes (settings) */
QGroupBox {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 12px;
    margin-top: 14px;
    padding: 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {MUTED};
}}

/* Checkboxes */
QCheckBox {{ color: {TEXT}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {BORDER_STRONG}; background: {FIELD};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

/* Progress bar */
QProgressBar {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    height: 8px;
    text-align: center;
    color: {MUTED};
    font-size: 11px;
}}
QProgressBar::chunk {{
    border-radius: 7px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #9b7ef2, stop:1 #7aa8ff);
}}

/* Scroll areas + bars */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 6px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 6px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* Status bar */
QStatusBar {{ background: {BG_2}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; border-radius: 6px; padding: 4px 8px; }}
"""


def apply_theme(app) -> None:
    """Apply the Fusion base + dark palette + QSS to a QApplication."""
    try:
        from PySide6.QtGui import QColor, QPalette
    except Exception:  # noqa: BLE001
        app.setStyleSheet(QSS)
        return

    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor(FIELD))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(PANEL_2))
    pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor(PANEL_2))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(PANEL))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(MUTED))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
