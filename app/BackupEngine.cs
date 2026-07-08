using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading;

namespace SteamScreenshotBackup
{
    internal enum ScreenshotType { Standard, HighRes }

    internal enum RunKind { Startup, Manual, Restore, DestinationChanged }

    // Result of one scan run: only what happened in THAT run.
    internal class RunResult
    {
        public int Copied;
        public int Skipped;
        public int OriginalsDeleted;
        public HashSet<string> GamesAffected = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    }

    // A source screenshot that isn't currently in the backup (deleted from the backup,
    // or never copied) and could be re-synced. Surfaced by the "Re-sync missing" window.
    internal class ResyncItem
    {
        public string Game;
        public ScreenshotType Type;
        public string SourcePath;
        public string DestPath;
        public DateTime Timestamp;
        public string DisplayName;   // the readable backup filename
        public long Size;
    }

    // The heart of the app. Watches both of Steam's screenshot stores, copies new
    // files into the backup structure, restores files deleted from the backup, and
    // survives the destination (e.g. a NAS share) going away temporarily.
    //
    // Backup layout:  <destination>\<Standard|High Resolution>\<template>\<file>
    // where <template> defaults to "{game}" and may use {game} {yyyy} {MM} {dd}.
    internal class BackupEngine : IDisposable
    {
        public const string StandardFolder = "Standard";
        public const string HighResFolder = "High Resolution";

        // Steam's managed store:  20260706210532_1.jpg
        private static readonly Regex StdName =
            new Regex(@"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_(\d+)(\.\w+)$", RegexOptions.Compiled);
        // Steam's external copies: 646570_20260707214723_1.png
        private static readonly Regex HighResSrcName =
            new Regex(@"^(\d+)_(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_(\d+)(\.\w+)$", RegexOptions.Compiled);
        // Our own backup naming:   2026-07-06 21.05.32 (2).jpg
        private static readonly Regex BackupName =
            new Regex(@"^\d{4}-\d{2}-\d{2} \d{2}\.\d{2}\.\d{2}( \(\d+\))?\.\w+$", RegexOptions.Compiled);

        private readonly Settings _settings;
        private readonly string _steamPath;
        private readonly string _userdata;
        private List<string> _highResFolders;
        private List<string> _autoHighResFolders = new List<string>();
        private readonly AppNameResolver _resolver;
        private readonly BlockingCollection<(ScreenshotType Type, string Path)> _queue
            = new BlockingCollection<(ScreenshotType, string)>();

        private FileSystemWatcher _stdWatcher;
        private readonly List<FileSystemWatcher> _highResWatchers = new List<FileSystemWatcher>();
        private FileSystemWatcher _destWatcher;
        private Timer _resyncTimer;
        private Timer _offlineRetryTimer;
        private Timer _unsuppressTimer;

        private volatile bool _paused;
        private volatile bool _offline;
        private volatile bool _resyncPending;
        private volatile bool _suppressDestEvents;   // during migrations/reorganizations
        private volatile bool _disposed;

        // Session statistics (since app start).
        private int _sessionFiles;
        private long _sessionBytes;
        public int SessionFiles => _sessionFiles;
        public long SessionBytes => Interlocked.Read(ref _sessionBytes);

        public bool Offline => _offline;

        // Debounced "something was deleted from the backup folder" signal.
        public event Action RestoreNeeded;
        public event Action DestinationOffline;
        public event Action DestinationOnline;

        public bool Paused
        {
            get => _paused;
            set
            {
                _paused = value;
                if (_stdWatcher != null) _stdWatcher.EnableRaisingEvents = !value;
                foreach (var w in _highResWatchers) w.EnableRaisingEvents = !value;
                if (_destWatcher != null) _destWatcher.EnableRaisingEvents = !value;
            }
        }

        public AppNameResolver Resolver => _resolver;

        public BackupEngine(Settings settings)
        {
            _settings = settings;

            _steamPath = SteamConfig.FindSteamPath()
                ?? throw new InvalidOperationException("Steam installation not found in the registry.");
            _userdata = Path.Combine(_steamPath, "userdata");
            _resolver = new AppNameResolver(_steamPath);
            RefreshHighResFolders();

            var worker = new Thread(ProcessQueue) { IsBackground = true, Name = "CopyWorker" };
            worker.Start();
        }

