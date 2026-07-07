# Steam Screenshot Backup

A zero-dependency PowerShell script that consolidates all of your Steam screenshots
into one folder — organized by **real game name** instead of appid, with filenames
you can actually read.

Steam buries screenshots in `userdata\<id>\760\remote\<appid>\screenshots` with names
like `20260706210532_1.jpg`. This script turns that into:

```
Steam Screenshots/
├── Slay the Spire/
│   ├── 2026-04-12 13.37.15 - 1.jpg
│   └── 2026-04-12 15.06.32 - 1.jpg
├── Yakuza Kiwami/
│   └── 2025-08-25 20.46.10 - 1.jpg
└── ...
```

## Features

- **Real game names** — resolved from local Steam app manifests for installed games,
  with the Steam store API as a fallback for uninstalled ones (cached locally, so
  each game is only ever looked up once)
- **Readable, sortable filenames** — `YYYY-MM-DD HH.MM.SS - N`, so sorting by name
  is identical to sorting by capture time
- **Incremental** — already-backed-up files are skipped; safe to run on a schedule
- **Complete coverage** — scans every Steam account on the machine and every
  library folder on every drive
- **Non-destructive** — Steam's own screenshot store is never modified
- **No dependencies** — plain Windows PowerShell 5.1, ships with Windows 10/11

## Quick start

```powershell
git clone https://github.com/<you>/steam-screenshot-backup.git
cd steam-screenshot-backup
powershell -ExecutionPolicy Bypass -File .\Backup-SteamScreenshots.ps1 -Destination "D:\Backups\Steam Screenshots"
```

Omit `-Destination` to back up to `%USERPROFILE%\Pictures\Steam Screenshots`.

## Run automatically

Create a daily Task Scheduler job (adjust paths):

```
schtasks /create /tn "SteamScreenshotBackup" /tr "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\path\to\Backup-SteamScreenshots.ps1 -Destination \"D:\Backups\Steam Screenshots\"" /sc daily /st 03:00
```

Pointing the destination at a synced folder (Syncthing, cloud drive, NAS) gets you
off-machine backups for free.

## How it works

1. Finds your Steam install via the registry, then parses `libraryfolders.vdf`
   to discover every library drive.
2. Builds an appid → name map from `appmanifest_*.acf` files (instant, offline).
3. For screenshots belonging to games you've uninstalled, queries the Steam store
   API once per appid and caches the result in
   `%LOCALAPPDATA%\SteamScreenshotBackup\appnames.json`. Steady-state runs make
   zero network calls.
4. Copies each screenshot to `<Destination>\<Game Name>\`, converting the raw
   `YYYYMMDDHHMMSS_N` filename to `YYYY-MM-DD HH.MM.SS - N`. `N` is Steam's own
   counter for multiple captures within the same second. File timestamps are
   preserved, so Explorer's Date Modified column stays accurate.

## Delisted games

Games removed from the Steam store can't be resolved via the API and fall back to
an `AppID_<number>` folder. Fix them manually by adding entries to the cache file:

```json
{ "1681430": "Some Delisted Game" }
```

The next run picks the name up and uses it.

## Limitations

- Backs up Steam's managed (compressed) screenshots. If you've enabled
  *"Save an uncompressed copy"* in Steam's settings, those files already live in a
  single folder of your choosing and don't need this script.
- Windows only (registry lookup + Windows path conventions).

## License

MIT — see [LICENSE](LICENSE).
