# -*- coding: utf-8 -*-
"""Build tiny VBA projects in code for the tests.

The writer follows [MS-CFB] and [MS-OVBA] closely enough for the reader. Excel
may not open these files; the tests need only the reader to accept them.
All module text is made up for the tests.
"""

import io
import struct
import zipfile

SECTOR = 512
MINI = 64
CUTOFF = 4096
FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
NOSTREAM = 0xFFFFFFFF


def compress(data, raw_full_chunks=False):
    """[MS-OVBA] 2.4.1 compression with a small match search."""
    out = bytearray(b"\x01")
    for start in range(0, len(data), 4096):
        chunk = data[start:start + 4096]
        if raw_full_chunks and len(chunk) == 4096:
            out += struct.pack("<H", 0x3FFF) + chunk
            continue
        body = bytearray()
        heads = {}
        i = 0
        while i < len(chunk):
            flag_at = len(body)
            body.append(0)
            flags = 0
            for bit in range(8):
                if i >= len(chunk):
                    break
                best_len = best_off = 0
                if i > 0 and i + 3 <= len(chunk):
                    bit_count = max((i - 1).bit_length(), 4)
                    max_len = (0xFFFF >> bit_count) + 3
                    max_off = 1 << (16 - bit_count)
                    for cand in reversed(heads.get(bytes(chunk[i:i + 3]), [])[-64:]):
                        off = i - cand
                        if off > max_off:
                            break
                        n = 0
                        while n < max_len and i + n < len(chunk) and chunk[cand + n] == chunk[i + n]:
                            n += 1
                        if n > best_len:
                            best_len, best_off = n, off
                step = best_len if best_len >= 3 else 1
                for k in range(i, i + step):
                    if k + 3 <= len(chunk):
                        heads.setdefault(bytes(chunk[k:k + 3]), []).append(k)
                if best_len >= 3:
                    token = ((best_off - 1) << (16 - bit_count)) | (best_len - 3)
                    body += struct.pack("<H", token)
                    flags |= 1 << bit
                else:
                    body.append(chunk[i])
                i += step
            body[flag_at] = flags
        out += struct.pack("<H", 0xB000 | (len(body) - 1)) + body
    return bytes(out)


