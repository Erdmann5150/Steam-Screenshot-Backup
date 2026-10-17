"""The main application window.

Live activity feed, backup statistics, and every action that is also available
from the tray menu.
"""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Qt, Signal, QTimer
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QMenu, QStackedLayout, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import __version__
from ..core import paths
from ..core.backup_engine import ScreenshotType, format_bytes, type_label
from ..core.logger import Logger, LogLevel
from .theme import Theme
from .widgets import (
    MessageDialog, ProgressDialog, button, edge, header_label, panel, small_label,
)

FILTERS = [
    ("All activity", None),
    ("Backups", {LogLevel.BACKUP}),
    ("Restores", {LogLevel.RESTORE}),
    ("Deletions", {LogLevel.DELETION}),
    ("Warnings and errors", {LogLevel.WARNING, LogLevel.ERROR}),
    ("Info", {LogLevel.INFO, LogLevel.UPDATE, LogLevel.PAUSED, LogLevel.RESUMED}),
]

MAX_ROWS = 1000


class _Bridge(QObject):
    """Marshals worker-thread callbacks onto the Qt thread."""
    log_added = Signal(object)
    totals_ready = Signal(int, int, int)
    unresolved = Signal(int)


class MainWindow(QMainWindow):
    _instance: "MainWindow | None" = None

    # ------------------------------------------------------------- singleton

    @classmethod
    def show_window(cls, app) -> "MainWindow":
        if cls._instance is None:
            cls._instance = MainWindow(app)
        w = cls._instance
        w.show()
        w.setWindowState(
            (w.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        w.raise_()
        w.activateWindow()
        return w

    @classmethod
    def toggle_window(cls, app) -> None:
        """Left-clicking the tray icon toggles the window: hide it when it's
        up, show/restore it otherwise."""
        w = cls._instance
        if (w is not None and w.isVisible()
                and not w.isMinimized()):
            w.hide()
        else:
            cls.show_window(app)

    # ----------------------------------------------------------------- build

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._unresolved_count = 0
        self._bridge = _Bridge()

        self.setWindowTitle("Steam Screenshot Backup")
        self.setWindowIcon(Theme.app_icon())
        self.resize(970, 620)
        self.setMinimumSize(880, 440)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_action_bar())
        layout.addWidget(edge())
        layout.addWidget(self._build_stats())
        layout.addWidget(edge())
        layout.addWidget(self._build_filter_row())
        layout.addWidget(self._build_list(), 1)
        layout.addWidget(edge())
        layout.addWidget(self._build_bottom_bar())

        self._apply_theme()
        Theme.changed.connect(self._apply_theme)

        # Live updates.
        self._bridge.log_added.connect(self._on_log_added)
        self._bridge.totals_ready.connect(self._on_totals)
        self._bridge.unresolved.connect(self._set_unresolved_count)
        Logger.add_listener(self._bridge.log_added.emit)
        self._app.pause_changed.append(self._on_pause_changed)
        self._app.engine.unresolved_count_changed.append(self._bridge.unresolved.emit)

        # Recompute totals shortly after bursts settle rather than per file.
        self._stats_debounce = QTimer(self)
        self._stats_debounce.setSingleShot(True)
        self._stats_debounce.setInterval(800)
        self._stats_debounce.timeout.connect(self._refresh_totals)

        self._on_pause_changed()
        self._reload()
        self._refresh_session_stat()
        self._refresh_totals()
        self._refresh_unresolved_badge()

    # ------------------------------------------------------------ action bar

    def _build_action_bar(self) -> QWidget:
        bar = panel(60)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(8)

        backup_now = button("Backup Now", primary=True)
        backup_now.clicked.connect(self._app.backup_now)

        open_folder = button("Open Backup Folder")
        open_folder.clicked.connect(self._app.open_backup_folder)

        resync = button("Re-Sync")
        resync.clicked.connect(lambda: self._app.open_resync(self))

        self._pause_btn = button("Pause Monitoring")
        self._pause_btn.clicked.connect(
            lambda: self._app.set_paused(not self._app.is_paused))

        settings = button("Settings")
        settings.clicked.connect(lambda: self._app.show_settings(self))

        self._names_btn = button("Game Names")
        self._names_btn.clicked.connect(self._open_game_names)

        utilities = button("⚙ Utilities")
        utilities.clicked.connect(lambda: self._show_utilities_menu(utilities))

        for b in (backup_now, open_folder, resync, self._pause_btn,
                  settings, self._names_btn, utilities):
            row.addWidget(b)
        row.addStretch(1)
        return bar

    def _open_game_names(self) -> None:
        self._app.open_game_names(self)
        self._refresh_unresolved_badge()   # names may have just been fixed

    # ----------------------------------------------------------- stats strip

    def _build_stats(self) -> QWidget:
        host = QWidget()
        host.setFixedHeight(78)
        row = QHBoxLayout(host)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(0)

        def make(caption: str, accent: bool = False):
            col = QWidget()
            v = QVBoxLayout(col)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            cap = header_label(caption)
            val = QLabel("—")
            val.setObjectName("StatAccent" if accent else "Stat")
            v.addWidget(cap)
            v.addWidget(val)
            row.addWidget(col, 1)
            return val

        self._stat_games = make("GAMES BACKED UP")
        self._stat_files = make("SCREENSHOTS BACKED UP")
        self._stat_session = make("THIS SESSION", accent=True)
        return host

    # ------------------------------------------------------------ filter row

    def _build_filter_row(self) -> QWidget:
        host = QWidget()
        host.setFixedHeight(50)
        row = QHBoxLayout(host)
        row.setContentsMargins(14, 8, 14, 8)

        self._filter = QComboBox()
        self._filter.setFixedWidth(220)
        for label, _ in FILTERS:
            self._filter.addItem(label)
        self._filter.currentIndexChanged.connect(self._reload)
        row.addWidget(self._filter)
        row.addStretch(1)

        self._count = small_label("")
        self._count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self._count)
        return host

    # --------------------------------------------------------- activity list

    def _build_list(self) -> QWidget:
        host = QWidget()
        self._list_stack = QStackedLayout(host)
        self._list_stack.setContentsMargins(0, 0, 0, 0)
        self._list_stack.setStackingMode(QStackedLayout.StackOne)

        self._list = QTreeWidget()
        self._list.setColumnCount(3)
        self._list.setHeaderLabels(["Time", "Event", "Details"])
        self._list.setRootIsDecorated(False)
        self._list.setAlternatingRowColors(True)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._list.setUniformRowHeights(True)
        self._list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._list.itemDoubleClicked.connect(self._reveal_selected_file)
        header = self._list.header()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionsClickable(False)
        self._list.setColumnWidth(0, 160)
        self._list.setColumnWidth(1, 96)

        self._empty = QLabel(
            "Nothing here yet — new activity will appear as it happens.")
        self._empty.setObjectName("Dim")
        self._empty.setAlignment(Qt.AlignCenter)

        self._list_stack.addWidget(self._list)
        self._list_stack.addWidget(self._empty)
        return host

    # ----------------------------------------------------------- bottom bar

    def _build_bottom_bar(self) -> QWidget:
        bar = panel(60)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(10)

        open_log = button("Open Full Log File")
        open_log.clicked.connect(self._open_log_file)
        row.addWidget(open_log)

        hint = small_label(
            "Double-click a backup or restore entry to show the file in your "
            "file manager")
        row.addWidget(hint)
        row.addStretch(1)

        row.addWidget(small_label(f"v{__version__}"))

        close = button("Close")
        close.clicked.connect(self.hide)
        row.addWidget(close)
        return bar

    # ------------------------------------------------------- utilities menu

    def _show_utilities_menu(self, anchor) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(Theme.stylesheet())

        def add(text, fn):
            act = QAction(text, menu)
            act.triggered.connect(fn)
            menu.addAction(act)

        add("Delete Standard Backups",
            lambda: self._delete_type_backups(ScreenshotType.STANDARD))
        add("Delete High-Resolution Backups",
            lambda: self._delete_type_backups(ScreenshotType.HIGH_RES))
        add("Delete Markdown Indexes", self._delete_markdown_indexes)
        add("Delete Standard Original Steam Files",
            lambda: self._delete_imported_originals(ScreenshotType.STANDARD))
        add("Delete High-Resolution Original Steam Files",
            lambda: self._delete_imported_originals(ScreenshotType.HIGH_RES))
        add("Clear Application Logs", self._clear_application_logs)
        menu.addSeparator()
        add("Granular Deletion", lambda: self._app.open_granular_delete(self))
        menu.addSeparator()
        add("Check for Updates Now", lambda: self._app.check_for_updates_now(self))

        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _delete_type_backups(self, t: ScreenshotType) -> None:
        engine = self._app.engine
        label = type_label(t)
        count, total = engine.preview_type_backups(t)
        if not MessageDialog.confirm_deletion(
                f"Delete all {label} backups?", count, total, parent=self):
            return
        ProgressDialog.run(self, "Deleting Backups…",
                           f"Moving {label} backups to the trash…",
                           lambda progress: engine.delete_type_backups(t))
        self._refresh_totals()

    def _delete_markdown_indexes(self) -> None:
        engine = self._app.engine
        count, total = engine.preview_markdown_indexes()
        if not MessageDialog.confirm_deletion(
                "Delete all Markdown index files?", count, total, parent=self):
            return
        ProgressDialog.run(self, "Deleting Index…",
                           "Moving _Screenshot_Log.md files to the trash…",
                           engine.delete_markdown_indexes)

    def _delete_imported_originals(self, t: ScreenshotType) -> None:
        engine = self._app.engine
        label = type_label(t)
        count, total = engine.preview_purge_imported_originals(t)
        if not MessageDialog.confirm_deletion(
                f"Delete original {label} Steam screenshots that are already "
                "backed up?", count, total, parent=self):
            return
        ProgressDialog.run(
            self, "Deleting Originals…",
            f"Moving imported {label} originals to the trash…",
            lambda progress: engine.purge_imported_originals(progress, t))

    def _clear_application_logs(self) -> None:
        count, total = Logger.preview_log_files()
        if not MessageDialog.confirm_deletion(
                "Clear the application log file and its archives?",
                count, total, parent=self):
            return
        Logger.clear_logs()
        self._reload()

    # ----------------------------------------------------------------- stats

    def _refresh_session_stat(self) -> None:
        engine = self._app.engine
        self._stat_session.setText(
            f"{engine.session_files} files  ·  "
            f"{format_bytes(engine.session_bytes)}")

    def _refresh_totals(self) -> None:
        engine = self._app.engine

        def work():
            try:
                games, files, total = engine.compute_totals()
                self._bridge.totals_ready.emit(games, files, total)
            except Exception:
                pass

        threading.Thread(target=work, name="Totals", daemon=True).start()

    def _on_totals(self, games: int, files: int, total: int) -> None:
        self._stat_games.setText(str(games))
        self._stat_files.setText(f"{files}  ·  {format_bytes(total)}")

    # ------------------------------------------------ unresolved-game badge

    def _refresh_unresolved_badge(self) -> None:
        """Recomputes the count directly from disk, for startup and right after
        the Game Names window closes, where waiting for the next background
        scan would leave a just-fixed badge showing stale."""
        engine = self._app.engine

        def work():
            try:
                count = len(engine.find_unresolved_game_folders())
                self._bridge.unresolved.emit(count)
            except Exception:
                pass

        threading.Thread(target=work, name="UnresolvedBadge", daemon=True).start()

    def _set_unresolved_count(self, count: int) -> None:
        self._unresolved_count = count
        self._names_btn.setToolTip(
            f"{count} game folder{'' if count == 1 else 's'} couldn't be named "
            "automatically" if count > 0 else "")
        # The button text stays fixed-width and a notification alone is easy to
        # miss, so an unresolved game swaps the border for a warning-coloured one.
        self._names_btn.setObjectName("Warned" if count > 0 else "")
        self._restyle(self._names_btn)

    def _on_pause_changed(self) -> None:
        paused = self._app.is_paused
        self._pause_btn.setText("Resume Monitoring" if paused else "Pause Monitoring")
        self._pause_btn.setObjectName("Paused" if paused else "")
        self._restyle(self._pause_btn)

    @staticmethod
    def _restyle(widget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    # -------------------------------------------------------------- log list

    def _passes_filter(self, entry) -> bool:
        allowed = FILTERS[self._filter.currentIndex()][1]
        return allowed is None or entry.level in allowed

    def _reload(self) -> None:
        self._list.setUpdatesEnabled(False)
        self._list.clear()
        for entry in Logger.snapshot():
            if self._passes_filter(entry):
                self._list.insertTopLevelItem(0, self._make_item(entry))   # newest first
        self._list.setUpdatesEnabled(True)
        self._update_chrome()

    def _on_log_added(self, entry) -> None:
        self._refresh_session_stat()
        if entry.level in (LogLevel.BACKUP, LogLevel.RESTORE, LogLevel.DELETION):
            self._stats_debounce.start()
        if not self._passes_filter(entry):
            return
        self._list.insertTopLevelItem(0, self._make_item(entry))
        while self._list.topLevelItemCount() > MAX_ROWS:
            self._list.takeTopLevelItem(self._list.topLevelItemCount() - 1)
        self._update_chrome()

    def _make_item(self, entry) -> QTreeWidgetItem:
        item = QTreeWidgetItem([
            entry.time.strftime("%Y-%m-%d %H:%M:%S"),
            entry.level.value,
            entry.message,
        ])
        item.setData(0, Qt.UserRole, entry)
        item.setForeground(0, QBrush(QColor(Theme.p.text_dim)))
        item.setForeground(1, QBrush(Theme.level_color(entry.level.value)))
        if entry.level == LogLevel.ERROR:
            item.setForeground(2, QBrush(QColor(Theme.p.error)))
        else:
            item.setForeground(2, QBrush(QColor(Theme.p.text)))
        return item

    def _update_chrome(self) -> None:
        n = self._list.topLevelItemCount()
        self._count.setText("1 entry" if n == 1 else f"{n} entries")
        self._list_stack.setCurrentIndex(1 if n == 0 else 0)

    def _reveal_selected_file(self) -> None:
        items = self._list.selectedItems()
        if not items:
            return
        entry = items[0].data(0, Qt.UserRole)
        if entry is None:
            return

        # Newer entries carry the path; entries loaded from older log files
        # don't, so fall back to reconstructing it from the message text.
        path = entry.file_path
        if not path and entry.level in (LogLevel.BACKUP, LogLevel.RESTORE,
                                        LogLevel.DELETION):
            path = self._app.engine.backup_path_from_log_message(entry.message)
        if not path:
            return

        try:
            if os.path.exists(path):
                paths.reveal_in_file_manager(path)
            else:
                MessageDialog.info(f"That file no longer exists:\n{path}", parent=self)
        except Exception as ex:
            Logger.error(f"Could not open the file manager: {ex}")

    def _open_log_file(self) -> None:
        try:
            if not Logger.log_file_path.is_file():
                MessageDialog.info("No log file has been written yet.", parent=self)
                return
            paths.open_text_file(Logger.log_file_path)
        except Exception as ex:
            Logger.error(f"Could not open log file: {ex}")

    # --------------------------------------------------------------- theming

    def _apply_theme(self) -> None:
        self.setStyleSheet(Theme.stylesheet())
        self._reload()

    # --------------------------------------------------------------- closing

    def closeEvent(self, event) -> None:
        """Closing hides to the tray rather than quitting, matching Windows."""
        event.ignore()
        self.hide()

    def detach(self) -> None:
        Logger.remove_listener(self._bridge.log_added.emit)
        try:
            self._app.pause_changed.remove(self._on_pause_changed)
        except ValueError:
            pass
        try:
            self._app.engine.unresolved_count_changed.remove(
                self._bridge.unresolved.emit)
        except ValueError:
            pass
