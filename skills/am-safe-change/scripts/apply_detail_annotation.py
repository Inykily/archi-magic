# -*- coding: utf-8 -*-
"""EXECUTE step for the detail-annotation recipe (issue #298). run_modify.

inputs: {"preview_path": "C:/.../annotation.preview.json"}   (forward slashes are fine)
    or  {"preview": {...preview dict...}}

Replays the preview's ordered "steps" inside ONE transaction, so the
user's Keep/Discard in Revit is all-or-nothing. Before it changes
anything it checks that the view still exists with the same origin and
directions as in the preview, and that every type and line style id
still exists. If not, it stops with no change ("Model changed since the
preview").

Steps:
- filled_region: FilledRegion.Create(doc, type_id, view_id, loops).
  Revit also adds the region's sketch: <Sketch> lines, automatic sketch
  dimensions and a sketch with no category. The preview expects them.
- detail_line: doc.Create.NewDetailCurve(view, Line), then LineStyle.
- text_note: TextNote.Create with TextNoteOptions (type, horizontal
  alignment). With a leader end, LeaderLeftAttachment is set first
  (TopLine by default), then AddLeader(TNLT_STRAIGHT_L) and only the
  leader End is set. With a centered note and the end straight below
  it, Revit puts the anchor and the elbow at the bottom center, so the
  leader is vertical. This matched finished details in the field.

result = {"view_id", "created": [{"step", "kind", "ids", "type_id",
          "loops" | "start", "end" | "at", "text", "leader_end"}],
          "steps_applied": n, "escaped": bool}
Points in the result are re-read from the new elements, in view
coordinates. A dry run returns the same result and Revit rolls back.
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import io
import json
import sys

from pyrevit.api import DB

ESCAPE = sys.platform == "cli"  # IronPython result encoder is ASCII-only (see read_sheets.py)
FRAME_TOLERANCE = 1e-6


def txt(s):
    if s is None or not ESCAPE:
        return s
    out = []
    for c in s:
        if c == "\\":
            out.append("\\\\")
        elif ord(c) < 128:
            out.append(c)
        else:
            out.append("\\u%04x" % ord(c))
    return "".join(out)


def id_int(element_id):
    try:
        return int(element_id.Value)        # Revit 2024+
    except AttributeError:
        return int(element_id.IntegerValue)  # removed in Revit 2026


try:
    import System
    from System.Collections.Generic import List

    def eid(n):
        return DB.ElementId(System.Int64(int(n)))
except ImportError:
    List = None

    def eid(n):
        return DB.ElementId(int(n))


def load_preview():
    if inputs.get("preview"):  # noqa: F821
        return inputs["preview"]  # noqa: F821
    path = inputs.get("preview_path")  # noqa: F821
    if not path:
        raise ValueError("inputs needs preview_path or preview")
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.loads(f.read())


def to_xyz(p):
    return DB.XYZ(float(p[0]), float(p[1]), float(p[2]))


class Frame(object):
    def __init__(self, view):
        self.o = view.Origin
        self.r = view.RightDirection
        self.u = view.UpDirection

    def uv(self, p):
        dx, dy, dz = p.X - self.o.X, p.Y - self.o.Y, p.Z - self.o.Z
        return [round(dx * self.r.X + dy * self.r.Y + dz * self.r.Z, 6),
                round(dx * self.u.X + dy * self.u.Y + dz * self.u.Z, 6)]


def same_vector(a, b):
    return all(abs(a[i] - b[i]) <= FRAME_TOLERANCE for i in range(3))


def check_stale(preview, view):
    frame = preview.get("view") or {}
    if view is None or not isinstance(view, DB.View):
        raise ValueError("Model changed since the preview: the view %s is gone." % frame.get("id"))
    now = {"origin": [view.Origin.X, view.Origin.Y, view.Origin.Z],
           "right": [view.RightDirection.X, view.RightDirection.Y, view.RightDirection.Z],
           "up": [view.UpDirection.X, view.UpDirection.Y, view.UpDirection.Z]}
    for key in ("origin", "right", "up"):
        if not same_vector(now[key], frame.get(key) or [0, 0, 0]):
            raise ValueError("Model changed since the preview: the view %s moved." % key)
    for step in preview.get("steps") or []:
        if doc.GetElement(eid(step["type_id"])) is None:  # noqa: F821
            raise ValueError("Model changed since the preview: type or style %s is gone." % step["type_id"])


def curve_loop(points):
    loop = DB.CurveLoop()
    n = len(points)
    for i in range(n):
        loop.Append(DB.Line.CreateBound(to_xyz(points[i]), to_xyz(points[(i + 1) % n])))
    return loop


def make_filled_region(view, step):
    if List is None:
        raise ValueError("FilledRegion.Create needs a .NET List (System.Collections.Generic).")
    loops = List[DB.CurveLoop]()
    for pts in step["loops_model"]:
        loops.Add(curve_loop(pts))
    region = DB.FilledRegion.Create(doc, eid(step["type_id"]), view.Id, loops)  # noqa: F821
    return [region]


def make_detail_line(view, step):
    line = DB.Line.CreateBound(to_xyz(step["start_model"]), to_xyz(step["end_model"]))
    curve = doc.Create.NewDetailCurve(view, line)  # noqa: F821
    curve.LineStyle = doc.GetElement(eid(step["type_id"]))  # noqa: F821
    return [curve]


def make_text_note(view, step):
    options = DB.TextNoteOptions(eid(step["type_id"]))
    options.HorizontalAlignment = getattr(DB.HorizontalTextAlignment, step.get("align") or "Center")
    note = DB.TextNote.Create(doc, view.Id, to_xyz(step["at_model"]), step["text"], options)  # noqa: F821
    if step.get("leader_end_model") is not None:
        note.LeaderLeftAttachment = getattr(DB.LeaderAtachement, step.get("leader_left") or "TopLine")
        leader = note.AddLeader(DB.TextNoteLeaderTypes.TNLT_STRAIGHT_L)
        leader.End = to_xyz(step["leader_end_model"])
    return [note]


def reread(frame, step, elements):
    el = elements[0]
    row = {"step": step["step"], "kind": step["kind"], "ids": [id_int(e.Id) for e in elements]}
    if step["kind"] == "filled_region":
        row["type_id"] = id_int(el.GetTypeId())
        row["loops"] = [[frame.uv(c.GetEndPoint(0)) for c in loop] for loop in el.GetBoundaries()]
    elif step["kind"] == "detail_line":
        row["type_id"] = id_int(el.LineStyle.Id)
        curve = el.GeometryCurve
        row["start"] = frame.uv(curve.GetEndPoint(0))
        row["end"] = frame.uv(curve.GetEndPoint(1))
    else:
        row["type_id"] = id_int(el.GetTypeId())
        row["text"] = txt(el.Text.rstrip("\r"))
        row["at"] = frame.uv(el.Coord)
        leaders = list(el.GetLeaders())
        row["leader_end"] = frame.uv(leaders[0].End) if leaders else None
    return row


MAKERS = {"filled_region": make_filled_region, "detail_line": make_detail_line,
          "text_note": make_text_note}


def main():
    preview = load_preview()
    if preview.get("blocked"):
        raise ValueError("The preview is blocked. Fix the plan first.")
    steps = preview.get("steps") or []
    if not steps:
        raise ValueError("The preview has no steps.")
    view = doc.GetElement(eid((preview.get("view") or {}).get("id")))  # noqa: F821
    check_stale(preview, view)
    frame = Frame(view)
    made = []
    t = DB.Transaction(doc, preview.get("title") or "Annotate detail view")  # noqa: F821
    t.Start()
    try:
        for step in steps:
            made.append((step, MAKERS[step["kind"]](view, step)))
        doc.Regenerate()  # noqa: F821
        created = [reread(frame, step, elements) for step, elements in made]
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return {"view_id": id_int(view.Id), "created": created, "steps_applied": len(created),
            "escaped": ESCAPE}


result = main()
