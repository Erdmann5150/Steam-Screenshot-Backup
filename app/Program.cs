using System;
using System.Threading;
using System.Windows.Forms;

namespace SteamScreenshotBackup
{
    internal static class Program
    {
        [STAThread]
        static void Main()
        {
            using var mutex = new Mutex(true, "SteamScreenshotBackup_SingleInstance", out bool createdNew);
            if (!createdNew)
            {
                MessageBox.Show("Steam Screenshot Backup is already running (check the system tray).",
                    "Steam Screenshot Backup", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            Application.SetHighDpiMode(HighDpiMode.SystemAware);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new TrayContext());
        }
    }
}
