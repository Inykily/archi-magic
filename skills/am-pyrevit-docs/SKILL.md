---
name: am-pyrevit-docs
description: Look up official pyRevit documentation (docs.pyrevitlabs.io) and the installed pyRevit source before writing or debugging pyRevit tools, extensions, bundles, forms, output window code, configs, CLI commands, routes or the Agent Runtime. Full-text searches the docs site's own search index (cached 7 days) and points at the exact page, then confirms against the installed pyrevitlib source. Triggers on "pyrevit docs", "how do I in pyrevit", "pyrevit forms", "pyrevit output", "pyrevit bundle / extension / pushbutton", "pyrevit cli", "pyrevit configs", "pyrevit routes", "script.get_output", "pyrevit agent runtime".
---

# am-pyrevit-docs

Ground pyRevit answers in the real docs and the installed source. Don't rely on memory: pyRevit 7 changed things since older tutorials were written.

## Sources, in order

1. **Search the docs** with the script in this skill's directory:
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File "<this skill dir>\scripts\search-pyrevit-docs.ps1" -Query "output window table"
   ```
   - It prints the matching sections with their exact URLs and a snippet. Every word must appear in the section. Use fewer, distinctive words: `"forms select_views"`, `"bundle.yaml"`, `"configs agent"`.
   - `-Index` prints `llms.txt`, one line per docs page, for browsing by topic.
   - `-Refresh` forces a re-download. The index is cached under `%LOCALAPPDATA%\archi-magic\cache` for 7 days; if the site is unreachable, the script warns and uses the cache.
2. **Read the page.** Fetch the URL the search returned when you need the full text or the code samples.
3. **Confirm against the installed source.** It's the truth for the user's version. pyRevit 7 per-user lives at `%APPDATA%\pyRevit-Master`:
   - `pyrevitlib\pyrevit\` holds the Python API: `forms`, `script`, `revit`, `output`, `coreutils`, `userconfig`. Grep for the function and read its docstring and signature.
   - `extensions\pyRevitTools.extension\` has real bundle examples (`*.pushbutton\script.py`, `bundle.yaml`).
   - `& "$env:APPDATA\pyRevit-Master\bin\pyrevit.exe" <command> --help` gives exact CLI usage.
4. **For Revit API questions** (`Autodesk.Revit.DB.*`), use the `am-revit-api-docs` skill.

## Rules

- Cite the docs URL or the source file you used, and the pyRevit version (`pyrevit --version`).
- If neither the docs nor the source mention it, say so. Don't invent a pyRevit function.
- pyRevit scripts default to IronPython 2.7: no f-strings, no type hints. Check `__context__`, `__title__` and the `bundle.yaml` keys against the docs, not memory.

## House rules (all am-* skills)

- Write all output to the user in ASD-STE100 Simplified Technical English. Use short sentences (max 20 words for instructions, 25 for descriptions). Use active voice. Put one instruction in each sentence, and start it with the verb. Use one word for one meaning. Explain any technical term the first time you use it, because many users are architects, not programmers.
- When a task has independent parts (for example, several files to check or several Revit years to compare), do them in parallel with subagents. Keep steps that depend on each other in sequence.