        // Rebuilds the high-resolution source list from Steam's config plus any manual
        // override the user set. Called at startup and whenever settings change.
        public void RefreshHighResFolders()
        {
            _autoHighResFolders = SteamConfig.FindHighResFolders(_steamPath);

            var combined = new List<string>(_autoHighResFolders);
            string manual = _settings.HighResFolderOverride;
            if (!string.IsNullOrWhiteSpace(manual) &&
                !combined.Contains(manual, StringComparer.OrdinalIgnoreCase))
                combined.Add(manual);

            _highResFolders = combined;
        }

        // True when a high-resolution source exists at all (auto-detected or manual).
        public bool HighResSourceAvailable => _highResFolders.Count > 0;

        // True only when Steam's config pointed us at a folder on its own.
        public bool HighResAutoDetected => _autoHighResFolders.Count > 0;

        // The first folder Steam's config pointed us at, for display in Settings.
        public string AutoDetectedHighResFolder =>
            _autoHighResFolders.Count > 0 ? _autoHighResFolders[0] : null;

        private string Destination => _settings.Destination;

        // ------------------------------------------------------------- watching

        public void StartWatching()
        {
            if (_settings.BackupStandard && Directory.Exists(_userdata))
            {
                _stdWatcher = new FileSystemWatcher(_userdata)
                {
                    IncludeSubdirectories = true,
                    InternalBufferSize = 64 * 1024,
                    NotifyFilter = NotifyFilters.FileName | NotifyFilters.Size | NotifyFilters.LastWrite
                };
                _stdWatcher.Created += (s, e) => EnqueueStandard(e.FullPath);
                _stdWatcher.Renamed += (s, e) => EnqueueStandard(e.FullPath);
                _stdWatcher.Error += (s, e) => Logger.Error("Steam watcher error: " + e.GetException()?.Message);
                _stdWatcher.EnableRaisingEvents = !_paused;
            }

            if (_settings.BackupHighRes)
            {
                foreach (var folder in _highResFolders.Where(Directory.Exists))
                {
                    var w = new FileSystemWatcher(folder)
                    {
                        NotifyFilter = NotifyFilters.FileName | NotifyFilters.Size | NotifyFilters.LastWrite
                    };
                    w.Created += (s, e) => EnqueueHighRes(e.FullPath);
                    w.Renamed += (s, e) => EnqueueHighRes(e.FullPath);
                    w.Error += (s, e) => Logger.Error("High-res watcher error: " + e.GetException()?.Message);
                    w.EnableRaisingEvents = !_paused;
                    _highResWatchers.Add(w);
                }
            }

            WatchDestination();
        }

        // Re-arms all source watchers, e.g. after screenshot types were toggled or
        // the destination moved.
        public void RestartWatching()
        {
            RefreshHighResFolders();   // pick up a newly-set manual folder
            _stdWatcher?.Dispose();
            _stdWatcher = null;
            foreach (var w in _highResWatchers) w.Dispose();
            _highResWatchers.Clear();
            StartWatching();
        }

