using System;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace SteamScreenshotBackup
{
    // Shared modal "doing something in the background" dialog: shows a themed message
    // that can be updated with (done, total) progress, and closes itself when the work
    // finishes. Used by every long-running delete/rebuild/migrate action in the app so
    // that boilerplate progress-form wiring lives in exactly one place.
    internal static class ProgressWindow
    {
        public static void Run(IWin32Window owner, string title, string initialText, Action<Action<int, int>> work)
        {
            var progress = new Form
            {
                Text = title,
                FormBorderStyle = FormBorderStyle.FixedDialog,
                ControlBox = false,
                StartPosition = FormStartPosition.CenterParent,
                ClientSize = new Size(380, 96)
            };
            Theme.ApplyWindow(progress);
            var label = new Label
            {
                Text = initialText,
                Dock = DockStyle.Fill,
                TextAlign = ContentAlignment.MiddleCenter,
                ForeColor = Theme.Text
            };
            progress.Controls.Add(label);

            progress.Shown += (s, e) => Task.Run(() =>
            {
                try
                {
                    work((done, total) =>
                    {
                        try { progress.BeginInvoke(new Action(() => label.Text = $"{initialText} {done} / {total}")); }
                        catch { }
                    });
                }
                catch (Exception ex) { Logger.Error($"{title} failed: {ex.Message}"); }
                finally { try { progress.BeginInvoke(new Action(progress.Close)); } catch { } }
            });

            if (owner != null) progress.ShowDialog(owner);
            else progress.ShowDialog();
        }
    }
}
