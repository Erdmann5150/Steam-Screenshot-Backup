using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;

namespace SteamScreenshotBackup
{
    internal enum LogLevel { Info, Backup, Restore, Deletion, Warning, Error, Update }

    internal class LogEntry
    {
        public DateTime Time { get; }
        public LogLevel Level { get; }
        public string Message { get; }
        public string FilePath { get; }   // the file involved, when the entry is about one

        public LogEntry(LogLevel level, string message, string filePath = null, DateTime? time = null)
        {
            Time = time ?? DateTime.Now;
            Level = level;
            Message = message;
            FilePath = filePath;
        }
    }

    // Application-wide log: keeps a bounded in-memory list for the activity window,
    // and appends to a size-rotated file so disk usage stays capped no matter how
    // long the app runs. On first use it loads the recent tail of the log file so the
    // activity window reflects prior sessions (not just the current one), keeping the
    // UI and the file in agreement.
    internal static class Logger
    {
        private const int MaxEntries = 1000;            // in-memory cap for the UI
        private const long MaxFileBytes = 1_000_000;    // rotate after ~1 MB
        private const int KeptArchives = 3;             // app.log.1 .. app.log.3

        private static readonly object Lock = new object();
        private static readonly List<LogEntry> Entries = new List<LogEntry>();
        private static readonly Regex LineRx =
            new Regex(@"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[([A-Za-z]+)\s*\]\s+(.*)$", RegexOptions.Compiled);
        private static bool _loaded;

        public static string LogFilePath => Path.Combine(Settings.Dir, "app.log");

        // Raised on whatever thread logged the entry; UI subscribers must marshal.
        public static event Action<LogEntry> Added;

        public static void Log(string message) => Write(LogLevel.Info, message);
        public static void Warn(string message) => Write(LogLevel.Warning, message);
        public static void Error(string message) => Write(LogLevel.Error, message);
        public static void Backup(string message, string filePath) => Write(LogLevel.Backup, message, filePath);
        public static void Restore(string message, string filePath) => Write(LogLevel.Restore, message, filePath);
        public static void Deletion(string message, string filePath) => Write(LogLevel.Deletion, message, filePath);
        public static void UpdateAvailable(string message) => Write(LogLevel.Update, message);

        public static LogEntry[] Snapshot()
        {
            lock (Lock)
            {
                EnsureLoaded();
                return Entries.ToArray();
            }
        }

        // Count and total size of the current log file plus its rotated archives, for
        // the "are you sure" prompt shown before ClearLogs actually deletes them.
        public static (int Count, long Bytes) PreviewLogFiles()
        {
            int count = 0; long bytes = 0;
            lock (Lock)
            {
                for (int i = 0; i <= KeptArchives; i++)
                {
                    string f = i == 0 ? LogFilePath : LogFilePath + "." + i;
                    if (!File.Exists(f)) continue;
                    count++;
                    try { bytes += new FileInfo(f).Length; } catch { }
                }
            }
            return (count, bytes);
        }

        // Sends the log file and its rotated archives to the Recycle Bin and clears the
        // in-memory activity list. A fresh log starts on the very next write.
        public static void ClearLogs()
        {
            lock (Lock)
            {
                Entries.Clear();
                for (int i = 0; i <= KeptArchives; i++)
                {
                    string f = i == 0 ? LogFilePath : LogFilePath + "." + i;
                    try { RecycleBin.Delete(f); } catch { }
                }
                _loaded = true;   // there's nothing left on disk to fold back in
            }
        }

        private static void Write(LogLevel level, string message, string filePath = null)
        {
            var entry = new LogEntry(level, message, filePath);
            lock (Lock)
            {
                EnsureLoaded();   // fold in the file's history before this session's first entry
                Entries.Add(entry);
                if (Entries.Count > MaxEntries) Entries.RemoveRange(0, Entries.Count - MaxEntries);

                try
                {
                    Directory.CreateDirectory(Settings.Dir);
                    RotateIfNeeded();
                    // The optional file path is stored after a tab so the activity window
                    // can still "reveal in Explorer" for entries reloaded from disk.
                    string tail = filePath != null ? "\t" + filePath : "";
                    File.AppendAllText(LogFilePath,
                        $"{entry.Time:yyyy-MM-dd HH:mm:ss}  [{level,-8}]  {message}{tail}{Environment.NewLine}");
                }
                catch { }   // logging must never take the app down
            }
            Added?.Invoke(entry);
        }

        // Reads the tail of the current log file back into memory so the activity window
        // shows history from earlier runs, matching what's on disk. Runs once, under Lock.
        private static void EnsureLoaded()
        {
            if (_loaded) return;
            _loaded = true;
            try
            {
                if (!File.Exists(LogFilePath)) return;
                string[] lines = File.ReadAllLines(LogFilePath);
                int start = Math.Max(0, lines.Length - MaxEntries);
                for (int i = start; i < lines.Length; i++)
                {
                    var m = LineRx.Match(lines[i]);
                    if (!m.Success) continue;   // skip blank / wrapped lines
                    if (!DateTime.TryParse(m.Groups[1].Value, out var t)) t = DateTime.Now;
                    if (!Enum.TryParse<LogLevel>(m.Groups[2].Value, ignoreCase: true, out var level))
                        level = LogLevel.Info;

                    // Split the optional tab-delimited file path back off the message.
                    string msg = m.Groups[3].Value;
                    string filePath = null;
                    int tab = msg.IndexOf('\t');
                    if (tab >= 0) { filePath = msg[(tab + 1)..]; msg = msg[..tab]; }
                    Entries.Add(new LogEntry(level, msg, filePath, t));
                }
            }
            catch { }
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
