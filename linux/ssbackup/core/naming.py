"""File-naming presets for backed-up screenshots.

Every preset encodes the same three facts - capture time, Steam's per-second
counter, and the extension - and can be parsed back into them, so the engine
recognizes a backup file whichever preset wrote it.  That is what lets the
naming style change without the next scan mistaking renamed (or not yet
renamed) files for missing ones and copying everything a second time.

"Date" is the default and the only style the Windows app writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

DEFAULT_PRESET = "Date"

# The reverse preset counts down from here, in seconds since _EPOCH, so names
# sort newest-first.  Ten digits last until the year 2316.
_EPOCH = datetime(2000, 1, 1)
_COUNTDOWN_START = 9_999_999_999

_DATE = (r"(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2}) "
         r"(?P<h>\d{2})\.(?P<mi>\d{2})\.(?P<s>\d{2})")
_PAREN_N = r"(?: \((?P<n>\d+)\))?"
_EXT = r"(?P<ext>\.\w+)"


@dataclass(frozen=True)
class ParsedName:
    preset: str
    timestamp: datetime
    index: int          # Steam's per-second counter; 1 for the first shot
    ext: str
    game: str | None = None


@dataclass(frozen=True)
class NamingPreset:
    key: str
    label: str
    description: str
    _pattern: re.Pattern
    _formatter: object  # (ts, index, ext, game) -> str

    def format(self, ts: datetime, index: int, ext: str, game: str = "") -> str:
        return self._formatter(ts, index, ext, sanitize_game(game))

    def parse(self, name: str) -> ParsedName | None:
        m = self._pattern.match(name)
        if not m:
            return None
        try:
            ts = datetime(int(m["y"]), int(m["mo"]), int(m["d"]),
                          int(m["h"]), int(m["mi"]), int(m["s"]))
        except ValueError:
            return None
        groups = m.groupdict()
        # A countdown that disagrees with its own date isn't one of ours; it is
        # far more likely a game-first name for a game called e.g. "1234567890".
        if "key" in groups and groups["key"] != _countdown(ts):
            return None
        return ParsedName(self.key, ts, int(groups.get("n") or 1), m["ext"],
                          groups.get("game"))


def sanitize_game(game: str | None) -> str:
    """The same character rules expand_template applies to folder names, plus
    path separators, which can't appear inside a file name."""
    clean = re.sub(r'[\\/:*?"<>|]', "", game or "").strip(" .")
    return clean or "Unknown Game"


def _countdown(ts: datetime) -> str:
    seconds = max(0, int((ts - _EPOCH).total_seconds()))
    return f"{_COUNTDOWN_START - seconds:010d}"


def _date(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H.%M.%S")


def _paren(index: int) -> str:
    return f" ({index})" if index > 1 else ""


PRESETS: list[NamingPreset] = [
    NamingPreset(
        "Date", "Date and time",
        "Sorting by name sorts by capture time, oldest first. The same names "
        "the Windows app uses.",
        re.compile(rf"^{_DATE}{_PAREN_N}{_EXT}$"),
        lambda ts, n, ext, game: f"{_date(ts)}{_paren(n)}{ext}"),
    NamingPreset(
        "Reverse", "Newest first (for Discord)",
        "A countdown number in front makes A-Z order newest first. Apps that "
        "reverse a multi-file upload, like Discord, then post the shots "
        "oldest first, in story order.",
        re.compile(rf"^(?P<key>\d{{10}}) - {_DATE}{_PAREN_N}{_EXT}$"),
        lambda ts, n, ext, game: f"{_countdown(ts)} - {_date(ts)}{_paren(n)}{ext}"),
    NamingPreset(
        "GameDate", "Game name, then date",
        "Keeps the game's name on the file when it's shared or moved out of "
        "its folder. Still sorts by time within a game.",
        re.compile(rf"^(?P<game>.+?) - {_DATE}{_PAREN_N}{_EXT}$"),
        lambda ts, n, ext, game: f"{game} - {_date(ts)}{_paren(n)}{ext}"),
    NamingPreset(
        "Compact", "Date and time, no spaces",
        "No spaces or brackets, for scripts, the command line and web uploads "
        "that mangle spaces.",
        re.compile(r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})_"
                   r"(?P<h>\d{2})-(?P<mi>\d{2})-(?P<s>\d{2})"
                   rf"(?:_(?P<n>\d+))?{_EXT}$"),
        lambda ts, n, ext, game: (ts.strftime("%Y-%m-%d_%H-%M-%S")
                                  + (f"_{n}" if n > 1 else "") + ext)),
]

_BY_KEY = {p.key.lower(): p for p in PRESETS}


def get_preset(key: str | None) -> NamingPreset:
    """The preset for a settings value, falling back to the default for an
    unknown or missing one (e.g. a settings file from a newer version)."""
    return _BY_KEY.get((key or "").strip().lower(), _BY_KEY[DEFAULT_PRESET.lower()])


def normalize_preset_key(key: str | None) -> str:
    return get_preset(key).key


def format_name(key: str | None, ts: datetime, index: int, ext: str,
                game: str = "") -> str:
    return get_preset(key).format(ts, index, ext, game)


def parse_name(name: str) -> ParsedName | None:
    """Parses a backup file name written by any preset.  The reverse preset is
    tried before game-first, since its countdown check is what tells a
    countdown apart from a numeric game name."""
    for preset in PRESETS:
        parsed = preset.parse(name)
        if parsed is not None:
            return parsed
    return None


def is_backup_name(name: str) -> bool:
    return parse_name(name) is not None


def candidate_names(ts: datetime, index: int, ext: str, game: str = "",
                    preferred: str | None = None) -> list[str]:
    """Every name this screenshot could have under any preset, the preferred
    preset's first."""
    first = get_preset(preferred)
    names = [first.format(ts, index, ext, game)]
    for p in PRESETS:
        if p is not first:
            names.append(p.format(ts, index, ext, game))
    return names


def example(key: str | None, game: str = "Portal 2") -> str:
    """A sample file name for showing a preset in the UI."""
    return format_name(key, datetime(2026, 4, 12, 13, 37, 15), 1, ".jpg", game)
