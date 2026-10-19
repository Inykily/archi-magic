---
name: am-revit-api-docs
description: Look up the Revit API (classes, methods, properties, enums, events, parameters, exceptions) in the version-exact documentation shipped with each installed Revit (RevitAPI.xml / RevitAPIUI.xml), before writing or reviewing any Revit add-in, pyRevit script, Dynamo Python or agent-runtime code. Use it to check that a member exists in the user's Revit year, read its signature/params/returns/remarks, and spot version differences (e.g. 2024 vs 2026). Triggers on "revit api", "does Revit have a method for", "what does <Revit class/member> do", "signature of", "which Revit version added/removed", "revitapidocs", "FilteredElementCollector", "Transaction", "ElementId".
---

# am-revit-api-docs

Ground Revit API answers in the documentation for the **Revit version the user actually runs**. Don't rely on memory: members get added, renamed and removed between years (for example `ElementId.IntegerValue` was replaced by `ElementId.Value` in 2024+).

## Sources, in order

1. **Local, version-exact docs (preferred).** Every Revit install ships `C:\Program Files\Autodesk\Revit <year>\RevitAPI.xml` and `RevitAPIUI.xml`. Search them with the script in this skill's directory:
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File "<this skill dir>\scripts\search-revit-api.ps1" -Query "Wall.Create"
   ```
   - `-Year 2024` picks a specific installed version. The default is the newest installed.
   - `-Kind T|M|P|F|E` filters to types, methods, properties, fields/enum values, or events.
   - `-AllYears` shows which installed years contain a match. Use it for "when was this added/removed".
   - Query words are matched as substrings of the full member name, in any order: `"OfCategory Collector"` finds `FilteredElementCollector.OfCategory`.
2. **Live Revit, if the pyRevit agent runtime is connected.** The `pyrevit` MCP tool `lookup_revit_api` asks the running Revit directly. Use it to confirm behavior against the open session.
3. **Online:** `https://www.revitapidocs.com/<year>/`, for browsing namespaces or when Revit isn't installed (the script exits 2). Fetch the specific page; don't guess its URL contents.
4. **The Revit SDK samples and The Building Coder** (jeremytammik.github.io/tbc) cover how-to patterns the XML doesn't explain.

## Rules

- Quote the member exactly as the docs give it (full name and signature), and say which Revit year you checked.
- If the script finds nothing, say "not found in Revit <year> docs on this machine". That's a scoped negative, not proof the API doesn't exist. Try a shorter query or `-AllYears` before concluding.
- When code must run on several Revit years, check each one with `-AllYears` and branch on the differences.
- pyRevit scripts run on IronPython 2.7 by default: no f-strings. Use `.Value` vs `.IntegerValue` according to the year.

## House rules (all am-* skills)

- Write all output to the user in ASD-STE100 Simplified Technical English. Use short sentences (max 20 words for instructions, 25 for descriptions). Use active voice. Put one instruction in each sentence, and start it with the verb. Use one word for one meaning. Explain any technical term the first time you use it, because many users are architects, not programmers.
- When a task has independent parts (for example, several files to check or several Revit years to compare), do them in parallel with subagents. Keep steps that depend on each other in sequence.
