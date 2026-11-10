from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import ezdxf
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from cad_layout_preview import FRAME, propose


@pytest.fixture
def layout(tmp_path):
    dxf = tmp_path / "geometry.dxf"
    doc = ezdxf.new("R2000")
    doc.units = ezdxf.units.MM
    model = doc.modelspace()
    model.add_line((0, 0, 3000), (4000, 0, 3000), dxfattribs={"layer": "A-WALL"})
    model.add_line((4000, 200, 3000), (0, 200, 3000), dxfattribs={"layer": "A-WALL"})
    model.add_line((900, 100, 3000), (1800, 100, 3000), dxfattribs={"layer": "A-DOOR"})
    model.add_lwpolyline([(0, 500), (3500, 500), (3500, 3000), (0, 3000)], close=True,
                         dxfattribs={"layer": "A-ROOM", "elevation": 3000})
    doc.saveas(dxf)
    read = ezdxf.readfile(dxf)
    assert read.units == ezdxf.units.MM
    geometry = read.modelspace()
    polyline, = geometry.query("LWPOLYLINE")
    assert polyline.closed and not polyline.has_arc and not polyline.has_width
    snapshot = {
        "coordinate_frame": FRAME, "link_id": "fixture-link", "level_id": "level-2", "level_mm": 3000,
        "segments": [{"id": e.dxf.handle, "layer": e.dxf.layer,
                      "start": list(e.dxf.start), "end": list(e.dxf.end)} for e in geometry.query("LINE")],
        "room_loops": [{"id": polyline.dxf.handle, "layer": polyline.dxf.layer, "closed": polyline.closed,
                        "vertices": [list(vertex) for vertex in polyline.vertices_in_wcs()],
                        "interior_point": [500, 1000, 3000]}],
    }
    mapping = {
        "tolerance_mm": 2, "minimum_overlap_mm": 200, "door_setback_mm": 100,
        "walls": {"A-WALL": {"type_id": "wall-type-200", "width_mm": 200}},
        "doors": {"A-DOOR": {"type_id": "door-type-900", "width_mm": 900}},
        "room_layers": ["A-ROOM"],
    }
    return snapshot, mapping


