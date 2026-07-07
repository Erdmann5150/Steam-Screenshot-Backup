# Steam Screenshot Backup

Automatically consolidates every Steam screenshot into one folder â€” organized by
**real game name** instead of appid, with filenames you can actually read.

Steam buries screenshots in `userdata\<id>\760\remote\<appid>\screenshots` under
names like `20260706210532_1.jpg`. This project turns that into:

```
Steam Screenshots/
â”œâ”€â”€ Slay the Spire/
â”‚   â”œâ”€â”€ 2026-04-12 13.37.15.jpg
â”‚   â””â”€â”€ 2026-04-12 15.06.32.jpg
â”œâ”€â”€ Yakuza Kiwami/
â”‚   â””â”€â”€ 2025-08-25 20.46.10.jpg
â””â”€â”€ ...
```

Two ways to use it:

| | Best for |
|---|---|
| **Tray app** (recommended) | Set-and-forget. Watches Steam in real time and backs up each screenshot the moment you take it. |
| **PowerShell script** | Scripters. One-shot or scheduled runs via Task Scheduler, no resident process. |

Both produce identical output and share the same game-name cache â€” switch between
them freely.

## Tray app

1. Download `SteamScreenshotBackup.exe` from the [latest release](../../releases/latest).
2. Run it. Pick a backup folder and (optionally) enable start-with-Windows. That's
   the entire setup.

From then on:

- Every screenshot you take is copied within about a second of Steam saving it
- A catch-up scan runs at each launch, so nothing taken while the app was closed
  is missed
- Right-click the tray icon for **Back up now**, **Open backup folder**,
  **Pause watching**, **Start with Windows**, **Change backup folder**, **Exit**
- The tray tooltip shows the most recent backup

> **Windows SmartScreen:** the exe is unsigned, so the first run may show
> *"Windows protected your PC."* Click **More info â†’ Run anyway** â€” or build from
> source (below) if you'd rather not trust a downloaded binary.

## PowerShell script

Zero dependencies â€” Windows PowerShell 5.1+, which ships with Windows 10/11:

```powershell
powershell -ExecutionPolicy Bypass -File .\Backup-SteamScreenshots.ps1 -Destination "D:\Backups\Steam Screenshots"
```

Omit `-Destination` to use `%USERPROFILE%\Pictures\Steam Screenshots`. Runs are
incremental (already-backed-up files are skipped), so scheduling it is safe:

```
schtasks /create /tn "SteamScreenshotBackup" /tr "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\path\to\Backup-SteamScreenshots.ps1" /sc daily /st 03:00
```

## What you get

- **Real game names** â€” resolved instantly from local Steam app manifests for
  installed games (across every library drive), with the Steam store API as a
  fallback for uninstalled ones. Results are cached in
  `%LOCALAPPDATA%\SteamScreenshotBackup\appnames.json`, so each game is only ever
  looked up once â€” shared across both tools.
- **Readable, sortable filenames** â€” `YYYY-MM-DD HH.MM.SS`, so sorting by name
  equals sorting by capture time. If Steam records multiple shots in the same
  second, extras get ` (2)`, ` (3)`, and so on.
- **Every Steam account** on the machine is covered.
- **Non-destructive** â€” Steam's own screenshot store is never touched, and file
  timestamps are preserved on copy.
- Point the destination at a synced folder (Syncthing, cloud drive, NAS) and you
  get off-machine backups for free.

## Delisted games

Games removed from the Steam store can't be resolved via the API and fall back to
an `AppID_<number>` folder. Fix them manually by adding entries to the cache file:

```json
{ "1681430": "Some Delisted Game" }
```

The next screenshot or scan picks the name up.

## Building the app from source

Requires the .NET 8 SDK (`winget install Microsoft.DotNet.SDK.8`):

```
cd app
dotnet publish -c Release -r win-x64 --self-contained -p:PublishSingleFile=true
```

The exe lands in `app\bin\Release\net8.0-windows\win-x64\publish\`. For a quick
test build, `dotnet run` inside `app\` works too.

## Limitations

- Backs up Steam's managed (compressed) screenshots. If you've enabled *"Save an
  uncompressed copy"* in Steam's settings, those already live in a single folder
  of your choosing and don't need this tool.
- Windows only.

## Repository layout

```
Backup-SteamScreenshots.ps1   PowerShell version
app/                          Tray app (C# / .NET 8 WinForms)
```

## License

MIT â€” see [LICENSE](LICENSE).
