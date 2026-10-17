"""End-to-end engine behaviour against the synthetic Steam tree."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ssbackup.core.backup_engine import MARKER_NAME, ScreenshotType
from tests.conftest import backup_root


# ------------------------------------------------------------ source scanning

def test_enumerates_all_sources(engine):
    sources = list(engine.enumerate_sources())
    paths = [os.path.basename(p) for p, _, _ in sources]

    # 6 standard shots across two accounts, 2 external copies.
    assert len(sources) == 8
    assert paths.count("20260412133715_1.jpg") == 1
    # The thumbnails/ copy must not be picked up.
    assert not any("thumbnails" in p for p, _, _ in sources)


def test_skips_thumbnails_directory(engine):
    # Checked against the Steam-relative portion, since pytest's own tmp dir
    # name can contain the word "thumbnails".
    for path, _, _ in engine.enumerate_sources():
        assert "/screenshots/thumbnails/" not in path


def test_covers_every_steam_account(engine):
    appids = {appid for _, appid, _ in engine.enumerate_sources()}
    assert "620" in appids       # account 11111
    assert "413150" in appids    # account 22222


# ------------------------------------------------------------------ full scan

def test_full_scan_creates_expected_layout(engine):
    run = engine.full_scan()
    assert run is not None
    assert run.copied == 8

    root = backup_root(engine)
    assert (root / "Standard" / "Portal 2" / "2026-04-12 13.37.15.jpg").is_file()
    assert (root / "Standard" / "Portal 2" / "2026-04-12 13.37.15 (2).jpg").is_file()
    assert (root / "Standard" / "Portal 2" / "2026-04-12 15.06.32.jpg").is_file()
    assert (root / "Standard" / "Stardew Valley" / "2026-03-01 09.00.00.jpg").is_file()
    assert (root / "High Resolution" / "Portal 2"
            / "2026-04-12 13.37.15.png").is_file()


def test_resolves_installed_game_from_manifest(engine):
    engine.full_scan()
    assert (backup_root(engine) / "Standard" / "Portal 2").is_dir()


def test_resolves_second_library_drive_game(engine):
    engine.full_scan()
    assert (backup_root(engine) / "Standard" / "Stardew Valley").is_dir()


def test_resolves_non_steam_shortcut(engine):
    engine.full_scan()
    assert (backup_root(engine) / "Standard" / "Balatro (non-Steam)").is_dir()


def test_unresolvable_game_falls_back_to_appid(engine):
    engine.full_scan()
    assert (backup_root(engine) / "Standard" / "AppID_1234567").is_dir()


def test_unresolved_folders_are_reported(engine):
    engine.full_scan()
    unresolved = engine.find_unresolved_game_folders()
    assert [appid for appid, _ in unresolved] == ["1234567"]


def test_second_scan_copies_nothing(engine):
    engine.full_scan()
    run = engine.full_scan()
    assert run.copied == 0
    assert run.skipped == 8


def test_scan_is_incremental(engine, steam_tree):
    from tests.conftest import make_jpeg
    engine.full_scan()
    make_jpeg(steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
              / "screenshots" / "20260601180000_1.jpg")
    run = engine.full_scan()
    assert run.copied == 1
    assert (backup_root(engine) / "Standard" / "Portal 2"
            / "2026-06-01 18.00.00.jpg").is_file()


def test_backup_is_tagged_with_game_name(engine):
    from ssbackup.core.metadata import has_game_name_metadata
    engine.full_scan()
    shot = backup_root(engine) / "Standard" / "Portal 2" / "2026-04-12 13.37.15.jpg"
    assert has_game_name_metadata(shot)
    assert "Portal 2".encode("utf-16-le") in shot.read_bytes()


def test_source_files_are_never_modified(engine, steam_tree):
    src = (steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
           / "screenshots" / "20260412133715_1.jpg")
    before = src.read_bytes()
    engine.full_scan()
    assert src.read_bytes() == before
    assert src.is_file()


def test_mtime_is_preserved_on_the_copy(engine, steam_tree):
    src = (steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
           / "screenshots" / "20260412133715_1.jpg")
    os.utime(src, (1200000, 1200000))
    engine.full_scan()
    dest = backup_root(engine) / "Standard" / "Portal 2" / "2026-04-12 13.37.15.jpg"
    assert int(dest.stat().st_mtime) == 1200000


# -------------------------------------------------------------------- totals

def test_compute_totals(engine):
    engine.full_scan()
    games, files, total = engine.compute_totals()
    assert files == 8
    # Portal 2, Stardew Valley, Balatro, AppID_1234567 - counted once each even
    # though Portal 2 and Stardew Valley appear under both type folders.
    assert games == 4
    assert total > 0


def test_totals_ignore_foreign_files(engine):
    engine.full_scan()
    stray = backup_root(engine) / "Standard" / "Portal 2" / "notes.txt"
    stray.write_text("not mine")
    _, files, _ = engine.compute_totals()
    assert files == 8   # unchanged


# ----------------------------------------------------------- folder templates

def test_template_change_plan_and_reorganize(engine):
    engine.full_scan()
    plan = engine.plan_reorganize("{game}", "{yyyy}/{game}")
    assert len(plan) == 8

    engine.reorganize_layout("{game}", "{yyyy}/{game}")
    engine._settings.FolderTemplate = "{yyyy}/{game}"

    root = backup_root(engine)
    assert (root / "Standard" / "2026" / "Portal 2"
            / "2026-04-12 13.37.15.jpg").is_file()
    assert not (root / "Standard" / "Portal 2").exists()


def test_scan_after_reorganize_copies_nothing(engine):
    """The setting and the on-disk layout must agree, or the next scan would
    recopy everything into the new shape."""
    engine.full_scan()
    engine.reorganize_layout("{game}", "{yyyy}/{game}")
    engine._settings.FolderTemplate = "{yyyy}/{game}"
    run = engine.full_scan()
    assert run.copied == 0


def test_totals_correct_under_nested_template(engine):
    engine._settings.FolderTemplate = "{yyyy}/{game}"
    engine.full_scan()
    games, files, _ = engine.compute_totals()
    assert files == 8
    assert games == 4


# --------------------------------------------------------------- re-sync

def test_find_missing_after_deletion(engine):
    engine.full_scan()
    shot = backup_root(engine) / "Standard" / "Portal 2" / "2026-04-12 13.37.15.jpg"
    shot.unlink()

    missing = engine.find_missing_from_backup()
    assert len(missing) == 1
    assert missing[0].display_name == "2026-04-12 13.37.15.jpg"
    assert missing[0].game == "Portal 2"


def test_resync_restores_the_file(engine):
    engine.full_scan()
    shot = backup_root(engine) / "Standard" / "Portal 2" / "2026-04-12 13.37.15.jpg"
    shot.unlink()

    copied = engine.resync(engine.find_missing_from_backup())
    assert copied == 1
    assert shot.is_file()
    assert engine.find_missing_from_backup() == []


def test_resync_is_a_no_op_when_in_sync(engine):
    engine.full_scan()
    assert engine.find_missing_from_backup() == []


# ------------------------------------------------------------ plan / preview

def test_plan_scan_lists_pending_imports(engine):
    plan = engine.plan_scan()
    assert len(plan) == 8
    assert all(src and dest for src, dest in plan)

    engine.full_scan()
    assert engine.plan_scan() == []


# ----------------------------------------------------------- markdown index

def test_markdown_index_generated(engine):
    engine._settings.GenerateMarkdownIndex = True
    engine.full_scan()
    md = backup_root(engine) / "Standard" / "Portal 2" / "_Screenshot_Log.md"
    assert md.is_file()
    text = md.read_text()
    assert text.startswith("# Screenshots")
    assert "### 2026-04-12" in text
    assert "![2026-04-12 13.37.15](<2026-04-12 13.37.15.jpg>)" in text


def test_markdown_rebuild_groups_by_day(engine):
    engine.full_scan()
    count = engine.rebuild_markdown_index()
    assert count > 0
    md = backup_root(engine) / "Standard" / "Portal 2" / "_Screenshot_Log.md"
    text = md.read_text()
    assert text.count("### 2026-04-12") == 1   # one header for three same-day shots
    assert text.count("![") == 3


def test_markdown_index_excluded_from_totals(engine):
    engine._settings.GenerateMarkdownIndex = True
    engine.full_scan()
    _, files, _ = engine.compute_totals()
    assert files == 8


def test_markdown_delete(engine):
    engine.full_scan()
    engine.rebuild_markdown_index()
    assert engine.markdown_index_exists()
    count, _ = engine.preview_markdown_indexes()
    assert count > 0
    engine.delete_markdown_indexes()
    assert not engine.markdown_index_exists()


# ---------------------------------------------------------- granular deletion

def test_backup_tree_groups_by_type_and_game(engine):
    engine.full_scan()
    tree = engine.get_backup_tree()
    assert "Portal 2" in tree[ScreenshotType.STANDARD]
    assert len(tree[ScreenshotType.STANDARD]["Portal 2"]) == 3
    assert "Portal 2" in tree[ScreenshotType.HIGH_RES]


def test_source_tree_marks_entries_as_source(engine):
    tree = engine.get_steam_source_tree()
    entries = tree[ScreenshotType.STANDARD]["Portal 2"]
    assert all(e.is_source for e in entries)


def test_delete_files_moves_to_trash(engine):
    engine.full_scan()
    shot = backup_root(engine) / "Standard" / "Portal 2" / "2026-04-12 13.37.15.jpg"
    assert shot.is_file()
    deleted = engine.delete_files([str(shot)])
    assert deleted == 1
    assert not shot.exists()
    # It went to the trash, not into the void.
    trash = Path.home() / ".local" / "share" / "Trash" / "files"
    assert any(trash.glob("2026-04-12 13.37.15*"))


def test_delete_type_backups(engine):
    engine.full_scan()
    count, size = engine.preview_type_backups(ScreenshotType.HIGH_RES)
    assert count == 2
    assert size > 0
    engine.delete_type_backups(ScreenshotType.HIGH_RES)
    assert not (backup_root(engine) / "High Resolution").exists()
    assert (backup_root(engine) / "Standard").is_dir()


# ------------------------------------------------------- delete originals

def test_originals_kept_by_default(engine, steam_tree):
    engine.full_scan()
    src = (steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
           / "screenshots" / "20260412133715_1.jpg")
    assert src.is_file()


def test_purge_imported_originals(engine, steam_tree):
    engine.full_scan()
    count, _ = engine.preview_purge_imported_originals(ScreenshotType.STANDARD)
    assert count == 6
    deleted = engine.purge_imported_originals(t=ScreenshotType.STANDARD)
    assert deleted == 6
    src = (steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
           / "screenshots" / "20260412133715_1.jpg")
    assert not src.exists()
    # The external copies were not in scope.
    assert count == 6


def test_purge_only_deletes_verified_backups(engine, steam_tree):
    """An original with no backup must survive, or turning the setting on could
    destroy screenshots that were never copied."""
    from tests.conftest import make_jpeg
    engine.full_scan()
    orphan = (steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
              / "screenshots" / "20261212121212_1.jpg")
    make_jpeg(orphan)
    engine.purge_imported_originals(t=ScreenshotType.STANDARD)
    assert orphan.is_file()


def test_delete_originals_setting_during_scan(engine, steam_tree):
    engine._settings.DeleteOriginals = True
    run = engine.full_scan()
    assert run.originals_deleted == 8
    src = (steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
           / "screenshots" / "20260412133715_1.jpg")
    assert not src.exists()


# -------------------------------------------------------- destination safety

def test_marker_file_is_written(engine):
    engine.full_scan()
    assert (backup_root(engine) / MARKER_NAME).is_file()


def test_vanished_mount_is_detected_as_offline(engine):
    """The Linux failure mode the Windows build never had: an unmounted NAS
    leaves an empty, writable directory behind, and a naive existence check
    would start filling the system disk with a second copy of everything."""
    engine.full_scan()
    root = backup_root(engine)

    # Simulate the unmount: the directory is still there, but empty.
    import shutil
    shutil.rmtree(root)
    root.mkdir(parents=True)

    assert engine._check_destination_available() is False
    assert engine.offline is True
    # And nothing gets written while it is in that state.
    assert engine.full_scan() is None
    assert list(root.iterdir()) == []


def test_destination_recovers_when_remounted(engine):
    engine.full_scan()
    root = backup_root(engine)
    marker = root / MARKER_NAME
    marker.unlink()
    assert engine._check_destination_available() is False

    marker.write_text("back")
    assert engine._check_destination_available() is True
    assert engine.offline is False


def test_missing_destination_is_created_on_first_run(engine, fake_home):
    new_dest = fake_home / "Elsewhere" / "Shots"
    engine._settings.Destination = str(new_dest)
    engine._marker_seen_for = None
    assert engine._check_destination_available() is True
    assert new_dest.is_dir()


def test_deeply_nested_new_destination_is_created(engine, fake_home):
    """Picking a folder several levels deep that doesn't exist yet is the
    normal first-run case and must work."""
    engine._settings.Destination = str(fake_home / "a" / "b" / "c" / "Shots")
    engine._marker_seen_for = None
    assert engine._check_destination_available() is True
    assert (fake_home / "a" / "b" / "c" / "Shots").is_dir()


@pytest.mark.skipif(os.geteuid() == 0,
                    reason="root bypasses write permissions, so this check "
                           "cannot be exercised as root")
def test_unwritable_mount_point_is_offline(engine, tmp_path):
    """The dangerous case: the path exists but nothing under it can be written,
    which is what a dropped root-owned mount point looks like."""
    import stat
    mount = tmp_path / "mnt"
    mount.mkdir()
    mount.chmod(stat.S_IRUSR | stat.S_IXUSR)   # read+execute, no write
    try:
        engine._settings.Destination = str(mount / "nas" / "Shots")
        engine._marker_seen_for = None
        assert engine._check_destination_available() is False
        assert engine.offline is True
    finally:
        mount.chmod(0o755)


# ------------------------------------------------------------------ migration

def test_move_backup_to_new_destination(engine, fake_home):
    engine.full_scan()
    old = backup_root(engine)
    new = fake_home / "Backups2"

    engine.move_backup(str(old), str(new))
    assert (new / "Standard" / "Portal 2" / "2026-04-12 13.37.15.jpg").is_file()
    assert not (old / "Standard" / "Portal 2").exists()


def test_legacy_layout_is_migrated_under_standard(engine, fake_home):
    """Older versions put game folders directly in the backup root."""
    from tests.conftest import make_jpeg
    root = backup_root(engine)
    make_jpeg(root / "Old Game" / "2025-01-01 10.00.00.jpg")

    engine._settings.StructureMigrated = False
    engine.migrate_structure_if_needed()
    assert (root / "Standard" / "Old Game" / "2025-01-01 10.00.00.jpg").is_file()
    assert not (root / "Old Game").exists()


def test_migration_leaves_foreign_folders_alone(engine):
    root = backup_root(engine)
    (root / "My Other Stuff").mkdir(parents=True)
    (root / "My Other Stuff" / "readme.txt").write_text("mine")

    engine._settings.StructureMigrated = False
    engine.migrate_structure_if_needed()
    assert (root / "My Other Stuff" / "readme.txt").is_file()


# ------------------------------------------------------------- log reverse-map

def test_backup_path_from_log_message(engine):
    engine.full_scan()
    msg = "Portal 2  ›  2026-04-12 13.37.15.jpg  [Standard]"
    path = engine.backup_path_from_log_message(msg)
    assert path is not None
    assert Path(path).is_file()


def test_backup_path_from_unrelated_message(engine):
    assert engine.backup_path_from_log_message("Watching for new screenshots.") is None


def test_changing_destination_without_migrating_still_works(engine, fake_home):
    """Changing the backup folder and declining migration must not leave the
    new, correctly-empty folder looking like an unmounted drive."""
    engine.full_scan()
    assert engine._marker_seen_for is not None

    new_dest = fake_home / "NewBackups"
    engine._settings.Destination = str(new_dest)

    assert engine._check_destination_available() is True
    assert engine.offline is False

    run = engine.full_scan()
    assert run is not None, "refused to write to a brand-new destination"
    assert run.copied == 8
    assert (new_dest / "Standard" / "Portal 2"
            / "2026-04-12 13.37.15.jpg").is_file()


def test_unmount_detection_still_works_after_a_destination_change(engine, fake_home):
    """The destination-aware marker must not weaken the unmount check itself."""
    import shutil
    engine.full_scan()

    new_dest = fake_home / "NewBackups"
    engine._settings.Destination = str(new_dest)
    engine.full_scan()                      # claims the new destination
    assert engine._marker_seen_for == str(new_dest)

    shutil.rmtree(new_dest)                 # the "volume" goes away
    new_dest.mkdir(parents=True)            # bare mount point left behind

    assert engine._check_destination_available() is False
    assert engine.offline is True