        private void EnqueueStandard(string fullPath)
        {
            if (_paused || !_settings.BackupStandard) return;
            if (!StdName.IsMatch(Path.GetFileName(fullPath))) return;
            string parent = Path.GetFileName(Path.GetDirectoryName(fullPath) ?? "");
            if (!parent.Equals("screenshots", StringComparison.OrdinalIgnoreCase)) return;   // excludes thumbnails\
            if (fullPath.IndexOf(@"\760\remote\", StringComparison.OrdinalIgnoreCase) < 0) return;
            _queue.Add((ScreenshotType.Standard, fullPath));
        }

        private void EnqueueHighRes(string fullPath)
        {
            if (_paused || !_settings.BackupHighRes) return;
            if (!HighResSrcName.IsMatch(Path.GetFileName(fullPath))) return;
            _queue.Add((ScreenshotType.HighRes, fullPath));
        }

        private void ProcessQueue()
        {
            foreach (var item in _queue.GetConsumingEnumerable())
            {
                try
                {
                    WaitWhileOffline();
                    if (_disposed) return;
                    if (!WaitForStableFile(item.Path)) continue;   // vanished, or never finished writing

                    if (item.Type == ScreenshotType.Standard)
                    {
                        string appid = Path.GetFileName(Path.GetDirectoryName(Path.GetDirectoryName(item.Path)));
                        CopyOne(item.Path, appid, ScreenshotType.Standard, restore: false);
                    }
                    else
                    {
                        string appid = HighResSrcName.Match(Path.GetFileName(item.Path)).Groups[1].Value;
                        CopyOne(item.Path, appid, ScreenshotType.HighRes, restore: false);
                    }
                }
                catch (Exception ex)
                {
                    Logger.Error($"Copy failed for {item.Path}: {ex.Message}");
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
            Logger.Warn("File never became exclusively readable, attempting copy anyway: " + path);
            return true;
        }

        // -------------------------------------------------------------- copying

        // Converts a source name to our readable, sortable backup name and copies it
        // if it isn't already in the backup. The size check uses >= because metadata
        // tagging makes the backup copy slightly larger than the source.
        private bool CopyOne(string src, string appid, ScreenshotType type, bool restore,
            RunResult run = null)
        {
            string game = _resolver.ResolveFolderName(appid);
            var (ts, destName) = ConvertName(Path.GetFileName(src), type);
            if (destName == null) return false;

            string destDir = Path.Combine(Destination, TypeFolder(type), ExpandTemplate(game, ts));
            string dest = Path.Combine(destDir, destName);

            if (File.Exists(dest) && new FileInfo(dest).Length >= new FileInfo(src).Length)
            {
                if (run != null) run.Skipped++;
                return false;   // already backed up
            }

            if (!CheckDestinationAvailable()) return false;
            Directory.CreateDirectory(destDir);
            File.Copy(src, dest, true);   // preserves the original timestamp
            Metadata.TagGameName(dest, game);

            Interlocked.Increment(ref _sessionFiles);
            Interlocked.Add(ref _sessionBytes, new FileInfo(dest).Length);

            string detail = $"{game}  \u203A  {destName}  [{TypeLabel(type)}]";
            if (restore) Logger.Restore(detail, dest);
            else Logger.Backup(detail, dest);

            if (run != null)
            {
                run.Copied++;
                run.GamesAffected.Add(game);
            }

            // Dangerous, opt-in: remove the just-imported original (to the Recycle Bin).
            DeleteOriginalToRecycleBin(src, dest, run);
            return true;
        }

        // Sends a successfully-imported original to the Windows Recycle Bin, but only
        // when the backup copy is provably present and complete. Never permanent, so a
        // mistake is always recoverable.
        private void DeleteOriginalToRecycleBin(string src, string dest, RunResult run)
        {
            if (!_settings.DeleteOriginals) return;
            try
            {
                if (!File.Exists(src)) return;
                if (!File.Exists(dest) || new FileInfo(dest).Length < new FileInfo(src).Length) return;
                RecycleBin.Delete(src);
                if (run != null) run.OriginalsDeleted++;
                else Logger.Log("Deleted original after import (sent to the Recycle Bin): " + Path.GetFileName(src));
            }
            catch (Exception ex)
            {
                Logger.Warn($"Could not delete original {Path.GetFileName(src)}: {ex.Message}");
            }
        }

        private static string TypeFolder(ScreenshotType t) =>
            t == ScreenshotType.Standard ? StandardFolder : HighResFolder;

        public static string TypeLabel(ScreenshotType t) =>
            t == ScreenshotType.Standard ? "Standard" : "High resolution";

        // 20260706210532_1.jpg / 646570_20260706210532_1.png -> "2026-07-06 21.05.32.ext"
        private static (DateTime Ts, string Name) ConvertName(string fileName, ScreenshotType type)
        {
            Match m = type == ScreenshotType.Standard
                ? StdName.Match(fileName) : HighResSrcName.Match(fileName);
            if (!m.Success) return (DateTime.MinValue, null);

            int g = type == ScreenshotType.Standard ? 1 : 2;   // first timestamp group index
            var parts = Enumerable.Range(g, 6).Select(i => m.Groups[i].Value).ToArray();
            int n = int.Parse(m.Groups[g + 6].Value);
            string ext = m.Groups[g + 7].Value;
            string suffix = n > 1 ? $" ({n})" : "";

            var ts = new DateTime(int.Parse(parts[0]), int.Parse(parts[1]), int.Parse(parts[2]),
                int.Parse(parts[3]), int.Parse(parts[4]), int.Parse(parts[5]));
            return (ts, $"{parts[0]}-{parts[1]}-{parts[2]} {parts[3]}.{parts[4]}.{parts[5]}{suffix}{ext}");
        }

        // {game}\{yyyy} etc. Each expanded segment is kept file-system safe.
        private string ExpandTemplate(string game, DateTime ts)
        {
            string t = string.IsNullOrWhiteSpace(_settings.FolderTemplate) ? "{game}" : _settings.FolderTemplate;
            string expanded = t
                .Replace("{game}", game)
                .Replace("{yyyy}", ts.ToString("yyyy"))
                .Replace("{MM}", ts.ToString("MM"))
                .Replace("{dd}", ts.ToString("dd"));
            var safeSegments = expanded.Split('\\', '/')
                .Select(s => Regex.Replace(s, "[:*?\"<>|]", "").Trim(' ', '.'))
                .Where(s => s.Length > 0);
            return string.Join("\\", safeSegments);
        }

        // ------------------------------------------------------------- scanning

        // Every valid screenshot across all enabled sources. Shared by the scanner and
        // the "missing from backup" finder so they always agree on what counts.
        private IEnumerable<(string Path, string Appid, ScreenshotType Type)> EnumerateSources()
        {
            if (_settings.BackupStandard && Directory.Exists(_userdata))
            {
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
                            if (StdName.IsMatch(Path.GetFileName(f)))
                                yield return (f, appid, ScreenshotType.Standard);
                    }
                }
            }

            if (_settings.BackupHighRes)
            {
                foreach (var folder in _highResFolders.Where(Directory.Exists))
                    foreach (var f in Directory.GetFiles(folder))
                    {
                        var m = HighResSrcName.Match(Path.GetFileName(f));
                        if (m.Success) yield return (f, m.Groups[1].Value, ScreenshotType.HighRes);
                    }
            }
        }

        // One full pass over every enabled source. Returns what THIS run did, or
        // null when the destination is offline.
        public RunResult FullScan(bool restore = false)
        {
            if (!CheckDestinationAvailable()) return null;
            var run = new RunResult();
            foreach (var (path, appid, type) in EnumerateSources())
            {
                try { CopyOne(path, appid, type, restore, run); }
                catch (Exception ex) { Logger.Error($"Copy failed for {path}: {ex.Message}"); }
            }
            if (run.OriginalsDeleted > 0)
                Logger.Log($"Deleted {run.OriginalsDeleted} imported original" +
                           $"{(run.OriginalsDeleted == 1 ? "" : "s")} (sent to the Recycle Bin).");
            return run;
        }

        // Retroactive one-shot for "delete originals after import": sends every original
        // that already has a verified backup to the Recycle Bin. Reports (done, total).
        public int PurgeImportedOriginals(Action<int, int> progress = null)
        {
            var sources = EnumerateSources().ToList();
            int deleted = 0, done = 0;
            foreach (var (path, appid, type) in sources)
            {
                try
                {
                    string game = _resolver.ResolveFolderName(appid);
                    var (ts, destName) = ConvertName(Path.GetFileName(path), type);
                    if (destName != null)
                    {
                        string dest = Path.Combine(Destination, TypeFolder(type), ExpandTemplate(game, ts), destName);
                        if (File.Exists(path) && File.Exists(dest) &&
                            new FileInfo(dest).Length >= new FileInfo(path).Length)
                        {
                            RecycleBin.Delete(path);
                            deleted++;
                        }
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warn($"Could not delete original {Path.GetFileName(path)}: {ex.Message}");
                }
                progress?.Invoke(++done, sources.Count);
            }
            if (deleted > 0)
                Logger.Log($"Retroactively deleted {deleted} imported original" +
                           $"{(deleted == 1 ? "" : "s")} (sent to the Recycle Bin).");
            return deleted;
        }

        // -------------------------------------------------- re-sync missing files

        // Source screenshots that have no counterpart in the backup right now (deleted
        // from the backup, or not yet copied). This is the manual complement to
        // auto-restore: the user reviews and re-syncs these per game.
        public List<ResyncItem> FindMissingFromBackup()
        {
            var missing = new List<ResyncItem>();
            if (!CheckDestinationAvailable()) return missing;

            foreach (var (path, appid, type) in EnumerateSources())
            {
                try
                {
                    string game = _resolver.ResolveFolderName(appid);
                    var (ts, destName) = ConvertName(Path.GetFileName(path), type);
                    if (destName == null) continue;

                    string dest = Path.Combine(Destination, TypeFolder(type), ExpandTemplate(game, ts), destName);
                    if (File.Exists(dest)) continue;   // already backed up

                    long size = 0;
                    try { size = new FileInfo(path).Length; } catch { }
                    missing.Add(new ResyncItem
                    {
                        Game = game, Type = type, SourcePath = path, DestPath = dest,
                        Timestamp = ts, DisplayName = destName, Size = size
                    });
                }
                catch { }
            }
            return missing;
        }

        // Copies the selected missing items back into the backup, logging each as a
        // restore. Reports progress as (done, total). Returns the count copied.
        public int Resync(IReadOnlyList<ResyncItem> items, Action<int, int> progress = null)
        {
            int copied = 0, done = 0;
            foreach (var it in items)
            {
                try
                {
                    if (!CheckDestinationAvailable()) break;
                    if (File.Exists(it.SourcePath) && !File.Exists(it.DestPath))
                    {
                        Directory.CreateDirectory(Path.GetDirectoryName(it.DestPath));
                        File.Copy(it.SourcePath, it.DestPath, true);
                        Metadata.TagGameName(it.DestPath, it.Game);
                        Interlocked.Increment(ref _sessionFiles);
                        Interlocked.Add(ref _sessionBytes, new FileInfo(it.DestPath).Length);
                        Logger.Restore($"{it.Game}  \u203A  {it.DisplayName}  [{TypeLabel(it.Type)}]", it.DestPath);
                        copied++;
                    }
                }
                catch (Exception ex)
                {
                    Logger.Error($"Re-sync failed for {it.SourcePath}: {ex.Message}");
                }
                progress?.Invoke(++done, items.Count);
            }
            if (copied > 0)
                Logger.Log($"Re-synced {copied} file{(copied == 1 ? "" : "s")} back to the backup.");
            return copied;
        }

        // -------------------------------------------------- backup folder totals

        // Counts everything currently in the backup (all-time totals). Runs on the
        // caller's thread; the UI calls it from a background task.
        public (int Games, int Files, long Bytes) ComputeTotals()
        {
            var games = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            int files = 0;
            long bytes = 0;
            try
            {
                foreach (var typeFolder in new[] { StandardFolder, HighResFolder })
                {
                    string root = Path.Combine(Destination, typeFolder);
                    if (!Directory.Exists(root)) continue;
                    foreach (var f in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories))
                    {
                        if (!BackupName.IsMatch(Path.GetFileName(f))) continue;
                        files++;
                        try { bytes += new FileInfo(f).Length; } catch { }
                        string game = ExtractGameFromRelPath(
                            Path.GetRelativePath(root, f));
                        if (game != null) games.Add(game);
                    }
                }
            }
            catch { }
            return (games.Count, files, bytes);
        }

        // One-time: add searchable game-name metadata to existing backups that predate
        // the metadata fix (older PNGs especially). Runs in the background; already-
        // tagged files are skipped with a cheap header check.
        public int BackfillMetadata()
        {
            int tagged = 0;
            try
            {
                foreach (var typeFolder in new[] { StandardFolder, HighResFolder })
                {
                    string root = Path.Combine(Destination, typeFolder);
                    if (!Directory.Exists(root)) continue;
                    foreach (var f in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories))
                    {
                        if (_disposed) return tagged;
                        string ext = Path.GetExtension(f).ToLowerInvariant();
                        if (ext is not ".jpg" and not ".jpeg" and not ".png") continue;
                        if (!BackupName.IsMatch(Path.GetFileName(f))) continue;
                        if (Metadata.HasGameNameMetadata(f)) continue;
                        string game = ExtractGameFromRelPath(Path.GetRelativePath(root, f));
                        if (game == null) continue;
                        Metadata.TagGameName(f, game);
                        tagged++;
                    }
                }
            }
            catch (Exception ex) { Logger.Warn("Metadata backfill error: " + ex.Message); }
            if (tagged > 0)
                Logger.Log($"Added searchable metadata to {tagged} existing backup file{(tagged == 1 ? "" : "s")}.");
            return tagged;
        }

        // Sends an entire screenshot-type backup tree (Standard / High Resolution) to
        // the Recycle Bin \u2014 used when the user turns that type off and opts to clean up.
        // Dest-watcher events are suppressed so it isn't mistaken for a manual deletion.
        public int DeleteTypeBackups(ScreenshotType type)
        {
            string root = Path.Combine(Destination, TypeFolder(type));
            if (!Directory.Exists(root)) return 0;

            int files = 0;
            try { files = Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories).Count(); }
            catch { }

            _suppressDestEvents = true;
            try
            {
                RecycleBin.DeleteDirectory(root);
                Logger.Log($"Deleted {files} {TypeLabel(type)} backup file{(files == 1 ? "" : "s")} " +
                           "(sent to the Recycle Bin).");
            }
            catch (Exception ex)
            {
                Logger.Error($"Could not delete {TypeLabel(type)} backups: {ex.Message}");
            }
            finally
            {
                // Re-enable dest events after a beat to swallow trailing delete notifications.
                _unsuppressTimer ??= new Timer(_ => _suppressDestEvents = false);
                _unsuppressTimer.Change(3000, Timeout.Infinite);
            }
            return files;
        }

