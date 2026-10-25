"""Application coordinator.

Owns the tray icon, the backup engine, and the actions shared between the tray
menu and the main window - the Linux counterpart to TrayContext.
"""

from __future__ import annotations

import shutil
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QSystemTrayIcon

from .. import __version__
from ..core import naming, paths, update_checker
from ..core.backup_engine import BackupEngine, RunKind, RunResult
from ..core.logger import Logger
from ..core.settings import Settings
from ..core.trash import trash_path
from .game_names_window import GameNamesWindow
from .main_window import MainWindow
from .naming_picker import NamingPromptWindow, offer_rename
from .preview_window import PreviewWindow
from .resync_window import ResyncWindow
from .settings_window import SettingsWindow
from .setup_window import SetupWindow
from .targeted_delete_window import TargetedDeleteWindow
from .theme import Theme
from .widgets import MessageDialog

APP_NAME = "Steam Screenshot Backup"


class _Bridge(QObject):
    """Everything a worker thread needs to hand back to the Qt thread."""
    notify = Signal(int, str, str, object)
    restore_needed = Signal()
    destination_offline = Signal()
    destination_online = Signal()
    unresolved_found = Signal(int)
    run_finished = Signal(object, object)       # (RunKind, RunResult|None)
    preview_request = Signal(object, object)    # (plan, result_holder)
    update_result = Signal(object, bool)        # (UpdateInfo|None, user_initiated)


