"""axon_fit.py: fit a locked axonometric camera from landmark pairs (issue #272)."""
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import axon_fit  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "axon_fit.py"
POINTS = [(0, 0, 0), (120, 0, 0), (120, 80, 0), (0, 80, 0), (60, 40, 45), (120, 80, 30)]


def pairs_for(az_deg, el_deg, scale, offset, points=POINTS, noise=None):
    out = []
    for i, p in enumerate(points):
        px, py = axon_fit.project(p, az_deg * axon_fit.DEG, el_deg * axon_fit.DEG, scale, offset)
        if noise:
            px += noise[i % len(noise)][0]
            py += noise[i % len(noise)][1]
        out.append({"name": "p%d" % i, "model": list(p), "image": [px, py]})
    return out


def angle_diff(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def test_basis_matches_the_viewer_named_views():
    # viewer-core.mjs: top = az -90, el 90 shows North up and East right.
    east = axon_fit.project((1, 0, 0), -90 * axon_fit.DEG, 89.999 * axon_fit.DEG)
    north = axon_fit.project((0, 1, 0), -90 * axon_fit.DEG, 89.999 * axon_fit.DEG)
    assert east[0] > 0.99 and abs(east[1]) < 1e-3
    assert north[1] < -0.99   # image y grows down, so North (up) is negative


@pytest.mark.parametrize("az,el", [(315, 35.264), (30, 20), (200, 60), (-45, 45)])
def test_fit_recovers_a_known_camera(az, el):
    result = axon_fit.fit_axon(pairs_for(az, el, 4.5, (800, 520)), image_size=(1600, 1000))
    assert angle_diff(result["azimuthDeg"], az) < 1e-3
    assert abs(result["elevationDeg"] - el) < 1e-3
    assert abs(result["scalePxPerUnit"] - 4.5) < 1e-3
    assert result["maxPx"] < 0.01
    assert result["checked"] is True
    assert abs(result["viewHeight"] - 1000 / 4.5) < 1e-2


def test_flat_landmarks_on_the_ground_still_fit():
    flat = [(0, 0, 0), (100, 0, 0), (100, 60, 0), (0, 60, 0)]
    result = axon_fit.fit_axon(pairs_for(320, 30, 3.0, (500, 400), points=flat))
    assert angle_diff(result["azimuthDeg"], 320) < 1e-2
    assert abs(result["elevationDeg"] - 30) < 1e-2


def test_residuals_show_a_wrong_landmark():
    pairs = pairs_for(315, 35, 4.0, (700, 500))
    pairs[4]["image"][0] += 40   # one point picked in the wrong place
    result = axon_fit.fit_axon(pairs)
    worst = max(result["residuals"], key=lambda r: r["px"])
    assert worst["name"] == "p4"
    assert result["maxPx"] > 10


def test_small_noise_gives_a_small_error():
    noise = [(0.8, -0.5), (-0.6, 0.4), (0.3, 0.9), (-0.9, -0.2)]
    result = axon_fit.fit_axon(pairs_for(300, 40, 5.0, (900, 600), noise=noise))
    assert angle_diff(result["azimuthDeg"], 300) < 0.5
    assert abs(result["elevationDeg"] - 40) < 0.5
    assert result["rmsPx"] < 1.5


def test_target_is_the_model_point_at_the_image_center():
    result = axon_fit.fit_axon(pairs_for(315, 35, 4.0, (700, 500)), image_size=(1400, 1000))
    cx, cy = axon_fit.project(result["target"], result["azimuth"], result["elevation"],
                              result["scalePxPerUnit"], result["offsetPx"])
    assert math.hypot(cx - 700, cy - 500) < 1e-6


@pytest.mark.parametrize("pairs,msg", [
    ([], "at least three"),
    ([{"model": [0, 0, 0], "image": [0, 0]}] * 2, "at least three"),
    ([{"model": [0, 0, 0], "image": [0, 0]}, {"model": [1, 1, 1], "image": [1, 1]},
      {"model": [2, 2, 2], "image": [2, 2]}], "one line"),
    ([{"model": [0, 0], "image": [0, 0]}] * 3, "needs"),
])
def test_bad_input(pairs, msg):
    with pytest.raises(ValueError, match=msg):
        axon_fit.fit_axon(pairs)


def test_cli_writes_the_camera(tmp_path):
    src = tmp_path / "landmarks.json"
    out = tmp_path / "camera.json"
    src.write_text(json.dumps({"image": {"width": 1600, "height": 1000},
                               "pairs": pairs_for(315, 35, 4.0, (800, 500))[:3]}), encoding="utf-8")
    run = subprocess.run([sys.executable, str(SCRIPT), str(src), "--out", str(out)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    cam = json.loads(out.read_text(encoding="utf-8"))
    assert cam["kind"] == "axon-fit" and cam["locked"] is True and cam["checked"] is False
    assert "Add a fourth landmark" in run.stderr
