# -*- coding: utf-8 -*-
"""3D-anchored labels, Pin tool formatting, and category-scoped framing (issue #199).

Supports:
1. bounds_for_categories(elements, categories): computes bounding box only from
   chosen categories or layers so far-away site/context objects do not pull
   camera framing off the building.
2. resolve_label_anchor(anchor, elements): resolves two 3D label anchor types:
   - fixed site feature point: {"text": "Entrance", "position": [x, y, z]}
   - relative to a category/layer bounding box:
     {"text": "Tower", "category": "Mass", "rel": [0.5, 0.5, 1.0], "offset": [0, 0, 5]}
     (follows whichever design option is shown).
3. format_pin_anchor(hit_point, text): formats a clicked 3D hit point into a
   ready-to-use label config entry.
4. rhino_orbit_controls_config(): returns the three.js OrbitControls mouseButton
   mapping for Rhino convention (right-drag orbit, Shift+right-drag pan,
   left-click select, wheel zoom).
"""

import argparse
import io
import json
import sys


def bounds_for_categories(elements, categories=None):
    """Compute bounding box {"min": [x,y,z], "max": [x,y,z]} for chosen categories/layers."""
    wanted = set(str(c).strip() for c in (categories or []) if str(c).strip())
    subset = []
    if wanted:
        for el in elements or []:
            cat = str(el.get("category") or el.get("layer") or "").strip()
            if cat in wanted:
                subset.append(el)
    if not subset:
        subset = list(elements or [])

    bmin = [float("inf"), float("inf"), float("inf")]
    bmax = [float("-inf"), float("-inf"), float("-inf")]

    for el in subset:
        verts = (el.get("mesh") or {}).get("vertices") or []
        i = 0
        n = len(verts)
        while i + 2 < n:
            for k in range(3):
                v = float(verts[i + k])
                if v < bmin[k]:
                    bmin[k] = v
                if v > bmax[k]:
                    bmax[k] = v
            i += 3
        bbox = el.get("bbox")
        if bbox and len(bbox) >= 2:
            for pt in (bbox[0], bbox[1]):
                for k in range(3):
                    v = float(pt[k])
                    if v < bmin[k]:
                        bmin[k] = v
                    if v > bmax[k]:
                        bmax[k] = v

    if bmin[0] == float("inf"):
        return {"min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]}
    return {"min": bmin, "max": bmax}


def resolve_label_anchor(anchor, elements):
    """Resolve a label anchor (fixed or category-bbox-relative) to 3D [x, y, z]."""
    pos = anchor.get("position")
    off = anchor.get("offset") or [0.0, 0.0, 0.0]
    ox = float(off[0]) if len(off) > 0 else 0.0
    oy = float(off[1]) if len(off) > 1 else 0.0
    oz = float(off[2]) if len(off) > 2 else 0.0

    if pos is not None and len(pos) >= 3 and not anchor.get("category") and not anchor.get("layer"):
        return [
            round(float(pos[0]) + ox, 3),
            round(float(pos[1]) + oy, 3),
            round(float(pos[2]) + oz, 3),
        ]

    target_cat = anchor.get("category") or anchor.get("layer")
    b = bounds_for_categories(elements, [target_cat] if target_cat else None)
    rel = anchor.get("rel") or [0.5, 0.5, 1.0]
    rx = float(rel[0]) if len(rel) > 0 else 0.5
    ry = float(rel[1]) if len(rel) > 1 else 0.5
    rz = float(rel[2]) if len(rel) > 2 else 1.0

    return [
        round(b["min"][0] + (b["max"][0] - b["min"][0]) * rx + ox, 3),
        round(b["min"][1] + (b["max"][1] - b["min"][1]) * ry + oy, 3),
        round(b["min"][2] + (b["max"][2] - b["min"][2]) * rz + oz, 3),
    ]


def format_pin_anchor(hit_point, text="Label"):
    """Format a 3D hit point from the Pin tool into a label config dict."""
    return {
        "text": str(text),
        "position": [
            round(float(hit_point[0]), 2),
            round(float(hit_point[1]), 2),
            round(float(hit_point[2]), 2),
        ],
    }


def rhino_orbit_controls_config():
    """Return the three.js OrbitControls mouseButtons config for Rhino convention."""
    return {
        "LEFT": None,
        "MIDDLE": "PAN",
        "RIGHT": "ROTATE",
        "note": "OrbitControls pans automatically on ROTATE + Shift (Shift + right-drag).",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Resolve 3D-anchored labels and category framing.")
    ap.add_argument("input", help="Path to viewer JSON file")
    ap.add_argument("--categories", help="Comma-separated categories to frame")
    ap.add_argument("--pin", help="Comma-separated x,y,z from Pin tool")
    ap.add_argument("--label-text", default="Callout")
    args = ap.parse_args(argv)

    if args.pin:
        pts = [float(x) for x in args.pin.split(",")]
        print(json.dumps(format_pin_anchor(pts, args.label_text), indent=2))
        return 0

    with io.open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    elements = data.get("elements") or []
    cats = [c.strip() for c in (args.categories or "").split(",") if c.strip()]
    bounds = bounds_for_categories(elements, cats)
    resolved = []
    for a in data.get("annotations") or []:
        item = dict(a)
        item["resolved_position"] = resolve_label_anchor(a, elements)
        resolved.append(item)

    print(json.dumps({"bounds": bounds, "annotations": resolved}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
