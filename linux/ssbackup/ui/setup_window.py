"""First-run setup: one window instead of a chain of prompts."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QVBoxLayout, QWidget,
)

from ..core import naming, steam_config
from .naming_picker import NamingPicker, fit_height
from .theme import Theme
from .widgets import button, edge, header_label, panel, small_label


class SetupWindow(QDialog):
    def __init__(self, default_destination: str, high_res_available: bool,
                 steam_roots: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Steam Screenshot Backup")
        self.setWindowIcon(Theme.app_icon())
        self.setStyleSheet(Theme.stylesheet())
        self.setModal(True)
        self.setFixedWidth(600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ----- header -----
        head = panel(96)
        head_row = QHBoxLayout(head)
        head_row.setContentsMargins(24, 0, 24, 0)
        head_row.setSpacing(16)

        logo = QLabel()
        logo.setPixmap(Theme.app_icon().pixmap(48, 48))
        logo.setFixedSize(48, 48)
        head_row.addWidget(logo)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        t = QLabel("Steam Screenshot Backup")
        t.setObjectName("Title")
        subtitle = QLabel("First-Time Setup")
        subtitle.setStyleSheet(f"color: {Theme.p.accent};")
        titles.addWidget(t)
        titles.addWidget(subtitle)
        head_row.addLayout(titles)
        head_row.addStretch(1)
        layout.addWidget(head)
        layout.addWidget(edge())

        # ----- body -----
        body = QWidget()
        body.setObjectName("Page")
        v = QVBoxLayout(body)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(10)

        intro = QLabel(
            "This app lives in your system tray and automatically copies every "
            "Steam screenshot you take into per-game folders with readable, "
            "sortable names. Click the tray icon at any time to see what it "
            "has been doing.")
        intro.setWordWrap(True)
        v.addWidget(intro)

        found = small_label(
            "Steam found at: " + steam_config.describe_installs(steam_roots))
        found.setWordWrap(True)
        v.addWidget(found)
        v.addSpacing(6)

        v.addWidget(header_label("BACKUP FOLDER"))
        row = QHBoxLayout()
        self._dest = QLineEdit(default_destination)
        browse = button("Browse")
        browse.clicked.connect(self._browse)
        row.addWidget(self._dest, 1)
        row.addWidget(browse)
        v.addLayout(row)
        v.addSpacing(6)

        v.addWidget(header_label("WHAT TO BACK UP"))
        self._standard = QCheckBox(
            "Standard screenshots (Steam's compressed library copies)")
        self._standard.setChecked(True)
        v.addWidget(self._standard)

        self._high_res = QCheckBox(
            'High-resolution screenshots (Steam\'s "save an external copy" files)')
        self._high_res.setChecked(high_res_available)
        v.addWidget(self._high_res)

        note = small_label(
            "A high-resolution screenshot folder was found in your Steam settings."
            if high_res_available else
            "Steam's external-copy option looks disabled; you can enable this "
            "later in Settings.")
        note.setWordWrap(True)
        note.setContentsMargins(22, 0, 0, 0)
        v.addWidget(note)
        v.addSpacing(6)

        v.addWidget(header_label("FILE NAMES"))
        self._naming = NamingPicker(naming.DEFAULT_PRESET)
        v.addWidget(self._naming)
        v.addSpacing(6)

        self._auto_start = QCheckBox("Start automatically when I log in")
        self._auto_start.setChecked(True)
        v.addWidget(self._auto_start)

        layout.addWidget(body, 1)

        # ----- footer -----
        layout.addWidget(edge())
        foot = panel(64)
        foot_row = QHBoxLayout(foot)
        foot_row.setContentsMargins(24, 0, 24, 0)
        foot_row.addStretch(1)
        go = button("Start Backing Up", primary=True)
        go.setDefault(True)
        go.clicked.connect(self.accept)
        foot_row.addWidget(go)
        layout.addWidget(foot)

        fit_height(self)

    # ---------------------------------------------------------------- values

    @property
    def destination(self) -> str:
        return os.path.expanduser(self._dest.text().strip())

    @property
    def auto_start(self) -> bool:
        return self._auto_start.isChecked()

    @property
    def backup_standard(self) -> bool:
        return self._standard.isChecked()

    @property
    def backup_high_res(self) -> bool:
        return self._high_res.isChecked()

    @property
    def file_name_preset(self) -> str:
        return self._naming.preset_key

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose the folder where screenshots will be backed up",
            self._dest.text() or str(Path.home()))
        if chosen:
            self._dest.setText(chosen)
