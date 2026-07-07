using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using System.Threading;
using Microsoft.Win32;

namespace SteamScreenshotBackup
{
    internal class BackupEngine : IDisposable
    {
        private static readonly Regex ScreenshotName =
            new Regex(@"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_(\d+)(\.\w+)$", RegexOptions.Compiled);

        private readonly Func<string> _getDestination;
        private readonly string _userdata;
        private readonly AppNameResolver _resolver;
        private readonly BlockingCollection<string> _queue = new BlockingCollection<string>();
        private FileSystemWatcher _watcher;
        private volatile bool _paused;

        public event Action<string> Status;   // short line for the tray tooltip

        public bool Paused
        {
            get => _paused;
            set { _paused = value; if (_watcher != null) _watcher.EnableRaisingEvents = !value; }
        }

        public BackupEngine(Func<string> getDestination)
        {
            _getDestination = getDestination;

            string steamPath = FindSteamPath()
                ?? throw new InvalidOperationException("Steam installation not found in the registry.");
            _userdata = Path.Combine(steamPath, "userdata");
            _resolver = new AppNameResolver(steamPath);

            var worker = new Thread(ProcessQueue) { IsBackground = true, Name = "CopyWorker" };
            worker.Start();
        }

        private static string FindSteamPath()
        {
            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(@"Software\Valve\Steam");
                if (key?.GetValue("SteamPath") is string p)
                {
                    p = p.Replace('/', '\\');
                    if (Directory.Exists(p)) return p;
                }
            }
            catch { }
            return null;
        }

        public void StartWatching()
        {
            _watcher = new FileSystemWatcher(_userdata)
            {
                IncludeSubdirectories = true,
                InternalBufferSize = 64 * 1024,
                NotifyFilter = NotifyFilters.FileName | NotifyFilters.Size | NotifyFilters.LastWrite
            };
            _watcher.Created += (s, e) => Enqueue(e.FullPath);
            _watcher.Renamed += (s, e) => Enqueue(e.FullPath);
            _watcher.Error += (s, e) => Logger.Log("Watcher error: " + e.GetException()?.Message);
            _watcher.EnableRaisingEvents = !_paused;
        }

        private void Enqueue(string fullPath)
        {
            if (!_paused && IsManagedScreenshot(fullPath))
                _queue.Add(fullPath);
        }

        private static bool IsManagedScreenshot(string fullPath)
        {
            if (!ScreenshotName.IsMatch(Path.GetFileName(fullPath))) return false;
            string parent = Path.GetFileName(Path.GetDirectoryName(fullPath) ?? "");
            if (!parent.Equals("screenshots", StringComparison.OrdinalIgnoreCase)) return false; // excludes thumbnails\
            return fullPath.IndexOf(@"\760\remote\", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private void ProcessQueue()
        {
            foreach (var path in _queue.GetConsumingEnumerable())
            {
                try
                {
                    if (!WaitForStableFile(path)) continue;   // vanished, or never finished writing
                    string appid = Path.GetFileName(Path.GetDirectoryName(Path.GetDirectoryName(path)));
                    if (CopyOne(path, appid, out string game, out string destName))
                        Status?.Invoke($"{game}: {destName}");
                }
                catch (Exception ex)
                {
                    Logger.Log($"Copy failed for {path}: {ex.Message}");
                }
            }
        }

        private static bool WaitForStableFile(string path)
        {
            // Steam may still be writing when the event fires; wait until we can open it exclusively.
            for (int i = 0; i < 60; i++)   // up to ~15 s
            {
                try
                {
                    if (!File.Exists(path)) return false;
                    using var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.None);
                    if (fs.Length > 0) return true;
                }
                catch (IOException) { }
                Thread.Sleep(250);
            }
            Logger.Log("File never became exclusively readable, attempting copy anyway: " + path);
            return true;
        }

        private bool CopyOne(string src, string appid, out string game, out string destName)
        {
            game = _resolver.ResolveFolderName(appid);
            destName = ConvertName(Path.GetFileName(src));

            string destDir = Path.Combine(_getDestination(), game);
            Directory.CreateDirectory(destDir);
            string dest = Path.Combine(destDir, destName);

            if (File.Exists(dest) && new FileInfo(dest).Length == new FileInfo(src).Length)
                return false;   // already backed up

            File.Copy(src, dest, true);   // preserves the original timestamp
            return true;
        }

        // 20260706210532_1.jpg -> "2026-07-06 21.05.32.jpg"; same-second extras get " (2)", " (3)"...
        public static string ConvertName(string fileName)
        {
            var m = ScreenshotName.Match(fileName);
            if (!m.Success) return fileName;
            int n = int.Parse(m.Groups[7].Value);
            string suffix = n > 1 ? $" ({n})" : "";
            return $"{m.Groups[1].Value}-{m.Groups[2].Value}-{m.Groups[3].Value} " +
                   $"{m.Groups[4].Value}.{m.Groups[5].Value}.{m.Groups[6].Value}{suffix}{m.Groups[8].Value}";
        }

        public (int Games, int Copied, int Skipped) FullScan()
        {
            int copied = 0, skipped = 0;
            var games = new HashSet<string>();
            if (!Directory.Exists(_userdata)) return (0, 0, 0);

            foreach (var user in Directory.GetDirectories(_userdata))
            {
                string remote = Path.Combine(user, @"760\remote");
                if (!Directory.Exists(remote)) continue;

                foreach (var appDir in Directory.GetDirectories(remote))
                {
                    string srcDir = Path.Combine(appDir, "screenshots");
                    if (!Directory.Exists(srcDir)) continue;

                    string appid = Path.GetFileName(appDir);
                    foreach (var f in Directory.GetFiles(srcDir))   // top level only; skips thumbnails\
                    {
                        try
                        {
                            if (CopyOne(f, appid, out _, out _)) copied++; else skipped++;
                            games.Add(appid);
                        }
                        catch (Exception ex)
                        {
                            Logger.Log($"Copy failed for {f}: {ex.Message}");
                        }
                    }
                }
            }
            return (games.Count, copied, skipped);
        }

        public void Dispose()
        {
            _watcher?.Dispose();
            _queue.CompleteAdding();
        }
    }
}
