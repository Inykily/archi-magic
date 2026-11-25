"""Fit a locked axonometric camera to a reference drawing (issue #272, first step).

A parallel (axonometric) view has five unknowns: azimuth, elevation, scale and a 2D offset.
Give three or more landmark pairs: a model point (x, y, z in the export units, feet) and the
same point on the reference image (pixels, x to the right, y down). The fit returns the camera
and the error of each landmark in pixels. Use four or more pairs, so one pair checks the others.

The camera uses the viewer's convention (mods/am-bim-viewer/viewer/viewer-core.mjs cameraBasis):
  azimuth   = angle in plan of the direction target -> camera, from +X toward +Y
  elevation = angle of that direction above the XY plane
  screen right r = (-sin az, cos az, 0), screen up u = d x r, d = direction to the camera

Input JSON:
  {"image": {"width": 1600, "height": 1000},          (optional, gives target and view height)
   "pairs": [{"name": "NE corner", "model": [x, y, z], "image": [px, py]}, ...]}

Usage:
  python axon_fit.py landmarks.json [--out camera.json] [--allow-below]

Pure Python 3, no Revit, no network. The fit does not fit a perspective rendering.
"""

import argparse
import io
import json
import math
import sys

DEG = math.pi / 180.0


def basis(azimuth, elevation):
    """Screen right and screen up vectors for a camera at (azimuth, elevation), in radians."""
    ca, sa = math.cos(azimuth), math.sin(azimuth)
    ce, se = math.cos(elevation), math.sin(elevation)
    d = (ce * ca, ce * sa, se)
    r = (-sa, ca, 0.0)
    u = (d[1] * r[2] - d[2] * r[1], d[2] * r[0] - d[0] * r[2], d[0] * r[1] - d[1] * r[0])
    return r, u, d


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def project(point, azimuth, elevation, scale=1.0, offset=(0.0, 0.0)):
    """Image pixel (x right, y down) of a model point."""
    r, u, _ = basis(azimuth, elevation)
    return (offset[0] + scale * dot(point, r), offset[1] - scale * dot(point, u))


def _solve_scale_offset(model, image, azimuth, elevation):
    """Best scale and offset for a fixed view direction (closed-form least squares)."""
    r, u, _ = basis(azimuth, elevation)
    sx = [dot(p, r) for p in model]
    sy = [-dot(p, u) for p in model]
    n = float(len(model))
    msx, msy = sum(sx) / n, sum(sy) / n
    mix = sum(q[0] for q in image) / n
    miy = sum(q[1] for q in image) / n
    num = den = 0.0
    for i in range(len(model)):
        ax, ay = sx[i] - msx, sy[i] - msy
        num += ax * (image[i][0] - mix) + ay * (image[i][1] - miy)
        den += ax * ax + ay * ay
    if den <= 0.0:
        return None
    s = num / den
    if s <= 0.0:
        return None
    ox, oy = mix - s * msx, miy - s * msy
    err = 0.0
    for i in range(len(model)):
        ex = ox + s * sx[i] - image[i][0]
        ey = oy + s * sy[i] - image[i][1]
        err += ex * ex + ey * ey
    return s, (ox, oy), err


def _check_pairs(pairs):
    if not isinstance(pairs, list) or len(pairs) < 3:
        raise ValueError("Give at least three landmark pairs.")
    model, image, names = [], [], []
    for i, p in enumerate(pairs):
        try:
            m = [float(v) for v in p["model"]]
            q = [float(v) for v in p["image"]]
        except (KeyError, TypeError, ValueError):
            raise ValueError("Pair %d needs \"model\": [x, y, z] and \"image\": [px, py]." % (i + 1))
        if len(m) != 3 or len(q) != 2 or not all(math.isfinite(v) for v in m + q):
            raise ValueError("Pair %d needs \"model\": [x, y, z] and \"image\": [px, py]." % (i + 1))
        model.append(tuple(m))
        image.append(tuple(q))
        names.append(str(p.get("name") or "pair %d" % (i + 1)))
    # The model points must span a plane at least (not all on one line).
    a = model[0]
    span = 0.0
    for b in model[1:]:
        for c in model[1:]:
            ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
            ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
            cx = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0])
            span = max(span, math.sqrt(dot(cx, cx)))
    if span < 1e-9:
        raise ValueError("The model points are on one line. Pick landmarks that are not in a row.")
    return model, image, names


