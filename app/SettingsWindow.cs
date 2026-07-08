using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace SteamScreenshotBackup
{
    // All app configuration in one place. Changes are applied when Save is clicked;
    // destination and layout changes offer to migrate/reorganize existing backups.
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
        private readonly CheckBox _standard, _highRes, _autoStart;
        private readonly ComboBox _layout, _theme;

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
            ClientSize = new Size(560, 566);
            Theme.ApplyWindow(this);

            int y = 20;
            Label Section(string text)
            {
                var l = new Label
                {
                    Text = text,
                    Font = Theme.HeaderFont,
                    ForeColor = Theme.TextDim,
                    AutoSize = true,
                    Location = new Point(24, y)
                };
                Controls.Add(l);
                y += 22;
                return l;
            }

            // ----- backup folder -----
            Section("BACKUP FOLDER");
            _dest = new TextBox
            {
                Text = _settings.Destination,
                Location = new Point(24, y),
                Width = 408,
                BorderStyle = BorderStyle.FixedSingle
            };
            Theme.StyleInput(_dest);
            var browse = new Button { Text = "Browse\u2026", Size = new Size(92, _dest.Height + 2) };
            browse.Location = new Point(440, y - 1);
            Theme.StyleButton(browse);
            browse.Click += (s, e) => Browse();
            Controls.Add(_dest);
            Controls.Add(browse);
            y += 44;

            // ----- what to back up -----
            Section("WHAT TO BACK UP");
            _standard = new CheckBox
            {
                Text = "Standard screenshots (Steam's compressed library copies)",
                Checked = _settings.BackupStandard,
                AutoSize = true,
                Location = new Point(24, y),
                ForeColor = Theme.Text
            };
            Controls.Add(_standard);
            y += 28;
            _highRes = new CheckBox
            {
                Text = "High-resolution screenshots (Steam's \"save an external copy\" files)",
                Checked = _settings.BackupHighRes,
                AutoSize = true,
                Location = new Point(24, y),
                ForeColor = Theme.Text
            };
            Controls.Add(_highRes);
            y += 30;

            // Manual high-resolution folder \u2014 used when Steam's config doesn't reveal
            // one (or to add an extra location). Placeholder shows the auto-detected path.
            string detected = _app.Engine.AutoDetectedHighResFolder;
            var hrCaption = new Label
            {
                Text = detected != null
                    ? "High-resolution folder (auto-detected; set only to use a different one):"
                    : "High-resolution folder (not auto-detected \u2014 set it here if you use external copies):",
                Font = Theme.SmallFont,
                ForeColor = Theme.TextDim,
                AutoSize = true,
                Location = new Point(42, y)
            };
            Controls.Add(hrCaption);
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
            var hrBrowse = new Button { Text = "Browse\u2026", Size = new Size(92, _highResFolder.Height + 2) };
            hrBrowse.Location = new Point(440, y - 1);
            Theme.StyleButton(hrBrowse);
            hrBrowse.Click += (s, e) => BrowseHighRes();
            Controls.Add(_highResFolder);
            Controls.Add(hrBrowse);
            y += 42;

            // ----- folder layout -----
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
            Controls.Add(_layout);
            y += 44;

            // ----- appearance / startup -----
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
            Controls.Add(_theme);
            y += 44;

            Section("STARTUP");
            _autoStart = new CheckBox
            {
                Text = "Start automatically when I sign in to Windows",
                Checked = _app.IsAutoStartEnabled,
                AutoSize = true,
                Location = new Point(24, y),
                ForeColor = Theme.Text
            };
            Controls.Add(_autoStart);

            // ----- footer -----
            var footer = new Panel { Dock = DockStyle.Bottom, Height = 60, BackColor = Theme.Panel };
            var footerEdge = new Panel { Dock = DockStyle.Bottom, Height = 1, BackColor = Theme.PanelEdge };

            var uninstall = new Button { Text = "Uninstall\u2026", Size = new Size(110, 32), Location = new Point(14, 13) };
            Theme.StyleButton(uninstall);
            uninstall.ForeColor = Theme.Error;
            uninstall.Click += (s, e) => { Close(); _app.Uninstall(); };
            footer.Controls.Add(uninstall);

            var cancel = new Button
            {
                Text = "Cancel",
                Size = new Size(96, 32),
                DialogResult = DialogResult.Cancel,
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            cancel.Location = new Point(footer.Width - 96 - 14, 13);
            Theme.StyleButton(cancel);
            footer.Controls.Add(cancel);

            var save = new Button
            {
                Text = "Save",
                Size = new Size(96, 32),
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            save.Location = new Point(footer.Width - 96 - 14 - 96 - 10, 13);
            Theme.StyleButton(save, primary: true);
            save.Click += (s, e) => SaveChanges();
            footer.Controls.Add(save);

            Controls.Add(footerEdge);
            Controls.Add(footer);
            AcceptButton = save;
            CancelButton = cancel;
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

            _settings.BackupStandard = _standard.Checked;
            _settings.BackupHighRes = _highRes.Checked;
            _settings.HighResFolderOverride = newOverride.Length == 0 ? null : newOverride;
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
                    "Migrate existing backup");
                _settings.Destination = newDest;
                if (migrate) RunMigration(oldDest, newDest);
            }

            if (templateChanged)
            {
                _settings.FolderTemplate = newTemplate;
                if (BackupExists(_settings.Destination) && MessageDialog.AskYesNo(
                        "Reorganize the existing backup into the new folder layout now?\n\n" +
                        "Choosing No applies the layout to new screenshots only, and the " +
                        "next scan may re-copy older ones into the new layout.",
                        "Reorganize backup"))
                {
                    var engine = _app.Engine;
                    Task.Run(() => engine.ReorganizeLayout(oldTemplate, newTemplate));
                }
            }

            _settings.Save();
            Theme.SetMode(_settings.Theme);
            _app.OnSettingsChanged(destChanged || typesChanged || overrideChanged);
            DialogResult = DialogResult.OK;
            Close();
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
            var progress = new Form
            {
                Text = "Migrating backup\u2026",
                FormBorderStyle = FormBorderStyle.FixedDialog,
                ControlBox = false,
                StartPosition = FormStartPosition.CenterParent,
                ClientSize = new Size(380, 96)
            };
            Theme.ApplyWindow(progress);
            var label = new Label
            {
                Text = "Moving files\u2026",
                AutoSize = false,
                Dock = DockStyle.Fill,
                TextAlign = ContentAlignment.MiddleCenter,
                ForeColor = Theme.Text
            };
            progress.Controls.Add(label);

            var engine = _app.Engine;
            progress.Shown += (s, e) => Task.Run(() =>
            {
                try
                {
                    engine.MoveBackup(oldDest, newDest, (done, total) =>
                    {
                        try
                        {
                            progress.BeginInvoke(new Action(() =>
                                label.Text = $"Moving files\u2026 {done} / {total}"));
                        }
                        catch { }
                    });
                }
                catch (Exception ex)
                {
                    Logger.Error("Backup migration failed: " + ex.Message);
                }
                finally
                {
                    try { progress.BeginInvoke(new Action(progress.Close)); } catch { }
                }
            });
            progress.ShowDialog(this);
        }
    }
}
