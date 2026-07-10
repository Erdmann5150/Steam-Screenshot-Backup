using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace SteamScreenshotBackup
{
    // All app configuration in one place, split across two tabs (General / Backup
    // configuration) so the window fits its content without a scrollbar. Changes are
    // applied when Save is clicked; destination and layout changes offer to migrate
    // or reorganize existing backups.
    internal class SettingsWindow : Form
    {
        private static readonly (string Label, string Template)[] LayoutPresets =
        {
            ("Game name",               "{game}"),
            ("Game name \\ Year",       "{game}\\{yyyy}"),
            ("Game name \\ Year-Month", "{game}\\{yyyy}-{MM}"),
            ("Year \\ Game name",       "{yyyy}\\{game}"),
            ("Year-Month \\ Game name", "{yyyy}-{MM}\\{game}"),
        };

        private readonly TrayContext _app;
        private readonly Settings _settings;

        private readonly TextBox _dest;
        private readonly TextBox _highResFolder;
        private readonly CheckBox _standard, _highRes, _autoStart, _autoRestore, _deleteOriginals,
                                  _showNotifications, _markdownIndex, _previewImport, _offlineMode;
        private readonly ComboBox _layout, _theme;
        private bool _suppressDangerPrompt;   // guards the enable-confirmation loop

        // Tab state.
        private readonly Panel _generalPage, _backupPage, _indicator;
        private readonly Button _tabGeneral, _tabBackup;

        public SettingsWindow(TrayContext app, Settings settings)
        {
            _app = app;
            _settings = settings;

            Text = "Settings \u2014 Steam Screenshot Backup";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterParent;
            AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(577, 600);   // provisional; final height set after layout
            Theme.ApplyWindow(this);

            // ----- footer (built first so anchored buttons settle to the right edge) -----
            var footer = new Panel { Dock = DockStyle.Bottom, Height = 60, BackColor = Theme.Panel };
            var footerEdge = new Panel { Dock = DockStyle.Bottom, Height = 1, BackColor = Theme.PanelEdge };

            var uninstall = new Button { Text = "Uninstall", Size = new Size(110, 32), Location = new Point(14, 13) };
            Theme.StyleButton(uninstall);
            uninstall.ForeColor = Theme.Error;
            uninstall.Click += (s, e) => { Close(); _app.Uninstall(); };
            footer.Controls.Add(uninstall);

            // Close just closes the window; it never implies "discard" the way Cancel
            // would, since Apply may already have saved earlier changes in this session.
            var close = new Button
            {
                Text = "Close",
                Size = new Size(96, 32),
                DialogResult = DialogResult.Cancel,
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            close.Location = new Point(footer.Width - 96 - 14, 13);
            Theme.StyleButton(close);
            footer.Controls.Add(close);

            // Apply saves in the background and leaves the window open, so the user can
            // keep adjusting settings and see the effect of each change without having
            // to reopen the window.
            var apply = new Button
            {
                Text = "Apply",
                Size = new Size(96, 32),
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            apply.Location = new Point(footer.Width - 96 - 14 - 96 - 10, 13);
            Theme.StyleButton(apply, primary: true);
            apply.Click += (s, e) => SaveChanges();
            footer.Controls.Add(apply);

            // ----- content host + two pages -----
            var contentHost = new Panel { Dock = DockStyle.Fill, BackColor = Theme.Background };
            _generalPage = new Panel { Dock = DockStyle.Fill, AutoScroll = true, BackColor = Theme.Background };
            _backupPage = new Panel { Dock = DockStyle.Fill, AutoScroll = true, BackColor = Theme.Background, Visible = false };
            Theme.ApplyScrollbars(_generalPage);
            Theme.ApplyScrollbars(_backupPage);
            contentHost.Controls.Add(_generalPage);
            contentHost.Controls.Add(_backupPage);

            // Shared builder: local functions capture `page` and `y`, which are reset
            // between the two pages so the same layout helpers serve both.
            Panel page = _generalPage;
            int y = 20;
            void Section(string text)
            {
                page.Controls.Add(new Label
                {
                    Text = text,
                    Font = Theme.HeaderFont,
                    ForeColor = Theme.TextDim,
                    AutoSize = true,
                    Location = new Point(24, y)
                });
                y += 22;
            }
            Label Hint(string text, int x = 42)
            {
                var l = new Label
                {
                    Text = text,
                    Font = Theme.SmallFont,
                    ForeColor = Theme.TextDim,
                    AutoSize = true,
                    Location = new Point(x, y)
                };
                page.Controls.Add(l);
                return l;
            }
            CheckBox Check(CheckBox box, string text, bool value, Color color)
            {
                box.Text = text;
                box.Checked = value;
                box.AutoSize = true;
                box.Location = new Point(24, y);
                box.ForeColor = color;
                page.Controls.Add(box);
                return box;
            }

            // ============================ GENERAL ============================
            page = _generalPage; y = 20;

            Section("APPEARANCE");
            _theme = new ComboBox
            {
                DropDownStyle = ComboBoxStyle.DropDownList,
                FlatStyle = FlatStyle.Flat,
                Width = 260,
                Location = new Point(24, y)
            };
            Theme.StyleInput(_theme);
            _theme.Items.AddRange(new object[] { "Dark", "Light", "Follow Windows setting" });
            _theme.SelectedIndex = _settings.Theme switch
            {
                ThemeMode.Light => 1,
                ThemeMode.System => 2,
                _ => 0
            };
            page.Controls.Add(_theme);
            y += 40;

            _showNotifications = new CheckBox();
            Check(_showNotifications, "Show popup notifications", _settings.ShowNotifications, Theme.Text);
            y += 40;

            Section("STARTUP");
            _autoStart = new CheckBox();
            Check(_autoStart, "Start automatically when I sign in to Windows", _app.IsAutoStartEnabled, Theme.Text);
            y += 40;

            Section("IMPORTING");
            _markdownIndex = new CheckBox();
            Check(_markdownIndex, "Generate a Markdown index (_Screenshot_Log.md) in each folder",
                _settings.GenerateMarkdownIndex, Theme.Text);
            y += 28;
            _previewImport = new CheckBox();
            Check(_previewImport, "Preview a list of changes before importing batches",
                _settings.PreviewBeforeImport, Theme.Text);
            y += 26;
            Hint("Real-time captures during play are never interrupted; this only affects batch scans.");
            y += 40;

            Section("DELETED-FILE PROTECTION");
            _autoRestore = new CheckBox();
            Check(_autoRestore, "Automatically restore files deleted from the backup",
                _settings.AutoRestore, Theme.Text);
            y += 26;
            Hint("When off, deletions are only logged \u2014 recover them yourself from \"Re-Sync\".");
            y += 28;

            Section("PRIVACY");
            _offlineMode = new CheckBox();
            Check(_offlineMode, "Offline mode: never contact Steam's servers for game names",
                _settings.OfflineMode, Theme.Text);
            y += 26;
            Hint("Game names still resolve from local Steam data; only unrecognized games\n" +
                 "fall back to an \"AppID_<id>\" folder name.");
            y += 44;
#if OFFLINE_ONLY
            _offlineMode.Checked = true;
            _offlineMode.Enabled = false;
#endif
            int generalBottom = y;

            // ======================= BACKUP CONFIGURATION =======================
            page = _backupPage; y = 20;

            Section("BACKUP FOLDER");
            _dest = new TextBox
            {
                Text = _settings.Destination,
                Location = new Point(24, y),
                Width = 408,
                BorderStyle = BorderStyle.FixedSingle
            };
            Theme.StyleInput(_dest);
            var browse = new Button { Text = "Browse", Size = new Size(92, _dest.Height + 2) };
            browse.Location = new Point(440, y - 1);
            Theme.StyleButton(browse);
            browse.Click += (s, e) => Browse();
            page.Controls.Add(_dest);
            page.Controls.Add(browse);
            y += 44;

            Section("WHAT TO BACK UP");
            _standard = new CheckBox();
            Check(_standard, "Standard screenshots (Steam's compressed library copies)",
                _settings.BackupStandard, Theme.Text);
            y += 28;
            _highRes = new CheckBox();
            Check(_highRes, "High-resolution screenshots (Steam's \"save an external copy\" files)",
                _settings.BackupHighRes, Theme.Text);
            y += 30;

            // Manual high-resolution folder \u2014 used when Steam's config doesn't reveal
            // one (or to add an extra location). Placeholder shows the auto-detected path.
            string detected = _app.Engine.AutoDetectedHighResFolder;
            Hint(detected != null
                ? "High-resolution folder (auto-detected; set only to use a different one):"
                : "High-resolution folder (not auto-detected \u2014 set it here if you use external copies):");
            y += 20;
            _highResFolder = new TextBox
            {
                Text = _settings.HighResFolderOverride ?? "",
                Location = new Point(42, y),
                Width = 390,
                BorderStyle = BorderStyle.FixedSingle
            };
            if (detected != null) _highResFolder.PlaceholderText = detected;
            Theme.StyleInput(_highResFolder);
            var hrBrowse = new Button { Text = "Browse", Size = new Size(92, _highResFolder.Height + 2) };
            hrBrowse.Location = new Point(440, y - 1);
            Theme.StyleButton(hrBrowse);
            hrBrowse.Click += (s, e) => BrowseHighRes();
            page.Controls.Add(_highResFolder);
            page.Controls.Add(hrBrowse);
            y += 42;

            Section("FOLDER LAYOUT (INSIDE EACH TYPE FOLDER)");
            _layout = new ComboBox
            {
                DropDownStyle = ComboBoxStyle.DropDownList,
                FlatStyle = FlatStyle.Flat,
                Width = 260,
                Location = new Point(24, y)
            };
            Theme.StyleInput(_layout);
            foreach (var p in LayoutPresets) _layout.Items.Add(p.Label);
            int idx = Array.FindIndex(LayoutPresets, p => p.Template == (_settings.FolderTemplate ?? "{game}"));
            _layout.SelectedIndex = idx >= 0 ? idx : 0;
            page.Controls.Add(_layout);
            y += 46;

            // ----- danger zone -----
            page.Controls.Add(new Label
            {
                Text = "DANGER ZONE",
                Font = Theme.HeaderFont,
                ForeColor = Theme.Error,
                AutoSize = true,
                Location = new Point(24, y)
            });
            y += 22;
            _deleteOriginals = new CheckBox();
            Check(_deleteOriginals, "Delete original Steam screenshots after import",
                _settings.DeleteOriginals, Theme.Error);
            _deleteOriginals.CheckedChanged += OnDeleteOriginalsToggled;
            y += 26;
            Hint("Removes each original from Steam once it is safely backed up. Files go to the\n" +
                 "Windows Recycle Bin (recoverable), not permanent deletion.");
            y += 44;
            int backupBottom = y;

            // ----- tab bar -----
            var tabBar = new Panel { Dock = DockStyle.Top, Height = 46, BackColor = Theme.Panel };
            var tabEdge = new Panel { Dock = DockStyle.Top, Height = 1, BackColor = Theme.PanelEdge };
            _tabGeneral = MakeTab("General", 8, 132);
            _tabBackup = MakeTab("Backup Configuration", 8 + 132, 200);
            _indicator = new Panel { Height = 2, BackColor = Theme.Accent };
            tabBar.Controls.Add(_tabGeneral);
            tabBar.Controls.Add(_tabBackup);
            tabBar.Controls.Add(_indicator);
            _tabGeneral.Click += (s, e) => SelectTab(0);
            _tabBackup.Click += (s, e) => SelectTab(1);

            // Invisible, non-visual control that soaks up the window's initial focus so
            // nothing (e.g. the Appearance dropdown) opens looking pre-selected.
            var focusCatcher = new Panel { TabStop = true, Size = new Size(0, 0), TabIndex = 0 };

            // ----- assemble (Fill first, then outer bars) -----
            Controls.Add(focusCatcher);
            Controls.Add(contentHost);
            Controls.Add(footerEdge);
            Controls.Add(footer);
            Controls.Add(tabEdge);
            Controls.Add(tabBar);

            AcceptButton = apply;
            CancelButton = close;

            // Size the window so the taller page shows without scrolling.
            int content = Math.Max(generalBottom, backupBottom);
            ClientSize = new Size(577, 46 + 1 + content + 1 + 60);

            SelectTab(0);
            ActiveControl = focusCatcher;
        }

        private Button MakeTab(string text, int x, int width)
        {
            var b = new Button
            {
                Text = text,
                Size = new Size(width, 44),
                Location = new Point(x, 0),
                FlatStyle = FlatStyle.Flat,
                BackColor = Theme.Panel,
                ForeColor = Theme.TextDim,
                Font = Theme.BaseFont,
                Cursor = Cursors.Hand,
                TextAlign = ContentAlignment.MiddleCenter
            };
            b.FlatAppearance.BorderSize = 0;
            b.FlatAppearance.MouseOverBackColor = Theme.Selection;
            b.FlatAppearance.MouseDownBackColor = Theme.Selection;
            b.UseVisualStyleBackColor = false;
            return b;
        }

        private void SelectTab(int i)
        {
            _generalPage.Visible = i == 0;
            _backupPage.Visible = i == 1;
            _tabGeneral.ForeColor = i == 0 ? Theme.Text : Theme.TextDim;
            _tabBackup.ForeColor = i == 1 ? Theme.Text : Theme.TextDim;
            var active = i == 0 ? _tabGeneral : _tabBackup;
            _indicator.Bounds = new Rectangle(active.Left, 44, active.Width, 2);
        }

        private void Browse()
        {
            using var dlg = new FolderBrowserDialog
            {
                Description = "Choose the folder where screenshots will be backed up.",
                UseDescriptionForTitle = true,
                SelectedPath = _dest.Text
            };
            if (dlg.ShowDialog(this) == DialogResult.OK)
                _dest.Text = dlg.SelectedPath;
        }

        private void BrowseHighRes()
        {
            using var dlg = new FolderBrowserDialog
            {
                Description = "Choose the folder where Steam saves external (high-resolution) copies.",
                UseDescriptionForTitle = true,
                SelectedPath = _highResFolder.Text
            };
            if (dlg.ShowDialog(this) == DialogResult.OK)
                _highResFolder.Text = dlg.SelectedPath;
        }

        // Strict confirmation the moment the dangerous box is ticked; reverts on decline.
        private void OnDeleteOriginalsToggled(object sender, EventArgs e)
        {
            if (_suppressDangerPrompt || !_deleteOriginals.Checked) return;

            // Two explicit confirmations for this irreversible-feeling, dangerous choice.
            bool ok =
                MessageDialog.AskYesNo(
                    "DANGER \u2014 delete originals after import\n\n" +
                    "With this on, every original Steam screenshot is removed from Steam as soon as it " +
                    "is safely backed up, and Steam will no longer show those screenshots.\n\n" +
                    "Deleted files go to the Windows Recycle Bin, so you can recover them until it is " +
                    "emptied \u2014 but this still changes Steam's own screenshot folder.\n\n" +
                    "Are you sure you want to enable this?",
                    "Enable a Dangerous Setting")
                &&
                MessageDialog.AskYesNo(
                    "Final confirmation.\n\n" +
                    "You are enabling automatic deletion of your original Steam screenshots after they " +
                    "are backed up. This changes Steam's own files.\n\n" +
                    "Do you explicitly confirm you want this?",
                    "Are You Absolutely Sure?");

            if (!ok)
            {
                _suppressDangerPrompt = true;
                _deleteOriginals.Checked = false;
                _suppressDangerPrompt = false;
            }
        }

        private void RunPurgeOriginals()
        {
            var engine = _app.Engine;
            ProgressWindow.Run(this, "Deleting Originals\u2026",
                "Sending imported originals to the Recycle Bin\u2026",
                progress => engine.PurgeImportedOriginals(progress));
        }

        private void RunMarkdownRebuild()
        {
            var engine = _app.Engine;
            ProgressWindow.Run(this, "Generating Index\u2026",
                "Writing _Screenshot_Log.md files\u2026",
                progress => engine.RebuildMarkdownIndex(progress));
        }

        private void RunMarkdownDelete()
        {
            var engine = _app.Engine;
            ProgressWindow.Run(this, "Deleting Index\u2026",
                "Sending _Screenshot_Log.md files to the Recycle Bin\u2026",
                progress => engine.DeleteMarkdownIndexes(progress));
        }

        private bool TypeBackupExists(ScreenshotType type)
        {
            try
            {
                string root = Path.Combine(_settings.Destination,
                    type == ScreenshotType.Standard ? BackupEngine.StandardFolder : BackupEngine.HighResFolder);
                return Directory.Exists(root) &&
                       Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories).Any();
            }
            catch { return false; }
        }

        private void RunTypeDelete(ScreenshotType type)
        {
            var engine = _app.Engine;
            ProgressWindow.Run(this, "Deleting Backups\u2026",
                $"Sending {BackupEngine.TypeLabel(type)} backups to the Recycle Bin\u2026",
                progress => engine.DeleteTypeBackups(type));
        }

        private void SaveChanges()
        {
            if (!_standard.Checked && !_highRes.Checked)
            {
                MessageDialog.Info("At least one screenshot type must stay enabled.");
                return;
            }

            string newDest = _dest.Text.Trim();
            if (newDest.Length == 0)
            {
                MessageDialog.Info("Please choose a backup folder.");
                return;
            }

            string oldDest = _settings.Destination;
            string oldTemplate = _settings.FolderTemplate ?? "{game}";
            string newTemplate = LayoutPresets[_layout.SelectedIndex].Template;

            string oldOverride = _settings.HighResFolderOverride ?? "";
            string newOverride = _highResFolder.Text.Trim();

            bool destChanged = !string.Equals(oldDest, newDest, StringComparison.OrdinalIgnoreCase);
            bool typesChanged = _standard.Checked != _settings.BackupStandard ||
                                _highRes.Checked != _settings.BackupHighRes;
            bool overrideChanged = !string.Equals(oldOverride, newOverride, StringComparison.OrdinalIgnoreCase);
            bool templateChanged = oldTemplate != newTemplate;

            // Types being switched off (captured before the settings are overwritten) so
            // we can offer to clean up the now-unwanted backups.
            bool standardTurnedOff = _settings.BackupStandard && !_standard.Checked;
            bool highResTurnedOff = _settings.BackupHighRes && !_highRes.Checked;

            // Snapshot of every remaining field's old value, for the audit log below.
            bool oldStandard = _settings.BackupStandard;
            bool oldHighRes = _settings.BackupHighRes;
            bool oldAutoRestore = _settings.AutoRestore;
            bool oldShowNotifications = _settings.ShowNotifications;
            bool oldMarkdownIndex = _settings.GenerateMarkdownIndex;
            bool oldPreviewImport = _settings.PreviewBeforeImport;
            bool oldDeleteOriginals = _settings.DeleteOriginals;
            bool oldOfflineMode = _settings.OfflineMode;
            ThemeMode oldTheme = _settings.Theme;
            bool oldAutoStart = _app.IsAutoStartEnabled;

            _settings.BackupStandard = _standard.Checked;
            _settings.BackupHighRes = _highRes.Checked;
            _settings.HighResFolderOverride = newOverride.Length == 0 ? null : newOverride;
            _settings.AutoRestore = _autoRestore.Checked;
            _settings.ShowNotifications = _showNotifications.Checked;
            bool markdownNewlyEnabled = _markdownIndex.Checked && !_settings.GenerateMarkdownIndex;
            bool markdownTurnedOff = _settings.GenerateMarkdownIndex && !_markdownIndex.Checked;
            _settings.GenerateMarkdownIndex = _markdownIndex.Checked;
            _settings.PreviewBeforeImport = _previewImport.Checked;
            _settings.OfflineMode = _offlineMode.Checked;
            bool deleteOriginalsNewlyEnabled = _deleteOriginals.Checked && !_settings.DeleteOriginals;
            _settings.DeleteOriginals = _deleteOriginals.Checked;
            _settings.Theme = _theme.SelectedIndex switch
            {
                1 => ThemeMode.Light,
                2 => ThemeMode.System,
                _ => ThemeMode.Dark
            };
            _app.SetAutoStartEnabled(_autoStart.Checked);

            // Destination move (with optional migration) happens before the template
            // change so a reorganization only ever runs in one place.
            if (destChanged)
            {
                bool hasExisting = BackupExists(oldDest);
                bool migrate = hasExisting && MessageDialog.AskYesNo(
                    "Move your existing backup files to the new location?\n\n" +
                    "Choosing No leaves the old files where they are and re-copies " +
                    "everything from Steam into the new folder on the next scan.",
                    "Migrate Existing Backup");
                _settings.Destination = newDest;
                if (migrate) RunMigration(oldDest, newDest);
            }

            if (templateChanged)
            {
                // Only adopt the new layout if there's nothing to move, or the user
                // confirms moving existing files to match it. Otherwise the setting
                // and the on-disk layout would disagree, breaking later scans (they'd
                // compute the new-layout path for an existing file, not find it there,
                // and wrongly treat it as missing).
                bool applyTemplate = true;
                if (BackupExists(_settings.Destination))
                {
                    var plan = _app.Engine.PlanReorganize(oldTemplate, newTemplate);
                    if (plan.Count > 0)
                    {
                        applyTemplate = PreviewWindow.Confirm(
                            "Preview Reorganization",
                            $"{plan.Count} file{(plan.Count == 1 ? "" : "s")} will be moved to match the new layout:",
                            plan, "Reorganize");
                        if (applyTemplate)
                        {
                            var engine = _app.Engine;
                            ProgressWindow.Run(this, "Reorganizing Backup\u2026", "Moving files into the new folder layout\u2026",
                                progress => engine.ReorganizeLayout(oldTemplate, newTemplate));
                        }
                    }
                }
                if (applyTemplate)
                {
                    _settings.FolderTemplate = newTemplate;
                }
                else
                {
                    // Declined the reorganize: the on-disk layout (and the setting) stay
                    // on the old template, so the dropdown needs to match or it would show
                    // a layout that was never actually applied.
                    int oldIdx = Array.FindIndex(LayoutPresets, p => p.Template == oldTemplate);
                    _layout.SelectedIndex = oldIdx >= 0 ? oldIdx : 0;
                }
            }

            LogSettingChange("Backup Folder", oldDest, _settings.Destination);
            LogSettingChange("Folder Layout", oldTemplate, _settings.FolderTemplate);
            LogSettingChange("High-Resolution Folder Override",
                oldOverride.Length == 0 ? "(auto-detect)" : oldOverride,
                _settings.HighResFolderOverride ?? "(auto-detect)");
            LogSettingChange("Backup Standard Screenshots", oldStandard, _settings.BackupStandard);
            LogSettingChange("Backup High-Resolution Screenshots", oldHighRes, _settings.BackupHighRes);
            LogSettingChange("Automatic Restore", oldAutoRestore, _settings.AutoRestore);
            LogSettingChange("Show Notifications", oldShowNotifications, _settings.ShowNotifications);
            LogSettingChange("Markdown Index", oldMarkdownIndex, _settings.GenerateMarkdownIndex);
            LogSettingChange("Preview Before Import", oldPreviewImport, _settings.PreviewBeforeImport);
            LogSettingChange("Delete Originals", oldDeleteOriginals, _settings.DeleteOriginals);
            LogSettingChange("Offline Mode", oldOfflineMode, _settings.OfflineMode);
            LogSettingChange("Theme", oldTheme, _settings.Theme);
            LogSettingChange("Start With Windows", oldAutoStart, _autoStart.Checked);

            _settings.Save();
            Theme.SetMode(_settings.Theme);
            _app.OnSettingsChanged(destChanged || typesChanged || overrideChanged);

            // Turned a screenshot type off: offer to remove its now-unwanted backups.
            if (standardTurnedOff && TypeBackupExists(ScreenshotType.Standard) && MessageDialog.AskYesNo(
                    "You turned off Standard screenshots. Delete the existing Standard backup files?\n\n" +
                    "They will be sent to the Windows Recycle Bin (recoverable). Choose No to keep them.",
                    "Delete Standard Backups?"))
                RunTypeDelete(ScreenshotType.Standard);

            if (highResTurnedOff && TypeBackupExists(ScreenshotType.HighRes) && MessageDialog.AskYesNo(
                    "You turned off High-resolution screenshots. Delete the existing High Resolution backup files?\n\n" +
                    "They will be sent to the Windows Recycle Bin (recoverable). Choose No to keep them.",
                    "Delete High Resolution Backups?"))
                RunTypeDelete(ScreenshotType.HighRes);

            // Newly enabled markdown index: offer to generate it for existing folders.
            if (markdownNewlyEnabled && BackupExists(_settings.Destination) && MessageDialog.AskYesNo(
                    "Generate the Markdown index for your existing backup folders now?\n\n" +
                    "This writes a _Screenshot_Log.md into each game folder covering the screenshots " +
                    "already backed up. Choose No to only index screenshots backed up from here on.",
                    "Generate Index for Existing Folders?"))
            {
                RunMarkdownRebuild();
            }

            // Turned the markdown index off: offer to remove the files it left behind.
            if (markdownTurnedOff && _app.Engine.MarkdownIndexExists() && MessageDialog.AskYesNo(
                    "You turned off the Markdown index. Delete the existing _Screenshot_Log.md files?\n\n" +
                    "They will be sent to the Windows Recycle Bin (recoverable). Choose No to leave them in place.",
                    "Delete Markdown Index Files?"))
            {
                RunMarkdownDelete();
            }

            // Newly enabled: offer to clean up originals that were already imported.
            if (deleteOriginalsNewlyEnabled && MessageDialog.AskYesNo(
                    "Also delete originals that were already imported?\n\n" +
                    "This sends every original that already has a backup to the Recycle Bin now. " +
                    "Choose No to only delete originals of screenshots imported from here on.",
                    "Apply to Already-Imported Screenshots?"))
            {
                RunPurgeOriginals();
            }
        }

        // Audit trail for Settings: one info-level log line per field that actually
        // changed, naming the field and its old and new values. Silent when unchanged.
        private static void LogSettingChange<T>(string name, T oldValue, T newValue)
        {
            if (!Equals(oldValue, newValue))
                Logger.Log($"Setting '{name}' changed to '{newValue}' (was '{oldValue}')");
        }

        private static bool BackupExists(string dest)
        {
            try
            {
                return Directory.Exists(dest) && new[]
                    { BackupEngine.StandardFolder, BackupEngine.HighResFolder }
                    .Any(t => Directory.Exists(Path.Combine(dest, t)) &&
                              Directory.EnumerateFiles(Path.Combine(dest, t), "*",
                                  SearchOption.AllDirectories).Any());
            }
            catch { return false; }
        }

        private void RunMigration(string oldDest, string newDest)
        {
            var engine = _app.Engine;
            ProgressWindow.Run(this, "Migrating Backup\u2026", "Moving files\u2026",
                progress => engine.MoveBackup(oldDest, newDest, progress));
        }
    }
}
