using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

namespace SteamScreenshotBackup
{
    // Application coordinator: owns the tray icon, the backup engine, and the
    // actions shared between the tray menu and the main window.
    internal class TrayContext : ApplicationContext
    {
        private const string AppName = "Steam Screenshot Backup";
        private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string RunValue = "SteamScreenshotBackup";

        private readonly NotifyIcon _tray;
        private readonly Settings _settings;
        private readonly Control _ui = new Control();   // invoke target for worker-thread callbacks
        private readonly ToolStripMenuItem _pauseItem;
        private readonly ToolStripMenuItem _autoStartItem;
        private readonly ContextMenuStrip _menu;
        private BackupEngine _engine;
#if !OFFLINE_ONLY
        // Fully-qualified to avoid ambiguity with System.Windows.Forms.Timer, which
        // is also in scope in this file.
        private System.Threading.Timer _updateCheckTimer;
#endif

        public BackupEngine Engine => _engine;
        public Settings SettingsObj => _settings;
        public bool IsPaused => _engine?.Paused ?? false;
        public event Action PauseChanged;

        public TrayContext(Settings settings)
        {
            _settings = settings;
            _ = _ui.Handle;   // force handle creation on the UI thread

            if (string.IsNullOrWhiteSpace(_settings.Destination))
                _settings.Destination = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.MyPictures), "Steam Screenshots");

            _menu = new ContextMenuStrip { Renderer = Theme.MenuRenderer };
            _menu.Items.Add("Open " + AppName, null, (s, e) => MainWindow.ShowWindow(this));
            _menu.Items.Add("Backup Now", null, (s, e) => BackUpNow());
            _menu.Items.Add("Re-Sync", null, (s, e) => ResyncWindow.ShowWindow(_engine));
            _menu.Items.Add("Open Backup Folder", null, (s, e) => OpenBackupFolder());
            _menu.Items.Add("Game Names", null, (s, e) => OpenGameNames());
            _menu.Items.Add(new ToolStripSeparator());

            _pauseItem = new ToolStripMenuItem("Pause Monitoring") { CheckOnClick = true };
            _pauseItem.CheckedChanged += (s, e) => ApplyPause(_pauseItem.Checked);
            _menu.Items.Add(_pauseItem);

            _autoStartItem = new ToolStripMenuItem("Start with Windows")
                { Checked = IsAutoStartEnabled, CheckOnClick = true };
            _autoStartItem.CheckedChanged += (s, e) => WriteAutoStart(_autoStartItem.Checked);
            _menu.Items.Add(_autoStartItem);

            _menu.Items.Add("Settings", null, (s, e) => ShowSettings(null));
#if !OFFLINE_ONLY
            _menu.Items.Add("Check for Updates Now", null, (s, e) => CheckForUpdatesNow());
#endif
            _menu.Items.Add(new ToolStripSeparator());
            _menu.Items.Add("Uninstall", null, (s, e) => Uninstall());
            _menu.Items.Add("Exit", null, (s, e) => ExitApp());
            Theme.Changed += () => _menu.Renderer = Theme.MenuRenderer;

            _tray = new NotifyIcon
            {
                Icon = Theme.AppIcon,
                ContextMenuStrip = _menu,
                Text = AppName,
                Visible = true
            };
            _tray.MouseClick += (s, e) =>
            {
                if (e.Button == MouseButtons.Left) MainWindow.ToggleWindow(this);
            };

            try
            {
                _engine = new BackupEngine(_settings);
            }
            catch (Exception ex)
            {
                MessageDialog.Fail(ex.Message);
                _tray.Visible = false;
                Environment.Exit(1);
                return;
            }

            if (!_settings.FirstRunDone) FirstRun();
            _settings.Save();

            _engine.RestoreNeeded += () => RunScan(RunKind.Restore);
            _engine.DestinationOffline += () => Notify(5000,
                "Backup folder is unreachable \u2014 backups will resume automatically when it returns.",
                ToolTipIcon.Warning);
            _engine.DestinationOnline += () => RunScan(RunKind.Startup);
            _engine.UnresolvedGameFound += count => Notify(6000,
                $"{count} game folder{(count == 1 ? "" : "s")} could not be named automatically \u2014 " +
                "open Game Names to identify " + (count == 1 ? "it" : "them") + ".",
                ToolTipIcon.Info);