        // Given a path relative to a type folder, find the {game} segment using the
        // active template (e.g. template "{yyyy}\{game}" puts the game second).
        private string ExtractGameFromRelPath(string rel)
        {
            var segments = rel.Split('\\', '/');
            var tSegments = (_settings.FolderTemplate ?? "{game}").Split('\\', '/');
            for (int i = 0; i < tSegments.Length && i < segments.Length - 1; i++)
                if (tSegments[i].Contains("{game}")) return segments[i];
            return segments.Length > 1 ? segments[0] : null;
        }

        // --------------------------------------------------- destination watching

        // Watches the backup destination so deletions are logged and restored.
        public void WatchDestination()
        {
            try
            {
                _destWatcher?.Dispose();
                _destWatcher = null;
                if (!Directory.Exists(Destination)) Directory.CreateDirectory(Destination);

                _destWatcher = new FileSystemWatcher(Destination)
                {
                    IncludeSubdirectories = true,
                    NotifyFilter = NotifyFilters.FileName | NotifyFilters.DirectoryName
                };
                _destWatcher.Deleted += (s, e) => OnDestinationDelete(e.Name, e.FullPath);
                _destWatcher.Renamed += (s, e) => OnDestinationDelete(e.OldName, e.OldFullPath);
                _destWatcher.Error += (s, e) => OnDestWatcherError();
                _destWatcher.EnableRaisingEvents = !_paused;
            }
            catch (Exception ex)
            {
                Logger.Warn("Could not watch the backup folder for deletions: " + ex.Message);
                CheckDestinationAvailable();   // probably offline; start the retry loop
            }
        }

