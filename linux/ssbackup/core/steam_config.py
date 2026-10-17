"""Central knowledge about the local Steam installation.

Where it lives, which accounts exist, where each account saves uncompressed
("high resolution") screenshot copies, and the names of non-Steam shortcuts.

The Windows app read one registry key to find Steam.  Linux has no registry
and several equally valid install layouts, so this probes the known ones in
order.  On Bazzite in particular, Steam ships natively in the image, but a
Flatpak Steam can be installed alongside it and the user may well have
screenshots under both, so every candidate that actually holds userdata is
returned rather than just the first hit.
"""

from __future__ import annotations

import os
import re
import struct
from pathlib import Path

from . import paths

# Steam's own layout, identical on every platform.
USERDATA = "userdata"
SCREENSHOT_SUBPATH = "760/remote"


def _candidate_roots() -> list[Path]:
    home = paths.home()
    data = paths.data_home()
    return [
        # Native install (the default on Bazzite, Fedora, Arch, and most distros).
        data / "Steam",
        home / ".steam" / "steam",
        home / ".steam" / "root",
        home / ".local" / "share" / "Steam",
        # Flatpak (com.valvesoftware.Steam).
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
        # Snap.
        home / "snap" / "steam" / "common" / ".local" / "share" / "Steam",
        home / "snap" / "steam" / "common" / ".steam" / "steam",
        # Debian/Ubuntu packaging, and a lowercase variant some distros use.
        home / ".steam" / "debian-installation",
        data / "steam",
    ]


def _looks_like_steam(path: Path) -> bool:
    try:
        if not path.is_dir():
            return False
    except OSError:
        return False
    # userdata is what this app actually needs; steamapps alone is a library
    # drive, not an installation.
    return (path / USERDATA).is_dir() or (path / "steamapps").is_dir()


def find_steam_paths(override: str | None = None) -> list[Path]:
    """Every Steam installation found, de-duplicated by resolved real path.

    `override` (from Settings.SteamPathOverride) is checked first and always
    wins if it looks like an installation.
    """
    found: list[Path] = []
    seen: set[Path] = set()

    def consider(candidate: Path) -> None:
        try:
            real = candidate.resolve()
        except OSError:
            return
        if real in seen:
            return
        if not _looks_like_steam(real):
            return
        seen.add(real)
        found.append(real)

    if override and override.strip():
        consider(Path(override.strip()).expanduser())

    for c in _candidate_roots():
        consider(c)

    # A user who moved Steam somewhere unusual may still have the symlinks;
    # registry.vdf records the install path Steam itself believes in.
    for reg in (paths.home() / ".steam" / "registry.vdf",
                paths.home() / ".steam" / "steam" / "registry.vdf"):
        try:
            if reg.is_file():
                text = reg.read_text(encoding="utf-8", errors="replace")
                for m in re.finditer(r'"(?:SteamPath|InstallPath|SourceModInstallPath)"\s+"([^"]+)"',
                                     text, re.IGNORECASE):
                    value = m.group(1).replace("\\\\", "/").replace("\\", "/")
                    if not value:
                        continue
                    p = Path(value)
                    # SourceModInstallPath points at steamapps/sourcemods; walk up.
                    for candidate in (p, p.parent.parent):
                        consider(candidate)
        except OSError:
            continue

    return found


def find_steam_path(override: str | None = None) -> Path | None:
    """The primary Steam installation, or None when none was found."""
    roots = find_steam_paths(override)
    return roots[0] if roots else None


def describe_installs(roots: list[Path]) -> str:
    """A short human-readable summary for the UI and the log."""
    if not roots:
        return "none"
    labels = []
    for r in roots:
        s = str(r)
        if "/.var/app/com.valvesoftware.Steam/" in s:
            labels.append(f"Flatpak ({s})")
        elif "/snap/steam/" in s:
            labels.append(f"Snap ({s})")
        else:
            labels.append(s)
    return ", ".join(labels)


# --------------------------------------------------------------- userdata

