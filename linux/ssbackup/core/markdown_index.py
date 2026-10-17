"""Maintains a "_Screenshot_Log.md" alongside the backed-up screenshots.

A running, chronological markdown index that embeds every shot with a relative
path and a per-day date header.  Handy for Obsidian / markdown journals.

Writes are serialized (screenshots can land in rapid succession) and the last
date written per file is cached so the whole log isn't re-scanned every append.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from .logger import Logger

FILE_NAME = "_Screenshot_Log.md"


class MarkdownIndex:
    def __init__(self):
        self._lock = threading.Lock()
        self._last_date: dict[str, str | None] = {}   # md path -> yyyy-MM-dd

    def append(self, image_path: str | Path, captured: datetime) -> None:
        """Appends the just-copied image to the markdown log in its folder.

        The image name is used for both the alt text and the (relative) link so
        it resolves from the log's location.  Angle brackets keep names with
        spaces valid markdown.
        """
        try:
            image = Path(image_path)
            directory = image.parent
            md_path = directory / FILE_NAME
            key = str(md_path)
            name = image.name
            alt = image.stem
            day = captured.strftime("%Y-%m-%d")

            with self._lock:
                if key not in self._last_date:
                    # Survive restarts / pre-existing logs.
                    self._last_date[key] = _read_last_date(md_path)
                last = self._last_date[key]

                parts = []
                if not md_path.is_file():
                    parts.append("# Screenshots\n\n")
                if last != day:
                    parts.append(f"### {day}\n\n")
                    self._last_date[key] = day
                parts.append(f"![{alt}](<{name}>)\n\n")

                with open(md_path, "a", encoding="utf-8") as fh:
                    fh.write("".join(parts))
        except OSError as ex:
            Logger.warn(f"Could not update {FILE_NAME}: {ex}")

    def rebuild(self, directory: str | Path,
                images: list[tuple[str, datetime]]) -> None:
        """Rebuilds a folder's log from scratch: every backup image in the
        folder, in the order given (callers pass them sorted by capture time),
        grouped under per-day headers.  Overwrites any existing log so it can't
        accumulate duplicates."""
        try:
            md_path = Path(directory) / FILE_NAME
            parts = ["# Screenshots\n\n"]
            last_day = None
            for name, captured in images:
                day = captured.strftime("%Y-%m-%d")
                if day != last_day:
                    parts.append(f"### {day}\n\n")
                    last_day = day
                alt = Path(name).stem
                parts.append(f"![{alt}](<{name}>)\n\n")

            with self._lock:
                md_path.write_text("".join(parts), encoding="utf-8")
                self._last_date[str(md_path)] = last_day
        except OSError as ex:
            Logger.warn(f"Could not rebuild {FILE_NAME}: {ex}")


def _read_last_date(md_path: Path) -> str | None:
    """The date of the last "### YYYY-MM-DD" header already in the file."""
    if not md_path.is_file():
        return None
    last = None
    try:
        with open(md_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("### "):
                    last = line[4:].strip()
    except OSError:
        pass
    return last