        private void OnDestinationDelete(string relName, string fullPath)
        {
            if (_paused || _suppressDestEvents || relName == null) return;

            // Only react to things that live inside our Standard/High Resolution trees.
            var segments = relName.Split('\\', '/');
            if (segments.Length == 0) return;
            bool std = segments[0].Equals(StandardFolder, StringComparison.OrdinalIgnoreCase);
            bool hr = segments[0].Equals(HighResFolder, StringComparison.OrdinalIgnoreCase);
            if (!std && !hr) return;

            string label = std ? "Standard" : "High resolution";
            if (segments.Length == 1)
            {
                Logger.Deletion($"{label} backup folder removed", fullPath);
            }
            else if (BackupName.IsMatch(segments[^1]))
            {
                string game = ExtractGameFromRelPath(string.Join('\\', segments.Skip(1)));
                Logger.Deletion($"{game ?? segments[1]}  \u203A  {segments[^1]}  [{label}]", fullPath);
            }
            else if (!Path.HasExtension(segments[^1]))
            {
                Logger.Deletion($"{segments[^1]}  \u203A  folder removed  [{label}]", fullPath);
            }
            else
            {
                return;   // some unrelated file (desktop.ini etc.); not ours
            }

            // Auto-restore is optional; when off, the deletion is still logged above but
            // the user re-syncs manually from the "Re-sync missing" window.
            if (!_settings.AutoRestore) return;

            if (!_resyncPending)
            {
                _resyncPending = true;
                Logger.Log("Restoring deleted backup files shortly\u2026");
            }
            // Debounce: a folder delete fires one event per file, so wait for quiet.
            _resyncTimer ??= new Timer(_ =>
            {
                _resyncPending = false;
                RestoreNeeded?.Invoke();
            });
            _resyncTimer.Change(5000, Timeout.Infinite);
        }

