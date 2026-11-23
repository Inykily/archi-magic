# -*- coding: utf-8 -*-
"""Read, check and plan edits of the VBA macros in an Excel workbook.

Runs on the user's computer with the Python standard library only. It never
starts Excel and never writes to the workbook.

Commands:
  find    list macro workbooks in shallow folders (Downloads and Desktop by default)
  dump    print every VBA module, or write each module to a new folder
  scan    heuristic check: modules without Option Explicit, undeclared variables
  plan    preview text edits as a diff and write a plan file for vba_apply.ps1
  verify  read an edited copy back and compare it with the plan

Formats: .xlsm, .xlsb, .xlam, .xltm (a zip with xl/vbaProject.bin) and the older
.xls/.xla (a compound file). The reader follows [MS-CFB] (compound file) and
[MS-OVBA] (VBA project storage and its compression).

Exit codes: 0 done, 1 verify found differences, 2 input or format error.
"""

from __future__ import print_function

import argparse
import difflib
import hashlib
import json
import os
import re
import struct
import sys
import time
import zipfile

PLAN_FORMAT = "am-excel-vba-plan/1"
MACRO_EXTENSIONS = (".xlsm", ".xlsb", ".xlam", ".xltm", ".xls", ".xla")
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_PROJECT_BYTES = 100 * 1024 * 1024
MAX_LINE_CHARS = 1023  # the VBA editor limit for one physical line

CFB_SIGNATURE = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
NOSTREAM = 0xFFFFFFFF


class VbaError(ValueError):
    """The input cannot be read as a VBA project."""


# --------------------------------------------------------------------------
# Compound file reader ([MS-CFB])
# --------------------------------------------------------------------------


