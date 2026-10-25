"""The tray coordinator.

Qt's offscreen platform provides no system tray, so QSystemTrayIcon is stubbed
out. Everything else - the engine, the menu wiring, the scan plumbing - is
real, because a mistake in this class means the app does not start at all.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from ssbackup.core.app_names import AppNameResolver  # noqa: E402
from ssbackup.core.settings import Settings  # noqa: E402


class _FakeTrayIcon:
    """Records what the app would have shown, so notifications are assertable.

    The enum members are the real ones: the app looks them up on this class at
    call time, so a double without them fails inside a Qt slot where the error
    is swallowed rather than raised.
    """

    instances: list["_FakeTrayIcon"] = []

    # Mirrored from the real class, which is still bound here at import time.
    MessageIcon = QSystemTrayIcon.MessageIcon
    NoIcon = QSystemTrayIcon.NoIcon
    Information = QSystemTrayIcon.Information
    Warning = QSystemTrayIcon.Warning
    Critical = QSystemTrayIcon.Critical
    Trigger = QSystemTrayIcon.Trigger
    DoubleClick = QSystemTrayIcon.DoubleClick

    @staticmethod
    def isSystemTrayAvailable() -> bool:
        return True

    def __init__(self, icon=None):
        self.icon = icon
        self.menu = None
        self.tooltip = ""
        self.visible = False
        self.messages: list[tuple[str, str]] = []
        self.activated = _Signal()
        _FakeTrayIcon.instances.append(self)

    def setToolTip(self, text):
        self.tooltip = text

    def setContextMenu(self, menu):
        self.menu = menu

    def setIcon(self, icon):
        self.icon = icon

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def showMessage(self, title, text, icon=None, ms=0):
        self.messages.append((title, text))


class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *args):
        for fn in self._slots:
            fn(*args)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tray_app(steam_tree, fake_home, monkeypatch, qapp):
    from ssbackup.ui import tray as tray_module

    _FakeTrayIcon.instances.clear()

    settings = Settings.load()
    settings.Destination = str(fake_home / "Backups" / "Steam Screenshots")
    settings.OfflineMode = True
    settings.FirstRunDone = True        # skip the setup wizard
    settings.FirstImportDone = True     # skip the first-run preview modal
    settings.FileNamingChosen = True    # skip the one-time naming prompt
    settings.StructureMigrated = True
    settings.MetadataBackfilled = True
    settings.ShowNotifications = True
    settings.save()

    monkeypatch.setattr(AppNameResolver, "_start_refresh_timer", lambda self: None)
    monkeypatch.setattr(tray_module, "QSystemTrayIcon", _FakeTrayIcon)

    app = tray_module.TrayApp(settings, qapp)
    yield app, settings
    app.engine.dispose()


def drain(qapp, seconds: float = 3.0, until=None) -> None:
    """Pumps the Qt event loop so queued cross-thread signals are delivered."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        if until is not None and until():
            return
        time.sleep(0.05)
    qapp.processEvents()


# ---------------------------------------------------------------- construction

def test_tray_app_starts(tray_app, qapp):
    app, settings = tray_app
    assert app.engine is not None
    assert _FakeTrayIcon.instances
    tray = _FakeTrayIcon.instances[0]
    assert tray.visible is True
    assert tray.tooltip == "Steam Screenshot Backup"
    assert tray.menu is not None


def test_tray_menu_has_every_action(tray_app, qapp):
    app, settings = tray_app
    tray = _FakeTrayIcon.instances[0]
    labels = [a.text() for a in tray.menu.actions() if a.text()]

    for expected in ("Open Steam Screenshot Backup", "Backup Now", "Re-Sync",
                     "Open Backup Folder", "Game Names", "Pause Monitoring",
                     "Start On Login", "Settings", "Check for Updates Now",
                     "Uninstall", "Exit"):
        assert expected in labels, f"{expected} missing from the tray menu"


def test_startup_scan_backs_everything_up(tray_app, qapp):
    """The catch-up scan runs on a worker thread at startup; this is the whole
    point of the app, so it is worth asserting end to end."""
    app, settings = tray_app
    from pathlib import Path

    expected = (Path(settings.Destination) / "Standard" / "Portal 2"
                / "2026-04-12 13.37.15.jpg")
    drain(qapp, seconds=20.0, until=expected.is_file)
    assert expected.is_file()


def test_startup_scan_notifies(tray_app, qapp):
    app, settings = tray_app
    tray = _FakeTrayIcon.instances[0]
    drain(qapp, seconds=20.0, until=lambda: bool(tray.messages))
    assert tray.messages
    assert any("Backup Complete" == title for title, _ in tray.messages)


# ---------------------------------------------------------------------- pause

def test_pause_toggles_engine_and_listeners(tray_app, qapp):
    app, settings = tray_app
    seen = []
    app.pause_changed.append(lambda: seen.append(app.is_paused))

    app.set_paused(True)
    assert app.is_paused is True
    assert app.engine.paused is True
    assert seen == [True]

    app.set_paused(False)
    assert app.is_paused is False
    assert app.engine.paused is False
    assert seen == [True, False]


# -------------------------------------------------------------- notifications

def test_notifications_respect_the_setting(tray_app, qapp):
    app, settings = tray_app
    tray = _FakeTrayIcon.instances[0]
    drain(qapp, seconds=15.0, until=lambda: bool(tray.messages))
    tray.messages.clear()

    settings.ShowNotifications = False
    app._notify(1000, "Title", "Body")
    drain(qapp, seconds=1.0)
    assert tray.messages == []

    settings.ShowNotifications = True
    app._notify(1000, "Title", "Body")
    drain(qapp, seconds=2.0, until=lambda: bool(tray.messages))
    assert tray.messages == [("Title", "Body")]


