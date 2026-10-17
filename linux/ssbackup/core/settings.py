"""Persisted user settings.

Field names match the Windows app's settings.json exactly (PascalCase on disk)
so a settings file can be carried between the two installs.  New fields default
sensibly so files written by either app load without migration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from enum import Enum
from pathlib import Path

from . import paths


class ThemeMode(str, Enum):
    SYSTEM = "System"
    DARK = "Dark"
    LIGHT = "Light"

    @classmethod
    def parse(cls, value) -> "ThemeMode":
        # The Windows app serializes this enum as an integer (System=0, Dark=1,
        # Light=2); accept both that and the string form.
        if isinstance(value, int):
            return {0: cls.SYSTEM, 1: cls.DARK, 2: cls.LIGHT}.get(value, cls.DARK)
        if isinstance(value, str):
            for m in cls:
                if m.value.lower() == value.strip().lower():
                    return m
        return cls.DARK


def normalize_template(template: str | None) -> str:
    """Accept both separators, store POSIX-style.

    A settings.json written on Windows uses "{game}\\{yyyy}"; on Linux the same
    layout is "{game}/{yyyy}".  Normalizing on load means either file works.
    """
    if not template or not template.strip():
        return "{game}"
    return template.replace("\\", "/").strip()


@dataclass
class Settings:
    Destination: str = ""
    FirstRunDone: bool = False

    # Which screenshot types to back up.
    BackupStandard: bool = True
    BackupHighRes: bool = True

    # Optional manual location of Steam's uncompressed ("external copy")
    # screenshots, used when auto-detection from Steam's config finds nothing.
    HighResFolderOverride: str | None = None

    # When true, files deleted from the backup are automatically restored from
    # Steam (if the source still has them).  When false, deletions are only
    # logged and the user re-syncs manually from the Re-Sync window.
    AutoRestore: bool = True

    # DANGEROUS: when true, an original Steam screenshot is sent to the trash
    # once it has been successfully imported into the backup.
    DeleteOriginals: bool = False

    # Show desktop notifications for backups, restores, etc.
    ShowNotifications: bool = True

    # Set once existing backups have been given searchable metadata (one-time).
    MetadataBackfilled: bool = False

    # Append each new backup to a "_Screenshot_Log.md" in its folder.
    GenerateMarkdownIndex: bool = False

    # Show a preview of proposed changes before a batch import/reorganize.
    PreviewBeforeImport: bool = False

    # Set once the first-run catch-up preview has been offered (one-time).
    FirstImportDone: bool = False

    # Folder layout under the type folder.  Tokens: {game} {yyyy} {MM} {dd}
    FolderTemplate: str = "{game}"

    Theme: ThemeMode = ThemeMode.DARK

    # Set once existing root-level game folders have been moved under Standard/.
    StructureMigrated: bool = False

    # When true, never contact Steam's store API for game names (no network
    # calls at all).  Unrelated to the engine's destination-offline concept
    # (a NAS being unreachable) - see AppNameResolver for what this gates.
    OfflineMode: bool = False

    # Automatically check GitHub for a newer release once a day.
    CheckForUpdates: bool = True

    # The newest version already shown in an update notification, so the same
    # release doesn't renotify on every daily check.
    LastNotifiedUpdateVersion: str | None = None

    # Linux-only: manual Steam installation path, for an install this app's
    # auto-detection doesn't know about.  Empty/None = auto-detect.
    SteamPathOverride: str | None = None

    _path: Path = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------- location

    @staticmethod
    def dir() -> Path:
        return paths.config_dir()

    @staticmethod
    def file_path() -> Path:
        return paths.config_dir() / "settings.json"

    # ------------------------------------------------------------ load/save

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        fp = cls.file_path()
        try:
            if fp.is_file():
                raw = json.loads(fp.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    s._apply(raw)
        except (OSError, ValueError):
            pass

        if not s.Destination.strip():
            s.Destination = str(paths.default_destination())
        s.FolderTemplate = normalize_template(s.FolderTemplate)
        return s

    def _apply(self, raw: dict) -> None:
        known = {f.name for f in fields(self) if not f.name.startswith("_")}
        # Tolerate case differences so a hand-edited file still loads.
        lowered = {k.lower(): v for k, v in raw.items()}
        for name in known:
            if name.lower() not in lowered:
                continue
            value = lowered[name.lower()]
            if name == "Theme":
                setattr(self, name, ThemeMode.parse(value))
                continue
            current = getattr(self, name)
            if isinstance(current, bool):
                setattr(self, name, bool(value))
            elif isinstance(current, str) or current is None:
                setattr(self, name, None if value is None else str(value))
            else:
                setattr(self, name, value)

    def save(self) -> None:
        try:
            d = self.dir()
            d.mkdir(parents=True, exist_ok=True)
            payload = {}
            for f in fields(self):
                if f.name.startswith("_"):
                    continue
                value = getattr(self, f.name)
                payload[f.name] = value.value if isinstance(value, Enum) else value

            # Write through a temp file so a crash mid-write can't truncate the
            # existing settings.
            tmp = self.file_path().with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.file_path())
        except OSError:
            pass