def fit_axon(pairs, allow_below=False, image_size=None):
    """Fit azimuth, elevation, scale and offset. Returns a JSON-ready dict."""
    model, image, names = _check_pairs(pairs)
    el_lo, el_hi = (-89.0 if allow_below else 1.0), 89.0
    best = None
    az = 0.0
    while az < 360.0:
        el = el_lo
        while el <= el_hi + 1e-9:
            sol = _solve_scale_offset(model, image, az * DEG, el * DEG)
            if sol and (best is None or sol[2] < best[0]):
                best = (sol[2], az, el)
            el += 2.0
        az += 2.0
    if best is None:
        raise ValueError("No view direction fits these pairs. Check that each image point matches its model point.")
    # Pattern search from the best grid cell, down to a small fraction of a degree.
    _, az, el = best
    step = 2.0
    err = best[0]
    while step > 1e-5:
        moved = False
        for daz, del_ in ((step, 0), (-step, 0), (0, step), (0, -step)):
            na, ne = az + daz, el + del_
            if ne < el_lo - 1.0 or ne > 90.0:
                continue
            sol = _solve_scale_offset(model, image, na * DEG, ne * DEG)
            if sol and sol[2] < err:
                err, az, el, moved = sol[2], na, ne, True
                break
        if not moved:
            step /= 2.0
    az %= 360.0
    s, offset, err = _solve_scale_offset(model, image, az * DEG, el * DEG)
    residuals = []
    for i in range(len(model)):
        px, py = project(model[i], az * DEG, el * DEG, s, offset)
        residuals.append({"name": names[i], "dx": px - image[i][0], "dy": py - image[i][1],
                          "px": math.hypot(px - image[i][0], py - image[i][1])})
    out = {
        "kind": "axon-fit",
        "projection": "parallel",
        "locked": True,
        "azimuthDeg": az,
        "elevationDeg": el,
        "azimuth": az * DEG,
        "elevation": el * DEG,
        "scalePxPerUnit": s,
        "offsetPx": [offset[0], offset[1]],
        "rmsPx": math.sqrt(err / len(model)),
        "maxPx": max(r["px"] for r in residuals),
        "residuals": residuals,
        "pairs": len(model),
        "checked": len(model) >= 4,
    }
    if image_size:
        w, h = float(image_size[0]), float(image_size[1])
        r, u, _ = basis(az * DEG, el * DEG)
        cx = (w / 2.0 - offset[0]) / s
        cy = -(h / 2.0 - offset[1]) / s
        # The model point at the image center (on the plane through the origin, normal to the view).
        out["target"] = [cx * r[i] + cy * u[i] for i in range(3)]
        # Height and width of the parallel view in model units (an OrthographicCamera frustum).
        out["viewHeight"] = h / s
        out["viewWidth"] = w / s
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("landmarks", help="JSON file with the landmark pairs")
    ap.add_argument("--out", help="write the camera JSON here")
    ap.add_argument("--allow-below", action="store_true", help="also try views from below the XY plane")
    args = ap.parse_args(argv)
    with io.open(args.landmarks, encoding="utf-8-sig") as f:
        data = json.load(f)
    size = None
    img = data.get("image") if isinstance(data, dict) else None
    if isinstance(img, dict) and img.get("width") and img.get("height"):
        size = (img["width"], img["height"])
    pairs = data.get("pairs") if isinstance(data, dict) else data
    try:
        result = fit_axon(pairs, allow_below=args.allow_below, image_size=size)
    except ValueError as exc:
        print("FAIL: %s" % exc)
        return 1
    text = json.dumps(result, indent=2)
    if args.out:
        with io.open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    if not result["checked"]:
        print("WARN: only three pairs. Add a fourth landmark to check the fit.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
