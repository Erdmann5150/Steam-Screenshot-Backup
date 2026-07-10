using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;

namespace SteamScreenshotBackup
{
    // Turns Steam appids into real game names, cheapest source first:
    //   1. app manifests of installed games (all library drives)
    //   2. the persistent name cache (shared with the PowerShell script)
    //   3. shortcuts.vdf for non-Steam games added to Steam
    //   4. the Steam store API (result cached forever, but periodically re-verified
    //      in the background \u2014 see RefreshStaleEntries)
    // Unresolvable ids fall back to "AppID_<id>" / "Non-Steam App <id>".
    // Step 4 is skipped entirely when Settings.OfflineMode is on, and compiled
    // out completely (no HttpClient, no network code) when built with the
    // OFFLINE_ONLY define.
    internal class AppNameResolver : IDisposable
    {
#if !OFFLINE_ONLY
        private static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
#endif

        private const int StoreThrottleMs = 500;   // min gap between Steam store API calls

        // Background cache maintenance: names resolved from the store are cached
        // forever (Steam appids essentially never get renamed), but rare cases do
        // happen (Early Access -> 1.0 rebrand, etc.), so each entry gets silently
        // re-verified against the store every RefreshAgeDays, a small batch at a
        // time so a large cache never bursts a flood of API calls at once.
        private static readonly TimeSpan RefreshInterval = TimeSpan.FromHours(24);
        private static readonly TimeSpan RefreshFirstRun = TimeSpan.FromMinutes(2);
        private const int RefreshBatchSize = 20;
        private const int RefreshAgeDays = 30;

        private readonly object _lock = new object();
        private readonly object _storeLock = new object();   // serializes + throttles store calls
        private readonly Dictionary<string, string> _manifestNames = new Dictionary<string, string>();
        private readonly Dictionary<string, string> _cache = new Dictionary<string, string>();
        private readonly Dictionary<string, DateTime> _verifiedAt = new Dictionary<string, DateTime>();
        private readonly HashSet<string> _failedLookups = new HashSet<string>();   // per-session
        private Dictionary<ulong, string> _shortcutNames;
        private readonly string _cacheFile;
        private readonly string _verifiedFile;
        private readonly string _steamPath;
        private readonly Settings _settings;
        private DateTime _lastManifestScan = DateTime.MinValue;
        private DateTime _lastStoreCall = DateTime.MinValue;
#if !OFFLINE_ONLY
        private Timer _refreshTimer;
#endif

        public AppNameResolver(string steamPath, Settings settings)
        {
            _steamPath = steamPath;
            _settings = settings;
            _cacheFile = Path.Combine(Settings.Dir, "appnames.json");   // shared with the PowerShell script
            _verifiedFile = Path.Combine(Settings.Dir, "appnames.verified.json");
            LoadCache();
            LoadVerified();
            ScanManifests();
#if !OFFLINE_ONLY
            _refreshTimer = new Timer(_ => RefreshStaleEntries(), null, RefreshFirstRun, RefreshInterval);
#endif
        }

#if OFFLINE_ONLY
        public void Dispose() { }
#else
        public void Dispose() => _refreshTimer?.Dispose();
#endif

        public string ResolveFolderName(string appid)
        {
            string safe = Sanitize(Resolve(appid));
            if (safe != null) return safe;
            return SteamConfig.IsNonSteamAppId(appid) ? $"Non-Steam App {appid}" : $"AppID_{appid}";
        }

        private string Resolve(string appid)
        {
            lock (_lock)
            {
                if (_manifestNames.TryGetValue(appid, out var n1)) return n1;
                if (_cache.TryGetValue(appid, out var n2)) return n2;
                if (_failedLookups.Contains(appid)) return null;
            }

            // Non-Steam shortcut games never resolve via manifests or the store.
            if (SteamConfig.IsNonSteamAppId(appid))
            {
                string shortcut = ResolveShortcut(appid);
                if (shortcut != null)
                {
                    lock (_lock) _cache[appid] = shortcut;
                    SaveCache();
                }
                else
                {
                    lock (_lock) _failedLookups.Add(appid);
                }
                return shortcut;
            }

            // Games installed after startup won't be in the manifest map yet; rescan (throttled).
            if ((DateTime.UtcNow - _lastManifestScan).TotalMinutes > 1)
            {
                ScanManifests();
                lock (_lock)
                    if (_manifestNames.TryGetValue(appid, out var n3)) return n3;
            }

            string name = _settings.OfflineMode ? null : QueryStore(appid);
            lock (_lock)
            {
                if (name != null) _cache[appid] = name;
                else _failedLookups.Add(appid);   // don't hammer the API again this session
            }
            if (name != null) SaveCache();
            return name;
        }