class CompoundFile(object):
    def __init__(self, data):
        if len(data) < 512 or data[:8] != CFB_SIGNATURE:
            raise VbaError("not a compound file")
        byte_order, sector_shift, mini_shift = struct.unpack_from("<HHH", data, 28)
        if byte_order != 0xFFFE or sector_shift not in (9, 12) or mini_shift != 6:
            raise VbaError("unsupported compound file header")
        self.data = data
        self.sector_size = 1 << sector_shift
        self.mini_size = 1 << mini_shift
        (num_fat, first_dir, _txn, self.mini_cutoff, first_minifat, num_minifat,
         first_difat, num_difat) = struct.unpack_from("<IIIIIIII", data, 44)
        self.max_sectors = max(0, (len(data) - self.sector_size) // self.sector_size) + 1
        fat_sectors = [s for s in struct.unpack_from("<109I", data, 76) if s not in (FREESECT, ENDOFCHAIN)]
        per_difat = self.sector_size // 4 - 1
        sector = first_difat
        seen = set()
        while sector not in (FREESECT, ENDOFCHAIN) and len(seen) < num_difat + 1:
            if sector in seen or sector >= self.max_sectors:
                raise VbaError("broken DIFAT chain")
            seen.add(sector)
            values = struct.unpack_from("<%dI" % (per_difat + 1), self._sector(sector))
            fat_sectors.extend(s for s in values[:per_difat] if s not in (FREESECT, ENDOFCHAIN))
            sector = values[per_difat]
        fat_sectors = fat_sectors[:max(num_fat, 0) or len(fat_sectors)]
        fat = bytearray()
        for s in fat_sectors:
            fat += self._sector(s)
        self.fat = struct.unpack("<%dI" % (len(fat) // 4), bytes(fat))
        self.entries = self._read_directory(first_dir)
        root = self.entries[0]
        if root["type"] != 5:
            raise VbaError("the compound file has no root entry")
        self.mini_stream = self._read_chain(root["start"], self.fat, self.sector_size, root["size"])
        minifat = self._read_chain(first_minifat, self.fat, self.sector_size, None) if num_minifat else b""
        self.minifat = struct.unpack("<%dI" % (len(minifat) // 4), minifat)

    def _sector(self, index):
        start = (index + 1) * self.sector_size
        block = self.data[start:start + self.sector_size]
        if len(block) < self.sector_size:
            block = block + b"\x00" * (self.sector_size - len(block))
        return block

    def _read_chain(self, start, table, unit, size, source=None):
        out = bytearray()
        sector = start
        seen = set()
        while sector not in (ENDOFCHAIN, FREESECT):
            if sector in seen or sector >= len(table):
                raise VbaError("broken sector chain")
            seen.add(sector)
            if source is None:
                out += self._sector(sector)
            else:
                out += source[sector * unit:(sector + 1) * unit]
            if size is not None and len(out) >= size:
                break
            sector = table[sector]
        if size is not None:
            if len(out) < size:
                raise VbaError("stream is shorter than its directory size")
            return bytes(out[:size])
        return bytes(out)

    def _read_directory(self, first_dir):
        raw = self._read_chain(first_dir, self.fat, self.sector_size, None)
        entries = []
        for offset in range(0, len(raw) - 127, 128):
            name_len = struct.unpack_from("<H", raw, offset + 64)[0]
            name = raw[offset:offset + max(0, min(name_len, 64) - 2)].decode("utf-16-le", "replace")
            kind = raw[offset + 66]
            if not isinstance(kind, int):
                kind = ord(kind)
            left, right, child = struct.unpack_from("<III", raw, offset + 68)
            start, size = struct.unpack_from("<IQ", raw, offset + 116)
            if self.sector_size == 512:
                size &= 0xFFFFFFFF
            entries.append({"name": name, "type": kind, "left": left, "right": right,
                            "child": child, "start": start, "size": size})
        if not entries:
            raise VbaError("empty directory")
        return entries

    def children(self, index):
        """Return {upper-case name: entry index} for the children of one storage."""
        out = {}
        stack = [self.entries[index]["child"]]
        seen = set()
        while stack:
            i = stack.pop()
            if i == NOSTREAM or i >= len(self.entries) or i in seen:
                continue
            seen.add(i)
            entry = self.entries[i]
            out[entry["name"].upper()] = i
            stack.append(entry["left"])
            stack.append(entry["right"])
        return out

    def read_stream(self, index):
        entry = self.entries[index]
        if entry["type"] != 2:
            raise VbaError("%s is not a stream" % entry["name"])
        if entry["size"] > MAX_PROJECT_BYTES:
            raise VbaError("stream %s is too large" % entry["name"])
        if entry["size"] < self.mini_cutoff:
            return self._read_chain(entry["start"], self.minifat, self.mini_size, entry["size"],
                                    source=self.mini_stream)
        return self._read_chain(entry["start"], self.fat, self.sector_size, entry["size"])

    def find_vba_storages(self):
        """Yield (parent storage index, VBA storage index) for each VBA storage with a dir stream."""
        stack = [0]
        seen = set()
        while stack:
            index = stack.pop()
            if index in seen:
                continue
            seen.add(index)
            kids = self.children(index)
            vba = kids.get("VBA")
            if vba is not None and self.entries[vba]["type"] == 1 and "DIR" in self.children(vba):
                yield index, vba
            for i in kids.values():
                if self.entries[i]["type"] in (1, 5):
                    stack.append(i)


# --------------------------------------------------------------------------
# MS-OVBA compression
# --------------------------------------------------------------------------


def decompress(data):
    """Decompress one [MS-OVBA] 2.4.1 compressed container."""
    data = bytearray(data)
    if not data or data[0] != 1:
        raise VbaError("compressed container has a bad signature")
    out = bytearray()
    pos = 1
    while pos < len(data):
        if pos + 2 > len(data):
            raise VbaError("truncated chunk header")
        header = data[pos] | (data[pos + 1] << 8)
        chunk_end = min(pos + (header & 0x0FFF) + 3, len(data))
        if (header >> 12) & 0x07 != 3:
            raise VbaError("chunk header has a bad signature")
        pos += 2
        if not header & 0x8000:
            out += data[pos:pos + 4096]
            pos += 4096
            continue
        chunk_start = len(out)
        while pos < chunk_end:
            flags = data[pos]
            pos += 1
            for bit in range(8):
                if pos >= chunk_end:
                    break
                if not (flags >> bit) & 1:
                    out.append(data[pos])
                    pos += 1
                    continue
                if pos + 2 > chunk_end:
                    raise VbaError("truncated copy token")
                token = data[pos] | (data[pos + 1] << 8)
                pos += 2
                done = len(out) - chunk_start
                bit_count = max((done - 1).bit_length(), 4)
                length = (token & (0xFFFF >> bit_count)) + 3
                offset = (token >> (16 - bit_count)) + 1
                if offset > done:
                    raise VbaError("copy token points before the chunk")
                source = len(out) - offset
                for i in range(length):
                    out.append(out[source + i])
        pos = chunk_end
    return bytes(out)


# --------------------------------------------------------------------------
# VBA project ([MS-OVBA] dir stream, PROJECT stream, module streams)
# --------------------------------------------------------------------------


def codec_for(codepage):
    for name in ("cp%d" % codepage, "utf-8" if codepage == 65001 else None):
        if not name:
            continue
        try:
            "".encode(name)
            return name
        except LookupError:
            pass
    return "cp1252"


def parse_dir(data):
    """Return (codepage, project name bytes, modules) from a decompressed dir stream."""
    pos = 0
    codepage = 1252
    project = b""
    modules = []
    current = None
    while pos + 6 <= len(data):
        rid, size = struct.unpack_from("<HI", data, pos)
        pos += 6
        if rid == 0x0009:  # PROJECTVERSION: its size field is a reserved 4; the record body is 6 bytes
            size = 6
        body = data[pos:pos + size]
        pos += size
        if rid == 0x0010:
            break
        if rid == 0x0003 and len(body) >= 2:
            codepage = struct.unpack_from("<H", body)[0]
        elif rid == 0x0004:
            project = body
        elif rid == 0x0019:
            current = {"name_bytes": body, "name": None, "stream_bytes": None, "stream": None,
                       "offset": 0, "dir_type": None}
            modules.append(current)
        elif current is not None:
            if rid == 0x0047:
                current["name"] = body.decode("utf-16-le", "replace")
            elif rid == 0x001A:
                current["stream_bytes"] = body
            elif rid == 0x0032:
                current["stream"] = body.decode("utf-16-le", "replace")
            elif rid == 0x0031 and len(body) >= 4:
                current["offset"] = struct.unpack_from("<I", body)[0]
            elif rid == 0x0021:
                current["dir_type"] = "module"
            elif rid == 0x0022:
                current["dir_type"] = "class"
            elif rid == 0x002B:
                current = None
    return codepage, project, modules


def parse_project_stream(text):
    """Map module name to kind from the PROJECT stream (Module=, Class=, Document=, BaseClass=)."""
    kinds = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip().lower()
        name = value.split("/")[0].strip()
        if key == "module":
            kinds[name] = "module"
        elif key == "class":
            kinds[name] = "class"
        elif key == "document":
            kinds[name] = "document"
        elif key == "baseclass":
            kinds[name] = "form"
    return kinds


ATTRIBUTE_LINE = re.compile(r"^Attribute\s+[A-Za-z_]", re.IGNORECASE)
EXTENSIONS = {"module": ".bas", "class": ".cls", "document": ".cls", "form": ".frm"}


def split_lines(text):
    lines = re.split(r"\r\n|\r|\n", text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def code_lines(source_lines):
    """Lines as the VBA editor numbers them: hidden Attribute lines removed."""
    return [line for line in source_lines if not ATTRIBUTE_LINE.match(line)]


def read_project_bytes(path):
    size = os.path.getsize(path)
    if size > MAX_FILE_BYTES:
        raise VbaError("the file is larger than %d MB" % (MAX_FILE_BYTES // (1024 * 1024)))
    with open(path, "rb") as handle:
        head = handle.read(8)
    if head[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(path) as archive:
            names = [i for i in archive.infolist() if i.filename.lower().endswith("vbaproject.bin")]
            if not names:
                raise VbaError("the workbook has no VBA project (no macros)")
            info = sorted(names, key=lambda i: (i.filename.lower() != "xl/vbaproject.bin", i.filename))[0]
            if info.file_size > MAX_PROJECT_BYTES:
                raise VbaError("the VBA project is too large")
            return archive.read(info)
    if head == CFB_SIGNATURE:
        with open(path, "rb") as handle:
            return handle.read()
    raise VbaError("not an Excel macro workbook (unknown file format)")


def load_project(path):
    """Return a dict with codepage, project name and the modules (source and code lines)."""
    cfb = CompoundFile(read_project_bytes(path))
    storages = list(cfb.find_vba_storages())
    if not storages:
        raise VbaError("the file has no VBA project (no macros)")
    parent, vba = storages[0]
    vba_kids = cfb.children(vba)
    codepage, project_bytes, raw_modules = parse_dir(decompress(cfb.read_stream(vba_kids["DIR"])))
    codec = codec_for(codepage)
    kinds = {}
    project_stream = cfb.children(parent).get("PROJECT")
    if project_stream is not None:
        kinds = parse_project_stream(cfb.read_stream(project_stream).decode(codec, "replace"))
    modules = []
    for raw in raw_modules:
        name = raw["name"] or raw["name_bytes"].decode(codec, "replace")
        stream = raw["stream"] or (raw["stream_bytes"] or raw["name_bytes"]).decode(codec, "replace")
        index = vba_kids.get(stream.upper())
        if index is None:
            raise VbaError("module stream %s is missing" % stream)
        data = cfb.read_stream(index)
        if raw["offset"] > len(data):
            raise VbaError("module %s has a bad source offset" % name)
        source = decompress(data[raw["offset"]:]).decode(codec, "replace")
        lines = split_lines(source)
        kind = kinds.get(name) or raw["dir_type"] or "module"
        modules.append({"name": name, "kind": kind, "extension": EXTENSIONS.get(kind, ".bas"),
                        "source": lines, "code": code_lines(lines)})
    return {"path": os.path.abspath(path), "codepage": codepage, "codec": codec,
            "project": project_bytes.decode(codec, "replace"), "modules": modules}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_lines(lines):
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# find
# --------------------------------------------------------------------------


def default_roots():
    home = os.path.expanduser("~")
    return [os.path.join(home, "Downloads"), os.path.join(home, "Desktop")]


def find_workbooks(roots, name_filter="", depth=3, seconds=20.0, clock=time.time):
    """Search each root to a fixed depth. Never follows links or junctions."""
    deadline = clock() + seconds
    needle = name_filter.lower()
    found = []
    complete = True
    for root in roots:
        stack = [(root, 0)]
        while stack:
            if clock() > deadline:
                complete = False
                stack = []
                break
            folder, level = stack.pop()
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if level + 1 < depth:
                            stack.append((entry.path, level + 1))
                        continue
                    lower = entry.name.lower()
                    if lower.startswith("~$") or not lower.endswith(MACRO_EXTENSIONS):
                        continue
                    if needle and needle not in lower:
                        continue
                    info = entry.stat(follow_symlinks=False)
                    found.append({"path": entry.path, "size": info.st_size,
                                  "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(info.st_mtime)),
                                  "_mtime": info.st_mtime})
                except OSError:
                    continue
    found.sort(key=lambda row: -row["_mtime"])
    for row in found:
        row.pop("_mtime")
    return {"roots": roots, "depth": depth, "complete": complete, "files": found}


# --------------------------------------------------------------------------
# scan (heuristic)
# --------------------------------------------------------------------------

IDENT = r"[A-Za-z][A-Za-z0-9_]*[%&!#@$]?"
PROC_START = re.compile(
    r"^(?:(?:Public|Private|Friend|Static)\s+)*(?:Sub|Function|Property\s+(?:Get|Let|Set))\s+(%s)\s*(?:\((.*)\))?"
    % IDENT, re.IGNORECASE)
PROC_END = re.compile(r"^End\s+(?:Sub|Function|Property)\b", re.IGNORECASE)
DECLARE = re.compile(r"^(?:(?:Public|Private)\s+)?Declare\s+(?:PtrSafe\s+)?(?:Sub|Function)\s+(%s)" % IDENT,
                     re.IGNORECASE)
DIM = re.compile(r"^(?:(Public|Private|Global|Dim|Static|ReDim(?:\s+Preserve)?)\s+(?:(?:Const|WithEvents|Shared)\s+)?|Const\s+)(.*)$",
                 re.IGNORECASE)
TYPE_START = re.compile(r"^(?:(?:Public|Private)\s+)?(Type|Enum)\s+(%s)" % IDENT, re.IGNORECASE)
TYPE_END = re.compile(r"^End\s+(?:Type|Enum)\b", re.IGNORECASE)
EVENT = re.compile(r"^(?:Public\s+)?Event\s+(%s)" % IDENT, re.IGNORECASE)
ASSIGN = re.compile(r"^(?:(?:Let|Set|LSet|RSet)\s+)?(%s)\s*(?:\([^=]*\))?\s*=(?!=)" % IDENT, re.IGNORECASE)
FOR_EACH = re.compile(r"^For\s+Each\s+(%s)\s+In\b" % IDENT, re.IGNORECASE)
FOR_TO = re.compile(r"^For\s+(%s)\s*=" % IDENT, re.IGNORECASE)
SINGLE_IF = re.compile(r"^(?:If|ElseIf)\b.*?\bThen\b\s*(.+)$", re.IGNORECASE)
OPTION_EXPLICIT = re.compile(r"^Option\s+Explicit\b", re.IGNORECASE)

KEYWORDS = set("""
call case const debug declare dim do else elseif end enum erase error event exit for function get global
gosub goto if implements let lset loop next on open option private property public put raise
randomize redim rem resume return rset select set static stop sub type wend while with write
""".split())
# Excel and VBA global names that code often assigns to without a declaration.
GLOBAL_NAMES = set("""
me mid midb date time err application activecell activesheet activeworkbook activewindow selection
range cells rows columns sheets worksheets workbooks charts names thisworkbook calculation
""".split())


def bare(name):
    return name.rstrip("%&!#@$").lower()


def strip_strings_and_comment(line):
    """Replace string contents with empty quotes and cut a trailing comment."""
    out = []
    in_string = False
    for char in line:
        if char == '"':
            in_string = not in_string
            out.append(char)
        elif in_string:
            continue
        elif char == "'":
            break
        else:
            out.append(char)
    text = "".join(out).rstrip()
    if re.match(r"^\s*Rem(\s|$)", text, re.IGNORECASE):
        return ""
    return text


def logical_statements(lines):
    """Yield (first line number, statement) after line joins and ':' splits."""
    pending = ""
    start = None
    for number, line in enumerate(lines, 1):
        text = strip_strings_and_comment(line)
        if start is None:
            start = number
        if text.endswith(" _") or text == "_":
            pending += text[:-1] + " "
            continue
        whole = (pending + text).strip()
        pending = ""
        first = start
        start = None
        for part in re.split(r":(?!=)", whole):
            part = part.strip()
            if part:
                yield first, part


def split_top_level(text):
    parts = []
    depth = 0
    current = []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def declared_names(declaration):
    names = []
    for part in split_top_level(declaration):
        part = re.sub(r"^\s*(?:Optional|ByVal|ByRef|ParamArray|WithEvents)\s+", "", part, flags=re.IGNORECASE)
        part = re.sub(r"^\s*(?:ByVal|ByRef)\s+", "", part, flags=re.IGNORECASE)
        match = re.match(r"\s*(%s)" % IDENT, part)
        if match:
            names.append(bare(match.group(1)))
    return names


def _module_outline(module):
    """Split one module into module-level names and procedures."""
    module_names = set()
    public_names = set()
    procedures = []
    current = None
    in_type = None
    explicit = False
    for number, statement in logical_statements(module["code"]):
        if current is None and OPTION_EXPLICIT.match(statement):
            explicit = True
        if in_type is not None:
            if TYPE_END.match(statement):
                in_type = None
            elif in_type == "enum":
                match = re.match(r"(%s)" % IDENT, statement)
                if match:
                    public_names.add(bare(match.group(1)))
            continue
        type_match = TYPE_START.match(statement)
        if type_match and current is None:
            in_type = type_match.group(1).lower()
            public_names.add(bare(type_match.group(2)))
            continue
        proc = PROC_START.match(statement)
        if proc and current is None:
            current = {"name": proc.group(1), "start": number, "declared": set(),
                       "statements": []}
            public_names.add(bare(current["name"]))
            if proc.group(2):
                current["declared"].update(declared_names(proc.group(2)))
            procedures.append(current)
            continue
        if PROC_END.match(statement):
            current = None
            continue
        if current is None:
            declare = DECLARE.match(statement) or EVENT.match(statement)
            if declare:
                public_names.add(bare(declare.group(1)))
                continue
            dim = DIM.match(statement)
            if dim:
                scope = (dim.group(1) or "").lower()
                target = public_names if scope in ("public", "global") else module_names
                target.update(declared_names(dim.group(2)))
            continue
        current["statements"].append((number, statement))
        dim = DIM.match(statement)
        if dim:
            current["declared"].update(declared_names(dim.group(2)))
    return {"explicit": explicit, "module_names": module_names, "public_names": public_names,
            "procedures": procedures}


def _targets(statement):
    """Return the variable names that a statement assigns to."""
    match = SINGLE_IF.match(statement)
    if match:
        names = []
        for part in re.split(r"\bElse\b", match.group(1), flags=re.IGNORECASE):
            names.extend(_targets(part.strip()))
        return names
    for pattern in (FOR_EACH, FOR_TO):
        match = pattern.match(statement)
        if match:
            return [match.group(1)]
    match = ASSIGN.match(statement)
    if match and match.group(1).lower() not in KEYWORDS:
        return [match.group(1)]
    return []


def scan_project(project):
    outlines = [(module, _module_outline(module)) for module in project["modules"]]
    project_names = set(GLOBAL_NAMES)
    for module, outline in outlines:
        project_names.add(bare(module["name"]))
        project_names.update(outline["public_names"])
    findings = []
    no_explicit = []
    for module, outline in outlines:
        if not outline["explicit"]:
            no_explicit.append(module["name"])
        known_module = project_names | outline["module_names"]
        for proc in outline["procedures"]:
            known = known_module | proc["declared"]
            reported = set()
            for number, statement in proc["statements"]:
                for name in _targets(statement):
                    key = bare(name)
                    if key in known or key in KEYWORDS or key in reported:
                        continue
                    reported.add(key)
                    findings.append({"module": module["name"], "procedure": proc["name"], "line": number,
                                     "name": name, "option_explicit": outline["explicit"],
                                     "statement": statement[:120]})
    return {"modules": len(project["modules"]), "modules_without_option_explicit": no_explicit,
            "undeclared": findings,
            "note": "Heuristic. It checks assignment targets and loop variables only. "
                    "Confirm each finding with Debug > Compile VBAProject in Excel."}


# --------------------------------------------------------------------------
# plan and verify
# --------------------------------------------------------------------------

ACTIONS = ("insert_before", "insert_after", "replace", "delete")


def _module_by_name(project, name):
    for module in project["modules"]:
        if module["name"].lower() == str(name).lower():
            return module
    raise VbaError("module %r is not in the workbook" % name)


def _check_new_lines(lines, codec):
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        raise VbaError("'lines' must be a list of strings")
    for line in lines:
        if "\r" in line or "\n" in line:
            raise VbaError("one entry in 'lines' contains a line break; give one entry per line")
        if len(line) > MAX_LINE_CHARS:
            raise VbaError("a new line is longer than %d characters" % MAX_LINE_CHARS)
        if ATTRIBUTE_LINE.match(line):
            raise VbaError("a new line starts with 'Attribute'; the VBA editor hides such lines")
        try:
            line.encode(codec)
        except UnicodeEncodeError:
            raise VbaError("a new line has characters that code page %s cannot store" % codec)


def build_plan(project, source_sha256, edits):
    """Resolve edits against the code lines and return the plan dict."""
    if not isinstance(edits, list) or not edits:
        raise VbaError("the edits file needs a non-empty 'edits' list")
    steps = []
    anchors = set()
    for number, edit in enumerate(edits, 1):
        if not isinstance(edit, dict):
            raise VbaError("edit %d is not an object" % number)
        action = edit.get("action")
        if action not in ACTIONS:
            raise VbaError("edit %d: action must be one of %s" % (number, ", ".join(ACTIONS)))
        module = _module_by_name(project, edit.get("module"))
        match = edit.get("match")
        if not isinstance(match, str) or not match.strip():
            raise VbaError("edit %d: 'match' must be the exact text of one existing line" % number)
        hits = [i + 1 for i, line in enumerate(module["code"]) if line.rstrip() == match.rstrip()]
        wanted = edit.get("line")
        if wanted is not None:
            if wanted not in hits:
                raise VbaError("edit %d: line %s does not hold the 'match' text (it is on lines %s)"
                               % (number, wanted, hits or "none"))
            line = wanted
        elif len(hits) == 1:
            line = hits[0]
        elif not hits:
            raise VbaError("edit %d: no line of %s has the 'match' text" % (number, module["name"]))
        else:
            raise VbaError("edit %d: the 'match' text is on %s lines %s; add 'line' to choose one"
                           % (number, len(hits), hits))
        new_lines = edit.get("lines", [])
        if action == "delete":
            new_lines = []
        else:
            _check_new_lines(new_lines, project["codec"])
            if action != "replace" and not new_lines:
                raise VbaError("edit %d: %s needs at least one entry in 'lines'" % (number, action))
        key = (module["name"], line)
        if key in anchors:
            raise VbaError("edit %d: two edits use line %d of %s; combine them" % (number, line, module["name"]))
        anchors.add(key)
        steps.append({"module": module["name"], "action": action, "line": line,
                      "anchor_text": module["code"][line - 1], "insert": list(new_lines)})
    order = {m["name"]: i for i, m in enumerate(project["modules"])}
    steps.sort(key=lambda s: (order[s["module"]], -s["line"]))
    expected = {}
    modules = {}
    for step in steps:
        module = _module_by_name(project, step["module"])
        modules[module["name"]] = {"code_lines": len(module["code"]), "code_sha256": sha256_lines(module["code"])}
        lines = expected.setdefault(module["name"], list(module["code"]))
        expected[module["name"]] = apply_step(lines, step)
    return {"format": PLAN_FORMAT, "source": project["path"], "source_sha256": source_sha256,
            "codepage": project["codepage"], "modules": modules, "steps": steps, "expected_code": expected}


def apply_step(lines, step):
    """Apply one step to a list of code lines, as vba_apply.ps1 does in the VBA editor."""
    lines = list(lines)
    index = step["line"] - 1
    if step["action"] == "insert_before":
        lines[index:index] = step["insert"]
    elif step["action"] == "insert_after":
        lines[index + 1:index + 1] = step["insert"]
    elif step["action"] == "replace":
        lines[index:index + 1] = step["insert"]
    else:
        del lines[index]
    return lines


def plan_diff(project, plan):
    out = []
    for name, new in plan["expected_code"].items():
        old = _module_by_name(project, name)["code"]
        out.extend(difflib.unified_diff(old, new, "%s (before)" % name, "%s (after)" % name, lineterm=""))
    return "\n".join(out)


def loose(line):
    """Compare text the way the VBA editor may rewrite it: case and spaces can change."""
    return re.sub(r"\s+", "", line).casefold()


def verify_copy(plan, copy_project):
    results = []
    ok = True
    for name, expected in plan["expected_code"].items():
        try:
            actual = _module_by_name(copy_project, name)["code"]
        except VbaError:
            results.append({"module": name, "status": "missing"})
            ok = False
            continue
        exact = [l.rstrip() for l in actual] == [l.rstrip() for l in expected]
        same = exact or [loose(l) for l in actual] == [loose(l) for l in expected]
        row = {"module": name, "status": "match" if same else "different", "exact": exact}
        if not same:
            ok = False
            row["diff"] = list(difflib.unified_diff(expected, actual, "planned", "saved", lineterm=""))[:60]
        results.append(row)
    return ok, results


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------


def _print_json(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def cmd_find(args):
    roots = args.root or default_roots()
    _print_json(find_workbooks(roots, args.name or "", args.depth, args.seconds))
    return 0


def cmd_dump(args):
    project = load_project(args.file)
    summary = [{"name": m["name"], "kind": m["kind"], "code_lines": len(m["code"])} for m in project["modules"]]
    if args.out:
        if os.path.exists(args.out) and os.listdir(args.out):
            raise VbaError("the output folder is not empty; give a new folder")
        if not os.path.isdir(args.out):
            os.makedirs(args.out)
        for module in project["modules"]:
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", module["name"]) + module["extension"]
            with open(os.path.join(args.out, safe), "w", encoding="utf-8", newline="\r\n") as handle:
                handle.write("\n".join(module["source"]) + "\n")
        _print_json({"file": project["path"], "out": os.path.abspath(args.out), "modules": summary})
        return 0
    if args.json:
        _print_json({"file": project["path"], "codepage": project["codepage"], "project": project["project"],
                     "modules": [dict(s, code=m["code"]) for s, m in zip(summary, project["modules"])]})
        return 0
    for module in project["modules"]:
        print("' ===== %s (%s, %d lines) =====" % (module["name"], module["kind"], len(module["code"])))
        for number, line in enumerate(module["code"], 1):
            print("%5d  %s" % (number, line) if args.numbers else line)
        print("")
    return 0


def cmd_scan(args):
    _print_json(scan_project(load_project(args.file)))
    return 0


def _read_json(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def cmd_plan(args):
    if os.path.exists(args.out):
        raise VbaError("the plan file already exists; give a new name")
    project = load_project(args.file)
    edits = _read_json(args.edits)
    plan = build_plan(project, sha256_file(args.file), edits.get("edits") if isinstance(edits, dict) else edits)
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(plan, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(plan_diff(project, plan))
    print("")
    print("Plan written: %s (%d steps). Nothing in the workbook changed." % (os.path.abspath(args.out), len(plan["steps"])))
    return 0


def cmd_verify(args):
    plan = _read_json(args.plan)
    if plan.get("format") != PLAN_FORMAT:
        raise VbaError("not an am-excel-vba plan file")
    if os.path.normcase(os.path.abspath(args.file)) == os.path.normcase(plan["source"]):
        raise VbaError("give the edited copy, not the source workbook")
    ok, results = verify_copy(plan, load_project(args.file))
    source_unchanged = os.path.exists(plan["source"]) and sha256_file(plan["source"]) == plan["source_sha256"]
    _print_json({"copy": os.path.abspath(args.file), "all_match": ok, "source_unchanged": source_unchanged,
                 "modules": results})
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("find", help="list macro workbooks in shallow folders")
    p.add_argument("--root", action="append", help="folder to search (repeat); default Downloads and Desktop")
    p.add_argument("--name", help="part of the file name")
    p.add_argument("--depth", type=int, default=3)
    p.add_argument("--seconds", type=float, default=20.0)
    p.set_defaults(func=cmd_find)
    p = sub.add_parser("dump", help="print every VBA module")
    p.add_argument("file")
    p.add_argument("--out", help="new folder: write one file per module")
    p.add_argument("--json", action="store_true")
    p.add_argument("--numbers", action="store_true", help="show line numbers as the VBA editor counts them")
    p.set_defaults(func=cmd_dump)
    p = sub.add_parser("scan", help="heuristic check for undeclared variables")
    p.add_argument("file")
    p.set_defaults(func=cmd_scan)
    p = sub.add_parser("plan", help="preview edits and write a plan file")
    p.add_argument("file")
    p.add_argument("--edits", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser("verify", help="compare an edited copy with the plan")
    p.add_argument("plan")
    p.add_argument("--file", required=True, help="the edited copy")
    p.set_defaults(func=cmd_verify)
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except (VbaError, zipfile.BadZipFile, OSError, ValueError, KeyError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
