"""Send files to the desktop trash instead of deleting them permanently.

The Windows app used the Recycle Bin so that a mistaken "delete originals" is
always recoverable.  The freedesktop.org trash spec is the direct equivalent,
and Plasma's Dolphin, GNOME Files and every other mainstream file manager
present it as the same "Trash" the user already knows.

This module deliberately imports nothing from the rest of the package: the
logger trashes its own rotated archives, so a dependency the other way would
be circular.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

try:
    from send2trash import send2trash as _send2trash
except ImportError:  # pragma: no cover - dependency is declared, this is belt and braces
    _send2trash = None


class TrashError(RuntimeError):
    """Raised when a path could not be moved to the trash."""


def trash_path(path: str | Path) -> bool:
    """Send a file or directory tree to the trash.

    Returns True if it was trashed or was already gone.  Raises TrashError if
    it exists but could not be moved, so callers can log a genuine failure
    rather than silently believing a deletion happened.
    """
    p = Path(path)
    if not p.exists() and not p.is_symlink():
        return True

    if _send2trash is None:
        raise TrashError(
            "The send2trash package is not installed, so files cannot be moved "
            "to the trash. Refusing to delete permanently."
        )

    try:
        _send2trash(str(p))
        return True
    except Exception as ex:
        # send2trash fails when the file lives on a filesystem with no trash
        # directory and none can be created - a FAT/exFAT USB drive, some NAS
        # mounts, or a read-only mount.  Never fall back to unlink(): the
        # entire promise of this app's deletions is that they are recoverable.
        raise TrashError(
            f"Could not move {p.name} to the trash: {ex}. "
            "This can happen on network or removable drives that have no trash "
            "folder; nothing was deleted."
        ) from ex


def trash_directory(path: str | Path) -> bool:
    """Send a whole directory tree to the trash."""
    return trash_path(path)


def trash_available_for(path: str | Path) -> bool:
    """Best-effort check that a trash exists for the volume holding `path`.

    Used to warn before offering a bulk delete, rather than discovering
    halfway through that nothing can be removed.
    """
    p = Path(path)
    probe = p if p.exists() else p.parent
    try:
        st = probe.stat()
    except OSError:
        return False

    try:
        home_dev = Path.home().stat().st_dev
    except OSError:
        return False

    if st.st_dev == home_dev:
        return True  # the home trash always works

    # A non-home volume needs either a .Trash-$uid or a top-level .Trash the
    # spec allows us to create.
    mount = probe.absolute()
    while mount != mount.parent and mount.stat().st_dev == st.st_dev:
        mount = mount.parent
    top = mount if mount.stat().st_dev == st.st_dev else _child_on_device(mount, st.st_dev)
    if top is None:
        return False

    uid = os.getuid()
    if (top / f".Trash-{uid}").is_dir():
        return True
    return os.access(top, os.W_OK)


def _child_on_device(parent: Path, device: int) -> Path | None:
    try:
        for child in parent.iterdir():
            try:
                if child.stat().st_dev == device:
                    return child
            except OSError:
                continue
    except OSError:
        pass
    return None


def disk_usage_free(path: str | Path) -> int:
    try:
        return shutil.disk_usage(str(path)).free
    except OSError:
        return 0
