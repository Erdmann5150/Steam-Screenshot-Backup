"""Choosing a file-naming preset, and renaming existing backups to match.

Shared by first-run setup, Settings, and the one-time prompt shown to installs
that predate naming presets, so all three describe the choices identically.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from ..core import naming
from .preview_window import PreviewWindow
from .theme import Theme
from .widgets import MessageDialog, ProgressDialog, button, edge, panel, small_label


def fit_height(dialog: QDialog) -> None:
    """Sizes a fixed-width dialog to the height its layout really needs.
    adjustSize() alone ignores word-wrapped labels' height-for-width, which
    leaves the rows squeezed into each other."""
    dialog.adjustSize()
    needed = dialog.layout().totalHeightForWidth(dialog.width())
    if needed > dialog.height():
        dialog.resize(dialog.width(), needed)


class NamingPicker(QWidget):
    """A preset dropdown with a live example name and a one-line explanation."""

    changed = Signal()

    def __init__(self, current: str | None, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        self._box = QComboBox()
        self._box.setFixedWidth(280)
        for p in naming.PRESETS:
            self._box.addItem(p.label, p.key)
        v.addWidget(self._box)

        self._example = QLabel()
        self._example.setContentsMargins(22, 0, 0, 0)
        self._example.setTextFormat(Qt.RichText)
        v.addWidget(self._example)

        self._description = small_label("")
        self._description.setWordWrap(True)
        self._description.setContentsMargins(22, 0, 0, 0)
        # Room for the longest description up front, so switching presets
        # never needs a fixed-width dialog to grow and squeezes nothing.
        self._description.setMinimumHeight(
            self._description.fontMetrics().lineSpacing() * 2 + 2)
        v.addWidget(self._description)

        self.set_preset_key(current)
        self._box.currentIndexChanged.connect(self._on_changed)

    @property
    def preset_key(self) -> str:
        return self._box.currentData()

    def set_preset_key(self, key: str | None) -> None:
        key = naming.normalize_preset_key(key)
        index = next((i for i, p in enumerate(naming.PRESETS) if p.key == key), 0)
        self._box.setCurrentIndex(index)
        self._refresh()

    def _on_changed(self, _index: int) -> None:
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        preset = naming.get_preset(self.preset_key)
        sample = naming.example(preset.key)
        self._example.setText(
            f'Example: <span style="font-family: monospace;">{sample}</span>')
        self._description.setText(preset.description)


class NamingPromptWindow(QDialog):
    """One-time question for installs that were set up before naming presets
    existed, so existing users get the same choice new ones do at setup."""

    def __init__(self, current: str | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Steam Screenshot Backup")
        self.setWindowIcon(Theme.app_icon())
        self.setStyleSheet(Theme.stylesheet())
        self.setModal(True)
        self.setFixedWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QWidget()
        body.setObjectName("Page")
        v = QVBoxLayout(body)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(10)

        title = QLabel("Choose how backup files are named")
        title.setObjectName("Title")
        v.addWidget(title)

        intro = QLabel(
            "Backups can now be named in different styles. For example, "
            "\"Newest first\" keeps a batch of screenshots in story order when "
            "you upload them to Discord together. You can change this any time "
            "in Settings → Backup Configuration.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        v.addSpacing(4)

        self._picker = NamingPicker(current)
        v.addWidget(self._picker)
        layout.addWidget(body, 1)

        layout.addWidget(edge())
        foot = panel(64)
        row = QHBoxLayout(foot)
        row.setContentsMargins(24, 0, 24, 0)
        row.addStretch(1)
        ok = button("Continue", primary=True)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        layout.addWidget(foot)

        fit_height(self)

    @property
    def preset_key(self) -> str:
        return self._picker.preset_key


def offer_rename(engine, settings, new_preset: str, parent=None) -> int:
    """After a naming change: offer to rename the files already backed up.

    Declining is safe - the engine recognizes every naming style, so the old
    names are never mistaken for missing files and re-copied - it just leaves
    folders with a mix of styles.  Returns the number of files renamed.
    """
    plan = engine.plan_rename(new_preset)
    if not plan:
        return 0

    label = naming.get_preset(new_preset).label
    count = f"{len(plan)} existing backup file{'' if len(plan) == 1 else 's'}"
    if settings.PreviewBeforeImport:
        ok = PreviewWindow.confirm(
            "Preview Rename",
            f"{count} will be renamed to the \"{label}\" style "
            "(Cancel keeps their current names):",
            plan, "Rename", parent)
    else:
        old_name = os.path.basename(plan[0][0])
        new_name = os.path.basename(plan[0][1])
        ok = MessageDialog.ask_yes_no(
            f"Rename your {count} to the \"{label}\" style?\n\n"
            f"For example:\n    {old_name}\n→  {new_name}\n\n"
            "Choose No to keep their current names; only screenshots backed up "
            "from now on will use the new style. Either way, nothing is copied "
            "twice.",
            "Rename Existing Backups?", parent)
    if not ok:
        return 0

    return ProgressDialog.run(
        parent, "Renaming Backups…", "Renaming files…",
        lambda progress: engine.rename_backups(new_preset, progress)) or 0
