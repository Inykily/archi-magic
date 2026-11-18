# Recipe: which floors lie in which rooms, and the finish floor plan

Use this recipe to change the finish floors of some rooms. It reads the model, shows how much of each floor lies in the rooms, asks one question per floor, and writes a change preview. It changes nothing.

Example requests:

- "Which floors are in these rooms?"
- "Change the finish floor of rooms 101 to 104 to the new tile."
- "Split the finish floor by room."

## Why Revit solids

The read script extrudes each room outline down and up from its boundary plane. It finds the floors whose bounding box meets that box (a fast prefilter). Then it intersects each floor solid with the room solid and adds up the faces of the result that point up. This gives the floor area inside the room. In the field, sample points missed floors, and point-in-polygon in Python timed out and froze Revit. The solid method with the bounding box prefilter finished.

## Files

| Step | File | Where it runs |
|---|---|---|
| Read | `scripts/read_floor_room_coverage.py` | Revit, `run_query` |
| Summary, questions, preview | `scripts/floor_coverage_plan.py` (rules in `scripts/lib/floor_coverage.py`) | Terminal, CPython 3 |

## Steps

1. Do the room shape check first ([room-shape-check.md](room-shape-check.md)). Leave blocked rooms out.
2. Call `get_context` and `get_skill("revit-scripting")`. Tell the user to save or sync.
3. Run `read_floor_room_coverage.py` with `run_query`. Pass `{"room_ids": [<id>, ...]}` (1 to 20 rooms). Optional inputs:
   - `floor_ids`: only these floors (at most 200).
   - `z_below_ft` and `z_above_ft`: the band around the room's boundary plane (default 3 ft each). It must hold the finish floor and the slab under it.
   - `time_budget_s`: default 240 s. The `run_query` limit is 300 s.
   Set `timeout_s` on the call when the rooms are large. If the IronPython engine is slow, run again with the CPython engine.
4. Save the result as `coverage.json`. If `complete` is false, run again with `pending_room_ids` and keep both files. Plan only from a complete read.
5. Ask the user which floor types are finish types. Use the `type_id` and `type_name` values from the read.
6. Run `python scripts/floor_coverage_plan.py summary --read coverage.json --finish-types <id>,<id> --out summary.json`.
7. Show the two tables in chat:
   - Floors: type, Structural flag, role (`finish` or `protected`), area, share in scope, action, rooms.
   - Rooms: area, finish floor coverage, verdict (`ok`, `gap` = part of the room has no finish floor, `double` = finish floors overlap in plan).
   Show every warning, for example finish floors at different height offsets.
8. Ask the printed questions one at a time, one per floor (user rule: ask before each action). Use AskUserQuestion. Put the recommended option first. Give the share in scope and the area outside the rooms in the question.

   | Action | Meaning | Options (recommended first) |
   |---|---|---|
   | `retype_whole` | 98 percent or more of the floor lies in one target room. | retype, skip |
   | `retype_whole_or_split` | The floor lies in two or more target rooms. | retype, split, skip |
   | `split_or_ask` | Only part of the floor lies in the target rooms. | split, retype (also changes the area outside), skip |
   | `edge_only` | Less than 2 percent lies in the rooms (strips under walls). | no question |
   | `never_change` | Protected: structural slab or not a finish type. | no question |
   | `unresolved` | Revit could not intersect the floor with a room. | no question. Tell the user. |

9. Ask for the new finish floor type (id and name from the model).
10. Write the preview:
    `python scripts/floor_coverage_plan.py preview --read coverage.json --finish-types <id>,<id> --decide <floor>=split,<floor>=retype --new-type-id <id> --new-type-name "<name>" --out preview.json`
    A split shows one row per room piece and one row for the rest of the old floor, which keeps its type. Exit 1 means blocked (for example a decision for a protected floor, or no new type). Explain the warning. Do not continue.
11. Hand `preview.json` to `am-safe-change`. Start at its step 4 (ownership check). Read "Model writes go through am-safe-change" in this skill's `SKILL.md` for the field notes on the apply script.
12. After Keep, run `read_floor_room_coverage.py` again with the same rooms. Run the summary again. Each room must show its new pieces, and no protected floor may change.
