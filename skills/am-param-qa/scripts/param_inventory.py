# -*- coding: utf-8 -*-
"""am-param-qa inventory mode: read-only parameter inventory for the pyRevit Agent Runtime.

Submit with the pyrevit MCP tool run_query, passing `inputs`
(or `pyrevit agent run <this file> --mode=query --inputs=<json>`).
IronPython 2.7 compatible: no f-strings, no type hints, no print kwargs.
The script changes nothing and writes no files. The agent saves the
`csv` string from the result to a notes folder; the script itself writes nothing.

inputs (all optional):
  {"categories": ["OST_Doors", "OST_Windows"],  # limit fill rates to these categories
   "name_rule": {"forbid_chars": " -", "case": "Pascal"},
   "skip_fill_rates": false,   # true skips the element scan (fast inventory)
   "scan_families": true,      # false skips the family scan (no unbound rows, no family usage)
   "max_rows": 1000,           # inventory rows returned
   "max_fill_elements": 0}     # 0 = no cap; else cap elements scanned per category

One row per parameter: name, shared or project, GUID, data type, group,
instance or type, bound categories, fill rate. Flags: same name under two
GUIDs, unbound shared parameters (with the family that brings each one),
group "Other", names that break a rule the user gives, no shared parameter
file set. Usage counts: schedule fields, schedule filters, view filters,
families. NOT checked, and stated in the result: tags, labels, nested
families. Usage counts match by GUID when Revit resolves the parameter,
else by parameter name; a name-matched count on a duplicate name is
flagged "usage-ambiguous".
"""
import sys

try:
    from pyrevit.api import DB
except Exception:
    DB = None

try:
    DOC = doc  # noqa: F821  (injected by the agent runtime)
except NameError:
    DOC = None

try:
    APP = app  # noqa: F821  (injected by the agent runtime)
except NameError:
    APP = None

try:
    INPUTS = inputs  # noqa: F821  (injected by the agent runtime)
except NameError:
    INPUTS = None
if not isinstance(INPUTS, dict):
    INPUTS = {}

CATEGORIES = INPUTS.get("categories") or None
NAME_RULE = INPUTS.get("name_rule") or None
SKIP_FILL_RATES = bool(INPUTS.get("skip_fill_rates"))
SCAN_FAMILIES = INPUTS.get("scan_families", True)
if SCAN_FAMILIES is None:
    SCAN_FAMILIES = True
SCAN_FAMILIES = bool(SCAN_FAMILIES)
MAX_ROWS = int(INPUTS.get("max_rows", 1000))
MAX_FILL_ELEMENTS = int(INPUTS.get("max_fill_elements", 0))
MAX_FAMILIES_LISTED = 50