        private void OnDestWatcherError()
        {
            if (_disposed) return;
            if (!CheckDestinationAvailable()) return;   // offline path handles re-arm
            // Watcher choked (buffer overflow or the root was briefly gone): re-arm,
            // and schedule a resync so a missed deletion isn't lost (only if auto-restore).
            WatchDestination();
            if (!_settings.AutoRestore) return;
            _resyncTimer ??= new Timer(_ => { _resyncPending = false; RestoreNeeded?.Invoke(); });
            _resyncTimer.Change(3000, Timeout.Infinite);
        }

        // -------------------------------------------------------- NAS resiliency

        // True while the destination root exists. Transitions into the offline state
        // (with a 20 s retry loop) when it doesn't - typical for a NAS that dropped.
        private bool CheckDestinationAvailable()
        {
            bool available;
            try { available = Directory.Exists(Path.GetPathRoot(Destination)) || Directory.Exists(Destination); }
            catch { available = false; }
            // For UNC paths GetPathRoot is \\server\share which Directory.Exists probes.

            if (available)
            {
                if (_offline)
                {
                    _offline = false;
                    Logger.Log("Backup destination is reachable again.");
                    _offlineRetryTimer?.Change(Timeout.Infinite, Timeout.Infinite);
                    WatchDestination();
                    DestinationOnline?.Invoke();
                }
                return true;
            }

            if (!_offline)
            {
                _offline = true;
                Logger.Warn("Backup destination is unreachable (network drive offline?). " +
                            "Backups are queued and will resume automatically.");
                DestinationOffline?.Invoke();
                _offlineRetryTimer ??= new Timer(_ => CheckDestinationAvailable());
                _offlineRetryTimer.Change(20000, 20000);
            }
            return false;
        }

