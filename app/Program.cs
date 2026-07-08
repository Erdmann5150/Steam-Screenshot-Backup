using System;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace SteamScreenshotBackup
{
    internal static class Program
    {
        [STAThread]
        static void Main()
        {
            Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);   // legacy-cache recovery
            Application.SetHighDpiMode(HighDpiMode.SystemAware);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            var settings = Settings.Load();
            Theme.SetMode(settings.Theme);

            using var mutex = new Mutex(true, "SteamScreenshotBackup_SingleInstance", out bool createdNew);
            if (!createdNew)
            {
                MessageDialog.Info("Steam Screenshot Backup is already running (check the system tray).");
                return;
            }

            Application.Run(new TrayContext(settings));
        }
    }
}
