"""Core logic: naming, templates, Steam discovery, metadata, update checks."""

from __future__ import annotations

from datetime import datetime

import pytest

from ssbackup.core import steam_config, update_checker
from ssbackup.core.backup_engine import (
    BACKUP_NAME, ScreenshotType, convert_name, expand_template,
    extract_fallback_app_id, extract_game_segment, format_bytes,
    parse_backup_timestamp,
)
from ssbackup.core.metadata import has_game_name_metadata, tag_game_name
from ssbackup.core.settings import Settings, ThemeMode, normalize_template


# ------------------------------------------------------------ name conversion

@pytest.mark.parametrize("src,kind,expected", [
    ("20260706210532_1.jpg", ScreenshotType.STANDARD, "2026-07-06 21.05.32.jpg"),
    ("20260706210532_2.jpg", ScreenshotType.STANDARD, "2026-07-06 21.05.32 (2).jpg"),
    ("20260706210532_11.jpg", ScreenshotType.STANDARD, "2026-07-06 21.05.32 (11).jpg"),
    ("646570_20260707214723_1.png", ScreenshotType.HIGH_RES, "2026-07-07 21.47.23.png"),
    ("646570_20260707214723_3.png", ScreenshotType.HIGH_RES,
     "2026-07-07 21.47.23 (3).png"),
])
def test_convert_name(src, kind, expected):
    ts, name = convert_name(src, kind)
    assert name == expected
    assert ts is not None


@pytest.mark.parametrize("src,kind", [
    ("notascreenshot.jpg", ScreenshotType.STANDARD),
    ("20260706210532.jpg", ScreenshotType.STANDARD),          # no _n
    ("20260706210532_1.jpg", ScreenshotType.HIGH_RES),        # missing appid
    ("20261306210532_1.jpg", ScreenshotType.STANDARD),        # month 13
    ("", ScreenshotType.STANDARD),
])
def test_convert_name_rejects(src, kind):
    _, name = convert_name(src, kind)
    assert name is None


def test_converted_names_match_backup_pattern():
    """Whatever convert_name produces must be recognised later as ours, or
    totals, re-sync and granular deletion would all silently skip it."""
    for src, kind in (("20260706210532_1.jpg", ScreenshotType.STANDARD),
                      ("20260706210532_4.jpg", ScreenshotType.STANDARD),
                      ("620_20260706210532_1.png", ScreenshotType.HIGH_RES)):
        _, name = convert_name(src, kind)
        assert BACKUP_NAME.match(name), name
        assert parse_backup_timestamp(name) is not None


# ------------------------------------------------------------------ templates

def test_expand_template_default():
    ts = datetime(2026, 4, 12, 13, 37, 15)
    assert expand_template("{game}", "Portal 2", ts) == "Portal 2"


def test_expand_template_nested():
    ts = datetime(2026, 4, 12)
    assert expand_template("{yyyy}/{game}", "Portal 2", ts) == "2026/Portal 2"
    assert expand_template("{game}/{yyyy}-{MM}", "Portal 2", ts) == "Portal 2/2026-04"
    assert expand_template("{yyyy}/{MM}/{dd}", "X", ts) == "2026/04/12"


def test_expand_template_accepts_windows_separators():
    """A settings.json carried over from the Windows build uses backslashes."""
    ts = datetime(2026, 4, 12)
    assert expand_template("{game}\\{yyyy}", "Portal 2", ts) == "Portal 2/2026"


def test_expand_template_strips_windows_illegal_characters():
    """Kept identical to the Windows app so both write the same folder name
    into a shared destination, even though Linux would allow these."""
    ts = datetime(2026, 4, 12)
    assert expand_template("{game}", 'Half-Life 2: Episode One', ts) \
        == "Half-Life 2 Episode One"
    assert expand_template("{game}", 'What?*"<>|Name', ts) == "WhatName"
    assert expand_template("{game}", "Trailing dots...", ts) == "Trailing dots"


def test_expand_template_drops_empty_segments():
    ts = datetime(2026, 4, 12)
    assert expand_template("{game}", "...", ts) == ""
    assert expand_template("{game}/{yyyy}", "", ts) == "2026"


def test_normalize_template():
    assert normalize_template(None) == "{game}"
    assert normalize_template("") == "{game}"
    assert normalize_template("   ") == "{game}"
    assert normalize_template("{game}\\{yyyy}") == "{game}/{yyyy}"


