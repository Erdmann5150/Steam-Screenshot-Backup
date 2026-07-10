# Steam Screenshot Backup

Steam stores screenshots in `userdata\<id>\760\remote\<appid>\screenshots` under
names like `20260706210532_1.jpg`, grouped by numeric app ID instead of game
name. The uncompressed "external copy" files (from Steam's *"Save an external
copy of my screenshots"* option) are similarly left ungrouped in a single
folder. This app watches both locations continuously and copies everything
into one folder tree, organized by real game name and readable timestamp:

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

## Screenshots

![The main window: backup statistics and a live, filterable activity feed](docs/img/main-window.png)

*The main window: total games and screenshots backed up, per-session counters, and a live activity feed you can filter by backups, restores, deletions, warnings, or info.*

![The Utilities menu's targeted deletion window: a checkbox tree by backup type, game, and file](docs/img/targeted-delete.png)

*Utilities → Granular Deletion. Pick exactly which files to remove, from the backup or from Steam's own screenshot folders.*

<details>
<summary>More screenshots (Settings, Game Names, tray menu, installer, preview)</summary>

<p align="center">
  <img src="docs/img/settings-general.png" alt="Settings window, General tab" width="49%">
  <img src="docs/img/settings-backup.png" alt="Settings window, Backup Configuration tab" width="49%">
</p>

*Settings: General (left) and Backup Configuration (right). Apply saves without closing the window; Close just closes it.*

<p align="center">
  <img src="docs/img/tray-menu.png" alt="Right-click tray menu" width="34%">
  <img src="docs/img/game-names.png" alt="Game Names window" width="49%">
</p>

*Left: the right-click tray menu. Right: Game Names, for fixing delisted or non-Steam games by hand. Unresolved folders are highlighted automatically.*

![The installer's task selection page](docs/img/installer.png)

*The installer (dark to match the app). Pick startup, shortcut, and import options during setup.*

![The preview window listing original and proposed backup paths](docs/img/preview.png)

*Optional preview before a batch import or reorganization, so you can see exactly what will happen before choosing Import or Cancel.*

</details>

## Key features

- **Real game names**, resolved automatically, including delisted and
  non-Steam games (which you can also rename by hand).
- **Both screenshot types**: Steam's compressed "Standard" copies and the
  uncompressed "High Resolution" external copies, both fully supported.
- **Real-time backup.** Each screenshot is copied shortly after Steam finishes
  writing it, plus a catch-up scan at launch for anything taken while it was off.
- **Self-healing backup.** Delete a file from the backup and it's restored
  automatically, or review and restore just what you want with **Re-Sync**.
- **Searchable metadata.** The game name is embedded in each backup file, so
  it shows up as searchable **Title**/**Tags** metadata in Explorer.
- **Unresolved games are flagged, not silently ignored.** If a custom Steam
  shortcut or a delisted game can't be named automatically, the app tells you:
  a tray notification, a marker on the main window's **Game Names** button,
  and a log entry, plus a button in **Game Names** to open the actual
  screenshot folder so you can see what the game is and name it yourself.
- **Every Steam account** on the machine is covered, and Steam's own files are
  never modified unless you ask it to.

<details>
<summary>Additional features</summary>

- **Readable, sortable filenames**: `YYYY-MM-DD HH.MM.SS`, so sorting by name is
  sorting by capture time.
- **Custom folder layouts.** Choose between `Game`, `Game\Year`, `Year\Game`
  and more; existing backups can be reorganized in place.
- **Markdown index.** Optionally maintain a `_Screenshot_Log.md` in each folder
  that embeds every screenshot under per-day headers, ready to drop into Obsidian
  or any markdown vault.
- **Retroactive game-name tracking.** Every backup run retries name resolution
  for games that couldn't be identified the first time.
- **Utilities menu**, with one-click bulk cleanup and **Granular Deletion**, a
  checkbox tree covering both your backup files and Steam's own original
  screenshots.
- **Preview before importing.** Optionally review what will happen before
  batch imports and layout reorganizations.
- **Optional Steam cleanup.** Turn on the (clearly marked, dangerous) *Delete
  originals after import* setting and each original is removed from Steam once
  it's safely backed up, recoverable from the Recycle Bin.
- **Network-drive friendly.** If the destination becomes unreachable, the app
  waits and retries automatically, then catches up once it's back.
- **Offline mode.** Skip Steam's store lookups entirely (a Settings toggle or
  an installer checkbox), or download the dedicated offline-only portable
  build with that code removed completely.
- **Update checks.** Optionally checks this project's GitHub releases once a
  day and lets you know if a newer version is out (a Settings toggle or an
  installer checkbox to turn it off), plus a manual **Check for Updates Now**
  button in the tray menu and Utilities. Off automatically in Offline mode,
  and not present at all in the offline-only portable build.
- **Dark and light themes**, or follow the Windows setting.
- **Statistics**: total games, screenshots, and data, plus per-session counters.

</details>

## Installation

### Installer (recommended)

1. Download `SteamScreenshotBackup-Setup-<version>.exe` from the
   [latest release](../../releases/latest).
2. Run it. Pick an install folder (defaults to Program Files) and choose whether
   to start with Windows, add Start Menu / Desktop shortcuts, turn off popup
   notifications, enable offline mode, turn off automatic update checks,
   preview batches before importing, and (optionally, and flagged as
   dangerous) delete originals after import. The main window opens
   automatically when setup finishes.
3. On first launch, choose your backup folder and which screenshot types to back
   up. That's the entire setup.

**Updating to a new version?** Just download the latest installer and run it,
no need to uninstall first. It installs directly over your existing copy in
place and keeps your settings, game-name cache, and backed-up screenshots
untouched.

Uninstall any time from **Windows Settings → Apps** (or Control Panel →
Programs). The uninstaller removes the app, its settings, cache, and autostart
entry; your backed-up screenshots are never touched. The same uninstaller is
reachable from the app's Settings window.

### Portable

Prefer zero-install? Download `SteamScreenshotBackup.exe` (portable) from the
release, put it anywhere, and run it. Identical functionality; the in-app
Uninstall option cleans up after itself.

A separate **offline-only** portable build, `SteamScreenshotBackup-Offline.exe`,
is also available on the same release - identical, but with the Steam
store name-lookup code removed entirely, for anyone who wants that guarantee
at the binary level rather than a runtime setting.

> **Windows SmartScreen:** the exe is unsigned, so the first run may show
> *"Windows protected your PC."* Click **More info → Run anyway**, or build from
> source (below) if you'd rather not trust a downloaded binary.

## Using the app

- **Left-click** the tray icon to toggle the main window: statistics, a live
  filterable activity feed, and every action as a button: **Backup Now**,
  **Open Backup Folder**, **Re-Sync**, **Pause Monitoring**, **Settings**,
  **Game Names**, **Utilities**. Double-click an entry to reveal the file in
  Explorer.
- **Right-click** the tray icon for the same actions in a quick menu, plus
  Start with Windows, Uninstall, and Exit.
- **Re-Sync** reviews everything in Steam that's missing from your backup,
  grouped by game, so you can restore just what you pick.
- **Settings** has two tabs: *General* (theme, notifications, startup, the
  Markdown index, offline mode) and *Backup Configuration* (folder, screenshot
  types, layout, and the danger zone). **Apply** saves in the background
  without closing the window, so you can keep adjusting settings; **Close**
  just closes it.
- **Game Names** fixes delisted or non-Steam games by hand, or opens the
  tracking file directly. Folders it couldn't name on its own are highlighted
  at the top of the list; select one and click **Open Folder** to see the
  actual screenshots and figure out what the game is.
- **Utilities** has one-click bulk cleanup and **Granular Deletion**, a
  checkbox tree for picking exactly which files to remove, from either your
  backup or Steam's own screenshot folders.

### High-resolution screenshots

Steam saves uncompressed copies only when *"Save an external copy of my
screenshots"* is enabled (Steam Settings → In Game). The app reads Steam's
config to find that folder automatically, including retroactively importing
everything already in it. If it can't be auto-detected, set the folder yourself
in **Settings → High-resolution folder**. Screenshots taken before the option
was enabled exist only as compressed copies, which is exactly what the Standard
backup covers.

## PowerShell script

The `Backup-SteamScreenshots.ps1` script produces the same backup layout and
shares the same game-name cache as the app, so use either, or both. Zero
dependencies beyond Windows PowerShell 5.1 (ships with Windows 10/11):

```powershell
.\Backup-SteamScreenshots.ps1 -Destination "D:\Backups\Steam Screenshots" -Types Both
```

| Parameter | Values | Default |
|---|---|---|
| `-Destination` | any folder | `%USERPROFILE%\Pictures\Steam Screenshots` |
| `-Types` | `Standard`, `HighRes`, `Both` | `Both` |
| `-FolderTemplate` | `{game}`, `{yyyy}\{game}`, … | `{game}` |
| `-HighResPath` | manual external-copy folder (if not auto-detected) | *(auto only)* |

Runs are incremental, so scheduling is safe:

```
schtasks /create /tn "SteamScreenshotBackup" /tr "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\path\to\Backup-SteamScreenshots.ps1" /sc daily /st 03:00
```

Note: metadata tagging is a tray-app feature; the script copies files verbatim.
The two tools recognize each other's copies either way.

## Delisted games

Games removed from the Steam store can't be resolved via the API. Fix them in
the app under **Game Names**, or add entries to
`%LOCALAPPDATA%\SteamScreenshotBackup\appnames.json` by hand:

```json
{ "1681430": "Some Delisted Game" }
```

## Resource usage and performance

Idle cost is near zero (native file-system watching, not polling), copies
preserve timestamps without re-encoding, game names are cached and only
re-checked against Steam's store in small background batches once a day,
logs are size-capped, and a dropped network destination is retried quietly
instead of erroring.

## Building from source

Requires the .NET 8 SDK (`winget install Microsoft.DotNet.SDK.8`); the installer
additionally needs Inno Setup 6 (`winget install JRSoftware.InnoSetup`):

```powershell
.\build.ps1     # produces dist\portable, dist\portable-offline, and dist\installer
```

For a quick development run: `dotnet run` inside `app\`.

## Repository layout

```
Backup-SteamScreenshots.ps1   Script version (same layout, same cache)
app/                          Tray app (C# / .NET 8 WinForms)
installer/setup.iss           Inno Setup installer script
build.ps1                     One-command release build
```

## Limitations

- Windows only.
- High-resolution backups require Steam's *"Save an external copy"* option to be
  enabled; Steam does not create uncompressed copies retroactively.

## What it does with your files

This app reads from and writes to your Steam screenshot folders, and can
delete from them if you turn that on. Specifics:

- Every backup, restore, deletion, warning, and error is logged in the main
  window's activity feed and in `app.log` on disk, including when a game
  folder can't be named automatically and needs your attention.
- Steam's own files are never modified or removed unless you explicitly enable
  *Delete originals after import*, which is off by default. Even then,
  deletions go to the Windows Recycle Bin, not a permanent delete.
- Any deletion of backup files (turning a screenshot type off, the Utilities
  menu's bulk actions, or the Granular Deletion window) goes to the Recycle
  Bin and shows the file count and total size before you confirm.
- The only network calls are automatic, read-only Steam store lookups to
  resolve an app ID into a game name - made only when the name isn't already
  known locally (installed-game manifests, the existing cache), and
  periodically re-checked in the background for names already resolved this
  way - plus an optional once-a-day check against this project's GitHub
  releases to let you know about a newer version. Only the app ID (for the
  Steam lookup) or nothing at all (for the update check) is sent, never
  screenshot data, filenames, or anything else; there's no telemetry and no
  account of any kind. Turn on **Offline mode** (Settings → General, or an
  installer checkbox) to skip both entirely - unresolved games just get an
  `AppID_<id>` folder name instead, and update checks stop - or download the
  dedicated offline-only portable build with that code removed completely.
  The update check alone can also be turned off on its own (Settings →
  General, or an installer checkbox) without affecting Steam name lookups.
- The source is all here, so anything about how it handles your files can be
  checked directly instead of taken on faith.

## FAQ

**Windows says this is unsafe / SmartScreen blocked it.** That's SmartScreen
flagging an unsigned binary, not a specific finding about this app - it does
that for any new, unsigned exe. Click **More info -> Run anyway** if you're
comfortable, or build from source (above) if you'd rather not.

**Why is the exe unsigned?** Cost - an EV code-signing certificate is a real
recurring expense for a free hobby project. The source is public if you want
to verify or build it yourself instead of trusting the download.

**Is it actually safe? Antivirus/VirusTotal?** All three v3.10.0 downloads
scan clean on VirusTotal:
[installer](https://www.virustotal.com/gui/file/513c32bf085fd04a383514998cd8c4c7ba013b74266c04bcb805cb43c57823d4/summary)
(0/67),
[portable](https://www.virustotal.com/gui/file/d399f4d867fac2966f7a59e679e642f4706ee912dddbe9ff0bfef756e14fe83a/summary)
(0/65), and
[offline portable](https://www.virustotal.com/gui/file/6d013052d5832f286d4a30381c50cb317a8bace61f4651958d613d50d5600460/summary)
(0/67).

**Does this upload my screenshots anywhere? Does it phone home?** No screenshot
data, ever - see [What it does with your files](#what-it-does-with-your-files).
The app does automatically make two kinds of read-only network calls: Steam
store lookups to resolve an app ID into a game name (only when it can't be
found locally, plus a periodic background re-check of names resolved this
way - only the numeric app ID is sent, nothing else), and an optional
once-a-day check against this project's GitHub releases for a newer version
(no data sent at all). Turn on **Offline mode** in Settings (or during
install) to disable both entirely, turn off just the update check on its own
(also in Settings, or during install), or use the offline-only portable
build, which has all of it removed at compile time. No telemetry, no account,
no analytics of any kind.

**Can it delete my screenshots?** Only if you turn on *Delete originals after
import*, which is off by default and marked as dangerous. Even then, deletions
go to the Recycle Bin, not a permanent delete.

**Will this work on Steam Deck / Linux / macOS?** No - it's a Windows-only
WinForms app for now, with no firm plans to change that.

**Checksums for the downloads?** Published in each
[release's](../../releases) notes.

## Disclaimer

This project was generated with [Claude Code](https://claude.com/claude-code)
(Anthropic's AI coding tool) under human direction and testing. Review the source
before use if that matters to you, it's all here.

## License

MIT, see [LICENSE](LICENSE).
