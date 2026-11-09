# -*- coding: utf-8 -*-
"""Export one design option from a large working Rhino .3dm for a web viewer (issue #198).

Provides pure planning and filtering functions (plus sequential cloud-file
reading for rhino3dm):
1. effective_layer_visibility(): parent-aware visibility (a child layer is
   effectively visible only when it AND every ancestor layer is visible).
2. list_design_options(): inventories option root layers with object counts,
   effective visibility, and missing render-mesh counts.
3. remap_near_black_color(): maps near-black layer colors (e.g. 0,0,0) to a
   light grey so web viewers do not render dark blobs.
4. filter_stray_objects(): crops stray objects parked below a Z threshold or
   outside a horizontal radius from the site center, reporting what was dropped.
5. plan_option_export(): prepares a mesh-only export for one option root,
   warning clearly when Breps or Extrusions have no saved render mesh (files
   saved with "Save Small").
6. read_3dm_sequential(): reads cloud-only .3dm files one at a time and retries
   once if File3dm.Read returns None.
"""

import argparse
import io
import json
import math
import sys
import time


def effective_layer_visibility(layers):
    """Compute parent-aware visibility for each layer.

    layers: [{"id": str, "name": str, "full_path": str,
              "parent_id": str or None, "visible": bool, "color": [r, g, b]}]
    Returns dict mapping layer id -> bool (True only if layer and all ancestors are visible).
    """
    by_id = {}
    for lay in layers or []:
        lid = str(lay.get("id") if lay.get("id") is not None else lay.get("full_path") or lay.get("name"))
        by_id[lid] = lay

    memo = {}

    def is_vis(lid, seen=None):
        if lid in memo:
            return memo[lid]
        if seen is None:
            seen = set()
        if lid in seen:
            return False
        seen.add(lid)
        lay = by_id.get(lid)
        if lay is None:
            return False
        if not bool(lay.get("visible", True)):
            memo[lid] = False
            return False
        pid = lay.get("parent_id")
        if pid is not None and str(pid) != "" and str(pid) in by_id:
            res = is_vis(str(pid), seen)
            memo[lid] = res
            return res
        memo[lid] = True
        return True

    out = {}
    for lid in by_id:
        out[lid] = is_vis(lid)
    return out


def remap_near_black_color(rgb, threshold=25, fallback=(200, 200, 200)):
    """Map near-black layer RGB colors to light grey for web readability."""
    if not rgb or len(rgb) < 3:
        return list(fallback)
    r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
    if r <= threshold and g <= threshold and b <= threshold:
        return [int(fallback[0]), int(fallback[1]), int(fallback[2])]
    return [r, g, b]


def _root_name(full_path):
    return str(full_path or "").split("::")[0].strip()


def list_design_options(layers, objects):
    """List top-level option layer trees with object counts and effective visibility."""
    vis_map = effective_layer_visibility(layers)
    layer_by_id = {}
    roots = {}

    for lay in layers or []:
        lid = str(lay.get("id") if lay.get("id") is not None else lay.get("full_path") or lay.get("name"))
        fpath = str(lay.get("full_path") or lay.get("name") or "")
        rname = _root_name(fpath)
        layer_by_id[lid] = {"layer": lay, "root": rname, "effective_visible": vis_map.get(lid, False)}
        rinfo = roots.setdefault(rname, {
            "root_name": rname,
            "layer_count": 0,
            "effective_visible": False,
            "total_objects": 0,
            "visible_objects": 0,
            "missing_render_mesh_count": 0,
        })
        rinfo["layer_count"] += 1
        if vis_map.get(lid, False):
            rinfo["effective_visible"] = True

    for obj in objects or []:
        lid = str(obj.get("layer_id") if obj.get("layer_id") is not None else obj.get("layer_path") or "")
        info = layer_by_id.get(lid)
        if info is None:
            rname = _root_name(obj.get("layer_path") or "")
            eff = True
        else:
            rname = info["root"]
            eff = info["effective_visible"]
        rinfo = roots.setdefault(rname, {
            "root_name": rname,
            "layer_count": 0,
            "effective_visible": eff,
            "total_objects": 0,
            "visible_objects": 0,
            "missing_render_mesh_count": 0,
        })
        rinfo["total_objects"] += 1
        if eff:
            rinfo["visible_objects"] += 1
            otype = str(obj.get("object_type") or "mesh").lower()
            if otype in ("brep", "extrusion", "subd") and not bool(obj.get("has_render_mesh", True)):
                rinfo["missing_render_mesh_count"] += 1

    return [roots[k] for k in sorted(roots.keys()) if k]