        private void WaitWhileOffline()
        {
            while (_offline && !_disposed) Thread.Sleep(2000);
        }

        // ------------------------------------------------------------ migrations

        // One-time upgrade: older versions put game folders directly in the backup
        // root; move them under "Standard\".
        public void MigrateStructureIfNeeded()
        {
            if (_settings.StructureMigrated) return;
            try
            {
                if (Directory.Exists(Destination))
                {
                    _suppressDestEvents = true;
                    int moved = 0;
                    string stdRoot = Path.Combine(Destination, StandardFolder);
                    foreach (var dir in Directory.GetDirectories(Destination))
                    {
                        string name = Path.GetFileName(dir);
                        if (name.Equals(StandardFolder, StringComparison.OrdinalIgnoreCase) ||
                            name.Equals(HighResFolder, StringComparison.OrdinalIgnoreCase)) continue;
                        // Only move folders that actually look like our game backups.
                        if (!Directory.EnumerateFiles(dir)
                                .Any(f => BackupName.IsMatch(Path.GetFileName(f)))) continue;

                        Directory.CreateDirectory(stdRoot);
                        string target = Path.Combine(stdRoot, name);
                        if (!Directory.Exists(target)) { Directory.Move(dir, target); moved++; }
                    }
                    if (moved > 0)
                        Logger.Log($"Upgraded backup layout: moved {moved} game folders under \"{StandardFolder}\\\".");
                }
                _settings.StructureMigrated = true;
                _settings.Save();
            }
            catch (Exception ex)
            {
                Logger.Error("Backup layout upgrade failed: " + ex.Message);
            }
            finally
            {
                _suppressDestEvents = false;
            }
        }

