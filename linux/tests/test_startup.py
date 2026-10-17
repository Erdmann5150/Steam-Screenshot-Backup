"""Startup behaviour: single-instance locking and the tray-availability wait."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


from ssbackup.__main__ import _acquire_single_instance_lock, _wait_for_system_tray  # noqa: E402


class _TrayStub:
    """Reports the tray as missing for the first `misses` checks, the way
    Plasma does while its panel is still starting up."""

    def __init__(self, misses: int):
        self.remaining = misses
        self.checks = 0

    def isSystemTrayAvailable(self) -> bool:
        self.checks += 1
        if self.remaining > 0:
            self.remaining -= 1
            return False
        return True


def test_tray_wait_returns_immediately_when_present():
    stub = _TrayStub(misses=0)
    assert _wait_for_system_tray(stub, timeout=5) is True
    assert stub.checks == 1


def test_tray_wait_retries_while_the_panel_starts():
    """The autostart case: the tray shows up a few seconds after login."""
    stub = _TrayStub(misses=3)
    assert _wait_for_system_tray(stub, timeout=10) is True
    assert stub.checks >= 4


def test_tray_wait_eventually_gives_up():
    stub = _TrayStub(misses=10_000)
    assert _wait_for_system_tray(stub, timeout=1.0) is False
    assert stub.checks > 1


def test_single_instance_lock_is_exclusive(fake_home):
    first = _acquire_single_instance_lock()
    assert first is not None
    # A second attempt from the same process still contends on the same file.
    second = _acquire_single_instance_lock()
    assert second is None
    first.close()


def test_single_instance_lock_is_released_on_close(fake_home):
    first = _acquire_single_instance_lock()
    assert first is not None
    first.close()
    again = _acquire_single_instance_lock()
    assert again is not None
    again.close()
