using System;
using System.Linq;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace SteamScreenshotBackup
{
    internal static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);   // legacy-cache recovery
            Application.SetHighDpiMode(HighDpiMode.SystemAware);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            // Last-resort safety net: log anything that would otherwise crash the app
            // silently (or with just the default .NET error dialog) with no record of
            // why. Individual methods already catch what they can; this is the catch-all
            // for whatever slips through, on the UI thread or a background one.
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException += (s, e) =>
                Logger.Error("Unhandled UI exception: " + e.Exception);
            AppDomain.CurrentDomain.UnhandledException += (s, e) =>
                Logger.Error("Unhandled exception (fatal=" + e.IsTerminating + "): " + e.ExceptionObject);

            // The installer launches with --show so the main window opens after setup,
            // instead of the app slipping silently into the tray.
            bool showUi = args.Any(a => string.Equals(a, "--show", StringComparison.OrdinalIgnoreCase));

            var settings = Settings.Load();
            Theme.SetMode(settings.Theme);

            using var mutex = new Mutex(true, "SteamScreenshotBackup_SingleInstance", out bool createdNew);
            if (!createdNew)
            {
                MessageDialog.Info("Steam Screenshot Backup is already running (check the system tray).");
                return;
            }

            var ctx = new TrayContext(settings);
            if (showUi) ctx.OpenMainWindow();
            Application.Run(ctx);
        }
    }
}
