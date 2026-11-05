# -*- coding: utf-8 -*-
"""Local time-saved log and ROI calculator for archi-magic (issue #184).

Tracks estimated manual time saved by agent runs, calculates monthly summaries,
and estimates return on investment (ROI). All data is kept local.
Compatible with Python 2.7 and 3.x (no f-strings, ASCII only).
"""

import datetime
import json
import os
import sys

DEFAULT_MANUAL_MINUTES = {
    "am-safe-change": 30,
    "am-param-qa": 45,
    "am-material-audit": 45,
    "am-shared-text-check": 40,
    "am-area-report": 60,
    "am-fill-standards": 30,
    "am-workset-audit": 25,
    "am-model-health": 30,
    "am-issue-board": 20,
    "am-corner-guard": 35,
    "default": 20,
}


def get_default_log_path():
    """Default local log file under LOCALAPPDATA or ~/.archi-magic."""
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        base = os.path.join(local_app, "archi-magic", "telemetry")
    else:
        home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or "."
        base = os.path.join(home, ".archi-magic", "telemetry")
    if not os.path.exists(base):
        try:
            os.makedirs(base)
        except Exception:
            pass
    return os.path.join(base, "time-saved.jsonl")


def estimate_minutes(skill, element_count=0):
    """Estimate manual minutes for a task based on skill and element count."""
    base = DEFAULT_MANUAL_MINUTES.get(skill, DEFAULT_MANUAL_MINUTES["default"])
    if element_count and element_count > 10:
        # Scale slightly for large element counts (e.g. +1 min per 20 elements over 10)
        extra = int((element_count - 10) / 20)
        return base + min(extra, 120)
    return base


def append_log(log_path, date_str, skill, element_count=0, estimated_minutes=None, model_name=None):
    """Append one record to the local JSONL log."""
    if estimated_minutes is None:
        estimated_minutes = estimate_minutes(skill, element_count)
    if not date_str:
        date_str = datetime.date.today().isoformat()

    record = {
        "date": str(date_str),
        "skill": str(skill),
        "element_count": int(element_count),
        "estimated_minutes": int(estimated_minutes),
        "model_name": str(model_name) if model_name else "local_model",
    }

    dir_name = os.path.dirname(log_path)
    if dir_name and not os.path.exists(dir_name):
        try:
            os.makedirs(dir_name)
        except Exception:
            pass

    line = json.dumps(record)
    with open(log_path, "a") as f:
        f.write(line + "\n")
    return record


def read_logs(log_path):
    """Read all entries from log file. Returns list of dicts."""
    if not os.path.exists(log_path):
        return []
    records = []
    with open(log_path, "r") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except Exception:
                continue
    return records


def monthly_summary(records):
    """Summarize records by YYYY-MM and skill."""
    summary = {}
    for r in records:
        d = r.get("date", "unknown")
        month = d[:7] if len(d) >= 7 else "unknown"
        skill = r.get("skill", "other")
        mins = r.get("estimated_minutes", 0)
        elems = r.get("element_count", 0)

        if month not in summary:
            summary[month] = {
                "month": month,
                "total_runs": 0,
                "total_elements": 0,
                "total_minutes": 0,
                "total_hours": 0.0,
                "by_skill": {},
            }
        m = summary[month]
        m["total_runs"] += 1
        m["total_elements"] += elems
        m["total_minutes"] += mins
        m["total_hours"] = round(m["total_minutes"] / 60.0, 1)

        if skill not in m["by_skill"]:
            m["by_skill"][skill] = {"runs": 0, "elements": 0, "minutes": 0}
        bs = m["by_skill"][skill]
        bs["runs"] += 1
        bs["elements"] += elems
        bs["minutes"] += mins

    # Return sorted by month
    return [summary[k] for k in sorted(summary.keys())]


def calculate_roi(records, hourly_rate=120.0):
    """Calculate financial ROI based on estimated hours and hourly rate."""
    months = monthly_summary(records)
    total_minutes = sum(m["total_minutes"] for m in months)
    total_hours = round(total_minutes / 60.0, 2)
    total_savings = round((total_minutes / 60.0) * hourly_rate, 2)

    return {
        "total_runs": sum(m["total_runs"] for m in months),
        "total_hours_saved": total_hours,
        "hourly_rate": hourly_rate,
        "total_cost_saved": total_savings,
        "monthly": months,
        "assumptions": (
            "Estimates based on standard manual task minutes: "
            "am-safe-change 30m, am-param-qa 45m, am-material-audit 45m, "
            "am-shared-text-check 40m, am-area-report 60m. "
            "Not measured time. Kept strictly local."
        ),
    }