        private string ResolveShortcut(string appid)
        {
            lock (_lock)
                _shortcutNames ??= SteamConfig.ReadShortcutNames(_steamPath);
            if (!ulong.TryParse(appid, out var id)) return null;
            // The screenshot folder id is the 32-bit shortcut id, sometimes shifted
            // into the high dword of a 64-bit value; try both interpretations.
            if (_shortcutNames.TryGetValue(id, out var name)) return name;
            if (_shortcutNames.TryGetValue(id >> 32, out name)) return name;
            if (_shortcutNames.TryGetValue(id & 0xFFFFFFFF, out name)) return name;
            return null;
        }

        // ----- cache editing API for the "Manage game names" window -----

        public SortedDictionary<string, string> GetCachedNames()
        {
            lock (_lock) return new SortedDictionary<string, string>(_cache);
        }

        public void SetCachedName(string appid, string name)
        {
            lock (_lock)
            {
                _cache[appid] = name;
                _failedLookups.Remove(appid);
            }
            SaveCache();
        }

        public void RemoveCachedName(string appid)
        {
            lock (_lock)
            {
                _cache.Remove(appid);
                _failedLookups.Remove(appid);
                _verifiedAt.Remove(appid);
            }
            SaveCache();
        }

        // True if this appid is already in the persistent game-name list (appnames.json).
        public bool IsTracked(string appid)
        {
            lock (_lock) return _cache.ContainsKey(appid);
        }

        // Forces a fresh resolution attempt, bypassing this session's failed-lookup
        // cache (sources like manifests or shortcuts.vdf may have changed since the
        // last attempt). A successful result is recorded in the persistent game-name
        // list even when it came from a free source (manifest), so it is visible and
        // editable from the "Game Names" window. Used by the retroactive app-id scan.
        public string TryResolveNow(string appid)
        {
            lock (_lock) _failedLookups.Remove(appid);
            string name = Resolve(appid);
            if (name != null) SetCachedName(appid, name);
            return name;
        }

        // Path to the persistent game-name cache file, for "open in editor" actions.
        public string CacheFilePath => _cacheFile;

        // ----- background cache maintenance -----

        // Re-verifies a bounded batch of the oldest (or never-verified) store-resolved
        // cache entries against the live store, so a rename/rebrand eventually gets
        // picked up without ever hammering the API. Manifest- and shortcut-backed
        // entries are skipped: those sources are already re-scanned fresh elsewhere.
        // Runs on the timer's own thread pool thread; safe to call at any time.
        private void RefreshStaleEntries()
        {
            if (_settings.OfflineMode) return;

            List<string> batch;
            lock (_lock)
            {
                var cutoff = DateTime.UtcNow.AddDays(-RefreshAgeDays);
                batch = _cache.Keys
                    .Where(id => !SteamConfig.IsNonSteamAppId(id) && !_manifestNames.ContainsKey(id))
                    .Where(id => !_verifiedAt.TryGetValue(id, out var t) || t < cutoff)
                    .OrderBy(id => _verifiedAt.TryGetValue(id, out var t) ? t : DateTime.MinValue)
                    .Take(RefreshBatchSize)
                    .ToList();
            }
            if (batch.Count == 0) return;

            bool cacheChanged = false;
            foreach (var appid in batch)
            {
                string fresh = QueryStore(appid);
                if (fresh == null) continue;   // network/lookup failure; retry on a later pass

                lock (_lock)
                {
                    if (!_cache.TryGetValue(appid, out var current)) continue;   // removed meanwhile
                    if (current != fresh)
                    {
                        _cache[appid] = fresh;
                        cacheChanged = true;
                        Logger.Log($"Game name updated: \"{current}\" is now \"{fresh}\" ({appid}).");
                    }
                    _verifiedAt[appid] = DateTime.UtcNow;
                }
            }

            if (cacheChanged) SaveCache();
            SaveVerified();
        }

        // ----- sources -----

