using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace SteamScreenshotBackup
{
    // Injects the resolved game name into image metadata so backups are searchable
    // in Windows Explorer wherever they end up.
    //
    //  - JPEG: a hand-built EXIF APP1 segment (ImageDescription, XPTitle, XPSubject)
    //    inserted right after the SOI marker. The compressed image data is never
    //    touched, so this is completely lossless.
    //  - PNG:  tEXt chunks (Title / Description) inserted after the IHDR chunk.
    //
    // All failures are logged and swallowed: a backup without metadata is still a
    // backup, and this must never break the copy pipeline.
    internal static class Metadata
    {
        public static void TagGameName(string filePath, string gameName)
        {
            try
            {
                string ext = Path.GetExtension(filePath).ToLowerInvariant();
                if (ext == ".jpg" || ext == ".jpeg") TagJpeg(filePath, gameName);
                else if (ext == ".png") TagPng(filePath, gameName);
            }
            catch (Exception ex)
            {
                Logger.Warn($"Could not tag metadata on {Path.GetFileName(filePath)}: {ex.Message}");
            }
        }

        // ---------------------------------------------------------------- JPEG

        private static void TagJpeg(string path, string gameName)
        {
            byte[] file = File.ReadAllBytes(path);
            if (file.Length < 4 || file[0] != 0xFF || file[1] != 0xD8) return;   // not a JPEG

            // If the file already carries an EXIF APP1 block, leave it alone rather
            // than risk clobbering existing metadata (Steam's JPEGs have none).
            if (HasExifSegment(file)) return;

            byte[] app1 = BuildExifApp1(gameName);
            using var fs = new FileStream(path, FileMode.Create, FileAccess.Write);
            fs.Write(file, 0, 2);                    // SOI
            fs.Write(app1, 0, app1.Length);          // our EXIF
            fs.Write(file, 2, file.Length - 2);      // everything else, byte-identical
        }

        private static bool HasExifSegment(byte[] f)
        {
            int pos = 2;
            while (pos + 4 <= f.Length && f[pos] == 0xFF)
            {
                byte marker = f[pos + 1];
                if (marker == 0xDA) break;                     // start of scan; no more headers
                int len = (f[pos + 2] << 8) | f[pos + 3];
                if (marker == 0xE1 && pos + 10 <= f.Length &&
                    f[pos + 4] == 'E' && f[pos + 5] == 'x' && f[pos + 6] == 'i' && f[pos + 7] == 'f')
                    return true;
                pos += 2 + len;
            }
            return false;
        }

        // Minimal EXIF: little-endian TIFF with one IFD holding ImageDescription
        // (ASCII), XPTitle and XPSubject (UTF-16LE byte arrays, the fields Windows
        // Explorer surfaces as Title / Subject).
        private static byte[] BuildExifApp1(string text)
        {
            byte[] ascii = Encoding.ASCII.GetBytes(text.Replace('\uFFFD', '?') + "\0");
            byte[] utf16 = Encoding.Unicode.GetBytes(text + "\0");

            var entries = new List<(ushort Tag, ushort Type, byte[] Data)>
            {
                (0x010E, 2, ascii),   // ImageDescription, ASCII
                (0x9C9B, 1, utf16),   // XPTitle, BYTE
                (0x9C9F, 1, utf16),   // XPSubject, BYTE
            };

            using var tiff = new MemoryStream();
            var w = new BinaryWriter(tiff);
            w.Write((byte)'I'); w.Write((byte)'I');            // little-endian TIFF
            w.Write((ushort)42);
            w.Write(0x00000008u);                              // IFD0 offset

            int dataStart = 8 + 2 + entries.Count * 12 + 4;    // after count+entries+next-IFD
            w.Write((ushort)entries.Count);
            int cursor = dataStart;
            foreach (var (tag, type, data) in entries)
            {
                w.Write(tag);
                w.Write(type);
                w.Write((uint)data.Length);
                if (data.Length <= 4)
                {
                    byte[] inline = new byte[4];
                    Array.Copy(data, inline, data.Length);
                    w.Write(inline);
                }
                else
                {
                    w.Write((uint)cursor);
                    cursor += data.Length;
                }
            }
            w.Write(0u);                                       // no next IFD
            foreach (var (_, _, data) in entries)
                if (data.Length > 4) w.Write(data);

            byte[] tiffBytes = tiff.ToArray();
            using var app1 = new MemoryStream();
            int segLen = 2 + 6 + tiffBytes.Length;             // length field + "Exif\0\0" + tiff
            app1.WriteByte(0xFF); app1.WriteByte(0xE1);
            app1.WriteByte((byte)(segLen >> 8)); app1.WriteByte((byte)(segLen & 0xFF));
            app1.Write(Encoding.ASCII.GetBytes("Exif\0\0"));
            app1.Write(tiffBytes);
            return app1.ToArray();
        }

        // ----------------------------------------------------------------- PNG

        private static void TagPng(string path, string gameName)
        {
            byte[] file = File.ReadAllBytes(path);
            if (file.Length < 33 || file[1] != 'P' || file[2] != 'N' || file[3] != 'G') return;

            // Skip if we (or anything else) already wrote a Title chunk.
            if (IndexOfSequence(file, Encoding.ASCII.GetBytes("tEXtTitle\0")) >= 0) return;

            int ihdrEnd = 8 + 4 + 4 + 13 + 4;   // signature + IHDR length/type/data/crc
            byte[] title = BuildTextChunk("Title", gameName);
            byte[] desc = BuildTextChunk("Description", "Steam screenshot from " + gameName);

            using var fs = new FileStream(path, FileMode.Create, FileAccess.Write);
            fs.Write(file, 0, ihdrEnd);
            fs.Write(title, 0, title.Length);
            fs.Write(desc, 0, desc.Length);
            fs.Write(file, ihdrEnd, file.Length - ihdrEnd);
        }

        private static byte[] BuildTextChunk(string keyword, string text)
        {
            // tEXt payload is Latin-1; degrade unmappable characters to '?'.
            byte[] payload = Encoding.Latin1.GetBytes(keyword + "\0" + text);
            byte[] type = Encoding.ASCII.GetBytes("tEXt");

            using var ms = new MemoryStream();
            ms.WriteByte((byte)(payload.Length >> 24));
            ms.WriteByte((byte)(payload.Length >> 16));
            ms.WriteByte((byte)(payload.Length >> 8));
            ms.WriteByte((byte)payload.Length);
            ms.Write(type);
            ms.Write(payload);

            uint crc = Crc32(type, payload);
            ms.WriteByte((byte)(crc >> 24));
            ms.WriteByte((byte)(crc >> 16));
            ms.WriteByte((byte)(crc >> 8));
            ms.WriteByte((byte)crc);
            return ms.ToArray();
        }

        private static uint[] _crcTable;

        private static uint Crc32(byte[] a, byte[] b)
        {
            if (_crcTable == null)
            {
                _crcTable = new uint[256];
                for (uint n = 0; n < 256; n++)
                {
                    uint c = n;
                    for (int k = 0; k < 8; k++)
                        c = (c & 1) != 0 ? 0xEDB88320 ^ (c >> 1) : c >> 1;
                    _crcTable[n] = c;
                }
            }
            uint crc = 0xFFFFFFFF;
            foreach (byte x in a) crc = _crcTable[(crc ^ x) & 0xFF] ^ (crc >> 8);
            foreach (byte x in b) crc = _crcTable[(crc ^ x) & 0xFF] ^ (crc >> 8);
            return crc ^ 0xFFFFFFFF;
        }

        private static int IndexOfSequence(byte[] haystack, byte[] needle)
        {
            for (int i = 0; i <= haystack.Length - needle.Length; i++)
            {
                bool hit = true;
                for (int j = 0; j < needle.Length; j++)
                    if (haystack[i + j] != needle[j]) { hit = false; break; }
                if (hit) return i;
            }
            return -1;
        }
    }
}
