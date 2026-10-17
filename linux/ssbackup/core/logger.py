"""Application-wide log.

Keeps a bounded in-memory list for the activity window and appends to a
size-rotated file so disk usage stays capped no matter how long the app runs.
On first use it loads the recent tail of the log file so the activity window
reflects prior sessions, keeping the UI and the file in agreement.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from . import paths
from .trash import trash_path

MAX_ENTRIES = 1000          # in-memory cap for the UI
MAX_FILE_BYTES = 1_000_000  # rotate after ~1 MB
KEPT_ARCHIVES = 3           # app.log.1 .. app.log.3


class LogLevel(str, Enum):
    INFO = "Info"
    BACKUP = "Backup"
    RESTORE = "Restore"
    DELETION = "Deletion"
    WARNING = "Warning"
    ERROR = "Error"
    UPDATE = "Update"
    PAUSED = "Paused"
    RESUMED = "Resumed"

    @classmethod
    def parse(cls, text: str) -> "LogLevel":
        for level in cls:
            if level.value.lower() == text.strip().lower():
                return level
        return cls.INFO


@dataclass(frozen=True)
class LogEntry:
    level: LogLevel
    message: str
    file_path: str | None = None
    time: datetime = None

    def __post_init__(self):
        if self.time is None:
            object.__setattr__(self, "time", datetime.now())


_LINE_RX = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[([A-Za-z]+)\s*\]\s+(.*)$"
)


class _Logger:
    def __init__(self):
        self._lock = threading.RLock()
        self._entries: list[LogEntry] = []
        self._loaded = False
        self._listeners: list = []

    # ------------------------------------------------------------ location

    @property
    def log_file_path(self) -> Path:
        return paths.state_dir() / "app.log"

    # ----------------------------------------------------------- listeners

    def add_listener(self, fn) -> None:
        with self._lock:
            self._listeners.append(fn)

    def remove_listener(self, fn) -> None:
        with self._lock:
            try:
                self._listeners.remove(fn)
            except ValueError:
                pass

    # ------------------------------------------------------- write helpers

    def log(self, message: str) -> None:
        self._write(LogLevel.INFO, message)

    def warn(self, message: str) -> None:
        self._write(LogLevel.WARNING, message)

    def error(self, message: str) -> None:
        self._write(LogLevel.ERROR, message)

    def backup(self, message: str, file_path: str) -> None:
        self._write(LogLevel.BACKUP, message, file_path)

    def restore(self, message: str, file_path: str) -> None:
        self._write(LogLevel.RESTORE, message, file_path)

    def deletion(self, message: str, file_path: str) -> None:
        self._write(LogLevel.DELETION, message, file_path)

    def update_available(self, message: str) -> None:
        self._write(LogLevel.UPDATE, message)

    def paused(self, message: str) -> None:
        self._write(LogLevel.PAUSED, message)

    def resumed(self, message: str) -> None:
        self._write(LogLevel.RESUMED, message)

    # ------------------------------------------------------------ snapshot

    def snapshot(self) -> list[LogEntry]:
        with self._lock:
            self._ensure_loaded()
            return list(self._entries)

    def preview_log_files(self) -> tuple[int, int]:
        """Count and total size of the log plus its archives, for the
        confirmation prompt shown before clear_logs deletes them."""
        count = 0
        total = 0
        with self._lock:
            for i in range(KEPT_ARCHIVES + 1):
                f = self.log_file_path if i == 0 else Path(f"{self.log_file_path}.{i}")
                if not f.is_file():
                    continue
                count += 1
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
        return count, total

    def clear_logs(self) -> None:
        """Sends the log file and its archives to the trash and clears the
        in-memory activity list.  A fresh log starts on the very next write."""
        with self._lock:
            self._entries.clear()
            for i in range(KEPT_ARCHIVES + 1):
                f = self.log_file_path if i == 0 else Path(f"{self.log_file_path}.{i}")
                try:
                    trash_path(f)
                except Exception:
                    pass
            self._loaded = True  # nothing left on disk to fold back in

    # -------------------------------------------------------------- internals

    def _write(self, level: LogLevel, message: str, file_path: str | None = None) -> None:
        entry = LogEntry(level, message, file_path)
        with self._lock:
            self._ensure_loaded()
            self._entries.append(entry)
            if len(self._entries) > MAX_ENTRIES:
                del self._entries[: len(self._entries) - MAX_ENTRIES]

            try:
                paths.state_dir().mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed()
                # The optional file path is stored after a tab so the activity
                # window can still reveal entries reloaded from disk.
                tail = f"\t{file_path}" if file_path else ""
                line = (f"{entry.time:%Y-%m-%d %H:%M:%S}  "
                        f"[{level.value:<8}]  {message}{tail}\n")
                with open(self.log_file_path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                pass  # logging must never take the app down

            listeners = list(self._listeners)

        for fn in listeners:
            try:
                fn(entry)
            except Exception:
                pass

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            fp = self.log_file_path
            if not fp.is_file():
                return
            lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            for raw in lines[max(0, len(lines) - MAX_ENTRIES):]:
                m = _LINE_RX.match(raw)
                if not m:
                    continue  # skip blank / wrapped lines
                try:
                    when = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    when = datetime.now()
                level = LogLevel.parse(m.group(2))

                msg = m.group(3)
                file_path = None
                if "\t" in msg:
                    msg, _, file_path = msg.partition("\t")
                self._entries.append(LogEntry(level, msg, file_path or None, when))
        except OSError:
            pass

    def _rotate_if_needed(self) -> None:
        """app.log -> app.log.1 -> app.log.2 -> app.log.3 -> deleted."""
        fp = self.log_file_path
        try:
            if not fp.is_file() or fp.stat().st_size < MAX_FILE_BYTES:
                return
        except OSError:
            return

        oldest = Path(f"{fp}.{KEPT_ARCHIVES}")
        try:
            oldest.unlink(missing_ok=True)
        except OSError:
            pass
        for i in range(KEPT_ARCHIVES - 1, 0, -1):
            src = Path(f"{fp}.{i}")
            if src.is_file():
                try:
                    src.rename(Path(f"{fp}.{i + 1}"))
                except OSError:
                    pass
        try:
            fp.rename(Path(f"{fp}.1"))
        except OSError:
            pass


Logger = _Logger()
