"""File-naming presets: formatting, parsing, sort order, and the engine's
handling of a naming change, with and without renaming existing files."""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from ssbackup.core import naming
from ssbackup.core.backup_engine import ScreenshotType, convert_name
from ssbackup.core.markdown_index import FILE_NAME as MD_FILE_NAME
from ssbackup.core.settings import Settings
from tests.conftest import backup_root

TS = datetime(2026, 4, 12, 13, 37, 15)
ALL_KEYS = [p.key for p in naming.PRESETS]


# ------------------------------------------------------------- the presets

@pytest.mark.parametrize("key,expected", [
    ("Date", "2026-04-12 13.37.15.jpg"),
    ("GameDate", "Portal 2 - 2026-04-12 13.37.15.jpg"),
    ("Compact", "2026-04-12_13-37-15.jpg"),
])
def test_format(key, expected):
    assert naming.format_name(key, TS, 1, ".jpg", "Portal 2") == expected


def test_reverse_format_has_countdown_then_date():
    name = naming.format_name("Reverse", TS, 1, ".jpg")
    prefix, _, rest = name.partition(" - ")
    assert len(prefix) == 10 and prefix.isdigit()
    assert rest == "2026-04-12 13.37.15.jpg"


@pytest.mark.parametrize("key", ALL_KEYS)
@pytest.mark.parametrize("index", [1, 2, 11])
def test_every_preset_round_trips(key, index):
    """Whatever a preset writes must be recognized later as ours, or totals,
    re-sync, renaming and duplicate detection would all skip it."""
    name = naming.format_name(key, TS, index, ".png", "Portal 2")
    parsed = naming.parse_name(name)
    assert parsed is not None, name
    assert parsed.preset == key
    assert parsed.timestamp == TS
    assert parsed.index == index
    assert parsed.ext == ".png"
    if key == "GameDate":
        assert parsed.game == "Portal 2"


def test_default_preset_matches_the_windows_app():
    _, name = convert_name("20260412133715_2.jpg", ScreenshotType.STANDARD)
    assert name == "2026-04-12 13.37.15 (2).jpg"
    assert naming.DEFAULT_PRESET == "Date"


def test_convert_name_uses_the_given_preset():
    _, name = convert_name("620_20260412133715_1.png", ScreenshotType.HIGH_RES,
                           "GameDate", "Portal 2")
    assert name == "Portal 2 - 2026-04-12 13.37.15.png"


def _shots():
    return [datetime(2026, 4, 12, 13, 37, 15), datetime(2026, 4, 12, 15, 6, 32),
            datetime(2026, 5, 1, 9, 0, 0), datetime(2027, 1, 1, 0, 0, 0)]


def test_date_sorts_oldest_first():
    names = [naming.format_name("Date", ts, 1, ".jpg") for ts in _shots()]
    assert sorted(names) == names


def test_reverse_sorts_newest_first():
    """The whole point of the preset: A-Z is newest first, so an uploader that
    reverses the order posts them oldest first."""
    names = [naming.format_name("Reverse", ts, 1, ".jpg") for ts in _shots()]
    assert sorted(names) == list(reversed(names))


def test_numeric_game_name_is_not_mistaken_for_a_countdown():
    name = naming.format_name("GameDate", TS, 1, ".jpg", "1234567890")
    parsed = naming.parse_name(name)
    assert parsed.preset == "GameDate"
    assert parsed.game == "1234567890"


def test_game_name_is_sanitized_for_the_file_system():
    name = naming.format_name("GameDate", TS, 1, ".jpg", 'Fate/Stay: "Night"?')
    assert "/" not in name and ":" not in name and '"' not in name
    assert naming.parse_name(name) is not None


def test_game_name_containing_the_separator_parses():
    name = naming.format_name("GameDate", TS, 1, ".jpg", "Batman - Arkham City")
    assert naming.parse_name(name).game == "Batman - Arkham City"


@pytest.mark.parametrize("name", [
    "notes.txt", "_Screenshot_Log.md", "2026-13-01 00.00.00.jpg",
    "20260412133715_1.jpg",                   # Steam's own name
])
def test_foreign_names_are_rejected(name):
    assert naming.parse_name(name) is None


def test_mismatched_countdown_reads_as_game_first():
    parsed = naming.parse_name("0000000000 - 2026-04-12 13.37.15.jpg")
    assert parsed.preset == "GameDate"
    assert parsed.game == "0000000000"


def test_unknown_preset_falls_back_to_default():
    assert naming.get_preset("NoSuchStyle").key == "Date"
    assert naming.get_preset(None).key == "Date"
    assert naming.get_preset("reverse").key == "Reverse"   # case-insensitive


def test_settings_roundtrip_and_normalize(fake_home):
    s = Settings.load()
    assert s.FileNamePreset == "Date"
    assert s.FileNamingChosen is False
    s.FileNamePreset = "Reverse"
    s.FileNamingChosen = True
    s.save()
    again = Settings.load()
    assert again.FileNamePreset == "Reverse"
    assert again.FileNamingChosen is True

    import json
    raw = json.loads(Settings.file_path().read_text())
    raw["FileNamePreset"] = "SomethingFromTheFuture"
    Settings.file_path().write_text(json.dumps(raw))
    assert Settings.load().FileNamePreset == "Date"