def test_extract_game_segment():
    assert extract_game_segment("Portal 2/shot.jpg", "{game}") == "Portal 2"
    assert extract_game_segment("2026/Portal 2/shot.jpg", "{yyyy}/{game}") == "Portal 2"
    assert extract_game_segment("Portal 2/2026/shot.jpg", "{game}/{yyyy}") == "Portal 2"
    assert extract_game_segment("shot.jpg", "{game}") is None


def test_extract_fallback_app_id():
    assert extract_fallback_app_id("AppID_1681430") == "1681430"
    assert extract_fallback_app_id("Non-Steam App 2946102768") == "2946102768"
    assert extract_fallback_app_id("Portal 2") is None
    assert extract_fallback_app_id("AppID_notanumber") is None


def test_format_bytes():
    assert format_bytes(512) == "512 B"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(5 * 1024 * 1024) == "5.0 MB"
    assert format_bytes(3 * 1024 ** 3) == "3.0 GB"


# ------------------------------------------------------------ Steam discovery

def test_finds_native_steam(steam_tree, fake_home):
    roots = steam_config.find_steam_paths()
    assert steam_tree.resolve() in roots


def test_finds_flatpak_steam(fake_home):
    flatpak = (fake_home / ".var" / "app" / "com.valvesoftware.Steam"
               / ".local" / "share" / "Steam")
    (flatpak / "userdata").mkdir(parents=True)
    roots = steam_config.find_steam_paths()
    assert flatpak.resolve() in roots


def test_finds_both_native_and_flatpak(steam_tree, fake_home):
    """Bazzite ships Steam natively but a Flatpak Steam can sit alongside it,
    and the user may have screenshots under both."""
    flatpak = (fake_home / ".var" / "app" / "com.valvesoftware.Steam"
               / ".local" / "share" / "Steam")
    (flatpak / "userdata").mkdir(parents=True)
    roots = steam_config.find_steam_paths()
    assert steam_tree.resolve() in roots
    assert flatpak.resolve() in roots


def test_symlinked_steam_is_not_duplicated(steam_tree, fake_home):
    """~/.steam/steam is normally a symlink to the real install; it must not
    show up as a second installation and double every screenshot."""
    link_dir = fake_home / ".steam"
    link_dir.mkdir(exist_ok=True)
    (link_dir / "steam").symlink_to(steam_tree)
    roots = steam_config.find_steam_paths()
    assert len(roots) == 1
    assert roots[0] == steam_tree.resolve()


def test_override_wins(steam_tree, fake_home, tmp_path):
    custom = tmp_path / "custom-steam"
    (custom / "userdata").mkdir(parents=True)
    roots = steam_config.find_steam_paths(str(custom))
    assert roots[0] == custom.resolve()


def test_no_steam_found(fake_home):
    assert steam_config.find_steam_paths() == []
    assert steam_config.find_steam_path() is None


def test_high_res_folders_detected(steam_tree, fake_home):
    folders = steam_config.find_high_res_folders([steam_tree])
    assert len(folders) == 1   # same path configured for both accounts
    assert folders[0] == str(fake_home / "Pictures" / "Uncompressed")


def test_high_res_ignored_when_disabled(steam_tree, fake_home):
    for cfg in steam_tree.glob("userdata/*/config/localconfig.vdf"):
        cfg.write_text(cfg.read_text().replace(
            '"InGameOverlayScreenshotSaveUncompressed"\t\t"1"',
            '"InGameOverlayScreenshotSaveUncompressed"\t\t"0"'))
    assert steam_config.find_high_res_folders([steam_tree]) == []


def test_shortcut_names_parsed(steam_tree):
    names = steam_config.read_shortcut_names([steam_tree])
    assert names.get(2946102768) == "Balatro (non-Steam)"


def test_library_folders_includes_second_drive(steam_tree, fake_home):
    libs = steam_config.library_folders([steam_tree])
    assert any("SteamLibrary" in str(p) for p in libs)


def test_is_non_steam_app_id():
    assert steam_config.is_non_steam_app_id("2946102768")
    assert not steam_config.is_non_steam_app_id("620")
    assert not steam_config.is_non_steam_app_id("notanumber")


# -------------------------------------------------------------------- metadata

