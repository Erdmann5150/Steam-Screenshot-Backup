using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace SteamScreenshotBackup
{
    // Central knowledge about the local Steam installation: where it lives, which
    // accounts exist, where each account saves uncompressed ("high resolution")
    // screenshot copies, and the names of non-Steam shortcut games.
    internal static class SteamConfig
    {
        public static string FindSteamPath()
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

        // Folders that Steam's "Save an external copy of my screenshots" writes to,
        // one per account that has the option enabled. Files there are named
        // <appid>_YYYYMMDDHHMMSS_<n>.png
        public static List<string> FindHighResFolders(string steamPath)
        {
            var folders = new List<string>();
            try
            {
                foreach (var cfg in Directory.GetFiles(
                    Path.Combine(steamPath, "userdata"), "localconfig.vdf", SearchOption.AllDirectories))
                {
                    try
                    {
                        string raw = File.ReadAllText(cfg);
                        bool enabled = Regex.IsMatch(raw,
                            "\"InGameOverlayScreenshotSaveUncompressed\"\\s+\"1\"");
                        var m = Regex.Match(raw,
                            "\"InGameOverlayScreenshotSaveUncompressedPath\"\\s+\"([^\"]+)\"");
                        if (!enabled || !m.Success) continue;

                        string path = m.Groups[1].Value.Replace(@"\\", @"\");
                        if (path.Length > 0 &&
                            !folders.Contains(path, StringComparer.OrdinalIgnoreCase))
                            folders.Add(path);
                    }
                    catch { }
                }
            }
            catch { }
            return folders;
        }

        // Non-Steam shortcut games get large synthetic appids (top bit set). Their
        // names live in each account's binary shortcuts.vdf. This does a minimal
        // binary scan rather than a full VDF parse: find the "appid" int32 field,
        // then the "appname" string field within the same entry.
        public static Dictionary<ulong, string> ReadShortcutNames(string steamPath)
        {
            var names = new Dictionary<ulong, string>();
            try
            {
                foreach (var vdf in Directory.GetFiles(
                    Path.Combine(steamPath, "userdata"), "shortcuts.vdf", SearchOption.AllDirectories))
                {
                    try { ScanShortcutsFile(File.ReadAllBytes(vdf), names); }
                    catch { }
                }
            }
            catch { }
            return names;
        }

        private static void ScanShortcutsFile(byte[] data, Dictionary<ulong, string> names)
        {
            byte[] appidKey = Encoding.ASCII.GetBytes("\x02appid\0");
            byte[] nameKey = Encoding.ASCII.GetBytes("\x01appname\0");

            int pos = 0;
            while ((pos = IndexOf(data, appidKey, pos)) >= 0)
            {
                int idOffset = pos + appidKey.Length;
                if (idOffset + 4 > data.Length) break;
                uint appid = BitConverter.ToUInt32(data, idOffset);

                int namePos = IndexOf(data, nameKey, idOffset);
                if (namePos >= 0)
                {
                    int start = namePos + nameKey.Length;
                    int end = Array.IndexOf(data, (byte)0, start);
                    if (end > start)
                    {
                        string name = Encoding.UTF8.GetString(data, start, end - start);
                        if (name.Length > 0) names[appid] = name;
                    }
                }
                pos = idOffset;
            }
        }

        private static int IndexOf(byte[] haystack, byte[] needle, int from)
        {
            for (int i = from; i <= haystack.Length - needle.Length; i++)
            {
                bool hit = true;
                for (int j = 0; j < needle.Length; j++)
                    if (haystack[i + j] != needle[j]) { hit = false; break; }
                if (hit) return i;
            }
            return -1;
        }

        // Screenshot appids above int.MaxValue are synthetic ids for non-Steam games.
        public static bool IsNonSteamAppId(string appid) =>
            ulong.TryParse(appid, out var v) && v > int.MaxValue;
    }
}
