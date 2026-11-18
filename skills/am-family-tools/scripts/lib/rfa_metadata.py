# -*- coding: utf-8 -*-
"""Read family metadata from a Revit family file (.rfa) without Revit.

An .rfa file is a Microsoft compound file (OLE container). It holds named
streams. Two of them help a library search:

- "PartAtom": an XML summary that Revit writes on save. It gives the
  category, the Revit version, the type names and the type parameter
  values (as display text with units).
- "RevitPreview4.0": a short header and the thumbnail as a PNG image.

This module reads only those two streams, with bounded seek reads. It
never runs Revit and never changes the file. It also parses a type
catalog (.txt next to the .rfa).

Pure Python. Runs in CPython 3; the syntax stays IronPython 2.7
compatible (no f-strings, no keyword-only arguments).
"""
import csv
import struct
import zlib
import xml.etree.ElementTree as ET

MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MAXREGSECT = 0xFFFFFFFA
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
NOSTREAM = 0xFFFFFFFF

PART_ATOM = "PartAtom"
PREVIEW = "RevitPreview4.0"
MAX_PART_ATOM_BYTES = 4 * 1024 * 1024
MAX_PREVIEW_BYTES = 1024 * 1024
MAX_DIRECTORY_ENTRIES = 100000
MAX_TYPES = 1000
MAX_PARAMETERS = 300
MAX_TEXT = 500
MAX_IMAGE_SIDE = 1024
MAX_CATALOG_BYTES = 4 * 1024 * 1024
MAX_CATALOG_ROWS = 5000

ATOM = "{http://www.w3.org/2005/Atom}"
PART = "{urn:schemas-autodesk-com:partatom}"
GROUPING = "adsk:revit:grouping"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class MetadataError(ValueError):
    """The file is not a readable family file, or a limit was hit."""


def _u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def _u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


class CompoundFile(object):
    """Bounded, read-only access to the top-level streams of a compound file.

    fileobj must be a binary file object that supports seek and read.
    """

    def __init__(self, fileobj):
        self.f = fileobj
        self.f.seek(0, 2)
        self.file_size = self.f.tell()
        header = self._read_at(0, 512)
        if len(header) < 512 or header[:8] != MAGIC:
            raise MetadataError("Not a compound file (no OLE signature).")
        if _u16(header, 0x1C) != 0xFFFE:
            raise MetadataError("Unsupported byte order in the file header.")
        major = _u16(header, 0x1A)
        shift = _u16(header, 0x1E)
        if (major, shift) not in ((3, 9), (4, 12)):
            raise MetadataError("Unsupported compound file version.")
        if _u16(header, 0x20) != 6:
            raise MetadataError("Unsupported mini sector size.")
        self.sector_size = 1 << shift
        self.mini_size = 64
        body = max(0, self.file_size - self.sector_size)
        self.sector_count = (body + self.sector_size - 1) // self.sector_size
        self.cutoff = _u32(header, 0x38)
        if self.cutoff != 4096:
            raise MetadataError("Unsupported mini stream cutoff.")
        fat_count = _u32(header, 0x2C)
        if fat_count > self.sector_count:
            raise MetadataError("The FAT is larger than the file.")
        difat = list(struct.unpack_from("<109I", header, 0x4C))
        next_difat = _u32(header, 0x44)
        difat_count = _u32(header, 0x48)
        per_sector = self.sector_size // 4
        seen = set()
        for _ in range(difat_count):
            if next_difat >= MAXREGSECT:
                break
            if next_difat in seen:
                raise MetadataError("The DIFAT chain has a loop.")
            seen.add(next_difat)
            values = struct.unpack("<%dI" % per_sector, self._sector(next_difat))
            difat.extend(values[:-1])
            next_difat = values[-1]
        fat_sectors = [s for s in difat if s < MAXREGSECT][:fat_count]
        if len(fat_sectors) != fat_count:
            raise MetadataError("The file header lists fewer FAT sectors than it says.")
        fat = []
        for sector in fat_sectors:
            fat.extend(struct.unpack("<%dI" % per_sector, self._sector(sector)))
        self.fat = fat
        self.entries = self._directory(_u32(header, 0x30))
        root = self.entries[0]
        if root["type"] != 5:
            raise MetadataError("The first directory entry is not the root.")
        self.root = root
        self.mini_fat = []
        mini_fat_start = _u32(header, 0x3C)
        if mini_fat_start < MAXREGSECT:
            for sector in self._chain(mini_fat_start, self.fat):
                self.mini_fat.extend(struct.unpack("<%dI" % per_sector, self._sector(sector)))
        self._root_chain = None

    def _read_at(self, offset, size):
        self.f.seek(offset)
        return self.f.read(size)

    def _sector(self, sector):
        if sector >= self.sector_count:
            raise MetadataError("A sector number points outside the file.")
        data = self._read_at((sector + 1) * self.sector_size, self.sector_size)
        # Some writers do not pad the last sector; the missing bytes read as zero.
        return data + b"\x00" * (self.sector_size - len(data))

    def _chain(self, start, table, limit=None):
        """Sector numbers of a chain. With a limit, stop after that many sectors."""
        chain = []
        seen = set()
        sector = start
        while sector < MAXREGSECT:
            if limit is not None and len(chain) >= limit:
                return chain
            if sector >= len(table) or sector in seen:
                raise MetadataError("A sector chain is broken or has a loop.")
            seen.add(sector)
            chain.append(sector)
            sector = table[sector]
        if sector not in (ENDOFCHAIN, FREESECT):
            raise MetadataError("A sector chain ends with an unexpected marker.")
        return chain

    def _directory(self, start):
        entries = []
        per_sector = self.sector_size // 128
        for sector in self._chain(start, self.fat):
            data = self._sector(sector)
            for i in range(per_sector):
                raw = data[i * 128:(i + 1) * 128]
                name_len = _u16(raw, 64)
                if name_len > 64 or name_len % 2:
                    name = u""
                else:
                    name = raw[:max(0, name_len - 2)].decode("utf-16-le", "replace")
                entries.append({
                    "name": name,
                    "type": bytearray(raw[66:67])[0],
                    "left": _u32(raw, 68),
                    "right": _u32(raw, 72),
                    "child": _u32(raw, 76),
                    "start": _u32(raw, 116),
                    "size": struct.unpack_from("<Q", raw, 120)[0],
                })
                if len(entries) > MAX_DIRECTORY_ENTRIES:
                    raise MetadataError("The file has too many directory entries.")
        if not entries:
            raise MetadataError("The file has no directory.")
        return entries

    def top_level(self):
        """Map of name -> entry for the streams directly under the root."""
        found = {}
        stack = [self.root["child"]]
        seen = set()
        while stack:
            index = stack.pop()
            if index == NOSTREAM:
                continue
            if index >= len(self.entries) or index in seen:
                raise MetadataError("The directory tree is broken or has a loop.")
            seen.add(index)
            entry = self.entries[index]
            if entry["type"] == 2:
                found[entry["name"]] = entry
            stack.append(entry["left"])
            stack.append(entry["right"])
        return found

    def read_stream(self, entry, maximum):
        size = entry["size"]
        if self.sector_size == 512:
            size &= 0xFFFFFFFF
        if size > maximum:
            raise MetadataError("The %s stream is larger than its limit." % entry["name"])
        if size == 0:
            return b""
        parts = []
        if size < self.cutoff:
            needed = (size + self.mini_size - 1) // self.mini_size
            if self._root_chain is None:
                self._root_chain = self._chain(self.root["start"], self.fat)
            for mini in self._chain(entry["start"], self.mini_fat, needed):
                offset = mini * self.mini_size
                index = offset // self.sector_size
                if index >= len(self._root_chain):
                    raise MetadataError("A mini sector points outside the mini stream.")
                sector = self._root_chain[index]
                start = (sector + 1) * self.sector_size + offset % self.sector_size
                parts.append(self._read_at(start, self.mini_size))
        else:
            needed = (size + self.sector_size - 1) // self.sector_size
            for sector in self._chain(entry["start"], self.fat, needed):
                parts.append(self._sector(sector))
        data = b"".join(parts)
        if len(data) < size:
            raise MetadataError("The %s stream is shorter than its size." % entry["name"])
        return data[:size]