def test_jpeg_tagging_roundtrip(tmp_path):
    from tests.conftest import make_jpeg
    f = tmp_path / "shot.jpg"
    make_jpeg(f)
    before = f.read_bytes()

    assert not has_game_name_metadata(f)
    tag_game_name(f, "Portal 2")
    assert has_game_name_metadata(f)

    after = f.read_bytes()
    assert after.startswith(b"\xff\xd8\xff\xe1")
    assert b"Exif\x00\x00" in after
    # The original image data must survive byte-identically after the inserted
    # segment: tagging is lossless, never a re-encode.
    assert after.endswith(before[2:])
    assert "Portal 2".encode("utf-16-le") in after


def test_jpeg_tagging_is_idempotent(tmp_path):
    from tests.conftest import make_jpeg
    f = tmp_path / "shot.jpg"
    make_jpeg(f)
    tag_game_name(f, "Portal 2")
    once = f.read_bytes()
    tag_game_name(f, "Portal 2")
    assert f.read_bytes() == once   # existing EXIF is never clobbered


def test_png_tagging_roundtrip(tmp_path):
    from tests.conftest import make_png
    f = tmp_path / "shot.png"
    make_png(f)
    before = f.read_bytes()

    assert not has_game_name_metadata(f)
    tag_game_name(f, "Stardew Valley")
    assert has_game_name_metadata(f)

    after = f.read_bytes()
    assert after.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"XML:com.adobe.xmp" in after
    assert b"Stardew Valley" in after
    assert after.endswith(before[33:])   # IDAT/IEND untouched
    assert b"IEND" in after


def test_png_tagging_is_idempotent(tmp_path):
    from tests.conftest import make_png
    f = tmp_path / "shot.png"
    make_png(f)
    tag_game_name(f, "Stardew Valley")
    once = f.read_bytes()
    tag_game_name(f, "Stardew Valley")
    assert f.read_bytes() == once


def test_png_chunk_crcs_are_valid(tmp_path):
    """A wrong CRC makes the file invalid for strict decoders, which would
    corrupt every backed-up PNG."""
    import struct
    import zlib
    from tests.conftest import make_png

    f = tmp_path / "shot.png"
    make_png(f)
    tag_game_name(f, "Sl\u00e1in \u2014 \u00e9\u00e0\u00fc")

    data = f.read_bytes()
    pos = 8
    seen = []
    while pos < len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        kind = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        stored = struct.unpack_from(">I", data, pos + 8 + length)[0]
        assert stored == zlib.crc32(kind + payload) & 0xFFFFFFFF, kind
        seen.append(kind)
        pos += 12 + length
    assert seen[0] == b"IHDR" and seen[-1] == b"IEND"
    assert b"iTXt" in seen


def test_tagging_preserves_mtime(tmp_path):
    import os
    from tests.conftest import make_jpeg
    f = tmp_path / "shot.jpg"
    make_jpeg(f)
    os.utime(f, (1000000, 1000000))
    tag_game_name(f, "Portal 2")
    assert int(f.stat().st_mtime) == 1000000


def test_tagging_non_image_is_a_no_op(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hello")
    tag_game_name(f, "Portal 2")
    assert f.read_text() == "hello"


# -------------------------------------------------------------- update checks

@pytest.mark.parametrize("tag,current,expected", [
    ("v1.1.0", "1.0.0", "1.1.0"),
    ("1.1.0", "1.0.0", "1.1.0"),
    ("v1.0.0", "1.0.0", None),
    ("v0.9.0", "1.0.0", None),
    ("v1.0.1", "1.0.0", "1.0.1"),
    ("v2.0", "1.9.9", "2.0"),
    ("v1.0", "1.0.0", None),
    ("v1.0.0.1", "1.0.0", "1.0.0.1"),
    ("garbage", "1.0.0", None),
    (None, "1.0.0", None),
    ("v1.1.0", "garbage", None),
])
def test_newer_version_or_none(tag, current, expected):
    assert update_checker.newer_version_or_none(tag, current) == expected


def test_check_now_respects_offline_mode():
    s = Settings()
    s.OfflineMode = True
    assert update_checker.check_now(s) is None


# -------------------------------------------------------------------- settings

def test_settings_roundtrip(fake_home):
    s = Settings.load()
    s.Destination = str(fake_home / "Backups")
    s.FolderTemplate = "{yyyy}/{game}"
    s.Theme = ThemeMode.LIGHT
    s.DeleteOriginals = True
    s.save()

    again = Settings.load()
    assert again.Destination == str(fake_home / "Backups")
    assert again.FolderTemplate == "{yyyy}/{game}"
    assert again.Theme == ThemeMode.LIGHT
    assert again.DeleteOriginals is True


def test_settings_default_destination(fake_home):
    s = Settings.load()
    assert s.Destination.endswith("Steam Screenshots")


def test_settings_reads_windows_file(fake_home):
    """A settings.json copied from the Windows install must load, including its
    integer Theme enum and backslash template."""
    import json
    d = Settings.dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "settings.json").write_text(json.dumps({
        "Destination": "D:\\Backups\\Steam Screenshots",
        "BackupStandard": True,
        "BackupHighRes": False,
        "FolderTemplate": "{game}\\{yyyy}",
        "Theme": 2,
        "AutoRestore": False,
    }))
    s = Settings.load()
    assert s.FolderTemplate == "{game}/{yyyy}"
    assert s.Theme == ThemeMode.LIGHT
    assert s.BackupHighRes is False
    assert s.AutoRestore is False


