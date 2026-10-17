"""XDG directories, autostart, and desktop integration.

This is the Linux counterpart to everything the Windows app did through
%LOCALAPPDATA%, the registry Run key, and explorer.exe.  Keeping it in one
module means the rest of the core never has to know about freedesktop specs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_ID = "steam-screenshot-backup"
APP_NAME = "Steam Screenshot Backup"
DESKTOP_FILE_NAME = f"{APP_ID}.desktop"


# --------------------------------------------------------------- XDG basics

def _xdg(env_var: str, default: Path) -> Path:
    raw = os.environ.get(env_var, "").strip()
    if raw and raw.startswith("/"):
        return Path(raw)
    return default


def home() -> Path:
    return Path.home()


def config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", home() / ".config")


def data_home() -> Path:
    return _xdg("XDG_DATA_HOME", home() / ".local" / "share")


def state_home() -> Path:
    return _xdg("XDG_STATE_HOME", home() / ".local" / "state")


def runtime_dir() -> Path:
    raw = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if raw and raw.startswith("/") and Path(raw).is_dir():
        return Path(raw)
    return Path("/tmp")


def config_dir() -> Path:
    """settings.json, appnames.json, appnames.verified.json live here."""
    return config_home() / APP_ID


def state_dir() -> Path:
    """app.log and its rotated archives live here."""
    return state_home() / APP_ID


def autostart_dir() -> Path:
    return config_home() / "autostart"


def applications_dir() -> Path:
    return data_home() / "applications"


# ------------------------------------------------------- default destination

def pictures_dir() -> Path:
    """The user's Pictures folder, honouring a localized xdg-user-dirs setup."""
    # xdg-user-dirs writes user-dirs.dirs; reading it directly avoids shelling out.
    cfg = config_home() / "user-dirs.dirs"
    try:
        if cfg.is_file():
            for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line.startswith("XDG_PICTURES_DIR"):
                    continue
                _, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                value = value.replace("$HOME", str(home()))
                if value:
                    p = Path(value)
                    if p.is_absolute():
                        return p
    except OSError:
        pass
    return home() / "Pictures"


def default_destination() -> Path:
    return pictures_dir() / "Steam Screenshots"


# ---------------------------------------------------------------- autostart

def _launcher_command() -> str:
    """The command an autostart/.desktop entry should run.

    Prefers the installed launcher script, since that is stable across Python
    upgrades; falls back to re-running whatever interpreter started us.
    """
    installed = home() / ".local" / "bin" / APP_ID
    if installed.is_file() and os.access(installed, os.X_OK):
        return str(installed)
    return f'"{sys.executable}" -m ssbackup'


def autostart_file() -> Path:
    return autostart_dir() / DESKTOP_FILE_NAME


def is_autostart_enabled() -> bool:
    f = autostart_file()
    if not f.is_file():
        return False
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    # An entry present but explicitly disabled by the DE's own UI.
    for line in text.splitlines():
        if line.strip().lower().replace(" ", "") == "hidden=true":
            return False
    return True


def set_autostart_enabled(on: bool) -> None:
    f = autostart_file()
    if not on:
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass
        return

    autostart_dir().mkdir(parents=True, exist_ok=True)
    f.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Back up Steam screenshots into per-game folders\n"
        f"Exec={_launcher_command()}\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
        "X-GNOME-Autostart-enabled=true\n"
        # Plasma restores its tray late; a short delay avoids a missing icon.
        "X-GNOME-Autostart-Delay=5\n"
        "X-KDE-autostart-after=panel\n",
        encoding="utf-8",
    )
    try:
        f.chmod(0o755)
    except OSError:
        pass


# ----------------------------------------------------- desktop integration

def open_path(path: str | Path) -> None:
    """Open a folder (or file) with the user's default handler."""
    target = str(path)
    opener = shutil.which("xdg-open") or shutil.which("gio")
    if opener and opener.endswith("gio"):
        subprocess.Popen([opener, "open", target],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    if opener:
        subprocess.Popen([opener, target],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    raise RuntimeError("No xdg-open or gio available to open paths.")


def reveal_in_file_manager(path: str | Path) -> None:
    """Select a file in the file manager - the equivalent of explorer /select.

    org.freedesktop.FileManager1 is implemented by Dolphin (Bazzite's default),
    Nautilus, Nemo and Thunar, and selects the file rather than just opening
    its folder.  Falls back to opening the containing folder.
    """
    target = Path(path)
    uri = target.absolute().as_uri()

    dbus_send = shutil.which("dbus-send")
    if dbus_send:
        try:
            result = subprocess.run(
                [
                    dbus_send, "--session", "--print-reply",
                    "--dest=org.freedesktop.FileManager1",
                    "/org/freedesktop/FileManager1",
                    "org.freedesktop.FileManager1.ShowItems",
                    f"array:string:{uri}",
                    "string:",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if result.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass

    open_path(target.parent if target.parent != target else target)


def open_text_file(path: str | Path) -> None:
    """Open a log/JSON file in whatever the user uses for text.

    .log often has no handler registered, so try a text editor before falling
    back to xdg-open and then to revealing it in the file manager.
    """
    target = str(path)
    for editor in ("kate", "gnome-text-editor", "gedit", "mousepad", "xed"):
        exe = shutil.which(editor)
        if exe:
            subprocess.Popen([exe, target],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    try:
        open_path(target)
    except Exception:
        reveal_in_file_manager(target)


def open_url(url: str) -> None:
    opener = shutil.which("xdg-open")
    if opener:
        subprocess.Popen([opener, url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
