using System;
using System.Net.Http;
using System.Text.Json;

namespace SteamScreenshotBackup
{
    // Checks GitHub's latest release against the running version: one read-only
    // HTTPS GET to the public releases API, nothing else sent or received beyond
    // that. Skipped entirely when Settings.OfflineMode is on, and compiled out
    // completely (no HttpClient, no network code) in the OFFLINE_ONLY build -
    // same pattern as AppNameResolver's Steam store lookups.
    internal static class UpdateChecker
    {
        private const string ReleasesApiUrl =
            "https://api.github.com/repos/Erdmann5150/Steam-Screenshot-Backup/releases/latest";
        public const string ReleasesPageUrl =
            "https://github.com/Erdmann5150/Steam-Screenshot-Backup/releases/latest";

        public class UpdateInfo
        {
            public string Version;
            public string Url;
        }

        // The running app's own version, read from assembly metadata (kept in sync
        // with the installer's #define AppVersion by build.ps1) rather than duplicated
        // here as a literal.
        public static string CurrentVersion { get; } =
            System.Reflection.Assembly.GetExecutingAssembly().GetName().Version?.ToString(3) ?? "0.0.0";

        // Pure comparison logic, kept separate from the network call so it can be
        // unit-tested without one. Returns the cleaned tag (leading "v" stripped) if
        // it parses as a version newer than `current`, otherwise null.
        internal static string NewerVersionOrNull(string tag, string current)
        {
            string latest = tag?.Trim().TrimStart('v', 'V');
            if (!Version.TryParse(latest, out var latestVersion)) return null;
            if (!Version.TryParse(current, out var currentVersion)) return null;
            return latestVersion > currentVersion ? latest : null;
        }

#if OFFLINE_ONLY
        public static UpdateInfo CheckNow(Settings settings) => null;
#else
        private static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };

        static UpdateChecker()
        {
            // GitHub's API rejects requests with no User-Agent.
            Http.DefaultRequestHeaders.UserAgent.ParseAdd("SteamScreenshotBackup-UpdateCheck");
        }

        // Returns the latest published release's version/url, or null when up to
        // date, offline mode is on, or the check failed for any reason - this never
        // throws, since it can run unattended on a background timer.
        public static UpdateInfo CheckNow(Settings settings)
        {
            if (settings.OfflineMode) return null;
            try
            {
                string json = Http.GetStringAsync(ReleasesApiUrl).GetAwaiter().GetResult();
                using var doc = JsonDocument.Parse(json);

                string tag = doc.RootElement.TryGetProperty("tag_name", out var t) ? t.GetString() : null;
                string url = doc.RootElement.TryGetProperty("html_url", out var u) ? u.GetString() : null;

                string newer = NewerVersionOrNull(tag, CurrentVersion);
                if (newer == null) return null;
                return new UpdateInfo { Version = newer, Url = url ?? ReleasesPageUrl };
            }
            catch (Exception ex)
            {
                Logger.Warn("Update check failed: " + ex.Message);
                return null;
            }
        }
#endif
    }
}
