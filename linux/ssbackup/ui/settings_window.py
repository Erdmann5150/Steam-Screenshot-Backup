"""All app configuration in one place, across two tabs.

Changes are applied when Apply is clicked; destination, layout and file-naming
changes offer to migrate, reorganize or rename existing backups first.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from ..core import naming, paths, steam_config
from ..core.backup_engine import (
    HIGH_RES_FOLDER, STANDARD_FOLDER, ScreenshotType, type_label,
)
from ..core.logger import Logger
from ..core.settings import ThemeMode
from .naming_picker import NamingPicker, offer_rename
from .preview_window import PreviewWindow
from .theme import Theme
from .widgets import (
    MessageDialog, ProgressDialog, button, edge, header_label, panel, small_label,
)

LAYOUT_PRESETS = [
    ("Game name",               "{game}"),
    ("Game name / Year",        "{game}/{yyyy}"),
    ("Game name / Year-Month",  "{game}/{yyyy}-{MM}"),
    ("Year / Game name",        "{yyyy}/{game}"),
    ("Year-Month / Game name",  "{yyyy}-{MM}/{game}"),
]

THEME_CHOICES = [
    ("Dark", ThemeMode.DARK),
    ("Light", ThemeMode.LIGHT),
    ("Follow system setting", ThemeMode.SYSTEM),
]


class SettingsWindow(QDialog):
    def __init__(self, app, settings, parent=None):
        super().__init__(parent)
        self._app = app
        self._settings = settings
        self._suppress_danger_prompt = False

        self.setWindowTitle("Settings — Steam Screenshot Backup")
        self.setWindowIcon(Theme.app_icon())
        self.setModal(False)
        self.resize(620, 720)
        self.setMinimumSize(560, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_tab_bar())
        layout.addWidget(edge())
        self._pages = QStackedWidget()
        self._pages.addWidget(self._wrap_scroll(self._build_general_page()))
        self._pages.addWidget(self._wrap_scroll(self._build_backup_page()))
        layout.addWidget(self._pages, 1)
        layout.addWidget(edge())
        layout.addWidget(self._build_footer())

        self._select_tab(0)
        self._apply_theme()
        Theme.changed.connect(self._apply_theme)

        self._capture_baseline()
        self._wire_dirty_tracking()
        self._update_apply_button()

    # ------------------------------------------------------------- scaffolding

    @staticmethod
    def _wrap_scroll(inner: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(inner)
        area.setFrameShape(QScrollArea.NoFrame)
        return area

    def _build_tab_bar(self) -> QWidget:
        bar = panel(48)
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 0, 8, 0)
        row.setSpacing(0)

        self._tab_general = QPushButton("General")
        self._tab_backup = QPushButton("Backup Configuration")
        for i, b in enumerate((self._tab_general, self._tab_backup)):
            b.setObjectName("Tab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self._select_tab(idx))
            row.addWidget(b)
        row.addStretch(1)
        return bar

    def _select_tab(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        self._tab_general.setChecked(index == 0)
        self._tab_backup.setChecked(index == 1)

    @staticmethod
    def _section(layout: QVBoxLayout, text: str) -> None:
        layout.addSpacing(8)
        layout.addWidget(header_label(text))

    @staticmethod
    def _hint(layout: QVBoxLayout, text: str) -> QLabel:
        lbl = small_label(text)
        lbl.setWordWrap(True)
        lbl.setContentsMargins(22, 0, 0, 0)
        layout.addWidget(lbl)
        return lbl

    # ------------------------------------------------------------ general tab

    def _build_general_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("Page")
        v = QVBoxLayout(page)
        v.setContentsMargins(24, 20, 24, 24)
        v.setSpacing(8)

        self._section(v, "APPEARANCE")
        self._theme = QComboBox()
        self._theme.setFixedWidth(280)
        for label, _ in THEME_CHOICES:
            self._theme.addItem(label)
        current = next((i for i, (_, m) in enumerate(THEME_CHOICES)
                        if m == self._settings.Theme), 0)
        self._theme.setCurrentIndex(current)
        v.addWidget(self._theme)
        v.addSpacing(6)

        self._show_notifications = QCheckBox("Show desktop notifications")
        self._show_notifications.setChecked(self._settings.ShowNotifications)
        v.addWidget(self._show_notifications)

        self._section(v, "STARTUP")
        self._auto_start = QCheckBox("Start automatically when I log in")
        self._auto_start.setChecked(paths.is_autostart_enabled())
        v.addWidget(self._auto_start)

        self._section(v, "IMPORTING")
        self._markdown_index = QCheckBox(
            "Generate a Markdown index (_Screenshot_Log.md) in each folder")
        self._markdown_index.setChecked(self._settings.GenerateMarkdownIndex)
        v.addWidget(self._markdown_index)

        self._preview_import = QCheckBox(
            "Preview a list of changes before importing batches")
        self._preview_import.setChecked(self._settings.PreviewBeforeImport)
        v.addWidget(self._preview_import)
        self._hint(v, "Real-time captures during play are never interrupted; "
                      "this only affects batch scans.")

        self._section(v, "DELETED-FILE PROTECTION")
        self._auto_restore = QCheckBox(
            "Automatically restore files deleted from the backup")
        self._auto_restore.setChecked(self._settings.AutoRestore)
        v.addWidget(self._auto_restore)
        self._hint(v, "When off, deletions are only logged — recover them "
                      'yourself from "Re-Sync".')

        self._section(v, "PRIVACY")
        self._offline_mode = QCheckBox(
            "Offline mode: never contact Steam's servers for game names")
        self._offline_mode.setChecked(self._settings.OfflineMode)
        v.addWidget(self._offline_mode)
        self._hint(v, "Game names still resolve from local Steam data; only "
                      'unrecognized games fall back to an "AppID_<id>" folder name.')

        self._section(v, "UPDATES")
        self._check_for_updates = QCheckBox(
            "Automatically check for new versions once a day")
        self._check_for_updates.setChecked(self._settings.CheckForUpdates)
        v.addWidget(self._check_for_updates)
        self._hint(v, "A read-only check against this project's GitHub releases "
                      "page — no data about you or your files is sent, just a "
                      "request for the latest version number.")

        # Offline mode already skips update checks at runtime; gray this out too
        # so the UI doesn't imply it does something on its own.
        self._check_for_updates.setEnabled(not self._offline_mode.isChecked())
        self._offline_mode.toggled.connect(
            lambda on: self._check_for_updates.setEnabled(not on))

        v.addStretch(1)
        return page

    # ------------------------------------------------------------- backup tab

    def _build_backup_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("Page")
        v = QVBoxLayout(page)
        v.setContentsMargins(24, 20, 24, 24)
        v.setSpacing(8)

        self._section(v, "BACKUP FOLDER")
        row = QHBoxLayout()
        self._dest = QLineEdit(self._settings.Destination)
        self._browse = button("Browse")
        self._browse.clicked.connect(self._browse_destination)
        row.addWidget(self._dest, 1)
        row.addWidget(self._browse)
        v.addLayout(row)

        self._section(v, "WHAT TO BACK UP")
        self._standard = QCheckBox(
            "Standard screenshots (Steam's compressed library copies)")
        self._standard.setChecked(self._settings.BackupStandard)
        v.addWidget(self._standard)

        self._high_res = QCheckBox(
            'High-resolution screenshots (Steam\'s "save an external copy" files)')
        self._high_res.setChecked(self._settings.BackupHighRes)
        v.addWidget(self._high_res)

        detected = self._app.engine.auto_detected_high_res_folder
        self._hint(v, "High-resolution folder (auto-detected; set only to use a "
                      "different one):" if detected else
                      "High-resolution folder (not auto-detected — set it here "
                      "if you use external copies):")
        hr_row = QHBoxLayout()
        hr_row.setContentsMargins(22, 0, 0, 0)
        self._high_res_folder = QLineEdit(self._settings.HighResFolderOverride or "")
        if detected:
            self._high_res_folder.setPlaceholderText(detected)
        self._hr_browse = button("Browse")
        self._hr_browse.clicked.connect(self._browse_high_res)
        hr_row.addWidget(self._high_res_folder, 1)
        hr_row.addWidget(self._hr_browse)
        v.addLayout(hr_row)

        self._section(v, "FOLDER LAYOUT (INSIDE EACH TYPE FOLDER)")
        self._layout_box = QComboBox()
        self._layout_box.setFixedWidth(280)
        for label, _ in LAYOUT_PRESETS:
            self._layout_box.addItem(label)
        current_template = self._settings.FolderTemplate or "{game}"
        idx = next((i for i, (_, t) in enumerate(LAYOUT_PRESETS)
                    if t == current_template), 0)
        self._layout_box.setCurrentIndex(idx)
        v.addWidget(self._layout_box)

        self._section(v, "FILE NAMES")
        self._naming = NamingPicker(self._settings.FileNamePreset)
        v.addWidget(self._naming)
        self._hint(v, "Only \"Date and time\" matches the Windows app. With "
                      "another style, a Windows install sharing this backup "
                      "folder would copy its own differently-named duplicates.")

        self._section(v, "STEAM INSTALLATION")
        found = self._app.engine.steam_roots
        self._hint(v, "Detected: " + steam_config.describe_installs(found))
        steam_row = QHBoxLayout()
        steam_row.setContentsMargins(22, 0, 0, 0)
        self._steam_path = QLineEdit(self._settings.SteamPathOverride or "")
        self._steam_path.setPlaceholderText(
            str(found[0]) if found else "Path to your Steam folder")
        self._steam_browse = button("Browse")
        self._steam_browse.clicked.connect(self._browse_steam)
        steam_row.addWidget(self._steam_path, 1)
        steam_row.addWidget(self._steam_browse)
        v.addLayout(steam_row)
        self._hint(v, "Leave blank to auto-detect. Set this only if your Steam "
                      "lives somewhere unusual.")

        v.addSpacing(10)
        danger = QLabel("DANGER ZONE")
        danger.setObjectName("Danger")
        v.addWidget(danger)
        self._delete_originals = QCheckBox(
            "Delete original Steam screenshots after import")
        self._delete_originals.setObjectName("DangerCheck")
        self._delete_originals.setChecked(self._settings.DeleteOriginals)
        self._delete_originals.toggled.connect(self._on_delete_originals_toggled)
        v.addWidget(self._delete_originals)
        self._hint(v, "Removes each original from Steam once it is safely backed "
                      "up. Files go to the trash (recoverable), not permanent "
                      "deletion.")

        v.addStretch(1)
        return page

    # ---------------------------------------------------------------- footer

    def _build_footer(self) -> QWidget:
        bar = panel(62)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(10)

        self._uninstall = button("Uninstall")
        self._uninstall.setObjectName("Danger")
        self._uninstall.clicked.connect(self._do_uninstall)
        row.addWidget(self._uninstall)
        row.addStretch(1)

        # Apply saves in the background and leaves the window open, so the user
        # can keep adjusting settings and see the effect of each change.
        self._apply = button("Apply", primary=True)
        self._apply.setEnabled(False)
        self._apply.clicked.connect(self._save_changes)
        row.addWidget(self._apply)

        # Close just closes the window; it never implies "discard" the way
        # Cancel would, since Apply may already have saved earlier changes.
        close = button("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        return bar

    def _do_uninstall(self) -> None:
        self.close()
        self._app.uninstall(self.parent())

    # ------------------------------------------------------------- browsing

    def _browse_destination(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose the folder where screenshots will be backed up",
            self._dest.text() or str(Path.home()))
        if chosen:
            self._dest.setText(chosen)

    def _browse_high_res(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose the folder where Steam saves external copies",
            self._high_res_folder.text() or str(Path.home()))
        if chosen:
            self._high_res_folder.setText(chosen)

    def _browse_steam(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose your Steam installation folder",
            self._steam_path.text() or str(Path.home()))
        if chosen:
            self._steam_path.setText(chosen)

    # --------------------------------------------------------- dirty tracking

    def _current_theme(self) -> ThemeMode:
        return THEME_CHOICES[self._theme.currentIndex()][1]

    def _state(self) -> tuple:
        return (
            self._dest.text().strip(),
            self._high_res_folder.text().strip(),
            self._steam_path.text().strip(),
            LAYOUT_PRESETS[self._layout_box.currentIndex()][1],
            self._naming.preset_key,
            self._standard.isChecked(),
            self._high_res.isChecked(),
            self._auto_start.isChecked(),
            self._auto_restore.isChecked(),
            self._delete_originals.isChecked(),
            self._show_notifications.isChecked(),
            self._markdown_index.isChecked(),
            self._preview_import.isChecked(),
            self._offline_mode.isChecked(),
            self._check_for_updates.isChecked(),
            self._current_theme(),
        )

    def _capture_baseline(self) -> None:
        """Snapshots every field's last-applied value.  Called at load and after
        each successful Apply, since Apply saves without closing."""
        self._baseline = self._state()

    def _update_apply_button(self) -> None:
        self._apply.setEnabled(self._state() != self._baseline)

    def _wire_dirty_tracking(self) -> None:
        """Every field gets a listener, so Apply lights up the moment something
        differs from the last-applied values and grays back out once it matches
        again (e.g. toggling a checkbox back off)."""
        for w in (self._dest, self._high_res_folder, self._steam_path):
            w.textChanged.connect(self._update_apply_button)
        for w in (self._layout_box, self._theme):
            w.currentIndexChanged.connect(self._update_apply_button)
        self._naming.changed.connect(self._update_apply_button)
        for w in (self._standard, self._high_res, self._auto_start,
                  self._auto_restore, self._delete_originals,
                  self._show_notifications, self._markdown_index,
                  self._preview_import, self._offline_mode,
                  self._check_for_updates):
            w.toggled.connect(self._update_apply_button)

    # ------------------------------------------------------- danger handling

    def _on_delete_originals_toggled(self, checked: bool) -> None:
        """Strict confirmation the moment the dangerous box is ticked; reverts
        on decline."""
        if self._suppress_danger_prompt or not checked:
            return

        ok = MessageDialog.ask_yes_no(
            "DANGER — delete originals after import\n\n"
            "With this on, every original Steam screenshot is removed from "
            "Steam as soon as it is safely backed up, and Steam will no longer "
            "show those screenshots.\n\n"
            "Deleted files go to the trash, so you can recover them until it "
            "is emptied — but this still changes Steam's own screenshot "
            "folder.\n\n"
            "Are you sure you want to enable this?",
            "Enable a Dangerous Setting", self,
        ) and MessageDialog.ask_yes_no(
            "Final confirmation.\n\n"
            "You are enabling automatic deletion of your original Steam "
            "screenshots after they are backed up. This changes Steam's own "
            "files.\n\n"
            "Do you explicitly confirm you want this?",
            "Are You Absolutely Sure?", self,
        )

        if not ok:
            self._suppress_danger_prompt = True
            self._delete_originals.setChecked(False)
            self._suppress_danger_prompt = False

    # ----------------------------------------------------------------- saving

    def _save_changes(self) -> None:
        s = self._settings

        if not self._standard.isChecked() and not self._high_res.isChecked():
            MessageDialog.info("At least one screenshot type must stay enabled.",
                               parent=self)
            return

        new_dest = self._dest.text().strip()
        if not new_dest:
            MessageDialog.info("Please choose a backup folder.", parent=self)
            return
        new_dest = os.path.expanduser(new_dest)

        old_dest = s.Destination
        old_template = s.FolderTemplate or "{game}"
        new_template = LAYOUT_PRESETS[self._layout_box.currentIndex()][1]
        old_naming = s.FileNamePreset
        new_naming = self._naming.preset_key

        old_override = s.HighResFolderOverride or ""
        new_override = self._high_res_folder.text().strip()
        old_steam = s.SteamPathOverride or ""
        new_steam = self._steam_path.text().strip()

        dest_changed = os.path.normpath(old_dest) != os.path.normpath(new_dest)
        types_changed = (self._standard.isChecked() != s.BackupStandard
                         or self._high_res.isChecked() != s.BackupHighRes)
        override_changed = old_override != new_override
        steam_changed = old_steam != new_steam
        template_changed = old_template != new_template

        # Types being switched off, captured before the settings are overwritten,
        # so we can offer to clean up the now-unwanted backups.
        standard_turned_off = s.BackupStandard and not self._standard.isChecked()
        high_res_turned_off = s.BackupHighRes and not self._high_res.isChecked()

        # Snapshot of the old values, for the audit log below.
        old = {
            "Backup Standard Screenshots": s.BackupStandard,
            "Backup High-Resolution Screenshots": s.BackupHighRes,
            "Automatic Restore": s.AutoRestore,
            "Show Notifications": s.ShowNotifications,
            "Markdown Index": s.GenerateMarkdownIndex,
            "Preview Before Import": s.PreviewBeforeImport,
            "Delete Originals": s.DeleteOriginals,
            "Offline Mode": s.OfflineMode,
            "Check For Updates": s.CheckForUpdates,
            "Theme": s.Theme.value,
            "Start On Login": paths.is_autostart_enabled(),
            "Steam Path Override": old_steam or "(auto-detect)",
        }

        markdown_newly_enabled = (self._markdown_index.isChecked()
                                  and not s.GenerateMarkdownIndex)
        markdown_turned_off = (s.GenerateMarkdownIndex
                               and not self._markdown_index.isChecked())
        delete_originals_newly_enabled = (self._delete_originals.isChecked()
                                          and not s.DeleteOriginals)

        s.BackupStandard = self._standard.isChecked()
        s.BackupHighRes = self._high_res.isChecked()
        s.HighResFolderOverride = new_override or None
        s.SteamPathOverride = new_steam or None
        s.AutoRestore = self._auto_restore.isChecked()
        s.ShowNotifications = self._show_notifications.isChecked()
        s.GenerateMarkdownIndex = self._markdown_index.isChecked()
        s.PreviewBeforeImport = self._preview_import.isChecked()
        s.OfflineMode = self._offline_mode.isChecked()
        s.CheckForUpdates = self._check_for_updates.isChecked()
        s.DeleteOriginals = self._delete_originals.isChecked()
        s.Theme = self._current_theme()
        paths.set_autostart_enabled(self._auto_start.isChecked())

        # The destination move happens before the template change so a
        # reorganization only ever runs in one place.
        if dest_changed:
            has_existing = _backup_exists(old_dest)
            migrate = has_existing and MessageDialog.ask_yes_no(
                "Move your existing backup files to the new location?\n\n"
                "Choosing No leaves the old files where they are and re-copies "
                "everything from Steam into the new folder on the next scan.",
                "Migrate Existing Backup", self)
            s.Destination = new_dest
            if migrate:
                engine = self._app.engine
                ProgressDialog.run(
                    self, "Migrating Backup…", "Moving files…",
                    lambda progress: engine.move_backup(old_dest, new_dest, progress))

        if steam_changed:
            self._app.engine.rescan_steam_installs()

        if template_changed:
            # Only adopt the new layout if there's nothing to move, or the user
            # confirms moving existing files to match it.  Otherwise the setting
            # and the on-disk layout would disagree, breaking later scans: they
            # would compute the new-layout path for an existing file, not find
            # it there, and wrongly treat it as missing.
            apply_template = True
            if _backup_exists(s.Destination):
                plan = self._app.engine.plan_reorganize(old_template, new_template)
                if plan:
                    apply_template = PreviewWindow.confirm(
                        "Preview Reorganization",
                        f"{len(plan)} file{'' if len(plan) == 1 else 's'} will be "
                        "moved to match the new layout:",
                        plan, "Reorganize", self)
                    if apply_template:
                        engine = self._app.engine
                        ProgressDialog.run(
                            self, "Reorganizing Backup…",
                            "Moving files into the new folder layout…",
                            lambda progress: engine.reorganize_layout(
                                old_template, new_template))
            if apply_template:
                s.FolderTemplate = new_template
            else:
                # Declined the reorganize: the on-disk layout and the setting
                # stay on the old template, so the dropdown has to match or it
                # would show a layout that was never actually applied.
                old_idx = next((i for i, (_, t) in enumerate(LAYOUT_PRESETS)
                                if t == old_template), 0)
                self._layout_box.setCurrentIndex(old_idx)

        if new_naming != old_naming:
            # After any move or reorganize, so this renames files where they
            # now are.  Declining the rename still adopts the new style for
            # future backups: every style is recognized, so nothing is recopied.
            s.FileNamePreset = new_naming
            s.FileNamingChosen = True
            if _backup_exists(s.Destination):
                offer_rename(self._app.engine, s, new_naming, self)

        _log_change("Backup Folder", old_dest, s.Destination)
        _log_change("Folder Layout", old_template, s.FolderTemplate)
        _log_change("File Naming", naming.get_preset(old_naming).label,
                    naming.get_preset(s.FileNamePreset).label)
        _log_change("High-Resolution Folder Override",
                    old_override or "(auto-detect)",
                    s.HighResFolderOverride or "(auto-detect)")
        new_values = {
            "Backup Standard Screenshots": s.BackupStandard,
            "Backup High-Resolution Screenshots": s.BackupHighRes,
            "Automatic Restore": s.AutoRestore,
            "Show Notifications": s.ShowNotifications,
            "Markdown Index": s.GenerateMarkdownIndex,
            "Preview Before Import": s.PreviewBeforeImport,
            "Delete Originals": s.DeleteOriginals,
            "Offline Mode": s.OfflineMode,
            "Check For Updates": s.CheckForUpdates,
            "Theme": s.Theme.value,
            "Start On Login": self._auto_start.isChecked(),
            "Steam Path Override": s.SteamPathOverride or "(auto-detect)",
        }
        for name, old_value in old.items():
            _log_change(name, old_value, new_values[name])

        s.save()
        Theme.set_mode(s.Theme)
        self._app.on_settings_changed(
            dest_changed or types_changed or override_changed or steam_changed)

        self._capture_baseline()
        self._update_apply_button()

        # Turned a screenshot type off: offer to remove its unwanted backups.
        if standard_turned_off and _type_backup_exists(s.Destination,
                                                       ScreenshotType.STANDARD):
            if MessageDialog.ask_yes_no(
                    "You turned off Standard screenshots. Delete the existing "
                    "Standard backup files?\n\n"
                    "They will be moved to the trash (recoverable). Choose No "
                    "to keep them.",
                    "Delete Standard Backups?", self):
                self._run_type_delete(ScreenshotType.STANDARD)

        if high_res_turned_off and _type_backup_exists(s.Destination,
                                                       ScreenshotType.HIGH_RES):
            if MessageDialog.ask_yes_no(
                    "You turned off High-resolution screenshots. Delete the "
                    "existing High Resolution backup files?\n\n"
                    "They will be moved to the trash (recoverable). Choose No "
                    "to keep them.",
                    "Delete High Resolution Backups?", self):
                self._run_type_delete(ScreenshotType.HIGH_RES)

        # Newly enabled markdown index: offer to generate it for existing folders.
        if (markdown_newly_enabled and _backup_exists(s.Destination)
                and MessageDialog.ask_yes_no(
                    "Generate the Markdown index for your existing backup "
                    "folders now?\n\n"
                    "This writes a _Screenshot_Log.md into each game folder "
                    "covering the screenshots already backed up. Choose No to "
                    "only index screenshots backed up from here on.",
                    "Generate Index for Existing Folders?", self)):
            engine = self._app.engine
            ProgressDialog.run(self, "Generating Index…",
                               "Writing _Screenshot_Log.md files…",
                               engine.rebuild_markdown_index)

        # Turned the markdown index off: offer to remove the files it left.
        if (markdown_turned_off and self._app.engine.markdown_index_exists()
                and MessageDialog.ask_yes_no(
                    "You turned off the Markdown index. Delete the existing "
                    "_Screenshot_Log.md files?\n\n"
                    "They will be moved to the trash (recoverable). Choose No "
                    "to leave them in place.",
                    "Delete Markdown Index Files?", self)):
            engine = self._app.engine
            ProgressDialog.run(self, "Deleting Index…",
                               "Moving _Screenshot_Log.md files to the trash…",
                               engine.delete_markdown_indexes)

        # Newly enabled: offer to clean up originals that were already imported.
        if (delete_originals_newly_enabled and MessageDialog.ask_yes_no(
                "Also delete originals that were already imported?\n\n"
                "This moves every original that already has a backup to the "
                "trash now. Choose No to only delete originals of screenshots "
                "imported from here on.",
                "Apply to Already-Imported Screenshots?", self)):
            engine = self._app.engine
            ProgressDialog.run(self, "Deleting Originals…",
                               "Moving imported originals to the trash…",
                               lambda progress:
                                   engine.purge_imported_originals(progress))

    def _run_type_delete(self, t: ScreenshotType) -> None:
        engine = self._app.engine
        ProgressDialog.run(self, "Deleting Backups…",
                           f"Moving {type_label(t)} backups to the trash…",
                           lambda progress: engine.delete_type_backups(t))

    # --------------------------------------------------------------- theming

    def _apply_theme(self) -> None:
        self.setStyleSheet(Theme.stylesheet())


# ------------------------------------------------------------------ helpers

def _log_change(name: str, old_value, new_value) -> None:
    """Audit trail: one info-level log line per field that actually changed,
    naming the field and its old and new values.  Silent when unchanged."""
    if old_value != new_value:
        Logger.log(f"Setting '{name}' changed to '{new_value}' (was '{old_value}')")


def _backup_exists(dest: str) -> bool:
    try:
        root = Path(dest)
        if not root.is_dir():
            return False
        for t in (STANDARD_FOLDER, HIGH_RES_FOLDER):
            sub = root / t
            if sub.is_dir() and any(f.is_file() for f in sub.rglob("*")):
                return True
    except OSError:
        pass
    return False


def _type_backup_exists(dest: str, t: ScreenshotType) -> bool:
    try:
        root = Path(dest) / (STANDARD_FOLDER if t == ScreenshotType.STANDARD
                             else HIGH_RES_FOLDER)
        return root.is_dir() and any(f.is_file() for f in root.rglob("*"))
    except OSError:
        return False
