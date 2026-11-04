# Recipe: standards view

A standards view is one drafting view in the model. It holds every rule
of the team, as the single source of truth. It is not an issue board.
An issue board tracks issues, status, and done work. A standards view
shows only what is proposed, and the open questions. It shows no status
and no history.

Use this recipe when the user asks for "standards view", "rules in the
model", "one view with all naming rules", or "single source of truth
for the team". Use am-issue-board for issues. Use am-safe-change for
other model changes.

## Create

1. Ask which view holds the standards view. Do not guess between views.
2. Make one text note per section. Give each section a fixed slot in
   two columns. Read the columns top to bottom, left column first, then
   right column. Do not read across rows. A table that does not fit in
   one column becomes a 2 x 2 grid.
3. Write the heading as the first line of the note: "Section N: Title".
   Make headings bold. Make body text regular. Keep one text style per
   part: heading, body, example. Do not mix bold body text with regular
   body text.
4. Find a note by its first line. Never find a note by element id. An
   element id can change. A first line stays.
5. Check that no notes overlap. Check that each note fits its slot.
   Use `capture_view` to confirm the layout.
6. For a table, use detail lines in a thin existing line style. Draw a
   frame per block. Draw one line between the code column and the name
   column. Draw one line under every row. Use the same style and the
   same paper spacing for every table in the view.
7. Pilot one section first. Get the user's approval of the style, with
   fixes. Then convert the other sections in the same style. Do not
   restyle all sections twice.

## Maintain

1. Before every edit, read the live layout. Read the live positions of
   the notes. Never reuse placement offsets from an earlier run. An
   earlier run can use an old layout.
2. Add a section: make one new note, in a free slot. Keep the column
   order.
3. Merge two sections: merge the text into one note. Remove the other
   note. Renumber the sections that follow.
4. Renumber sections: change each section number, and update every
   "see section N" reference. Use `renumber_sections` in
   `scripts/standards_view.py` (see "Check" below). A swap of two
   numbers must not cascade: "see
   section 1" and "see section 2" must trade places, not both become 2.
5. Repoint pointer notes in other views: a pointer note points to the
   standards view. Update its text when sections move. Delete old rule
   fragments only after the pointer notes point to the new view.
6. After every rewrite of a rule note, run a before/after word diff.
   Only format words may change: "ex:", colons, "=" signs, brackets
   around a list, and new column titles. If a content word changes,
   stop. Tell the user. A layout change must never change a rule.
7. Keep exceptions and placeholders out of table rows. A TBD row is an
   open item to resolve, not a rule. Put exceptions and placeholders
   under the table, after "Exceptions:". Each exception names the rule
   that it breaks.
8. Take examples from real names in the model. If no name in the model
   matches a rule, leave that example empty. Report the mismatch as a
   cleanup item. An empty example is a free compliance check.
9. If a note is gone, stop. Tell the user which note is gone. Do not
   recreate it silently. The user decides if it comes back.
10. If the user says a section looks cut off, do not say "nothing is
    clipped" from the stored text alone. Compare the stored text with
    what the user's screen shows. Ask for the zoom level. Then decide.

## Content rule: proposal only

The view shows only proposed rules and open questions. Never write
these in the view:

- "agreed", "agreement", "done", "renames done", "renamed",
  "completed", "in progress", "not renamed yet", "history".
- Dates, session names, run ids, progress notes.
- Status lines of any kind.

Write "proposed" for a rule that is not signed off. Write "TBD" for an
open question. Keep progress, dates, run ids, and session names in a
notes file outside the model.

Write a status only after a read-back from the model. Never write a
status from what a peer says it will do. A peer promise is not a fact
in the model.

## One writer

One session writes a view, or one session writes a section. Other
sessions read the view with `run_query` and send exact line changes.
They do not edit the view directly. Two writers on one layout will
break each other's placement scripts.

## Capture

Clear the selection before `capture_view`. If you do not clear it, the
changed elements show in the Revit selection color. Say in your report
that the color is not in the model. Do not let the user take it as a
style change.

## Check

`scripts/standards_view.py` holds pure logic. It runs under IronPython
2.7 in Revit, and under CPython 3 in tests. It never touches the model.

- `find_history_words(text)`: finds every forbidden word, with line
  numbers. Run it on every note before you finish. All notes must be
  clean.
- `check_notes(notes)`: checks a list of notes at once.
- `find_note_by_first_line(notes, first_line)`: finds a note by its
  first line. It returns None when the note is gone.
- `renumber_sections(sections, mapping)`: renumbers sections and
  updates every "see section N" reference.
- `word_diff(before, after, ignore)`: reports added and removed
  content words. Pass new column titles as `ignore`.

Run the tests with `python -m pytest -q tests` in this skill folder.
Model changes still need a dry run first and Keep/Discard approval in
Revit. Model changes follow am-safe-change.

## What this recipe does not do

This recipe does not verify a live Revit run. It does not check what
the user's screen shows. The "cut off" case still needs the user's
screenshot or zoom level. The home of this recipe is am-issue-board,
because it is close to the issue-board machinery: text notes in a
drafting view, found by text, edited in place.
