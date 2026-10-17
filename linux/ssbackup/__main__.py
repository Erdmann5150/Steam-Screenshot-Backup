"""Entry point.

Starts the tray application, enforcing a single instance the way the Windows
build used a named mutex.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import signal
import sys

from . import __version__
from .core import paths
from .core.logger import Logger
from .core.settings import Settings


def _acquire_single_instance_lock() -> object | None:
    """An advisory lock in the runtime dir.  Returns the open file handle on
    success (which must stay referenced for the process's lifetime), or None if
    another instance already holds it."""
    lock_path = paths.runtime_dir() / "steam-screenshot-backup.lock"
    try:
        handle = open(lock_path, "w")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write(str(os.getpid()))
        handle.flush()
        return handle
    except OSError:
        return None


def _wait_for_system_tray(tray_class, timeout: float = 30.0) -> bool:
    """Waits for the desktop's tray to appear.

    Starting on login is the normal case, and on KDE Plasma the app can easily
    beat its own panel to the punch - the tray reports itself unavailable for a
    few seconds and then arrives.  Giving up immediately would mean the app
    silently fails exactly when it was asked to start automatically, so this
    retries briefly before declaring the tray genuinely missing.
    """
    import time
    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + timeout
    while True:
        if tray_class.isSystemTrayAvailable():
            return True
        if time.monotonic() >= deadline:
            return False
        # Keep the event loop breathing so Qt notices the tray appearing.
        QApplication.processEvents()
        time.sleep(0.5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="steam-screenshot-backup",
        description="Back up Steam screenshots into per-game folders.")
    parser.add_argument("--show", action="store_true",
                        help="open the main window at startup")
    parser.add_argument("--version", action="version",
                        version=f"Steam Screenshot Backup {__version__}")
    args = parser.parse_args(argv)

    # Qt is imported after argument parsing so --version and --help work even
    # on a machine with no display.
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from .ui.theme import Theme
    from .ui.tray import TrayApp
    from .ui.widgets import MessageDialog

    QApplication.setDesktopFileName(paths.APP_ID)
    qt_app = QApplication(sys.argv[:1])
    qt_app.setApplicationName(paths.APP_NAME)
    qt_app.setApplicationDisplayName(paths.APP_NAME)
    qt_app.setApplicationVersion(__version__)
    qt_app.setOrganizationName("SteamScreenshotBackup")
    # The window list is empty most of the time, since the app lives in the
    # tray; without this, hiding the last window would quit.
    qt_app.setQuitOnLastWindowClosed(False)

    settings = Settings.load()
    Theme.set_mode(settings.Theme)
    qt_app.setWindowIcon(Theme.app_icon())
    qt_app.setStyleSheet(Theme.stylesheet())

    lock = _acquire_single_instance_lock()
    if lock is None:
        MessageDialog.info(
            "Steam Screenshot Backup is already running "
            "(look for its icon in the system tray).")
        return 0

    if not _wait_for_system_tray(QSystemTrayIcon):
        message = (
            "No system tray is available on this desktop.\n\n"
            "On KDE Plasma this usually means the system tray widget was "
            "removed from the panel. On GNOME it usually means the "
            "AppIndicator extension is not installed or enabled.\n\n"
            "The app needs a tray to run, since that is where it lives.")
        # Printed as well as shown: when this happens at login there may be no
        # one looking at a dialog, and when it happens in a terminal the dialog
        # may not be visible at all.
        print(f"steam-screenshot-backup: {message}", file=sys.stderr)
        MessageDialog.fail(message, "No System Tray")
        return 1

    # Follow the desktop's light/dark setting when asked to.
    try:
        qt_app.styleHints().colorSchemeChanged.connect(
            lambda _scheme: Theme.refresh_from_system())
    except (AttributeError, TypeError):
        pass   # older Qt; the explicit Dark/Light modes still work

    def restyle():
        qt_app.setStyleSheet(Theme.stylesheet())
    Theme.changed.connect(restyle)

    try:
        app = TrayApp(settings, qt_app)
    except SystemExit as ex:
        return int(ex.code or 1)

    if args.show:
        app.open_main_window()

    # Ctrl-C in a terminal should exit cleanly rather than leaving a stray tray
    # icon; Qt otherwise swallows the signal while its event loop runs.
    signal.signal(signal.SIGINT, lambda *_: app.exit_app())
    signal.signal(signal.SIGTERM, lambda *_: app.exit_app())
    from PySide6.QtCore import QTimer
    heartbeat = QTimer()
    heartbeat.start(500)
    heartbeat.timeout.connect(lambda: None)   # lets Python run signal handlers

    try:
        return qt_app.exec()
    finally:
        try:
            Logger.log("Application exited.")
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
