; Inno Setup script for Steam Screenshot Backup.
; Build with build.ps1 at the repository root (it publishes the exe first and
; passes the version in), or manually:
;   ISCC.exe setup.iss /DAppVersion=3.5.0 /DPublishDir=..\app\bin\Release\net8.0-windows\win-x64\publish

#ifndef AppVersion
  #define AppVersion "3.5.0"
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
AppPublisher=Erdmann5150
AppPublisherURL=https://github.com/Erdmann5150/Steam-Screenshot-Backup
AppSupportURL=https://github.com/Erdmann5150/Steam-Screenshot-Backup/issues
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

[Messages]
; Drop the redundant instruction line on the tasks page for a cleaner flow.
SelectTasksLabel2=

[Tasks]
Name: "startupwindows"; Description: "Start {#AppName} automatically when I sign in to Windows"
Name: "startmenuicon"; Description: "Create a Start Menu entry"
Name: "desktopicon"; Description: "Create a Desktop shortcut"; Flags: unchecked
Name: "nonotifications"; Description: "Turn off popup notifications"; Flags: unchecked
Name: "previewimport"; Description: "Preview a list of changes before importing batches of screenshots"; Flags: unchecked
Name: "deleteoriginals"; Description: "Delete original Steam screenshots after import (dangerous, sends them to the Recycle Bin)"; Flags: unchecked

[Files]
Source: "{#PublishDir}\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startmenuicon
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; "Start with Windows" — writes the same per-user Run value the app's own toggle uses,
; so the app's Settings checkbox stays in sync. Removed on uninstall.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SteamScreenshotBackup"; ValueData: """{app}\{#AppExe}"""; Tasks: startupwindows; Flags: uninsdeletevalue
; The app reads these markers on first run to pre-apply the matching settings.
Root: HKCU; Subkey: "Software\SteamScreenshotBackup"; ValueType: dword; ValueName: "DeleteOriginalsDefault"; ValueData: 1; Tasks: deleteoriginals; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\SteamScreenshotBackup"; ValueType: dword; ValueName: "NotificationsOffDefault"; ValueData: 1; Tasks: nonotifications; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\SteamScreenshotBackup"; ValueType: dword; ValueName: "PreviewImportsDefault"; ValueData: 1; Tasks: previewimport; Flags: uninsdeletevalue uninsdeletekeyifempty

[Run]
; --show opens the main window after install instead of only landing in the tray.
Filename: "{app}\{#AppExe}"; Parameters: "--show"; Description: "Launch {#AppName}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; Stop the running tray app so its exe can be removed.
Filename: "{cmd}"; Parameters: "/c taskkill /im {#AppExe} /f"; Flags: runhidden; RunOnceId: "KillApp"
; Remove the per-user autostart entry the app may have written.
Filename: "reg.exe"; Parameters: "delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v SteamScreenshotBackup /f"; Flags: runhidden; RunOnceId: "RemoveAutostart"

[UninstallDelete]
; Settings, name cache and logs (per-user, best effort). Backups are never touched.
Type: filesandordirs; Name: "{localappdata}\SteamScreenshotBackup"

[Code]
// ----- best-effort dark theme for the wizard (matches the app) -----
function DwmSetWindowAttribute(hwnd: HWND; attr: Integer; var value: Integer; size: Integer): Integer;
  external 'DwmSetWindowAttribute@dwmapi.dll stdcall';

const
  clDarkBg    = $00251D16;   // TColor (BGR) of RGB(22,29,37)
  clDarkPanel = $00342920;   // RGB(32,41,52)
  clLightText = $00EBE2D6;   // RGB(214,226,235)

procedure ApplyDarkTo(C: TControl);
var
  i: Integer;
begin
  if C is TNewCheckListBox then begin
    TNewCheckListBox(C).Color := clDarkBg;
    TNewCheckListBox(C).Font.Color := clLightText;
  end
  else if C is TNewStaticText then TNewStaticText(C).Font.Color := clLightText
  else if C is TNewCheckBox then TNewCheckBox(C).Font.Color := clLightText
  else if C is TNewRadioButton then TNewRadioButton(C).Font.Color := clLightText
  else if C is TNewEdit then begin
    TNewEdit(C).Color := clDarkPanel; TNewEdit(C).Font.Color := clLightText;
  end
  else if C is TNewMemo then begin
    TNewMemo(C).Color := clDarkPanel; TNewMemo(C).Font.Color := clLightText;
  end
  else if C is TNewNotebookPage then TNewNotebookPage(C).Color := clDarkBg
  else if C is TPanel then TPanel(C).Color := clDarkBg;

  if C is TWinControl then
    for i := 0 to TWinControl(C).ControlCount - 1 do
      ApplyDarkTo(TWinControl(C).Controls[i]);
end;

procedure ApplyDarkMode;
var
  v: Integer;
begin
  WizardForm.Color := clDarkBg;
  WizardForm.MainPanel.Color := clDarkBg;
  ApplyDarkTo(WizardForm);
  v := 1;
  DwmSetWindowAttribute(WizardForm.Handle, 20, v, SizeOf(v));   // dark title bar
end;

procedure InitializeWizard;
begin
  ApplyDarkMode;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  ApplyDarkMode;   // re-theme controls created per page
end;

// Stop a running instance before installing over it.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  R: Integer;
begin
  Exec(ExpandConstant('{cmd}'), '/c taskkill /im {#AppExe} /f', '', SW_HIDE, ewWaitUntilTerminated, R);
  Result := '';
end;

// Extra explicit confirmation when the dangerous "delete originals" task is selected.
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectTasks then
    if WizardIsTaskSelected('deleteoriginals') then
      if MsgBox('DANGER: "Delete original Steam screenshots after import" is selected.'#13#10#13#10 +
                'This removes your original screenshots from Steam after they are backed up ' +
                '(they go to the Recycle Bin, but Steam will no longer show them).'#13#10#13#10 +
                'Are you sure you want to enable this?', mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
end;
