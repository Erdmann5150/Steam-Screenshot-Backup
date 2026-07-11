using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace SteamScreenshotBackup
{
    // Finds screenshots that exist in Steam but are missing from the backup (deleted
    // from it, or not yet copied) and lets the user re-sync them selectively, grouped
    // by game \u2014 the manual complement to automatic restore.
    internal class ResyncWindow : Form
    {
        private static ResyncWindow _open;

        private readonly BackupEngine _engine;
        private readonly TreeView _tree;
        private readonly Label _summary;
        private readonly Button _resync, _selectAll, _rescan;
        private bool _cascading;
        private bool _busy;

        public static void ShowWindow(BackupEngine engine)
        {
            if (_open == null || _open.IsDisposed)
            {
                _open = new ResyncWindow(engine);
                _open.Show();
            }
            if (_open.WindowState == FormWindowState.Minimized)
                _open.WindowState = FormWindowState.Normal;
            _open.Activate();
            _open.BringToFront();
        }

        private ResyncWindow(BackupEngine engine)
        {
            _engine = engine;

            Text = "Re-Sync Missing Screenshots";
            StartPosition = FormStartPosition.CenterScreen;
            Size = new Size(640, 560);
            MinimumSize = new Size(520, 400);
            AutoScaleMode = AutoScaleMode.Dpi;
            Theme.ApplyWindow(this);

            // ----- header -----
            var top = new Panel { Dock = DockStyle.Top, Height = 58, BackColor = Theme.Panel };
            top.Controls.Add(new Label
            {
                Text = "Screenshots in Steam That Aren't in Your Backup",
                Font = Theme.HeaderFont,
                ForeColor = Theme.Text,
                AutoSize = true,
                Location = new Point(14, 10)
            });
            _summary = new Label
            {
                Text = "Scanning\u2026",
                Font = Theme.SmallFont,
                ForeColor = Theme.TextDim,
                AutoSize = true,
                Location = new Point(14, 32)
            };
            top.Controls.Add(_summary);
            var topEdge = new Panel { Dock = DockStyle.Top, Height = 1, BackColor = Theme.PanelEdge };

            // ----- tree -----
            _tree = new TreeView
            {
                Dock = DockStyle.Fill,
                CheckBoxes = true,
                BackColor = Theme.Background,
                ForeColor = Theme.Text,
                BorderStyle = BorderStyle.None,
                HideSelection = true,
                ShowLines = true,
                ItemHeight = 22
            };
            _tree.AfterCheck += OnAfterCheck;
            Theme.ApplyScrollbars(_tree);

            // ----- bottom bar -----
            var bottom = new Panel { Dock = DockStyle.Bottom, Height = 56, BackColor = Theme.Panel };
            var bottomEdge = new Panel { Dock = DockStyle.Bottom, Height = 1, BackColor = Theme.PanelEdge };

            _selectAll = new Button { Text = "Select All", Size = new Size(96, 32), Location = new Point(14, 12) };
            Theme.StyleButton(_selectAll);
            _selectAll.Click += (s, e) => SetAllChecked(true);

            _rescan = new Button { Text = "Rescan", Size = new Size(88, 32), Location = new Point(118, 12) };
            Theme.StyleButton(_rescan);
            _rescan.Click += (s, e) => StartScan();

            var close = new Button
            {
                Text = "Close",
                Size = new Size(96, 32),
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            close.Location = new Point(bottom.Width - close.Width - 14, 12);
            Theme.StyleButton(close);
            close.Click += (s, e) => Close();

            _resync = new Button
            {
                Text = "Re-Sync Selected",
                Size = new Size(150, 32),
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            _resync.Location = new Point(bottom.Width - close.Width - 14 - _resync.Width - 10, 12);
            Theme.StyleButton(_resync, primary: true);
            _resync.Click += (s, e) => ResyncSelected();

            bottom.Controls.Add(_selectAll);
            bottom.Controls.Add(_rescan);
            bottom.Controls.Add(_resync);
            bottom.Controls.Add(close);

            Controls.Add(_tree);
            Controls.Add(topEdge);
            Controls.Add(top);
            Controls.Add(bottomEdge);
            Controls.Add(bottom);

            StartScan();
        }

        // ------------------------------------------------------------- scanning

        private void StartScan()
        {
            if (_busy) return;
            SetBusy(true);
            _summary.Text = "Scanning\u2026";
            _tree.Nodes.Clear();

            var engine = _engine;
            Task.Run(() =>
            {
                List<ResyncItem> missing;
                try { missing = engine.FindMissingFromBackup(); }
                catch (Exception ex) { Logger.Error("Re-sync scan failed: " + ex.Message); missing = new List<ResyncItem>(); }

                try
                {
                    if (!IsDisposed && IsHandleCreated)
                        BeginInvoke(new Action(() => Populate(missing)));
                }
                catch { }
            });
        }

        private void Populate(List<ResyncItem> missing)
        {
            _tree.BeginUpdate();
            _tree.Nodes.Clear();

            var byGame = missing
                .GroupBy(i => i.Game, StringComparer.OrdinalIgnoreCase)
                .OrderBy(g => g.Key, StringComparer.OrdinalIgnoreCase);

            foreach (var group in byGame)
            {
                var items = group.OrderBy(i => i.Timestamp).ToList();
                var parent = new TreeNode($"{group.Key}  ({items.Count})")
                    { Tag = null, BackColor = Theme.Panel, ForeColor = Theme.TextDim };
                for (int i = 0; i < items.Count; i++)
                {
                    var it = items[i];
                    parent.Nodes.Add(new TreeNode(
                        $"{it.DisplayName}   [{BackupEngine.TypeLabel(it.Type)}]")
                        { Tag = it, BackColor = i % 2 == 0 ? Theme.Background : Theme.RowAlt });
                }
                _tree.Nodes.Add(parent);
            }
            if (missing.Count <= 500) _tree.ExpandAll();   // show items; avoid huge expands
            _tree.EndUpdate();

            int games = byGame.Count();
            _summary.Text = missing.Count == 0
                ? "Your backup is in sync \u2014 nothing in Steam is missing from it."
                : $"{missing.Count} screenshot{(missing.Count == 1 ? "" : "s")} across " +
                  $"{games} game{(games == 1 ? "" : "s")} can be re-synced.";
            SetBusy(false);
        }

        // ------------------------------------------------------------- checking

        private void OnAfterCheck(object sender, TreeViewEventArgs e)
        {
            if (_cascading) return;
            if (e.Action == TreeViewAction.Unknown) return;   // programmatic change
            _cascading = true;
            // Parent toggles all its children.
            if (e.Node.Nodes.Count > 0)
                foreach (TreeNode child in e.Node.Nodes)
                    child.Checked = e.Node.Checked;
            _cascading = false;
            UpdateResyncButton();
        }

        private void SetAllChecked(bool value)
        {
            _cascading = true;
            foreach (TreeNode parent in _tree.Nodes)
            {
                parent.Checked = value;
                foreach (TreeNode child in parent.Nodes) child.Checked = value;
            }
            _cascading = false;
            UpdateResyncButton();
        }

        private List<ResyncItem> CheckedItems()
        {
            var list = new List<ResyncItem>();
            foreach (TreeNode parent in _tree.Nodes)
                foreach (TreeNode child in parent.Nodes)
                    if (child.Checked && child.Tag is ResyncItem it)
                        list.Add(it);
            return list;
        }

        private void UpdateResyncButton()
        {
            int n = CheckedItems().Count;
            _resync.Text = n > 0 ? $"Re-Sync Selected ({n})" : "Re-Sync Selected";
            _resync.Enabled = !_busy && n > 0;
        }

        // ------------------------------------------------------------- re-syncing

        private void ResyncSelected()
        {
            var items = CheckedItems();
            if (items.Count == 0) return;

            var progress = new Form
            {
                Text = "Re-Syncing\u2026",
                FormBorderStyle = FormBorderStyle.FixedDialog,
                ControlBox = false,
                StartPosition = FormStartPosition.CenterParent,
                ClientSize = new Size(380, 96)
            };
            Theme.ApplyWindow(progress);
            var label = new Label
            {
                Text = "Copying files\u2026",
                Dock = DockStyle.Fill,
                TextAlign = ContentAlignment.MiddleCenter,
                ForeColor = Theme.Text
            };
            progress.Controls.Add(label);

            var engine = _engine;
            progress.Shown += (s, e) => Task.Run(() =>
            {
                int copied = 0;
                try
                {
                    copied = engine.Resync(items, (done, total) =>
                    {
                        try { progress.BeginInvoke(new Action(() => label.Text = $"Copying files\u2026 {done} / {total}")); }
                        catch { }
                    });
                }
                catch (Exception ex) { Logger.Error("Re-sync failed: " + ex.Message); }
                finally
                {
                    try { progress.BeginInvoke(new Action(progress.Close)); } catch { }
                }
            });
            progress.ShowDialog(this);

            StartScan();   // refresh \u2014 synced items drop off the list
        }

        private void SetBusy(bool busy)
        {
            _busy = busy;
            _rescan.Enabled = !busy;
            _selectAll.Enabled = !busy;
            UpdateResyncButton();
        }
    }
}
