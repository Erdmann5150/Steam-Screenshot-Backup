"""If the trash is unavailable, nothing may be deleted — ever."""
import pytest

from tests.conftest import backup_root
from ssbackup.core.backup_engine import ScreenshotType
from ssbackup.core import trash as trash_mod


def test_originals_survive_when_trash_is_unavailable(engine, steam_tree, monkeypatch):
    engine.full_scan()

    # Simulate a filesystem with no trash folder (FAT/exFAT USB, some NAS mounts).
    def no_trash(path):
        raise trash_mod.TrashError("no trash folder on this volume")
    monkeypatch.setattr(trash_mod, "_send2trash", None)
    monkeypatch.setattr("ssbackup.core.backup_engine.trash_path", no_trash)

    src = (steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
           / "screenshots" / "20260412133715_1.jpg")
    before = src.read_bytes()

    engine._settings.DeleteOriginals = True
    run = engine.full_scan()

    assert src.is_file(), "a Steam original was deleted with no recoverable trash"
    assert src.read_bytes() == before
    assert run.originals_deleted == 0, "counted a deletion that never happened"


def test_purge_reports_zero_when_trash_unavailable(engine, steam_tree, monkeypatch):
    engine.full_scan()

    def no_trash(path):
        raise trash_mod.TrashError("no trash folder on this volume")
    monkeypatch.setattr("ssbackup.core.backup_engine.trash_path", no_trash)

    deleted = engine.purge_imported_originals(t=ScreenshotType.STANDARD)
    assert deleted == 0
    src = (steam_tree / "userdata" / "11111" / "760" / "remote" / "620"
           / "screenshots" / "20260412133715_1.jpg")
    assert src.is_file()


def test_backup_files_survive_when_trash_unavailable(engine, monkeypatch):
    engine.full_scan()
    shot = backup_root(engine) / "Standard" / "Portal 2" / "2026-04-12 13.37.15.jpg"

    def no_trash(path):
        raise trash_mod.TrashError("no trash folder on this volume")
    monkeypatch.setattr("ssbackup.core.backup_engine.trash_path", no_trash)

    deleted = engine.delete_files([str(shot)])
    assert deleted == 0
    assert shot.is_file(), "a backup file was deleted unrecoverably"


def test_trash_module_never_falls_back_to_unlink(tmp_path, monkeypatch):
    """The whole promise of this app's deletions is that they are recoverable."""
    monkeypatch.setattr(trash_mod, "_send2trash", None)
    victim = tmp_path / "precious.jpg"
    victim.write_text("data")

    with pytest.raises(trash_mod.TrashError):
        trash_mod.trash_path(victim)
    assert victim.is_file()