def what_if(skill, monthly_frequency, hourly_rate=120.0, custom_minutes=None):
    """Calculate projected savings for a hypothetical usage rate."""
    mins = custom_minutes if custom_minutes is not None else DEFAULT_MANUAL_MINUTES.get(
        skill, DEFAULT_MANUAL_MINUTES["default"]
    )
    monthly_hours = (mins * monthly_frequency) / 60.0
    annual_hours = monthly_hours * 12.0
    monthly_cost = round(monthly_hours * hourly_rate, 2)
    annual_cost = round(annual_hours * hourly_rate, 2)

    return {
        "skill": skill,
        "monthly_frequency": monthly_frequency,
        "minutes_per_run": mins,
        "hourly_rate": hourly_rate,
        "monthly_hours_saved": round(monthly_hours, 1),
        "annual_hours_saved": round(annual_hours, 1),
        "monthly_cost_saved": monthly_cost,
        "annual_cost_saved": annual_cost,
    }


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: time_log.py <log|report|roi|what-if> [options]")
        return 0

    cmd = args[0]
    log_file = get_default_log_path()

    # Parse optional --log
    for i, a in enumerate(args):
        if a == "--log" and i + 1 < len(args):
            log_file = args[i + 1]

    if cmd == "log":
        skill = "am-safe-change"
        elements = 0
        minutes = None
        model = "local"
        date_str = None
        i = 1
        while i < len(args):
            if args[i] == "--skill" and i + 1 < len(args):
                skill = args[i + 1]
                i += 2
            elif args[i] == "--elements" and i + 1 < len(args):
                elements = int(args[i + 1])
                i += 2
            elif args[i] == "--minutes" and i + 1 < len(args):
                minutes = int(args[i + 1])
                i += 2
            elif args[i] == "--model" and i + 1 < len(args):
                model = args[i + 1]
                i += 2
            elif args[i] == "--date" and i + 1 < len(args):
                date_str = args[i + 1]
                i += 2
            else:
                i += 1
        rec = append_log(log_file, date_str, skill, elements, minutes, model)
        print("Logged: %s (%s mins)" % (rec["skill"], rec["estimated_minutes"]))
        return 0

    elif cmd == "report":
        records = read_logs(log_file)
        months = monthly_summary(records)
        if "--json" in args:
            print(json.dumps(months, indent=2))
        else:
            print("=== archi-magic Time Saved Report ===")
            print("Total logged runs: %d" % len(records))
            for m in months:
                print("\nMonth: %s | Runs: %d | Elements: %d | Saved: %.1f hrs" % (
                    m["month"], m["total_runs"], m["total_elements"], m["total_hours"]
                ))
                for s, data in sorted(m["by_skill"].items()):
                    print("  - %-20s: %2d runs, %4d elements, %3d mins" % (
                        s, data["runs"], data["elements"], data["minutes"]
                    ))
        return 0

    elif cmd == "roi":
        rate = 120.0
        for i, a in enumerate(args):
            if a == "--rate" and i + 1 < len(args):
                rate = float(args[i + 1])
        records = read_logs(log_file)
        roi = calculate_roi(records, hourly_rate=rate)
        if "--json" in args:
            print(json.dumps(roi, indent=2))
        else:
            print("=== archi-magic ROI Report ===")
            print("Total runs logged: %d" % roi["total_runs"])
            print("Total estimated hours saved: %.1f hrs" % roi["total_hours_saved"])
            print("Hourly rate: $%.2f/hr" % roi["hourly_rate"])
            print("Total estimated cost saved: $%.2f" % roi["total_cost_saved"])
            print("\nAssumptions: %s" % roi["assumptions"])
        return 0

    elif cmd == "what-if":
        skill = "am-safe-change"
        freq = 4
        rate = 120.0
        custom_mins = None
        i = 1
        while i < len(args):
            if args[i] == "--skill" and i + 1 < len(args):
                skill = args[i + 1]
                i += 2
            elif args[i] == "--freq" and i + 1 < len(args):
                freq = int(args[i + 1])
                i += 2
            elif args[i] == "--rate" and i + 1 < len(args):
                rate = float(args[i + 1])
                i += 2
            elif args[i] == "--minutes" and i + 1 < len(args):
                custom_mins = int(args[i + 1])
                i += 2
            else:
                i += 1
        res = what_if(skill, freq, rate, custom_mins)
        if "--json" in args:
            print(json.dumps(res, indent=2))
        else:
            print("=== What-If ROI Projection: %s ===" % res["skill"])
            print("Usage: %d runs/month at %d mins manual time per run" % (
                res["monthly_frequency"], res["minutes_per_run"]
            ))
            print("Monthly hours saved: %.1f hrs ($%.2f)" % (
                res["monthly_hours_saved"], res["monthly_cost_saved"]
            ))
            print("Annual hours saved:  %.1f hrs ($%.2f)" % (
                res["annual_hours_saved"], res["annual_cost_saved"]
            ))
        return 0

    else:
        print("Unknown command: %s" % cmd)
        return 1


if __name__ == "__main__":
    sys.exit(main())
