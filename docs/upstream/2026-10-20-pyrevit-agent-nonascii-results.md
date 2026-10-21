# Upstream issue draft: pyRevit agent runtime cannot return non-ASCII text from an IronPython run

Status: FILED on 2026-10-20 as https://github.com/pyrevitlabs/pyRevit/issues/3812. The public issue leaves out the archi-magic file list below.
Repro verified live on 2026-10-20 (run ids below are local run records under `%APPDATA%\pyRevit\agent\runs`).

---

## Title

Agent runtime: `run_query` on IronPython fails with `ResultSerializationError` when `result` contains a non-ASCII character

## Environment

- pyRevit 7.0.0.26278+2233 (per-user install, `get_context` reports `"version": "7.0.0.26278+2233"`)
- Revit 2026.3 (build 26.3.0.37), English_USA
- pyRevit Agent Runtime, MCP server `pyrevit mcp`, agent policy `ask`
- Engine: `ironpython 2.7.12` (the default engine)
- Windows 11 Enterprise 10.0.26100
- Model: Autodesk sample "Snowdon Towers Sample Architectural" (any model works; the script does not read the model)

## Minimal repro

Call the MCP tool `run_query` with `engine: "ironpython"` and this script:

```python
import sys
result = {"python": sys.version, "text": u"Café"}
```

The `é` escape keeps the script source pure ASCII, so the source encoding is not a factor.

## Actual (IronPython 2.7.12, run id `b7f7885ae0ad`)

```json
{"status":"error","run_id":"b7f7885ae0ad","error":{"type":"ResultSerializationError","message":"'unknown' codec can't decode byte 0xe9 in position 3: Unable to translate bytes [E9] at index 3 from specified code page to Unicode.","traceback":"Traceback (most recent call last):\n  File \"json\\__init__.py\", line 247, in dumps\n  File \"json\\encoder.py\", line 209, in encode\n  File \"json\\encoder.py\", line 434, in _iterencode\n  File \"json\\encoder.py\", line 390, in _iterencode_dict\n  File \"json\\encoder.py\", line 47, in py_encode_basestring_ascii\nUnicodeDecodeError: 'unknown' codec can't decode byte 0xe9 in position 3: Unable to translate bytes [E9] at index 3 from specified code page to Unicode.\n"},"engine":"ironpython 2.7.12","elapsed_ms":14}
```

We first saw it with real model text: a sheet named "Café Kitchen" read with `ViewSheet.Name` (reported by our am-safe-change builder; the literal repro above is the one verified live).

## Expected

The run succeeds and returns `"text": "Café"`, as the CPython engine does with the same script.

Control, same session, `engine: "cpython"` (run id `a6085891aee1`):

```json
{"status":"ok","run_id":"a6085891aee1","result":{"python":"3.12.3 (tags/v3.12.3:f6650f9, Apr  9 2024, 14:05:25) [MSC v.1938 64 bit (AMD64)]","text":"Café"},"engine":"cpython 3.12.3","elapsed_ms":23}
```

Control, IronPython with an ASCII-only result (run id `b3bb4113be05`): `"status":"ok"`.

## Likely cause

The result serializer calls the stdlib `json.dumps` under IronPython 2.7. `py_encode_basestring_ascii` treats the string as a byte `str` and decodes it with the default code page, which fails on U+00E9. Under IronPython every `str` is a .NET `System.String` (already Unicode), so the decode step is wrong. A fix could serialize the result with `ensure_ascii=False` plus an explicit UTF-8 write, or with the .NET JSON serializer on the host side.

## Workaround we use (archi-magic)

Before setting `result`, the IronPython scripts escape every non-ASCII character as `\uXXXX` and set `"escaped": true` in the result. The caller (CPython on the user's computer) reverses the escape. Example:

```python
def txt(s):
    return "".join(c if ord(c) < 128 else "\\u%04x" % ord(c) for c in s)
```

## archi-magic files that carry the workaround (remove when fixed upstream)

Revit-side scripts (escape):

- `skills/am-safe-change/scripts/read_sheets.py`
- `skills/am-safe-change/scripts/read_elements.py`
- `skills/am-safe-change/scripts/apply_sheet_shift.py`
- `skills/am-safe-change/scripts/apply_transforms.py`
- `skills/am-markup-intake/scripts/read_model_index.py`
- `skills/am-area-report/scripts/area_report.py`
- `skills/am-workset-audit/scripts/workset_audit.py`
- `skills/am-workset-audit/scripts/workset_fix.py`
- `skills/am-schedule-view/scripts/read_schedules.py`

Caller side (unescape when `"escaped": true`):

- `skills/am-safe-change/scripts/lib/sheet_shift.py` (`unescape`, `load_read_result`)
- `skills/am-safe-change/scripts/lib/transforms.py` (`unescape`)
- `skills/am-safe-change/scripts/sheet_preview.py`
- `skills/am-markup-intake/scripts/consolidate.py` (`_unescape`, `load_model`)

Docs that mention it:

- `skills/am-safe-change/SKILL.md` (engine note)
- `skills/am-area-report/SKILL.md`
- `skills/am-workset-audit/SKILL.md`

Tests that pin the round trip: `skills/am-safe-change/tests/test_sheet_shift.py` (`test_unescape_round_trip`), `skills/am-safe-change/tests/test_transforms.py` (`test_unescape_read_result`), `skills/am-markup-intake/tests/test_markup_intake.py` (`test_model_index_unescape`).

When the fix ships: keep the unescape on the caller side for one release (old run records still carry `"escaped": true`), then remove the Revit-side escape and set a minimum pyRevit version in am-doctor.
