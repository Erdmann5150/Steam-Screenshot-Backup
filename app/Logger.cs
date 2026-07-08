using System;
using System.Collections.Generic;
using System.IO;

namespace SteamScreenshotBackup
{
    internal enum LogLevel { Info, Backup, Restore, Deletion, Warning, Error }

    internal class LogEntry
    {
        public DateTime Time { get; }
        public LogLevel Level { get; }
        public string Message { get; }
        public string FilePath { get; }   // the file involved, when the entry is about one

        public LogEntry(LogLevel level, string message, string filePath = null)
        {
            Time = DateTime.Now;
            Level = level;
            Message = message;
            FilePath = filePath;
        }
    }

    // Application-wide log: keeps a bounded in-memory list for the activity window,
    // and appends to a size-rotated file so disk usage stays capped no matter how
    // long the app runs.
    internal static class Logger
    {
        private const int MaxEntries = 1000;            // in-memory cap for the UI
        private const long MaxFileBytes = 1_000_000;    // rotate after ~1 MB
        private const int KeptArchives = 3;             // app.log.1 .. app.log.3

        private static readonly object Lock = new object();
        private static readonly List<LogEntry> Entries = new List<LogEntry>();

        public static string LogFilePath => Path.Combine(Settings.Dir, "app.log");

        // Raised on whatever thread logged the entry; UI subscribers must marshal.
        public static event Action<LogEntry> Added;

        public static void Log(string message) => Write(LogLevel.Info, message);
        public static void Warn(string message) => Write(LogLevel.Warning, message);
        public static void Error(string message) => Write(LogLevel.Error, message);
        public static void Backup(string message, string filePath) => Write(LogLevel.Backup, message, filePath);
        public static void Restore(string message, string filePath) => Write(LogLevel.Restore, message, filePath);
        public static void Deletion(string message, string filePath) => Write(LogLevel.Deletion, message, filePath);

        public static LogEntry[] Snapshot()
        {
            lock (Lock) return Entries.ToArray();
        }

        private static void Write(LogLevel level, string message, string filePath = null)
        {
            var entry = new LogEntry(level, message, filePath);
            lock (Lock)
            {
                Entries.Add(entry);
                if (Entries.Count > MaxEntries) Entries.RemoveRange(0, Entries.Count - MaxEntries);

                try
                {
                    Directory.CreateDirectory(Settings.Dir);
                    RotateIfNeeded();
                    File.AppendAllText(LogFilePath,
                        $"{entry.Time:yyyy-MM-dd HH:mm:ss}  [{level,-8}]  {message}{Environment.NewLine}");
                }
                catch { }   // logging must never take the app down
            }
            Added?.Invoke(entry);
        }

        // app.log -> app.log.1 -> app.log.2 -> app.log.3 -> deleted.
        private static void RotateIfNeeded()
        {
            var f = new FileInfo(LogFilePath);
            if (!f.Exists || f.Length < MaxFileBytes) return;

            string oldest = LogFilePath + "." + KeptArchives;
            if (File.Exists(oldest)) File.Delete(oldest);
            for (int i = KeptArchives - 1; i >= 1; i--)
            {
                string from = LogFilePath + "." + i;
                if (File.Exists(from)) File.Move(from, LogFilePath + "." + (i + 1));
            }
            File.Move(LogFilePath, LogFilePath + ".1");
        }
    }
}
