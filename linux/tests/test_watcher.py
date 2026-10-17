"""Live file-watching: a screenshot appearing while the app runs.

These exercise the real inotify observers rather than the catch-up scan, since
that is the path the app spends virtually all its time in.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ssbackup.core.app_names import AppNameResolver
from ssbackup.core.backup_engine import BackupEngine
from ssbackup.core.settings import Settings
from tests.conftest import make_jpeg, make_png


def wait_for(predicate, timeout: float = 15.0, interval: float = 0.1) -> bool:
    """Polls until the predicate holds, so these tests are not timing-fragile
    on a slow or loaded machine."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def watching_engine(steam_tree, fake_home, monkeypatch):
    settings = Settings.load()
    settings.Destination = str(fake_home / "Backups" / "Steam Screenshots")
    settings.OfflineMode = True
    settings.FirstRunDone = True
    settings.StructureMigrated = True
    settings.save()

    monkeypatch.setattr(AppNameResolver, "_start_refresh_timer", lambda self: None)
    eng = BackupEngine(settings)
    eng.full_scan()          # start from a synced state
    eng.start_watching()
    time.sleep(0.4)          # let the observers arm
    yield eng
    eng.dispose()


def test_new_screenshot_is_backed_up_automatically(watching_engine, steam_tree):
    engine = watching_engine
    dest = (Path(engine.destination) / "Standard" / "Portal 2"
            / "2026-08-09 14.30.00.jpg")
    assert not dest.exists()

    make_jpeg(steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
              / "screenshots" / "20260809143000_1.jpg")

    assert wait_for(dest.is_file), "the watcher never copied the new screenshot"


def test_new_high_res_copy_is_backed_up(watching_engine, fake_home):
    engine = watching_engine
    dest = (Path(engine.destination) / "High Resolution" / "Portal 2"
            / "2026-08-09 14.30.00.png")
    assert not dest.exists()

    make_png(fake_home / "Pictures" / "Uncompressed" / "620_20260809143000_1.png")

    assert wait_for(dest.is_file), "the watcher never copied the external copy"


def test_screenshot_for_a_new_game_folder_is_caught(watching_engine, steam_tree):
    """A game screenshotted for the first time creates its appid directory
    while we are already watching, so the watch has to be recursive."""
    engine = watching_engine
    make_jpeg(steam_tree / "userdata" / "11111" / "760" / "remote" / "413150"
              / "screenshots" / "20260809150000_1.jpg")

    dest = (Path(engine.destination) / "Standard" / "Stardew Valley"
            / "2026-08-09 15.00.00.jpg")
    assert wait_for(dest.is_file), "a brand-new game folder was not watched"


def test_thumbnails_are_ignored_by_the_watcher(watching_engine, steam_tree):
    engine = watching_engine
    make_jpeg(steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
              / "screenshots" / "thumbnails" / "20260809160000_1.jpg")
    time.sleep(1.5)

    dest = (Path(engine.destination) / "Standard" / "Portal 2"
            / "2026-08-09 16.00.00.jpg")
    assert not dest.exists()


def test_unrelated_file_is_ignored(watching_engine, steam_tree):
    engine = watching_engine
    folder = (steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
              / "screenshots")
    (folder / "notes.txt").write_text("not a screenshot")
    time.sleep(1.0)

    _, files, _ = engine.compute_totals()
    assert files == 8   # unchanged


def test_paused_engine_ignores_new_screenshots(watching_engine, steam_tree):
    engine = watching_engine
    engine.paused = True

    make_jpeg(steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
              / "screenshots" / "20260809170000_1.jpg")
    time.sleep(1.5)

    dest = (Path(engine.destination) / "Standard" / "Portal 2"
            / "2026-08-09 17.00.00.jpg")
    assert not dest.exists()

    # And resuming plus a manual scan picks it up, so nothing is lost.
    engine.paused = False
    engine.full_scan()
    assert dest.is_file()


def test_deletion_from_backup_is_detected(watching_engine):
    """The destination watcher is what drives auto-restore."""
    engine = watching_engine
    fired = []
    engine.restore_needed.append(lambda: fired.append(True))

    shot = (Path(engine.destination) / "Standard" / "Portal 2"
            / "2026-04-12 13.37.15.jpg")
    shot.unlink()

    # The engine debounces for 5 s so a folder delete is one event, not many.
    assert wait_for(lambda: bool(fired), timeout=20.0), \
        "deleting a backup file never triggered a restore"
