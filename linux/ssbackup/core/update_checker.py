"""Checks GitHub's releases against the running version.

One read-only HTTPS GET to the public releases API, nothing else sent or
received beyond that.  Skipped entirely when Settings.OfflineMode is on.

This app shares a repository with the Windows version, which has its own
independent version number (3.x at the time of writing, against this app's
1.x).  So "newest release" is not a usable signal: /releases/latest would
return a Windows release and this app would report an update forever.  Only
tags carrying the Linux prefix below are considered, which keeps the two
release streams from seeing each other.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .. import __version__
from .logger import Logger

REPO = "Erdmann5150/Steam-Screenshot-Backup"

# Releases of this app are tagged "linux-v1.2.3"; the Windows app uses bare
# "v3.11.7" tags, and neither stream should ever notify about the other.
TAG_PREFIX = "linux-v"

# The list endpoint, not /releases/latest - see the module docstring.
RELEASES_API_URL = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
RELEASES_PAGE_URL = f"https://github.com/{REPO}/releases"

CURRENT_VERSION = __version__


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str


def strip_tag_prefix(tag: str | None) -> str | None:
    """The version part of a "linux-v1.2.3" tag, or None if the tag belongs to
    another release stream (the Windows app's bare "v3.11.7", say)."""
    if not tag:
        return None
    tag = tag.strip()
    if not tag.lower().startswith(TAG_PREFIX.lower()):
        return None
    return tag[len(TAG_PREFIX):] or None


def _parse_version(text: str | None) -> tuple[int, ...] | None:
    """Parses a dotted numeric version, ignoring any leading 'v' and any
    pre-release suffix.  Returns None for anything unparseable."""
    if not text:
        return None
    cleaned = text.strip().lstrip("vV")
    m = re.match(r"^(\d+(?:\.\d+)*)", cleaned)
    if not m:
        return None
    try:
        parts = tuple(int(p) for p in m.group(1).split("."))
    except ValueError:
        return None
    return parts or None


def _pad(a: tuple[int, ...], length: int) -> tuple[int, ...]:
    return a + (0,) * (length - len(a))


def newer_version_or_none(tag: str | None, current: str) -> str | None:
    """Pure comparison logic, kept separate from the network call so it can be
    unit-tested without one.  Returns the cleaned tag if it parses as a version
    newer than `current`, otherwise None.

    Accepts a tag with or without the Linux prefix, so it can be used on both
    raw release tags and already-stripped versions.
    """
    stripped = strip_tag_prefix(tag)
    candidate = stripped if stripped is not None else tag

    latest = _parse_version(candidate)
    running = _parse_version(current)
    if latest is None or running is None:
        return None
    length = max(len(latest), len(running))
    if _pad(latest, length) > _pad(running, length):
        return (candidate or "").strip().lstrip("vV")
    return None


def newest_linux_release(releases, current: str) -> UpdateInfo | None:
    """Picks the newest release whose tag belongs to this app's stream.

    `releases` is the decoded /releases list.  Drafts and prereleases are
    skipped, as is anything tagged for the Windows app.  Returns None when
    nothing in the list is newer than `current`.
    """
    if not isinstance(releases, list):
        return None

    best: tuple[tuple[int, ...], str, str] | None = None
    for entry in releases:
        if not isinstance(entry, dict):
            continue
        if entry.get("draft") or entry.get("prerelease"):
            continue
        version = strip_tag_prefix(entry.get("tag_name"))
        if version is None:
            continue   # the Windows app's stream, or an unrelated tag
        parsed = _parse_version(version)
        if parsed is None:
            continue
        url = entry.get("html_url") or RELEASES_PAGE_URL
        # GitHub returns newest-first, but ordering is not guaranteed and a
        # backdated release would break it, so compare rather than take [0].
        if best is None or parsed > best[0]:
            best = (parsed, version, url)

    if best is None:
        return None
    if newer_version_or_none(best[1], current) is None:
        return None
    return UpdateInfo(version=best[1], url=best[2])


def check_now(settings) -> UpdateInfo | None:
    """The latest published release's version/url, or None when up to date,
    offline mode is on, or the check failed for any reason.  Never raises,
    since it runs unattended on a background timer."""
    if settings.OfflineMode:
        return None
    try:
        req = urllib.request.Request(
            RELEASES_API_URL,
            headers={
                # GitHub's API rejects requests with no User-Agent.
                "User-Agent": "SteamScreenshotBackup-Linux-UpdateCheck",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            doc = json.loads(resp.read().decode("utf-8", errors="replace"))

        return newest_linux_release(doc, CURRENT_VERSION)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as ex:
        Logger.warn(f"Update check failed: {ex}")
        return None
