# Recipe: door sill values from the floor finishes and the transition details

Example request: "Fill the empty SILL values in the door schedule from the transition details."

This recipe reads each door, the floor finish of its From Room and To Room, and the transition details on the sheets that the user picks. It plans a sill value `<detail number>/<sheet number>` for each door with one clear match. It lists every other door for the user and does not guess. It comes from issue #299. This is a first step: the plan is read only, and the write goes through `am-safe-change`.

Files (paths relative to the am-modeling-helpers skill folder):

| Step | File | Where it runs |
|---|---|---|
| Read | `scripts/read_door_thresholds.py` | Revit, `run_query` |
| Report and preview | `scripts/door_threshold_plan.py` (uses `scripts/lib/door_thresholds.py`) | Terminal |
| Write | `am-safe-change`, 8 steps, a change with no recipe yet | Revit, `run_modify` |

## 1. Ask

Ask only what the request leaves open. Use AskUserQuestion, one decision per question:

1. **Which door parameter holds the sill value?** For example `SILL`. Read the door schedule with `am-schedule-view` to see it.
2. **Which room parameter holds the floor finish?** "Floor Finish" (Recommended), or another one. A room key schedule can drive this value. If so, the value is the key's value. Use [room-key-schedules.md](room-key-schedules.md) to check.
3. **Which sheets hold the transition details?** Give the sheet ids.
4. **Which phase?** The last phase (Recommended). From Room and To Room depend on the phase.
5. **Which value format?** `<detail>/<sheet>` (Recommended), for example `5/A-501`. Pass another format with `--format "{sheet}-{detail}"`.

## 2. Read

Run `scripts/read_door_thresholds.py` with `run_query` and `inputs: {"sill_parameter": "SILL", "finish_parameter": "Floor Finish", "sheet_ids": [<ids>]}`. Add `"phase_id"` or `"door_ids"` when needed. Save the result as `doors.json`. It reads at most 5000 doors and 50 sheets.

## 3. Build the finish map with the user

Rooms hold finish codes (for example `CPT`, `TZ`, `RF`). Detail view names hold words (Carpet, Terrazzo, Rubber). Write a map file `finish-map.json`:

```json
{"confirmed": false,
 "codes": {"CPT": ["carpet"], "TZ": ["terrazzo"], "RF": ["rubber"]},
 "details": {"5/A-502": ["CPT", "RF"]}}
```

- `codes`: one or more words for each code. Matching ignores case and needs whole words. "Polished concrete" works as one word.
- `details`: optional manual pairs for detail names that do not say the two finishes.
- `separators`: optional. The characters that split two codes in one room value. Default `/,;+&`.

Run the report:

```powershell
python "<skill dir>\scripts\door_threshold_plan.py" report --read doors.json --map finish-map.json
```

It prints each detail with the finish pair found in its name, the room finish codes with their counts, and one row per door with its status. Show the map and the detail pairs to the user. Ask the user to confirm the map. In the field session the user stopped this question, so the map stayed unconfirmed and nothing was written. Set `"confirmed": true` only after the user says yes. An unconfirmed map blocks the preview.

## 4. Statuses

| Status | Meaning | Written? |
|---|---|---|
| `match` | One detail shows the finish pair. The order of the two rooms does not matter. | Yes |
| `more_than_one_match` | Two or more details show the pair. | No, ask the user |
| `no_match` | No detail shows the pair. | No |
| `mixed_finish` | A room holds more than one code, for example `CPT/TZ`. | No |
| `empty_finish` | A room value is empty or `-`. | No |
| `unknown_code` | A room code is not in the map. | No |
| `same_finish` | Both rooms have the same code. | No |
| `one_side_no_room` | One side has no room, often an outside door. | No |
| `no_rooms` | Neither side has a room. | No |
| `has_value` | The sill already has a value. The plan never overwrites it. | No |
| `read_only` | The sill parameter is read-only on the door. | No |
| `no_parameter` | The door has no parameter with that name. | No |

## 5. Preview

```powershell
python "<skill dir>\scripts\door_threshold_plan.py" preview --read doors.json --map finish-map.json --out preview.json
```

The preview has one row per clear match: `ElementId`, `Mark`, and the sill parameter, empty before and the detail reference after. Its notes count the other statuses. `not_changed` lists every other door with its reason. Show that list to the user too. Exit code 1 means BLOCKED.

## 6. Write with am-safe-change

Give `preview.json` to `am-safe-change`. Follow its 8 steps for a change with no recipe yet: ownership check, preview, confirm, dry run, Keep/Discard, verify.

- Each step is `{"op": "set_parameter", "element_id", "parameter", "value", "expect_before"}`.
- Stale-state guard for the apply script: read the parameter again and stop when its value is not `expect_before` (empty). Someone else may have filled it since the read.
- Set the value with `element.LookupParameter(parameter).Set(value)` in one transaction.
- Verify with `am-safe-change` `scripts/read_values_by_id.py` and `scripts/verify_commit.py`. The preview columns are parameter names, so the re-read compares them directly.

## Not verified

- The scripts are tested with stand-ins, not in Revit. The field session stopped before any write.
- How other offices name their transition details. Use the map words and the manual pairs to fit them.
