# -*- coding: utf-8 -*-
"""COMPUTE, DRAW and VERIFY steps for the detail-annotation recipe (issue #298).

Runs outside Revit (CPython 3).

Sum up the house style of the reference details in a read result:
    python detail_annotation_preview.py style --read read.json --view <target view id>

Compute a change preview from a plan (items in view coordinates, feet):
    python detail_annotation_preview.py compute --read read.json --plan plan.json --out preview.json

Draw the preview over a capture of the view (a PNG from capture_view):
    python detail_annotation_preview.py draw --preview preview.json --out preview-drawing.html
        [--capture view.png --known "u1,v1:px1,py1" --known "u2,v2:px2,py2"]
    Without --known, the crop region fills the image. Without --capture,
    the page draws the plan on a blank sheet with the crop region.

Compare an apply result (dry run or real run) with the preview:
    python detail_annotation_preview.py compare --preview preview.json --actual run.json

Show the side-effect counts of a dry run (filled region sketches are expected):
    python detail_annotation_preview.py side-effects --preview preview.json --dryrun dryrun.json

Input files may be the bare result or the whole run JSON.
Exit codes: 0 ok, 1 differences or blocked, 2 bad input.
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import detail_annotation as da  # noqa: E402
import side_effects as se  # noqa: E402

BLANK_SIZE = (1000, 700)


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def parse_known(spec):
    """'u,v:px,py' into ([u, v], [px, py])."""
    try:
        view_part, pixel_part = spec.split(":")
        u, v = [float(x) for x in view_part.split(",")]
        px, py = [float(x) for x in pixel_part.split(",")]
    except ValueError:
        raise da.PlanError("Bad --known value %r: use \"u,v:px,py\"." % spec)
    return [u, v], [px, py]


def draw(preview, out, capture=None, known=None):
    warnings = []
    if capture:
        with io.open(capture, "rb") as f:
            png = f.read()
        width, height = da.png_size(png)
        href = da.data_uri(png)
    else:
        width, height = BLANK_SIZE
        href = None
    crop = (preview.get("view") or {}).get("crop_uv")
    if known:
        if len(known) != 2:
            raise da.PlanError("Give exactly two --known points.")
        (va, pa), (vb, pb) = [parse_known(k) for k in known]
        mapping, warnings = da.mapping_from_points(va, pa, vb, pb)
        note = "Mapped with two known points."
    else:
        mapping = da.mapping_from_crop(crop, width, height, margin=0 if capture else 40)
        note = ("Mapped from the crop region. If the view was panned or zoomed, the overlay can be off: "
                "use two known points." if capture else "No capture: drawn on a blank sheet.")
    svg = da.svg_overlay(preview, mapping, width, height, href)
    write_text(out, da.html_page(preview, svg, note))
    return note, warnings


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("style")
    s.add_argument("--read", required=True)
    s.add_argument("--view", help="target view id (left out of the summary)")
    c = sub.add_parser("compute")
    c.add_argument("--read", required=True)
    c.add_argument("--plan", required=True)
    c.add_argument("--out", required=True)
    d = sub.add_parser("draw")
    d.add_argument("--preview", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--capture")
    d.add_argument("--known", action="append", default=[])
    v = sub.add_parser("compare")
    v.add_argument("--preview", required=True)
    v.add_argument("--actual", required=True)
    e = sub.add_parser("side-effects")
    e.add_argument("--preview", required=True)
    e.add_argument("--dryrun", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "style":
            read = da.load_read(load_json(a.read))
            print(da.style_text(da.style_summary(read, a.view)))
            return 0
        if a.cmd == "compute":
            read = da.load_read(load_json(a.read))
            preview = da.compute_plan(read, load_json(a.plan))
            write_text(a.out, json.dumps(preview, indent=1, ensure_ascii=False))
            print(da.text_table(preview))
            return 1 if preview["blocked"] else 0
        if a.cmd == "draw":
            note, warnings = draw(load_json(a.preview), a.out, a.capture, a.known)
            print("Wrote %s. %s" % (a.out, note))
            for w in warnings:
                print("WARN: %s" % w)
            return 0
        if a.cmd == "compare":
            preview = load_json(a.preview)
            diffs = da.compare(preview, load_json(a.actual))
            if diffs:
                print("DIFFERENT from preview (%d):" % len(diffs))
                for line in diffs:
                    print("  " + line)
                return 1
            print("MATCHES PREVIEW: %d new element(s) checked." % len(preview.get("steps") or []))
            return 0
        if a.cmd == "side-effects":
            preview = load_json(a.preview)
            summary = se.summarize(preview, load_json(a.dryrun), preview.get("edited_categories") or [])
            print(se.text_table(summary))
            return 0
    except (da.PlanError, ValueError, KeyError, IOError, OSError) as exc:
        print("ERROR: %s" % exc)
        return 2
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
