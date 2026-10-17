"""The heart of the app.

Watches both of Steam's screenshot stores, copies new files into the backup
structure, restores files deleted from the backup, and survives the destination
(e.g. a NAS share) going away temporarily.

Backup layout:  <destination>/<Standard|High Resolution>/<template>/<file>
where <template> defaults to "{game}" and may use {game} {yyyy} {MM} {dd}.

This is a direct port of the Windows engine, and deliberately produces the same
paths, the same filenames and the same name cache, so a Windows machine and a
Linux machine can share one destination without fighting each other.
"""

from __future__ import annotations

import errno
import os
import queue
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from . import steam_config
from .app_names import AppNameResolver
from .logger import Logger
from .markdown_index import MarkdownIndex, FILE_NAME as MD_FILE_NAME
from .metadata import has_game_name_metadata, tag_game_name
from .settings import Settings, normalize_template
from .trash import TrashError, trash_directory, trash_path

STANDARD_FOLDER = "Standard"
HIGH_RES_FOLDER = "High Resolution"

# A marker written into the destination root.  Its absence after it has once
# been seen means the volume went away and left a bare mount point behind -
# the Linux failure mode that would otherwise quietly fill the system disk.
MARKER_NAME = ".steam-screenshot-backup"


class ScreenshotType(str, Enum):
    STANDARD = "Standard"
    HIGH_RES = "HighRes"


class RunKind(str, Enum):
    STARTUP = "Startup"
    MANUAL = "Manual"
    RESTORE = "Restore"
    DESTINATION_CHANGED = "DestinationChanged"


@dataclass
class RunResult:
    """Result of one scan run: only what happened in THAT run."""
    copied: int = 0
    skipped: int = 0
    originals_deleted: int = 0
    games_affected: set = field(default_factory=set)


@dataclass
class ResyncItem:
    """A source screenshot that isn't currently in the backup and could be
    re-synced.  Surfaced by the Re-Sync window."""
    game: str
    type: ScreenshotType
    source_path: str
    dest_path: str
    timestamp: datetime
    display_name: str
    size: int = 0


@dataclass
class BackupFileEntry:
    """One entry in the granular-deletion tree."""
    path: str
    name: str
    size: int
    is_source: bool = False


# Steam's managed store:  20260706210532_1.jpg
STD_NAME = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_(\d+)(\.\w+)$")
# Steam's external copies: 646570_20260707214723_1.png
HIGH_RES_SRC_NAME = re.compile(
    r"^(\d+)_(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_(\d+)(\.\w+)$")
# Our own backup naming:   2026-07-06 21.05.32 (2).jpg
BACKUP_NAME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}\.\d{2}\.\d{2}( \(\d+\))?\.\w+$")
# The timestamp prefix of a backup name.
BACKUP_TS = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2})\.(\d{2})\.(\d{2})")
# A "game  >  name  [type]" activity-log message.
FILE_MSG_RX = re.compile(r"^(.+?)\s+›\s+(.+?)\s+\[(Standard|High resolution)\]$")
# A fallback folder name written when no source could name the game.
FALLBACK_APPID_RX = re.compile(r"^(?:AppID_|Non-Steam App )(\d+)$")

# Errors a dropped network mount raises, as opposed to "the path is simply gone".
_OFFLINE_ERRNOS = {
    errno.ESTALE, errno.EIO, errno.ENOTCONN, errno.EHOSTDOWN, errno.EHOSTUNREACH,
    errno.ENETDOWN, errno.ENETUNREACH, errno.ETIMEDOUT, errno.ECONNABORTED,
    errno.ECONNRESET, errno.EREMOTEIO, errno.EACCES, errno.EPERM,
}


def type_folder(t: ScreenshotType) -> str:
    return STANDARD_FOLDER if t == ScreenshotType.STANDARD else HIGH_RES_FOLDER


def type_label(t: ScreenshotType) -> str:
    return "Standard" if t == ScreenshotType.STANDARD else "High Resolution"


def convert_name(file_name: str, t: ScreenshotType) -> tuple[datetime | None, str | None]:
    """20260706210532_1.jpg / 646570_20260706210532_1.png
    -> (datetime, "2026-07-06 21.05.32.ext")"""
    m = (STD_NAME.match(file_name) if t == ScreenshotType.STANDARD
         else HIGH_RES_SRC_NAME.match(file_name))
    if not m:
        return None, None

    g = 1 if t == ScreenshotType.STANDARD else 2   # first timestamp group index
    parts = [m.group(i) for i in range(g, g + 6)]
    n = int(m.group(g + 6))
    ext = m.group(g + 7)
    suffix = f" ({n})" if n > 1 else ""

    try:
        ts = datetime(int(parts[0]), int(parts[1]), int(parts[2]),
                      int(parts[3]), int(parts[4]), int(parts[5]))
    except ValueError:
        return None, None
    return ts, (f"{parts[0]}-{parts[1]}-{parts[2]} "
                f"{parts[3]}.{parts[4]}.{parts[5]}{suffix}{ext}")


def expand_template(template: str | None, game: str, ts: datetime) -> str:
    """{game}/{yyyy} etc.  Each expanded segment is kept file-system safe, using
    the Windows character rules so the result matches what the Windows app
    would write into the same destination."""
    t = normalize_template(template)
    expanded = (t.replace("{game}", game)
                 .replace("{yyyy}", ts.strftime("%Y"))
                 .replace("{MM}", ts.strftime("%m"))
                 .replace("{dd}", ts.strftime("%d")))
    segments = []
    for raw in re.split(r"[\\/]", expanded):
        clean = re.sub(r'[:*?"<>|]', "", raw).strip(" .")
        if clean:
            segments.append(clean)
    return "/".join(segments)


def extract_fallback_app_id(folder_name: str) -> str | None:
    m = FALLBACK_APPID_RX.match(folder_name)
    return m.group(1) if m else None