def test_actual_dxf_geometry_through_cli(layout, tmp_path):
    snapshot, mapping = layout
    source, config = tmp_path / "snapshot.json", tmp_path / "mapping.json"
    for path, data in ((source, snapshot), (config, mapping)):
        path.write_text(json.dumps(data))
    result = subprocess.run([sys.executable, str(SCRIPTS / "cad_layout_preview.py"),
                             str(source), "--mapping", str(config)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    preview = json.loads(result.stdout)
    assert preview["kind"] == "cad-layout-proposal" and preview["model_write_approved"] is False
    assert preview["snapshot_sha256"] == sha256(source.read_bytes()).hexdigest()
    assert preview["mapping_sha256"] == sha256(config.read_bytes()).hexdigest()
    assert preview["level_mm"] == 3000 and preview["unresolved"] == []
    wall, = preview["walls"]
    assert wall["axis"] == [[0, 100], [4000, 100]]
    assert wall["source_ids"] == [line["id"] for line in snapshot["segments"][:2]]
    for line in snapshot["segments"][:2]:
        assert all(abs(point[1] - 100) == 100 for point in (line["start"], line["end"]))
        assert sorted(point[0] for point in (line["start"], line["end"])) == [0, 4000]
    assert wall["face_residual_mm"] == 0
    door, = preview["doors"]
    assert (door["host"], door["location"], door["span_mm"]) == (wall["id"], [1350, 100], [900, 1800])
    room, = preview["rooms"]
    assert room["boundary"] == [[0, 500], [3500, 500], [3500, 3000], [0, 3000]]
    assert room["interior_point"] == [500, 1000]


def test_tail_and_wrong_width_or_height_block_wall_and_door(layout):
    snapshot, mapping = layout
    for changed in ([600, 200, 3000], [0, 206, 3000], [0, 200, 3020], [0, 240, 3000]):
        case = deepcopy(snapshot)
        case["segments"][1]["end"] = changed
        result = propose(case, mapping)
        assert result["walls"] == result["doors"] == []
        assert result["unresolved"]
        if changed[0]:
            assert any(row.get("maximum_tail_mm") == 600 for row in result["unresolved"])


def test_competing_wall_faces_or_interior_crossings_are_unresolved(layout):
    snapshot, mapping = layout
    case = deepcopy(snapshot)
    extra = {**case["segments"][0], "id": "duplicate"}
    case["segments"].append(extra)
    assert propose(case, mapping)["walls"] == []
    for i, x in enumerate((1900, 2100)):
        snapshot["segments"].append({"id": f"cross-{i}", "layer": "A-WALL",
                                     "start": [x, -1000, 3000], "end": [x, 1000, 3000]})
    result = propose(snapshot, mapping)
    assert result["walls"] == []
    assert any("crosses" in row["reason"] for row in result["unresolved"])


def test_overlapping_door_markers_or_wrong_level_never_propose_door(layout):
    snapshot, mapping = layout
    marker = snapshot["segments"][-1]
    snapshot["segments"].append({**marker, "id": "extra-door",
                                 "start": [950, 100, 3000], "end": [1850, 100, 3000]})
    result = propose(snapshot, mapping)
    assert len(result["walls"]) == 1 and result["doors"] == []
    assert sum("Door spans overlap" in row["reason"] for row in result["unresolved"]) == 2
    marker["start"][2] = 2990
    marker["end"][2] = 2990
    snapshot["segments"].pop()
    assert propose(snapshot, mapping)["doors"] == []


def test_room_rejects_self_crossing_shared_edges_and_outside_seed(layout):
    snapshot, mapping = layout
    for vertices, seed in [
        ([[0, 0, 3000], [3500, 3000, 3000], [0, 3000, 3000], [3500, 0, 3000]], [500, 1000, 3000]),
        (snapshot["room_loops"][0]["vertices"], [3501, 1000, 3000]),
    ]:
        case = deepcopy(snapshot)
        case["room_loops"][0].update(vertices=vertices, interior_point=seed)
        assert propose(case, mapping)["rooms"] == []
    snapshot["room_loops"].append({"id": "adjacent", "layer": "A-ROOM", "closed": True,
        "vertices": [[3500, 500, 3000], [6000, 500, 3000], [6000, 3000, 3000], [3500, 3000, 3000]],
        "interior_point": [4000, 1000, 3000]})
    result = propose(snapshot, mapping)
    assert result["rooms"] == []
    assert all("share a boundary" in row["reason"] for row in result["unresolved"])


def test_segment_limit_rejects_before_pairing(layout):
    snapshot, mapping = layout
    source = snapshot["segments"][0]
    snapshot["segments"] = [{**source, "id": str(i)} for i in range(401)]
    with pytest.raises(ValueError, match="400 segments"):
        propose(snapshot, mapping)


def test_dense_competing_geometry_has_a_separate_budget(layout):
    snapshot, mapping = layout
    first, second = snapshot["segments"][:2]
    snapshot["segments"] = [{**line, "id": f"face-{group}-{i}"}
                            for group, line in enumerate((first, second)) for i in range(65)]
    with pytest.raises(ValueError, match="Too many competing wall pairs"):
        propose(snapshot, mapping)


def test_rotated_translated_wall_retains_exact_face_offset(layout):
    snapshot, mapping = layout
    for line in snapshot["segments"]:
        for key in ("start", "end"):
            x, y, z = line[key]
            line[key] = [24000 - y, x - 5000, z]
    snapshot["room_loops"] = []
    result = propose(snapshot, mapping)
    assert result["unresolved"] == []
    wall, = result["walls"]
    assert wall["axis"] == [(23900, -5000), (23900, -1000)]
    assert wall["face_residual_mm"] == 0
    assert result["doors"][0]["location"] == [23900, -3650]