def test_settings_survives_corrupt_file(fake_home):
    d = Settings.dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "settings.json").write_text("{not valid json")
    s = Settings.load()
    assert s.BackupStandard is True   # fell back to defaults


# -------------------------- shared-repo release filtering

def test_windows_releases_are_ignored():
    """The Linux app shares a repo with the Windows app, whose version numbers
    are far higher. Seeing those would mean nagging about an update forever."""
    releases = [
        {"tag_name": "v3.11.7", "html_url": "https://example.test/win"},
        {"tag_name": "v3.11.6", "html_url": "https://example.test/win2"},
    ]
    assert update_checker.newest_linux_release(releases, "1.0.0") is None


def test_linux_release_is_found_among_windows_ones():
    releases = [
        {"tag_name": "v3.11.7", "html_url": "https://example.test/win"},
        {"tag_name": "linux-v1.1.0", "html_url": "https://example.test/linux"},
        {"tag_name": "v3.11.6", "html_url": "https://example.test/win2"},
    ]
    info = update_checker.newest_linux_release(releases, "1.0.0")
    assert info is not None
    assert info.version == "1.1.0"
    assert info.url == "https://example.test/linux"


def test_own_current_release_is_not_an_update():
    releases = [{"tag_name": "linux-v1.0.0", "html_url": "https://example.test/l"}]
    assert update_checker.newest_linux_release(releases, "1.0.0") is None


def test_newest_linux_release_wins_regardless_of_order():
    """GitHub returns newest-first, but a backdated release would break that."""
    releases = [
        {"tag_name": "linux-v1.0.1", "html_url": "https://example.test/a"},
        {"tag_name": "linux-v1.2.0", "html_url": "https://example.test/b"},
        {"tag_name": "linux-v1.1.0", "html_url": "https://example.test/c"},
    ]
    info = update_checker.newest_linux_release(releases, "1.0.0")
    assert info.version == "1.2.0"
    assert info.url == "https://example.test/b"


def test_drafts_and_prereleases_are_skipped():
    releases = [
        {"tag_name": "linux-v2.0.0", "draft": True, "html_url": "x"},
        {"tag_name": "linux-v1.9.0", "prerelease": True, "html_url": "y"},
        {"tag_name": "linux-v1.1.0", "html_url": "https://example.test/stable"},
    ]
    info = update_checker.newest_linux_release(releases, "1.0.0")
    assert info.version == "1.1.0"


def test_malformed_release_list_is_survivable():
    for payload in (None, {}, "nonsense", [None, 5, {"tag_name": None}],
                    [{"tag_name": "linux-vnotaversion"}]):
        assert update_checker.newest_linux_release(payload, "1.0.0") is None


@pytest.mark.parametrize("tag,expected", [
    ("linux-v1.2.3", "1.2.3"),
    ("LINUX-V1.2.3", "1.2.3"),
    ("v3.11.7", None),
    ("3.11.7", None),
    ("linux-v", None),
    (None, None),
])
def test_strip_tag_prefix(tag, expected):
    assert update_checker.strip_tag_prefix(tag) == expected