        // Moves the whole backup to a new destination (used by Settings). Reports
        // progress as (done, total). Falls back to copy+delete across volumes.
        public void MoveBackup(string oldDest, string newDest, Action<int, int> progress)
        {
            _suppressDestEvents = true;
            try
            {
                var files = new List<string>();
                foreach (var typeFolder in new[] { StandardFolder, HighResFolder })
                {
                    string root = Path.Combine(oldDest, typeFolder);
                    if (Directory.Exists(root))
                        files.AddRange(Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories));
                }

                int done = 0;
                foreach (var src in files)
                {
                    string rel = Path.GetRelativePath(oldDest, src);
                    string dest = Path.Combine(newDest, rel);
                    Directory.CreateDirectory(Path.GetDirectoryName(dest));
                    if (!File.Exists(dest)) File.Move(src, dest);
                    else File.Delete(src);   // already present at target
                    progress?.Invoke(++done, files.Count);
                }

                // Clean now-empty tree at the old location.
                foreach (var typeFolder in new[] { StandardFolder, HighResFolder })
                {
                    string root = Path.Combine(oldDest, typeFolder);
                    if (Directory.Exists(root)) DeleteEmptyTree(root);
                }
                Logger.Log($"Migrated {files.Count} backup files to {newDest}");
            }
            finally
            {
                _suppressDestEvents = false;
            }
        }

        // Re-shapes the existing backup when the folder template changes,
        // e.g. {game} -> {yyyy}\{game}. Unrecognized files are left alone.
        public void ReorganizeLayout(string oldTemplate, string newTemplate)
        {
            _suppressDestEvents = true;
            try
            {
                int moved = 0;
                foreach (var typeFolder in new[] { StandardFolder, HighResFolder })
                {
                    string root = Path.Combine(Destination, typeFolder);
                    if (!Directory.Exists(root)) continue;

                    foreach (var src in Directory.GetFiles(root, "*", SearchOption.AllDirectories))
                    {
                        string file = Path.GetFileName(src);
                        if (!BackupName.IsMatch(file)) continue;

                        string game = ExtractGameSegment(Path.GetRelativePath(root, src), oldTemplate);
                        if (game == null) continue;
                        var tsMatch = Regex.Match(file, @"^(\d{4})-(\d{2})-(\d{2}) (\d{2})\.(\d{2})\.(\d{2})");
                        if (!tsMatch.Success) continue;
                        var ts = new DateTime(
                            int.Parse(tsMatch.Groups[1].Value), int.Parse(tsMatch.Groups[2].Value),
                            int.Parse(tsMatch.Groups[3].Value), int.Parse(tsMatch.Groups[4].Value),
                            int.Parse(tsMatch.Groups[5].Value), int.Parse(tsMatch.Groups[6].Value));

                        string newRel = newTemplate
                            .Replace("{game}", game)
                            .Replace("{yyyy}", ts.ToString("yyyy"))
                            .Replace("{MM}", ts.ToString("MM"))
                            .Replace("{dd}", ts.ToString("dd"));
                        string dest = Path.Combine(root, newRel, file);
                        if (string.Equals(dest, src, StringComparison.OrdinalIgnoreCase)) continue;

                        Directory.CreateDirectory(Path.GetDirectoryName(dest));
                        if (!File.Exists(dest)) { File.Move(src, dest); moved++; }
                    }
                    DeleteEmptyTree(root, keepRoot: true);
                }
                if (moved > 0) Logger.Log($"Reorganized {moved} backup files into the new folder layout.");
            }
            catch (Exception ex)
            {
                Logger.Error("Layout reorganization failed: " + ex.Message);
            }
            finally
            {
                _suppressDestEvents = false;
            }
        }

        private static string ExtractGameSegment(string rel, string template)
        {
            var segments = rel.Split('\\', '/');
            var tSegments = (string.IsNullOrWhiteSpace(template) ? "{game}" : template).Split('\\', '/');
            for (int i = 0; i < tSegments.Length && i < segments.Length - 1; i++)
                if (tSegments[i].Contains("{game}")) return segments[i];
            return null;
        }

        private static void DeleteEmptyTree(string root, bool keepRoot = false)
        {
            try
            {
                foreach (var dir in Directory.GetDirectories(root))
                    DeleteEmptyTree(dir);
                if (!keepRoot &&
                    !Directory.EnumerateFileSystemEntries(root).Any())
                    Directory.Delete(root);
            }
            catch { }
        }

        public void Dispose()
        {
            _disposed = true;
            _stdWatcher?.Dispose();
            foreach (var w in _highResWatchers) w.Dispose();
            _destWatcher?.Dispose();
            _resyncTimer?.Dispose();
            _offlineRetryTimer?.Dispose();
            _unsuppressTimer?.Dispose();
            _queue.CompleteAdding();
        }
    }
}
