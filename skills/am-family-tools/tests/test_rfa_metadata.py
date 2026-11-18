# -*- coding: utf-8 -*-
"""Tests for scripts/lib/rfa_metadata.py (offline .rfa metadata, issue #153).

All files are synthetic (tests/cfb_writer.py). No real family file is used.

Run:
    python -m pytest -q skills/am-family-tools/tests
"""
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

import cfb_writer as cw  # noqa: E402
import rfa_metadata as rm  # noqa: E402

DOOR_TYPES = [
    ("900 x 2100mm", [("Width", "900", "Length", "mm"), ("Height", "2100", "Length", "mm"),
                      ("Fire Rating", "60 min", "Text", None)]),
    ("1000 x 2100mm", [("Width", "1000", "Length", "mm"), ("Height", "2100", "Length", "mm")]),
]


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def test_reads_category_version_types_and_values_from_mini_stream(tmp_path):
    path = write(tmp_path, "Door.rfa", cw.family_file("Doors", DOOR_TYPES))
    meta = rm.read_family_file(path, want_thumbnail=True)
    assert meta["status"] == "ok", meta["reason"]
    assert meta["category"] == "Doors"
    assert meta["revit_version"] == "2026"
    assert [t["name"] for t in meta["types"]] == ["900 x 2100mm", "1000 x 2100mm"]
    first = meta["types"][0]["parameters"]
    assert first[0] == {"name": "Width", "value": "900", "kind": "Length", "units": "mm"}
    assert first[2]["value"] == "60 min" and first[2]["units"] is None
    assert meta["thumbnail"]["png"].startswith(b"\x89PNG")
    assert (meta["thumbnail"]["width"], meta["thumbnail"]["height"]) == (2, 2)


def test_reads_a_large_part_atom_from_normal_sectors(tmp_path):
    data = cw.family_file("Furniture", DOOR_TYPES, padding=9000)
    path = write(tmp_path, "Big.rfa", data)
    meta = rm.read_family_file(path)
    assert meta["status"] == "ok", meta["reason"]
    assert meta["category"] == "Furniture"
    assert len(meta["types"]) == 2
    assert meta["thumbnail"] is None  # not asked for


def test_omniclass_and_family_without_types():
    xml = cw.part_atom("Generic Models", [], omniclass="23.40.20.00")
    meta = rm.parse_part_atom(xml)
    assert meta["category"] == "Generic Models"
    assert meta["omniclass"] == "23.40.20.00"
    assert meta["types"] == []


def test_not_a_compound_file_is_reported_not_raised(tmp_path):
    path = write(tmp_path, "Fake.rfa", b"this is not a family file" * 40)
    meta = rm.read_family_file(path)
    assert meta["status"] == "unreadable"
    assert "OLE" in meta["reason"]


def test_missing_part_atom_is_no_metadata(tmp_path):
    path = write(tmp_path, "Old.rfa", cw.build([("Contents", b"abc" * 10)]))
    meta = rm.read_family_file(path)
    assert meta["status"] == "no_metadata"
    assert meta["types"] == []


def test_doctype_is_refused():
    xml = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><entry xmlns="http://www.w3.org/2005/Atom"/>'
    try:
        rm.parse_part_atom(xml)
    except rm.MetadataError as exc:
        assert "DOCTYPE" in str(exc)
    else:
        raise AssertionError("a DOCTYPE must be refused")


def test_bad_xml_and_wrong_root_are_refused():
    for xml in (b"<entry", b'<feed xmlns="http://www.w3.org/2005/Atom"/>'):
        try:
            rm.parse_part_atom(xml)
        except rm.MetadataError:
            pass
        else:
            raise AssertionError("bad PartAtom must be refused")


def test_fat_loop_is_detected(tmp_path):
    data = bytearray(cw.build([("PartAtom", cw.part_atom("Doors", DOOR_TYPES, ) + b" " * 6000)]))
    # The PartAtom stream starts at sector 0. Point sector 0 at itself.
    offset = cw.fat_offset(bytes(data), 0)
    struct.pack_into("<I", data, offset, 0)
    path = write(tmp_path, "Loop.rfa", bytes(data))
    meta = rm.read_family_file(path)
    assert meta["status"] == "unreadable"
    assert "loop" in meta["reason"]


def test_truncated_file_is_reported(tmp_path):
    data = cw.family_file("Doors", DOOR_TYPES, padding=9000)
    path = write(tmp_path, "Cut.rfa", data[:2048])
    meta = rm.read_family_file(path)
    assert meta["status"] == "unreadable"


def test_stream_limit_is_enforced():
    data = cw.build([("PartAtom", b"<x/>" * 2000)])
    container = rm.CompoundFile(io.BytesIO(data))
    entry = container.top_level()["PartAtom"]
    try:
        container.read_stream(entry, 100)
    except rm.MetadataError as exc:
        assert "limit" in str(exc)
    else:
        raise AssertionError("the stream limit must hold")


def test_thumbnail_with_bad_crc_is_ignored():
    image = bytearray(cw.png())
    image[40] ^= 0xFF  # inside the IDAT chunk
    assert rm.thumbnail_png(b"head" + bytes(image)) is None
    assert rm.thumbnail_png(b"no image here") is None
    assert rm.thumbnail_png(b"x" + cw.png(3, 1))["width"] == 3


def test_type_catalog_with_units_and_duplicates():
    text = (u",Width##LENGTH##MILLIMETERS,Height##LENGTH##MILLIMETERS,Finish##OTHER##\r\n"
            u"900 x 2100,900,2100,\"Oak, oiled\"\r\n"
            u"1000 x 2100,1000,2100,Paint\r\n"
            u"900 x 2100,900,2100,Paint\r\n")
    catalog = rm.parse_type_catalog(text.encode("utf-8"))
    assert [p["name"] for p in catalog["parameters"]] == ["Width", "Height", "Finish"]
    assert catalog["parameters"][0]["spec"] == "LENGTH"
    assert [t["name"] for t in catalog["types"]] == ["900 x 2100", "1000 x 2100"]
    assert catalog["types"][0]["parameters"][2]["value"] == "Oak, oiled"
    assert catalog["types"][0]["parameters"][0]["units"] == "MILLIMETERS"
    assert any("repeats" in issue for issue in catalog["issues"])


def test_type_catalog_utf16_and_bad_header():
    text = u",Width##LENGTH##INCHES\r\nCaf\u00e9 36in,36\r\n"
    catalog = rm.parse_type_catalog(b"\xff\xfe" + text.encode("utf-16-le"))
    assert catalog["types"][0]["name"] == u"Caf\u00e9 36in"
    bad = rm.parse_type_catalog(b"Width,Height\r\nA,1,2\r\n")
    assert bad["types"] == [] and bad["issues"]
    assert rm.parse_type_catalog(b"")["issues"] == ["The catalog is empty."]