def test_destination_offline_notifies(tray_app, qapp):
    app, settings = tray_app
    tray = _FakeTrayIcon.instances[0]
    drain(qapp, seconds=15.0, until=lambda: bool(tray.messages))
    tray.messages.clear()

    app._on_destination_offline()
    drain(qapp, seconds=2.0, until=lambda: bool(tray.messages))
    assert any("Backup Paused" == title for title, _ in tray.messages)


def test_unresolved_games_notify(tray_app, qapp):
    app, settings = tray_app
    tray = _FakeTrayIcon.instances[0]
    drain(qapp, seconds=15.0, until=lambda: bool(tray.messages))
    tray.messages.clear()

    app._on_unresolved_found(2)
    drain(qapp, seconds=2.0, until=lambda: bool(tray.messages))
    title, body = tray.messages[0]
    assert title == "Game Names Needed"
    assert "2 game folders" in body


# ------------------------------------------------------------- update results

def test_update_result_notifies_once(tray_app, qapp, monkeypatch):
    from ssbackup.core.update_checker import UpdateInfo
    app, settings = tray_app
    tray = _FakeTrayIcon.instances[0]
    drain(qapp, seconds=15.0, until=lambda: bool(tray.messages))
    tray.messages.clear()

    app._on_update_result(UpdateInfo(version="9.9.9", url="https://example.test"),
                          user_initiated=False)
    drain(qapp, seconds=2.0, until=lambda: bool(tray.messages))
    assert any("Update Available" == title for title, _ in tray.messages)


def test_up_to_date_is_silent_when_automatic(tray_app, qapp):
    app, settings = tray_app
    tray = _FakeTrayIcon.instances[0]
    drain(qapp, seconds=15.0, until=lambda: bool(tray.messages))
    tray.messages.clear()

    app._on_update_result(None, user_initiated=False)
    drain(qapp, seconds=1.0)
    assert tray.messages == []


def test_offline_mode_blocks_manual_update_check(tray_app, qapp, monkeypatch):
    from ssbackup.ui import tray as tray_module
    app, settings = tray_app
    settings.OfflineMode = True

    shown = []
    monkeypatch.setattr(tray_module.MessageDialog, "info",
                        staticmethod(lambda text, *a, **k: shown.append(text)))
    app.check_for_updates_now(None)
    assert shown and "Offline Mode is on" in shown[0]


# ------------------------------------------------------------------- shutdown

def test_exit_hides_tray_and_disposes_engine(tray_app, qapp, monkeypatch):
    app, settings = tray_app
    tray = _FakeTrayIcon.instances[0]
    monkeypatch.setattr(qapp, "quit", lambda: None)

    app.exit_app()
    assert tray.visible is False
    assert app.engine._disposed is True


# ------------------------------------------------------- window lifetimes

def test_settings_window_survives_the_call(tray_app, qapp):
    """Settings is modeless, so a local-variable reference would be garbage
    collected the moment show_settings() returned and Qt would destroy the
    window with it - the window would flash and vanish."""
    import gc

    app, settings = tray_app
    app.show_settings(None)
    gc.collect()
    drain(qapp, seconds=1.0)

    window = getattr(app, "_settings_window", None)
    assert window is not None, "no reference was kept to the Settings window"
    # Touching it proves the underlying C++ object is still alive; if Qt had
    # destroyed it this raises RuntimeError.
    assert window.windowTitle().startswith("Settings")
    assert window.isVisible()
    window.close()


def test_reopening_settings_reuses_one_window(tray_app, qapp):
    app, settings = tray_app
    app.show_settings(None)
    first = app._settings_window
    app.show_settings(None)
    assert app._settings_window is first, "a second Settings window was stacked"
    first.close()


def test_settings_can_be_reopened_after_closing(tray_app, qapp):
    app, settings = tray_app
    app.show_settings(None)
    app._settings_window.close()
    drain(qapp, seconds=0.5)

    app.show_settings(None)
    assert app._settings_window.isVisible()
    app._settings_window.close()


# ---------------------------------------------------------- naming prompt

def test_existing_install_is_asked_for_file_naming_once(
        steam_tree, fake_home, monkeypatch, qapp):
    """Installs set up before naming presets existed get the choice too."""
    from ssbackup.ui import tray as tray_module

    settings = Settings.load()
    settings.Destination = str(fake_home / "Backups" / "Steam Screenshots")
    settings.OfflineMode = True
    settings.FirstRunDone = True
    settings.FirstImportDone = True
    settings.StructureMigrated = True
    settings.MetadataBackfilled = True
    settings.save()
    assert settings.FileNamingChosen is False

    class _FakePrompt:
        shown = 0

        def __init__(self, current, parent=None):
            self.current = current

        def exec(self):
            _FakePrompt.shown += 1
            return tray_module.QDialog.Accepted

        @property
        def preset_key(self):
            return "Reverse"

    offered = []
    monkeypatch.setattr(AppNameResolver, "_start_refresh_timer", lambda self: None)
    monkeypatch.setattr(tray_module, "QSystemTrayIcon", _FakeTrayIcon)
    monkeypatch.setattr(tray_module, "NamingPromptWindow", _FakePrompt)
    monkeypatch.setattr(tray_module, "offer_rename",
                        lambda engine, s, preset, parent=None: offered.append(preset))

    app = tray_module.TrayApp(settings, qapp)
    try:
        assert _FakePrompt.shown == 1
        assert offered == ["Reverse"]
        assert settings.FileNamePreset == "Reverse"
        assert Settings.load().FileNamingChosen is True
    finally:
        app.engine.dispose()
