"""Re-sync missing screenshots.

Finds screenshots that exist in Steam but are missing from the backup (deleted
from it, or not yet copied) and lets the user re-sync them selectively, grouped
by game - the manual complement to automatic restore.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core.backup_engine import format_bytes, type_label
from ..core.logger import Logger
from .theme import Theme
from .widgets import ProgressDialog, button, edge, header_label, panel, small_label


class _Bridge(QObject):
    scanned = Signal(object)


class ResyncWindow(QWidget):
    _instance: "ResyncWindow | None" = None

    @classmethod
    def show_window(cls, engine, parent=None) -> "ResyncWindow":
        if cls._instance is None:
            cls._instance = ResyncWindow(engine)
        w = cls._instance
        w.show()
        w.setWindowState((w.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        w.raise_()
        w.activateWindow()
        return w

    def __init__(self, engine):
        super().__init__()
        self._engine = engine
        self._busy = False
        self._cascading = False
        self._bridge = _Bridge()
        self._bridge.scanned.connect(self._populate)

        self.setWindowTitle("Re-Sync Missing Screenshots")
        self.setWindowIcon(Theme.app_icon())
        self.setStyleSheet(Theme.stylesheet())
        self.resize(680, 600)
        self.setMinimumSize(540, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top = panel(62)
        top_v = QVBoxLayout(top)
        top_v.setContentsMargins(14, 8, 14, 8)
        top_v.setSpacing(2)
        top_v.addWidget(header_label(
            "Screenshots in Steam That Aren't in Your Backup"))
        self._summary = small_label("Scanning…")
        top_v.addWidget(self._summary)
        layout.addWidget(top)
        layout.addWidget(edge())

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QAbstractItemView.NoSelection)
        self._tree.setUniformRowHeights(True)
        self._tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._tree, 1)

        layout.addWidget(edge())
        layout.addWidget(self._build_bottom())

        self._start_scan()

    def _build_bottom(self) -> QWidget:
        bar = panel(60)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(10)

        self._select_all = button("Select All")
        self._select_all.clicked.connect(lambda: self._set_all_checked(True))
        row.addWidget(self._select_all)

        self._select_none = button("Select None")
        self._select_none.clicked.connect(lambda: self._set_all_checked(False))
        row.addWidget(self._select_none)

        self._rescan = button("Rescan")
        self._rescan.clicked.connect(self._start_scan)
        row.addWidget(self._rescan)
        row.addStretch(1)

        self._resync_btn = button("Re-Sync Selected", primary=True)
        self._resync_btn.setEnabled(False)
        self._resync_btn.clicked.connect(self._resync_selected)
        row.addWidget(self._resync_btn)

        close = button("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        return bar

    # -------------------------------------------------------------- scanning

    def _start_scan(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._summary.setText("Scanning…")
        self._tree.clear()

        engine = self._engine

        def work():
            try:
                missing = engine.find_missing_from_backup()
            except Exception as ex:
                Logger.error(f"Re-sync scan failed: {ex}")
                missing = []
            self._bridge.scanned.emit(missing)

        threading.Thread(target=work, name="ResyncScan", daemon=True).start()

    def _populate(self, missing: list) -> None:
        self._tree.blockSignals(True)
        self._tree.clear()

        by_game: dict[str, list] = {}
        for item in missing:
            by_game.setdefault(item.game, []).append(item)

        for game in sorted(by_game, key=str.lower):
            items = sorted(by_game[game], key=lambda i: i.timestamp)
            total = sum(i.size for i in items)
            parent = QTreeWidgetItem(
                [f"{game}  ({len(items)})  ·  {format_bytes(total)}"])
            parent.setFlags(parent.flags() | Qt.ItemIsUserCheckable)
            parent.setCheckState(0, Qt.Unchecked)
            for it in items:
                child = QTreeWidgetItem(
                    [f"{it.display_name}   [{type_label(it.type)}]"])
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Unchecked)
                child.setData(0, Qt.UserRole, it)
                parent.addChild(child)
            self._tree.addTopLevelItem(parent)

        if len(missing) <= 500:
            self._tree.expandAll()   # show items; avoid huge expands
        self._tree.blockSignals(False)

        games = len(by_game)
        self._summary.setText(
            "Your backup is in sync — nothing in Steam is missing from it."
            if not missing else
            f"{len(missing)} screenshot{'' if len(missing) == 1 else 's'} across "
            f"{games} game{'' if games == 1 else 's'} can be re-synced."
        )
        self._set_busy(False)

    # -------------------------------------------------------------- checking

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._cascading or column != 0:
            return
        self._cascading = True
        # Parent toggles all its children.
        if item.childCount() > 0:
            state = item.checkState(0)
            for i in range(item.childCount()):
                item.child(i).setCheckState(0, state)
        elif item.parent() is not None:
            parent = item.parent()
            states = [parent.child(i).checkState(0)
                      for i in range(parent.childCount())]
            parent.setCheckState(
                0, Qt.Checked if all(s == Qt.Checked for s in states) else Qt.Unchecked)
        self._cascading = False
        self._update_resync_button()

    def _set_all_checked(self, value: bool) -> None:
        self._cascading = True
        state = Qt.Checked if value else Qt.Unchecked
        for i in range(self._tree.topLevelItemCount()):
            parent = self._tree.topLevelItem(i)
            parent.setCheckState(0, state)
            for j in range(parent.childCount()):
                parent.child(j).setCheckState(0, state)
        self._cascading = False
        self._update_resync_button()

    def _checked_items(self) -> list:
        out = []
        for i in range(self._tree.topLevelItemCount()):
            parent = self._tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) == Qt.Checked:
                    data = child.data(0, Qt.UserRole)
                    if data is not None:
                        out.append(data)
        return out

    def _update_resync_button(self) -> None:
        n = len(self._checked_items())
        self._resync_btn.setText(
            f"Re-Sync Selected ({n})" if n else "Re-Sync Selected")
        self._resync_btn.setEnabled(not self._busy and n > 0)

    # ------------------------------------------------------------ re-syncing

    def _resync_selected(self) -> None:
        items = self._checked_items()
        if not items:
            return
        engine = self._engine
        ProgressDialog.run(self, "Re-Syncing…", "Copying files…",
                           lambda progress: engine.resync(items, progress))
        self._start_scan()   # refresh - synced items drop off the list

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._rescan.setEnabled(not busy)
        self._select_all.setEnabled(not busy)
        self._select_none.setEnabled(not busy)
        self._update_resync_button()

    def closeEvent(self, event) -> None:
        ResyncWindow._instance = None
        super().closeEvent(event)
