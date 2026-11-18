# Recipe: room parameters driven by a key schedule

Use this check before you set a room parameter such as Floor Finish, Wall Finish, Base Finish or Ceiling Finish. It is read only.

A key schedule is a table of named "keys". Each key holds a set of values. A room that uses a key shows the key's values, and Revit makes those room parameters read-only. A write to them fails with "The parameter is read-only."

Example requests:

- "The floor finish is read-only. Why?"
- "Set the floor finish of these rooms to the new tile."

## Files

| Step | File | Where it runs |
|---|---|---|
| Read | `scripts/read_room_keys.py` | Revit, `run_query` |
| Report and preview | `scripts/room_key_plan.py` (rules in `scripts/lib/room_keys.py`) | Terminal, CPython 3 |

## Steps

1. Call `get_context` and `get_skill("revit-scripting")`.
2. Run `read_room_keys.py` with `run_query`. Pass `{"room_ids": [<id>, ...]}` (1 to 500 target rooms). Add `"parameters": ["<name>", ...]` for parameters other than the four built-in finish parameters.
3. Save the result as `keys.json`. If `scan_complete` is false, the scan of all rooms stopped early. Do not edit a shared key from that read.
4. Run `python scripts/room_key_plan.py report --read keys.json --parameter "<name>"`. Use the parameter name that the read lists in `parameters`.
5. Show the states in chat:
   - `writable`: set the value on the room.
   - `key_driven`: a key drives the value. The report names the key, how many listed rooms use it, and how many other rooms use it.
   - `read_only_other`: read-only for another reason. This skill cannot fix it. Tell the user.
   - `missing`: the room has no parameter with that name.
6. For each key, ask the user one question (AskUserQuestion). Put the recommended option first:
   - **New key for these rooms**: copy the key row, change the value, and assign the new key to the listed rooms only. This is the recommended option when other rooms use the key.
   - **Edit the key**: change the value on the key row. Every room that uses the key changes. This is the recommended option only when no other room uses the key.
   - **Skip**.
   Ask for the new value, and for the new key name when the user picks a new key.
7. Write the preview for that one decision:
   `python scripts/room_key_plan.py preview --read keys.json --parameter "<name>" --value "<value>" --option new-key --key <key id> --new-key-name "<name>" --out preview.json`
   Use `--option edit-key --key <key id>` for a key edit, and `--option set-rooms` for the writable rooms.
   Exit 1 means the preview is blocked (for example the new key name exists, or the scan is incomplete). Explain the warning. Do not continue.
8. Hand `preview.json` to `am-safe-change`. Start at its step 4 (ownership check). The preview lists the rooms of a key edit with "Room (by key)", because their values change too.
9. After Keep, run `read_room_keys.py` again with the same inputs. Check that each target room shows the new value and the planned key.
