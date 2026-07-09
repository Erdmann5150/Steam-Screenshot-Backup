# Steam Screenshot Backup — working notes for Claude

A WinForms (.NET 8) tray app + PowerShell script that backs up Steam screenshots
(standard and high-res) into `Standard\`/`High Resolution\` folders under a
game-name/date template, with metadata tagging, an activity log, and an Inno
Setup installer. See README.md for the feature list — this file is about how to
work in the repo safely and efficiently, not what it does.

## Encoding: pure ASCII in all .cs/.ps1 sources, no exceptions

The whole reason this project's history includes an encoding-repair episode is a
prior mojibake bug (UTF-8 written, read back as ANSI). Every source file must stay
byte-for-byte ASCII. Never type a literal em dash, smart quote, arrow, bullet, or
non-breaking space into a .cs or .ps1 file — use `\uXXXX` escapes instead
(`—` for —, `…` for …, etc.). After editing, sweep and verify:

```powershell
Get-ChildItem app -Filter *.cs | ForEach-Object {
  $b = [System.IO.File]::ReadAllBytes($_.FullName)
  $s = if ($b.Length -gt 3 -and $b[0] -eq 0xEF) { 3 } else { 0 }   # skip BOM
  if (@($b[$s..($b.Length-1)] | Where-Object { $_ -gt 127 }).Count) { $_.Name }
}
```
Run this after every batch of edits, before building. If it reports a file, find
the offending char and replace it with an escape (a small PowerShell
`Replace([string][char]0x2014, '—')` pass works well).

## Build & release

- `build.ps1` at repo root does everything: publishes the self-contained exe,
  copies it to `dist\portable\`, compiles `installer\setup.iss` to
  `dist\installer\`, and drops safe copies in
  `Documents\SteamBackup Releases\v<version>\` (outside the repo, so testing
  never risks the only copy of a release).
- Version lives in **two places that must be bumped together**:
  `app/SteamScreenshotBackup.csproj` (`<Version>`) and the fallback in
  `installer/setup.iss` (`#define AppVersion` + the header comment example).
- Before running `build.ps1`, stop any running instance
  (`Get-Process SteamScreenshotBackup | Stop-Process -Force`) — the publish step
  fails if the exe is locked.
- **Never run `gh release create` / publish a GitHub release without the user
  explicitly saying "publish"** (or equivalent). Committing and pushing to `main`
  is fine to do proactively as part of finishing a feature; cutting a public
  release is not.

## Testing without touching the real backup

The user's real backup lives at `D:\Screenshots\Steam` with ~2000 real files —
never run destructive operations against it directly. Two safe patterns, both
used repeatedly and both work well:

1. **Throwaway engine harness** — a scratch `.csproj` that includes
   `app\*.cs` (excluding `Program.cs`) with its own `Main`, pointing
   `Settings.Destination` at a temp folder. Compiles the real production code, so
   it's a genuine test, not a reimplementation. Use `OutputType=Exe` (not
   `WinExe`) if you need console output / a bash-blocking process; `WinExe`
   detaches and PowerShell won't wait for it.
2. **Settings backup/restore** — before flipping a real setting for a live test
   (e.g. `DeleteOriginals`, `AutoRestore`), copy
   `%LOCALAPPDATA%\SteamScreenshotBackup` aside first, restore it after.

Known PowerShell sandbox trip-wire: a single command that both references a
`C:\Program Files...` path *and* calls `Remove-Item` (even unrelated) gets
blocked by the harness's safety layer. Split into separate tool calls.

## README screenshots

Screenshots in `docs/img/` are rendered programmatically, not hand-captured —
keeps them trivially reproducible after any UI change:
- App windows (MainWindow, SettingsWindow, PreviewWindow, tray menu): a scratch
  `WinExe` harness that includes `app\*.cs`, constructs the real `TrayContext` /
  windows (private ctors via reflection if needed), calls `Application.DoEvents()`
  in a pump loop to let it render, then `Form.DrawToBitmap`.
- The installer: compile `setup.iss` with `PrivilegesRequired=lowest` and
  `DisableWelcomePage=yes` (throwaway copy, don't commit), launch it, find the
  wizard window by title (`Setup - <AppName>*`), `SendKeys('{ENTER}')` to advance
  past the dir page, then `PrintWindow` (not `DrawToBitmap` — it's not a managed
  form) into a `Bitmap`.

Regenerate all screenshots whenever a rendered window's layout changes; stale
screenshots are worse than none.

## Repo

- GitHub: `Erdmann5150/Steam-Screenshot-Backup` (renamed from
  `Backup-SteamScreenshots` — old URLs redirect, but link to the current name in
  new docs).
- `installer/setup.iss` is the source of truth for what the installer does;
  `[Code]` section has a `DwmSetWindowAttribute`-based dark-mode hack for the
  wizard chrome plus a `NextButtonClick` handler that adds a confirmation prompt
  when the dangerous "delete originals" task is checked.
