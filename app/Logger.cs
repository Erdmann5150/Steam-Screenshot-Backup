using System;
using System.IO;

namespace SteamScreenshotBackup
{
    internal static class Logger
    {
        private static readonly object Lock = new object();
        private static string LogFile => Path.Combine(Settings.Dir, "app.log");

        public static void Log(string message)
        {
            try
            {
                lock (Lock)
                {
                    Directory.CreateDirectory(Settings.Dir);
                    var f = new FileInfo(LogFile);
                    if (f.Exists && f.Length > 1_000_000) f.Delete();   // simple size cap
                    File.AppendAllText(LogFile,
                        $"{DateTime.Now:yyyy-MM-dd HH:mm:ss}  {message}{Environment.NewLine}");
                }
            }
            catch { }
        }
    }
}
