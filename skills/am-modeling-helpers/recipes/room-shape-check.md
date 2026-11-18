# Recipe: find sliver, ring and broken rooms

Use this check before you model a finish from a room boundary. It is read only.

Example requests:

- "Is this room safe to model a finish from?"
- "Find sliver rooms on level 3."

## Files

| Step | File | Where it runs |
|---|---|---|
| Read | `scripts/read_room_shapes.py` | Revit, `run_query` |
| Check | `scripts/room_shape_report.py` (rules in `scripts/lib/room_shape.py`) | Terminal, CPython 3 |

## Steps

1. Call `get_context` and `get_skill("revit-scripting")`.
2. Run `read_room_shapes.py` with `run_query`. Pass one of these inputs:
   - `{"room_ids": [<id>, ...]}` for 1 to 500 rooms.
   - `{"level_id": <id>}` for every room on one level (at most 500).
   Add `"boundary_location": "center"` only when the user asks for the wall center line. The default is the finish face, the same face that Revit uses for room area.
3. Save the result as `shapes.json`. If `complete` is false, run again with the ids in `pending_room_ids`.
4. Run `python scripts/room_shape_report.py --read shapes.json --out shape-report.json`.
   Exit 0: no room is blocked. Exit 1: some rooms are not safe to model from. Exit 2: bad input.
5. Show the table in chat. Give the reason for each flagged room in one line.

## What the flags mean

| Flag | Level | Meaning |
|---|---|---|
| `point_outside` | block | The location point is outside the room's own boundary (or on its edge). The room can be the gap between two outlines, not the space the user means. |
| `ring` | block | The room has a hole, and its mean width (2 x area / perimeter) is below the limit (12 in by default). A finish from this boundary is a thin ring. |
| `narrow` | block | The room is a strip below the width limit. |
| `tiny` | block | The area is below 2 sf. |
| `no_area`, `no_boundary`, `no_location_point` | block | Revit gives no usable boundary or no location point. |
| `large_hole` | warn | Holes take half or more of the outer outline. Check that the hole is real. |
| `area_mismatch` | warn | The boundary area differs from the Revit area by more than 5 percent. |
| `revit_point_check_differs` | warn | Revit's own point-in-room test gives a different answer. Check the room in a plan view. |

`loop_sources` lists the categories that bound each loop of a flagged room (for example "linked model" or "Floors"). Use it to tell the user why the boundary is wrong. In the field case, the outer loop was a linked building outline and the hole was bounded by a roof floor.

## What to do next

- Leave every blocked room out of the finish scope. Tell the user which rooms and why.
- Do not fix a room boundary from this skill. A fix (room bounding settings, separation lines, moving the room) is a model change. It goes through `am-safe-change` as a separate task, after the user decides.
- Change the limits only when the user asks: `--min-width-in`, `--min-area-sf`, `--area-tolerance`.