IRONPYTHON = sys.platform == "cli"


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def jsonable(value):
    """Keep non-ASCII names intact through the runtime's json.dumps on IronPython 2.7.
    See skills/am-param-qa/scripts/param_qa.py for the reason."""
    if isinstance(value, dict):
        return dict((jsonable(k), jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if IRONPYTHON and isinstance(value, basestring):  # noqa: F821
        if any(ord(c) > 127 for c in value):
            return value.encode("utf-8").decode("latin-1")
    return value


def id_int(element_id):
    """ElementId -> int. Revit 2024+ has .Value; 2023 and older only .IntegerValue."""
    if hasattr(element_id, "Value"):
        return int(element_id.Value)
    return int(element_id.IntegerValue)


def group_label(definition):
    """Display name for the 'Group parameter under' value, else the enum name."""
    group = safe(lambda: definition.ParameterGroup)
    if group is None:
        return ""
    if DB is not None:
        label = safe(lambda: DB.LabelUtils.GetLabelFor(group))
        if label:
            return label
    return str(group)


def group_is_other(definition):
    if DB is None:
        return False
    group = safe(lambda: definition.ParameterGroup)
    other = safe(lambda: DB.BuiltInParameterGroup.PG_OTHER)
    return group is not None and other is not None and group == other


def name_rule_violations(name, rule):
    """Names that break a rule the user gives. Rule keys: forbid_chars, case.

    case: "lower", "upper", "Pascal", "camel", or "any" (default "any").
    Returns a list of violation strings (empty when the name passes)."""
    if not rule or not isinstance(rule, dict):
        return []
    out = []
    for ch in (rule.get("forbid_chars") or ""):
        if ch and ch in name:
            shown = "space" if ch == " " else repr(ch)
            out.append("contains %s" % shown)
    case = (rule.get("case") or "any").lower()
    cased = [c for c in name if c.isalpha()]
    if case == "lower" and any(c.isupper() for c in cased):
        out.append("not lower case")
    elif case == "upper" and any(c.islower() for c in cased):
        out.append("not upper case")
    elif case == "pascal":
        if not name or not name[0].isalpha() or not name[0].isupper():
            out.append("not PascalCase")
        elif "_" in name or " " in name:
            out.append("not PascalCase")
    elif case == "camel":
        if not name or not name[0].isalpha() or not name[0].islower():
            out.append("not camelCase")
        elif "_" in name or " " in name:
            out.append("not camelCase")
    return out


def is_filled(p):
    """Mirror of param_qa.is_empty, inverted. A numeric 0 that the user entered counts."""
    if p is None or not safe(lambda: p.HasValue, False):
        return False
    if DB is not None and safe(lambda: p.StorageType) == DB.StorageType.String:
        v = safe(lambda: p.AsString())
        return v is not None and bool(v.strip())
    if DB is not None and safe(lambda: p.StorageType) == DB.StorageType.ElementId:
        return id_int(safe(lambda: p.AsElementId())) >= 0
    return True


def csv_escape(value):
    text = "" if value is None else str(value)
    if any(c in text for c in (",", '"', "\n", "\r")):
        return '"' + text.replace('"', '""') + '"'
    return text


def inventory_csv(rows):
    """CSV text for the inventory rows. The agent saves this to a notes folder."""
    header = ["name", "kind", "guid", "data_type", "group", "binding", "categories",
              "fill_rate", "filled", "total", "schedule_fields", "schedule_filters",
              "view_filters", "families", "flags"]
    lines = [",".join(header)]
    for r in rows:
        vals = [r["name"], r["kind"], r["guid"], r["data_type"], r["group"],
                r["binding"], "; ".join(r["categories"]),
                "" if r["fill_rate"] is None else r["fill_rate"],
                "" if r["filled"] is None else r["filled"],
                "" if r["total"] is None else r["total"],
                r["usage"]["schedule_fields"], r["usage"]["schedule_filters"],
                r["usage"]["view_filters"],
                "; ".join(r["families"]),
                "; ".join(r["flags"])]
        lines.append(",".join(csv_escape(v) for v in vals))
    return "\n".join(lines)


def join_usage(guid, name, usage_by_guid, usage_by_name):
    """Join a row to its usage counts. GUID match wins; else name match.

    Returns (usage_dict, match) where match is "guid", "name", or "none"."""
    if guid and guid in usage_by_guid:
        return dict(usage_by_guid[guid]), "guid"
    if name in usage_by_name:
        return dict(usage_by_name[name]), "name"
    return {"schedule_fields": 0, "schedule_filters": 0, "view_filters": 0}, "none"


def compute_flags(row, name_keys, rule):
    """Flags for one inventory row. name_keys maps a name to its set of keys
    (GUIDs, plus "project" for project parameters)."""
    flags = []
    if row["binding"] == "unbound":
        flags.append("unbound")
    if row["group_other"]:
        flags.append("group-other")
    keys = name_keys.get(row["name"], set())
    if len(keys) > 1:
        flags.append("duplicate-name")
    if row["usage_match"] == "name" and len(keys) > 1:
        flags.append("usage-ambiguous")
    for v in name_rule_violations(row["name"], rule):
        flags.append("name-rule: " + v)
    return flags


def resolve_param_id(pid):
    """Resolve a schedule/filter parameter id to (guid, name).

    Shared parameters resolve to their GUID through the shared parameter
    element. Anything else resolves by element name when Revit has an
    element for the id, else (None, None). Built-in ids are negative."""
    if pid is None:
        return (None, None)
    try:
        n = id_int(pid)
    except Exception:
        return (None, None)
    if n < 0:
        return (None, None)
    el = safe(lambda: DOC.GetElement(pid))
    if el is None:
        return (None, None)
    guid = safe(lambda: str(el.GuidValue))
    if guid:
        return (guid, safe(lambda: el.Name))
    return (None, safe(lambda: el.Name))


def count_usage_into(usage_by_guid, usage_by_name, guid, name, field):
    if guid:
        bucket = usage_by_guid.setdefault(guid, {"schedule_fields": 0,
                                                 "schedule_filters": 0,
                                                 "view_filters": 0})
        bucket[field] += 1
    elif name:
        bucket = usage_by_name.setdefault(name, {"schedule_fields": 0,
                                                 "schedule_filters": 0,
                                                 "view_filters": 0})
        bucket[field] += 1


def schedule_usage():
    """Count schedule field and filter uses. Returns (by_guid, by_name, unresolved_filters)."""
    by_guid, by_name = {}, {}
    unresolved = 0
    if DB is None:
        return by_guid, by_name, unresolved
    col = DB.FilteredElementCollector(DOC).OfClass(DB.ViewSchedule)
    for vs in col:
        if safe(lambda: vs.IsTemplate, False):
            continue
        if safe(lambda: vs.IsTitleblockRevisionSchedule, False):
            continue
        d = safe(lambda: vs.Definition)
        if d is None:
            continue
        for i in range(safe(lambda: d.GetFieldCount(), 0)):
            f = safe(lambda: d.GetField(i))
            if f is None:
                continue
            pid = safe(lambda: f.ParameterId)
            guid, name = resolve_param_id(pid)
            if guid is None and name is None:
                name = safe(lambda: f.ColumnHeading)
            count_usage_into(by_guid, by_name, guid, name, "schedule_fields")
        for i in range(safe(lambda: d.GetFilterCount(), 0)):
            sf = safe(lambda: d.GetFilter(i))
            if sf is None:
                continue
            field = None
            fid = safe(lambda: sf.FieldId)
            if fid is not None:
                field = safe(lambda: d.GetField(fid))
            if field is None:
                unresolved += 1
                continue
            pid = safe(lambda: field.ParameterId)
            guid, name = resolve_param_id(pid)
            if guid is None and name is None:
                name = safe(lambda: field.ColumnHeading)
            count_usage_into(by_guid, by_name, guid, name, "schedule_filters")
    return by_guid, by_name, unresolved


def filter_rules(pfe):
    """Filter rules for one view filter element, across API shapes."""
    rules = safe(lambda: pfe.GetRules())
    if rules:
        return list(rules)
    ef = safe(lambda: pfe.GetElementFilter())
    if ef is not None and DB is not None:
        try:
            if isinstance(ef, DB.ElementParameterFilter):
                rules = safe(lambda: ef.GetRules())
                if rules:
                    return list(rules)
        except Exception:
            pass
    return []


def view_filter_usage():
    """Count view filter rule uses. Returns (by_guid, by_name, unresolved_rules)."""
    by_guid, by_name = {}, {}
    unresolved = 0
    if DB is None:
        return by_guid, by_name, unresolved
    col = DB.FilteredElementCollector(DOC).OfClass(DB.ParameterFilterElement)
    for pfe in col:
        for rule in filter_rules(pfe):
            pid = safe(lambda: rule.GetRuleParameter())
            guid, name = resolve_param_id(pid)
            if guid is None and name is None:
                unresolved += 1
                continue
            count_usage_into(by_guid, by_name, guid, name, "view_filters")
    return by_guid, by_name, unresolved


def family_scan():
    """Shared parameters carried by loaded families.

    Returns (guid -> info) where info has name, data_type, group,
    group_other, and the set of family names that carry it."""
    found = {}
    if DB is None:
        return found
    col = DB.FilteredElementCollector(DOC).OfClass(DB.FamilySymbol)
    for symbol in col:
        fam_name = safe(lambda: symbol.Family.Name, "")
        params = safe(lambda: list(symbol.Parameters), [])
        for p in params:
            if not safe(lambda: p.IsShared, False):
                continue
            definition = safe(lambda: p.Definition)
            if definition is None:
                continue
            guid = safe(lambda: str(definition.GUID))
            if not guid:
                continue
            info = found.get(guid)
            if info is None:
                info = {"name": safe(lambda: definition.Name, ""),
                        "data_type": str(safe(lambda: definition.ParameterType, "")),
                        "group": group_label(definition),
                        "group_other": group_is_other(definition),
                        "families": set()}
                found[guid] = info
            if fam_name:
                info["families"].add(fam_name)
    return found


def summarize(rows):
    bound = [r for r in rows if r["binding"] != "unbound"]
    unbound = [r for r in rows if r["binding"] == "unbound"]
    return {
        "parameters": len(rows),
        "bound": len(bound),
        "unbound_shared": len(unbound),
        "duplicate_names": len(set(r["name"] for r in rows if "duplicate-name" in r["flags"])),
        "group_other": len([r for r in rows if "group-other" in r["flags"]]),
        "name_rule_violations": len([r for r in rows
                                     if any(f.startswith("name-rule:") for f in r["flags"])]),
    }


if DOC is None or safe(lambda: DOC.IsFamilyDocument, False):
    result = {"error": "no_project_document",
              "message": "Open a Revit project (.rvt), not a family, then run again."}
else:
    shared_file = safe(lambda: APP.SharedParametersFilename) if APP is not None else None
    shared_file_set = bool(shared_file)

    # 1. Project parameter bindings: one row seed per binding.
    bound = {}  # (name, guid) -> row seed; project params key on ("project", name)
    unknown_categories = []
    wanted = None
    if CATEGORIES:
        wanted = set()
        for cat_key in CATEGORIES:
            bic = safe(lambda: getattr(DB.BuiltInCategory, cat_key, None))
            if bic is None:
                unknown_categories.append(cat_key)
            else:
                wanted.add(cat_key)
    bindings = safe(lambda: DOC.ParameterBindings)
    if bindings is not None:
        it = safe(lambda: bindings.ForwardIterator())
        while it is not None and safe(lambda: it.MoveNext(), False):
            definition = safe(lambda: it.Key)
            binding = safe(lambda: it.Current)
            if definition is None or binding is None:
                continue
            name = safe(lambda: definition.Name, "")
            guid = safe(lambda: str(definition.GUID))
            if not guid or guid == "00000000-0000-0000-0000-000000000000":
                guid = ""
            kind = "shared" if guid else "project"
            if DB is not None and safe(lambda: isinstance(binding, DB.InstanceBinding), False):
                binding_kind = "instance"
            elif DB is not None and safe(lambda: isinstance(binding, DB.TypeBinding), False):
                binding_kind = "type"
            else:
                binding_kind = "unknown"
            cats = []
            cat_ids = []
            for cat in safe(lambda: list(binding.Categories), []):
                cats.append(safe(lambda: cat.Name, ""))
                cat_ids.append(cat)
            bound[(name, guid)] = {
                "name": name, "kind": kind, "guid": guid,
                "data_type": str(safe(lambda: definition.ParameterType, "")),
                "group": group_label(definition),
                "group_other": group_is_other(definition),
                "binding": binding_kind, "categories": cats,
                "definition": definition, "cat_ids": cat_ids,
            }

    # 2. Family scan: unbound shared parameters, and family usage.
    fam_info = family_scan() if SCAN_FAMILIES else {}
    bound_guids = set(g for (_, g) in bound.keys() if g)
    unbound_rows = []
    for guid in sorted(fam_info.keys()):
        if guid in bound_guids:
            continue
        info = fam_info[guid]
        unbound_rows.append({
            "name": info["name"], "kind": "shared", "guid": guid,
            "data_type": info["data_type"], "group": info["group"],
            "group_other": info["group_other"], "binding": "unbound",
            "categories": [], "definition": None, "cat_ids": [],
            "scan_families": sorted(info["families"]),
        })

    # 3. Usage counts.
    sched_guid, sched_name, unresolved_sched = schedule_usage()
    filt_guid, filt_name, unresolved_filt = view_filter_usage()
    usage_by_guid = {}
    for guid in set(list(sched_guid.keys()) + list(filt_guid.keys())):
        merged = {"schedule_fields": 0, "schedule_filters": 0, "view_filters": 0}
        for src in (sched_guid, filt_guid):
            for k, v in src.get(guid, {}).items():
                merged[k] += v
        usage_by_guid[guid] = merged
    usage_by_name = {}
    for name in set(list(sched_name.keys()) + list(filt_name.keys())):
        merged = {"schedule_fields": 0, "schedule_filters": 0, "view_filters": 0}
        for src in (sched_name, filt_name):
            for k, v in src.get(name, {}).items():
                merged[k] += v
        usage_by_name[name] = merged

    # 4. Fill rates over bound categories (instance first, then type).
    fill = {}
    if not SKIP_FILL_RATES:
        for seed in bound.values():
            definition = seed["definition"]
            filled = 0
            total = 0
            computed = False
            for cat in seed["cat_ids"]:
                bic_name = safe(lambda: str(cat.BuiltInCategory))
                if wanted is not None and bic_name not in wanted:
                    continue
                computed = True
                col = (DB.FilteredElementCollector(DOC)
                       .OfCategoryId(cat.Id).WhereElementIsNotElementType())
                count = 0
                for el in col:
                    if MAX_FILL_ELEMENTS and count >= MAX_FILL_ELEMENTS:
                        break
                    count += 1
                    total += 1
                    p = safe(lambda: el.get_Parameter(definition))
                    if is_filled(p):
                        filled += 1
                        continue
                    el_type = safe(lambda: DOC.GetElement(el.GetTypeId()))
                    tp = safe(lambda: el_type.get_Parameter(definition)) \
                        if el_type is not None else None
                    if is_filled(tp):
                        filled += 1
            fill[(seed["name"], seed["guid"])] = (filled, total, computed)

    # 5. Assemble rows.
    name_keys = {}
    seeds = list(bound.values()) + unbound_rows
    for seed in seeds:
        key = seed["guid"] if seed["guid"] else "project"
        name_keys.setdefault(seed["name"], set()).add(key)
    rows = []
    for seed in sorted(seeds, key=lambda s: s["name"].lower()):
        usage, match = join_usage(seed["guid"], seed["name"],
                                  usage_by_guid, usage_by_name)
        fams = []
        if seed["guid"] and seed["guid"] in fam_info:
            fams = sorted(fam_info[seed["guid"]]["families"])
        elif seed.get("scan_families") is not None:
            fams = seed["scan_families"]
        row = {
            "name": seed["name"], "kind": seed["kind"], "guid": seed["guid"],
            "data_type": seed["data_type"], "group": seed["group"],
            "group_other": seed["group_other"], "binding": seed["binding"],
            "categories": seed["categories"],
            "fill_rate": None, "filled": None, "total": None,
            "usage": usage, "usage_match": match,
            "families": fams[:MAX_FAMILIES_LISTED],
            "families_truncated": len(fams) > MAX_FAMILIES_LISTED,
            "flags": [],
        }
        if seed["binding"] != "unbound" and not SKIP_FILL_RATES:
            filled, total, computed = fill.get((seed["name"], seed["guid"]),
                                               (0, 0, False))
            if computed:
                row["filled"] = filled
                row["total"] = total
                row["fill_rate"] = (round(100.0 * filled / total, 1)
                                    if total else None)
        row["flags"] = compute_flags(row, name_keys, NAME_RULE)
        rows.append(row)
    rows_truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]

    result = jsonable({
        "model": safe(lambda: DOC.Title, ""),
        "shared_param_file_set": shared_file_set,
        "shared_param_file": shared_file or "",
        "unknown_categories": unknown_categories,
        "summary": summarize(rows),
        "not_checked": ["tags", "labels", "nested families"],
        "usage_unresolved": {
            "schedule_filters": unresolved_sched,
            "view_filter_rules": unresolved_filt,
        },
        "rows": rows,
        "rows_truncated": rows_truncated,
        "csv": inventory_csv(rows),
    })
    print("am-param-qa inventory: %d parameters, %d bound, %d unbound shared"
          % (result["summary"]["parameters"], result["summary"]["bound"],
             result["summary"]["unbound_shared"]))
