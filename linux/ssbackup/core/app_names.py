"""Turns Steam appids into real game names, cheapest source first.

  1. app manifests of installed games (all library drives)
  2. the persistent name cache (same appnames.json the Windows app and the
     PowerShell script use, so the file is portable between them)
  3. shortcuts.vdf for non-Steam games added to Steam
  4. the Steam store API (result cached, but periodically re-verified in the
     background - see refresh_stale_entries)

Unresolvable ids fall back to "AppID_<id>" / "Non-Steam App <id>".
Step 4 is skipped entirely when Settings.OfflineMode is on.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import steam_config
from .logger import Logger
from .settings import Settings

STORE_THROTTLE_SECONDS = 0.5   # min gap between Steam store API calls

# Names resolved from the store are cached effectively forever (Steam appids
# essentially never get renamed), but rare cases do happen (Early Access -> 1.0
# rebrand), so each entry is silently re-verified every REFRESH_AGE_DAYS, a
# small batch at a time so a large cache never bursts a flood of API calls.
REFRESH_INTERVAL = timedelta(hours=24)
REFRESH_FIRST_RUN = timedelta(minutes=2)
REFRESH_BATCH_SIZE = 20
REFRESH_AGE_DAYS = 30

STORE_URL = "https://store.steampowered.com/api/appdetails?appids={appid}&filters=basic"
USER_AGENT = "SteamScreenshotBackup-Linux"

# Kept identical to the Windows app so both produce the same folder names for
# the same game, even though Linux itself would allow most of these characters.
_ILLEGAL = re.compile(r'[\\/:*?"<>|�]')


def sanitize(name: str | None) -> str | None:
    if not name or not name.strip():
        return None
    clean = _ILLEGAL.sub("", name).strip(" .")
    return clean or None


class AppNameResolver:
    def __init__(self, steam_roots: list[Path], settings: Settings):
        self._roots = steam_roots
        self._settings = settings
        self._lock = threading.RLock()
        self._store_lock = threading.Lock()

        self._manifest_names: dict[str, str] = {}
        self._cache: dict[str, str] = {}
        self._verified_at: dict[str, datetime] = {}
        self._failed_lookups: set[str] = set()   # per-session
        self._shortcut_names: dict[int, str] | None = None

        self._cache_file = Settings.dir() / "appnames.json"
        self._verified_file = Settings.dir() / "appnames.verified.json"

        self._last_manifest_scan = datetime.min.replace(tzinfo=timezone.utc)
        self._last_store_call = 0.0

        self._stop = threading.Event()
        self._refresh_thread: threading.Thread | None = None

        self._load_cache()
        self._load_verified()
        self.scan_manifests()
        self._start_refresh_timer()

    # ------------------------------------------------------------- lifecycle

    def _start_refresh_timer(self) -> None:
        def loop():
            if self._stop.wait(REFRESH_FIRST_RUN.total_seconds()):
                return
            while not self._stop.is_set():
                try:
                    self.refresh_stale_entries()
                except Exception as ex:
                    Logger.warn(f"Name cache refresh failed: {ex}")
                if self._stop.wait(REFRESH_INTERVAL.total_seconds()):
                    return

        self._refresh_thread = threading.Thread(
            target=loop, name="NameCacheRefresh", daemon=True
        )
        self._refresh_thread.start()

    def dispose(self) -> None:
        self._stop.set()

    @property
    def cache_file_path(self) -> Path:
        return self._cache_file

    def set_steam_roots(self, roots: list[Path]) -> None:
        with self._lock:
            self._roots = roots
            self._shortcut_names = None
        self.scan_manifests()

    # --------------------------------------------------------------- resolve

    def resolve_folder_name(self, appid: str) -> str:
        safe = sanitize(self._resolve(appid))
        if safe:
            return safe
        return (f"Non-Steam App {appid}"
                if steam_config.is_non_steam_app_id(appid)
                else f"AppID_{appid}")

    def _resolve(self, appid: str) -> str | None:
        with self._lock:
            if appid in self._manifest_names:
                return self._manifest_names[appid]
            if appid in self._cache:
                return self._cache[appid]
            if appid in self._failed_lookups:
                return None

        # Non-Steam shortcut games never resolve via manifests or the store.
        if steam_config.is_non_steam_app_id(appid):
            shortcut = self._resolve_shortcut(appid)
            if shortcut:
                with self._lock:
                    self._cache[appid] = shortcut
                self._save_cache()
            else:
                with self._lock:
                    self._failed_lookups.add(appid)
            return shortcut

        # Games installed after startup won't be in the manifest map yet;
        # rescan, throttled to once a minute.
        if (datetime.now(timezone.utc) - self._last_manifest_scan) > timedelta(minutes=1):
            self.scan_manifests()
            with self._lock:
                if appid in self._manifest_names:
                    return self._manifest_names[appid]

        name = None if self._settings.OfflineMode else self._query_store(appid)
        with self._lock:
            if name:
                self._cache[appid] = name
            else:
                self._failed_lookups.add(appid)   # don't hammer the API again
        if name:
            self._save_cache()
        return name

    def _resolve_shortcut(self, appid: str) -> str | None:
        with self._lock:
            if self._shortcut_names is None:
                self._shortcut_names = steam_config.read_shortcut_names(self._roots)
            shortcuts = self._shortcut_names
        try:
            value = int(appid)
        except (TypeError, ValueError):
            return None
        # The screenshot folder id is the 32-bit shortcut id, sometimes shifted
        # into the high dword of a 64-bit value; try both interpretations.
        for key in (value, value >> 32, value & 0xFFFFFFFF):
            if key in shortcuts:
                return shortcuts[key]
        return None

    # ---------------------------------- cache editing API for the UI

    def get_cached_names(self) -> dict[str, str]:
        with self._lock:
            return dict(sorted(self._cache.items()))

    def set_cached_name(self, appid: str, name: str) -> None:
        with self._lock:
            self._cache[appid] = name
            self._failed_lookups.discard(appid)
        self._save_cache()

    def remove_cached_name(self, appid: str) -> None:
        with self._lock:
            self._cache.pop(appid, None)
            self._failed_lookups.discard(appid)
            self._verified_at.pop(appid, None)
        self._save_cache()

    def is_tracked(self, appid: str) -> bool:
        with self._lock:
            return appid in self._cache

    def try_resolve_now(self, appid: str) -> str | None:
        """Forces a fresh resolution attempt, bypassing this session's
        failed-lookup cache.  A successful result is recorded in the persistent
        list even when it came from a free source, so it is visible and
        editable from the Game Names window."""
        with self._lock:
            self._failed_lookups.discard(appid)
        name = self._resolve(appid)
        if name:
            self.set_cached_name(appid, name)
        return name

    # ----------------------------------------- background cache maintenance

    def refresh_stale_entries(self) -> None:
        """Re-verifies a bounded batch of the oldest store-resolved entries, so
        a rename eventually gets picked up without ever hammering the API.
        Manifest- and shortcut-backed entries are skipped: those sources are
        re-scanned fresh elsewhere."""
        if self._settings.OfflineMode:
            return

        with self._lock:
            cutoff = datetime.now(timezone.utc) - timedelta(days=REFRESH_AGE_DAYS)
            candidates = [
                appid for appid in self._cache
                if not steam_config.is_non_steam_app_id(appid)
                and appid not in self._manifest_names
                and (appid not in self._verified_at or self._verified_at[appid] < cutoff)
            ]
            candidates.sort(
                key=lambda a: self._verified_at.get(
                    a, datetime.min.replace(tzinfo=timezone.utc))
            )
            batch = candidates[:REFRESH_BATCH_SIZE]

        if not batch:
            return

        cache_changed = False
        for appid in batch:
            if self._stop.is_set():
                return
            fresh = self._query_store(appid)
            if not fresh:
                continue  # network/lookup failure; retry on a later pass
            with self._lock:
                current = self._cache.get(appid)
                if current is None:
                    continue  # removed meanwhile
                if current != fresh:
                    self._cache[appid] = fresh
                    cache_changed = True
                    Logger.log(f'Game name updated: "{current}" is now "{fresh}" ({appid}).')
                self._verified_at[appid] = datetime.now(timezone.utc)

        if cache_changed:
            self._save_cache()
        self._save_verified()

    # ----------------------------------------------------------- sources

    def scan_manifests(self) -> None:
        with self._lock:
            self._last_manifest_scan = datetime.now(timezone.utc)
            roots = list(self._roots)

        found: dict[str, str] = {}
        for lib in steam_config.library_folders(roots):
            try:
                for acf in lib.glob("appmanifest_*.acf"):
                    try:
                        raw = acf.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    id_m = re.search(r'"appid"\s+"(\d+)"', raw, re.IGNORECASE)
                    name_m = re.search(r'"name"\s+"([^"]+)"', raw, re.IGNORECASE)
                    if id_m and name_m:
                        found[id_m.group(1)] = name_m.group(1)
            except OSError:
                continue

        with self._lock:
            self._manifest_names.update(found)

    def _query_store(self, appid: str) -> str | None:
        """Queries the Steam store API for a name.

        Callers are always background threads, never the Qt UI thread, so the
        throttle below never freezes the UI.  Store calls are serialized and
        spaced at least STORE_THROTTLE_SECONDS apart to avoid rate-limiting
        during large bulk imports; cached names never reach this method, so the
        delay only applies to real network calls.
        """
        with self._store_lock:
            wait = STORE_THROTTLE_SECONDS - (time.monotonic() - self._last_store_call)
            if wait > 0:
                if self._stop.wait(wait):
                    return None
            try:
                req = urllib.request.Request(
                    STORE_URL.format(appid=appid),
                    headers={"User-Agent": USER_AGENT},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    doc = json.loads(resp.read().decode("utf-8", errors="replace"))
                entry = doc.get(appid) if isinstance(doc, dict) else None
                if (isinstance(entry, dict) and entry.get("success")
                        and isinstance(entry.get("data"), dict)):
                    name = entry["data"].get("name")
                    if isinstance(name, str) and name:
                        return name
            except (urllib.error.URLError, OSError, ValueError, TimeoutError) as ex:
                Logger.warn(f"Name lookup failed for {appid}: {ex}")
            finally:
                self._last_store_call = time.monotonic()
        return None

    # ------------------------------------------------------- persistence

    def _load_cache(self) -> None:
        try:
            if not self._cache_file.is_file():
                return
            raw = self._cache_file.read_bytes()
            try:
                text = raw.decode("utf-8")
                recovered = False
            except UnicodeDecodeError:
                # Cache written in a legacy ANSI code page (old PowerShell
                # script versions did this); decode it so special characters
                # survive, then rewrite as clean UTF-8.
                text = raw.decode("cp1252", errors="replace")
                recovered = True

            data = json.loads(text)
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, str) and "�" not in value:
                        self._cache[str(key)] = value
            if recovered:
                self._save_cache()
        except (OSError, ValueError):
            pass

    def _save_cache(self) -> None:
        try:
            Settings.dir().mkdir(parents=True, exist_ok=True)
            with self._lock:
                payload = json.dumps(self._cache, indent=2, ensure_ascii=False)
            tmp = self._cache_file.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(self._cache_file)
        except OSError:
            pass

    def _load_verified(self) -> None:
        try:
            if not self._verified_file.is_file():
                return
            data = json.loads(self._verified_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key, value in data.items():
                    try:
                        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        self._verified_at[str(key)] = parsed
                    except ValueError:
                        continue
        except (OSError, ValueError):
            pass

    def _save_verified(self) -> None:
        try:
            Settings.dir().mkdir(parents=True, exist_ok=True)
            with self._lock:
                payload = json.dumps(
                    {k: v.isoformat() for k, v in self._verified_at.items()},
                    indent=2,
                )
            tmp = self._verified_file.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(self._verified_file)
        except OSError:
            pass
