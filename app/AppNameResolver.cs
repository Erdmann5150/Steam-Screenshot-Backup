using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;

namespace SteamScreenshotBackup
{
    internal class AppNameResolver
    {
        private static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };

        private readonly object _lock = new object();
        private readonly Dictionary<string, string> _manifestNames = new Dictionary<string, string>();
        private readonly Dictionary<string, string> _cache = new Dictionary<string, string>();
        private readonly string _cacheFile;
        private readonly string _steamPath;
        private DateTime _lastManifestScan = DateTime.MinValue;

        public AppNameResolver(string steamPath)
        {
            _steamPath = steamPath;
            _cacheFile = Path.Combine(Settings.Dir, "appnames.json");   // shared with the PowerShell script
            LoadCache();
            ScanManifests();
        }

        public string ResolveFolderName(string appid)
        {
            string safe = Sanitize(Resolve(appid));
            return safe ?? $"AppID_{appid}";
        }

        private string Resolve(string appid)
        {
            lock (_lock)
            {
                if (_manifestNames.TryGetValue(appid, out var n1)) return n1;
                if (_cache.TryGetValue(appid, out var n2)) return n2;
            }

            // Games installed after startup won't be in the manifest map yet; rescan (throttled).
            if ((DateTime.UtcNow - _lastManifestScan).TotalMinutes > 1)
            {
                ScanManifests();
                lock (_lock)
                    if (_manifestNames.TryGetValue(appid, out var n3)) return n3;
            }

            string name = QueryStore(appid);
            if (name != null)
            {
                lock (_lock) _cache[appid] = name;
                SaveCache();
            }
            return name;
        }

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

        private string QueryStore(string appid)
        {
            try
            {
                string json = Http.GetStringAsync(
                        $"https://store.steampowered.com/api/appdetails?appids={appid}&filters=basic")
                    .GetAwaiter().GetResult();
                Thread.Sleep(300);   // be polite to the store API

                using var doc = JsonDocument.Parse(json);
                if (doc.RootElement.TryGetProperty(appid, out var e) &&
                    e.TryGetProperty("success", out var s) && s.GetBoolean() &&
                    e.TryGetProperty("data", out var d) &&
                    d.TryGetProperty("name", out var n))
                    return n.GetString();
            }
            catch (Exception ex)
            {
                Logger.Log($"Name lookup failed for {appid}: {ex.Message}");
            }
            return null;
        }

        private void LoadCache()
        {
            try
            {
                if (!File.Exists(_cacheFile)) return;
                var d = JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(_cacheFile));
                if (d != null) foreach (var kv in d) _cache[kv.Key] = kv.Value;
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

        private static string Sanitize(string name)
        {
            if (string.IsNullOrWhiteSpace(name)) return null;
            string clean = Regex.Replace(name, "[\\\\/:*?\"<>|]", "").Trim(' ', '.');
            return string.IsNullOrWhiteSpace(clean) ? null : clean;
        }
    }
}
