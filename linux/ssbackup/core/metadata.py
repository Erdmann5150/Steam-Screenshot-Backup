"""Injects the resolved game name into image metadata so backups are searchable.

Byte-for-byte the same output the Windows app produces, which matters because
both can write into the same destination:

 - JPEG: a hand-built EXIF APP1 segment (ImageDescription, XPTitle, XPSubject).
 - PNG:  an XMP packet in an iTXt chunk (dc:title, dc:subject), plus a plain
         tEXt Title.

On Linux, KDE's Baloo and GNOME's Tracker both index XMP dc:title and
dc:subject, so the names surface in Dolphin and Files search the same way they
surface in Explorer.  The XP* EXIF tags are Windows-specific but harmless, and
keeping them means a backup copied to a Windows machine stays searchable there.

Both paths only insert metadata segments - the compressed image data is never
re-encoded, so tagging is lossless - and the file's timestamps are preserved.
All failures are logged and swallowed: a backup without metadata is still a
backup, and this must never break the copy pipeline.
"""

from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path
from xml.sax.saxutils import escape

from .logger import Logger

XMP_KEYWORD = b"XML:com.adobe.xmp"


def tag_game_name(file_path: str | Path, game_name: str) -> None:
    p = Path(file_path)
    try:
        st = p.stat()
        atime, mtime = st.st_atime, st.st_mtime

        ext = p.suffix.lower()
        if ext in (".jpg", ".jpeg"):
            changed = _tag_jpeg(p, game_name)
        elif ext == ".png":
            changed = _tag_png(p, game_name)
        else:
            changed = False

        # Keep the capture/backup timestamps; writing metadata would otherwise
        # stamp the file with "now".
        if changed:
            try:
                os.utime(p, (atime, mtime))
            except OSError:
                pass
    except Exception as ex:
        Logger.warn(f"Could not tag metadata on {p.name}: {ex}")


def has_game_name_metadata(file_path: str | Path) -> bool:
    """True if the file already carries our game-name metadata.

    Used by the backfill so it doesn't rewrite files that are already tagged.
    Reads only the header, where the metadata is always placed, so it stays
    cheap across a large backup.
    """
    p = Path(file_path)
    try:
        ext = p.suffix.lower()
        head = _read_head(p, 65536)
        if ext in (".jpg", ".jpeg"):
            return _has_exif_segment(head)
        if ext == ".png":
            return XMP_KEYWORD in head
    except OSError:
        pass
    return False


def _read_head(path: Path, max_bytes: int) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(max_bytes)


# ------------------------------------------------------------------- JPEG

def _tag_jpeg(path: Path, game_name: str) -> bool:
    data = path.read_bytes()
    if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
        return False  # not a JPEG

    # If the file already carries an EXIF APP1 block, leave it alone rather
    # than risk clobbering existing metadata (Steam's JPEGs have none).
    if _has_exif_segment(data):
        return False

    app1 = _build_exif_app1(game_name)
    tmp = path.with_name(path.name + ".ssbtmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data[:2])      # SOI
            fh.write(app1)          # our EXIF
            fh.write(data[2:])      # everything else, byte-identical
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return True


def _has_exif_segment(f: bytes) -> bool:
    pos = 2
    while pos + 4 <= len(f) and f[pos] == 0xFF:
        marker = f[pos + 1]
        if marker == 0xDA:   # start of scan; no more headers
            break
        length = (f[pos + 2] << 8) | f[pos + 3]
        if length < 2:
            break
        if marker == 0xE1 and pos + 10 <= len(f) and f[pos + 4:pos + 8] == b"Exif":
            return True
        pos += 2 + length
    return False


def _build_exif_app1(text: str) -> bytes:
    """Minimal EXIF: little-endian TIFF with one IFD holding ImageDescription
    (ASCII), XPTitle and XPSubject (UTF-16LE byte arrays).  Tags must be in
    ascending order."""
    ascii_bytes = (text.replace("�", "?").encode("ascii", errors="replace")
                   + b"\x00")
    utf16 = (text + "\x00").encode("utf-16-le")

    entries = [
        (0x010E, 2, ascii_bytes),   # ImageDescription, ASCII
        (0x9C9B, 1, utf16),         # XPTitle, BYTE
        (0x9C9F, 1, utf16),         # XPSubject, BYTE
    ]

    out = bytearray()
    out += b"II"                        # little-endian TIFF
    out += struct.pack("<H", 42)
    out += struct.pack("<I", 8)         # IFD0 offset

    data_start = 8 + 2 + len(entries) * 12 + 4   # after count+entries+next-IFD
    out += struct.pack("<H", len(entries))
    cursor = data_start
    trailing = bytearray()
    for tag, type_id, payload in entries:
        out += struct.pack("<HHI", tag, type_id, len(payload))
        if len(payload) <= 4:
            out += payload.ljust(4, b"\x00")
        else:
            out += struct.pack("<I", cursor)
            cursor += len(payload)
            trailing += payload
    out += struct.pack("<I", 0)         # no next IFD
    out += trailing

    tiff = bytes(out)
    seg_len = 2 + 6 + len(tiff)         # length field + "Exif\0\0" + tiff
    return (b"\xFF\xE1" + struct.pack(">H", seg_len)
            + b"Exif\x00\x00" + tiff)


# -------------------------------------------------------------------- PNG

def _tag_png(path: Path, game_name: str) -> bool:
    data = path.read_bytes()
    if len(data) < 33 or data[1:4] != b"PNG":
        return False

    # Skip if our XMP is already present.
    if XMP_KEYWORD in data:
        return False

    ihdr_end = 8 + 4 + 4 + 13 + 4   # signature + IHDR length/type/data/crc
    xmp = _build_xmp_itxt_chunk(game_name)            # what indexers read
    title = _build_text_chunk("Title", game_name)     # tEXt for other tools
    desc = _build_text_chunk("Description", f"Steam screenshot from {game_name}")

    tmp = path.with_name(path.name + ".ssbtmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data[:ihdr_end])
            fh.write(xmp)
            fh.write(title)
            fh.write(desc)
            fh.write(data[ihdr_end:])
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return True


def _build_xmp_itxt_chunk(game: str) -> bytes:
    """An "XML:com.adobe.xmp" iTXt chunk carrying dc:title and dc:subject."""
    g = escape(game)
    xmp = (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:title><rdf:Alt><rdf:li xml:lang="x-default">{g}</rdf:li></rdf:Alt></dc:title>'
        f'<dc:subject><rdf:Bag><rdf:li>{g}</rdf:li></rdf:Bag></dc:subject>'
        '</rdf:Description></rdf:RDF></x:xmpmeta>'
        '<?xpacket end="w"?>'
    )

    payload = bytearray()
    payload += XMP_KEYWORD
    payload += b"\x00"   # keyword null terminator
    payload += b"\x00"   # compression flag = uncompressed
    payload += b"\x00"   # compression method
    payload += b"\x00"   # empty language tag + null
    payload += b"\x00"   # empty translated keyword + null
    payload += xmp.encode("utf-8")
    return _build_chunk(b"iTXt", bytes(payload))


def _build_text_chunk(keyword: str, text: str) -> bytes:
    # tEXt payload is Latin-1; degrade unmappable characters to '?'.
    payload = (keyword + "\x00" + text).encode("latin-1", errors="replace")
    return _build_chunk(b"tEXt", payload)


def _build_chunk(type_name: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(type_name + payload) & 0xFFFFFFFF
    return (struct.pack(">I", len(payload)) + type_name + payload
            + struct.pack(">I", crc))