def userdata_dirs(roots: list[Path]) -> list[Path]:
    dirs = []
    for root in roots:
        d = root / USERDATA
        if d.is_dir():
            dirs.append(d)
    return dirs


# ----------------------------------------------------- high-res screenshots

def find_high_res_folders(roots: list[Path]) -> list[str]:
    """Folders Steam's "Save an external copy of my screenshots" writes to.

    One per account that has the option enabled.  Files there are named
    <appid>_YYYYMMDDHHMMSS_<n>.png
    """
    folders: list[str] = []
    seen: set[str] = set()

    for userdata in userdata_dirs(roots):
        for cfg in sorted(userdata.glob("*/config/localconfig.vdf")):
            try:
                raw = cfg.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            enabled = re.search(
                r'"InGameOverlayScreenshotSaveUncompressed"\s+"1"', raw, re.IGNORECASE
            )
            m = re.search(
                r'"InGameOverlayScreenshotSaveUncompressedPath"\s+"([^"]*)"',
                raw, re.IGNORECASE,
            )
            if not enabled or not m:
                continue

            value = m.group(1)
            if not value:
                continue
            # Steam escapes backslashes in VDF.  A Linux path has none; a path
            # carried over from a Windows profile would, and is not usable here
            # anyway, so only accept something that resolves locally.
            path = value.replace("\\\\", "/").replace("\\", "/")
            path = os.path.expanduser(path)
            if not path.startswith("/"):
                continue
            key = os.path.normpath(path)
            if key.lower() in seen:
                continue
            seen.add(key.lower())
            folders.append(key)

    return folders


# ------------------------------------------------------ non-Steam shortcuts

def read_shortcut_names(roots: list[Path]) -> dict[int, str]:
    """Names of non-Steam shortcut games, keyed by their synthetic appid.

    Those ids live in each account's binary shortcuts.vdf.  This does a minimal
    binary scan rather than a full VDF parse: find the "appid" int32 field,
    then the "appname" string field within the same entry.
    """
    names: dict[int, str] = {}
    for userdata in userdata_dirs(roots):
        for vdf in sorted(userdata.glob("*/config/shortcuts.vdf")):
            try:
                _scan_shortcuts(vdf.read_bytes(), names)
            except OSError:
                continue
    return names


_APPID_KEY = b"\x02appid\x00"
_NAME_KEY = b"\x01appname\x00"


def _scan_shortcuts(data: bytes, names: dict[int, str]) -> None:
    pos = 0
    while True:
        pos = data.find(_APPID_KEY, pos)
        if pos < 0:
            return
        id_offset = pos + len(_APPID_KEY)
        if id_offset + 4 > len(data):
            return
        appid = struct.unpack_from("<I", data, id_offset)[0]

        name_pos = data.find(_NAME_KEY, id_offset)
        if name_pos >= 0:
            start = name_pos + len(_NAME_KEY)
            end = data.find(b"\x00", start)
            if end > start:
                try:
                    name = data[start:end].decode("utf-8")
                except UnicodeDecodeError:
                    name = data[start:end].decode("utf-8", errors="replace")
                if name:
                    names[appid] = name
        pos = id_offset


def is_non_steam_app_id(appid: str) -> bool:
    """Screenshot appids above int32 max are synthetic ids for non-Steam games."""
    try:
        return int(appid) > 2147483647
    except (TypeError, ValueError):
        return False


# ----------------------------------------------------------- game manifests

def library_folders(roots: list[Path]) -> list[Path]:
    """Every steamapps directory across every library drive."""
    libs: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        try:
            if p.is_dir() and str(p).lower() not in seen:
                seen.add(str(p).lower())
                libs.append(p)
        except OSError:
            pass

    for root in roots:
        add(root / "steamapps")
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            if vdf.is_file():
                text = vdf.read_text(encoding="utf-8", errors="replace")
                for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                    value = m.group(1).replace("\\\\", "/").replace("\\", "/")
                    add(Path(value) / "steamapps")
        except OSError:
            pass

    return libs
