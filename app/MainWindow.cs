using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace SteamScreenshotBackup
{
    // The main application window: live activity feed, backup statistics, and
    // every action that is also available from the tray menu.
    internal class MainWindow : Form
    {
        private static MainWindow _open;

        private readonly TrayContext _app;
        private readonly FlatListView _list;
        private readonly ComboBox _filter;
        private readonly Label _count;
        private readonly Label _empty;
        private readonly Action<LogEntry> _onAdded;

        private Button _pauseBtn;
        private Button _namesBtn;
        private int _unresolvedCount;
        private readonly ToolTip _tip = new ToolTip();
        private Label _statGames, _statFiles, _statSession;
        private Label _statGamesCap, _statFilesCap, _statSessionCap;
        private Panel _top, _stats, _bottom;
        private Panel[] _edges;
        private Button[] _buttons;
        private System.Windows.Forms.Timer _statsDebounce;

        public static void ShowWindow(TrayContext app)
        {
            if (_open == null || _open.IsDisposed)
            {
                _open = new MainWindow(app);
                _open.Show();
            }
            else if (!_open.Visible)
            {
                _open.Show();
            }
            if (_open.WindowState == FormWindowState.Minimized)
                _open.WindowState = FormWindowState.Normal;
            _open.Activate();
            _open.BringToFront();
        }

        // Left-clicking the tray icon toggles the main window: hide it when it's up,
        // show/restore it otherwise.
        public static void ToggleWindow(TrayContext app)
        {
            if (_open != null && !_open.IsDisposed && _open.Visible &&
                _open.WindowState != FormWindowState.Minimized)
                _open.Hide();
            else
                ShowWindow(app);
        }

        private MainWindow(TrayContext app)
        {
            _app = app;

            Text = "Steam Screenshot Backup";
            StartPosition = FormStartPosition.CenterScreen;
            Size = new Size(970, 600);
            MinimumSize = new Size(930, 420);
            AutoScaleMode = AutoScaleMode.Dpi;

            // ----- action bar -----
            _top = new Panel { Dock = DockStyle.Top, Height = 56 };
            var backupNow = MakeButton("Backup Now", 120, primary: true);
            backupNow.Click += (s, e) => _app.BackUpNow();
            var openFolder = MakeButton("Open Backup Folder", 155);
            openFolder.Click += (s, e) => _app.OpenBackupFolder();
            var resync = MakeButton("Re-Sync", 90);
            resync.Click += (s, e) => ResyncWindow.ShowWindow(_app.Engine);
            _pauseBtn = MakeButton("Pause Monitoring", 155);
            _pauseBtn.Click += (s, e) => _app.SetPaused(!_app.IsPaused);
            var settings = MakeButton("Settings", 90);
            settings.Click += (s, e) => _app.ShowSettings(this);
            _namesBtn = MakeButton("Game Names", 110);
            _namesBtn.Click += (s, e) =>
            {
                new GameNamesWindow(_app.Engine).ShowDialog(this);
                RefreshUnresolvedBadge();   // names may have just been fixed
            };
            var utilities = MakeButton("\u2699 Utilities", 120);
            utilities.Click += (s, e) => ShowUtilitiesMenu(utilities);

            _buttons = new[] { backupNow, openFolder, resync, _pauseBtn, settings, _namesBtn, utilities };
            int x = 14;
            foreach (var b in _buttons)
            {
                b.Location = new Point(x, 12);
                x += b.Width + 8;
                _top.Controls.Add(b);
            }

            // ----- statistics strip -----
            _stats = new Panel { Dock = DockStyle.Top, Height = 74 };
            (_statGames, _statGamesCap) = MakeStat(_stats, 14, "GAMES BACKED UP");
            (_statFiles, _statFilesCap) = MakeStat(_stats, 234, "SCREENSHOTS BACKED UP");
            (_statSession, _statSessionCap) = MakeStat(_stats, 454, "THIS SESSION");
            _stats.Resize += (s, e) => LayoutStats();

            // ----- filter row -----
            var filterRow = new Panel { Dock = DockStyle.Top, Height = 46 };
            _filter = new ComboBox
            {
                DropDownStyle = ComboBoxStyle.DropDownList,
                FlatStyle = FlatStyle.Flat,
                Width = 210,
                Location = new Point(14, 10)
            };
            _filter.Items.AddRange(new object[]
                { "All activity", "Backups", "Restores", "Deletions", "Warnings and errors", "Info" });
            _filter.SelectedIndex = 0;
            Theme.StyleComboBox(_filter);
            _filter.SelectedIndexChanged += (s, e) => Reload();
            filterRow.Controls.Add(_filter);

            _count = new Label
            {
                AutoSize = false,
                Width = 240,
                Height = 24,
                TextAlign = ContentAlignment.MiddleRight,
                Font = Theme.SmallFont,
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            _count.Location = new Point(filterRow.Width - _count.Width - 14, 12);
            filterRow.Controls.Add(_count);

            // ----- bottom bar -----
            _bottom = new Panel { Dock = DockStyle.Bottom, Height = 56 };
            var openLog = MakeButton("Open Full Log File", 150);
            openLog.Location = new Point(14, 12);
            openLog.Click += (s, e) => OpenLogFile();
            _bottom.Controls.Add(openLog);

            var hint = new Label
            {
                Text = "Double-click a backup or restore entry to show the file in Explorer",
                AutoSize = true,
                Font = Theme.SmallFont,
                Location = new Point(176, 20)
            };
            _bottom.Controls.Add(hint);

            var close = MakeButton("Close", 96);
            close.Anchor = AnchorStyles.Top | AnchorStyles.Right;
            close.Location = new Point(_bottom.Width - close.Width - 14, 12);
            close.Click += (s, e) => Close();
            _bottom.Controls.Add(close);

            // Subtle version label, tucked to the right just before Close.
            var version = new Label
            {
                Text = "v" + Application.ProductVersion.Split('+')[0],
                AutoSize = true,
                Font = Theme.SmallFont,
                Anchor = AnchorStyles.Top | AnchorStyles.Right,
                Location = new Point(close.Left - 62, 20)
            };
            _bottom.Controls.Add(version);

            // ----- activity list -----
            _list = new FlatListView
            {
                Dock = DockStyle.Fill,
                View = View.Details,
                FullRowSelect = true,
                MultiSelect = false,
                HeaderStyle = ColumnHeaderStyle.Nonclickable,
                BorderStyle = BorderStyle.None,
                OwnerDraw = true
            };
            _list.Columns.Add("Time", 150);
            _list.Columns.Add("Event", 96);
            _list.Columns.Add("Details", 480);
            _list.DrawColumnHeader += DrawHeader;
            _list.DrawSubItem += DrawSubItem;
            _list.Resize += (s, e) => FitDetailsColumn();
            _list.MouseDoubleClick += (s, e) => RevealSelectedFile();
            Theme.ApplyScrollbars(_list);
            Theme.EnableDoubleBuffer(_list);

            _empty = new Label
            {
                Text = "Nothing here yet \u2014 new activity will appear as it happens.",
                Dock = DockStyle.Fill,
                TextAlign = ContentAlignment.MiddleCenter
            };

            var e1 = new Panel { Dock = DockStyle.Top, Height = 1 };
            var e2 = new Panel { Dock = DockStyle.Top, Height = 1 };
            var e3 = new Panel { Dock = DockStyle.Bottom, Height = 1 };
            _edges = new[] { e1, e2, e3 };

            Controls.Add(_empty);
            Controls.Add(_list);
            Controls.Add(filterRow);
            Controls.Add(e2);
            Controls.Add(_stats);
            Controls.Add(e1);
            Controls.Add(_top);
            Controls.Add(e3);
            Controls.Add(_bottom);

            ApplyTheme();
            Theme.Changed += ApplyTheme;

            _onAdded = entry =>
            {
                try
                {
                    if (!IsDisposed && IsHandleCreated)
                        BeginInvoke(new Action(() => { Append(entry); OnActivity(entry); }));
                }
                catch { }   // window torn down mid-callback
            };
            Logger.Added += _onAdded;
            _app.PauseChanged += OnPauseChanged;
            Action<int> onUnresolvedCountChanged = count =>
            {
                try
                {
                    if (!IsDisposed && IsHandleCreated)
                        BeginInvoke(new Action(() => SetUnresolvedCount(count)));
                }
                catch { }   // window torn down mid-callback
            };
            _app.Engine.UnresolvedCountChanged += onUnresolvedCountChanged;
            FormClosed += (s, e) =>
            {
                Logger.Added -= _onAdded;
                Theme.Changed -= ApplyTheme;
                _app.PauseChanged -= OnPauseChanged;
                _app.Engine.UnresolvedCountChanged -= onUnresolvedCountChanged;
            };

            _statsDebounce = new System.Windows.Forms.Timer { Interval = 800 };
            _statsDebounce.Tick += (s, e) => { _statsDebounce.Stop(); RefreshTotals(); };

            OnPauseChanged();
            Reload();
            RefreshSessionStat();
            RefreshTotals();
            LayoutStats();
            RefreshUnresolvedBadge();
        }

        // ------------------------------------------------------------- theming

        private Button MakeButton(string text, int width, bool primary = false)
        {
            var b = new Button { Text = text, Size = new Size(width, 32), Tag = primary };
            Theme.StyleButton(b, primary);
            return b;
        }

        // -------------------------------------------------------- utilities menu

        private void ShowUtilitiesMenu(Control anchor)
        {
            var menu = new ContextMenuStrip { Renderer = Theme.MenuRenderer };
            menu.Items.Add("Delete Standard Backups", null, (s, e) => DeleteTypeBackups(ScreenshotType.Standard));
            menu.Items.Add("Delete High-Resolution Backups", null, (s, e) => DeleteTypeBackups(ScreenshotType.HighRes));
            menu.Items.Add("Delete Markdown Indexes", null, (s, e) => DeleteMarkdownIndexes());
            menu.Items.Add("Delete Original Steam Screenshot Files", null, (s, e) => DeleteImportedOriginals());
            menu.Items.Add("Clear Application Logs", null, (s, e) => ClearApplicationLogs());
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Granular Deletion", null,
                (s, e) => TargetedDeleteWindow.ShowWindow(_app.Engine, this));
#if !OFFLINE_ONLY
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Check for Updates Now", null, (s, e) => _app.CheckForUpdatesNow());
#endif
            menu.Show(anchor, new Point(0, anchor.Height));
        }

        private void DeleteTypeBackups(ScreenshotType type)
        {
            var engine = _app.Engine;
            string label = BackupEngine.TypeLabel(type);
            var (count, bytes) = engine.PreviewTypeBackups(type);
            if (!MessageDialog.ConfirmDeletion($"Delete all {label} backups?", count, bytes)) return;
            ProgressWindow.Run(this, "Deleting Backups\u2026", $"Sending {label} backups to the Recycle Bin\u2026",
                progress => engine.DeleteTypeBackups(type));
        }

        private void DeleteMarkdownIndexes()
        {
            var engine = _app.Engine;
            var (count, bytes) = engine.PreviewMarkdownIndexes();
            if (!MessageDialog.ConfirmDeletion("Delete all Markdown index files?", count, bytes)) return;
            ProgressWindow.Run(this, "Deleting Index\u2026", "Sending _Screenshot_Log.md files to the Recycle Bin\u2026",
                progress => engine.DeleteMarkdownIndexes(progress));
        }

        private void DeleteImportedOriginals()
        {
            var engine = _app.Engine;
            var (count, bytes) = engine.PreviewPurgeImportedOriginals();
            if (!MessageDialog.ConfirmDeletion(
                    "Delete original Steam screenshots that are already backed up?", count, bytes)) return;
            ProgressWindow.Run(this, "Deleting Originals\u2026", "Sending imported originals to the Recycle Bin\u2026",
                progress => engine.PurgeImportedOriginals(progress));
        }

        private void ClearApplicationLogs()
        {
            var (count, bytes) = Logger.PreviewLogFiles();
            if (!MessageDialog.ConfirmDeletion("Clear the application log file and its archives?", count, bytes)) return;
            Logger.ClearLogs();
            Reload();
        }

        private (Label Value, Label Caption) MakeStat(Panel host, int x, string caption)
        {
            var cap = new Label
            {
                Text = caption,
                Font = Theme.HeaderFont,
                AutoSize = true,
                Location = new Point(x, 12)
            };
            var val = new Label
            {
                Text = "\u2014",
                Font = Theme.StatFont,
                AutoSize = true,
                Location = new Point(x - 2, 32)
            };
            host.Controls.Add(cap);
            host.Controls.Add(val);
            return (val, cap);
        }

        // Spread the three stat columns evenly across the strip so they track the
        // window width instead of bunching at fixed left offsets.
        private void LayoutStats()
        {
            if (_stats == null || _stats.Width <= 0) return;
            var caps = new[] { _statGamesCap, _statFilesCap, _statSessionCap };
            var vals = new[] { _statGames, _statFiles, _statSession };
            int colW = _stats.Width / caps.Length;
            for (int i = 0; i < caps.Length; i++)
            {
                int left = i * colW + 14;
                caps[i].Left = left;
                vals[i].Left = left - 2;
            }
        }

        private void ApplyTheme()
        {
            Theme.ApplyWindow(this);
            _top.BackColor = Theme.Panel;
            _stats.BackColor = Theme.Background;
            _bottom.BackColor = Theme.Panel;
            foreach (var e in _edges) e.BackColor = Theme.PanelEdge;
            foreach (Control c in _top.Controls)
                if (c is Button b) Theme.StyleButton(b, (bool)b.Tag);
            ApplyUnresolvedHighlight();
            foreach (Control c in _bottom.Controls)
            {
                if (c is Button b) Theme.StyleButton(b, (bool)b.Tag);
                if (c is Label l) l.ForeColor = Theme.TextDim;
            }
            foreach (var cap in new[] { _statGamesCap, _statFilesCap, _statSessionCap })
                cap.ForeColor = Theme.TextDim;
            foreach (var val in new[] { _statGames, _statFiles, _statSession })
                val.ForeColor = Theme.Text;
            _statSession.ForeColor = Theme.Accent;
            _filter.Parent.BackColor = Theme.Background;
            Theme.StyleInput(_filter);
            _count.ForeColor = Theme.TextDim;
            _list.BackColor = Theme.Background;
            _list.ForeColor = Theme.Text;
            _empty.BackColor = Theme.Background;
            _empty.ForeColor = Theme.TextDim;
            Invalidate(true);
        }

        // ------------------------------------------------------------ stats

        private void OnActivity(LogEntry entry)
        {
            RefreshSessionStat();
            if (entry.Level is LogLevel.Backup or LogLevel.Restore or LogLevel.Deletion)
            {
                _statsDebounce.Stop();
                _statsDebounce.Start();   // recompute totals shortly after bursts settle
            }
        }

        private void RefreshSessionStat()
        {
            _statSession.Text = $"{_app.Engine.SessionFiles} files  \u00B7  {FormatBytes(_app.Engine.SessionBytes)}";
        }

        private void RefreshTotals()
        {
            var engine = _app.Engine;
            Task.Run(() =>
            {
                var (games, files, bytes) = engine.ComputeTotals();
                try
                {
                    if (!IsDisposed && IsHandleCreated)
                        BeginInvoke(new Action(() =>
                        {
                            _statGames.Text = games.ToString();
                            _statFiles.Text = $"{files}  \u00B7  {FormatBytes(bytes)}";
                        }));
                }
                catch { }
            });
        }

        // ------------------------------------------------------- unresolved-game badge

        // Recomputes the current count directly from disk (used at startup and right
        // after the Game Names window closes, where waiting for the next background
        // scan would leave a just-fixed badge showing stale).
        private void RefreshUnresolvedBadge()
        {
            var engine = _app.Engine;
            Task.Run(() =>
            {
                int count = engine.FindUnresolvedGameFolders().Count;
                try
                {
                    if (!IsDisposed && IsHandleCreated)
                        BeginInvoke(new Action(() => SetUnresolvedCount(count)));
                }
                catch { }   // window torn down mid-callback
            });
        }

        private void SetUnresolvedCount(int count)
        {
            _unresolvedCount = count;
            _tip.SetToolTip(_namesBtn, count > 0
                ? $"{count} game folder{(count == 1 ? "" : "s")} couldn't be named automatically"
                : null);
            ApplyUnresolvedHighlight();
        }

        // The button's own text stays fixed-width ("Game Names") and a toast notification
        // alone is easy to miss, so an unresolved game instead swaps the button's normal
        // grayish border for a highlighted warning-colored one.
        private void ApplyUnresolvedHighlight()
        {
            if (_unresolvedCount > 0)
            {
                _namesBtn.FlatAppearance.BorderColor = Theme.Warning;
                _namesBtn.FlatAppearance.BorderSize = 2;
            }
            else
            {
                Theme.StyleButton(_namesBtn, false);
            }
        }

        internal static string FormatBytes(long b)
        {
            if (b >= 1L << 30) return $"{b / (double)(1L << 30):0.0} GB";
            if (b >= 1L << 20) return $"{b / (double)(1L << 20):0.0} MB";
            if (b >= 1L << 10) return $"{b / (double)(1L << 10):0.0} KB";
            return $"{b} B";
        }

        private void OnPauseChanged()
        {
            _pauseBtn.Text = _app.IsPaused ? "Resume Monitoring" : "Pause Monitoring";
        }

        // ------------------------------------------------------------- log list

        private bool PassesFilter(LogEntry e) => _filter.SelectedIndex switch
        {
            1 => e.Level == LogLevel.Backup,
            2 => e.Level == LogLevel.Restore,
            3 => e.Level == LogLevel.Deletion,
            4 => e.Level == LogLevel.Warning || e.Level == LogLevel.Error,
            5 => e.Level == LogLevel.Info || e.Level == LogLevel.Update,
            _ => true
        };

        private void Reload()
        {
            _list.BeginUpdate();
            _list.Items.Clear();
            foreach (var entry in Logger.Snapshot())
                if (PassesFilter(entry))
                    _list.Items.Insert(0, MakeItem(entry));   // newest first
            _list.EndUpdate();
            FitDetailsColumn();
            UpdateChrome();
        }

        private void Append(LogEntry entry)
        {
            if (!PassesFilter(entry)) return;
            _list.Items.Insert(0, MakeItem(entry));
            if (_list.Items.Count > 1000) _list.Items.RemoveAt(_list.Items.Count - 1);
            UpdateChrome();
        }

        private static ListViewItem MakeItem(LogEntry e)
        {
            string kind = e.Level switch
            {
                LogLevel.Backup => "Backup",
                LogLevel.Restore => "Restore",
                LogLevel.Deletion => "Deletion",
                LogLevel.Warning => "Warning",
                LogLevel.Error => "Error",
                LogLevel.Update => "Update",
                _ => "Info"
            };
            var item = new ListViewItem(e.Time.ToString("yyyy-MM-dd HH:mm:ss")) { Tag = e };
            item.SubItems.Add(kind);
            item.SubItems.Add(e.Message);
            return item;
        }

        private void UpdateChrome()
        {
            int n = _list.Items.Count;
            _count.Text = n == 1 ? "1 entry this session" : $"{n} entries this session";
            _empty.Visible = n == 0;
        }

        private void FitDetailsColumn()
        {
            int w = _list.ClientSize.Width - _list.Columns[0].Width - _list.Columns[1].Width;
            if (w > 100) _list.Columns[2].Width = w;
        }

        private static Color LevelColor(LogLevel level) => level switch
        {
            LogLevel.Backup => Theme.Accent,
            LogLevel.Restore => Theme.Success,
            LogLevel.Deletion => Theme.Warning,
            LogLevel.Warning => Theme.Warning,
            LogLevel.Error => Theme.Error,
            LogLevel.Update => Theme.Accent,
            _ => Theme.TextDim
        };

        private void DrawHeader(object sender, DrawListViewColumnHeaderEventArgs e)
        {
            using var b = new SolidBrush(Theme.Panel);
            e.Graphics.FillRectangle(b, e.Bounds);
            var r = new Rectangle(e.Bounds.X + 8, e.Bounds.Y, e.Bounds.Width - 8, e.Bounds.Height);
            TextRenderer.DrawText(e.Graphics, e.Header.Text, Theme.HeaderFont, r, Theme.TextDim,
                TextFormatFlags.Left | TextFormatFlags.VerticalCenter);
            using var edge = new Pen(Theme.PanelEdge);
            e.Graphics.DrawLine(edge, e.Bounds.Left, e.Bounds.Bottom - 1, e.Bounds.Right, e.Bounds.Bottom - 1);
        }

        private void DrawSubItem(object sender, DrawListViewSubItemEventArgs e)
        {
            Color bg;
            if (e.Item.Selected) bg = Theme.Selection;
            else bg = e.ItemIndex % 2 == 0 ? Theme.Background : Theme.RowAlt;
            using (var b = new SolidBrush(bg)) e.Graphics.FillRectangle(b, e.Bounds);

            // A faint divider under every row makes it easy to tell where one entry
            // ends and the next begins, even between two same-shade rows.
            using (var edge = new Pen(Theme.PanelEdge))
                e.Graphics.DrawLine(edge, e.Bounds.Left, e.Bounds.Bottom - 1, e.Bounds.Right, e.Bounds.Bottom - 1);

            var level = ((LogEntry)e.Item.Tag).Level;
            Color fg = e.ColumnIndex switch
            {
                0 => Theme.TextDim,
                1 => LevelColor(level),
                _ => level == LogLevel.Error ? Theme.Error : Theme.Text
            };
            var r = new Rectangle(e.Bounds.X + 8, e.Bounds.Y, e.Bounds.Width - 8, e.Bounds.Height);
            TextRenderer.DrawText(e.Graphics, e.SubItem.Text, Font, r, fg,
                TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
        }

        private void RevealSelectedFile()
        {
            if (_list.SelectedItems.Count == 0) return;
            var entry = (LogEntry)_list.SelectedItems[0].Tag;

            // Newer entries carry the path; entries loaded from older log files don't,
            // so fall back to reconstructing it from the message text.
            string path = entry.FilePath;
            if (string.IsNullOrEmpty(path) &&
                entry.Level is LogLevel.Backup or LogLevel.Restore or LogLevel.Deletion)
                path = _app.Engine.BackupPathFromLogMessage(entry.Message);
            if (string.IsNullOrEmpty(path)) return;

            try
            {
                if (File.Exists(path))
                    Process.Start("explorer.exe", $"/select,\"{path}\"");
                else
                    MessageDialog.Info("That file no longer exists:\n" + path);
            }
            catch (Exception ex)
            {
                Logger.Error("Could not open Explorer: " + ex.Message);
            }
        }

        private static void OpenLogFile()
        {
            try
            {
                if (!File.Exists(Logger.LogFilePath))
                {
                    MessageDialog.Info("No log file has been written yet.");
                    return;
                }
                // ".log" has no default file association on most systems, so a plain
                // ShellExecute silently does nothing. Open it in Notepad (always present),
                // and fall back to revealing it in Explorer if that ever fails.
                try
                {
                    Process.Start(new ProcessStartInfo("notepad.exe", $"\"{Logger.LogFilePath}\"")
                        { UseShellExecute = true });
                }
                catch
                {
                    Process.Start("explorer.exe", $"/select,\"{Logger.LogFilePath}\"");
                }
            }
            catch (Exception ex)
            {
                Logger.Error("Could not open log file: " + ex.Message);
            }
        }
    }
}
