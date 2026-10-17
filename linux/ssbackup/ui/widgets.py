"""Small shared building blocks: themed dialogs, a progress modal, and the
panel/edge helpers every window uses.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from ..core.backup_engine import format_bytes
from ..core.logger import Logger
from .theme import Theme

APP_TITLE = "Steam Screenshot Backup"


# ------------------------------------------------------------ layout helpers

def panel(height: int | None = None) -> QFrame:
    f = QFrame()
    f.setObjectName("Panel")
    if height is not None:
        f.setFixedHeight(height)
    return f


def edge() -> QFrame:
    f = QFrame()
    f.setObjectName("Edge")
    f.setFixedHeight(1)
    return f


def small_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Small")
    return lbl


def header_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Header")
    return lbl


def button(text: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setObjectName("Primary")
    b.setCursor(Qt.PointingHandCursor)
    return b


# ------------------------------------------------------------- message boxes

class MessageDialog(QDialog):
    """Themed replacement for QMessageBox so every dialog looks the same.

    A coloured accent stripe down the left edge ties the dialog to its severity,
    exactly like the Windows build.
    """

    def __init__(self, text: str, title: str, stripe: str,
                 ok_text: str, cancel_text: str | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(Theme.app_icon())
        self.setStyleSheet(Theme.stylesheet())
        self.setModal(True)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        strip = QFrame()
        strip.setFixedWidth(4)
        strip.setStyleSheet(f"background-color: {stripe}; border: none;")
        outer.addWidget(strip)

        body = QWidget()
        outer.addWidget(body, 1)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(18)

        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        msg.setMinimumWidth(360)
        msg.setMaximumWidth(520)
        layout.addWidget(msg)

        row = QHBoxLayout()
        row.addStretch(1)
        if cancel_text is not None:
            cancel = button(cancel_text)
            cancel.clicked.connect(self.reject)
            row.addWidget(cancel)
        ok = button(ok_text, primary=True)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        layout.addLayout(row)

        self.adjustSize()
        self.setMinimumWidth(min(560, max(380, self.sizeHint().width())))

    # ----------------------------------------------------------- shortcuts

    @staticmethod
    def info(text: str, title: str = APP_TITLE, parent=None) -> None:
        MessageDialog(text, title, Theme.p.accent, "OK", None, parent).exec()

    @staticmethod
    def fail(text: str, title: str = APP_TITLE, parent=None) -> None:
        MessageDialog(text, title, Theme.p.error, "OK", None, parent).exec()

    @staticmethod
    def ask_yes_no(text: str, title: str = APP_TITLE, parent=None) -> bool:
        dlg = MessageDialog(text, title, Theme.p.accent, "Yes", "No", parent)
        return dlg.exec() == QDialog.Accepted

    @staticmethod
    def confirm(text: str, title: str, ok_text: str,
                cancel_text: str, parent=None) -> bool:
        dlg = MessageDialog(text, title, Theme.p.accent, ok_text, cancel_text, parent)
        return dlg.exec() == QDialog.Accepted

    @staticmethod
    def confirm_deletion(action: str, count: int, total_bytes: int,
                         title: str = "Confirm Deletion", parent=None) -> bool:
        """Mandatory second-look confirmation before any deletion: always states
        exactly how many files and how much data are about to be moved to the
        trash.  Returns False (with an info dialog, not a confirmation) when
        there is nothing to delete."""
        if count == 0:
            MessageDialog.info(
                f"Nothing to delete — {action} found no matching files.",
                parent=parent)
            return False
        return MessageDialog.ask_yes_no(
            f"{action}\n\n"
            f"This will delete {count} file{'' if count == 1 else 's'} "
            f"({format_bytes(total_bytes)}), moved to the trash (recoverable).\n\n"
            "Continue?",
            title, parent)


# ---------------------------------------------------------- progress dialog

class _WorkSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(object, object)   # (result, exception)


class ProgressDialog(QDialog):
    """Shared modal "doing something in the background" dialog.

    Shows a themed message with an optional (done, total) bar and closes itself
    when the work finishes, so that boilerplate lives in exactly one place.
    """

    def __init__(self, title: str, initial_text: str, work, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(Theme.app_icon())
        self.setStyleSheet(Theme.stylesheet())
        self.setModal(True)
        self.setFixedWidth(420)
        # No close button: the work decides when this goes away.
        self.setWindowFlags(
            (self.windowFlags() | Qt.CustomizeWindowHint)
            & ~Qt.WindowCloseButtonHint & ~Qt.WindowContextHelpButtonHint
        )

        self._result = None
        self._error: Exception | None = None
        self._work = work
        self._initial_text = initial_text

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        self._label = QLabel(initial_text)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)   # indeterminate until the first progress tick
        self._bar.setTextVisible(False)
        layout.addWidget(self._bar)

        self._signals = _WorkSignals()
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_finished)

        QTimer.singleShot(0, self._start)

    def _start(self) -> None:
        def runner():
            result = None
            error = None
            try:
                result = self._work(
                    lambda done, total: self._signals.progress.emit(done, total))
            except Exception as ex:   # noqa: BLE001 - reported to the user
                error = ex
            self._signals.finished.emit(result, error)

        threading.Thread(target=runner, name="ProgressWork", daemon=True).start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            if self._bar.maximum() != total:
                self._bar.setRange(0, total)
                self._bar.setTextVisible(True)
            self._bar.setValue(done)
        self._label.setText(f"{self._initial_text}  {done} / {total}")

    def _on_finished(self, result, error) -> None:
        self._result = result
        self._error = error
        self.accept()

    def reject(self) -> None:
        pass   # the work owns this dialog's lifetime

    @staticmethod
    def run(parent, title: str, initial_text: str, work):
        """Runs `work(progress_callback)` on a worker thread behind a modal."""
        dlg = ProgressDialog(title, initial_text, work, parent)
        dlg.exec()
        if dlg._error is not None:
            Logger.error(f"{title} failed: {dlg._error}")
            MessageDialog.fail(f"{title.rstrip('.…')} failed:\n\n{dlg._error}",
                               parent=parent)
        return dlg._result
