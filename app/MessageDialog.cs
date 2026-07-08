using System;
using System.Drawing;
using System.Windows.Forms;

namespace SteamScreenshotBackup
{
    // Themed replacement for MessageBox so every dialog in the app looks the same.
    internal class MessageDialog : Form
    {
        public static void Info(string text, string title = "Steam Screenshot Backup")
            => Show(text, title, Theme.Accent, "OK", null);

        public static void Fail(string text, string title = "Steam Screenshot Backup")
            => Show(text, title, Theme.Error, "OK", null);

        public static bool AskYesNo(string text, string title = "Steam Screenshot Backup")
            => Show(text, title, Theme.Accent, "Yes", "No") == DialogResult.OK;

        private static DialogResult Show(string text, string title, Color stripe,
            string okText, string cancelText)
        {
            using var dlg = new MessageDialog(text, title, stripe, okText, cancelText);
            return dlg.ShowDialog();
        }

        private MessageDialog(string text, string title, Color stripe, string okText, string cancelText)
        {
            Text = title;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleMode = AutoScaleMode.Dpi;
            Theme.ApplyWindow(this);

            // Measure the wrapped text at a fixed width so word-wrap and any explicit
            // line breaks agree (AutoSize + MaximumSize together produce ragged spacing).
            const int TextWidth = 380;
            const TextFormatFlags MeasureFlags =
                TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl;
            Size measured = TextRenderer.MeasureText(
                text, Font, new Size(TextWidth, int.MaxValue), MeasureFlags);

            var body = new Label
            {
                Text = text,
                AutoSize = false,
                Size = new Size(Math.Min(TextWidth, measured.Width), measured.Height),
                Location = new Point(28, 24),
                ForeColor = Theme.Text,
                UseMnemonic = false
            };
            Controls.Add(body);

            // Colored accent stripe down the left edge ties the dialog to its severity.
            var strip = new Panel { BackColor = stripe, Location = new Point(0, 0), Width = 4 };
            Controls.Add(strip);

            var ok = new Button { Text = okText, Size = new Size(96, 32), DialogResult = DialogResult.OK };
            Theme.StyleButton(ok, primary: true);
            Controls.Add(ok);
            AcceptButton = ok;

            Button cancel = null;
            if (cancelText != null)
            {
                cancel = new Button { Text = cancelText, Size = new Size(96, 32), DialogResult = DialogResult.Cancel };
                Theme.StyleButton(cancel);
                Controls.Add(cancel);
                CancelButton = cancel;
            }

            int contentBottom = body.Bottom + 24;
            ClientSize = new Size(Math.Max(body.Right + 28, 320), contentBottom + 56);
            strip.Height = ClientSize.Height;

            int x = ClientSize.Width - 28 - ok.Width;
            if (cancel != null)
            {
                cancel.Location = new Point(x, contentBottom + 12);
                x -= ok.Width + 10;
            }
            ok.Location = new Point(x, contentBottom + 12);
        }
    }
}