def _text(value):
    if value is None:
        return None
    value = " ".join(value.split())
    return value[:MAX_TEXT]


def _local(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def parse_part_atom(data):
    """Category, Revit version and types with parameter values from PartAtom XML.

    Returns {"category", "omniclass", "revit_version", "types": [{"name",
    "parameters": [{"name", "value", "kind", "units"}]}], "types_truncated"}.
    """
    if len(data) > MAX_PART_ATOM_BYTES:
        raise MetadataError("The PartAtom stream is larger than its limit.")
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise MetadataError("The PartAtom XML has a DOCTYPE or ENTITY; it is not read.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise MetadataError("The PartAtom XML does not parse.")
    if root.tag != ATOM + "entry":
        raise MetadataError("The PartAtom XML has an unexpected root element.")
    result = {"category": None, "omniclass": None, "revit_version": None,
              "types": [], "types_truncated": False}
    for category in root.findall(ATOM + "category"):
        term = _text(category.findtext(ATOM + "term"))
        scheme = _text(category.findtext(ATOM + "scheme"))
        if scheme == GROUPING and term and result["category"] is None:
            result["category"] = term
        elif scheme == "std:oc1" and term and result["omniclass"] is None:
            result["omniclass"] = term
    for link in root.findall(ATOM + "link"):
        version = _text(link.findtext(PART + "design-file/" + PART + "product-version"))
        if version:
            result["revit_version"] = version
            break
    family = root.find(PART + "family")
    if family is None:
        return result
    for part in family.findall(PART + "part"):
        if len(result["types"]) >= MAX_TYPES:
            result["types_truncated"] = True
            break
        name = _text(part.findtext(ATOM + "title"))
        if not name:
            continue
        parameters = []
        for child in list(part):
            if child.tag == ATOM + "title" or len(parameters) >= MAX_PARAMETERS:
                continue
            label = child.get("displayName") or _local(child.tag)
            parameters.append({
                "name": _text(label),
                "value": _text(child.text) or u"",
                "kind": _text(child.get("typeOfParameter")),
                "units": _text(child.get("units")),
            })
        result["types"].append({"name": name, "parameters": parameters})
    return result


def thumbnail_png(data):
    """The PNG image inside a RevitPreview4.0 stream, or None.

    Returns {"png": bytes, "width": int, "height": int} or None.
    Every chunk CRC is checked; a damaged image returns None.
    """
    start = data.find(PNG_SIGNATURE)
    if start < 0:
        return None
    pos = start + len(PNG_SIGNATURE)
    width = height = None
    while True:
        if pos + 12 > len(data):
            return None
        length = struct.unpack_from(">I", data, pos)[0]
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if length > MAX_PREVIEW_BYTES or end > len(data):
            return None
        body = data[pos + 8:pos + 8 + length]
        crc = struct.unpack_from(">I", data, pos + 8 + length)[0]
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            return None
        if width is None:
            if kind != b"IHDR" or length != 13:
                return None
            width, height = struct.unpack(">II", body[:8])
            if not (0 < width <= MAX_IMAGE_SIDE and 0 < height <= MAX_IMAGE_SIDE):
                return None
        pos = end
        if kind == b"IEND":
            return {"png": data[start:pos], "width": width, "height": height}


def read_family_file(path, want_thumbnail=False):
    """Metadata of one .rfa file. Never raises for a bad file: it reports.

    Returns {"status": "ok" | "no_metadata" | "unreadable", "reason",
    "category", "omniclass", "revit_version", "types", "types_truncated",
    "thumbnail"} where thumbnail is the PNG dict or None.
    """
    result = {"status": "ok", "reason": None, "category": None, "omniclass": None,
              "revit_version": None, "types": [], "types_truncated": False,
              "thumbnail": None}
    try:
        with open(path, "rb") as f:
            container = CompoundFile(f)
            streams = container.top_level()
            atom = streams.get(PART_ATOM)
            if atom is None:
                result["status"] = "no_metadata"
                result["reason"] = "The file has no PartAtom stream."
            else:
                result.update(parse_part_atom(container.read_stream(atom, MAX_PART_ATOM_BYTES)))
            preview = streams.get(PREVIEW)
            if want_thumbnail and preview is not None:
                result["thumbnail"] = thumbnail_png(container.read_stream(preview, MAX_PREVIEW_BYTES))
    except (MetadataError, struct.error, IOError, OSError) as exc:
        result["status"] = "unreadable"
        result["reason"] = str(exc)
    return result


def _decode_catalog(data):
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16"), None
    try:
        return data.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        return data.decode("latin-1"), "The catalog is not UTF-8 or UTF-16; it was read as Latin-1."


def _split(line, delimiter):
    return next(csv.reader([line], delimiter=delimiter))


def parse_type_catalog(data):
    """Type names and values from a Revit type catalog (.txt).

    The first line is the header: an empty first field, then one
    "Name##SPEC##UNITS" field per parameter. Each later line is one type.
    Returns {"parameters": [{"name", "spec", "units"}],
    "types": [{"name", "parameters": [{"name", "value", "kind", "units"}]}],
    "issues": [text]}.
    """
    result = {"parameters": [], "types": [], "issues": []}
    if len(data) > MAX_CATALOG_BYTES:
        result["issues"].append("The catalog is larger than its limit; it was not read.")
        return result
    text, note = _decode_catalog(data)
    if note:
        result["issues"].append(note)
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        result["issues"].append("The catalog is empty.")
        return result
    delimiter = lines[0][0]
    if delimiter.isalnum() or delimiter in "\"#":
        result["issues"].append("The catalog header must start with its delimiter (usually a comma).")
        return result
    try:
        header = _split(lines[0], delimiter)
    except Exception:
        result["issues"].append("The catalog header does not parse.")
        return result
    definitions = []
    for field in header[1:]:
        parts = field.split("##")
        definitions.append({
            "name": _text(parts[0]) or u"",
            "spec": _text(parts[1]) if len(parts) > 1 else None,
            "units": _text(parts[2]) if len(parts) > 2 else None,
        })
    result["parameters"] = definitions
    seen = set()
    for number, line in enumerate(lines[1:], 2):
        if len(result["types"]) >= MAX_CATALOG_ROWS:
            result["issues"].append("The catalog has more than %d types; the rest were not read." % MAX_CATALOG_ROWS)
            break
        try:
            cells = _split(line, delimiter)
        except Exception:
            result["issues"].append("Line %d does not parse." % number)
            continue
        name = _text(cells[0]) if cells else None
        if not name:
            result["issues"].append("Line %d has no type name." % number)
            continue
        if name.lower() in seen:
            result["issues"].append("Line %d repeats the type name %s." % (number, name))
            continue
        seen.add(name.lower())
        values = []
        for definition, cell in zip(definitions, cells[1:]):
            values.append({"name": definition["name"], "value": _text(cell) or u"",
                           "kind": definition["spec"], "units": definition["units"]})
        result["types"].append({"name": name, "parameters": values})
    return result
