using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace SteamScreenshotBackup
{
    // Maintains a "_Screenshot_Log.md" alongside the backed-up screenshots in each
    // folder: a running, chronological markdown index that embeds every shot with a
    // relative path and a per-day date header. Handy for Obsidian / markdown journals.
    //
    // Writes are serialized (screenshots can land in rapid succession) and the last
    // date written per file is cached so we don't re-scan the whole log every append.
    internal class MarkdownIndex
    {
        private const string FileName = "_Screenshot_Log.md";

        private readonly object _lock = new object();
        private readonly Dictionary<string, string> _lastDate =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);   // md path -> yyyy-MM-dd

        // Appends the just-copied image to the markdown log in its own folder. The image
        // name is used for both the alt text and the (relative) link so it resolves from
        // the log's location. Angle brackets keep names with spaces valid markdown.
        public void Append(string imagePath, DateTime captured)
        {
            try
            {
                string dir = Path.GetDirectoryName(imagePath);
                if (dir == null) return;
                string mdPath = Path.Combine(dir, FileName);
                string name = Path.GetFileName(imagePath);
                string alt = Path.GetFileNameWithoutExtension(imagePath);
                string day = captured.ToString("yyyy-MM-dd");

                lock (_lock)
                {
                    if (!_lastDate.TryGetValue(mdPath, out string last))
                    {
                        last = ReadLastDate(mdPath);   // survive restarts / pre-existing logs
                        _lastDate[mdPath] = last;
                    }

                    var sb = new StringBuilder();
                    if (!File.Exists(mdPath))
                        sb.Append("# Screenshots\n\n");
                    if (!string.Equals(last, day, StringComparison.Ordinal))
                    {
                        sb.Append("### ").Append(day).Append("\n\n");
                        _lastDate[mdPath] = day;
                    }
                    sb.Append("![").Append(alt).Append("](<").Append(name).Append(">)\n\n");

                    File.AppendAllText(mdPath, sb.ToString());
                }
            }
            catch (Exception ex)
            {
                Logger.Warn($"Could not update {FileName}: {ex.Message}");
            }
        }

        // Rebuilds a folder's log from scratch: every backup image in the folder, in
        // the order given (callers pass them sorted by capture time), grouped under
        // per-day headers. Overwrites any existing log so it can't accumulate duplicates.
        public void Rebuild(string dir, IReadOnlyList<(string Name, DateTime Captured)> images)
        {
            try
            {
                string mdPath = Path.Combine(dir, FileName);
                var sb = new StringBuilder();
                sb.Append("# Screenshots\n\n");
                string lastDay = null;
                foreach (var (name, captured) in images)
                {
                    string day = captured.ToString("yyyy-MM-dd");
                    if (!string.Equals(day, lastDay, StringComparison.Ordinal))
                    {
                        sb.Append("### ").Append(day).Append("\n\n");
                        lastDay = day;
                    }
                    string alt = Path.GetFileNameWithoutExtension(name);
                    sb.Append("![").Append(alt).Append("](<").Append(name).Append(">)\n\n");
                }

                lock (_lock)
                {
                    File.WriteAllText(mdPath, sb.ToString());
                    _lastDate[mdPath] = lastDay;   // keep the append cache consistent
                }
            }
            catch (Exception ex)
            {
                Logger.Warn($"Could not rebuild {FileName}: {ex.Message}");
            }
        }

        // The date of the last "### YYYY-MM-DD" header already in the file, or null.
        private static string ReadLastDate(string mdPath)
        {
            if (!File.Exists(mdPath)) return null;
            string last = null;
            try
            {
                foreach (var line in File.ReadLines(mdPath))
                    if (line.StartsWith("### ", StringComparison.Ordinal))
                        last = line.Substring(4).Trim();
            }
            catch { }
            return last;
        }
    }
}
