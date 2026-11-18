# -*- coding: utf-8 -*-
"""Tests for scripts/lib/family_index.py and scripts/family_library.py (issue #153).

Each test builds a small synthetic library in a temporary folder.
All names are invented.
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import cfb_writer as cw  # noqa: E402
import family_index as fi  # noqa: E402
import family_library  # noqa: E402
import rfa_metadata as rm  # noqa: E402

DOOR = [("900 x 2100mm", [("Width", "900", "Length", "mm"), ("Height", "2100", "Length", "mm")]),
        ("1000 x 2100mm", [("Width", "1000", "Length", "mm"), ("Height", "2100", "Length", "mm")])]
DESK = [("1600 x 800", [("Width", "1600", "Length", "mm"), ("Finish", "Oak", "Text", None)])]


def make_library(root):
    def put(relative, data):
        path = os.path.join(str(root), *relative.split("/"))
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        with io.open(path, "wb") as f:
            f.write(data)
    put("Doors/Single Door.rfa", cw.family_file("Doors", DOOR))
    put("Doors/Single Door.txt", u",Width##LENGTH##MILLIMETERS\r\n800 x 2100mm,800\r\n".encode("utf-8"))
    put("Doors/Archive/Single Door.rfa", cw.family_file("Doors", DOOR[:1], version="2024"))
    put("Furniture/Desk.rfa", cw.family_file("Furniture", DESK))
    put("Furniture/Desk.0001.rfa", cw.family_file("Furniture", DESK))
    put("Furniture/Broken.rfa", b"not a family" * 50)
    put("Furniture/readme.txt", b"notes")
    return str(root)


def test_index_counts_duplicates_backups_and_catalogs(tmp_path):
    root = make_library(tmp_path / "lib")
    index = fi.build_index(root, thumbnails_dir=str(tmp_path / "thumbs"))
    rows = dict((r["relative"], r) for r in index["families"])
    assert sorted(rows) == ["Doors/Archive/Single Door.rfa", "Doors/Single Door.rfa",
                            "Furniture/Broken.rfa", "Furniture/Desk.0001.rfa", "Furniture/Desk.rfa"]
    assert index["complete"] is True
    assert rows["Doors/Single Door.rfa"]["duplicate_name"] is True
    assert rows["Furniture/Desk.0001.rfa"]["backup"] is True
    assert rows["Furniture/Broken.rfa"]["status"] == "unreadable"
    door = rows["Doors/Single Door.rfa"]
    assert [(t["name"], t["origin"]) for t in door["types"]] == [
        ("900 x 2100mm", "embedded"), ("1000 x 2100mm", "embedded"), ("800 x 2100mm", "catalog")]
    assert door["catalog"]["type_count"] == 1
    assert door["thumbnail"] and os.path.isfile(os.path.join(str(tmp_path / "thumbs"), door["thumbnail"]))
    assert rows["Doors/Archive/Single Door.rfa"]["revit_version"] == "2024"
    assert index["counts"]["by_status"] == {"ok": 4, "unreadable": 1}


def test_search_by_text_category_type_and_parameter(tmp_path):
    index = fi.build_index(make_library(tmp_path / "lib"))
    found = fi.search(index, text="single archive")
    assert [(r["relative"], r["type"]) for r in found["rows"]] == [
        ("Doors/Archive/Single Door.rfa", "900 x 2100mm")]
    found = fi.search(index, category="door", type_name="1000")
    assert [r["type"] for r in found["rows"]] == ["1000 x 2100mm"]
    found = fi.search(index, parameter=fi.parse_parameter_filter("width=900.0"))
    assert [(r["relative"], r["type"]) for r in found["rows"]] == [
        ("Doors/Archive/Single Door.rfa", "900 x 2100mm"), ("Doors/Single Door.rfa", "900 x 2100mm")]
    assert found["rows"][0]["parameter"]["units"] == "mm"
    found = fi.search(index, parameter=fi.parse_parameter_filter("Finish=oak"))
    assert [r["family"] for r in found["rows"]] == ["Desk"]
    catalog = fi.search(index, parameter=fi.parse_parameter_filter("Width=800"))
    assert [(r["type"], r["type_origin"]) for r in catalog["rows"]] == [("800 x 2100mm", "catalog")]
    assert fi.search(index, parameter=fi.parse_parameter_filter("Height"))["total"] == 3


def test_backups_and_unreadable_are_hidden_by_default(tmp_path):
    index = fi.build_index(make_library(tmp_path / "lib"))
    assert [r["relative"] for r in fi.search(index, text="desk")["rows"]] == ["Furniture/Desk.rfa"]
    shown = fi.search(index, text="desk", include_backups=True)["rows"]
    assert [r["relative"] for r in shown] == ["Furniture/Desk.0001.rfa", "Furniture/Desk.rfa"]
    broken = fi.search(index, text="broken", include_unreadable=True)["rows"]
    assert broken[0]["type"] is None and broken[0]["status"] == "unreadable"


def test_limit_and_truncation(tmp_path):
    index = fi.build_index(make_library(tmp_path / "lib"))
    result = fi.search(index, limit=2)
    assert len(result["rows"]) == 2 and result["truncated"] is True and result["total"] == 5


def test_value_matching_rules():
    assert fi.value_matches("2100", "2100.0")
    assert fi.value_matches("36\"", "36")
    assert fi.value_matches("900 mm", "900")
    assert not fi.value_matches("900", "9000")
    assert fi.value_matches("Oak", "OAK")
    assert not fi.value_matches("1/2\"", "0.5")  # fractions compare as text only


def test_mark_in_model_with_escaped_names(tmp_path):
    index = fi.build_index(make_library(tmp_path / "lib"))
    rows = fi.search(index, text="single")["rows"]
    loaded = {"result": {"escaped": True, "truncated": False, "families": [
        {"name": "single door", "category": "Doors", "types": ["900 x 2100mm"]},
        {"name": "Caf\\u00e9 Table", "category": "Furniture", "types": []}]}}
    marked = fi.mark_in_model(rows, loaded)["rows"]
    state = [(r["relative"], r["type"], r["family_in_model"], r["type_in_model"]) for r in marked]
    assert ("Doors/Single Door.rfa", "900 x 2100mm", True, True) in state
    assert ("Doors/Single Door.rfa", "1000 x 2100mm", True, False) in state
    assert fi.unescape("Caf\\u00e9 \\\\ A") == u"Caf\u00e9 \\ A"


def test_refresh_reuses_unchanged_rows_and_rereads_changed(tmp_path):
    root = make_library(tmp_path / "lib")
    first = fi.build_index(root)
    second = fi.build_index(root, previous=first)
    assert second["counts"]["reused"] == 5
    desk = os.path.join(root, "Furniture", "Desk.rfa")
    with io.open(desk, "wb") as f:
        f.write(cw.family_file("Furniture", DESK + [("2000 x 900", [])]))
    os.utime(desk, (1000000000, 1000000000))
    third = fi.build_index(root, previous=second)
    assert third["counts"]["reused"] == 4
    row = [r for r in third["families"] if r["relative"] == "Furniture/Desk.rfa"][0]
    assert [t["name"] for t in row["types"]] == ["1600 x 800", "2000 x 900"]


def test_cloud_only_files_are_skipped_without_reading(tmp_path, monkeypatch):
    root = make_library(tmp_path / "lib")
    opened = []
    real_read = rm.read_family_file

    def spy(path, want_thumbnail=False):
        opened.append(os.path.basename(path))
        return real_read(path, want_thumbnail)

    def attributes(info):
        return fi.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS if info.st_size == os.path.getsize(
            os.path.join(root, "Furniture", "Broken.rfa")) else 0

    monkeypatch.setattr(rm, "read_family_file", spy)
    monkeypatch.setattr(fi, "_attributes", attributes)
    index = fi.build_index(root)
    assert "Broken.rfa" not in opened
    assert {"relative": "Furniture/Broken.rfa", "reason": "cloud_only"} in index["skipped"]
    assert index["complete"] is False


def test_entry_and_depth_limits_make_the_index_partial(tmp_path):
    root = make_library(tmp_path / "lib")
    small = fi.build_index(root, max_entries=3)
    assert "entries" in small["limits_hit"] and small["complete"] is False
    shallow = fi.build_index(root, max_depth=1)
    assert "depth" in shallow["limits_hit"]
    assert {"relative": "Doors/Archive", "reason": "too_deep"} in shallow["skipped"]


def test_links_are_not_followed(tmp_path):
    root = make_library(tmp_path / "lib")
    try:
        os.symlink(os.path.join(root, "Doors"), os.path.join(root, "Linked"), target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        return  # symlinks need extra rights on some Windows machines
    index = fi.build_index(root)
    assert {"relative": "Linked", "reason": "link_not_followed"} in index["skipped"]
    assert not any(r["relative"].startswith("Linked/") for r in index["families"])


def test_cli_index_search_and_exit_codes(tmp_path, capsys):
    root = make_library(tmp_path / "lib")
    out = str(tmp_path / "index.json")
    assert family_library.main(["index", root, "--out", out, "--thumbnails", str(tmp_path / "t")]) == 0
    assert "Indexed 5 families" in capsys.readouterr().out
    loaded = str(tmp_path / "loaded.json")
    with io.open(loaded, "w", encoding="utf-8") as f:
        f.write(json.dumps({"families": [{"name": "Desk", "category": "Furniture", "types": []}]}))
    results = str(tmp_path / "results.json")
    code = family_library.main(["search", out, "--text", "desk", "--in-model", loaded, "--out", results])
    text = capsys.readouterr().out
    assert code == 0 and "family loaded, type not" in text
    with io.open(results, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["rows"][0]["family_in_model"] is True
    assert saved["rows"][0]["thumbnail"].endswith(".png")
    assert family_library.main(["search", out, "--text", "nothing-like-this"]) == 1
    assert family_library.main(["search", results]) == 2
    assert family_library.main(["index", str(tmp_path / "missing"), "--out", out]) == 2


def test_index_file_replaced_in_one_step(tmp_path):
    index = fi.build_index(make_library(tmp_path / "lib"))
    path = str(tmp_path / "index.json")
    fi.write_index(index, path)
    fi.write_index(index, path)
    assert not os.path.exists(path + ".tmp")
    assert fi.load_index(path)["counts"]["families"] == 5
