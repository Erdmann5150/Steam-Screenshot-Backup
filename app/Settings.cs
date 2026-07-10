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

        // When true, files deleted from the backup are automatically restored from
        // Steam (if the source still has them). When false, deletions are only logged
        // and the user re-syncs manually from the "Re-sync missing" window.
        public bool AutoRestore { get; set; } = true;

        // DANGEROUS: when true, an original Steam screenshot is sent to the Windows
        // Recycle Bin once it has been successfully imported into the backup.
        public bool DeleteOriginals { get; set; } = false;

        // Show tray popup (balloon) notifications for backups, restores, etc.
        public bool ShowNotifications { get; set; } = true;

        // Set once existing backups have been given searchable metadata (one-time).
        public bool MetadataBackfilled { get; set; }

        // Append each new backup to a "_Screenshot_Log.md" in its folder.
        public bool GenerateMarkdownIndex { get; set; } = false;

        // Show a preview of proposed changes before running a batch import/reorganize.
        public bool PreviewBeforeImport { get; set; } = false;

        // Set once the first-run catch-up preview has been offered (one-time).
        public bool FirstImportDone { get; set; }

        // Folder layout under the type folder. Tokens: {game} {yyyy} {MM} {dd}
        public string FolderTemplate { get; set; } = "{game}";

        public ThemeMode Theme { get; set; } = ThemeMode.Dark;

        // Set once existing root-level game folders have been moved under "Standard\".
        public bool StructureMigrated { get; set; }

        // When true, never contact Steam's store API for game names (no network
        // calls at all). Unrelated to BackupEngine's destination-offline concept
        // (a NAS being unreachable) - see AppNameResolver for what this gates.
        public bool OfflineMode { get; set; } = false;

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
