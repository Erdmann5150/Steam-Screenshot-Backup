"""Shared look-and-feel for every window.

The same two Steam-inspired palettes the Windows app uses, so the two installs
look like the same product.  "System" follows the desktop's colour scheme,
which Qt 6.5+ reports natively on both Plasma and GNOME.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap

from ..core.settings import ThemeMode


class _Palette:
    def __init__(self, dark: bool):
        self.dark = dark

    def _pick(self, d: str, l: str) -> str:
        return d if self.dark else l

    # Matching Theme.cs exactly.
    @property
    def background(self):  return self._pick("#161d25", "#f4f7fa")
    @property
    def row_alt(self):     return self._pick("#1b232d", "#ecf0f4")
    @property
    def panel(self):       return self._pick("#202934", "#ffffff")
    @property
    def panel_edge(self):  return self._pick("#354252", "#d0d8e0")
    @property
    def text(self):        return self._pick("#d6e2eb", "#1a2632")
    @property
    def text_dim(self):    return self._pick("#7e8f9e", "#6c7a88")
    @property
    def accent(self):      return self._pick("#66c0f4", "#166a9e")
    @property
    def accent_dark(self): return self._pick("#1c5274", "#166a9e")
    @property
    def selection(self):   return self._pick("#1c5274", "#cbe4f5")
    @property
    def warning(self):     return self._pick("#e9b95b", "#9e6a0a")
    @property
    def error(self):       return self._pick("#e86a64", "#b82a24")
    @property
    def success(self):     return self._pick("#81c995", "#16803d")

    @property
    def hover(self):       return self._pick("#2a3644", "#e4eaf0")


class _Theme(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._mode = ThemeMode.DARK
        self._palette = _Palette(True)

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    @property
    def is_dark(self) -> bool:
        if self._mode == ThemeMode.DARK:
            return True
        if self._mode == ThemeMode.LIGHT:
            return False
        return self._system_prefers_dark()

    @staticmethod
    def _system_prefers_dark() -> bool:
        try:
            hints = QGuiApplication.styleHints()
            scheme = hints.colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return True
            if scheme == Qt.ColorScheme.Light:
                return False
        except Exception:
            pass
        # Unknown: fall back to the window colour the platform theme reports.
        try:
            c = QGuiApplication.palette().window().color()
            return (c.red() + c.green() + c.blue()) / 3 < 128
        except Exception:
            return True

    @property
    def p(self) -> _Palette:
        return self._palette

    def set_mode(self, mode: ThemeMode) -> None:
        self._mode = mode
        self._refresh_palette()
        self.changed.emit()

    def refresh_from_system(self) -> None:
        """Called when the desktop's colour scheme changes while we're set to
        follow it."""
        if self._mode != ThemeMode.SYSTEM:
            return
        self._refresh_palette()
        self.changed.emit()

    def _refresh_palette(self) -> None:
        self._palette = _Palette(self.is_dark)

    # ------------------------------------------------------------ stylesheet

    def stylesheet(self) -> str:
        p = self.p
        return f"""
QWidget {{
    background-color: {p.background};
    color: {p.text};
    font-size: 10pt;
}}
QDialog, QMainWindow {{ background-color: {p.background}; }}

QFrame#Panel  {{ background-color: {p.panel}; border: none; }}
QFrame#Edge   {{ background-color: {p.panel_edge}; border: none; max-height: 1px;
                 min-height: 1px; }}
QFrame#VEdge  {{ background-color: {p.panel_edge}; border: none; max-width: 1px;
                 min-width: 1px; }}
QWidget#Page  {{ background-color: {p.background}; }}

QLabel          {{ background: transparent; }}
QLabel#Dim      {{ color: {p.text_dim}; }}
QLabel#Header   {{ color: {p.text_dim}; font-weight: 600; font-size: 9pt; }}
QLabel#Title    {{ color: {p.text}; font-weight: 600; font-size: 14pt; }}
QLabel#Stat     {{ color: {p.text}; font-weight: 600; font-size: 15pt; }}
QLabel#StatAccent {{ color: {p.accent}; font-weight: 600; font-size: 15pt; }}
QLabel#Danger   {{ color: {p.error}; font-weight: 600; font-size: 9pt; }}
QLabel#Warn     {{ color: {p.warning}; }}
QLabel#Small    {{ color: {p.text_dim}; font-size: 9pt; }}

QPushButton {{
    background-color: {p.panel};
    color: {p.text};
    border: 1px solid {p.panel_edge};
    border-radius: 4px;
    padding: 6px 14px;
    min-height: 20px;
}}
QPushButton:hover    {{ background-color: {p.hover}; }}
QPushButton:pressed  {{ background-color: {p.selection}; }}
QPushButton:disabled {{ color: {p.text_dim}; border-color: {p.panel_edge};
                        background-color: {p.background}; }}

QPushButton#Primary {{
    background-color: {p.accent_dark};
    color: {'#ffffff' if not p.dark else p.text};
    border: 1px solid {p.accent};
}}
QPushButton#Primary:hover    {{ background-color: {p.accent}; color: #0b1016; }}
QPushButton#Primary:disabled {{ background-color: {p.background};
                                color: {p.text_dim}; border-color: {p.panel_edge}; }}

QPushButton#Danger {{ color: {p.error}; }}
QPushButton#Warned {{ border: 2px solid {p.warning}; }}
QPushButton#Paused {{ border: 2px solid {p.error}; }}

