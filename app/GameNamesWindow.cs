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

        public GameNamesWindow(AppNameResolver resolver)
        {
            _resolver = resolver;

            Text = "Game Names \u2014 Steam Screenshot Backup";
            StartPosition = FormStartPosition.CenterParent;
            Size = new Size(560, 480);
            MinimumSize = new Size(460, 320);
            AutoScaleMode = AutoScaleMode.Dpi;
            Theme.ApplyWindow(this);

            var intro = new Label
            {
                Text = "Fix names for delisted or non-Steam games. Installed games are named\n" +
                       "straight from Steam and do not need entries here.",
                Dock = DockStyle.Top,
                Height = 48,
                Padding = new Padding(14, 8, 14, 0),
                ForeColor = Theme.TextDim,
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

            var colId = new DataGridViewTextBoxColumn { HeaderText = "App ID", FillWeight = 30 };
            var colName = new DataGridViewTextBoxColumn { HeaderText = "Game Name", FillWeight = 70 };
            _grid.Columns.Add(colId);
            _grid.Columns.Add(colName);

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

            var cancel = new Button
            {
                Text = "Cancel",
                Size = new Size(96, 32),
                DialogResult = DialogResult.Cancel,
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            cancel.Location = new Point(footer.Width - 96 - 14, 12);
            Theme.StyleButton(cancel);
            footer.Controls.Add(cancel);

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
            CancelButton = cancel;
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