class TrayApp(QObject):
    def __init__(self, settings: Settings, qt_app: QApplication):
        super().__init__()
        self._settings = settings
        self._qt = qt_app
        self.pause_changed: list = []

        self._bridge = _Bridge()
        self._bridge.notify.connect(self._do_notify)
        self._bridge.restore_needed.connect(
            lambda: self._run_scan(RunKind.RESTORE))
        self._bridge.destination_offline.connect(self._on_destination_offline)
        self._bridge.destination_online.connect(
            lambda: self._run_scan(RunKind.STARTUP))
        self._bridge.unresolved_found.connect(self._on_unresolved_found)
        self._bridge.run_finished.connect(self._report_run)
        self._bridge.preview_request.connect(self._show_preview)
        self._bridge.update_result.connect(self._on_update_result)

        # ----- engine -----
        try:
            self.engine = BackupEngine(settings)
        except Exception as ex:
            MessageDialog.fail(str(ex), "Steam Not Found")
            raise SystemExit(1)

        # ----- tray -----
        self._tray = QSystemTrayIcon(Theme.app_icon())
        self._tray.setToolTip(APP_NAME)
        self._menu = self._build_menu()
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()
        Theme.changed.connect(self._on_theme_changed)

        if not settings.FirstRunDone:
            self._first_run()
        settings.save()

        self.engine.restore_needed.append(self._bridge.restore_needed.emit)
        self.engine.destination_offline.append(self._bridge.destination_offline.emit)
        self.engine.destination_online.append(self._bridge.destination_online.emit)
        self.engine.unresolved_game_found.append(self._bridge.unresolved_found.emit)

        self.engine.migrate_structure_if_needed()
        if not settings.FileNamingChosen:
            # Before watching starts, so renames can't be seen as deletions.
            self._ask_file_naming()
        self.engine.start_watching()
        Logger.log(f"Watching for new screenshots. Backing up to: "
                   f"{settings.Destination}")
        self._run_scan(RunKind.STARTUP)   # catch up on anything taken while off

        # One-time: give pre-existing backups searchable metadata.
        if not settings.MetadataBackfilled:
            def backfill():
                self.engine.backfill_metadata()
                settings.MetadataBackfilled = True
                settings.save()
            threading.Thread(target=backfill, name="Backfill", daemon=True).start()

        # Small delay so this never competes with the startup catch-up scan,
        # then once a day - the same cadence as the name-cache re-verification.
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._auto_check_for_updates)
        self._update_timer.start(24 * 60 * 60 * 1000)
        QTimer.singleShot(2 * 60 * 1000, self._auto_check_for_updates)

    # ------------------------------------------------------------- tray menu

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        menu.setStyleSheet(Theme.stylesheet())

        def add(text, fn):
            act = QAction(text, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
            return act

        add(f"Open {APP_NAME}", lambda: MainWindow.show_window(self))
        add("Backup Now", self.backup_now)
        add("Re-Sync", lambda: self.open_resync(None))
        add("Open Backup Folder", self.open_backup_folder)
        add("Game Names", lambda: self.open_game_names(None))
        menu.addSeparator()

        self._pause_action = QAction("Pause Monitoring", menu)
        self._pause_action.setCheckable(True)
        self._pause_action.toggled.connect(self._apply_pause)
        menu.addAction(self._pause_action)

        self._autostart_action = QAction("Start On Login", menu)
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(paths.is_autostart_enabled())
        self._autostart_action.toggled.connect(paths.set_autostart_enabled)
        menu.addAction(self._autostart_action)

        add("Settings", lambda: self.show_settings(None))
        add("Check for Updates Now", lambda: self.check_for_updates_now(None))
        menu.addSeparator()
        add("Uninstall", lambda: self.uninstall(None))
        add("Exit", self.exit_app)
        return menu

    def _on_theme_changed(self) -> None:
        self._menu.setStyleSheet(Theme.stylesheet())
        self._tray.setIcon(Theme.app_icon())

    def _on_tray_activated(self, reason) -> None:
        # Plasma and GNOME both deliver a plain left click as Trigger.
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            MainWindow.toggle_window(self)

    # ------------------------------------------------------------ first run

    def _first_run(self) -> None:
        setup = SetupWindow(self._settings.Destination,
                            self.engine.high_res_source_available,
                            self.engine.steam_roots)
        setup.exec()   # closing the window accepts the defaults

        if setup.destination:
            self._settings.Destination = setup.destination
        self._settings.BackupStandard = (setup.backup_standard
                                         or not setup.backup_high_res)
        self._settings.BackupHighRes = setup.backup_high_res
        self._settings.FileNamePreset = setup.file_name_preset
        self._settings.FileNamingChosen = True
        if setup.auto_start:
            self._autostart_action.setChecked(True)   # handler writes the file
        self._settings.FirstRunDone = True

    def _ask_file_naming(self) -> None:
        """One-time: installs set up before naming presets existed get the same
        choice first-run setup now offers, and can rename what's already
        backed up to match."""
        old_preset = self._settings.FileNamePreset
        prompt = NamingPromptWindow(old_preset)
        # Closing the window instead of clicking Continue keeps the current style.
        accepted = prompt.exec() == QDialog.Accepted
        new_preset = prompt.preset_key if accepted else old_preset
        if new_preset != old_preset:
            self._settings.FileNamePreset = new_preset
            Logger.log(f"Setting 'File Naming' changed to "
                       f"'{naming.get_preset(new_preset).label}' "
                       f"(was '{naming.get_preset(old_preset).label}')")
        offer_rename(self.engine, self._settings, new_preset)
        self._settings.FileNamingChosen = True
        self._settings.save()

    # -------------------------------------------------------------- actions

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def is_paused(self) -> bool:
        return self.engine.paused

    def open_main_window(self) -> None:
        MainWindow.show_window(self)

    def backup_now(self) -> None:
        self._run_scan(RunKind.MANUAL)

    def open_backup_folder(self) -> None:
        try:
            dest = self._settings.Destination
            import os
            os.makedirs(dest, exist_ok=True)
            paths.open_path(dest)
        except Exception as ex:
            Logger.error(f"Open folder failed: {ex}")
            MessageDialog.fail(f"Could not open the backup folder:\n{ex}")

    def set_paused(self, paused: bool) -> None:
        self._pause_action.setChecked(paused)   # handler does the rest

    def _apply_pause(self, paused: bool) -> None:
        self.engine.paused = paused
        if paused:
            Logger.paused("Watching paused.")
        else:
            Logger.resumed("Watching resumed.")
        for fn in list(self.pause_changed):
            try:
                fn()
            except Exception:
                pass

    def show_settings(self, parent) -> None:
        # The reference has to outlive this method: Settings is modeless (Apply
        # saves without closing), so a local variable would be garbage collected
        # the moment this returns and Qt would destroy the window with it.
        existing = getattr(self, "_settings_window", None)
        if existing is not None and not existing.isHidden():
            existing.raise_()
            existing.activateWindow()
            return

        self._settings_window = SettingsWindow(self, self._settings, parent)
        self._settings_window.setAttribute(Qt.WA_DeleteOnClose, False)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def open_game_names(self, parent) -> None:
        GameNamesWindow(self.engine, parent).exec()

    def open_resync(self, parent) -> None:
        ResyncWindow.show_window(self.engine, parent)

    def open_granular_delete(self, parent) -> None:
        TargetedDeleteWindow.show_window(self.engine, parent)

    def on_settings_changed(self, sources_changed: bool) -> None:
        """Called by SettingsWindow after saving; restarts watchers when sources
        or the destination changed, then scans to pick up the difference."""
        self._autostart_action.setChecked(paths.is_autostart_enabled())
        if sources_changed:
            self.engine.restart_watching()
            self._run_scan(RunKind.DESTINATION_CHANGED)

    # -------------------------------------------------------- notifications

    def _notify(self, ms: int, title: str, text: str,
                icon=QSystemTrayIcon.Information) -> None:
        """Central gate so the "show notifications" setting is honoured.

        The desktop's own notification chrome already shows the app name and
        icon, so the title here is a short, specific header - never a repeat of
        "Steam Screenshot Backup" or a restatement of the body.
        """
        if not self._settings.ShowNotifications:
            return
        # The enum travels as-is; converting it to an int and back was one more
        # place for this to fail silently inside a Qt slot.
        self._bridge.notify.emit(ms, title, text, icon)

    def _do_notify(self, ms: int, title: str, text: str, icon) -> None:
        try:
            self._tray.showMessage(title, text, icon, ms)
        except Exception as ex:
            Logger.warn(f"Could not show a notification: {ex}")

    def _on_destination_offline(self) -> None:
        self._notify(5000, "Backup Paused",
                     "Backup folder is unreachable — backups will resume "
                     "automatically when it returns.",
                     QSystemTrayIcon.Warning)

    def _on_unresolved_found(self, count: int) -> None:
        self._notify(6000, "Game Names Needed",
                     f"{count} game folder{'' if count == 1 else 's'} could not "
                     "be named automatically — open Game Names to identify "
                     f"{'it' if count == 1 else 'them'}.")

    # ------------------------------------------------------------ scan runs

    def _run_scan(self, kind: RunKind) -> None:
        engine = self.engine
        settings = self._settings

        # The first-ever catch-up always previews; other batch scans preview
        # only if the user opted in.  Auto-restore and real-time captures never
        # preview.
        first_import = kind == RunKind.STARTUP and not settings.FirstImportDone
        want_preview = kind != RunKind.RESTORE and (
            first_import or (settings.PreviewBeforeImport and kind in (
                RunKind.MANUAL, RunKind.STARTUP, RunKind.DESTINATION_CHANGED)))

        def work():
            try:
                if want_preview:
                    plan = engine.plan_scan()
                    if first_import:
                        settings.FirstImportDone = True
                        settings.save()
                    if plan:
                        holder = {"event": threading.Event(), "ok": False}
                        self._bridge.preview_request.emit(plan, holder)
                        holder["event"].wait()
                        if not holder["ok"]:
                            Logger.log(f"Import cancelled from preview "
                                       f"({len(plan)} not imported).")
                            return

                run = engine.full_scan(restore=kind == RunKind.RESTORE)
                self._bridge.run_finished.emit(kind, run)
            except Exception as ex:
                Logger.error(f"Scan failed: {ex}")
                self._notify(4000, "Backup Failed", "Open the app for details.",
                             QSystemTrayIcon.Critical)

        threading.Thread(target=work, name=f"Scan-{kind.value}",
                         daemon=True).start()

    def _show_preview(self, plan: list, holder: dict) -> None:
        """Runs the modal on the Qt thread for a background scan task."""
        try:
            holder["ok"] = PreviewWindow.confirm(
                "Preview Import",
                f"{len(plan)} screenshot{'' if len(plan) == 1 else 's'} will be "
                "imported into your backup:",
                plan, "Import")
        finally:
            holder["event"].set()

    def _report_run(self, kind: RunKind, run: RunResult | None) -> None:
        """Log + notify with only what THIS run did (no lifetime totals)."""
        if run is None:
            if kind == RunKind.MANUAL:
                self._notify(4000, "Backup Unreachable",
                             "The backup folder is currently unreachable.",
                             QSystemTrayIcon.Warning)
            return

        n = run.copied
        games = len(run.games_affected)
        verb = "restored" if kind == RunKind.RESTORE else "new"

        if n > 0:
            Logger.log(
                f"{'Restore' if kind == RunKind.RESTORE else 'Backup'} run "
                f"complete: {n} {verb} file{'' if n == 1 else 's'} across "
                f"{games} game{'' if games == 1 else 's'}.")
            title = ("Restore Complete" if kind == RunKind.RESTORE
                     else "Backup Complete")
            text = (f"Restored {n} screenshot{'' if n == 1 else 's'} across "
                    f"{games} game{'' if games == 1 else 's'}."
                    if kind == RunKind.RESTORE else
                    f"{n} new screenshot{'' if n == 1 else 's'} from "
                    f"{games} game{'' if games == 1 else 's'}.")
            self._notify(4000, title, text)
        elif kind == RunKind.RESTORE:
            Logger.warn("Deleted backup files could not be restored — they no "
                        "longer exist in Steam's screenshot folders.")
            self._notify(5000, "Restore Failed",
                         "Deleted files no longer exist in Steam.",
                         QSystemTrayIcon.Warning)
        else:
            Logger.log("Backup run complete: nothing new to copy.")
            if kind == RunKind.MANUAL:
                self._notify(3000, "Up to Date", "Everything is already backed up.")

    # --------------------------------------------------------- update checks

    def check_for_updates_now(self, parent) -> None:
        """User-initiated: always gives visible feedback, even when there's
        nothing new."""
        if self._settings.OfflineMode:
            MessageDialog.info(
                "Offline Mode is on, so update checks are disabled.\n\n"
                "Turn it off in Settings → Privacy to check for updates.",
                parent=parent)
            return

        def work():
            info = update_checker.check_now(self._settings)
            self._bridge.update_result.emit(info, True)

        threading.Thread(target=work, name="UpdateCheck", daemon=True).start()

    def _auto_check_for_updates(self) -> None:
        """Timer-driven: silent unless there's actually something new, and only
        once per version so it doesn't nag on every pass."""
        if not self._settings.CheckForUpdates or self._settings.OfflineMode:
            return

        def work():
            info = update_checker.check_now(self._settings)
            if info is None:
                return
            if (self._settings.LastNotifiedUpdateVersion or "").lower() == \
                    info.version.lower():
                return
            self._settings.LastNotifiedUpdateVersion = info.version
            self._settings.save()
            self._bridge.update_result.emit(info, False)

        threading.Thread(target=work, name="UpdateCheckAuto", daemon=True).start()

    def _on_update_result(self, info, user_initiated: bool) -> None:
        if info is None:
            if user_initiated:
                MessageDialog.info(
                    f"You're running the latest version ({__version__}).")
            return

        if user_initiated:
            if MessageDialog.confirm(
                    f"Version {info.version} is available — you have "
                    f"{__version__}.",
                    "Update Available", "View Release", "Later"):
                paths.open_url(info.url)
            return

        Logger.update_available(
            f"Update available: version {info.version} "
            f"(currently running {__version__}).")
        self._notify(6000, "Update Available",
                     f"Version {info.version} is available — use "
                     '"Check for Updates Now" to view it.')

    # ------------------------------------------------------------ uninstall

    def uninstall(self, parent) -> None:
        installer = paths.data_home() / "steam-screenshot-backup" / "uninstall.sh"
        has_installer = installer.is_file()

        ok = MessageDialog.ask_yes_no(
            f"This removes {APP_NAME} from this computer:\n\n"
            "  •  stops the app and removes it from your login startup\n"
            "  •  deletes its settings, game-name list, and log\n"
            "  •  deletes the program files themselves\n\n"
            "Your backed-up screenshots and Steam's own files are NOT touched.\n\n"
            "Uninstall now?",
            f"Uninstall {APP_NAME}", parent)
        if not ok:
            return

        try:
            paths.set_autostart_enabled(False)
        except Exception:
            pass

        if has_installer:
            # The installed copy ships its own uninstaller, which can remove the
            # venv this process is running from once we have exited.
            import subprocess
            try:
                subprocess.Popen(
                    ["/bin/sh", str(installer), "--from-app"],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.exit_app()
                return
            except OSError as ex:
                Logger.error(f"Could not start the uninstaller: {ex}")

        # Running from a source checkout: clean up what we own and leave the
        # checkout itself alone, since we did not create it.
        for target in (paths.config_dir(), paths.state_dir(),
                       paths.applications_dir() / paths.DESKTOP_FILE_NAME):
            try:
                trash_path(target)
            except Exception:
                try:
                    if target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        target.unlink(missing_ok=True)
                except OSError:
                    pass
        MessageDialog.info(
            "Settings, the game-name list and the log have been removed.\n\n"
            "This copy is running from a source folder, so the folder itself "
            "was left in place — delete it whenever you like.", parent=parent)
        self.exit_app()

    # ----------------------------------------------------------------- exit

    def exit_app(self) -> None:
        try:
            self._tray.hide()
        except Exception:
            pass
        try:
            self.engine.dispose()
        except Exception:
            pass
        self._qt.quit()