QPushButton#Tab {{
    background-color: {p.panel};
    color: {p.text_dim};
    border: none;
    border-radius: 0px;
    padding: 12px 18px;
}}
QPushButton#Tab:hover   {{ background-color: {p.selection}; }}
QPushButton#Tab:checked {{ color: {p.text};
                           border-bottom: 2px solid {p.accent}; }}

QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {p.panel};
    color: {p.text};
    border: 1px solid {p.panel_edge};
    border-radius: 4px;
    padding: 5px 8px;
    selection-background-color: {p.selection};
    selection-color: {p.text};
}}
QLineEdit:focus {{ border-color: {p.accent}; }}
QLineEdit:disabled {{ color: {p.text_dim}; }}

QComboBox {{
    background-color: {p.panel};
    color: {p.text};
    border: 1px solid {p.panel_edge};
    border-radius: 4px;
    padding: 5px 8px;
    min-height: 20px;
}}
QComboBox:hover {{ border-color: {p.accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {p.text_dim};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {p.panel};
    color: {p.text};
    border: 1px solid {p.panel_edge};
    selection-background-color: {p.selection};
    selection-color: {p.text};
    outline: none;
}}

QCheckBox {{ background: transparent; spacing: 8px; padding: 2px 0px; }}
QCheckBox#DangerCheck {{ color: {p.error}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {p.panel_edge};
    border-radius: 3px;
    background-color: {p.panel};
}}
QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{
    background-color: {p.accent};
    border-color: {p.accent};
}}
QCheckBox::indicator:disabled {{ background-color: {p.background}; }}

QTreeWidget, QTreeView, QTableWidget, QTableView, QListWidget {{
    background-color: {p.background};
    alternate-background-color: {p.row_alt};
    color: {p.text};
    border: none;
    outline: none;
    selection-background-color: {p.selection};
    selection-color: {p.text};
}}
QTreeWidget::item, QTableWidget::item {{ padding: 4px 2px; }}
QTreeWidget::item:selected, QTableWidget::item:selected,
QTreeView::item:selected {{
    background-color: {p.selection};
    color: {p.text};
}}
QTreeView::branch {{ background: transparent; }}

QHeaderView::section {{
    background-color: {p.panel};
    color: {p.text_dim};
    border: none;
    border-bottom: 1px solid {p.panel_edge};
    padding: 6px 8px;
    font-weight: 600;
    font-size: 9pt;
}}
QTableCornerButton::section {{ background-color: {p.panel}; border: none; }}

QScrollBar:vertical {{
    background: {p.background}; width: 12px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p.panel_edge}; border-radius: 6px; min-height: 28px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_dim}; }}
QScrollBar:horizontal {{
    background: {p.background}; height: 12px; margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {p.panel_edge}; border-radius: 6px; min-width: 28px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p.text_dim}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QMenu {{
    background-color: {p.panel};
    color: {p.text};
    border: 1px solid {p.panel_edge};
    padding: 4px;
}}
QMenu::item {{ padding: 6px 26px 6px 22px; border-radius: 3px; }}
QMenu::item:selected {{ background-color: {p.selection}; }}
QMenu::item:disabled {{ color: {p.text_dim}; }}
QMenu::separator {{ height: 1px; background: {p.panel_edge}; margin: 4px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; margin-left: 5px; }}

QToolTip {{
    background-color: {p.panel};
    color: {p.text};
    border: 1px solid {p.panel_edge};
    padding: 4px 6px;
}}

QProgressBar {{
    background-color: {p.panel};
    border: 1px solid {p.panel_edge};
    border-radius: 4px;
    text-align: center;
    color: {p.text};
    height: 18px;
}}
QProgressBar::chunk {{ background-color: {p.accent}; border-radius: 3px; }}

QScrollArea {{ border: none; background: {p.background}; }}
QScrollArea > QWidget > QWidget {{ background: {p.background}; }}
"""

    # ------------------------------------------------------------- level hues

    def level_color(self, level_name: str) -> QColor:
        p = self.p
        return QColor({
            "Backup": p.accent,
            "Restore": p.success,
            "Deletion": p.warning,
            "Warning": p.warning,
            "Error": p.error,
            "Update": p.accent,
            "Paused": p.warning,
            "Resumed": p.success,
        }.get(level_name, p.text_dim))

    # ----------------------------------------------------------------- icon

    def app_icon(self, size: int = 64) -> QIcon:
        """A simple camera glyph, drawn rather than shipped as a binary so the
        repo stays text-only and the icon follows the theme."""
        icon = QIcon()
        for s in (16, 22, 24, 32, 48, 64, 128):
            icon.addPixmap(self._camera_pixmap(s))
        return icon

    def _camera_pixmap(self, size: int) -> QPixmap:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)

        body = QColor(self.p.accent)
        inner = QColor("#0b1016" if self.p.dark else "#ffffff")

        unit = size / 64.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(body)
        # Camera body with a rounded top bump.
        painter.drawRoundedRect(int(4 * unit), int(18 * unit),
                                int(56 * unit), int(38 * unit),
                                6 * unit, 6 * unit)
        painter.drawRoundedRect(int(20 * unit), int(10 * unit),
                                int(24 * unit), int(12 * unit),
                                3 * unit, 3 * unit)
        # Lens.
        painter.setBrush(inner)
        painter.drawEllipse(int(22 * unit), int(26 * unit),
                            int(20 * unit), int(20 * unit))
        painter.setBrush(body)
        painter.drawEllipse(int(27 * unit), int(31 * unit),
                            int(10 * unit), int(10 * unit))
        painter.end()
        return pm


Theme = _Theme()
