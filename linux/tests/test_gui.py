"""Headless GUI tests.

Every window is really constructed and driven under Qt's offscreen platform, so
these catch the layout, signal and API mistakes that an import check misses.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt                      # noqa: E402
from PySide6.QtWidgets import QApplication          # noqa: E402

from ssbackup.core.app_names import AppNameResolver  # noqa: E402
from ssbackup.core.backup_engine import BackupEngine  # noqa: E402
from ssbackup.core.settings import Settings, ThemeMode  # noqa: E402
from ssbackup.ui.theme import Theme                 # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def gui_engine(steam_tree, fake_home, monkeypatch, qapp):
    settings = Settings.load()
    settings.Destination = str(fake_home / "Backups" / "Steam Screenshots")
    settings.OfflineMode = True
    settings.FirstRunDone = True
    settings.StructureMigrated = True
    settings.save()

    monkeypatch.setattr(AppNameResolver, "_start_refresh_timer", lambda self: None)
    eng = BackupEngine(settings)
    eng.full_scan()
    yield eng, settings
    eng.dispose()


class FakeApp:
    """Stands in for TrayApp so the windows can be tested without a real tray,
    which the offscreen platform does not provide."""

    def __init__(self, engine, settings):
        self.engine = engine
        self._settings = settings
        self.pause_changed = []
        self._paused = False
        self.calls = []

    @property
    def settings(self):
        return self._settings

    @property
    def is_paused(self):
        return self._paused

    def set_paused(self, value):
        self._paused = value
        for fn in self.pause_changed:
            fn()

    def backup_now(self):
        self.calls.append("backup_now")

    def open_backup_folder(self):
        self.calls.append("open_backup_folder")

    def show_settings(self, parent=None):
        self.calls.append("show_settings")

    def open_game_names(self, parent=None):
        self.calls.append("open_game_names")

    def open_resync(self, parent=None):
        self.calls.append("open_resync")

    def open_granular_delete(self, parent=None):
        self.calls.append("open_granular_delete")

    def check_for_updates_now(self, parent=None):
        self.calls.append("check_for_updates")

    def on_settings_changed(self, sources_changed):
        self.calls.append(("on_settings_changed", sources_changed))

    def uninstall(self, parent=None):
        self.calls.append("uninstall")


# ----------------------------------------------------------------- the theme

def test_stylesheet_builds_for_every_mode(qapp):
    for mode in (ThemeMode.DARK, ThemeMode.LIGHT, ThemeMode.SYSTEM):
        Theme.set_mode(mode)
        css = Theme.stylesheet()
        assert "QPushButton" in css
        assert "{{" not in css   # no unescaped f-string braces left behind
        assert "None" not in css
    Theme.set_mode(ThemeMode.DARK)


def test_dark_and_light_palettes_differ(qapp):
    Theme.set_mode(ThemeMode.DARK)
    dark_bg = Theme.p.background
    Theme.set_mode(ThemeMode.LIGHT)
    assert Theme.p.background != dark_bg
    Theme.set_mode(ThemeMode.DARK)


def test_app_icon_renders(qapp):
    icon = Theme.app_icon()
    assert not icon.isNull()
    pm = icon.pixmap(64, 64)
    assert pm.width() == 64 and not pm.isNull()


# ---------------------------------------------------------------- main window

def test_main_window_builds_and_lists_activity(gui_engine, qapp):
    from ssbackup.ui.main_window import MainWindow
    engine, settings = gui_engine
    app = FakeApp(engine, settings)

    w = MainWindow(app)
    assert w.windowTitle() == "Steam Screenshot Backup"
    # The scan in the fixture logged backups, so the feed is populated.
    assert w._list.topLevelItemCount() > 0
    w.detach()
    w.deleteLater()


def test_main_window_filter_narrows_the_feed(gui_engine, qapp):
    from ssbackup.ui.main_window import MainWindow
    engine, settings = gui_engine
    w = MainWindow(FakeApp(engine, settings))

    w._filter.setCurrentIndex(0)
    total = w._list.topLevelItemCount()
    w._filter.setCurrentIndex(1)          # Backups only
    backups = w._list.topLevelItemCount()
    w._filter.setCurrentIndex(3)          # Deletions only
    deletions = w._list.topLevelItemCount()

    assert backups > 0
    assert deletions == 0
    assert backups < total
    w.detach()
    w.deleteLater()


def test_main_window_buttons_fire_actions(gui_engine, qapp):
    """Clicks the real buttons, so a mis-wired signal is caught here."""
    from PySide6.QtWidgets import QPushButton
    from ssbackup.ui.main_window import MainWindow
    engine, settings = gui_engine
    app = FakeApp(engine, settings)
    w = MainWindow(app)

    by_text = {b.text(): b for b in w.findChildren(QPushButton)}
    by_text["Backup Now"].click()
    by_text["Open Backup Folder"].click()
    by_text["Re-Sync"].click()
    by_text["Settings"].click()

    assert "backup_now" in app.calls
    assert "open_backup_folder" in app.calls
    assert "open_resync" in app.calls
    assert "show_settings" in app.calls
    w.detach()
    w.deleteLater()


def test_pause_button_reflects_state(gui_engine, qapp):
    from ssbackup.ui.main_window import MainWindow
    engine, settings = gui_engine
    app = FakeApp(engine, settings)
    w = MainWindow(app)

    assert w._pause_btn.text() == "Pause Monitoring"
    app.set_paused(True)
    assert w._pause_btn.text() == "Resume Monitoring"
    assert w._pause_btn.objectName() == "Paused"
    app.set_paused(False)
    assert w._pause_btn.text() == "Pause Monitoring"
    w.detach()
    w.deleteLater()


def test_unresolved_badge_highlights_game_names(gui_engine, qapp):
    from ssbackup.ui.main_window import MainWindow
    engine, settings = gui_engine
    w = MainWindow(FakeApp(engine, settings))

    w._set_unresolved_count(3)
    assert w._names_btn.objectName() == "Warned"
    assert "3 game folders" in w._names_btn.toolTip()
    w._set_unresolved_count(0)
    assert w._names_btn.objectName() == ""
    w.detach()
    w.deleteLater()


def test_main_window_close_hides_rather_than_quits(gui_engine, qapp):
    from ssbackup.ui.main_window import MainWindow
    engine, settings = gui_engine
    w = MainWindow(FakeApp(engine, settings))
    w.show()
    w.close()
    assert not w.isVisible()
    w.detach()
    w.deleteLater()


# ------------------------------------------------------------ settings window

def test_settings_window_builds(gui_engine, qapp):
    from ssbackup.ui.settings_window import SettingsWindow
    engine, settings = gui_engine
    w = SettingsWindow(FakeApp(engine, settings), settings)

    assert w._dest.text() == settings.Destination
    assert w._standard.isChecked() is settings.BackupStandard
    assert w._apply.isEnabled() is False   # nothing changed yet
    w.deleteLater()


def test_settings_apply_enables_on_change(gui_engine, qapp):
    from ssbackup.ui.settings_window import SettingsWindow
    engine, settings = gui_engine
    w = SettingsWindow(FakeApp(engine, settings), settings)

    w._show_notifications.setChecked(not w._show_notifications.isChecked())
    assert w._apply.isEnabled() is True
    # Toggling back should gray it out again.
    w._show_notifications.setChecked(not w._show_notifications.isChecked())
    assert w._apply.isEnabled() is False
    w.deleteLater()


def test_settings_tabs_switch(gui_engine, qapp):
    from ssbackup.ui.settings_window import SettingsWindow
    engine, settings = gui_engine
    w = SettingsWindow(FakeApp(engine, settings), settings)

    w._select_tab(1)
    assert w._pages.currentIndex() == 1
    assert w._tab_backup.isChecked()
    w._select_tab(0)
    assert w._pages.currentIndex() == 0
    w.deleteLater()


def test_offline_mode_disables_update_check(gui_engine, qapp):
    from ssbackup.ui.settings_window import SettingsWindow
    engine, settings = gui_engine
    w = SettingsWindow(FakeApp(engine, settings), settings)

    w._offline_mode.setChecked(True)
    assert w._check_for_updates.isEnabled() is False
    w._offline_mode.setChecked(False)
    assert w._check_for_updates.isEnabled() is True
    w.deleteLater()


def test_settings_saves_simple_changes(gui_engine, qapp, monkeypatch):
    from ssbackup.ui.settings_window import SettingsWindow
    from ssbackup.ui import settings_window as sw
    engine, settings = gui_engine
    app = FakeApp(engine, settings)
    w = SettingsWindow(app, settings)

    # Nothing here should prompt, but fail loudly if it does.
    monkeypatch.setattr(sw.MessageDialog, "ask_yes_no",
                        lambda *a, **k: pytest.fail("unexpected prompt"))

    w._markdown_index.setChecked(False)
    w._preview_import.setChecked(True)
    w._save_changes()

    assert settings.PreviewBeforeImport is True
    assert w._apply.isEnabled() is False   # baseline recaptured
    assert Settings.load().PreviewBeforeImport is True
    w.deleteLater()


def test_danger_setting_reverts_when_declined(gui_engine, qapp, monkeypatch):
    from ssbackup.ui.settings_window import SettingsWindow
    from ssbackup.ui import settings_window as sw
    engine, settings = gui_engine
    w = SettingsWindow(FakeApp(engine, settings), settings)

    monkeypatch.setattr(sw.MessageDialog, "ask_yes_no", lambda *a, **k: False)
    w._delete_originals.setChecked(True)
    assert w._delete_originals.isChecked() is False
    w.deleteLater()


def test_danger_setting_requires_two_confirmations(gui_engine, qapp, monkeypatch):
    from ssbackup.ui.settings_window import SettingsWindow
    from ssbackup.ui import settings_window as sw
    engine, settings = gui_engine
    w = SettingsWindow(FakeApp(engine, settings), settings)

    seen = []

    def fake_ask(text, title=None, parent=None):
        seen.append(title)
        return True

    monkeypatch.setattr(sw.MessageDialog, "ask_yes_no", fake_ask)
    w._delete_originals.setChecked(True)
    assert len(seen) == 2
    assert w._delete_originals.isChecked() is True
    w.deleteLater()


# ---------------------------------------------------------- game names window

def test_game_names_window_lists_entries(gui_engine, qapp):
    from ssbackup.ui.game_names_window import GameNamesWindow
    engine, settings = gui_engine
    w = GameNamesWindow(engine)

    ids = [w._cell(r, 0) for r in range(w._table.rowCount())]
    assert "1234567" in ids          # the unresolved delisted game
    assert w._save_btn.isEnabled() is False
    w.deleteLater()


def test_game_names_save_enables_on_edit(gui_engine, qapp):
    from PySide6.QtWidgets import QTableWidgetItem
    from ssbackup.ui.game_names_window import GameNamesWindow
    engine, settings = gui_engine
    w = GameNamesWindow(engine)

    row = next(r for r in range(w._table.rowCount()) if w._cell(r, 0) == "1234567")
    w._table.setItem(row, 1, QTableWidgetItem("Some Delisted Game"))
    assert w._save_btn.isEnabled() is True
    w.deleteLater()


def test_game_names_save_writes_the_cache(gui_engine, qapp):
    from PySide6.QtWidgets import QTableWidgetItem
    from ssbackup.ui.game_names_window import GameNamesWindow
    engine, settings = gui_engine
    w = GameNamesWindow(engine)

    row = next(r for r in range(w._table.rowCount()) if w._cell(r, 0) == "1234567")
    w._table.setItem(row, 1, QTableWidgetItem("Some Delisted Game"))
    w._save_changes()

    assert engine.resolver.get_cached_names().get("1234567") == "Some Delisted Game"
    assert engine.resolver.resolve_folder_name("1234567") == "Some Delisted Game"
    w.deleteLater()


def test_game_names_rejects_non_numeric_id(gui_engine, qapp, monkeypatch):
    from PySide6.QtWidgets import QTableWidgetItem
    from ssbackup.ui.game_names_window import GameNamesWindow
    from ssbackup.ui import game_names_window as gnw
    engine, settings = gui_engine
    w = GameNamesWindow(engine)

    messages = []
    monkeypatch.setattr(gnw.MessageDialog, "info",
                        lambda text, *a, **k: messages.append(text))

    last = w._table.rowCount() - 1
    w._table.setItem(last, 0, QTableWidgetItem("not-a-number"))
    w._table.setItem(last, 1, QTableWidgetItem("Whatever"))
    w._save_changes()

    assert messages and "not a valid App ID" in messages[0]
    w.deleteLater()


# -------------------------------------------------------------- resync window

def test_resync_window_reports_in_sync(gui_engine, qapp):
    from ssbackup.ui.resync_window import ResyncWindow
    engine, settings = gui_engine
    w = ResyncWindow(engine)
    w._populate(engine.find_missing_from_backup())

    assert "in sync" in w._summary.text()
    assert w._resync_btn.isEnabled() is False
    w.close()
    w.deleteLater()


def test_resync_window_lists_and_selects_missing(gui_engine, qapp):
    from ssbackup.ui.resync_window import ResyncWindow
    from pathlib import Path
    engine, settings = gui_engine

    shot = (Path(engine.destination) / "Standard" / "Portal 2"
            / "2026-04-12 13.37.15.jpg")
    shot.unlink()

    w = ResyncWindow(engine)
    w._populate(engine.find_missing_from_backup())
    assert w._tree.topLevelItemCount() == 1
    assert "1 screenshot" in w._summary.text()

    w._set_all_checked(True)
    assert len(w._checked_items()) == 1
    assert w._resync_btn.isEnabled() is True
    assert "(1)" in w._resync_btn.text()

    w._set_all_checked(False)
    assert w._checked_items() == []
    w.close()
    w.deleteLater()


def test_resync_parent_check_cascades(gui_engine, qapp):
    from ssbackup.ui.resync_window import ResyncWindow
    from pathlib import Path
    engine, settings = gui_engine

    game_dir = Path(engine.destination) / "Standard" / "Portal 2"
    for f in list(game_dir.glob("*.jpg")):
        f.unlink()

    w = ResyncWindow(engine)
    w._populate(engine.find_missing_from_backup())
    parent = w._tree.topLevelItem(0)
    assert parent.childCount() == 3

    parent.setCheckState(0, Qt.Checked)
    assert len(w._checked_items()) == 3
    w.close()
    w.deleteLater()


# ----------------------------------------------------- granular delete window

def test_granular_delete_builds_tree(gui_engine, qapp):
    from ssbackup.ui.targeted_delete_window import TargetedDeleteWindow
    engine, settings = gui_engine
    w = TargetedDeleteWindow(engine)

    # Standard + High Resolution backups, plus both Steam source trees.
    assert w._tree.topLevelItemCount() == 4
    assert w._summary.text() == "Nothing selected"
    assert w._delete_btn.isEnabled() is False
    w.deleteLater()


def test_granular_delete_selection_summary(gui_engine, qapp):
    from ssbackup.ui.targeted_delete_window import TargetedDeleteWindow
    engine, settings = gui_engine
    w = TargetedDeleteWindow(engine)

    type_node = w._tree.topLevelItem(0)
    game_node = type_node.child(0)
    game_node.setCheckState(0, Qt.Checked)

    files = w._checked_files()
    assert files
    assert "selected" in w._summary.text()
    assert w._delete_btn.isEnabled() is True
    assert f"({len(files)})" in w._delete_btn.text()
    w.deleteLater()


def test_granular_delete_parent_syncs_with_children(gui_engine, qapp):
    from ssbackup.ui.targeted_delete_window import TargetedDeleteWindow
    engine, settings = gui_engine
    w = TargetedDeleteWindow(engine)

    type_node = w._tree.topLevelItem(0)
    game_node = type_node.child(0)
    game_node.setCheckState(0, Qt.Checked)
    assert game_node.checkState(0) == Qt.Checked

    # Unchecking one child must clear the parent, not leave it looking whole.
    game_node.child(0).setCheckState(0, Qt.Unchecked)
    assert game_node.checkState(0) == Qt.Unchecked
    w.deleteLater()


# ------------------------------------------------------------ preview window

def test_preview_window_lists_rows(gui_engine, qapp):
    from PySide6.QtWidgets import QTreeWidget
    from ssbackup.ui.preview_window import PreviewWindow

    rows = [("/from/a.jpg", "/to/a.jpg"), ("/from/b.jpg", "/to/b.jpg")]
    w = PreviewWindow("Preview Import", "2 screenshots will be imported:",
                      rows, "Import")

    tree = w.findChild(QTreeWidget)
    assert tree.topLevelItemCount() == 2
    assert tree.topLevelItem(0).text(0) == "/from/a.jpg"
    assert tree.topLevelItem(0).text(1) == "/to/a.jpg"
    w.deleteLater()


# -------------------------------------------------------------- setup window

def test_setup_window_defaults(gui_engine, qapp, fake_home):
    from ssbackup.ui.setup_window import SetupWindow
    engine, settings = gui_engine
    w = SetupWindow(str(fake_home / "Pictures" / "Steam Screenshots"),
                    True, engine.steam_roots)

    assert w.backup_standard is True
    assert w.backup_high_res is True      # a high-res folder was detected
    assert w.auto_start is True
    assert w.destination.endswith("Steam Screenshots")
    w.deleteLater()


def test_setup_window_without_high_res(gui_engine, qapp, fake_home):
    from ssbackup.ui.setup_window import SetupWindow
    engine, settings = gui_engine
    w = SetupWindow(str(fake_home / "Shots"), False, engine.steam_roots)
    assert w.backup_high_res is False
    w.deleteLater()


# ------------------------------------------------------------------- dialogs

def test_message_dialog_builds(qapp):
    from ssbackup.ui.widgets import MessageDialog
    d = MessageDialog("Something happened.", "Title", Theme.p.accent, "OK", None)
    assert d.windowTitle() == "Title"
    d.deleteLater()


def test_confirm_deletion_short_circuits_on_zero(qapp, monkeypatch):
    from ssbackup.ui import widgets
    shown = []
    monkeypatch.setattr(widgets.MessageDialog, "info",
                        staticmethod(lambda text, *a, **k: shown.append(text)))
    result = widgets.MessageDialog.confirm_deletion("Delete all backups?", 0, 0)
    assert result is False
    assert shown and "Nothing to delete" in shown[0]


def test_progress_dialog_runs_work_and_closes(qapp):
    from ssbackup.ui.widgets import ProgressDialog
    seen = {}

    def work(progress):
        progress(1, 2)
        progress(2, 2)
        seen["done"] = True
        return 42

    result = ProgressDialog.run(None, "Working…", "Doing things…", work)
    assert seen.get("done") is True
    assert result == 42


def test_progress_dialog_surfaces_errors(qapp, monkeypatch):
    from ssbackup.ui import widgets
    failures = []
    monkeypatch.setattr(widgets.MessageDialog, "fail",
                        staticmethod(lambda text, *a, **k: failures.append(text)))

    def work(progress):
        raise RuntimeError("the disk exploded")

    widgets.ProgressDialog.run(None, "Working…", "Doing things…", work)
    assert failures and "the disk exploded" in failures[0]
