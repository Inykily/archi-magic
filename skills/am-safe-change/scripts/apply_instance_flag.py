# -*- coding: utf-8 -*-
"""EXECUTE step for the instance-flag recipe (issue #250). run_modify: dry run, then real.

inputs: {"preview_path": "C:/.../flag.preview.json"}   (forward slashes are fine)
    or  {"preview": {...preview dict...}}

In ONE transaction:
1. If the preview says create_parameter, create the flag parameter as a
   shared instance text parameter, bound to the preview's categories, in
   the Data group, with "values can vary by group instance" on.
   The Revit API cannot create a plain project parameter. So the script
   points Revit at a temporary shared parameter file in the temp folder,
   creates the definition there, and binds it. A `finally` block always
   restores the user's shared parameter file setting
   (Application.SharedParametersFilename) and deletes the temporary file,
   also when the run fails and also in a dry run.
2. Stale-state guard: each target still has the preview's "before" value,
   and no target is now borrowed by another user. If not, it stops with
   "Model changed since the preview" and changes nothing.
3. Writes each step's value. "" clears a flag of an older run.

result = {"rows": [[id, value_after], ...], "steps_applied": n,
          "created_parameter": bool, "shared_parameter_file": <the setting>,
          "shared_parameter_file_restored": bool, "escaped": bool}
A dry run returns the same result and Revit rolls everything back.
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import io
import json
import os
import sys
import tempfile
import uuid

from pyrevit.api import DB

ESCAPE = sys.platform == "cli"  # IronPython result encoder is ASCII-only (see read_sheets.py)
GROUP_NAME = "am-safe-change"


def txt(s):
    if s is None or not ESCAPE:
        return s
    out = []
    for c in s:
        if c == "\\":
            out.append("\\\\")
        elif ord(c) < 128:
            out.append(c)
        else:
            out.append("\\u%04x" % ord(c))
    return "".join(out)


try:
    import System

    def eid(n):
        return DB.ElementId(System.Int64(int(n)))
except ImportError:
    def eid(n):
        return DB.ElementId(int(n))


def load_preview():
    if inputs.get("preview"):  # noqa: F821
        return inputs["preview"]  # noqa: F821
    path = inputs.get("preview_path")  # noqa: F821
    if not path:
        raise ValueError("inputs needs preview_path or preview")
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.loads(f.read())


def parameter_bound(document, name):
    it = document.ParameterBindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        if it.Key is not None and it.Key.Name == name:
            return True
    return False


def create_parameter(document, name, category_names):
    """Create and bind a shared instance text parameter. Returns the restore state."""
    app = document.Application
    original = app.SharedParametersFilename
    temp_path = os.path.join(tempfile.gettempdir(),
                             "am-safe-change-params-%s.txt" % uuid.uuid4().hex[:12])
    state = {"original": original, "restored": False}
    try:
        with io.open(temp_path, "w", encoding="utf-8") as f:
            f.write(u"")
        app.SharedParametersFilename = temp_path
        definition_file = app.OpenSharedParameterFile()
        if definition_file is None:
            raise ValueError("Revit could not open the temporary shared parameter file.")
        group = definition_file.Groups.Create(GROUP_NAME)
        options = DB.ExternalDefinitionCreationOptions(name, DB.SpecTypeId.String.Text)
        options.Visible = True
        definition = group.Definitions.Create(options)
        categories = app.Create.NewCategorySet()
        for cat_name in category_names:
            category = DB.Category.GetCategory(document, getattr(DB.BuiltInCategory, cat_name))
            if category is None or not category.AllowsBoundParameters:
                raise ValueError("Category %s cannot take a project parameter." % cat_name)
            categories.Insert(category)
        binding = app.Create.NewInstanceBinding(categories)
        if not document.ParameterBindings.Insert(definition, binding, DB.GroupTypeId.Data):
            raise ValueError("Revit refused to bind the parameter %r." % name)
        shared = DB.SharedParameterElement.Lookup(document, definition.GUID)
        if shared is None:
            raise ValueError("The new shared parameter is not in the model.")
        shared.GetDefinition().SetAllowVaryBetweenGroups(document, True)
    finally:
        try:
            app.SharedParametersFilename = original if original is not None else ""
            state["restored"] = (app.SharedParametersFilename or "") == (original or "")
        except Exception:
            state["restored"] = False
        try:
            os.remove(temp_path)
        except OSError:
            pass
    return state


preview = load_preview()
if preview.get("kind") != "change-preview":
    raise ValueError("Not a change-preview file.")
if preview.get("blocked"):
    raise ValueError("The preview is BLOCKED. Resolve its blocking warnings first.")
steps = preview.get("steps") or []
if not steps:
    raise ValueError("The preview has no steps. Nothing to apply.")
params = preview.get("params") or {}
name = params.get("parameter")
if not name:
    raise ValueError("The preview names no parameter.")

created = False
restore = {"original": None, "restored": True}
t = DB.Transaction(doc, preview.get("title") or "Flag instances")  # noqa: F821
t.Start()
try:
    if not parameter_bound(doc, name):  # noqa: F821
        if not params.get("create_parameter"):
            raise ValueError("Model changed since the preview. Parameter %r is gone." % name)
        restore = create_parameter(doc, name, params.get("categories") or [])  # noqa: F821
        created = True
        doc.Regenerate()  # noqa: F821
    elif params.get("create_parameter"):
        raise ValueError("Model changed since the preview. Parameter %r now exists." % name)
    workshared = bool(doc.IsWorkshared)  # noqa: F821
    targets = []
    for st in steps:
        el = doc.GetElement(eid(st["id"]))  # noqa: F821
        if el is None:
            raise ValueError("Model changed since the preview. Element %s is gone." % st["id"])
        param = el.LookupParameter(name)
        if param is None or param.IsReadOnly:
            raise ValueError("Element %s has no writable parameter %r." % (st["id"], name))
        now = param.AsString() or ""
        if not created and now != (st.get("before") or ""):
            raise ValueError("Model changed since the preview. Element %s now reads %r."
                             % (st["id"], txt(now)))
        if workshared and str(DB.WorksharingUtils.GetCheckoutStatus(doc, el.Id)) == "OwnedByOtherUser":  # noqa: F821
            raise ValueError("Model changed since the preview. Element %s is now borrowed by "
                             "another user." % st["id"])
        targets.append((st, param))
    rows = []
    for st, param in targets:
        param.Set(st.get("after") or "")
    for st, param in targets:
        rows.append([int(st["id"]), txt(param.AsString() or "")])
    t.Commit()
except Exception:
    if t.HasStarted() and not t.HasEnded():
        t.RollBack()
    raise

result = {"rows": rows, "steps_applied": len(rows), "created_parameter": created,
          "shared_parameter_file": txt(restore.get("original")),
          "shared_parameter_file_restored": bool(restore.get("restored")),
          "escaped": ESCAPE}