# ------------------------------------------------------------- the engine

def _names(engine, *rel):
    return sorted(os.listdir(backup_root(engine).joinpath(*rel)))


def test_scan_uses_the_chosen_preset(engine):
    engine._settings.FileNamePreset = "GameDate"
    run = engine.full_scan()
    assert run.copied == 8
    assert "Portal 2 - 2026-04-12 13.37.15.jpg" in _names(engine, "Standard", "Portal 2")
    assert engine.full_scan().copied == 0


def test_changing_preset_without_renaming_copies_nothing(engine):
    """Declining the rename must not make the next scan see every old-style
    file as missing and back it all up a second time."""
    engine.full_scan()
    engine._settings.FileNamePreset = "Reverse"
    assert engine.full_scan().copied == 0
    assert engine.find_missing_from_backup() == []
    assert engine.plan_scan() == []
    _, files, _ = engine.compute_totals()
    assert files == 8


def test_new_shots_use_the_new_preset_alongside_old_names(engine, steam_tree):
    from tests.conftest import make_jpeg
    engine.full_scan()
    engine._settings.FileNamePreset = "Compact"
    make_jpeg(steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
              / "screenshots" / "20260601120000_1.jpg")
    assert engine.full_scan().copied == 1
    names = _names(engine, "Standard", "Portal 2")
    assert "2026-06-01_12-00-00.jpg" in names
    assert "2026-04-12 13.37.15.jpg" in names


def test_rename_plan_and_apply(engine):
    engine.full_scan()
    plan = engine.plan_rename("Reverse")
    assert len(plan) == 8
    assert engine.rename_backups("Reverse") == 8
    engine._settings.FileNamePreset = "Reverse"

    names = _names(engine, "Standard", "Portal 2")
    assert all(naming.parse_name(n).preset == "Reverse" for n in names)
    assert engine.plan_rename("Reverse") == []
    assert engine.full_scan().copied == 0
    _, files, _ = engine.compute_totals()
    assert files == 8


def test_rename_to_game_first_uses_the_folder_name(engine):
    engine.full_scan()
    engine.rename_backups("GameDate")
    assert "Portal 2 - 2026-04-12 13.37.15 (2).jpg" in _names(
        engine, "Standard", "Portal 2")
    assert "Stardew Valley - 2026-03-01 09.00.00.png" in _names(
        engine, "High Resolution", "Stardew Valley")


def test_rename_back_restores_the_original_names(engine):
    engine.full_scan()
    before = _names(engine, "Standard", "Portal 2")
    engine.rename_backups("GameDate")
    engine.rename_backups("Date")
    assert _names(engine, "Standard", "Portal 2") == before


def test_rename_never_overwrites(engine):
    engine.full_scan()
    folder = backup_root(engine) / "Standard" / "Portal 2"
    blocker = folder / naming.format_name("Compact", datetime(2026, 4, 12, 15, 6, 32),
                                          1, ".jpg")
    blocker.write_bytes(b"someone else's file")
    engine.rename_backups("Compact")
    assert blocker.read_bytes() == b"someone else's file"
    assert (folder / "2026-04-12 15.06.32.jpg").is_file()   # left alone


def test_rename_leaves_foreign_files_alone(engine):
    engine.full_scan()
    stray = backup_root(engine) / "Standard" / "Portal 2" / "notes.txt"
    stray.write_text("mine")
    engine.rename_backups("Reverse")
    assert stray.read_text() == "mine"


def test_rename_rebuilds_existing_markdown_index(engine):
    engine.full_scan()
    engine.rebuild_markdown_index()
    engine.rename_backups("Compact")
    md = (backup_root(engine) / "Standard" / "Portal 2" / MD_FILE_NAME).read_text()
    assert "2026-04-12_13-37-15.jpg" in md
    assert "2026-04-12 13.37.15.jpg" not in md


def test_rename_does_not_create_markdown_index(engine):
    engine.full_scan()
    engine.rename_backups("Compact")
    assert not engine.markdown_index_exists()


def test_purge_originals_recognizes_other_preset_names(engine, steam_tree):
    engine.full_scan()
    engine._settings.FileNamePreset = "GameDate"   # files still in "Date" style
    assert engine.preview_purge_imported_originals()[0] == 8
    assert engine.purge_imported_originals() == 8


def test_log_message_path_follows_a_rename(engine):
    engine.full_scan()
    message = "Portal 2  ›  2026-04-12 13.37.15.jpg  [Standard]"
    engine.rename_backups("Reverse")
    engine._settings.FileNamePreset = "Reverse"
    path = engine.backup_path_from_log_message(message)
    assert os.path.isfile(path)
    assert naming.parse_name(os.path.basename(path)).preset == "Reverse"


def test_reorganize_keeps_custom_names(engine):
    engine._settings.FileNamePreset = "Reverse"
    engine.full_scan()
    engine.reorganize_layout("{game}", "{yyyy}/{game}")
    engine._settings.FolderTemplate = "{yyyy}/{game}"
    names = _names(engine, "Standard", "2026", "Portal 2")
    assert len(names) == 3
    assert engine.full_scan().copied == 0
