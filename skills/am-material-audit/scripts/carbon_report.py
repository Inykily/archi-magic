"""Estimate embodied carbon from exported material volumes and user factors."""

import argparse
import csv
from decimal import Decimal, DecimalException
import json
import sys


def table(path, required):
    with open(path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or not set(required).issubset(fields):
            raise ValueError("expected unique headers including " + ", ".join(required))
        for row in reader:
            if None in row or any(row[field] is None or not row[field].strip() for field in required):
                raise ValueError(f"line {reader.line_num} has a missing or extra value")
            yield reader.line_num, {field: row[field].strip() for field in required}


def number(text, line, field):
    try:
        value = Decimal(text)
    except DecimalException as exc:
        raise ValueError(f"line {line} has an invalid {field}") from exc
    if not value.is_finite():
        raise ValueError(f"line {line} has a non-finite {field}")
    return value


def add(totals, volume, factor):
    mapped, unmapped, carbon = totals
    if factor is None:
        totals[1] = unmapped + volume
    else:
        totals[0] = mapped + volume
        totals[2] = (Decimal(0) if carbon is None else carbon) + volume * factor


def totals_row(totals):
    mapped, unmapped, carbon = totals
    return {
        "mapped_volume_m3": str(mapped),
        "unmapped_volume_m3": str(unmapped),
        "known_kg_co2e": None if carbon is None else str(carbon),
    }


def report(volumes_path, factors_path):
    factors = {}
    for line, row in table(factors_path, ("material", "kg_co2e_per_m3")):
        key = row["material"]
        if key in factors:
            raise ValueError(f"line {line} duplicates a material factor")
        factors[key] = number(row["kg_co2e_per_m3"], line, "carbon factor")

    by_category_level = {}
    unmapped = {}
    totals = [Decimal(0), Decimal(0), None]
    zero = Decimal(0)
    for line, row in table(volumes_path, ("material", "category", "level", "volume_m3")):
        key = row["material"]
        volume = number(row["volume_m3"], line, "volume")
        if volume < 0:
            raise ValueError(f"line {line} has a negative volume")
        group = row["category"], row["level"]
        factor = factors.get(key)
        add(by_category_level.setdefault(group, [zero, zero, None]), volume, factor)
        add(totals, volume, factor)
        if factor is None:
            missing = group + (key,)
            unmapped[missing] = unmapped.get(missing, zero) + volume
    if not by_category_level:
        raise ValueError("the volume table has no material rows")
    return {
        "status": "incomplete" if unmapped else "complete",
        "totals": totals_row(totals),
        "by_category_and_level": [
            dict(totals_row(values), category=category, level=level)
            for (category, level), values in sorted(by_category_level.items())
        ],
        "unmapped_materials": [
            {"category": category, "level": level, "material": material, "volume_m3": str(volume)}
            for (category, level, material), volume in sorted(unmapped.items())
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volumes", required=True)
    parser.add_argument("--factors", required=True)
    args = parser.parse_args(argv)
    try:
        result = report(args.volumes, args.factors)
    except (OSError, UnicodeError, csv.Error, DecimalException, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "incomplete" else 0


if __name__ == "__main__":
    raise SystemExit(main())
