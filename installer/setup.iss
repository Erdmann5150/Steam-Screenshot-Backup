; Inno Setup script for Steam Screenshot Backup.
; Build with build.ps1 at the repository root (it publishes the exe first and
; passes the version in), or manually:
;   ISCC.exe setup.iss /DAppVersion=3.0.0 /DPublishDir=..\app\bin\Release\net8.0-windows\win-x64\publish

#ifndef AppVersion
  #define AppVersion "3.0.0"
#endif
#ifndef PublishDir
  #define PublishDir "..\app\bin\Release\net8.0-windows\win-x64\publish"
#endif

#define AppName "Steam Screenshot Backup"
#define AppExe "SteamScreenshotBackup.exe"

[Setup]
; Fixed GUID identifies the app across upgrades (Control Panel entry reuse).
AppId={{7E6B1F63-1B0A-4B62-9E1D-52A9C7C5B8D4}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Steam Screenshot Backup project
AppPublisherURL=https://github.com/Erdmann5150/Backup-SteamScreenshots
AppSupportURL=https://github.com/Erdmann5150/Backup-SteamScreenshots/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
OutputBaseFilename=SteamScreenshotBackup-Setup-{#AppVersion}
SetupIconFile=..\app\Assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
; Clean name in "Apps & features" / Control Panel (no "version x.x.x" suffix).
UninstallDisplayName={#AppName}
VersionInfoVersion={#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "startupwindows"; Description: "Start {#AppName} automatically when I sign in to Windows"
Name: "startmenuicon"; Description: "Create a Start Menu entry"
Name: "desktopicon"; Description: "Create a Desktop shortcut"; Flags: unchecked

[Files]
Source: "{#PublishDir}\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startmenuicon
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; "Start with Windows" — writes the same per-user Run value the app's own toggle uses,
; so the app's Settings checkbox stays in sync. Removed on uninstall.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SteamScreenshotBackup"; ValueData: """{app}\{#AppExe}"""; Tasks: startupwindows; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; Stop the running tray app so its exe can be removed.
Filename: "{cmd}"; Parameters: "/c taskkill /im {#AppExe} /f"; Flags: runhidden; RunOnceId: "KillApp"
; Remove the per-user autostart entry the app may have written.
Filename: "reg.exe"; Parameters: "delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v SteamScreenshotBackup /f"; Flags: runhidden; RunOnceId: "RemoveAutostart"

[UninstallDelete]
; Settings, name cache and logs (per-user, best effort). Backups are never touched.
Type: filesandordirs; Name: "{localappdata}\SteamScreenshotBackup"

[Code]
// Stop a running instance before installing over it.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  R: Integer;
begin
  Exec(ExpandConstant('{cmd}'), '/c taskkill /im {#AppExe} /f', '', SW_HIDE, ewWaitUntilTerminated, R);
  Result := '';
end;
