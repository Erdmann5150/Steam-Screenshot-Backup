"""Granular deletion.

A checkbox tree (backup type -> game -> file) so the user can pick exactly
which files to remove, with a file count on every node and a mandatory
count+size confirmation before anything is moved to the trash.  Covers both the
backup copies and Steam's own originals.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core.backup_engine import ScreenshotType, format_bytes, type_label
from .theme import Theme
from .widgets import (
    MessageDialog, ProgressDialog, button, edge, header_label, panel, small_label,
)


class TargetedDeleteWindow(QDialog):
    @staticmethod
    def show_window(engine, parent=None) -> None:
        TargetedDeleteWindow(engine, parent).exec()

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._cascading = False

        self.setWindowTitle("Granular Deletion")
        self.setWindowIcon(Theme.app_icon())
        self.setStyleSheet(Theme.stylesheet())
        self.setModal(True)
        self.resize(700, 620)
        self.setMinimumSize(520, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top = panel(48)
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(14, 0, 14, 0)
        top_row.addWidget(header_label("Choose Files to Delete"))
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

        self._populate()

    def _build_bottom(self) -> QWidget:
        bar = panel(60)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(10)

        self._summary = small_label("Nothing selected")
        row.addWidget(self._summary)
        row.addStretch(1)

        self._delete_btn = button("Delete Selected", primary=True)
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._delete_selected)
        row.addWidget(self._delete_btn)

        close = button("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        return bar

    # -------------------------------------------------------------- populate

    def _populate(self) -> None:
        self._tree.blockSignals(True)
        self._tree.clear()
        self._add_type_nodes(self._engine.get_backup_tree(), type_label)
        self._add_type_nodes(
            self._engine.get_steam_source_tree(),
            lambda t: f"Steam Screenshots — {type_label(t)}")
        self._tree.blockSignals(False)
        self._update_summary()

    def _add_type_nodes(self, by_type: dict, label_fn) -> None:
        for t in (ScreenshotType.STANDARD, ScreenshotType.HIGH_RES):
            by_game = by_type.get(t) or {}
            if not by_game:
                continue

            type_node = QTreeWidgetItem([""])
            type_node.setFlags(type_node.flags() | Qt.ItemIsUserCheckable)
            type_node.setCheckState(0, Qt.Unchecked)
            type_files = 0

            for game in sorted(by_game, key=str.lower):
                files = by_game[game]
                total = sum(f.size for f in files)
                game_node = QTreeWidgetItem(
                    [f"{game}  ({len(files)})  ·  {format_bytes(total)}"])
                game_node.setFlags(game_node.flags() | Qt.ItemIsUserCheckable)
                game_node.setCheckState(0, Qt.Unchecked)
                for f in files:
                    child = QTreeWidgetItem(
                        [f"{f.name}  ({format_bytes(f.size)})"])
                    child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                    child.setCheckState(0, Qt.Unchecked)
                    child.setData(0, Qt.UserRole, f)
                    child.setToolTip(0, f.path)
                    game_node.addChild(child)
                type_node.addChild(game_node)
                type_files += len(files)

            type_node.setText(0, f"{label_fn(t)}  ({type_files})")
            self._tree.addTopLevelItem(type_node)

    # -------------------------------------------------------------- checking

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._cascading or column != 0:
            return
        self._cascading = True
        _check_all_children(item, item.checkState(0))
        _sync_ancestors(item.parent())
        self._cascading = False
        self._update_summary()

    def _checked_files(self) -> list:
        out = []

        def walk(node: QTreeWidgetItem) -> None:
            for i in range(node.childCount()):
                child = node.child(i)
                data = child.data(0, Qt.UserRole)
                if child.checkState(0) == Qt.Checked and data is not None:
                    out.append(data)
                walk(child)

        for i in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(i))
        return out

    def _checked_folder_count(self) -> int:
        """A per-game node counts as selected only when every file under it is
        checked - the case that actually means "this whole folder goes"."""
        count = 0
        for i in range(self._tree.topLevelItemCount()):
            type_node = self._tree.topLevelItem(i)
            for j in range(type_node.childCount()):
                game_node = type_node.child(j)
                if game_node.childCount() > 0 and _all_checked(game_node):
                    count += 1
        return count

    def _update_summary(self) -> None:
        files = self._checked_files()
        total = sum(f.size for f in files)
        folders = self._checked_folder_count()

        self._summary.setText(
            "Nothing selected" if not files else
            f"{folders} folder{'' if folders == 1 else 's'}, "
            f"{len(files)} file{'' if len(files) == 1 else 's'} selected  "
            f"·  {format_bytes(total)}")
        self._delete_btn.setText(
            f"Delete Selected ({len(files)})" if files else "Delete Selected")
        self._delete_btn.setEnabled(bool(files))

    # -------------------------------------------------------------- deleting

    def _delete_selected(self) -> None:
        files = self._checked_files()
        if not files:
            return
        total = sum(f.size for f in files)
        if not MessageDialog.confirm_deletion(
                f"Delete {len(files)} selected file"
                f"{'' if len(files) == 1 else 's'}?",
                len(files), total, parent=self):
            return

        backup_paths = [f.path for f in files if not f.is_source]
        source_paths = [f.path for f in files if f.is_source]
        engine = self._engine

        def work(progress):
            total_count = len(backup_paths) + len(source_paths)
            if backup_paths:
                engine.delete_files(
                    backup_paths, lambda d, _t: progress(d, total_count))
            offset = len(backup_paths)
            if source_paths:
                engine.delete_files(
                    source_paths,
                    lambda d, _t: progress(offset + d, total_count),
                    "Steam screenshot")

        ProgressDialog.run(self, "Deleting Selected Files…",
                           "Moving selected files to the trash…", work)
        self._populate()


def _check_all_children(node: QTreeWidgetItem, state) -> None:
    for i in range(node.childCount()):
        child = node.child(i)
        child.setCheckState(0, state)
        _check_all_children(child, state)


def _sync_ancestors(node: QTreeWidgetItem | None) -> None:
    """A parent's checkbox mirrors its children: fully checked once every child
    is, and cleared as soon as one isn't - otherwise checking individual files
    leaves the game/type row out of sync with reality."""
    while node is not None:
        node.setCheckState(
            0, Qt.Checked if node.childCount() > 0 and _all_checked(node)
            else Qt.Unchecked)
        node = node.parent()


def _all_checked(node: QTreeWidgetItem) -> bool:
    for i in range(node.childCount()):
        if node.child(i).checkState(0) != Qt.Checked:
            return False
    return True
