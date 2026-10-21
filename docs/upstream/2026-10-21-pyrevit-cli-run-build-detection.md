# Upstream issue draft: `pyrevit run` cannot detect the version of a Revit 2026.3 model

Status: DRAFT. Not filed. File it at https://github.com/pyrevitlabs/pyRevit/issues/new after the user says yes.

## Summary

`pyrevit run <script> <model.rvt> --revit=2026` stops with:

```
Error: Can not detect the Revit version of model at "...\Snowdon-src2.rvt". Model might be newer than specified version 2026.
```

The model is the Autodesk sample `Snowdon Towers Sample Architectural.rvt` from Revit 2026.3 (`C:\Program Files\Autodesk\Revit 2026\Samples`). Revit 2026.3 opens it without an upgrade prompt.

## Evidence (`--debug`)

```
Debug: Parsing info from BasicFileInfo: "Format: 2026"
Debug: Parsing info from BasicFileInfo: "Build: 1515(x64)"
Debug: Getting host product info for: Build: 1515(x64)
Debug: No host product matches "Build: 1515(x64)"
Debug: Stream "PartAtom" not found in structured storage file ...
Error: Can not detect the Revit version of model ...
```

The CLI reads `Format: 2026`, but it finds the version only from the build number. Build `1515` is not in its host product table. The file also has no PartAtom stream for the fallback, so detection fails.

## Environment

- pyRevit 7.0.0.26278+2233, CLI at `%APPDATA%\pyRevit-Master\bin\pyrevit.exe`
- Revit 2026.3 (build 26.3.0.37), Windows 11

## Suggested fix

When no host product matches the build, fall back to the `Format: <year>` line of BasicFileInfo. If `--revit=<year>` is given and equals that format year, accept it.

## Related

pyRevit's bundled test model (`Make Pattern.pushbutton/tests/Tests.rvt`) gives the same error with `--revit=2026`.
