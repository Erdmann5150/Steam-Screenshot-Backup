using System.IO;
using Microsoft.VisualBasic.FileIO;

namespace SteamScreenshotBackup
{
    // Sends files to the Windows Recycle Bin instead of deleting them permanently,
    // so a mistaken "delete originals" is always recoverable by the user.
    internal static class RecycleBin
    {
        // Returns true if the file was sent to the Recycle Bin (or was already gone).
        public static bool Delete(string path)
        {
            if (!File.Exists(path)) return true;
            // OnlyErrorDialogs = no confirmation UI; SendToRecycleBin = recoverable;
            // ThrowException on cancel so callers can log a genuine failure.
            FileSystem.DeleteFile(path, UIOption.OnlyErrorDialogs,
                RecycleOption.SendToRecycleBin, UICancelOption.ThrowException);
            return true;
        }

        // Sends a whole directory tree to the Recycle Bin.
        public static bool DeleteDirectory(string path)
        {
            if (!Directory.Exists(path)) return true;
            FileSystem.DeleteDirectory(path, UIOption.OnlyErrorDialogs,
                RecycleOption.SendToRecycleBin, UICancelOption.ThrowException);
            return true;
        }
    }
}