            _engine.MigrateStructureIfNeeded();
            _engine.StartWatching();
            Logger.Log($"Watching for new screenshots. Backing up to: {_settings.Destination}");
            RunScan(RunKind.Startup);   // catch up on anything taken while we weren't running

            // One-time: give pre-existing backups searchable metadata (older PNGs lacked it).
            if (!_settings.MetadataBackfilled)
                Task.Run(() =>
                {
                    _engine.BackfillMetadata();
                    _settings.MetadataBackfilled = true;
                    _settings.Save();
                });

#if !OFFLINE_ONLY
            // Small delay so this never competes with the startup catch-up scan above;
            // then once a day, same cadence as AppNameResolver's background re-verification.
            _updateCheckTimer = new System.Threading.Timer(
                _ => AutoCheckForUpdates(), null, TimeSpan.FromMinutes(2), TimeSpan.FromHours(24));
#endif
        }

        // Central gate for tray popups so the "show notifications" setting is honored.
        private void Notify(int ms, string text, ToolTipIcon icon)
        {
            if (!_settings.ShowNotifications) return;
            OnUi(() => _tray.ShowBalloonTip(ms, AppName, text, icon));
        }

        private void FirstRun()
        {
            using var setup = new SetupWindow(_settings.Destination, _engine.HighResSourceAvailable);
            setup.ShowDialog();   // closing the window accepts the defaults

            if (!string.IsNullOrWhiteSpace(setup.Destination))
                _settings.Destination = setup.Destination;
            _settings.BackupStandard = setup.BackupStandard || !setup.BackupHighRes;
            _settings.BackupHighRes = setup.BackupHighRes;
            if (setup.AutoStart)
                _autoStartItem.Checked = true;   // CheckedChanged handler writes the registry value

            // The installer can pre-select a couple of options via registry markers;
            // honor them on first run.
            try
            {
                using var k = Registry.CurrentUser.OpenSubKey(@"Software\SteamScreenshotBackup");
                if (k?.GetValue("DeleteOriginalsDefault") is int d && d == 1)
                    _settings.DeleteOriginals = true;
                if (k?.GetValue("NotificationsOffDefault") is int n && n == 1)
                    _settings.ShowNotifications = false;
                if (k?.GetValue("PreviewImportsDefault") is int p && p == 1)
                    _settings.PreviewBeforeImport = true;
                if (k?.GetValue("OfflineModeDefault") is int o && o == 1)
                    _settings.OfflineMode = true;
                if (k?.GetValue("UpdateCheckOffDefault") is int u && u == 1)
                    _settings.CheckForUpdates = false;
            }
            catch { }

            _settings.FirstRunDone = true;
        }

        // ------------------------------------------------------------- actions

        public void OpenMainWindow() => MainWindow.ShowWindow(this);

        public void BackUpNow() => RunScan(RunKind.Manual);

        public void OpenBackupFolder()
        {
            try
            {
                Directory.CreateDirectory(_settings.Destination);
                Process.Start(new ProcessStartInfo { FileName = _settings.Destination, UseShellExecute = true });
            }
            catch (Exception ex) { Logger.Error("Open folder failed: " + ex.Message); }
        }

        public void SetPaused(bool paused) => _pauseItem.Checked = paused;   // handler does the rest

        private void ApplyPause(bool paused)
        {
            if (_engine == null) return;
            _engine.Paused = paused;
            Logger.Log(paused ? "Watching paused." : "Watching resumed.");
            PauseChanged?.Invoke();
        }

        public void ShowSettings(IWin32Window owner)
        {
            using var dlg = new SettingsWindow(this, _settings);
            if (owner != null) dlg.ShowDialog(owner);
            else dlg.ShowDialog();
        }

        public void OpenGameNames()
        {
            using var dlg = new GameNamesWindow(_engine);
            dlg.ShowDialog();
        }

        // Called by SettingsWindow after saving; restarts watchers when sources or
        // the destination changed, then runs a scan to pick up the difference.
        public void OnSettingsChanged(bool sourcesChanged)
        {
            _autoStartItem.Checked = IsAutoStartEnabled;
            if (sourcesChanged && _engine != null)
            {
                _engine.RestartWatching();
                RunScan(RunKind.DestinationChanged);
            }
        }

