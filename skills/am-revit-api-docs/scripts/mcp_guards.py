# -*- coding: utf-8 -*-
"""Guards for pyRevit MCP tool arguments and post-sync element ID checks (issue #195).

1. capture_view silently ignores unknown arguments (such as 'view_id' or 'viewId')
   and captures the active view instead of the requested view.
   validate_capture_view() rejects unknown argument names, normalizes 'view_id'
   only when explicitly requested, and verifies that the returned capture result
   matches the requested view name or id.
2. After Synchronize with Central, Revit can assign new ElementIds to newly
   created elements when central already used those ids. A post-sync check by
   old ElementId alone falsely reports that committed elements "no longer exist"
   (undone or deleted). reconcile_post_sync_elements() re-finds elements by
   UniqueId, SharedParameterElement GUID, or a stable key (e.g. level + point).
"""

VALID_CAPTURE_VIEW_ARGS = ("view", "width", "height", "format", "revit", "timeout_s")
COMMON_ALIAS_MISTAKES = {
    "view_id": "view",
    "viewId": "view",
    "view_name": "view",
    "viewName": "view",
}


def validate_capture_view(call_args, result=None):
    """Validate capture_view arguments and optional tool result.

    Returns dict: {"ok": bool, "error": str, "requested_view": str,
                   "captured_view": str, "line": str}
    """
    call_args = dict(call_args or {})
    unknown = [k for k in sorted(call_args.keys()) if k not in VALID_CAPTURE_VIEW_ARGS]
    if unknown:
        hints = []
        for k in unknown:
            target = COMMON_ALIAS_MISTAKES.get(k)
            if target:
                hints.append("unknown argument '%s'; use '%s'" % (k, target))
            else:
                hints.append("unknown argument '%s' (valid: %s)"
                             % (k, ", ".join(VALID_CAPTURE_VIEW_ARGS)))
        return {
            "ok": False,
            "error": "; ".join(hints) + ". Passing an unknown argument causes capture_view to capture the active view silently.",
            "requested_view": "",
            "captured_view": "",
            "line": "",
        }

    req = str(call_args.get("view") or "").strip()
    if result is None:
        return {
            "ok": True,
            "error": "",
            "requested_view": req,
            "captured_view": "",
            "line": "Requested view: %s" % (req or "(active view)"),
        }

    cap_name = str(result.get("view_name") or result.get("view") or result.get("name") or "").strip()
    cap_id = str(result.get("view_id") or result.get("id") or "").strip()
    captured = cap_name or cap_id or "(unknown)"

    if req:
        matches = (req.lower() == cap_name.lower()) or (req == cap_id)
        if not matches and cap_name:
            return {
                "ok": False,
                "error": "capture_view returned view '%s' (id %s), which does not match requested view '%s'."
                         % (cap_name, cap_id or "?", req),
                "requested_view": req,
                "captured_view": captured,
                "line": "Captured view: %s (requested: %s) - MISMATCH" % (captured, req),
            }

    return {
        "ok": True,
        "error": "",
        "requested_view": req or "(active view)",
        "captured_view": captured,
        "line": "Captured view: %s (requested: %s)" % (captured, req or "(active view)"),
    }


def reconcile_post_sync_elements(committed, current):
    """Re-find committed elements after Sync with Central by UniqueId, GUID, or stable key.

    committed: [{"id": int, "unique_id": str, "guid": str, "stable_key": str, "name": str}]
    current:   [{"id": int, "unique_id": str, "guid": str, "stable_key": str, "name": str}]

    Returns dict with keys:
      - total: int
      - unchanged: [id]
      - id_changed: [{"from": old_id, "to": new_id, "matched_by": "unique_id"|"guid"|"stable_key"}]
      - missing: [old_id]
      - status: "ok" | "ids_renumbered_at_sync" | "missing_elements"
      - message: plain-English summary
    """
    by_id = {}
    by_uid = {}
    by_guid = {}
    by_key = {}

    for el in current or []:
        eid = el.get("id")
        if eid is not None:
            by_id[int(eid)] = el
        if el.get("unique_id"):
            by_uid[str(el["unique_id"])] = el
        if el.get("guid"):
            by_guid[str(el["guid"]).lower()] = el
        if el.get("stable_key"):
            by_key[str(el["stable_key"])] = el

    unchanged = []
    id_changed = []
    missing = []

    for rec in committed or []:
        old_id = int(rec["id"])
        uid = str(rec.get("unique_id") or "")
        guid = str(rec.get("guid") or "").lower()
        skey = str(rec.get("stable_key") or "")

        if old_id in by_id:
            cand = by_id[old_id]
            # Verify identity if unique_id or guid was recorded
            uid_ok = (not uid) or (str(cand.get("unique_id") or "") == uid)
            guid_ok = (not guid) or (str(cand.get("guid") or "").lower() == guid)
            if uid_ok and guid_ok:
                unchanged.append(old_id)
                continue

        # Fallback lookup by UniqueId, then GUID, then stable_key
        found = None
        matched_by = ""
        if uid and uid in by_uid:
            found = by_uid[uid]
            matched_by = "unique_id"
        elif guid and guid in by_guid:
            found = by_guid[guid]
            matched_by = "guid"
        elif skey and skey in by_key:
            found = by_key[skey]
            matched_by = "stable_key"

        if found is not None:
            new_id = int(found["id"])
            if new_id == old_id:
                unchanged.append(old_id)
            else:
                id_changed.append({
                    "from": old_id,
                    "to": new_id,
                    "matched_by": matched_by,
                })
        else:
            missing.append(old_id)

    total = len(committed or [])
    if missing:
        status = "missing_elements"
        msg = "%d of %d committed element(s) no longer exist (undone or deleted): %s." % (
            len(missing), total, ", ".join(str(x) for x in missing)
        )
    elif id_changed:
        status = "ids_renumbered_at_sync"
        pairs = ", ".join("%s -> %s (%s)" % (c["from"], c["to"], c["matched_by"]) for c in id_changed)
        msg = ("All %d committed element(s) exist in the model; %d element id(s) changed "
               "(likely Sync with Central): %s." % (total, len(id_changed), pairs))
    else:
        status = "ok"
        msg = "All %d committed element(s) verified with unchanged ids." % total

    return {
        "total": total,
        "unchanged": unchanged,
        "id_changed": id_changed,
        "missing": missing,
        "status": status,
        "message": msg,
    }