def filter_stray_objects(objects, z_min=-100.0, center_xy=(0.0, 0.0), max_radius=1500.0):
    """Drop objects parked below z_min or outside max_radius from center_xy."""
    cx, cy = float(center_xy[0]), float(center_xy[1])
    kept = []
    dropped = []
    dropped_z = 0
    dropped_r = 0

    for obj in objects or []:
        bbox = obj.get("bbox")
        if not bbox or len(bbox) < 2:
            kept.append(obj)
            continue
        bmin, bmax = bbox[0], bbox[1]
        min_z = float(bmin[2])
        ox = 0.5 * (float(bmin[0]) + float(bmax[0]))
        oy = 0.5 * (float(bmin[1]) + float(bmax[1]))
        dist_xy = math.hypot(ox - cx, oy - cy)

        if min_z < float(z_min):
            dropped_z += 1
            dropped.append({"id": obj.get("id"), "reason": "below_z_min", "min_z": round(min_z, 2)})
            continue
        if max_radius is not None and dist_xy > float(max_radius):
            dropped_r += 1
            dropped.append({"id": obj.get("id"), "reason": "outside_radius", "distance_xy": round(dist_xy, 2)})
            continue
        kept.append(obj)

    return {
        "kept": kept,
        "dropped": dropped,
        "dropped_below_z": dropped_z,
        "dropped_outside_radius": dropped_r,
    }


def plan_option_export(layers, objects, option_root, re_root_name=None,
                       z_min=-100.0, center_xy=(0.0, 0.0), max_radius=1500.0):
    """Prepare a lightweight mesh-only export plan for one design option root."""
    vis_map = effective_layer_visibility(layers)
    short_root = str(re_root_name or option_root).strip()

    opt_layers = {}
    exported_layers = []
    remapped_colors = 0

    for lay in layers or []:
        lid = str(lay.get("id") if lay.get("id") is not None else lay.get("full_path") or lay.get("name"))
        fpath = str(lay.get("full_path") or lay.get("name") or "")
        if _root_name(fpath) != option_root:
            continue
        eff = vis_map.get(lid, False)
        orig_color = list(lay.get("color") or [200, 200, 200])
        new_color = remap_near_black_color(orig_color)
        if new_color != orig_color[:3]:
            remapped_colors += 1
        suffix = fpath[len(option_root):].lstrip(":")
        new_path = ("%s::%s" % (short_root, suffix)) if suffix else short_root
        entry = {
            "id": lid,
            "original_path": fpath,
            "export_path": new_path,
            "effective_visible": eff,
            "color": new_color,
        }
        opt_layers[lid] = entry
        if eff:
            exported_layers.append(entry)

    candidates = []
    for obj in objects or []:
        lid = str(obj.get("layer_id") if obj.get("layer_id") is not None else obj.get("layer_path") or "")
        linfo = opt_layers.get(lid)
        if linfo is None:
            continue
        if not linfo["effective_visible"]:
            continue
        candidates.append(obj)

    crop = filter_stray_objects(candidates, z_min=z_min, center_xy=center_xy, max_radius=max_radius)
    exportable = []
    missing_mesh = []

    for obj in crop["kept"]:
        otype = str(obj.get("object_type") or "mesh").lower()
        has_mesh = bool(obj.get("has_render_mesh", True))
        if otype in ("brep", "extrusion", "subd") and not has_mesh:
            missing_mesh.append(obj.get("id"))
        else:
            exportable.append(obj)

    warnings = []
    if missing_mesh:
        warnings.append(
            "%d brep/extrusion object(s) have no saved render mesh (file may be saved with Save Small). "
            "Open in Rhino, switch to a Shaded viewport, and save without Save Small."
            % len(missing_mesh)
        )

    return {
        "option_root": option_root,
        "export_root": short_root,
        "layer_count": len(exported_layers),
        "remapped_black_layers": remapped_colors,
        "candidate_objects": len(candidates),
        "exported_objects": len(exportable),
        "dropped_count": len(crop["dropped"]),
        "dropped_below_z": crop["dropped_below_z"],
        "dropped_outside_radius": crop["dropped_outside_radius"],
        "dropped": crop["dropped"],
        "missing_render_mesh_count": len(missing_mesh),
        "missing_render_mesh_ids": missing_mesh,
        "warnings": warnings,
        "layers": exported_layers,
        "objects": exportable,
    }


def read_3dm_sequential(paths, reader_fn, retry_delay_s=0.0):
    """Read cloud-only .3dm files one at a time, retrying once if reader_fn returns None."""
    results = []
    for p in paths or []:
        model = reader_fn(p)
        retried = False
        if model is None:
            if retry_delay_s > 0:
                time.sleep(float(retry_delay_s))
            retried = True
            model = reader_fn(p)
        results.append({
            "path": p,
            "loaded": model is not None,
            "retried": retried,
            "model": model,
        })
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="Plan or inspect a Rhino .3dm design-option web export.")
    ap.add_argument("input", help="Path to JSON snapshot of layers and objects")
    ap.add_argument("--option", help="Option root layer name to export")
    ap.add_argument("--re-root", help="Short root layer name in exported file")
    ap.add_argument("--z-min", type=float, default=-100.0)
    ap.add_argument("--max-radius", type=float, default=1500.0)
    ap.add_argument("--out", help="Output plan JSON path")
    args = ap.parse_args(argv)

    with io.open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    layers = data.get("layers") or []
    objects = data.get("objects") or []

    if not args.option:
        opts = list_design_options(layers, objects)
        res = {"options": opts}
    else:
        res = plan_option_export(
            layers, objects, args.option,
            re_root_name=args.re_root,
            z_min=args.z_min,
            max_radius=args.max_radius,
        )

    if args.out:
        with io.open(args.out, "w", encoding="utf-8") as f:
            f.write(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