        private void ScanManifests()
        {
            lock (_lock)
            {
                _lastManifestScan = DateTime.UtcNow;

                var libraries = new List<string> { Path.Combine(_steamPath, "steamapps") };
                string vdf = Path.Combine(_steamPath, @"steamapps\libraryfolders.vdf");
                try
                {
                    if (File.Exists(vdf))
                        foreach (Match m in Regex.Matches(File.ReadAllText(vdf), "\"path\"\\s+\"([^\"]+)\""))
                        {
                            string p = Path.Combine(m.Groups[1].Value.Replace(@"\\", @"\"), "steamapps");
                            if (Directory.Exists(p) && !libraries.Contains(p, StringComparer.OrdinalIgnoreCase))
                                libraries.Add(p);
                        }
                }
                catch { }

                foreach (var lib in libraries)
                {
                    try
                    {
                        foreach (var acf in Directory.GetFiles(lib, "appmanifest_*.acf"))
                        {
                            string raw = File.ReadAllText(acf);
                            string id = Regex.Match(raw, "\"appid\"\\s+\"(\\d+)\"").Groups[1].Value;
                            string name = Regex.Match(raw, "\"name\"\\s+\"([^\"]+)\"").Groups[1].Value;
                            if (id.Length > 0 && name.Length > 0) _manifestNames[id] = name;
                        }
                    }
                    catch { }
                }
            }
        }

        // Queries the Steam store API for a name. Callers are always background threads
        // (the copy worker / scan tasks), never the WinForms UI thread, so the throttle
        // below never freezes the UI. Store calls are serialized and spaced at least
        // StoreThrottleMs apart to avoid rate-limiting during large bulk imports; cached
        // names never reach this method, so the delay only applies to real network calls.
#if OFFLINE_ONLY
        private string QueryStore(string appid) => null;
#else
        private string QueryStore(string appid)
        {
            lock (_storeLock)
            {
                var wait = TimeSpan.FromMilliseconds(StoreThrottleMs) - (DateTime.UtcNow - _lastStoreCall);
                if (wait > TimeSpan.Zero) Thread.Sleep(wait);

                try
                {
                    string json = Http.GetStringAsync(
                            $"https://store.steampowered.com/api/appdetails?appids={appid}&filters=basic")
                        .GetAwaiter().GetResult();

                    using var doc = JsonDocument.Parse(json);
                    if (doc.RootElement.TryGetProperty(appid, out var e) &&
                        e.TryGetProperty("success", out var s) && s.GetBoolean() &&
                        e.TryGetProperty("data", out var d) &&
                        d.TryGetProperty("name", out var n))
                        return n.GetString();
                }
                catch (Exception ex)
                {
                    Logger.Warn($"Name lookup failed for {appid}: {ex.Message}");
                }
                finally
                {
                    _lastStoreCall = DateTime.UtcNow;
                }
            }
            return null;
        }
#endif

        // ----- persistence -----

        private void LoadCache()
        {
            try
            {
                if (!File.Exists(_cacheFile)) return;

                byte[] bytes = File.ReadAllBytes(_cacheFile);
                string json;
                bool recovered = false;
                try
                {
                    json = new UTF8Encoding(false, throwOnInvalidBytes: true).GetString(bytes);
                }
                catch (DecoderFallbackException)
                {
                    // Cache written in the legacy ANSI code page (old PowerShell script
                    // versions did this); decode it correctly so special characters survive.
                    json = Encoding.GetEncoding(1252).GetString(bytes);
                    recovered = true;
                }

                var d = JsonSerializer.Deserialize<Dictionary<string, string>>(json);
                if (d != null)
                    foreach (var kv in d)
                        if (!kv.Value.Contains('\uFFFD'))   // drop already-corrupted names; they re-resolve
                            _cache[kv.Key] = kv.Value;

                if (recovered) SaveCache();   // rewrite as clean UTF-8 immediately
            }
            catch { }
        }

        private void SaveCache()
        {
            try
            {
                Directory.CreateDirectory(Settings.Dir);
                lock (_lock)
                    File.WriteAllText(_cacheFile,
                        JsonSerializer.Serialize(_cache, new JsonSerializerOptions { WriteIndented = true }));
            }
            catch { }
        }

        private void LoadVerified()
        {
            try
            {
                if (!File.Exists(_verifiedFile)) return;
                var d = JsonSerializer.Deserialize<Dictionary<string, DateTime>>(File.ReadAllText(_verifiedFile));
                if (d != null)
                    foreach (var kv in d) _verifiedAt[kv.Key] = kv.Value;
            }
            catch { }
        }

        private void SaveVerified()
        {
            try
            {
                Directory.CreateDirectory(Settings.Dir);
                lock (_lock)
                    File.WriteAllText(_verifiedFile,
                        JsonSerializer.Serialize(_verifiedAt, new JsonSerializerOptions { WriteIndented = true }));
            }
            catch { }
        }

        private static string Sanitize(string name)
        {
            if (string.IsNullOrWhiteSpace(name)) return null;
            string clean = Regex.Replace(name, "[\\\\/:*?\"<>|\uFFFD]", "").Trim(' ', '.');
            return string.IsNullOrWhiteSpace(clean) ? null : clean;
        }
    }
}
