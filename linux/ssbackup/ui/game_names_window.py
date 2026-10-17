"""Edits the persistent appid -> game name list (appnames.json).

Lets users fix delisted or non-Steam games without touching the file in a text
editor.  Folders that couldn't be named automatically are highlighted at the
top, with a button that opens the actual screenshots so the user can see what
the game is.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ..core import paths
from ..core.logger import Logger
from .theme import Theme
from .widgets import MessageDialog, button, edge, panel


class GameNamesWindow(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._resolver = engine.resolver
        unresolved = engine.find_unresolved_game_folders()
        self._unresolved_ids = {appid for appid, _ in unresolved}

        self.setWindowTitle("Game Names — Steam Screenshot Backup")
        self.setWindowIcon(Theme.app_icon())
        self.setStyleSheet(Theme.stylesheet())
        self.setModal(True)
        self.resize(720, 520)
        self.setMinimumSize(620, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        intro_panel = panel()
        intro_layout = QVBoxLayout(intro_panel)
        intro_layout.setContentsMargins(14, 10, 14, 10)
        intro = QLabel(
            "Fix names for delisted or non-Steam games. Installed games are "
            "named straight from Steam and do not need entries here."
            if not unresolved else
            f"{len(unresolved)} game folder"
            f"{'' if len(unresolved) == 1 else 's'} could not be named "
            'automatically (highlighted below). Select one and click "Open '
            'Folder" to view its screenshots, then type the game\'s name.'
        )
        intro.setWordWrap(True)
        intro.setObjectName("Warn" if unresolved else "Small")
        intro_layout.addWidget(intro)
        layout.addWidget(intro_panel)
        layout.addWidget(edge())

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["App ID", "Game Name"])
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.setColumnWidth(0, 160)
        layout.addWidget(self._table, 1)

        # Unresolved folders first, so they are impossible to miss, each
        # carrying the folder path so Open Folder knows where to go.
        for appid, folder in unresolved:
            self._add_row(appid, "", folder, warn=True)
        for appid, name in self._resolver.get_cached_names().items():
            if appid in self._unresolved_ids:
                continue
            self._add_row(appid, name, None, warn=False)
        self._add_blank_row()

        layout.addWidget(edge())
        layout.addWidget(self._build_footer(bool(unresolved)))

        self._baseline = self._snapshot_rows()
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.currentCellChanged.connect(self._update_open_folder_button)
        self._update_open_folder_button()

        if unresolved:
            self._table.setCurrentCell(0, 1)

    # ---------------------------------------------------------------- footer

    def _build_footer(self, has_unresolved: bool):
        bar = panel(60)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(10)

        remove = button("Remove Selected")
        remove.clicked.connect(self._remove_selected)
        row.addWidget(remove)

        open_file = button("Open Tracking File")
        open_file.clicked.connect(self._open_tracking_file)
        row.addWidget(open_file)

        self._open_folder_btn = button("Open Folder")
        self._open_folder_btn.setEnabled(False)
        self._open_folder_btn.clicked.connect(self._open_folder)
        self._open_folder_btn.setVisible(has_unresolved)
        row.addWidget(self._open_folder_btn)

        row.addStretch(1)

        self._save_btn = button("Save", primary=True)
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_changes)
        row.addWidget(self._save_btn)

        close = button("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        return bar

    # ------------------------------------------------------------ table rows

    def _add_row(self, appid: str, name: str, folder: str | None,
                 warn: bool) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        id_item = QTableWidgetItem(appid)
        name_item = QTableWidgetItem(name)
        if folder:
            id_item.setData(Qt.UserRole, folder)
        if warn:
            brush = QBrush(QColor(Theme.p.warning))
            id_item.setForeground(brush)
            name_item.setForeground(brush)
        self._table.setItem(row, 0, id_item)
        self._table.setItem(row, 1, name_item)

    def _add_blank_row(self) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(""))
        self._table.setItem(row, 1, QTableWidgetItem(""))

    def _on_item_changed(self, _item) -> None:
        # Keep exactly one trailing blank row so there is always somewhere to
        # type a new entry, the way the Windows grid's "new row" behaved.
        last = self._table.rowCount() - 1
        if last >= 0 and (self._cell(last, 0) or self._cell(last, 1)):
            self._table.blockSignals(True)
            self._add_blank_row()
            self._table.blockSignals(False)
        self._save_btn.setEnabled(self._snapshot_rows() != self._baseline)

    def _cell(self, row: int, col: int) -> str:
        item = self._table.item(row, col)
        return item.text().strip() if item else ""

    def _snapshot_rows(self) -> set[tuple[str, str]]:
        """One (id, name) pair per non-blank row, so two states can be compared
        regardless of row order."""
        out = set()
        for row in range(self._table.rowCount()):
            appid, name = self._cell(row, 0), self._cell(row, 1)
            if not appid and not name:
                continue
            out.add((appid, name))
        return out

    def _remove_selected(self) -> None:
        rows = sorted({i.row() for i in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            if row < self._table.rowCount():
                self._table.removeRow(row)
        if self._table.rowCount() == 0:
            self._add_blank_row()
        self._save_btn.setEnabled(self._snapshot_rows() != self._baseline)

    # --------------------------------------------------------------- actions

    def _update_open_folder_button(self, *_args) -> None:
        row = self._table.currentRow()
        folder = None
        if 0 <= row < self._table.rowCount():
            item = self._table.item(row, 0)
            folder = item.data(Qt.UserRole) if item else None
        self._open_folder_btn.setEnabled(bool(folder))

    def _open_folder(self) -> None:
        row = self._table.currentRow()
        item = self._table.item(row, 0) if row >= 0 else None
        folder = item.data(Qt.UserRole) if item else None
        if not folder:
            return
        try:
            paths.open_path(folder)
        except Exception as ex:
            Logger.error(f"Could not open folder: {ex}")
            MessageDialog.fail(f"Could not open that folder:\n{ex}", parent=self)

    def _open_tracking_file(self) -> None:
        path = self._resolver.cache_file_path
        if not path.is_file():
            MessageDialog.info("No tracking file has been written yet.", parent=self)
            return
        try:
            paths.open_text_file(path)
        except Exception as ex:
            Logger.error(f"Could not open tracking file: {ex}")

    def _save_changes(self) -> None:
        edited: dict[str, str] = {}
        for row in range(self._table.rowCount()):
            appid, name = self._cell(row, 0), self._cell(row, 1)
            if not appid and not name:
                continue
            if not name and appid in self._unresolved_ids:
                continue   # not identified yet; leave it unresolved
            if not appid.isdigit():
                MessageDialog.info(
                    f'"{appid}" is not a valid App ID (numbers only).', parent=self)
                return
            if not name:
                MessageDialog.info(f"App ID {appid} needs a game name.", parent=self)
                return
            edited[appid] = name

        current = self._resolver.get_cached_names()
        for key in [k for k in current if k not in edited]:
            self._resolver.remove_cached_name(key)
        for appid, name in edited.items():
            if current.get(appid) != name:
                self._resolver.set_cached_name(appid, name)

        Logger.log("Game name list updated.")
        self.accept()
