"""A reusable "preview the changes" modal.

Shows a list of Original -> Proposed mappings with Proceed / Cancel.  Used
before batch imports and layout reorganizations so the user can see exactly
what will happen first.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from .theme import Theme
from .widgets import button, edge, header_label, panel, small_label


class PreviewWindow(QDialog):
    @staticmethod
    def confirm(title: str, description: str,
                rows: list[tuple[str, str]],
                proceed_text: str = "Proceed", parent=None) -> bool:
        """Returns True if the user chose Proceed."""
        dlg = PreviewWindow(title, description, rows, proceed_text, parent)
        return dlg.exec() == QDialog.Accepted

    def __init__(self, title: str, description: str,
                 rows: list[tuple[str, str]], proceed_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(Theme.app_icon())
        self.setStyleSheet(Theme.stylesheet())
        self.setModal(True)
        self.resize(980, 620)
        self.setMinimumSize(640, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top = panel(48)
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(14, 0, 14, 0)
        head = header_label(description)
        head.setWordWrap(True)
        top_row.addWidget(head)
        layout.addWidget(top)
        layout.addWidget(edge())

        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels(["Original", "Proposed backup path"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setSelectionMode(QAbstractItemView.NoSelection)
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        tree.header().setSectionsClickable(False)

        tree.setUpdatesEnabled(False)
        items = []
        for src, dest in rows:
            item = QTreeWidgetItem([src, dest])
            item.setToolTip(0, src)
            item.setToolTip(1, dest)
            items.append(item)
        tree.addTopLevelItems(items)
        tree.setUpdatesEnabled(True)
        layout.addWidget(tree, 1)

        layout.addWidget(edge())
        bottom = panel(60)
        row = QHBoxLayout(bottom)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(10)
        row.addWidget(small_label(
            f"{len(rows)} item{'' if len(rows) == 1 else 's'}"))
        row.addStretch(1)

        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)

        proceed = button(proceed_text, primary=True)
        proceed.setDefault(True)
        proceed.clicked.connect(self.accept)
        row.addWidget(proceed)
        layout.addWidget(bottom)