def extract_game_segment(rel: str, template: str | None) -> str | None:
    """Given a path relative to a type folder, find the {game} segment using
    the given template (e.g. "{yyyy}/{game}" puts the game second)."""
    segments = re.split(r"[\\/]", rel)
    t_segments = re.split(r"[\\/]", normalize_template(template))
    for i, seg in enumerate(t_segments):
        if i >= len(segments) - 1:
            break
        if "{game}" in seg:
            return segments[i]
    return None


def parse_backup_timestamp(name: str) -> datetime | None:
    m = BACKUP_TS.match(name)
    if not m:
        return None
    try:
        return datetime(*(int(m.group(i)) for i in range(1, 7)))
    except ValueError:
        return None


# ----------------------------------------------------------- watcher glue

class _SourceHandler(FileSystemEventHandler):
    """Feeds new/renamed source files into the engine's copy queue."""

    def __init__(self, engine: "BackupEngine", t: ScreenshotType):
        self._engine = engine
        self._type = t

    def on_created(self, event):
        if not event.is_directory:
            self._engine._enqueue(self._type, event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._engine._enqueue(self._type, event.dest_path)


class _DestHandler(FileSystemEventHandler):
    """Reports deletions inside the backup tree."""

    def __init__(self, engine: "BackupEngine"):
        self._engine = engine

    def on_deleted(self, event):
        self._engine._on_destination_delete(event.src_path, event.is_directory)

    def on_moved(self, event):
        # A move out of the tree looks like a deletion from the backup's side.
        self._engine._on_destination_delete(event.src_path, event.is_directory)


# ----------------------------------------------------------------- engine

class BackupEngine:
    def __init__(self, settings: Settings):
        self._settings = settings

        self._steam_roots = steam_config.find_steam_paths(settings.SteamPathOverride)
        if not self._steam_roots:
            # Settings is unreachable from here - the app cannot start at all
            # without Steam - so this points at the one route that does work
            # rather than at a window the user cannot open.
            raise RuntimeError(
                "No Steam installation was found.\n\n"
                "Looked in the usual places, including a native install under "
                "~/.local/share/Steam and a Flatpak one under "
                "~/.var/app/com.valvesoftware.Steam.\n\n"
                "If Steam is installed but has never been run, start it once so "
                "it creates its userdata folder, then start this app again.\n\n"
                "If Steam lives somewhere unusual, add its path to\n"
                f"{Settings.file_path()}\n"
                'as:   { "SteamPathOverride": "/path/to/Steam" }'
            )

        self._resolver = AppNameResolver(self._steam_roots, settings)
        self._markdown = MarkdownIndex()

        self._high_res_folders: list[str] = []
        self._auto_high_res_folders: list[str] = []
        self.refresh_high_res_folders()

        self._queue: queue.Queue = queue.Queue()
        self._observers: list[Observer] = []
        self._dest_observer: Observer | None = None

        self._paused = False
        self._offline = False
        self._resync_pending = False
        self._suppress_dest_events = False
        self._disposed = False
        # The destination the marker has been seen in, or None.  Storing the
        # path rather than a bare flag means changing the backup folder can
        # never inherit the previous folder's state and misdiagnose a new,
        # correctly-empty folder as an unmounted drive.
        self._marker_seen_for: str | None = None

        self._session_files = 0
        self._session_bytes = 0
        self._stat_lock = threading.Lock()

        self._resync_timer: threading.Timer | None = None
        self._unsuppress_timer: threading.Timer | None = None
        self._offline_thread: threading.Thread | None = None
        self._offline_stop = threading.Event()

        self._notified_unresolved: set[str] = set()   # per-session

        # Listeners, mirroring the C# events.
        self.restore_needed: list = []
        self.destination_offline: list = []
        self.destination_online: list = []
        self.unresolved_game_found: list = []       # (count_new)
        self.unresolved_count_changed: list = []    # (total_still_unresolved)

        worker = threading.Thread(target=self._process_queue,
                                  name="CopyWorker", daemon=True)
        worker.start()

    # ------------------------------------------------------------ properties

    @property
    def steam_roots(self) -> list[Path]:
        return list(self._steam_roots)

    @property
    def resolver(self) -> AppNameResolver:
        return self._resolver

    @property
    def offline(self) -> bool:
        return self._offline

    @property
    def session_files(self) -> int:
        with self._stat_lock:
            return self._session_files

    @property
    def session_bytes(self) -> int:
        with self._stat_lock:
            return self._session_bytes

    @property
    def destination(self) -> str:
        return self._settings.Destination

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        self._paused = value

    @property
    def high_res_source_available(self) -> bool:
        return len(self._high_res_folders) > 0

    @property
    def high_res_auto_detected(self) -> bool:
        return len(self._auto_high_res_folders) > 0

    @property
    def auto_detected_high_res_folder(self) -> str | None:
        return self._auto_high_res_folders[0] if self._auto_high_res_folders else None

    def _fire(self, listeners: list, *args) -> None:
        for fn in list(listeners):
            try:
                fn(*args)
            except Exception as ex:
                Logger.warn(f"Event handler failed: {ex}")

    # --------------------------------------------------------------- sources

    def refresh_high_res_folders(self) -> None:
        """Rebuilds the high-resolution source list from Steam's config plus
        any manual override the user set."""
        self._auto_high_res_folders = steam_config.find_high_res_folders(self._steam_roots)

        combined = list(self._auto_high_res_folders)
        manual = (self._settings.HighResFolderOverride or "").strip()
        if manual:
            manual = os.path.expanduser(manual)
            if not any(os.path.normpath(f) == os.path.normpath(manual) for f in combined):
                combined.append(manual)
        self._high_res_folders = combined

    def rescan_steam_installs(self) -> None:
        self._steam_roots = steam_config.find_steam_paths(self._settings.SteamPathOverride)
        self._resolver.set_steam_roots(self._steam_roots)
        self.refresh_high_res_folders()

    # -------------------------------------------------------------- watching

    def start_watching(self) -> None:
        if self._settings.BackupStandard:
            for userdata in steam_config.userdata_dirs(self._steam_roots):
                self._add_observer(str(userdata),
                                   _SourceHandler(self, ScreenshotType.STANDARD),
                                   recursive=True, label="Steam")

        if self._settings.BackupHighRes:
            for folder in self._high_res_folders:
                if os.path.isdir(folder):
                    self._add_observer(folder,
                                       _SourceHandler(self, ScreenshotType.HIGH_RES),
                                       recursive=False, label="High-res")

        self.watch_destination()

    def _add_observer(self, path: str, handler, recursive: bool, label: str) -> None:
        try:
            obs = Observer()
            obs.schedule(handler, path, recursive=recursive)
            obs.start()
            self._observers.append(obs)
        except OSError as ex:
            # inotify watch limits are the usual cause; the catch-up scans still
            # work, so this degrades rather than failing outright.
            Logger.error(f"{label} watcher could not start on {path}: {ex}")

    def restart_watching(self) -> None:
        """Re-arms all source watchers, e.g. after screenshot types were
        toggled or the destination moved."""
        self.refresh_high_res_folders()
        for obs in self._observers:
            try:
                obs.stop()
            except Exception:
                pass
        for obs in self._observers:
            try:
                obs.join(timeout=2)
            except Exception:
                pass
        self._observers.clear()
        self.start_watching()

    def _enqueue(self, t: ScreenshotType, full_path: str) -> None:
        if self._paused or self._disposed:
            return
        name = os.path.basename(full_path)

        if t == ScreenshotType.STANDARD:
            if not self._settings.BackupStandard:
                return
            if not STD_NAME.match(name):
                return
            parent = os.path.basename(os.path.dirname(full_path))
            if parent.lower() != "screenshots":   # excludes thumbnails/
                return
            if "/760/remote/" not in full_path.replace("\\", "/"):
                return
        else:
            if not self._settings.BackupHighRes:
                return
            if not HIGH_RES_SRC_NAME.match(name):
                return

        self._queue.put((t, full_path))

    def _process_queue(self) -> None:
        while True:
            try:
                item = self._queue.get()
            except Exception:
                return
            if item is None or self._disposed:
                return
            t, path = item
            try:
                self._wait_while_offline()
                if self._disposed:
                    return
                if not _wait_for_stable_file(path):
                    continue   # vanished, or never finished writing

                if t == ScreenshotType.STANDARD:
                    # .../<appid>/screenshots/<file>
                    appid = os.path.basename(os.path.dirname(os.path.dirname(path)))
                    self._copy_one(path, appid, ScreenshotType.STANDARD, restore=False)
                else:
                    m = HIGH_RES_SRC_NAME.match(os.path.basename(path))
                    if m:
                        self._copy_one(path, m.group(1), ScreenshotType.HIGH_RES,
                                       restore=False)
            except Exception as ex:
                Logger.error(f"Copy failed for {path}: {ex}")

    # --------------------------------------------------------------- copying

    def _copy_one(self, src: str, appid: str, t: ScreenshotType,
                  restore: bool, run: RunResult | None = None) -> bool:
        """Converts a source name to the readable backup name and copies it if
        it isn't already in the backup.  The size check uses >= because metadata
        tagging makes the backup copy slightly larger than the source."""
        game = self._resolver.resolve_folder_name(appid)
        ts, dest_name = convert_name(os.path.basename(src), t)
        if not dest_name:
            return False

        dest_dir = os.path.join(self.destination, type_folder(t),
                                expand_template(self._settings.FolderTemplate, game, ts))
        dest = os.path.join(dest_dir, dest_name)

        try:
            src_size = os.path.getsize(src)
        except OSError:
            return False

        if os.path.exists(dest):
            try:
                if os.path.getsize(dest) >= src_size:
                    if run is not None:
                        run.skipped += 1
                    return False   # already backed up
            except OSError:
                pass

        if not self._check_destination_available():
            return False

        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(src, dest)   # preserves the original timestamps
        tag_game_name(dest, game)

        try:
            copied_size = os.path.getsize(dest)
        except OSError:
            copied_size = src_size
        with self._stat_lock:
            self._session_files += 1
            self._session_bytes += copied_size

        detail = f"{game}  ›  {dest_name}  [{type_label(t)}]"
        if restore:
            Logger.restore(detail, dest)
        else:
            Logger.backup(detail, dest)

        if run is not None:
            run.copied += 1
            run.games_affected.add(game)

        # Markdown index: only for genuinely new backups, not restores (which
        # would otherwise duplicate an entry the log already has).
        if not restore and self._settings.GenerateMarkdownIndex:
            self._markdown.append(dest, ts)

        # Dangerous, opt-in: remove the just-imported original.
        self._delete_original_to_trash(src, dest, run)
        return True

    def _delete_original_to_trash(self, src: str, dest: str,
                                  run: RunResult | None) -> None:
        """Sends a successfully-imported original to the trash, but only when
        the backup copy is provably present and complete.  Never permanent, so
        a mistake is always recoverable."""
        if not self._settings.DeleteOriginals:
            return
        try:
            if not os.path.exists(src):
                return
            if not os.path.exists(dest):
                return
            if os.path.getsize(dest) < os.path.getsize(src):
                return
            trash_path(src)
            if run is not None:
                run.originals_deleted += 1
            else:
                Logger.log("Deleted original after import (moved to the trash): "
                           + os.path.basename(src))
        except (OSError, TrashError) as ex:
            Logger.warn(f"Could not delete original {os.path.basename(src)}: {ex}")

    # -------------------------------------------------------------- scanning

    def enumerate_sources(self):
        """Every valid screenshot across all enabled sources.  Shared by the
        scanner and the missing-from-backup finder so they always agree on what
        counts."""
        if self._settings.BackupStandard:
            for userdata in steam_config.userdata_dirs(self._steam_roots):
                try:
                    users = sorted(userdata.iterdir())
                except OSError:
                    continue
                for user in users:
                    remote = user / "760" / "remote"
                    if not remote.is_dir():
                        continue
                    try:
                        app_dirs = sorted(remote.iterdir())
                    except OSError:
                        continue
                    for app_dir in app_dirs:
                        src_dir = app_dir / "screenshots"
                        if not src_dir.is_dir():
                            continue
                        appid = app_dir.name
                        try:
                            entries = sorted(src_dir.iterdir())
                        except OSError:
                            continue
                        for f in entries:   # top level only; skips thumbnails/
                            if f.is_file() and STD_NAME.match(f.name):
                                yield str(f), appid, ScreenshotType.STANDARD

        if self._settings.BackupHighRes:
            for folder in self._high_res_folders:
                p = Path(folder)
                if not p.is_dir():
                    continue
                try:
                    entries = sorted(p.iterdir())
                except OSError:
                    continue
                for f in entries:
                    if not f.is_file():
                        continue
                    m = HIGH_RES_SRC_NAME.match(f.name)
                    if m:
                        yield str(f), m.group(1), ScreenshotType.HIGH_RES

    def full_scan(self, restore: bool = False) -> RunResult | None:
        """One full pass over every enabled source.  Returns what THIS run did,
        or None when the destination is offline."""
        if not self._check_destination_available():
            return None
        run = RunResult()
        for path, appid, t in self.enumerate_sources():
            try:
                self._copy_one(path, appid, t, restore, run)
            except Exception as ex:
                Logger.error(f"Copy failed for {path}: {ex}")
        if run.originals_deleted > 0:
            Logger.log(f"Deleted {run.originals_deleted} imported original"
                       f"{'' if run.originals_deleted == 1 else 's'} "
                       "(moved to the trash).")
        self._scan_for_untracked_appid_folders()
        return run

    def _scan_for_untracked_appid_folders(self) -> None:
        """Looks for existing backup folders that fell back to an unresolved
        appid name and retries resolution now, in case a manifest, shortcut, or
        the store can identify it today."""
        seen: set[str] = set()
        newly_unresolved = 0
        still_unresolved = 0
        try:
            for folder in (STANDARD_FOLDER, HIGH_RES_FOLDER):
                root = Path(self.destination) / folder
                if not root.is_dir():
                    continue
                # Depth varies with the folder-layout template, so check every level.
                for d in root.rglob("*"):
                    if not d.is_dir():
                        continue
                    appid = extract_fallback_app_id(d.name)
                    if appid is None or appid in seen or self._resolver.is_tracked(appid):
                        continue
                    seen.add(appid)

                    resolved = self._resolver.try_resolve_now(appid)
                    if resolved:
                        Logger.log(f"Detected existing backup game folder: "
                                   f"{resolved} ({appid})")
                        self._notified_unresolved.discard(appid)
                    else:
                        still_unresolved += 1
                        if appid not in self._notified_unresolved:
                            self._notified_unresolved.add(appid)
                            newly_unresolved += 1
                            Logger.warn(
                                f"Game folder could not be named automatically: "
                                f"{d.name} ({appid}) — open Game Names to identify it.")
        except OSError as ex:
            Logger.warn(f"App ID tracking scan failed: {ex}")

        if newly_unresolved > 0:
            self._fire(self.unresolved_game_found, newly_unresolved)
        self._fire(self.unresolved_count_changed, still_unresolved)

    def find_unresolved_game_folders(self) -> list[tuple[str, str]]:
        """The still-unresolved (appid, folder) pairs, so the Game Names window
        can point the user at the actual screenshots."""
        result: list[tuple[str, str]] = []
        seen: set[str] = set()
        try:
            for folder in (STANDARD_FOLDER, HIGH_RES_FOLDER):
                root = Path(self.destination) / folder
                if not root.is_dir():
                    continue
                for d in root.rglob("*"):
                    if not d.is_dir():
                        continue
                    appid = extract_fallback_app_id(d.name)
                    if appid is None or appid in seen or self._resolver.is_tracked(appid):
                        continue
                    seen.add(appid)
                    result.append((appid, str(d)))
        except OSError as ex:
            Logger.warn(f"Unresolved game folder scan failed: {ex}")
        return result

    def purge_imported_originals(self, progress=None,
                                 t: ScreenshotType | None = None) -> int:
        """Retroactive one-shot for "delete originals after import": sends every
        original that already has a verified backup to the trash."""
        sources = [s for s in self.enumerate_sources() if t is None or s[2] == t]
        deleted = 0
        done = 0
        for path, appid, src_type in sources:
            try:
                game = self._resolver.resolve_folder_name(appid)
                ts, dest_name = convert_name(os.path.basename(path), src_type)
                if dest_name:
                    dest = os.path.join(
                        self.destination, type_folder(src_type),
                        expand_template(self._settings.FolderTemplate, game, ts),
                        dest_name)
                    if (os.path.exists(path) and os.path.exists(dest)
                            and os.path.getsize(dest) >= os.path.getsize(path)):
                        trash_path(path)
                        deleted += 1
            except (OSError, TrashError) as ex:
                Logger.warn(f"Could not delete original {os.path.basename(path)}: {ex}")
            done += 1
            if progress:
                progress(done, len(sources))
        if deleted > 0:
            Logger.log(f"Retroactively deleted {deleted} imported original"
                       f"{'' if deleted == 1 else 's'} (moved to the trash).")
        return deleted

    # ---------------------------------------------------- markdown / paths

    def rebuild_markdown_index(self, progress=None) -> int:
        """Rebuilds "_Screenshot_Log.md" for every backup folder from the images
        it contains.  Returns the number of folders written."""
        by_dir: dict[str, list[tuple[str, datetime]]] = {}
        try:
            for folder in (STANDARD_FOLDER, HIGH_RES_FOLDER):
                root = Path(self.destination) / folder
                if not root.is_dir():
                    continue
                for f in root.rglob("*"):
                    if not f.is_file() or not BACKUP_NAME.match(f.name):
                        continue
                    ts = parse_backup_timestamp(f.name)
                    if ts is None:
                        try:
                            ts = datetime.fromtimestamp(f.stat().st_mtime)
                        except OSError:
                            continue
                    by_dir.setdefault(str(f.parent), []).append((f.name, ts))

            done = 0
            for directory, images in by_dir.items():
                images.sort(key=lambda x: x[1])
                self._markdown.rebuild(directory, images)
                done += 1
                if progress:
                    progress(done, len(by_dir))
        except OSError as ex:
            Logger.warn(f"Markdown rebuild error: {ex}")
        if by_dir:
            Logger.log(f"Generated the Markdown index in {len(by_dir)} "
                       f"folder{'' if len(by_dir) == 1 else 's'}.")
        return len(by_dir)

    def markdown_index_exists(self) -> bool:
        try:
            for folder in (STANDARD_FOLDER, HIGH_RES_FOLDER):
                root = Path(self.destination) / folder
                if root.is_dir() and next(root.rglob(MD_FILE_NAME), None) is not None:
                    return True
        except OSError:
            pass
        return False

    def delete_markdown_indexes(self, progress=None) -> int:
        """Sends every "_Screenshot_Log.md" under the backup to the trash."""
        files: list[Path] = []
        try:
            for folder in (STANDARD_FOLDER, HIGH_RES_FOLDER):
                root = Path(self.destination) / folder
                if root.is_dir():
                    files.extend(root.rglob(MD_FILE_NAME))
        except OSError as ex:
            Logger.warn(f"Markdown index scan failed: {ex}")

        deleted = 0
        done = 0
        for f in files:
            try:
                trash_path(f)
                deleted += 1
            except (OSError, TrashError) as ex:
                Logger.warn(f"Could not delete {f.name}: {ex}")
            done += 1
            if progress:
                progress(done, len(files))
        if deleted > 0:
            Logger.log(f"Deleted {deleted} Markdown index file"
                       f"{'' if deleted == 1 else 's'} (moved to the trash).")
        return deleted

    def backup_path_from_log_message(self, message: str) -> str | None:
        """Reconstructs the on-disk path of a log entry from its message text,
        so rows loaded from older log files can still be revealed."""
        if not message:
            return None
        m = FILE_MSG_RX.match(message)
        if not m:
            return None
        game = m.group(1).strip()
        dest_name = m.group(2).strip()
        t = (ScreenshotType.STANDARD if m.group(3) == "Standard"
             else ScreenshotType.HIGH_RES)
        ts = parse_backup_timestamp(dest_name) or datetime.min
        return os.path.join(self.destination, type_folder(t),
                            expand_template(self._settings.FolderTemplate, game, ts),
                            dest_name)

    # ------------------------------------------------ re-sync missing files

    def find_missing_from_backup(self) -> list[ResyncItem]:
        """Source screenshots that have no counterpart in the backup right now."""
        missing: list[ResyncItem] = []
        if not self._check_destination_available():
            return missing

        for path, appid, t in self.enumerate_sources():
            try:
                game = self._resolver.resolve_folder_name(appid)
                ts, dest_name = convert_name(os.path.basename(path), t)
                if not dest_name:
                    continue
                dest = os.path.join(
                    self.destination, type_folder(t),
                    expand_template(self._settings.FolderTemplate, game, ts), dest_name)
                if os.path.exists(dest):
                    continue   # already backed up

                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = 0
                missing.append(ResyncItem(game=game, type=t, source_path=path,
                                          dest_path=dest, timestamp=ts,
                                          display_name=dest_name, size=size))
            except OSError:
                continue
        return missing

    def resync(self, items: list[ResyncItem], progress=None) -> int:
        """Copies the selected missing items back into the backup, logging each
        as a restore."""
        copied = 0
        done = 0
        for it in items:
            try:
                if not self._check_destination_available():
                    break
                if os.path.exists(it.source_path) and not os.path.exists(it.dest_path):
                    os.makedirs(os.path.dirname(it.dest_path), exist_ok=True)
                    shutil.copy2(it.source_path, it.dest_path)
                    tag_game_name(it.dest_path, it.game)
                    try:
                        size = os.path.getsize(it.dest_path)
                    except OSError:
                        size = it.size
                    with self._stat_lock:
                        self._session_files += 1
                        self._session_bytes += size
                    Logger.restore(
                        f"{it.game}  ›  {it.display_name}  [{type_label(it.type)}]",
                        it.dest_path)
                    copied += 1
            except OSError as ex:
                Logger.error(f"Re-sync failed for {it.source_path}: {ex}")
            done += 1
            if progress:
                progress(done, len(items))
        if copied > 0:
            Logger.log(f"Re-synced {copied} file{'' if copied == 1 else 's'} "
                       "back to the backup.")
        return copied

    # ------------------------------------------------- backup folder totals

    def compute_totals(self) -> tuple[int, int, int]:
        """Counts everything currently in the backup (all-time totals)."""
        games: set[str] = set()
        files = 0
        total = 0
        try:
            for folder in (STANDARD_FOLDER, HIGH_RES_FOLDER):
                root = Path(self.destination) / folder
                if not root.is_dir():
                    continue
                for f in root.rglob("*"):
                    if not f.is_file() or not BACKUP_NAME.match(f.name):
                        continue
                    files += 1
                    try:
                        total += f.stat().st_size
                    except OSError:
                        pass
                    game = self._extract_game_from_rel(str(f.relative_to(root)))
                    if game:
                        games.add(game.lower())
        except OSError:
            pass
        return len(games), files, total

    def backfill_metadata(self) -> int:
        """One-time: add searchable game-name metadata to existing backups that
        predate the metadata feature.  Already-tagged files are skipped with a
        cheap header check."""
        tagged = 0
        try:
            for folder in (STANDARD_FOLDER, HIGH_RES_FOLDER):
                root = Path(self.destination) / folder
                if not root.is_dir():
                    continue
                for f in root.rglob("*"):
                    if self._disposed:
                        return tagged
                    if not f.is_file():
                        continue
                    if f.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                        continue
                    if not BACKUP_NAME.match(f.name):
                        continue
                    if has_game_name_metadata(f):
                        continue
                    game = self._extract_game_from_rel(str(f.relative_to(root)))
                    if not game:
                        continue
                    tag_game_name(f, game)
                    tagged += 1
        except OSError as ex:
            Logger.warn(f"Metadata backfill error: {ex}")
        if tagged > 0:
            Logger.log(f"Added searchable metadata to {tagged} existing backup "
                       f"file{'' if tagged == 1 else 's'}.")
        return tagged

    def delete_type_backups(self, t: ScreenshotType) -> int:
        """Sends an entire screenshot-type backup tree to the trash."""
        root = Path(self.destination) / type_folder(t)
        if not root.is_dir():
            return 0

        files = 0
        try:
            files = sum(1 for f in root.rglob("*") if f.is_file())
        except OSError:
            pass

        self._suppress_dest_events = True
        try:
            trash_directory(root)
            Logger.log(f"Deleted {files} {type_label(t)} backup "
                       f"file{'' if files == 1 else 's'} (moved to the trash).")
        except (OSError, TrashError) as ex:
            Logger.error(f"Could not delete {type_label(t)} backups: {ex}")
        finally:
            self._schedule_unsuppress()
        return files

    def preview_type_backups(self, t: ScreenshotType) -> tuple[int, int]:
        return _count_and_size(Path(self.destination) / type_folder(t), "*")

    def preview_markdown_indexes(self) -> tuple[int, int]:
        count = 0
        total = 0
        for folder in (STANDARD_FOLDER, HIGH_RES_FOLDER):
            c, b = _count_and_size(Path(self.destination) / folder, MD_FILE_NAME)
            count += c
            total += b
        return count, total

    def preview_purge_imported_originals(
            self, t: ScreenshotType | None = None) -> tuple[int, int]:
        count = 0
        total = 0
        for path, appid, src_type in self.enumerate_sources():
            if t is not None and src_type != t:
                continue
            try:
                game = self._resolver.resolve_folder_name(appid)
                ts, dest_name = convert_name(os.path.basename(path), src_type)
                if not dest_name:
                    continue
                dest = os.path.join(
                    self.destination, type_folder(src_type),
                    expand_template(self._settings.FolderTemplate, game, ts), dest_name)
                if not os.path.exists(path) or not os.path.exists(dest):
                    continue
                src_size = os.path.getsize(path)
                if os.path.getsize(dest) < src_size:
                    continue
                count += 1
                total += src_size
            except OSError:
                continue
        return count, total

    # -------------------------------------------------- granular deletion

    def get_backup_tree(self) -> dict:
        """The whole backup, grouped by type then game.  Only files matching our
        own backup naming are included (skips _Screenshot_Log.md and anything
        else that doesn't belong to us)."""
        result: dict[ScreenshotType, dict[str, list[BackupFileEntry]]] = {}
        for t in (ScreenshotType.STANDARD, ScreenshotType.HIGH_RES):
            root = Path(self.destination) / type_folder(t)
            by_game: dict[str, list[BackupFileEntry]] = {}
            if root.is_dir():
                try:
                    for f in sorted(root.rglob("*")):
                        if not f.is_file() or not BACKUP_NAME.match(f.name):
                            continue
                        game = (self._extract_game_from_rel(str(f.relative_to(root)))
                                or "(unknown)")
                        try:
                            size = f.stat().st_size
                        except OSError:
                            size = 0
                        by_game.setdefault(game, []).append(
                            BackupFileEntry(str(f), f.name, size, False))
                except OSError:
                    pass
            result[t] = by_game
        return result

    def get_steam_source_tree(self) -> dict:
        """Steam's own screenshot files, grouped the same way get_backup_tree
        groups the backup copy."""
        result: dict[ScreenshotType, dict[str, list[BackupFileEntry]]] = {}
        for path, appid, t in self.enumerate_sources():
            by_game = result.setdefault(t, {})
            game = self._resolver.resolve_folder_name(appid)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            by_game.setdefault(game, []).append(
                BackupFileEntry(path, os.path.basename(path), size, True))
        return result

    def delete_files(self, paths: list[str], progress=None,
                     label: str = "backup file") -> int:
        """Sends a specific set of files to the trash."""
        deleted = 0
        done = 0
        self._suppress_dest_events = True
        try:
            for f in paths:
                try:
                    trash_path(f)
                    deleted += 1
                except (OSError, TrashError) as ex:
                    Logger.warn(f"Could not delete {os.path.basename(f)}: {ex}")
                done += 1
                if progress:
                    progress(done, len(paths))
            if deleted > 0:
                Logger.log(f"Deleted {deleted} selected {label}"
                           f"{'' if deleted == 1 else 's'} (moved to the trash).")
        finally:
            self._schedule_unsuppress()
        return deleted

    def _extract_game_from_rel(self, rel: str) -> str | None:
        game = extract_game_segment(rel, self._settings.FolderTemplate)
        if game:
            return game
        segments = re.split(r"[\\/]", rel)
        return segments[0] if len(segments) > 1 else None

    # ---------------------------------------------- destination watching

    def watch_destination(self) -> None:
        """Watches the backup destination so deletions are logged and restored."""
        try:
            if self._dest_observer is not None:
                try:
                    self._dest_observer.stop()
                    self._dest_observer.join(timeout=2)
                except Exception:
                    pass
                self._dest_observer = None

            dest = Path(self.destination)
            if not dest.is_dir():
                dest.mkdir(parents=True, exist_ok=True)

            obs = Observer()
            obs.schedule(_DestHandler(self), str(dest), recursive=True)
            obs.start()
            self._dest_observer = obs
        except OSError as ex:
            Logger.warn(f"Could not watch the backup folder for deletions: {ex}")
            self._check_destination_available()   # probably offline; start retrying

    def _on_destination_delete(self, full_path: str, is_directory: bool) -> None:
        if self._paused or self._suppress_dest_events or not full_path:
            return
        try:
            rel = os.path.relpath(full_path, self.destination)
        except ValueError:
            return
        if rel.startswith(".."):
            return

        segments = [s for s in re.split(r"[\\/]", rel) if s]
        if not segments:
            return
        std = segments[0].lower() == STANDARD_FOLDER.lower()
        hr = segments[0].lower() == HIGH_RES_FOLDER.lower()
        if not std and not hr:
            return

        label = "Standard" if std else "High resolution"
        last = segments[-1]
        if len(segments) == 1:
            Logger.deletion(f"{label} backup folder removed", full_path)
        elif BACKUP_NAME.match(last):
            game = self._extract_game_from_rel("/".join(segments[1:]))
            Logger.deletion(f"{game or segments[1]}  ›  {last}  [{label}]", full_path)
        elif not os.path.splitext(last)[1]:
            Logger.deletion(f"{last}  ›  folder removed  [{label}]", full_path)
        else:
            return   # some unrelated file; not ours

        # Auto-restore is optional; when off, the deletion is still logged above
        # but the user re-syncs manually from the Re-Sync window.
        if not self._settings.AutoRestore:
            return

        if not self._resync_pending:
            self._resync_pending = True
            Logger.log("Restoring deleted backup files shortly…")

        # Debounce: a folder delete fires one event per file, so wait for quiet.
        if self._resync_timer is not None:
            self._resync_timer.cancel()
        self._resync_timer = threading.Timer(5.0, self._fire_restore_needed)
        self._resync_timer.daemon = True
        self._resync_timer.start()

    def _fire_restore_needed(self) -> None:
        self._resync_pending = False
        self._fire(self.restore_needed)

    def _schedule_unsuppress(self) -> None:
        """Re-enable dest events after a beat, to swallow trailing deletes."""
        if self._unsuppress_timer is not None:
            self._unsuppress_timer.cancel()
        self._unsuppress_timer = threading.Timer(
            3.0, lambda: setattr(self, "_suppress_dest_events", False))
        self._unsuppress_timer.daemon = True
        self._unsuppress_timer.start()

    # -------------------------------------------------------- NAS resiliency

    def _check_destination_available(self) -> bool:
        """True while the destination is genuinely reachable.

        Windows could just probe the drive root.  On Linux a dropped NFS/SMB
        mount usually leaves the mount point behind as an ordinary empty
        directory, so an existence check alone would happily start writing the
        backup onto the system disk.  The marker file below is what tells the
        two situations apart.
        """
        available, reason = self._probe_destination()

        if available:
            if self._offline:
                self._offline = False
                Logger.log("Backup destination is reachable again.")
                self._offline_stop.set()
                self.watch_destination()
                self._fire(self.destination_online)
            return True

        if not self._offline:
            self._offline = True
            Logger.warn(f"Backup destination is unreachable ({reason}). "
                        "Backups are queued and will resume automatically.")
            self._fire(self.destination_offline)
            self._start_offline_retry()
        return False

    def _probe_destination(self) -> tuple[bool, str]:
        dest = Path(self.destination)
        marker = dest / MARKER_NAME

        try:
            if not dest.is_dir():
                # Not yet created, or the volume it lives on went away.  Walk up
                # to the nearest directory that does exist: creating the backup
                # folder is only safe if something real is there to create it
                # under.  A dropped mount usually leaves a root-owned mount
                # point, which fails the writability check below.
                anchor = dest.parent
                while not anchor.is_dir() and anchor != anchor.parent:
                    anchor = anchor.parent
                if not anchor.is_dir():
                    return False, "no part of the path exists"
                if not os.access(anchor, os.W_OK):
                    return False, f"{anchor} is not writable"
                try:
                    dest.mkdir(parents=True, exist_ok=True)
                except OSError as ex:
                    return False, f"the folder could not be created: {ex.strerror or ex}"

            if not os.access(dest, os.W_OK):
                return False, "the folder is not writable"

            if marker.is_file():
                self._marker_seen_for = str(dest)
                return True, ""

            if self._marker_seen_for == str(dest):
                # We have written the marker before and it is gone while the
                # folder itself still exists: the volume was unmounted and this
                # is the bare mount point.
                return False, "the drive appears to have been unmounted"

            # First successful look at this destination - claim it.
            try:
                marker.write_text(
                    "This folder is managed by Steam Screenshot Backup.\n"
                    "It uses this file to tell a mounted drive apart from an empty\n"
                    "mount point, so deleting it is harmless but not useful.\n",
                    encoding="utf-8",
                )
                self._marker_seen_for = str(dest)
            except OSError as ex:
                return False, f"the folder could not be written to: {ex.strerror or ex}"
            return True, ""

        except OSError as ex:
            if ex.errno in _OFFLINE_ERRNOS:
                return False, f"I/O error: {ex.strerror or ex}"
            return False, str(ex)

    def _start_offline_retry(self) -> None:
        self._offline_stop = threading.Event()
        stop = self._offline_stop

        def loop():
            while not stop.wait(20.0):
                if self._disposed:
                    return
                if self._check_destination_available():
                    return

        self._offline_thread = threading.Thread(
            target=loop, name="DestinationRetry", daemon=True)
        self._offline_thread.start()

    def _wait_while_offline(self) -> None:
        while self._offline and not self._disposed:
            time.sleep(2)

    # ------------------------------------------------------------ migrations

    def migrate_structure_if_needed(self) -> None:
        """One-time upgrade: older versions put game folders directly in the
        backup root; move them under "Standard/"."""
        if self._settings.StructureMigrated:
            return
        try:
            dest = Path(self.destination)
            if dest.is_dir():
                self._suppress_dest_events = True
                moved = 0
                std_root = dest / STANDARD_FOLDER
                for d in sorted(dest.iterdir()):
                    if not d.is_dir():
                        continue
                    if d.name.lower() in (STANDARD_FOLDER.lower(),
                                          HIGH_RES_FOLDER.lower()):
                        continue
                    # Only move folders that actually look like our game backups.
                    try:
                        if not any(f.is_file() and BACKUP_NAME.match(f.name)
                                   for f in d.iterdir()):
                            continue
                    except OSError:
                        continue

                    std_root.mkdir(parents=True, exist_ok=True)
                    target = std_root / d.name
                    if not target.exists():
                        shutil.move(str(d), str(target))
                        moved += 1
                if moved > 0:
                    Logger.log(f"Upgraded backup layout: moved {moved} game "
                               f'folders under "{STANDARD_FOLDER}/".')
            self._settings.StructureMigrated = True
            self._settings.save()
        except OSError as ex:
            Logger.error(f"Backup layout upgrade failed: {ex}")
        finally:
            self._suppress_dest_events = False

    def move_backup(self, old_dest: str, new_dest: str, progress=None) -> None:
        """Moves the whole backup to a new destination."""
        self._suppress_dest_events = True
        try:
            files: list[Path] = []
            for folder in (STANDARD_FOLDER, HIGH_RES_FOLDER):
                root = Path(old_dest) / folder
                if root.is_dir():
                    files.extend(f for f in root.rglob("*") if f.is_file())

            done = 0
            for src in files:
                rel = src.relative_to(old_dest)
                dest = Path(new_dest) / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    shutil.move(str(src), str(dest))   # falls back to copy+delete
                else:
                    try:
                        src.unlink()   # already present at target
                    except OSError:
                        pass
                done += 1
                if progress:
                    progress(done, len(files))

            # Clean the now-empty tree at the old location.
            for folder in (STANDARD_FOLDER, HIGH_RES_FOLDER):
                root = Path(old_dest) / folder
                if root.is_dir():
                    _delete_empty_tree(root)
            Logger.log(f"Migrated {len(files)} backup files to {new_dest}")
        finally:
            self._suppress_dest_events = False
            self._marker_seen_for = None   # the new destination needs its own marker

    # --------------------------------------------------- preview / dry-run

    def plan_scan(self) -> list[tuple[str, str]]:
        """What a catch-up scan would import right now.  Resolving names may hit
        the store API, so callers run this off the UI thread."""
        plan: list[tuple[str, str]] = []
        if not self._check_destination_available():
            return plan
        for path, appid, t in self.enumerate_sources():
            try:
                game = self._resolver.resolve_folder_name(appid)
                ts, dest_name = convert_name(os.path.basename(path), t)
                if not dest_name:
                    continue
                dest = os.path.join(
                    self.destination, type_folder(t),
                    expand_template(self._settings.FolderTemplate, game, ts), dest_name)
                if (os.path.exists(dest)
                        and os.path.getsize(dest) >= os.path.getsize(path)):
                    continue
                plan.append((path, dest))
            except OSError:
                continue
        return plan

    def plan_reorganize(self, old_template: str,
                        new_template: str) -> list[tuple[str, str]]:
        """The moves a template change would make."""
        plan: list[tuple[str, str]] = []
        for folder in (STANDARD_FOLDER, HIGH_RES_FOLDER):
            root = Path(self.destination) / folder
            if not root.is_dir():
                continue
            try:
                candidates = sorted(root.rglob("*"))
            except OSError:
                continue
            for src in candidates:
                if not src.is_file() or not BACKUP_NAME.match(src.name):
                    continue
                game = extract_game_segment(str(src.relative_to(root)), old_template)
                if not game:
                    continue
                ts = parse_backup_timestamp(src.name)
                if ts is None:
                    continue
                new_rel = expand_template(new_template, game, ts)
                dest = root / new_rel / src.name
                if str(dest) != str(src):
                    plan.append((str(src), str(dest)))
        return plan

    def reorganize_layout(self, old_template: str, new_template: str) -> None:
        """Re-shapes the existing backup when the folder template changes.
        Unrecognized files are left alone."""
        self._suppress_dest_events = True
        try:
            moved = 0
            for src, dest in self.plan_reorganize(old_template, new_template):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                if not os.path.exists(dest):
                    shutil.move(src, dest)
                    moved += 1
            for folder in (STANDARD_FOLDER, HIGH_RES_FOLDER):
                root = Path(self.destination) / folder
                if root.is_dir():
                    _delete_empty_tree(root, keep_root=True)
            if moved > 0:
                Logger.log(f"Reorganized {moved} backup files into the new "
                           "folder layout.")
        except OSError as ex:
            Logger.error(f"Layout reorganization failed: {ex}")
        finally:
            self._suppress_dest_events = False

    # -------------------------------------------------------------- teardown

    def dispose(self) -> None:
        self._disposed = True
        self._offline_stop.set()
        for obs in self._observers:
            try:
                obs.stop()
            except Exception:
                pass
        if self._dest_observer is not None:
            try:
                self._dest_observer.stop()
            except Exception:
                pass
        for timer in (self._resync_timer, self._unsuppress_timer):
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    pass
        if self._resolver is not None:
            self._resolver.dispose()
        try:
            self._queue.put(None)
        except Exception:
            pass
        for obs in self._observers:
            try:
                obs.join(timeout=2)
            except Exception:
                pass
        if self._dest_observer is not None:
            try:
                self._dest_observer.join(timeout=2)
            except Exception:
                pass


# ------------------------------------------------------------------ helpers

def _wait_for_stable_file(path: str) -> bool:
    """Steam may still be writing when the event fires; wait until the size
    stops changing.  Linux has no exclusive-open equivalent to the Windows
    check, so this watches for a quiet period instead."""
    last_size = -1
    stable_rounds = 0
    for _ in range(60):   # up to ~15 s
        try:
            if not os.path.exists(path):
                return False
            size = os.path.getsize(path)
            if size > 0 and size == last_size:
                stable_rounds += 1
                if stable_rounds >= 2:   # ~500 ms unchanged
                    return True
            else:
                stable_rounds = 0
            last_size = size
        except OSError:
            pass
        time.sleep(0.25)
    Logger.warn(f"File never settled, attempting copy anyway: {path}")
    return os.path.exists(path)


def _count_and_size(root: Path, pattern: str) -> tuple[int, int]:
    count = 0
    total = 0
    if root.is_dir():
        try:
            for f in root.rglob(pattern):
                if not f.is_file():
                    continue
                count += 1
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
        except OSError:
            pass
    return count, total


def _delete_empty_tree(root: Path, keep_root: bool = False) -> None:
    try:
        for d in sorted(root.iterdir()):
            if d.is_dir():
                _delete_empty_tree(d)
        if not keep_root and not any(root.iterdir()):
            root.rmdir()
    except OSError:
        pass


def format_bytes(b: int) -> str:
    if b >= 1 << 30:
        return f"{b / (1 << 30):.1f} GB"
    if b >= 1 << 20:
        return f"{b / (1 << 20):.1f} MB"
    if b >= 1 << 10:
        return f"{b / (1 << 10):.1f} KB"
    return f"{b} B"
