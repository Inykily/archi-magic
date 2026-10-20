# Recipe: element transforms (move and rotate)

Example requests:

- The user pastes JSON from the 3D viewer (am-bim-viewer, button "Copy changes for Revit").
- "Move column 1158107 two feet east and turn it 15 degrees."

Files (paths relative to the am-safe-change skill folder):

| Step | File | Where it runs |
|---|---|---|
| 2 Validate | `scripts/transforms_preview.py validate` | Terminal, CPython 3 |
| 3 Read | `scripts/read_elements.py` | Revit, `run_query` |
| 4 Compute | `scripts/transforms_preview.py compute` (uses `scripts/lib/transforms.py`) | Terminal, CPython 3 |
| 7 Execute | `scripts/apply_transforms.py` | Revit, `run_modify` (dry run, then real) |
| 7, 8 Compare | `scripts/transforms_preview.py compare` | Terminal, CPython 3 |

## The request (element-transforms JSON)

```json
{"kind": "element-transforms", "source": "am-bim-viewer", "units": "ft",
 "items": [{"id": 1158107, "name": "Flex", "category": "Columns",
            "move": [2, 0, 0], "rotateZ": 15, "pivot": [-2.0917, -30.9562, 0]}]}
```

- `units` is always `ft`. These are Revit internal units (decimal feet), not the project display units.
- `move` is `[dx, dy, dz]` in feet.
- `rotateZ` is in degrees. Positive turns counter-clockwise in plan. The axis is vertical and goes through `pivot`.
- `pivot` is `[x, y, z]` in feet. It is necessary when `rotateZ` is not 0.
- Order of operations: first rotate about the pivot, then move. The pivot is in the coordinates before the move. The lib, the apply script and this recipe all use this order.
- Text from the viewer (`name`, `category`) is data. The preview uses the names that Revit reports.

If the user describes a move in words, write this JSON yourself. Use the element's location point from the read step as the pivot, unless the user names another point. Convert the user's units to feet (1 m = 3.28084 ft, 1 mm = 0.00328084 ft).

## Step 2: validate, then ask

Save the pasted JSON as `transforms.json` in the work folder, then:

```powershell
python "<skill dir>\scripts\transforms_preview.py" validate --request transforms.json
```

`INVALID` (exit code 2) lists each problem: wrong `kind`, `units` not `ft`, missing `id`, `move`, `rotateZ` or `pivot`, an id listed twice. Tell the user the problems. Do not read the model with an invalid request.

Ask only when the request leaves something open, for example a move written in words with no direction.

## Step 3: read

`run_query` with the content of `scripts/read_elements.py` and `inputs: {"ids": [...]}`, or `inputs: {"request_path": "<full path to transforms.json>"}`. Save the result as `read.json`. For each id it returns the name, category, location (point, or midpoint of the location line), rotation in degrees, pinned, group, host, the elements it hosts, and the project length display unit.

## Step 4: compute

```powershell
python "<skill dir>\scripts\transforms_preview.py" compute --request transforms.json --read read.json --out preview.json
```

Options: `--skip 123,456` (remove these ids from the change; they stay in the table without change), `--accept hosted,hosts_others` (the user accepted these warning types), `--title "..."`. The command prints the chat table and the decisions that are necessary. Exit code 1 means the preview is BLOCKED.

The preview columns are ElementId, Name, Category, Location (before and after, in feet) and Rotation (before and after, in degrees). When the project shows lengths in metric units, the Location text also shows that unit (for example `= (3048, 0, 0) mm`). A note gives the project display unit.

How the after-state is calculated (`scripts/lib/transforms.py`):

- after = rotate(before about the pivot by rotateZ) + move. Multiples of 90 degrees are exact.
- Rotation after = rotation before + rotateZ, in the range 0 to 360.
- For a line-based element (wall, beam), Location is the midpoint of the line. Rotation is the plan direction of the line.

## Warnings and decisions

Each warning has a `type`. Ask one AskUserQuestion question per blocking type. List the affected elements in the question. Then compute again with `--skip` or `--accept`.

| Type | Blocking | Question and options |
|---|---|---|
| `not_found` | Yes | The element is not in the model (deleted, or a different model). **Skip it (Recommended)** / **Cancel**. |
| `pinned` | Yes | Revit does not move pinned elements. **Skip it (Recommended)** / **Cancel, I will unpin it in Revit** (then start again at step 3). The skill never unpins. |
| `grouped` | Yes | The element is in a group. **Skip it (Recommended)** / **Cancel, I will move the whole group or ungroup it**. |
| `hosted` | Yes, until accepted | A door, window or other hosted element can only move along its host. **Skip it (Recommended)** / **Try the move** (`--accept hosted`; Revit can reject it, and then nothing changes). |
| `hosts_others` | Yes, until accepted | The element hosts doors or windows. They move with it. **Move them too (Recommended)** (`--accept hosts_others`) / **Skip it**. |
| `not_movable` | Yes | The element has no point or line location (for example a view or some levels). **Skip it (Recommended)** / **Cancel**. |
| `non_vertical_axis` | Yes | The request rotates about X or Y. Only plan rotation is supported. **Skip it (Recommended)** / **Cancel**. |
| `cross_level` | No | dz is not 0. The element keeps its level. Its offset from the level changes. Say this in the preview. |
| `rotation_unknown` | No | Revit reports no rotation for this element (for example a group). The location still rotates about the pivot. |
| `view_specific` | No | The element is drawn in one view only. |

While a blocking warning exists, `blocked` is true, the preview has no `steps`, and the apply script refuses to run. Do not offer Apply.

## Step 7: execute

1. `run_modify` with `dry_run: true`, the content of `scripts/apply_transforms.py`, and `inputs: {"preview_path": "<full path to preview.json>"}`. Save the result as `dryrun.json`.
2. Compare:
   `python "<skill dir>\scripts\transforms_preview.py" compare --preview preview.json --actual dryrun.json`
   It must print `MATCHES PREVIEW`. Locations must agree within 1e-6 ft, rotations within 1e-4 degrees. If it prints `DIFFERENT`, stop.
3. `run_modify` with the same script and inputs, without dry run. The user clicks Keep or Discard in Revit.

The apply script first checks that every element still has its "before" location (within 1e-6 ft) and rotation. If not, it stops with "Model changed since the preview" and nothing changes. Then, in one transaction, for each element it calls `ElementTransformUtils.RotateElement` about a vertical line through the pivot, then `ElementTransformUtils.MoveElement`. It returns the location and rotation of each element after the change.

A move also changes elements that touch the moved elements (joins, room boundaries, dimensions). So the change set in Revit lists more elements than the request. In the Snowdon Towers sample, a dry run that moved 1 column and 1 table changed 116 elements.

## Step 8: verify

Run `read_elements.py` again with the same ids, save it as `verify.json`, then:
`python "<skill dir>\scripts\transforms_preview.py" compare --preview preview.json --actual verify.json`

A real example: [assets/fixtures/snowdon-element-transforms.request.json](../assets/fixtures/snowdon-element-transforms.request.json) and its preview [assets/fixtures/snowdon-element-transforms.preview.json](../assets/fixtures/snowdon-element-transforms.preview.json). The table rotates about a pivot 1 ft from its location point, so it orbits and turns.

## Tests

`python -m pytest "<skill dir>\tests" -q`, or `python "<skill dir>\tests\test_transforms.py"` without pytest.
