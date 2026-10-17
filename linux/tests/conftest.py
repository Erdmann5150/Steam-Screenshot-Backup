"""Shared fixtures: a synthetic Steam installation and an isolated config dir.

Every test runs against a throwaway HOME so nothing touches the real Steam
install, the real config, or the real trash.
"""

from __future__ import annotations

import os
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# A 1x1 JPEG and a 1x1 PNG, built byte-wise so the metadata tests operate on
# structurally real files without shipping binaries in the repo.
def make_jpeg(path: Path, padding: int = 0) -> None:
    body = (
        b"\xff\xd8"                                  # SOI
        b"\xff\xdb\x00\x43\x00" + bytes([1] * 64) +  # DQT
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"   # SOF0
        b"\xff\xc4\x00\x14\x00" + bytes([0] * 16) + b"\x00"       # DHT
        b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"  # SOS
        + b"\x00" * padding +
        b"\xff\xd9"                                  # EOI
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def make_png(path: Path, padding: int = 0) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\xff\xff" + b"\x00" * padding
    body = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def write_shortcuts_vdf(path: Path, entries: dict[int, str]) -> None:
    """A minimal binary shortcuts.vdf carrying appid/appname pairs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = bytearray(b"\x00shortcuts\x00")
    for index, (appid, name) in enumerate(entries.items()):
        out += b"\x00" + str(index).encode() + b"\x00"
        out += b"\x02appid\x00" + struct.pack("<I", appid)
        out += b"\x01appname\x00" + name.encode("utf-8") + b"\x00"
        out += b"\x08"
    out += b"\x08\x08"
    path.write_bytes(bytes(out))


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """An isolated HOME with XDG dirs pointed inside it."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    (tmp_path / "run").mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    # send2trash resolves the home trash once, at import time, so without this
    # every test would move files into the real user's trash and the trash
    # assertions would pass without testing anything.
    # Note the types: send2trash does all its path work in bytes internally and
    # only HOMETRASH is a str, so these have to match or it raises
    # "Can't mix strings and bytes in path components".
    import send2trash.plat_other as plat_other
    fake_trash = home / ".local" / "share" / "Trash"
    monkeypatch.setattr(plat_other, "HOMETRASH", str(fake_trash))
    monkeypatch.setattr(plat_other, "HOMETRASH_B", os.fsencode(str(fake_trash)))
    monkeypatch.setattr(plat_other, "XDG_DATA_HOME",
                        os.fsencode(str(home / ".local" / "share")))

    # The logger caches its loaded state across tests otherwise.
    from ssbackup.core.logger import Logger
    Logger._loaded = False
    Logger._entries.clear()
    return home


@pytest.fixture
def steam_tree(fake_home):
    """A Steam install with two accounts, three games and both screenshot types.

    Layout mirrors a real one closely enough that the engine cannot tell the
    difference:

      ~/.local/share/Steam/
        steamapps/appmanifest_620.acf            -> Portal 2 (installed)
        steamapps/libraryfolders.vdf             -> second library
        userdata/11111/760/remote/620/screenshots/20260412133715_1.jpg
        userdata/11111/760/remote/620/screenshots/thumbnails/...   (ignored)
        userdata/11111/760/remote/1234567/screenshots/...          (delisted)
        userdata/22222/760/remote/620/screenshots/...
        userdata/.../config/localconfig.vdf      -> external copies enabled
        userdata/.../config/shortcuts.vdf        -> one non-Steam game
    """
    steam = fake_home / ".local" / "share" / "Steam"
    steamapps = steam / "steamapps"
    steamapps.mkdir(parents=True)

    (steamapps / "appmanifest_620.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"620"\n\t"name"\t\t"Portal 2"\n}\n')

    second_lib = fake_home / "games" / "SteamLibrary"
    (second_lib / "steamapps").mkdir(parents=True)
    (second_lib / "steamapps" / "appmanifest_413150.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"413150"\n\t"name"\t\t"Stardew Valley"\n}\n')
    (steamapps / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n'
        '\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n'
        '\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n' % (steam, second_lib))

    high_res = fake_home / "Pictures" / "Uncompressed"
    high_res.mkdir(parents=True)

    for user in ("11111", "22222"):
        config = steam / "userdata" / user / "config"
        config.mkdir(parents=True)
        (config / "localconfig.vdf").write_text(
            '"UserLocalConfigStore"\n{\n\t"system"\n\t{\n'
            '\t\t"InGameOverlayScreenshotSaveUncompressed"\t\t"1"\n'
            f'\t\t"InGameOverlayScreenshotSaveUncompressedPath"\t\t"{high_res}"\n'
            '\t}\n}\n')

    write_shortcuts_vdf(
        steam / "userdata" / "11111" / "config" / "shortcuts.vdf",
        {2946102768: "Balatro (non-Steam)"})

    remote = steam / "userdata" / "11111" / "760" / "remote"
    # Portal 2, two shots on the same day.
    make_jpeg(remote / "620" / "screenshots" / "20260412133715_1.jpg")
    make_jpeg(remote / "620" / "screenshots" / "20260412150632_1.jpg")
    # A thumbnail, which must be ignored.
    make_jpeg(remote / "620" / "screenshots" / "thumbnails" / "20260412133715_1.jpg")
    # A delisted game, resolvable by nothing.
    make_jpeg(remote / "1234567" / "screenshots" / "20250825204610_1.jpg")
    # A non-Steam shortcut game.
    make_jpeg(remote / "2946102768" / "screenshots" / "20260501120000_1.jpg")
    # A second shot in the same second, which gets the " (2)" suffix.
    make_jpeg(remote / "620" / "screenshots" / "20260412133715_2.jpg")

    remote2 = steam / "userdata" / "22222" / "760" / "remote"
    make_jpeg(remote2 / "413150" / "screenshots" / "20260301090000_1.jpg")

    # External (high-resolution) copies.
    make_png(high_res / "620_20260412133715_1.png")
    make_png(high_res / "413150_20260301090000_1.png")

    return steam


@pytest.fixture
def engine(steam_tree, fake_home, monkeypatch):
    """An engine wired to the fake tree, with the store API blocked.

    Offline mode is on so no test ever reaches the network; delisted games fall
    back to AppID_<id>, which is exactly the behaviour being tested.
    """
    from ssbackup.core.app_names import AppNameResolver
    from ssbackup.core.backup_engine import BackupEngine
    from ssbackup.core.settings import Settings

    settings = Settings.load()
    settings.Destination = str(fake_home / "Backups" / "Steam Screenshots")
    settings.OfflineMode = True
    settings.FirstRunDone = True
    settings.StructureMigrated = True
    settings.save()

    monkeypatch.setattr(AppNameResolver, "_start_refresh_timer", lambda self: None)
    eng = BackupEngine(settings)
    yield eng
    eng.dispose()


def backup_root(engine):
    """The engine's destination as a Path, for readability in assertions."""
    from pathlib import Path
    return Path(engine.destination)
