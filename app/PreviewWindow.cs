using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;

namespace SteamScreenshotBackup
{
    // A reusable "preview the changes" modal: shows a list of Original -> Proposed
    // mappings with Proceed / Cancel. Used before batch imports and layout
    // reorganizations so the user can see exactly what will happen first.
    internal class PreviewWindow : Form
    {
        private readonly IReadOnlyList<(string From, string To)> _rows;
        private readonly ListView _list;

        // Returns true if the user chose Proceed.
        public static bool Confirm(string title, string description,
            IReadOnlyList<(string From, string To)> rows, string proceedText = "Proceed")
        {
            using var w = new PreviewWindow(title, description, rows, proceedText);
            return w.ShowDialog() == DialogResult.OK;
        }

        private PreviewWindow(string title, string description,
            IReadOnlyList<(string From, string To)> rows, string proceedText)
        {
            _rows = rows;

            Text = title;
            StartPosition = FormStartPosition.CenterScreen;
            Size = new Size(960, 600);
            MinimumSize = new Size(640, 400);
            AutoScaleMode = AutoScaleMode.Dpi;
            Theme.ApplyWindow(this);

            var top = new Panel { Dock = DockStyle.Top, Height = 44, BackColor = Theme.Panel };
            top.Controls.Add(new Label
            {
                Text = description,
                ForeColor = Theme.Text,
                Font = Theme.HeaderFont,
                AutoSize = false,
                Dock = DockStyle.Fill,
                TextAlign = ContentAlignment.MiddleLeft,
                Padding = new Padding(14, 0, 14, 0)
            });
            var topEdge = new Panel { Dock = DockStyle.Top, Height = 1, BackColor = Theme.PanelEdge };

            _list = new ListView
            {
                Dock = DockStyle.Fill,
                View = View.Details,
                FullRowSelect = true,
                HeaderStyle = ColumnHeaderStyle.Nonclickable,
                BorderStyle = BorderStyle.None,
                OwnerDraw = true,
                BackColor = Theme.Background,
                ForeColor = Theme.Text,
                SmallImageList = new ImageList { ImageSize = new Size(1, 26) }   // taller rows
            };
            _list.Columns.Add("Original", 460);
            _list.Columns.Add("Proposed backup path", 460);
            _list.DrawColumnHeader += DrawHeader;
            _list.DrawSubItem += DrawSubItem;
            Theme.ApplyScrollbars(_list);
            Theme.EnableDoubleBuffer(_list);

            _list.BeginUpdate();
            var items = new ListViewItem[rows.Count];
            for (int i = 0; i < rows.Count; i++)
                items[i] = new ListViewItem(new[] { rows[i].From, rows[i].To });
            _list.Items.AddRange(items);
            _list.EndUpdate();

            var bottom = new Panel { Dock = DockStyle.Bottom, Height = 56, BackColor = Theme.Panel };
            var bottomEdge = new Panel { Dock = DockStyle.Bottom, Height = 1, BackColor = Theme.PanelEdge };

            var count = new Label
            {
                Text = $"{rows.Count} item{(rows.Count == 1 ? "" : "s")}",
                ForeColor = Theme.TextDim,
                Font = Theme.SmallFont,
                AutoSize = true,
                Location = new Point(16, 20)
            };
            bottom.Controls.Add(count);

            var cancel = new Button
            {
                Text = "Cancel",
                Size = new Size(100, 32),
                DialogResult = DialogResult.Cancel,
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            cancel.Location = new Point(bottom.Width - cancel.Width - 14, 12);
            Theme.StyleButton(cancel);
            bottom.Controls.Add(cancel);

            var proceed = new Button
            {
                Text = proceedText,
                Size = new Size(140, 32),
                DialogResult = DialogResult.OK,
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            proceed.Location = new Point(bottom.Width - cancel.Width - 14 - proceed.Width - 10, 12);
            Theme.StyleButton(proceed, primary: true);
            bottom.Controls.Add(proceed);

            Controls.Add(_list);
            Controls.Add(topEdge);
            Controls.Add(top);
            Controls.Add(bottomEdge);
            Controls.Add(bottom);

            AcceptButton = proceed;
            CancelButton = cancel;
            _list.Resize += (s, e) => FitColumns();
            FitColumns();
        }

        private void FitColumns()
        {
            int w = Math.Max(120, (_list.ClientSize.Width - 2) / 2);
            _list.Columns[0].Width = w;
            _list.Columns[1].Width = _list.ClientSize.Width - w;
        }

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

            // A faint divider under every row makes it easy to tell where one file's
            // mapping ends and the next begins, even between two same-shade rows.
            using (var edge = new Pen(Theme.PanelEdge))
                e.Graphics.DrawLine(edge, e.Bounds.Left, e.Bounds.Bottom - 1, e.Bounds.Right, e.Bounds.Bottom - 1);

            Color fg = e.ColumnIndex == 0 ? Theme.TextDim : Theme.Text;
            var r = new Rectangle(e.Bounds.X + 12, e.Bounds.Y, e.Bounds.Width - 20, e.Bounds.Height);
            TextRenderer.DrawText(e.Graphics, e.SubItem.Text, Font, r, fg,
                TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.PathEllipsis);
        }
    }
}
