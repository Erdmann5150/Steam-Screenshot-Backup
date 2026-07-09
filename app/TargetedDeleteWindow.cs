using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;

namespace SteamScreenshotBackup
{
    // Granular deletion: a checkbox tree (Backup type -> Game -> File) so the user can
    // pick exactly which backup files to remove, with a file count on every node and a
    // mandatory count+size confirmation before anything is sent to the Recycle Bin.
    internal class TargetedDeleteWindow : Form
    {
        private readonly BackupEngine _engine;
        private readonly TreeView _tree;
        private readonly Label _summary;
        private readonly Button _deleteBtn;
        private bool _cascading;

        public static void ShowWindow(BackupEngine engine, IWin32Window owner)
        {
            using var w = new TargetedDeleteWindow(engine);
            w.ShowDialog(owner);
        }

        private TargetedDeleteWindow(BackupEngine engine)
        {
            _engine = engine;

            Text = "Delete specific files/folders";
            StartPosition = FormStartPosition.CenterParent;
            Size = new Size(640, 560);
            MinimumSize = new Size(480, 380);
            AutoScaleMode = AutoScaleMode.Dpi;
            Theme.ApplyWindow(this);

            var top = new Panel { Dock = DockStyle.Top, Height = 44, BackColor = Theme.Panel };
            top.Controls.Add(new Label
            {
                Text = "Choose backup files to delete",
                Font = Theme.HeaderFont,
                ForeColor = Theme.Text,
                AutoSize = true,
                Location = new Point(14, 14)
            });
            var topEdge = new Panel { Dock = DockStyle.Top, Height = 1, BackColor = Theme.PanelEdge };

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

            var bottom = new Panel { Dock = DockStyle.Bottom, Height = 56, BackColor = Theme.Panel };
            var bottomEdge = new Panel { Dock = DockStyle.Bottom, Height = 1, BackColor = Theme.PanelEdge };

            _summary = new Label
            {
                Text = "Nothing selected",
                Font = Theme.SmallFont,
                ForeColor = Theme.TextDim,
                AutoSize = true,
                Location = new Point(14, 20)
            };
            bottom.Controls.Add(_summary);

            var close = new Button
            {
                Text = "Close",
                Size = new Size(96, 32),
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            close.Location = new Point(bottom.Width - close.Width - 14, 12);
            Theme.StyleButton(close);
            close.Click += (s, e) => Close();
            bottom.Controls.Add(close);

            _deleteBtn = new Button
            {
                Text = "Delete selected",
                Size = new Size(140, 32),
                Anchor = AnchorStyles.Top | AnchorStyles.Right,
                Enabled = false
            };
            _deleteBtn.Location = new Point(bottom.Width - close.Width - 14 - _deleteBtn.Width - 10, 12);
            Theme.StyleButton(_deleteBtn, primary: true);
            _deleteBtn.Click += (s, e) => DeleteSelected();
            bottom.Controls.Add(_deleteBtn);

            Controls.Add(_tree);
            Controls.Add(topEdge);
            Controls.Add(top);
            Controls.Add(bottomEdge);
            Controls.Add(bottom);
            CancelButton = close;

            Populate();
        }

        // ------------------------------------------------------------- populate

        private void Populate()
        {
            _tree.BeginUpdate();
            _tree.Nodes.Clear();

            var byType = _engine.GetBackupTree();
            foreach (var type in new[] { ScreenshotType.Standard, ScreenshotType.HighRes })
            {
                if (!byType.TryGetValue(type, out var byGame) || byGame.Count == 0) continue;

                int typeFiles = 0;
                var typeNode = new TreeNode { Tag = null };
                foreach (var kv in byGame)
                {
                    var gameNode = new TreeNode($"{kv.Key}  ({kv.Value.Count})") { Tag = null };
                    foreach (var file in kv.Value)
                        gameNode.Nodes.Add(new TreeNode(
                            $"{file.Name}  ({MainWindow.FormatBytes(file.Size)})") { Tag = file });
                    typeNode.Nodes.Add(gameNode);
                    typeFiles += kv.Value.Count;
                }
                typeNode.Text = $"{BackupEngine.TypeLabel(type)}  ({typeFiles})";
                _tree.Nodes.Add(typeNode);
            }
            _tree.EndUpdate();

            UpdateSummary();
        }

        // ------------------------------------------------------------- checking

        private void OnAfterCheck(object sender, TreeViewEventArgs e)
        {
            if (_cascading) return;
            if (e.Action == TreeViewAction.Unknown) return;   // programmatic change
            _cascading = true;
            CheckAllChildren(e.Node, e.Node.Checked);
            _cascading = false;
            UpdateSummary();
        }

        private static void CheckAllChildren(TreeNode node, bool value)
        {
            foreach (TreeNode child in node.Nodes)
            {
                child.Checked = value;
                CheckAllChildren(child, value);
            }
        }

        private List<BackupEngine.BackupFileEntry> CheckedFiles()
        {
            var list = new List<BackupEngine.BackupFileEntry>();
            void Walk(TreeNodeCollection nodes)
            {
                foreach (TreeNode node in nodes)
                {
                    if (node.Checked && node.Tag is BackupEngine.BackupFileEntry f) list.Add(f);
                    Walk(node.Nodes);
                }
            }
            Walk(_tree.Nodes);
            return list;
        }

        private void UpdateSummary()
        {
            var files = CheckedFiles();
            long bytes = 0;
            foreach (var f in files) bytes += f.Size;
            int folders = CheckedFolderCount();

            _summary.Text = files.Count == 0
                ? "Nothing selected"
                : $"{folders} folder{(folders == 1 ? "" : "s")}, " +
                  $"{files.Count} file{(files.Count == 1 ? "" : "s")} selected  \u00B7  {MainWindow.FormatBytes(bytes)}";
            _deleteBtn.Enabled = files.Count > 0;
        }

        // A "folder" (per-game node) counts as selected only when every file under it
        // is checked \u2014 that's the case that actually means "this whole folder goes".
        private int CheckedFolderCount()
        {
            int count = 0;
            foreach (TreeNode typeNode in _tree.Nodes)
                foreach (TreeNode gameNode in typeNode.Nodes)
                    if (gameNode.Nodes.Count > 0 && AllChecked(gameNode))
                        count++;
            return count;
        }

        private static bool AllChecked(TreeNode node)
        {
            foreach (TreeNode child in node.Nodes)
                if (!child.Checked) return false;
            return true;
        }

        // ------------------------------------------------------------- deleting

        private void DeleteSelected()
        {
            var files = CheckedFiles();
            if (files.Count == 0) return;

            long bytes = 0;
            foreach (var f in files) bytes += f.Size;
            if (!MessageDialog.ConfirmDeletion(
                    $"Delete {files.Count} selected backup file{(files.Count == 1 ? "" : "s")}?",
                    files.Count, bytes)) return;

            var paths = files.ConvertAll(f => f.Path);
            var engine = _engine;
            ProgressWindow.Run(this, "Deleting selected files\u2026", "Sending selected files to the Recycle Bin\u2026",
                progress => engine.DeleteFiles(paths, progress));

            Populate();
        }
    }
}
