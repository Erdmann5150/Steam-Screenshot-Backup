using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace SteamScreenshotBackup
{
    // Edits the persistent appid -> game name cache (appnames.json) so users can fix
    // delisted or non-Steam games without touching the file in a text editor.
    internal class GameNamesWindow : Form
    {
        private readonly AppNameResolver _resolver;
        private readonly DataGridView _grid;
        private readonly HashSet<string> _unresolvedIds = new HashSet<string>();

        public GameNamesWindow(BackupEngine engine)
        {
            _resolver = engine.Resolver;
            var unresolved = engine.FindUnresolvedGameFolders();

            Text = "Game Names \u2014 Steam Screenshot Backup";
            StartPosition = FormStartPosition.CenterParent;
            Size = new Size(560, 480);
            MinimumSize = new Size(460, 320);
            AutoScaleMode = AutoScaleMode.Dpi;
            Theme.ApplyWindow(this);

            var intro = new Label
            {
                Text = unresolved.Count == 0
                    ? "Fix names for delisted or non-Steam games. Installed games are named\n" +
                      "straight from Steam and do not need entries here."
                    : $"{unresolved.Count} game folder{(unresolved.Count == 1 ? "" : "s")} could not be " +
                      "named automatically (highlighted below). Click \"Open Folder\" to view its\n" +
                      "screenshots, then type the game's name.",
                Dock = DockStyle.Top,
                Height = 48,
                Padding = new Padding(14, 8, 14, 0),
                ForeColor = unresolved.Count == 0 ? Theme.TextDim : Theme.Warning,
                BackColor = Theme.Panel,
                Font = Theme.SmallFont
            };

            _grid = new DataGridView
            {
                Dock = DockStyle.Fill,
                AllowUserToAddRows = true,
                AllowUserToDeleteRows = true,
                AllowUserToResizeRows = false,
                RowHeadersVisible = false,
                AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill,
                BackgroundColor = Theme.Background,
                BorderStyle = BorderStyle.None,
                GridColor = Theme.PanelEdge,
                EnableHeadersVisualStyles = false,
                ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.DisableResizing,
                ColumnHeadersHeight = 32
            };
            _grid.ColumnHeadersDefaultCellStyle.BackColor = Theme.Panel;
            _grid.ColumnHeadersDefaultCellStyle.ForeColor = Theme.TextDim;
            _grid.ColumnHeadersDefaultCellStyle.Font = Theme.HeaderFont;
            _grid.ColumnHeadersDefaultCellStyle.SelectionBackColor = Theme.Panel;
            _grid.DefaultCellStyle.BackColor = Theme.Background;
            _grid.DefaultCellStyle.ForeColor = Theme.Text;
            _grid.DefaultCellStyle.SelectionBackColor = Theme.Selection;
            _grid.DefaultCellStyle.SelectionForeColor = Theme.Text;
            _grid.AlternatingRowsDefaultCellStyle.BackColor = Theme.RowAlt;
            _grid.AlternatingRowsDefaultCellStyle.SelectionBackColor = Theme.Selection;
            _grid.AlternatingRowsDefaultCellStyle.SelectionForeColor = Theme.Text;
            Theme.ApplyScrollbars(_grid);

            var colId = new DataGridViewTextBoxColumn { HeaderText = "App ID", FillWeight = 26 };
            var colName = new DataGridViewTextBoxColumn { HeaderText = "Game Name", FillWeight = 54 };
            _grid.Columns.Add(colId);
            _grid.Columns.Add(colName);

            if (unresolved.Count > 0)
            {
                var colFolder = new DataGridViewButtonColumn
                {
                    HeaderText = "",
                    UseColumnTextForButtonValue = false,
                    FlatStyle = FlatStyle.Flat,
                    AutoSizeMode = DataGridViewAutoSizeColumnMode.None,
                    Width = 100
                };
                colFolder.DefaultCellStyle.BackColor = Theme.Panel;
                colFolder.DefaultCellStyle.ForeColor = Theme.Text;
                colFolder.DefaultCellStyle.SelectionBackColor = Theme.Panel;
                colFolder.DefaultCellStyle.SelectionForeColor = Theme.Text;
                _grid.Columns.Add(colFolder);
                int folderColIndex = colFolder.Index;

                foreach (var (appid, folderPath) in unresolved)
                {
                    _unresolvedIds.Add(appid);
                    int i = _grid.Rows.Add(appid, "", "Open Folder");
                    var row = _grid.Rows[i];
                    row.Tag = folderPath;
                    row.DefaultCellStyle.ForeColor = Theme.Warning;
                }

                _grid.CellContentClick += (s, e) =>
                {
                    if (e.RowIndex < 0 || e.ColumnIndex != folderColIndex) return;
                    if (_grid.Rows[e.RowIndex].Tag is string path) OpenFolder(path);
                };
            }

            foreach (var kv in _resolver.GetCachedNames())
                _grid.Rows.Add(kv.Key, kv.Value);

            var footer = new Panel { Dock = DockStyle.Bottom, Height = 56, BackColor = Theme.Panel };
            var footerEdge = new Panel { Dock = DockStyle.Bottom, Height = 1, BackColor = Theme.PanelEdge };

            var remove = new Button { Text = "Remove Selected", Size = new Size(140, 32), Location = new Point(14, 12) };
            Theme.StyleButton(remove);
            remove.Click += (s, e) =>
            {
                foreach (DataGridViewRow row in _grid.SelectedRows.Cast<DataGridViewRow>().ToList())
                    if (!row.IsNewRow) _grid.Rows.Remove(row);
            };
            footer.Controls.Add(remove);

            var openFile = new Button
                { Text = "Open Tracking File", Size = new Size(140, 32), Location = new Point(164, 12) };
            Theme.StyleButton(openFile);
            openFile.Click += (s, e) => OpenTrackingFile();
            footer.Controls.Add(openFile);

            var close = new Button
            {
                Text = "Close",
                Size = new Size(96, 32),
                DialogResult = DialogResult.Cancel,
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            close.Location = new Point(footer.Width - 96 - 14, 12);
            Theme.StyleButton(close);
            footer.Controls.Add(close);

            var save = new Button
            {
                Text = "Save",
                Size = new Size(96, 32),
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            save.Location = new Point(footer.Width - 96 - 14 - 96 - 10, 12);
            Theme.StyleButton(save, primary: true);
            save.Click += (s, e) => SaveChanges();
            footer.Controls.Add(save);

            Controls.Add(_grid);
            Controls.Add(intro);
            Controls.Add(footerEdge);
            Controls.Add(footer);
            CancelButton = close;
        }

        private void OpenFolder(string path)
        {
            try { Process.Start(new ProcessStartInfo("explorer.exe", $"\"{path}\"") { UseShellExecute = true }); }
            catch (Exception ex) { Logger.Error("Could not open folder: " + ex.Message); }
        }

        private void OpenTrackingFile()
        {
            string path = _resolver.CacheFilePath;
            try
            {
                if (!File.Exists(path))
                {
                    MessageDialog.Info("No tracking file has been written yet.");
                    return;
                }
                Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
            }
            catch (Exception ex)
            {
                Logger.Error("Could not open tracking file: " + ex.Message);
                try { Process.Start("explorer.exe", $"/select,\"{path}\""); } catch { }
            }
        }

        private void SaveChanges()
        {
            var edited = new Dictionary<string, string>();
            foreach (DataGridViewRow row in _grid.Rows)
            {
                if (row.IsNewRow) continue;
                string id = (row.Cells[0].Value?.ToString() ?? "").Trim();
                string name = (row.Cells[1].Value?.ToString() ?? "").Trim();
                if (id.Length == 0 && name.Length == 0) continue;
                if (name.Length == 0 && _unresolvedIds.Contains(id)) continue;   // not identified yet
                if (!ulong.TryParse(id, out _))
                {
                    MessageDialog.Info($"\"{id}\" is not a valid App ID (numbers only).");
                    return;
                }
                if (name.Length == 0)
                {
                    MessageDialog.Info($"App ID {id} needs a game name.");
                    return;
                }
                edited[id] = name;
            }

            var current = _resolver.GetCachedNames();
            foreach (var key in current.Keys.Where(k => !edited.ContainsKey(k)))
                _resolver.RemoveCachedName(key);
            foreach (var kv in edited)
                if (!current.TryGetValue(kv.Key, out var old) || old != kv.Value)
                    _resolver.SetCachedName(kv.Key, kv.Value);

            Logger.Log("Game name list updated.");
            DialogResult = DialogResult.OK;
            Close();
        }
    }
}