#if !OFFLINE_ONLY
        // ----------------------------------------------------------- update checks

        // User-initiated, from the tray menu or the Utilities menu: always gives
        // visible feedback, even when there's nothing new.
        public void CheckForUpdatesNow()
        {
            if (_settings.OfflineMode)
            {
                MessageDialog.Info(
                    "Offline Mode is on, so update checks are disabled.\n\n" +
                    "Turn it off in Settings \u2192 Privacy to check for updates.");
                return;
            }

            Task.Run(() =>
            {
                var info = UpdateChecker.CheckNow(_settings);
                OnUi(() =>
                {
                    if (info == null)
                    {
                        MessageDialog.Info($"You're running the latest version ({UpdateChecker.CurrentVersion}).");
                        return;
                    }
                    if (MessageDialog.Confirm(
                            $"Version {info.Version} is available \u2014 you have {UpdateChecker.CurrentVersion}.",
                            "Update Available", "View Release", "Later"))
                        Process.Start(new ProcessStartInfo { FileName = info.Url, UseShellExecute = true });
                });
            });
        }

        // Timer-driven background check: silent unless there's actually something
        // new, and only notifies once per version so it doesn't nag on every pass.
        private void AutoCheckForUpdates()
        {
            if (!_settings.CheckForUpdates || _settings.OfflineMode) return;

            var info = UpdateChecker.CheckNow(_settings);
            if (info == null) return;
            if (string.Equals(_settings.LastNotifiedUpdateVersion, info.Version, StringComparison.OrdinalIgnoreCase))
                return;

            _settings.LastNotifiedUpdateVersion = info.Version;
            _settings.Save();
            Logger.UpdateAvailable($"Update available: version {info.Version} (currently running {UpdateChecker.CurrentVersion}).");
            Notify(6000,
                $"Version {info.Version} is available \u2014 use \"Check for Updates Now\" to view it.",
                ToolTipIcon.Info);
        }
