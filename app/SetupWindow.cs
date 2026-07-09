using System;
using System.Drawing;
using System.Windows.Forms;

namespace SteamScreenshotBackup
{
    // First-run setup: one window that replaces the old chain of message boxes.
    internal class SetupWindow : Form
    {
        public string Destination => _dest.Text;
        public bool AutoStart => _autoStart.Checked;
        public bool BackupStandard => _standard.Checked;
        public bool BackupHighRes => _highRes.Checked;

        private readonly TextBox _dest;
        private readonly CheckBox _autoStart, _standard, _highRes;

        public SetupWindow(string defaultDestination, bool highResAvailable)
        {
            Text = "Steam Screenshot Backup";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(560, 484);
            Theme.ApplyWindow(this);

            // ----- header -----
            var header = new Panel { Dock = DockStyle.Top, Height = 92, BackColor = Theme.Panel };
            var logo = new PictureBox
            {
                Image = Theme.DrawCamera(48),
                Size = new Size(48, 48),
                Location = new Point(24, 22),
                SizeMode = PictureBoxSizeMode.Zoom,
                BackColor = Color.Transparent
            };
            header.Controls.Add(logo);
            header.Controls.Add(new Label
            {
                Text = "Steam Screenshot Backup",
                Font = Theme.TitleFont,
                ForeColor = Theme.Text,
                AutoSize = true,
                Location = new Point(86, 22),
                BackColor = Color.Transparent
            });
            header.Controls.Add(new Label
            {
                Text = "First-Time Setup",
                Font = Theme.SmallFont,
                ForeColor = Theme.Accent,
                AutoSize = true,
                Location = new Point(88, 52),
                BackColor = Color.Transparent
            });
            var headerEdge = new Panel { Dock = DockStyle.Top, Height = 1, BackColor = Theme.PanelEdge };

            // ----- body -----
            var intro = new Label
            {
                Text = "This app lives in the system tray and automatically copies every Steam " +
                       "screenshot you take into per-game folders with readable, sortable names. " +
                       "Left-click the tray icon at any time to see what it has been doing.",
                AutoSize = true,
                MaximumSize = new Size(512, 0),
                Location = new Point(24, 112),
                ForeColor = Theme.Text
            };

            var destLabel = new Label
            {
                Text = "BACKUP FOLDER",
                Font = Theme.HeaderFont,
                ForeColor = Theme.TextDim,
                AutoSize = true,
                Location = new Point(24, 192)
            };

            _dest = new TextBox
            {
                Text = defaultDestination,
                Location = new Point(24, 214),
                Width = 408,
                BorderStyle = BorderStyle.FixedSingle
            };
            Theme.StyleInput(_dest);

            var browse = new Button
            {
                Text = "Browse",
                Size = new Size(92, _dest.Height + 2),
                Location = new Point(440, 213)
            };
            Theme.StyleButton(browse);
            browse.Click += (s, e) => Browse();

            var typeLabel = new Label
            {
                Text = "WHAT TO BACK UP",
                Font = Theme.HeaderFont,
                ForeColor = Theme.TextDim,
                AutoSize = true,
                Location = new Point(24, 256)
            };

            _standard = new CheckBox
            {
                Text = "Standard screenshots (Steam's compressed library copies)",
                Checked = true,
                AutoSize = true,
                Location = new Point(24, 280),
                ForeColor = Theme.Text
            };

            _highRes = new CheckBox
            {
                Text = "High-resolution screenshots (Steam's \"save an external copy\" files)",
                Checked = highResAvailable,
                AutoSize = true,
                Location = new Point(24, 308),
                ForeColor = Theme.Text
            };

            var hrNote = new Label
            {
                Text = highResAvailable
                    ? "A high-resolution screenshot folder was found in your Steam settings."
                    : "Steam's external-copy option looks disabled; you can enable this later in Settings.",
                Font = Theme.SmallFont,
                ForeColor = Theme.TextDim,
                AutoSize = true,
                Location = new Point(42, 332)
            };

            _autoStart = new CheckBox
            {
                Text = "Start automatically when I sign in to Windows",
                Checked = true,
                AutoSize = true,
                Location = new Point(24, 366),
                ForeColor = Theme.Text
            };

            Controls.Add(intro);
            Controls.Add(destLabel);
            Controls.Add(_dest);
            Controls.Add(browse);
            Controls.Add(typeLabel);
            Controls.Add(_standard);
            Controls.Add(_highRes);
            Controls.Add(hrNote);
            Controls.Add(_autoStart);

            // ----- footer -----
            var footer = new Panel { Dock = DockStyle.Bottom, Height = 60, BackColor = Theme.Panel };
            var go = new Button
            {
                Text = "Start Backing Up",
                Size = new Size(160, 34),
                DialogResult = DialogResult.OK,
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            go.Location = new Point(footer.Width - go.Width - 24, 13);
            Theme.StyleButton(go, primary: true);
            footer.Controls.Add(go);
            var footerEdge = new Panel { Dock = DockStyle.Bottom, Height = 1, BackColor = Theme.PanelEdge };

            Controls.Add(headerEdge);
            Controls.Add(header);
            Controls.Add(footerEdge);
            Controls.Add(footer);

            AcceptButton = go;
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
    }
}
