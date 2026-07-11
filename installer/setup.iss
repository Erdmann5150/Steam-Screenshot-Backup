; Inno Setup script for Steam Screenshot Backup.
; Build with build.ps1 at the repository root (it publishes the exe first and
; passes the version in), or manually:
;   ISCC.exe setup.iss /DAppVersion=3.11.7 /DPublishDir=..\app\bin\Release\net8.0-windows\win-x64\publish

#ifndef AppVersion
  #define AppVersion "3.11.7"
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
; Inno's own default AppVerName ("{#AppName} version {#AppVersion}") puts a
; lowercase "version" mid-title; set it explicitly for a clean Title Case
; wizard caption ("Setup - Steam Screenshot Backup 3.7.0").
AppVerName={#AppName} {#AppVersion}
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
; "modern" wizard style defaults DisableWelcomePage to yes, silently
; skipping the standard Welcome page. Force it back on.
DisableWelcomePage=no

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
Name: "offlinemode"; Description: "Offline mode: never contact Steam's servers for game names"; Flags: unchecked
Name: "noupdatecheck"; Description: "Turn off automatic update checks"; Flags: unchecked

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
Root: HKCU; Subkey: "Software\SteamScreenshotBackup"; ValueType: dword; ValueName: "OfflineModeDefault"; ValueData: 1; Tasks: offlinemode; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\SteamScreenshotBackup"; ValueType: dword; ValueName: "UpdateCheckOffDefault"; ValueData: 1; Tasks: noupdatecheck; Flags: uninsdeletevalue uninsdeletekeyifempty

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
// ----- theme for the wizard (matches the app's dark palette) -----
function DwmSetWindowAttribute(hwnd: HWND; attr: Integer; var value: Integer; size: Integer): Integer;
  external 'DwmSetWindowAttribute@dwmapi.dll stdcall';

const
  // TColor (BGR) values, same palette as the app's Theme.cs.
  clDarkBg    = $00251D16;   // RGB(22,29,37)
  clDarkPanel = $00342920;   // RGB(32,41,52)
  clDarkText  = $00EBE2D6;   // RGB(214,226,235)
  clLiteBg    = $00FAF7F4;   // RGB(244,247,250)
  clLitePanel = $00FFFFFF;   // RGB(255,255,255)
  clLiteText  = $0032261A;   // RGB(26,38,50)

var
  IsDarkTheme: Boolean;
  TaskIndexOfflineMode, TaskIndexNoUpdateCheck: Integer;

procedure ApplyThemeTo(C: TControl; Dark: Boolean; Bg, Panel, Txt: TColor);
var
  i: Integer;
begin
  if C is TNewCheckListBox then begin
    TNewCheckListBox(C).Color := Bg;
    TNewCheckListBox(C).Font.Color := Txt;
  end
  else if C is TNewStaticText then TNewStaticText(C).Font.Color := Txt
  else if C is TNewCheckBox then TNewCheckBox(C).Font.Color := Txt
  else if C is TNewRadioButton then TNewRadioButton(C).Font.Color := Txt
  else if C is TNewEdit then begin
    TNewEdit(C).Color := Panel; TNewEdit(C).Font.Color := Txt;
  end
  else if C is TNewMemo then begin
    TNewMemo(C).Color := Panel; TNewMemo(C).Font.Color := Txt;
  end
  else if C is TNewNotebookPage then TNewNotebookPage(C).Color := Bg
  else if C is TPanel then TPanel(C).Color := Bg;

  if C is TWinControl then
    for i := 0 to TWinControl(C).ControlCount - 1 do
      ApplyThemeTo(TWinControl(C).Controls[i], Dark, Bg, Panel, Txt);
end;

procedure ApplyTheme;
var
  v: Integer;
  bg, panel, txt: TColor;
begin
  if IsDarkTheme then begin bg := clDarkBg; panel := clDarkPanel; txt := clDarkText; end
  else begin bg := clLiteBg; panel := clLitePanel; txt := clLiteText; end;

  WizardForm.Color := bg;
  WizardForm.MainPanel.Color := bg;
  ApplyThemeTo(WizardForm, IsDarkTheme, bg, panel, txt);

  if IsDarkTheme then v := 1 else v := 0;
  DwmSetWindowAttribute(WizardForm.Handle, 20, v, SizeOf(v));   // dark/light title bar
end;

function FindTaskIndex(const Desc: String): Integer;
var
  i: Integer;
begin
  Result := -1;
  for i := 0 to WizardForm.TasksList.Items.Count - 1 do
    if WizardForm.TasksList.Items[i] = Desc then begin
      Result := i;
      Exit;
    end;
end;

// Offline mode already skips update checks at runtime (see TrayContext), so
// force "Turn off automatic update checks" on and gray it out to match -
// same reasoning as Settings' _checkForUpdates.Enabled wiring.
procedure SyncUpdateCheckTask;
begin
  if (TaskIndexOfflineMode < 0) or (TaskIndexNoUpdateCheck < 0) then Exit;
  if WizardForm.TasksList.Checked[TaskIndexOfflineMode] then begin
    WizardForm.TasksList.Checked[TaskIndexNoUpdateCheck] := True;
    WizardForm.TasksList.ItemEnabled[TaskIndexNoUpdateCheck] := False;
  end else
    WizardForm.TasksList.ItemEnabled[TaskIndexNoUpdateCheck] := True;
end;

procedure TasksListClickCheck(Sender: TObject);
begin
  SyncUpdateCheckTask;
end;

procedure InitializeWizard;
begin
  IsDarkTheme := True;   // installer defaults to dark mode, matching the app
  ApplyTheme;
  TaskIndexOfflineMode := -1;
  TaskIndexNoUpdateCheck := -1;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  ApplyTheme;   // re-theme controls created per page

  // TasksList isn't populated with items until its page is actually reached,
  // so the index lookup can't happen any earlier than this (InitializeWizard
  // is too soon - Items.Count is still 0 there).
  if (CurPageID = wpSelectTasks) and (TaskIndexOfflineMode < 0) then begin
    TaskIndexOfflineMode := FindTaskIndex('Offline mode: never contact Steam''s servers for game names');
    TaskIndexNoUpdateCheck := FindTaskIndex('Turn off automatic update checks');
    WizardForm.TasksList.OnClickCheck := @TasksListClickCheck;
    SyncUpdateCheckTask;
  end;
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
