import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "carbon_report.py"


def run(tmp_path, volumes, factors):
    volume_file = tmp_path / "takeoff.csv"
    factor_file = tmp_path / "factors.csv"
    volume_file.write_text("material,category,level,volume_m3\n" + volumes, encoding="utf-8-sig")
    factor_file.write_text("material,kg_co2e_per_m3\n" + factors, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--volumes", str(volume_file), "--factors", str(factor_file)],
        capture_output=True, text=True,
    )


def test_reports_unmapped_materials_without_zeroing_them(tmp_path):
    result = run(tmp_path, "Steel,Walls,L1,2\nConcrete,Walls,L1,1.5\nGlass,Floors,L2,4\n",
                 "Steel,100\n")
    data = json.loads(result.stdout)
    assert result.returncode == 1
    assert data["status"] == "incomplete"
    assert data["totals"] == {
        "mapped_volume_m3": "2", "unmapped_volume_m3": "5.5", "known_kg_co2e": "200",
    }
    assert data["by_category_and_level"] == [
        {"category": "Floors", "level": "L2", "mapped_volume_m3": "0",
         "unmapped_volume_m3": "4", "known_kg_co2e": None},
        {"category": "Walls", "level": "L1", "mapped_volume_m3": "2",
         "unmapped_volume_m3": "1.5", "known_kg_co2e": "200"},
    ]
    assert data["unmapped_materials"] == [
        {"category": "Floors", "level": "L2", "material": "Glass", "volume_m3": "4"},
        {"category": "Walls", "level": "L1", "material": "Concrete", "volume_m3": "1.5"},
    ]


def test_zero_factor_is_mapped_and_known_carbon_is_summed(tmp_path):
    result = run(tmp_path, "Steel,Walls,L1,2\nSteel,Walls,L1,0.5\nReuse,Floors,L2,4\n",
                 "Steel,80\nReuse,0\n")
    data = json.loads(result.stdout)
    assert result.returncode == 0
    assert data["unmapped_materials"] == []
    assert data["totals"]["known_kg_co2e"] == "200.0"
    assert data["by_category_and_level"][0]["known_kg_co2e"] == "0"


@pytest.mark.parametrize("volumes,factors,diagnosis", [
    ("Steel,Walls,L1,-1\n", "Steel,100\n", "negative volume"),
    ("Steel,Walls,L1,NaN\n", "Steel,100\n", "non-finite volume"),
    ("Steel,Walls,L1,1\n", "Steel,100\nSteel,80\n", "duplicates"),
])
def test_rejects_invalid_inputs(tmp_path, volumes, factors, diagnosis):
    result = run(tmp_path, volumes, factors)
    assert result.returncode == 2
    assert diagnosis in result.stderr
    assert not result.stdout
