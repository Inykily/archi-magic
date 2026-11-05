# -*- coding: utf-8 -*-
"""Check packs evaluator and runner (issue #180).

Loads team-authored rule packs (JSON), evaluates elements against rules,
groups findings by severity (error, warning, info), and formats for
am-issue-board hand-off.
Compatible with Python 2.7 and 3.x (no f-strings, ASCII only).
"""

import json
import os
import sys

PACKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "packs")


def load_pack(pack_path_or_name):
    """Load a rule pack from path or built-in pack name."""
    path = pack_path_or_name
    if not os.path.exists(path):
        candidate = os.path.join(PACKS_DIR, pack_path_or_name)
        if not candidate.endswith(".json"):
            candidate += ".json"
        if os.path.exists(candidate):
            path = candidate
        else:
            raise IOError("Pack file not found: %s" % pack_path_or_name)

    with open(path, "r") as f:
        return json.load(f)


def list_builtin_packs():
    """List available built-in packs."""
    packs = []
    if os.path.exists(PACKS_DIR):
        for fname in sorted(os.listdir(PACKS_DIR)):
            if fname.endswith(".json"):
                p = os.path.join(PACKS_DIR, fname)
                try:
                    with open(p, "r") as f:
                        data = json.load(f)
                        packs.append({
                            "file": fname,
                            "name": data.get("name", fname),
                            "version": data.get("version", "1.0"),
                            "rules_count": len(data.get("rules", [])),
                        })
                except Exception:
                    continue
    return packs


def evaluate_condition(element_value, condition, target_value=None):
    """Evaluate whether an element value satisfies a condition.

    Returns True if valid (PASS), False if broken (FAIL).
    """
    str_val = str(element_value).strip() if element_value is not None else ""

    if condition == "not_empty":
        return bool(str_val)
    elif condition == "empty":
        return not bool(str_val)
    elif condition == "equals":
        return str_val == str(target_value)
    elif condition == "not_equals":
        return str_val != str(target_value)
    elif condition == "contains":
        return str(target_value) in str_val
    elif condition == "not_contains":
        return str(target_value) not in str_val
    elif condition == "greater_than":
        try:
            return float(str_val) > float(target_value)
        except Exception:
            return False
    elif condition == "less_than":
        try:
            return float(str_val) < float(target_value)
        except Exception:
            return False
    else:
        # Unknown condition passes by default
        return True


def evaluate_rule(rule, element):
    """Evaluate a single rule against an element dict.

    Returns finding dict if failed, None if passed.
    """
    category = rule.get("category")
    elem_cat = element.get("category")
    if category and elem_cat and category != elem_cat:
        return None

    param_name = rule.get("parameter")
    params = element.get("parameters", {})
    val = params.get(param_name) if param_name else None

    cond = rule.get("condition", "not_empty")
    target = rule.get("value")

    passed = evaluate_condition(val, cond, target)
    if not passed:
        return {
            "rule_id": rule.get("id", "RULE"),
            "element_id": element.get("id"),
            "element_name": element.get("name", "Unknown"),
            "category": elem_cat or category or "Unknown",
            "parameter": param_name,
            "actual_value": val,
            "severity": rule.get("severity", "warning"),
            "message": rule.get("message", "Rule condition failed"),
            "fix_hint": rule.get("fix_hint", "Review parameter value"),
        }
    return None


def evaluate_pack(pack_data, elements):
    """Evaluate all rules in a pack against a list of element dicts.

    Returns {
        "pack_name": ...,
        "elements_scanned": n,
        "summary": {"error": count, "warning": count, "info": count, "total": count},
        "findings": [...]
    }
    """
    rules = pack_data.get("rules", [])
    findings = []
    counts = {"error": 0, "warning": 0, "info": 0}

    for el in elements:
        for r in rules:
            f = evaluate_rule(r, el)
            if f:
                sev = f.get("severity", "warning").lower()
                if sev in counts:
                    counts[sev] += 1
                else:
                    counts["warning"] += 1
                findings.append(f)

    return {
        "pack_name": pack_data.get("name", "Custom Pack"),
        "pack_version": pack_data.get("version", "1.0"),
        "elements_scanned": len(elements),
        "rules_evaluated": len(rules),
        "summary": {
            "error": counts["error"],
            "warning": counts["warning"],
            "info": counts["info"],
            "total": len(findings),
        },
        "findings": findings,
    }


def to_issue_board_findings(evaluation_result):
    """Convert check pack findings into am-issue-board finding list format."""
    board_findings = []
    for f in evaluation_result.get("findings", []):
        board_findings.append({
            "code": f["rule_id"],
            "severity": f["severity"],
            "element_id": f["element_id"],
            "element_name": f["element_name"],
            "category": f["category"],
            "title": f["message"],
            "suggestion": f["fix_hint"],
        })
    return board_findings


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: check_packs.py <list-packs|evaluate> [options]")
        return 0

    cmd = args[0]

    if cmd == "list-packs":
        packs = list_builtin_packs()
        print("Available Built-in Check Packs (%d):" % len(packs))
        for p in packs:
            print("  - %-25s : %s (v%s, %d rules)" % (
                p["file"], p["name"], p["version"], p["rules_count"]
            ))
        return 0

    elif cmd == "evaluate":
        pack_name = None
        data_file = None
        out_file = None
        i = 1
        while i < len(args):
            if args[i] == "--pack" and i + 1 < len(args):
                pack_name = args[i + 1]
                i += 2
            elif args[i] == "--data" and i + 1 < len(args):
                data_file = args[i + 1]
                i += 2
            elif args[i] == "--out" and i + 1 < len(args):
                out_file = args[i + 1]
                i += 2
            else:
                i += 1

        if not pack_name or not data_file:
            print("Error: --pack and --data are required")
            return 1

        pack = load_pack(pack_name)
        with open(data_file, "r") as f:
            elements = json.load(f)
            if isinstance(elements, dict) and "elements" in elements:
                elements = elements["elements"]

        res = evaluate_pack(pack, elements)
        out_json = json.dumps(res, indent=2)

        if out_file:
            with open(out_file, "w") as f:
                f.write(out_json)
            print("Wrote %d findings to %s" % (res["summary"]["total"], out_file))
        else:
            print(out_json)
        return 0

    else:
        print("Unknown command: %s" % cmd)
        return 1


if __name__ == "__main__":
    sys.exit(main())
