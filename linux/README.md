# Steam Screenshot Backup for Linux

Steam stores screenshots in `userdata/<id>/760/remote/<appid>/screenshots` under
names like `20260706210532_1.jpg`, grouped by numeric app ID instead of game
name. The uncompressed "external copy" files (from Steam's *"Save an external
copy of my screenshots"* option) are similarly left ungrouped in a single
folder. This app watches both locations continuously and copies everything into
one folder tree, organized by real game name and readable timestamp:

```
Steam Screenshots/
├── Standard/
│   ├── Slay the Spire/
│   │   ├── 2026-04-12 13.37.15.jpg
│   │   └── 2026-04-12 15.06.32.jpg
│   └── Hollow Knight/
│       └── 2025-08-25 20.46.10.jpg
└── High Resolution/
    └── Slay the Spire/
        └── 2026-04-12 13.37.15.png
```

Built for **Bazzite**, and works on any Linux desktop with a system tray. It is
a port of the [Windows version](../) in the root of this repository, and
deliberately writes an identical layout — see
[Sharing a backup folder with Windows](#sharing-a-backup-folder-with-windows).

## Key features

- **Real game names**, resolved automatically, including delisted and non-Steam
  games (which you can also rename by hand).
- **Both screenshot types**: Steam's compressed "Standard" copies and the
  uncompressed "High Resolution" external copies.
- **Finds every Steam install.** Native, Flatpak and Snap are all detected, and
  all of them are watched — which matters on Bazzite, where a Flatpak Steam can
  sit alongside the built-in one.
- **Real-time backup.** Each screenshot is copied shortly after Steam finishes
  writing it, plus a catch-up scan at launch for anything taken while it was off.
- **Self-healing backup.** Delete a file from the backup and it's restored
  automatically, or review and restore just what you want with **Re-Sync**.
- **Searchable metadata.** The game name is embedded in each backup file as XMP
  and EXIF, so it shows up in Dolphin and GNOME Files search (and as
  Title/Tags if you ever open the folder on Windows).
- **Unresolved games are flagged, not silently ignored.** If a custom Steam
  shortcut or a delisted game can't be named automatically, the app tells you: a
  notification, a marker on the main window's **Game Names** button, and a log
  entry, plus a button in **Game Names** to open the actual screenshot folder so
  you can see what the game is and name it yourself.
- **Every Steam account** on the machine is covered, and Steam's own files are
  never modified unless you ask it to.

<details>
<summary><b>Additional features</b></summary>

- **Readable, sortable filenames**: `YYYY-MM-DD HH.MM.SS`, so sorting by name is
  sorting by capture time.
- **Custom folder layouts.** Choose between `Game`, `Game/Year`, `Year/Game` and
  more; existing backups can be reorganized in place, with a preview first.
- **Markdown index.** Optionally maintain a `_Screenshot_Log.md` in each folder
  that embeds every screenshot under per-day headers, ready to drop into
  Obsidian or any markdown vault.
- **Retroactive game-name tracking.** Every backup run retries name resolution
  for games that couldn't be identified the first time.
- **Utilities menu**, with one-click bulk cleanup and **Granular Deletion**, a
  checkbox tree covering both your backup files and Steam's own originals.
- **Preview before importing.** Optionally review what will happen before batch
  imports and layout reorganizations.
- **Optional Steam cleanup.** Turn on the (clearly marked, dangerous) *Delete
  originals after import* setting and each original is removed from Steam once
  it's safely backed up, recoverable from the trash.
- **Network-drive friendly.** If the destination becomes unreachable, the app
  waits and retries automatically, then catches up once it's back — and it can
  tell a mounted drive from an empty mount point, so an unmounted NAS never
  causes a second copy of everything to land on your system disk.
- **Offline mode.** Skip Steam's store lookups entirely.
- **Update checks.** Optionally checks this project's GitHub releases once a day.
  Only `linux-v*` tags are considered, so the Windows app's releases in the same
  repository never trigger a notification here. Off automatically in Offline mode.
- **Dark and light themes**, or follow the system setting.
- **Statistics**: total games, screenshots, and data, plus per-session counters.

</details>

## Installation

Nothing is installed outside your home directory: no `rpm-ostree` layering, no
root, no reboot. That means a Bazzite image update won't disturb it.

```bash
git clone https://github.com/Erdmann5150/Steam-Screenshot-Backup.git
cd Steam-Screenshot-Backup/linux
./install.sh
```

The installer asks whether to start the app on login and whether to launch it
now. Pass `--yes` to accept both, or `--no-autostart` / `--no-run` to decline.

On first launch, choose your backup folder and which screenshot types to back
up. That's the entire setup.

**Updating:** pull and re-run `./install.sh`. It installs over the existing copy
and keeps your settings, game-name list, and backed-up screenshots untouched.

**Uninstalling:** use **Uninstall** in the app's Settings, or run
`~/.local/share/steam-screenshot-backup/uninstall.sh`. Either removes the app,
its settings, cache and autostart entry; your backed-up screenshots are never
touched.

<details>
<summary><b>What gets installed where</b></summary>

| Path | What |
| --- | --- |
| `~/.local/share/steam-screenshot-backup/` | the app and its private virtualenv |
| `~/.local/bin/steam-screenshot-backup` | the launcher |
| `~/.local/share/applications/*.desktop` | app-menu entry |
| `~/.config/autostart/*.desktop` | start-on-login (optional) |
| `~/.config/steam-screenshot-backup/` | `settings.json`, `appnames.json` |
| `~/.local/state/steam-screenshot-backup/` | `app.log` and its archives |

The virtualenv is about 260 MB, almost entirely Qt. That is the price of a
self-contained install that doesn't depend on system packages and can't be
broken by an OS update.

</details>

### Requirements

- Python 3.10 or newer (Bazzite ships it)
- A system tray. KDE Plasma — Bazzite's desktop — works as-is. **On GNOME** you
  need the [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/),
  since GNOME has no tray of its own.

## Using the app

- **Click the tray icon** to toggle the main window: statistics, a live
  filterable activity feed, and every action as a button: **Backup Now**, **Open
  Backup Folder**, **Re-Sync**, **Pause Monitoring**, **Settings**, **Game
  Names**, **Utilities**. Double-click an entry to reveal the file in your file
  manager.
- **Right-click** the tray icon for the same actions in a quick menu, plus Start
  On Login, Uninstall, and Exit.
- **Re-Sync** reviews everything in Steam that's missing from your backup,
  grouped by game, so you can restore just what you pick.
- **Pause Monitoring** gets a red border while paused, so it's obvious at a
  glance that new screenshots aren't being backed up right now.
- **Settings** has two tabs: *General* (theme, notifications, startup, the
  Markdown index, offline mode, updates) and *Backup Configuration* (folder,
  screenshot types, layout, Steam location, and the danger zone). **Apply**
  saves without closing the window; **Close** just closes it.
- **Game Names** fixes delisted or non-Steam games by hand. Folders it couldn't
  name on its own are highlighted at the top; select one and click **Open
  Folder** to see the actual screenshots and figure out what the game is.
- **Utilities** has one-click bulk cleanup and **Granular Deletion**, a checkbox
  tree for picking exactly which files to remove, from either your backup or
  Steam's own screenshot folders.

### High-resolution screenshots

Steam saves uncompressed copies only when *"Save an external copy of my
screenshots"* is enabled (Steam Settings → In Game). The app reads Steam's
config to find that folder automatically, including retroactively importing
everything already in it. If it can't be auto-detected, set the folder yourself
in **Settings → High-resolution folder**. Screenshots taken before the option
was enabled exist only as compressed copies, which is exactly what the Standard
backup covers.

### Delisted games

Games removed from the Steam store can't be resolved via the API. Fix them in
the app under **Game Names**, or add entries to
`~/.config/steam-screenshot-backup/appnames.json` by hand:

```json
{ "1681430": "Some Delisted Game" }
```

## Sharing a backup folder with Windows

The backup layout, filename format and `appnames.json` schema are identical to
the Windows version, and filenames are sanitized with the stricter Windows
character rules even on Linux. So:

- Both machines can back up to the same NAS folder and will cooperate rather
  than produce two divergent trees.
- Each will skip what the other already copied, instead of duplicating it.
- `appnames.json` is portable — copy it across and your hand-fixed names come
  with it.
- `settings.json` from the Windows app loads here too, including its
  backslash folder templates.

## Resource usage and performance

Idle cost is near zero (inotify, not polling), copies preserve timestamps
without re-encoding, game names are cached and only re-checked against Steam's
store in small background batches once a day, logs are size-capped, and a
dropped network destination is retried quietly instead of erroring.

If you have an unusually large Steam library you may hit the kernel's inotify
watch limit, which shows up as a watcher error in the log. The catch-up scans
still work, and you can raise the limit:

```bash
echo 'fs.inotify.max_user_watches=524288' | sudo tee /etc/sysctl.d/99-inotify.conf
sudo sysctl --system
```

## What it does with your files

This app reads from and writes to your Steam screenshot folders, and can delete
from them if you turn that on. Specifics:

- Every backup, restore, deletion, warning and error is logged in the main
  window's activity feed and in `app.log` on disk, including when a game folder
  can't be named automatically.
- Steam's own files are never modified or removed unless you explicitly enable
  *Delete originals after import*, which is off by default. Even then, deletions
  go to the trash, not a permanent delete.
- Any deletion of backup files (turning a screenshot type off, the Utilities
  menu's bulk actions, or the Granular Deletion window) goes to the trash and
  shows the file count and total size before you confirm.
- If a file can't be moved to the trash — some network and removable drives have
  no trash folder — the app reports it and deletes nothing, rather than falling
  back to an unrecoverable delete. This holds for *Delete originals after
  import* too: with no working trash, Steam's originals are left alone.
- The only network calls are automatic, read-only Steam store lookups to resolve
  an app ID into a game name — made only when the name isn't already known
  locally, and periodically re-checked in the background — plus an optional
  once-a-day check against this project's GitHub releases. Only the app ID (for
  the Steam lookup) or nothing at all (for the update check) is sent, never
  screenshot data, filenames, or anything else. There's no telemetry and no
  account of any kind. Turn on **Offline mode** to skip both entirely.
- The source is all here, so anything about how it handles your files can be
  checked directly instead of taken on faith.

## Releases

This app shares a repository with the Windows version but versions
independently. Linux releases are tagged **`linux-v<version>`** (for example
`linux-v1.0.0`); the Windows app keeps its bare `v<version>` tags. The in-app
update check only looks at `linux-v*` tags, so neither stream notifies about
the other.

## Development

```bash
pip install -r requirements-dev.txt
python -m ssbackup            # run from a checkout
python -m pytest              # 166 tests, including a headless GUI pass
```

The test suite builds a synthetic Steam installation (two accounts, several
games, both screenshot types, a delisted game, a non-Steam shortcut, a second
library drive) and runs the real engine against it, including live inotify
watching. GUI tests construct and drive every window under Qt's offscreen
platform, so they run without a display.

```
ssbackup/core/     backup logic, no Qt dependency
ssbackup/ui/       PySide6 windows and the tray
tests/             unit, end-to-end, watcher and GUI tests
install.sh         one-command installer
```

## Differences from the Windows version

Same features, adapted where the platform demands it:

| Windows | Linux |
| --- | --- |
| Recycle Bin | freedesktop trash (`~/.local/share/Trash`) |
| Registry `Run` key | `~/.config/autostart/*.desktop` |
| Registry Steam path | probes native, Flatpak and Snap locations |
| `explorer /select` | `org.freedesktop.FileManager1` D-Bus, with fallbacks |
| Inno Setup installer | `install.sh` into `~/.local` |
| Drive-root reachability check | mount-aware check with a marker file |

There is no separate offline-only build; Offline mode is a setting. The
PowerShell script from the Windows repo is Windows-only and has no counterpart
here.

## Disclaimer

This project was generated with [Claude](https://claude.com) under human
direction and testing. Review the source before use if that matters to you —
it's all here.

## License

MIT, see [LICENSE](LICENSE).