#endif

        // ----------------------------------------------------------- scan runs

        private void RunScan(RunKind kind)
        {
            if (_engine == null) return;

            // The first-ever catch-up always previews; other batch scans preview only if
            // the user opted in. Auto-restore and real-time captures never preview.
            bool firstImport = kind == RunKind.Startup && !_settings.FirstImportDone;
            bool wantPreview = kind != RunKind.Restore &&
                (firstImport || (_settings.PreviewBeforeImport &&
                    kind is RunKind.Manual or RunKind.Startup or RunKind.DestinationChanged));

            Task.Run(() =>
            {
                try
                {
                    if (wantPreview)
                    {
                        var plan = _engine.PlanScan();
                        if (firstImport) { _settings.FirstImportDone = true; _settings.Save(); }
                        if (plan.Count > 0)
                        {
                            bool proceed = OnUiSync(() => PreviewWindow.Confirm(
                                "Preview Import",
                                $"{plan.Count} screenshot{(plan.Count == 1 ? "" : "s")} will be imported into your backup:",
                                plan, "Import"));
                            if (!proceed)
                            {
                                Logger.Log($"Import cancelled from preview ({plan.Count} not imported).");
                                return;
                            }
                        }
                    }

                    var run = _engine.FullScan(restore: kind == RunKind.Restore);
                    if (run == null)
                    {
                        if (kind == RunKind.Manual)
                            Notify(4000, "Backup folder is currently unreachable.", ToolTipIcon.Warning);
                        return;
                    }

                    ReportRun(kind, run);
                }
                catch (Exception ex)
                {
                    Logger.Error("Scan failed: " + ex.Message);
                    Notify(4000, "Backup scan failed \u2014 open the app for details.", ToolTipIcon.Error);
                }
            });
        }

        // Log + notify with only what THIS run did (no lifetime totals).
        private void ReportRun(RunKind kind, RunResult run)
        {
            int n = run.Copied;
            int games = run.GamesAffected.Count;
            string verb = kind == RunKind.Restore ? "restored" : "new";

            if (n > 0)
            {
                Logger.Log($"{(kind == RunKind.Restore ? "Restore" : "Backup")} run complete: " +
                           $"{n} {verb} file{(n == 1 ? "" : "s")} across {games} game{(games == 1 ? "" : "s")}.");
                string text = kind == RunKind.Restore
                    ? $"Restored {n} screenshot{(n == 1 ? "" : "s")} across {games} game{(games == 1 ? "" : "s")}."
                    : $"Backed up {n} new screenshot{(n == 1 ? "" : "s")} from {games} game{(games == 1 ? "" : "s")}.";
                Notify(4000, text, ToolTipIcon.Info);
            }
            else if (kind == RunKind.Restore)
            {
                Logger.Warn("Deleted backup files could not be restored - they no longer exist " +
                            "in Steam's screenshot folders.");
                Notify(5000, "Deleted files could not be restored \u2014 they no longer exist in Steam.",
                    ToolTipIcon.Warning);
            }
            else
            {
                Logger.Log("Backup run complete: nothing new to copy.");
                if (kind == RunKind.Manual)
                    Notify(3000, "Everything is already backed up.", ToolTipIcon.Info);
            }
        }

        private void OnUi(Action a)
        {
            if (_ui.InvokeRequired) _ui.BeginInvoke(a);
            else a();
        }

        // Runs a function on the UI thread and waits for its result (for modal prompts
        // triggered from background scan tasks).
        private T OnUiSync<T>(Func<T> f)
        {
            if (_ui.InvokeRequired) return (T)_ui.Invoke(f);
            return f();
        }

        // ------------------------------------------------------------ autostart

        public bool IsAutoStartEnabled
        {
            get
            {
                using var k = Registry.CurrentUser.OpenSubKey(RunKey);
                return k?.GetValue(RunValue) != null;
            }
        }

        public void SetAutoStartEnabled(bool on) => _autoStartItem.Checked = on;

        private static void WriteAutoStart(bool on)
        {
            using var k = Registry.CurrentUser.OpenSubKey(RunKey, writable: true);
            if (k == null) return;
            if (on) k.SetValue(RunValue, $"\"{Environment.ProcessPath ?? Application.ExecutablePath}\"");
            else k.DeleteValue(RunValue, false);
        }

        // ------------------------------------------------------------ uninstall

        // Installed builds carry Inno Setup's uninstaller next to the exe; portable
        // builds clean up after themselves with a detached cmd.
        public void Uninstall()
        {
            string exeDir = AppContext.BaseDirectory;
            string innoUninstaller = Path.Combine(exeDir, "unins000.exe");

            if (File.Exists(innoUninstaller))
            {
                try
                {
                    Process.Start(new ProcessStartInfo { FileName = innoUninstaller, UseShellExecute = true });
                    ExitApp();
                }
                catch (Exception ex)
                {
                    MessageDialog.Fail("Could not start the uninstaller:\n" + ex.Message);
                }
                return;
            }

            bool ok = MessageDialog.AskYesNo(
                "This removes " + AppName + " from this PC:\n\n" +
                "  \u2022  stops the app and removes it from Windows startup\n" +
                "  \u2022  deletes its settings, game-name cache, and log\n" +
                "  \u2022  deletes the program file itself\n\n" +
                "Your backed-up screenshots and Steam's own files are NOT touched.\n\n" +
                "Uninstall now?",
                "Uninstall " + AppName);
            if (!ok) return;

            try { WriteAutoStart(false); } catch { }

            // The exe can't delete itself while running, and the data folder could be
            // recreated by a late log write - hand both jobs to a detached cmd that
            // waits for this process to exit. Everything is best-effort by design.
            string exe = Environment.ProcessPath ?? Application.ExecutablePath;
            string dataDir = Settings.Dir;
            string temp = Path.Combine(Path.GetTempPath(), ".net", "SteamScreenshotBackup");
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = "cmd.exe",
                    Arguments = "/c ping -n 4 127.0.0.1 >nul" +
                                $" & del /f /q \"{exe}\"" +
                                $" & rmdir /s /q \"{dataDir}\"" +
                                $" & rmdir /s /q \"{temp}\"",
                    WindowStyle = ProcessWindowStyle.Hidden,
                    CreateNoWindow = true,
                    UseShellExecute = false
                });
            }
            catch { }

            try { Directory.Delete(dataDir, true); } catch { }
            ExitApp();
        }

        private void ExitApp()
        {
            _tray.Visible = false;
#if !OFFLINE_ONLY
            _updateCheckTimer?.Dispose();
#endif
            _engine?.Dispose();
            ExitThread();
        }
    }
}
