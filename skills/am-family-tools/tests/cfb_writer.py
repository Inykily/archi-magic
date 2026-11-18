# -*- coding: utf-8 -*-
"""Test helper: write a small compound file (the container format of .rfa files).

Version 3, 512-byte sectors. Streams under 4096 bytes go to the mini
stream, larger ones to normal sectors, so tests reach both read paths.
All content in the tests is invented. No real family file is used.
"""
import struct
import zlib

MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
SS = 512
MINI = 64
END = 0xFFFFFFFE
FREE = 0xFFFFFFFF
FATSECT = 0xFFFFFFFD
NOSTREAM = 0xFFFFFFFF


def _entry(name, kind, start, size, child=NOSTREAM, right=NOSTREAM):
    raw = name.encode("utf-16-le") + b"\x00\x00"
    data = raw.ljust(64, b"\x00")
    data += struct.pack("<HBB", len(raw), kind, 1)
    data += struct.pack("<III", NOSTREAM, right, child)
    data += b"\x00" * 36
    data += struct.pack("<IQ", start, size)
    return data


EMPTY_ENTRY = (b"\x00" * 64 + struct.pack("<HBB", 0, 0, 0)
               + struct.pack("<III", NOSTREAM, NOSTREAM, NOSTREAM)
               + b"\x00" * 36 + struct.pack("<IQ", 0, 0))


def build(streams):
    """streams: list of (name, bytes) at the top level. Returns file bytes."""
    sectors = []
    fat = []

    def alloc(data):
        if not data:
            return END
        count = (len(data) + SS - 1) // SS
        start = len(sectors)
        for i in range(count):
            sectors.append(data[i * SS:(i + 1) * SS].ljust(SS, b"\x00"))
            fat.append(start + i + 1 if i < count - 1 else END)
        return start

    mini = b""
    mini_fat = []
    entries = []
    for name, data in streams:
        if 0 < len(data) < 4096:
            start = len(mini) // MINI
            count = (len(data) + MINI - 1) // MINI
            mini += data.ljust(count * MINI, b"\x00")
            for i in range(count):
                mini_fat.append(start + i + 1 if i < count - 1 else END)
        elif data:
            start = alloc(data)
        else:
            start = END
        entries.append((name, start, len(data)))
    root_start = alloc(mini)
    mini_fat_bytes = b"".join(struct.pack("<I", v) for v in mini_fat)
    if mini_fat_bytes:
        pad = (-len(mini_fat_bytes)) % SS
        mini_fat_bytes += struct.pack("<I", FREE) * (pad // 4)
    mini_fat_start = alloc(mini_fat_bytes)
    directory = _entry("Root Entry", 5, root_start, len(mini), child=1 if entries else NOSTREAM)
    for i, (name, start, size) in enumerate(entries):
        right = i + 2 if i + 1 < len(entries) else NOSTREAM
        directory += _entry(name, 2, start, size, right=right)
    while len(directory) % SS:
        directory += EMPTY_ENTRY
    directory_start = alloc(directory)
    fat_count = 1
    while len(sectors) + fat_count > fat_count * (SS // 4):
        fat_count += 1
    fat_start = len(sectors)
    fat.extend([FATSECT] * fat_count)
    fat.extend([FREE] * (fat_count * (SS // 4) - len(fat)))
    for i in range(fat_count):
        sectors.append(struct.pack("<128I", *fat[i * 128:(i + 1) * 128]))
    header = MAGIC + b"\x00" * 16
    header += struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\x00" * 6
    header += struct.pack("<IIIIIIIII", 0, fat_count, directory_start, 0, 4096,
                          mini_fat_start, len(mini_fat_bytes) // SS, END, 0)
    header += struct.pack("<109I", *([fat_start + i for i in range(fat_count)] + [FREE] * (109 - fat_count)))
    assert len(header) == 512
    return header + b"".join(sectors)


def fat_offset(data, sector):
    """Byte offset of the FAT entry for a sector (first FAT sector only)."""
    first_fat = struct.unpack_from("<I", data, 0x4C)[0]
    return (first_fat + 1) * SS + 4 * sector


def png(width=2, height=2):
    """A small valid PNG image."""
    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + b"\x80" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def part_atom(category, types, version="2026", omniclass=None):
    """PartAtom XML like Revit writes. types: list of (name, [(param, value, kind, units)])."""
    parts = []
    for name, parameters in types:
        cells = []
        for i, (label, value, kind, units) in enumerate(parameters):
            tag = "P%d" % i
            unit = ' units="%s"' % units if units else ""
            cells.append('<%s displayName="%s" type="custom" typeOfParameter="%s"%s>%s</%s>'
                         % (tag, label, kind, unit, value, tag))
        parts.append('<A:part type="user"><title>%s</title>%s</A:part>' % (name, "".join(cells)))
    oc = ('<category><term>%s</term><scheme>std:oc1</scheme></category>' % omniclass) if omniclass else ""
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<entry xmlns="http://www.w3.org/2005/Atom" xmlns:A="urn:schemas-autodesk-com:partatom">'
           '<title>0123456789abcdef</title><id></id>'
           '%s<category><term>%s</term><scheme>adsk:revit:grouping</scheme></category>'
           '<link rel="design-2d" type="application/rfa" href="."><A:design-file>'
           '<A:product>Revit</A:product><A:product-version>%s</A:product-version>'
           '</A:design-file></link>'
           '<A:family type="user"><A:variationCount>%d</A:variationCount>%s</A:family></entry>'
           % (oc, category, version, len(types), "".join(parts)))
    return xml.encode("utf-8")


def family_file(category, types, thumbnail=True, padding=0, version="2026"):
    """Bytes of a synthetic .rfa with PartAtom and an optional preview stream."""
    atom = part_atom(category, types, version)
    if padding:
        atom = atom.replace(b"<id></id>", b"<id></id><!--" + b"x" * padding + b"-->")
    streams = [("BasicFileInfo", b"\x00" * 100), ("PartAtom", atom)]
    if thumbnail:
        streams.append(("RevitPreview4.0", b"\x01\x02header" + png() + b"tail"))
    return build(streams)
