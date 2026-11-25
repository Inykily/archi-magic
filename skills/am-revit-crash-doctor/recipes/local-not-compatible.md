# Recipe: rescue work when the local file is "not compatible with central"

Example message from Revit: "Your local file is not compatible with the central model."

Use this recipe when Synchronize with Central and Reload Latest both fail at once with that message. It comes from one field session on a cloud workshared model (Revit 2026, pyRevit 7.0, issue #281). It worked once. Read "Not verified" at the end before you start.

Words in this recipe:

- **Local file (local):** the user's own copy of a workshared model.
- **Central:** the shared model on the server or in Autodesk Docs.
- **Rescue copy:** a desktop copy of the broken local, made with Save As.
- **New local:** a fresh local that Revit makes from central.
- **UniqueId:** the element id that stays the same in every copy of one model. The plain element id can change.

## Rules

- Do not copy anything into central until step 5 says so. Most "missing" work is already in central.
- Every step in Revit is read-only until step 5. Step 5 uses `am-safe-change`.
- Never delete a local file or a cache folder. Rename it, so the user can go back.
- The user closes and opens models. Never close or open the model for the user.
- Show only file names and counts in the chat. Do not show full paths.

## Step 1: read the journal first

Run the crash check in `am-revit-crash-doctor` (Steps 1 and 2 of `SKILL.md`). Find the last sync and how it ended.

- Look for a crash (`CRASH` or `ABRUPT_END`), a graphics driver reset (`DXGI_ERROR_DEVICE_REMOVED`), and the "not compatible" dialogs.
- If a sync ended "ok" before the crash, the work is probably already in central. Say so to the user. The crash then hit while Revit saved the local after the sync.
- If the last sync did not end "ok", some work is probably not in central. Step 5 then copies it.

## Step 2: map the borrowed elements (read only)

Elements that the user borrowed are the user's recent work. Find them with a native filter. It ran in about 3 seconds on a large model.

```python
# run_query, read only. IronPython 2.7 and CPython 3. No f-strings.
# The agent runtime gives `doc` (the active document).
from pyrevit.api import DB
user = doc.Application.Username
rule = DB.ParameterFilterRuleFactory.CreateEqualsRule(
    DB.ElementId(DB.BuiltInParameter.EDITED_BY), user)
borrowed = DB.FilteredElementCollector(doc) \
    .WhereElementIsNotElementType() \
    .WherePasses(DB.ElementParameterFilter(rule)).ToElements()
rows = []
for e in borrowed:
    owner = doc.GetElement(e.OwnerViewId) if e.OwnerViewId != DB.ElementId.InvalidElementId else None
    rows.append({
        "unique_id": e.UniqueId,
        "owner_view_unique_id": owner.UniqueId if owner else "",
        "category": e.Category.Name if e.Category else "",
    })
result = {"document": doc.Title, "count": len(rows), "rows": rows[:50]}
```

- `CreateEqualsRule` with a string needs a case argument in some Revit years. Check it with `lookup_revit_api` first.
- Add a geometry fingerprint to each row: filled region boundaries, curve end points, tag head and leader points, and view crop boxes. Round the numbers.
- Write the full map to JSON and CSV in the user's work folder. Return the file paths and the count, not the rows. See "Result size" in `am-revit-api-docs`.
- Put the document title in the result. See "Several documents open" below.

## Step 3: have the user make a rescue copy

Ask the user to use Save As to make a desktop copy of the broken local. Then check the copy against the map by UniqueId (read only).

Tell the user two things first:

- The copy becomes a separate file-based central. Never sync it with the real central.
- OneDrive can lock or upload a large .rvt. Save the copy in a folder outside OneDrive.

## Step 4: make a new local (cloud model)

Ask the user to close the model. Then help the user find the old local in the cloud cache:

`%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit <year>\CollaborationCache\<account>\<project guid>\<model guid>.rvt`

- The model guid file has a `_backup` folder next to it. Rename both. For example, add `.old` to the end. Do not delete them.
- Pick the file by its size and its last save time. The folder names are guids, not model names.
- The user then opens the model again from Autodesk Docs. Revit makes a new local.

For a file-based central (not cloud), the user makes a new local the usual way: Open, select the central, and select "Create New Local". This case was not tested.

## Step 5: compare before you copy

In the new local, look up each UniqueId from the map. Compare the geometry fingerprint (read only).

- Same UniqueId and same geometry: the element is already in central. Do not copy it.
- Missing UniqueId, or different geometry: list it. Show the list to the user.
- Copy only what the user approves, with `am-safe-change`.

`GetModelUpdatesStatus` is not proof. In a local that did not record its last sync, it can say `NotYetInCentral` for elements that central already has. In the field session it said this for about 260 elements. All of them were in central with the same UniqueId and geometry. Without the compare, the agent would have copied duplicates.

## Step 6: compare the rescue copy with the healthy model

Use this step when the user asks: "Is anything in the rescue copy worth moving to the healthy model?"

Match by content first. Use UniqueId only to find views and sheets. A diff by UniqueId alone gives a lot of noise:

- DWG import sub-elements get new UniqueIds in the copy. Compare the import instances by type name and origin, and the sub-element counts.
- Sketches, sketch planes and automatic sketch dimensions were more than half of each "only in one model" list. Leave them out.

Compare these, view by view (find each view by UniqueId):

- the element count per category in each owner view;
- the text note strings;
- the areas by area scheme and level (count and total area);
- the import instances by type name and origin.

Then name the person who last changed each difference:

- Read `LastChangedBy` with `WorksharingUtils.GetWorksharingTooltipInfo` in the new local of the live central only.
- Never read it in the rescue copy. After Save As, `Creator` shows the current user for every element.
- If someone else changed the element later in central, the default is "do not transfer". The rescue copy is an older snapshot. A copy can bring back content that a colleague deleted on purpose.

Full-model scans are slow in IronPython. A loop over every element in two documents took 148 seconds, and Revit was frozen. Use a native filter, or `engine="cpython"`. See "Slow scans" in `am-revit-api-docs`.

## Several documents open

The rescue copy and the new local can be open in one Revit at the same time. A `run_query` script reads the active document. The active document can change when the user opens a second model.

- Call `get_context` before each read query. Check the document title.
- With more than one project document open, find the document by title in `app.Documents`. Put the title in the result.
- Never report a result without the title of the document that it read.

```python
# run_query, read only. inputs: {"title": "<document title from get_context>"}
target = None
for d in doc.Application.Documents:
    if not d.IsFamilyDocument and d.Title == inputs["title"]:
        target = d
if target is None:
    result = {"error": "document not open", "open": [d.Title for d in doc.Application.Documents]}
else:
    result = {"document": target.Title}  # read `target`, not `doc`, below this line
```

`run_modify` and `show_elements` act on the active document only. Before a change in step 5, ask the user to make the new local the active window. Then check the `get_context` title.

## Not verified

- File-based (not cloud) central models.
- Revit years other than 2026.
- The case where the last sync did not reach central. Step 5 must then copy work. The field session did not test this.
- Whether the `Creator` reset also happens after Detach from Central, or only after Save As.