def build_cfb(tree):
    """tree: {name: bytes or {name: ...}} under the root storage."""
    entries = []

    def add(name, node, kind):
        index = len(entries)
        entry = {"name": name, "type": kind, "left": NOSTREAM, "right": NOSTREAM, "child": NOSTREAM,
                 "data": b"", "start": ENDOFCHAIN, "size": 0}
        entries.append(entry)
        if isinstance(node, dict):
            kids = [add(k, v, 1 if isinstance(v, dict) else 2)
                    for k, v in sorted(node.items(), key=lambda kv: (len(kv[0]), kv[0].upper()))]
            if kids:
                entry["child"] = kids[0]
                for a, b in zip(kids, kids[1:]):
                    entries[a]["right"] = b
        else:
            entry["data"] = node
        return index

    add("Root Entry", tree, 5)
    sectors = []
    fat = []

    def alloc(blob):
        if not blob:
            return ENDOFCHAIN
        count = (len(blob) + SECTOR - 1) // SECTOR
        first = len(sectors)
        for n in range(count):
            piece = blob[n * SECTOR:(n + 1) * SECTOR]
            sectors.append(piece + b"\x00" * (SECTOR - len(piece)))
            fat.append(first + n + 1 if n < count - 1 else ENDOFCHAIN)
        return first

    mini = bytearray()
    minifat = []
    for entry in entries:
        if entry["type"] != 2:
            continue
        data = entry["data"]
        entry["size"] = len(data)
        if not data:
            continue
        if len(data) < CUTOFF:
            first = len(mini) // MINI
            count = (len(data) + MINI - 1) // MINI
            mini += data + b"\x00" * (count * MINI - len(data))
            for n in range(count):
                minifat.append(first + n + 1 if n < count - 1 else ENDOFCHAIN)
            entry["start"] = first
        else:
            entry["start"] = alloc(data)
    entries[0]["start"] = alloc(bytes(mini))
    entries[0]["size"] = len(mini)
    minifat_start = ENDOFCHAIN
    minifat_sectors = 0
    if minifat:
        per = SECTOR // 4
        padded = minifat + [FREESECT] * (-len(minifat) % per)
        minifat_sectors = len(padded) // per
        minifat_start = alloc(struct.pack("<%dI" % len(padded), *padded))
    raw_dir = bytearray()
    for entry in entries + [None] * (-len(entries) % 4):
        if entry is None:
            raw_dir += b"\x00" * 64 + struct.pack("<HBB", 0, 0, 0) + struct.pack("<III", NOSTREAM, NOSTREAM, NOSTREAM)
            raw_dir += b"\x00" * 36 + struct.pack("<IQ", 0, 0)
            continue
        name = (entry["name"] + "\x00").encode("utf-16-le")
        raw_dir += name + b"\x00" * (64 - len(name))
        raw_dir += struct.pack("<HBB", len(name), entry["type"], 1)
        raw_dir += struct.pack("<III", entry["left"], entry["right"], entry["child"])
        raw_dir += b"\x00" * 36
        raw_dir += struct.pack("<IQ", entry["start"], entry["size"])
    dir_start = alloc(bytes(raw_dir))
    fat_count = 1
    while len(fat) + fat_count > fat_count * (SECTOR // 4):
        fat_count += 1
    fat_ids = list(range(len(sectors), len(sectors) + fat_count))
    fat += [FATSECT] * fat_count
    fat += [FREESECT] * (fat_count * (SECTOR // 4) - len(fat))
    header = bytearray()
    header += b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1" + b"\x00" * 16
    header += struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\x00" * 6
    header += struct.pack("<IIIIIIIII", 0, fat_count, dir_start, 0, CUTOFF, minifat_start,
                          minifat_sectors, ENDOFCHAIN, 0)
    difat = fat_ids + [FREESECT] * (109 - len(fat_ids))
    header += struct.pack("<109I", *difat)
    assert len(header) == 512
    body = b"".join(sectors) + struct.pack("<%dI" % len(fat), *fat)
    return bytes(header) + body


def record(rid, data=b""):
    return struct.pack("<HI", rid, len(data)) + data


def build_dir(modules, codepage, project_name, offsets):
    out = bytearray()
    out += record(0x0001, struct.pack("<I", 1))
    out += record(0x004A, struct.pack("<I", 2))
    out += record(0x0002, struct.pack("<I", 0x409))
    out += record(0x0014, struct.pack("<I", 0x409))
    out += record(0x0003, struct.pack("<H", codepage))
    out += record(0x0004, project_name.encode("ascii"))
    out += record(0x0005) + record(0x0040)
    out += record(0x0006) + record(0x003D)
    out += record(0x0007, struct.pack("<I", 0))
    out += record(0x0008, struct.pack("<I", 0))
    out += struct.pack("<HIIH", 0x0009, 4, 1, 2)  # PROJECTVERSION: size field 4, body 6 bytes
    out += record(0x000C) + record(0x003C)
    libid = b"*\\G{00000000-0000-0000-0000-000000000000}#2.0#0#stdole#Test Library"
    out += record(0x0016, b"stdole") + record(0x003E, "stdole".encode("utf-16-le"))
    out += record(0x000D, struct.pack("<I", len(libid)) + libid + struct.pack("<IH", 0, 0))
    out += record(0x000F, struct.pack("<H", len(modules)))
    out += record(0x0013, struct.pack("<H", 0xFFFF))
    for (name, kind, _text), offset in zip(modules, offsets):
        out += record(0x0019, name.encode("ascii")) + record(0x0047, name.encode("utf-16-le"))
        out += record(0x001A, name.encode("ascii")) + record(0x0032, name.encode("utf-16-le"))
        out += record(0x001C) + record(0x0048)
        out += record(0x0031, struct.pack("<I", offset))
        out += record(0x001E, struct.pack("<I", 0))
        out += record(0x002C, struct.pack("<H", 0xFFFF))
        out += record(0x0021 if kind == "module" else 0x0022)
        out += record(0x002B)
    out += record(0x0010)
    return bytes(out)


def build_vba_storage(modules, codepage=1252, project_name="VBAProject", raw_full_chunks=False):
    """modules: list of (name, kind, source text). Kind: module, class, document."""
    codec = "cp%d" % codepage
    vba = {"_VBA_PROJECT": b"\xCC\x61\xFF\xFF\x00\x00\x00"}
    offsets = []
    for index, (name, _kind, text) in enumerate(modules):
        cache = bytes((index * 7 + n) % 251 for n in range(23 + index))  # stand-in for compiled code
        offsets.append(len(cache))
        vba[name] = cache + compress(text.encode(codec), raw_full_chunks)
    vba["dir"] = compress(build_dir(modules, codepage, project_name, offsets))
    lines = ['ID="{00000000-0000-0000-0000-000000000000}"']
    for name, kind, _text in modules:
        if kind == "document":
            lines.append("Document=%s/&H00000000" % name)
        elif kind == "class":
            lines.append("Class=%s" % name)
        else:
            lines.append("Module=%s" % name)
    lines.append('Name="%s"' % project_name)
    project = ("\r\n".join(lines) + "\r\n").encode(codec)
    return {"PROJECT": project, "PROJECTwm": b"", "VBA": vba}


def build_vba_project_bin(modules, **kwargs):
    return build_cfb(build_vba_storage(modules, **kwargs))


def build_xlsm(path, modules, **kwargs):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<?xml version=\"1.0\"?><Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/vbaProject.bin", build_vba_project_bin(modules, **kwargs))
    return path


def build_xls(path, modules, **kwargs):
    tree = {"Workbook": b"\x09\x08" + b"\x00" * 600, "_VBA_PROJECT_CUR": build_vba_storage(modules, **kwargs)}
    with open(path, "wb") as handle:
        handle.write(build_cfb(tree))
    return path


SAMPLE_MODULES = [
    ("ThisWorkbook", "document",
     "Attribute VB_Name = \"ThisWorkbook\"\r\nAttribute VB_Base = \"0{00020819-0000-0000-C000-000000000046}\"\r\n"
     "Attribute VB_GlobalNameSpace = False\r\nOption Explicit\r\n"),
    ("Keynotes", "module",
     "Attribute VB_Name = \"Keynotes\"\r\n"
     "Option Explicit\r\n"
     "\r\n"
     "Private mCount As Long\r\n"
     "Public Const SHEET_NAME As String = \"Keys\"\r\n"
     "\r\n"
     "Public Sub ExportKeys()\r\n"
     "    Dim ws As Worksheet, lastRow As Long\r\n"
     "    Set ws = ThisWorkbook.Worksheets(SHEET_NAME)\r\n"
     "    lastRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row\r\n"
     "    For i = 2 To lastRow\r\n"
     "        keyText = ws.Cells(i, 1).Value ' note: \"x = 1\" in a comment\r\n"
     "        If keyText = \"\" Then skipped = skipped + 1\r\n"
     "        mCount = mCount + 1\r\n"
     "        Cells(i, 3) = \"done: ok\"\r\n"
     "    Next i\r\n"
     "    ExportKeys_Count = _\r\n"
     "        mCount\r\n"
     "End Sub\r\n"
     "\r\n"
     "Public Function KeyCount(ByVal start As Long, Optional ByRef stop_at As Long = 0) As Long\r\n"
     "    Dim n As Long\r\n"
     "    n = start: KeyCount = n + mCount\r\n"
     "    stop_at = n\r\n"
     "End Function\r\n"),
    ("KeyItem", "class",
     "Attribute VB_Name = \"KeyItem\"\r\nAttribute VB_PredeclaredId = False\r\n"
     "Public Key As String\r\n"
     "Public Sub Clear()\r\n"
     "    Key = \"\"\r\n"
     "    total = 0\r\n"
     "End Sub\r\n"),
]
