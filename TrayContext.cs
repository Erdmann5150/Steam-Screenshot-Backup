using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

namespace SteamScreenshotBackup
{
    internal class TrayContext : ApplicationContext
    {
        private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string RunValue = "SteamScreenshotBackup";

        private readonly NotifyIcon _tray;
        private readonly Settings _settings;
        private readonly Control _ui = new Control();   // invoke target for worker-thread callbacks
        private readonly ToolStripMenuItem _autoStartItem;
        private BackupEngine _engine;

        public TrayContext()
        {
            _ = _ui.Handle;   // force handle creation on the UI thread

            _settings = Settings.Load();
            if (string.IsNullOrWhiteSpace(_settings.Destination))
                _settings.Destination = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.MyPictures), "Steam Screenshots");

            var menu = new ContextMenuStrip();
            menu.Items.Add("Back up now", null, (s, e) => RunFullScan(showResult: true));
            menu.Items.Add("Open backup folder", null, (s, e) => OpenBackupFolder());
            menu.Items.Add(new ToolStripSeparator());

            var pauseItem = new ToolStripMenuItem("Pause watching") { CheckOnClick = true };
            pauseItem.CheckedChanged += (s, e) => { if (_engine != null) _engine.Paused = pauseItem.Checked; };
            menu.Items.Add(pauseItem);

            _autoStartItem = new ToolStripMenuItem("Start with Windows")
                { Checked = IsAutoStart(), CheckOnClick = true };
            _autoStartItem.CheckedChanged += (s, e) => SetAutoStart(_autoStartItem.Checked);
            menu.Items.Add(_autoStartItem);

            menu.Items.Add("Change backup folder\u2026", null, (s, e) => ChangeDestination());
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Exit", null, (s, e) => ExitApp());

            _tray = new NotifyIcon
            {
                Icon = CreateTrayIcon(),
                ContextMenuStrip = menu,
                Text = "Steam Screenshot Backup",
                Visible = true
            };
            _tray.DoubleClick += (s, e) => OpenBackupFolder();

            if (!_settings.FirstRunDone) FirstRun();
            _settings.Save();

            try
            {
                _engine = new BackupEngine(() => _settings.Destination);
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.Message, "Steam Screenshot Backup",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                _tray.Visible = false;
                Environment.Exit(1);
                return;
            }

            _engine.Status += SetStatus;
            _engine.StartWatching();
            RunFullScan(showResult: false);   // catch up on anything taken while we weren't running
        }

        private void FirstRun()
        {
            MessageBox.Show(
                "Steam Screenshot Backup runs in the system tray and automatically copies every Steam " +
                "screenshot you take into per-game folders with readable names.\n\n" +
                "Next, choose where your backups should be stored.",
                "Welcome", MessageBoxButtons.OK, MessageBoxIcon.Information);

            ChangeDestination();

            if (MessageBox.Show("Start automatically when you sign in to Windows?",
                    "Steam Screenshot Backup", MessageBoxButtons.YesNo, MessageBoxIcon.Question)
                == DialogResult.Yes)
            {
                _autoStartItem.Checked = true;   // CheckedChanged handler writes the registry value
            }

            _settings.FirstRunDone = true;
        }

        private void ChangeDestination()
        {
            using var dlg = new FolderBrowserDialog
            {
                Description = "Choose the folder where screenshots will be backed up.",
                UseDescriptionForTitle = true,
                SelectedPath = _settings.Destination
            };
            if (dlg.ShowDialog() != DialogResult.OK) return;

            _settings.Destination = dlg.SelectedPath;
            _settings.Save();
            RunFullScan(showResult: true);   // populate the new location
        }

        private void RunFullScan(bool showResult)
        {
            if (_engine == null) return;
            Task.Run(() =>
            {
                try
                {
                    var (games, copied, skipped) = _engine.FullScan();
                    SetStatus($"scan done, {copied} new");
                    if (showResult || copied > 0)
                        OnUi(() => _tray.ShowBalloonTip(4000, "Steam Screenshot Backup",
                            $"{games} games \u2014 {copied} new screenshots copied, {skipped} already backed up.",
                            ToolTipIcon.Info));
                }
                catch (Exception ex)
                {
                    Logger.Log("Full scan failed: " + ex.Message);
                    OnUi(() => _tray.ShowBalloonTip(4000, "Steam Screenshot Backup",
                        "Backup scan failed \u2014 see app.log for details.", ToolTipIcon.Error));
                }
            });
        }

        private void SetStatus(string s)
        {
            OnUi(() =>
            {
                string text = "Steam Screenshots \u2014 " + s;
                _tray.Text = text.Length > 63 ? text.Substring(0, 63) : text;   // tooltip hard limit
            });
        }

        private void OnUi(Action a)
        {
            if (_ui.InvokeRequired) _ui.BeginInvoke(a);
            else a();
        }

        private void OpenBackupFolder()
        {
            try
            {
                Directory.CreateDirectory(_settings.Destination);
                Process.Start(new ProcessStartInfo { FileName = _settings.Destination, UseShellExecute = true });
            }
            catch (Exception ex) { Logger.Log("Open folder failed: " + ex.Message); }
        }

        private static bool IsAutoStart()
        {
            using var k = Registry.CurrentUser.OpenSubKey(RunKey);
            return k?.GetValue(RunValue) != null;
        }

        private static void SetAutoStart(bool on)
        {
            using var k = Registry.CurrentUser.OpenSubKey(RunKey, writable: true);
            if (k == null) return;
            if (on) k.SetValue(RunValue, $"\"{Environment.ProcessPath ?? Application.ExecutablePath}\"");
            else k.DeleteValue(RunValue, false);
        }

        private void ExitApp()
        {
            _tray.Visible = false;
            _engine?.Dispose();
            ExitThread();
        }

        private static Icon CreateTrayIcon()
        {
            // Simple camera glyph drawn at runtime - no binary assets in the repo.
            using var bmp = new Bitmap(32, 32);
            using (var g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.Clear(Color.Transparent);
                using var body = new SolidBrush(Color.FromArgb(35, 35, 40));
                g.FillRectangle(body, 2, 9, 28, 19);
                g.FillRectangle(body, 10, 5, 12, 6);
                using var lens = new SolidBrush(Color.FromArgb(102, 192, 244));   // Steam blue
                g.FillEllipse(lens, 9, 12, 14, 14);
                using var inner = new SolidBrush(Color.White);
                g.FillEllipse(inner, 13, 16, 6, 6);
            }
            return Icon.FromHandle(bmp.GetHicon());
        }
    }
}