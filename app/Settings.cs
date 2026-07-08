using System;
using System.IO;
using System.Text.Json;

namespace SteamScreenshotBackup
{
    // Persisted user settings. New fields default sensibly so settings files written
    // by older versions load without migration.
    internal class Settings
    {
        public string Destination { get; set; }
        public bool FirstRunDone { get; set; }

        // Which screenshot types to back up.
        public bool BackupStandard { get; set; } = true;
        public bool BackupHighRes { get; set; } = true;

        // Optional manual location of Steam's uncompressed ("external copy") screenshots,
        // used when auto-detection from Steam's config finds nothing. Null/empty = auto only.
        public string HighResFolderOverride { get; set; }

        // Folder layout under the type folder. Tokens: {game} {yyyy} {MM} {dd}
        public string FolderTemplate { get; set; } = "{game}";

        public ThemeMode Theme { get; set; } = ThemeMode.Dark;

        // Set once existing root-level game folders have been moved under "Standard\".
        public bool StructureMigrated { get; set; }

        public static string Dir => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "SteamScreenshotBackup");

        private static string FilePath => Path.Combine(Dir, "settings.json");

        public static Settings Load()
        {
            try
            {
                if (File.Exists(FilePath))
                    return JsonSerializer.Deserialize<Settings>(File.ReadAllText(FilePath)) ?? new Settings();
            }
            catch { }
            return new Settings();
        }

        public void Save()
        {
            try
            {
                Directory.CreateDirectory(Dir);
                File.WriteAllText(FilePath,
                    JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true }));
            }
            catch { }
        }
    }
}
