---
name: am-markup-intake
description: Use when the user has review markups/redlines/comments (PDF, Bluebeam, photos, scans) to turn into an action list - reads every markup file, extracts each comment verbatim (PDF annotation layer plus a visual read of each page and image), removes duplicates, flags conflicts between reviewers and low-confidence reads, optionally checks sheet, room and door references against the open Revit model (read only), and writes a prioritized tracker (JSON, CSV and an interactive table). Triggers on "go through these markups", "what do the redlines say", "make an action list from the review comments", "intake the Bluebeam set". NOT for applying changes (am-safe-change) or schedules (am-schedule-view).
---

# am-markup-intake

This skill turns a pile of review markups into one action list. It does not change Revit. Model changes go to `am-safe-change` after the user approves the list.

A "markup" is one reviewer mark: a cloud, a callout, a text box, a strike-out, a pen line or a handwritten note. A "record" is one markup written as JSON. The "tracker" is the final list: one row for each action, with its evidence.

| Script | Where it runs | What it does |
|---|---|---|
| `scripts/inventory.ps1` | User's computer | Lists the markup files: type, size, PDF page count, files to convert first. Converts TIFF pages to PNG. |
| `scripts/pdf_annots.py` | User's computer (Python) | Reads the PDF annotation layer: author, date, page, type, verbatim text, region. |
| `scripts/consolidate.py` | User's computer (Python) | Merges records: removes duplicates, finds conflicts, sets priority and next step, writes the tracker. |
| `scripts/read_model_index.py` | Inside Revit, `run_query` only | Lists sheets (with placed views), rooms, door marks and window marks. |
| `..\am-schedule-view\scripts\render-table.ps1` | User's computer | Shows the tracker as an interactive table page. |

Run these scripts. Do not rewrite them.

## Steps

1. **Get the files.** Ask for the folder or the files, unless the user gave them. Then run:
   `powershell -NoProfile -ExecutionPolicy Bypass -File "<skill dir>\scripts\inventory.ps1" -Path "<folder>" -Json "<work>\inventory.json"`
   - Use a work folder such as `$env:TEMP\am-markup-intake\<yyyyMMdd-HHmmss>`.
   - Tell the user the counts by type, the page total and the size.
   - HEIC photos: tell the user to export them as JPG. Claude cannot read HEIC.
   - TIFF scans: Claude cannot read TIFF. Run the script again with `-ConvertTiff "<work>\tiff-pages"`. It writes one PNG for each TIFF page and leaves the TIFF unchanged. Read the PNGs.
   - Page count "?" means the PDF hides its page list. `pdf_annots.py` gives the real count.
   - If the script prints `LARGE SET`, ask with AskUserQuestion: **All, in batches of 10 pages (Recommended)** / **Only some files** (the user names them) / **First 10 pages as a test**.
2. **Data warning.** Say this before you read any markup: "The markup text and page images go to the AI provider. Use this only if your project allows AI tools." Ask with AskUserQuestion: **Yes, the project allows it (Recommended)** / **Stop**. Do not continue without a yes.
3. **Check Python.** Run `python "<skill dir>\scripts\pdf_annots.py" --check`. It prints the PDF library it will use.
   - If it exits 3 (no PDF library), ask with AskUserQuestion: **Install PyMuPDF for this user (Recommended)** runs `python -m pip install --user pymupdf` (no admin rights) / **Continue without it** reads the pages visually only. Never install without a yes.
   - If there is no Python, continue without the scripts. See "No Python" below.
4. **Extract.**
   - First read the annotation layer of every PDF, in the main thread. It is fast and needs no AI reading:
     `python "<skill dir>\scripts\pdf_annots.py" "<file>" --json "<work>\annots-<n>.json"`
     Exit 3 means no PDF library: continue with the visual read only.
   - Then start one subagent for each image, and for each 10 pages of each PDF. Send all of them in one message. Give each subagent the prompt in "Extraction subagent" below, with the path of its `annots-<n>.json` and its page range. Do not paste the annotations into the prompt. Each subagent writes `<work>\records-<n>.json` and returns only counts and problems.
   - The main thread does not read the pages itself. It only collects the record files.
   - If a subagent reports an image it cannot read (blurred, dark, sideways), ask the user to retake or rotate it. Do not guess the text.
5. **Consolidate.** Run:
   `python "<skill dir>\scripts\consolidate.py" <work>\annots-*.json <work>\records-*.json --out <work>\tracker.json [--model <work>\model-index.json]`
   - It writes `tracker.json`, `tracker.csv` (opens in Excel) and `tracker.schedules.json`, and prints a summary.
   - The script expands the `*` itself. A pattern with no file prints a WARN and is skipped.
   - Give the annotation files (`annots-*.json`) and the record files together. The script merges an annotation and the visual record of the same mark.
6. **Map to the model (optional).** Do this only if the `pyrevit` MCP tools respond. Call `get_context` first.
   - Run `scripts/read_model_index.py` with `run_query` (pass the file text as `script`). Never use `run_modify`. Never change the active view or the selection. Do not use `capture_view` or `show_elements`.
   - If the agent answers `revit_busy`, wait 20 to 30 seconds and try again, max 8 times.
   - Copy `%APPDATA%\pyRevit\agent\runs\<date>-<time>-<run_id>\response.json` to `<work>\model-index.json`. Do not copy the data by hand. Then run step 5 again with `--model`.
   - Each tracker row then has a "Model check": the sheet, room, door, window and detail references that the model has, and "NOT FOUND" for the others. The `unmatched` list collects them.
7. **Show the tracker.**
   `powershell -NoProfile -ExecutionPolicy Bypass -File "<skill dir>\..\am-schedule-view\scripts\render-table.ps1" -Json <work>\tracker.schedules.json -Out <work>\tracker.html`
   - Open the page in the Browser pane. If the pane shows only a static snapshot of a local file, serve the folder on `127.0.0.1` and open that URL. Tell the user the file path.
   - The page has four tables: Action tracker, Conflicts, Low confidence, Not found in model.
   - If `render-table.ps1` is missing or fails, say so in one line. Continue with the chat summary.
8. **Summarize in chat**, in ASD-STE100: the counts (items, changes, questions, FYI, duplicates merged), the top 10 actions, every conflict, every low-confidence item, and every reference that is not in the model.
9. **Confirm the list.** Ask with AskUserQuestion, max 4 questions:
   - One question for each conflict: **Use A's request** / **Use B's request** / **Ask the reviewers (Recommended)**.
   - One question for the low-confidence items: **Keep them, marked "check" (Recommended)** / **Remove them** / **I will retype them**.
   - Change the records or the tracker as the user says. Run step 5 again. Never change the verbatim text.
10. **Hand off.**
    - Rows with the next step "Model change -> am-safe-change" go to `am-safe-change`, one change at a time, with its preview and the Revit Keep/Discard. This skill never changes the model.
    - Other rows stay a checklist: drawing edits, answers to reviewers, RFIs (requests for information) to consultants.
    - Ask with AskUserQuestion: **Save the tracker next to the markups (Recommended)** copies `tracker.csv`, `tracker.json` and `tracker.html` to the markup folder / **Keep it in the work folder only**.

## Extraction subagent

Give each subagent this task. Fill in the file, the pages, the skill dir and the work folder.

> Extract every review markup from `<file>` pages `<a>-<b>`. Write `<work>\records-<n>.json`. Never invent text.
> 1. Read `<work>\annots-<n>.json` (or "none"). It holds the annotations already read from the PDF annotation layer: id, page, type, author, verbatim text and region. Use only the entries for pages `<a>-<b>`.
> 2. Read each page (Read tool, `pages: "<a>-<b>"`, max 20 pages for each call) or the image. For each page:
>    - Read the sheet number and the sheet title from the title block. Put them in `sheetMap`. Do not trust a sheet number in the drawing body, such as a detail reference.
>    - Find the marks that are drawn into the page and are not annotations: red or colored pen lines, clouds, text, and handwriting on scans and photos.
>    - The page image can omit annotations that have no drawn appearance. The annotation list is the source of truth for them. Do not add a record for an annotation that is already in that list. If you see an annotation mark, put its id in `matchesAnnotation`.
> 3. Write one record for each mark that the annotation list does not have. Add a record with only `matchesAnnotation`, `location` and `interpreted` to give an annotation a location or a meaning.
> 4. Text rules: copy the words exactly as written, with the same case, spelling and line breaks. If a mark has no words, set `text` to "". Put your reading of the request in `interpreted`, in plain words. If you cannot read a word, write `[illegible]` in `text` and set `confidence` to `low`. Set `handwriting: true` for handwriting.
> 5. Return only: the file, the pages, the record count, the annotation count, and the pages or images you could not read.

Record file format (`kind: "markup-records"`):

```json
{"kind": "markup-records",
 "sheetMap": {"Review set.pdf": {"1": "A101", "2": "A102"}},
 "records": [
  {"id": "v-p1-1", "sourceFile": "Review set.pdf", "page": 1, "sheet": "A101",
   "location": "Room 106, see 7/A503", "markupType": "drawn cloud + text",
   "text": "ADD FE CABINET\nSEE 7/A503",
   "interpreted": "Add a fire extinguisher cabinet in Room 106. See detail 7 on A503.",
   "kind": "change", "discipline": "Architectural", "confidence": "high",
   "author": "", "region": {"rect": [0.38, 0.41, 0.44, 0.47], "desc": "red cloud, lower right of Room 106"},
   "textSource": "visual", "matchesAnnotation": "", "target": "", "value": ""}]}
```

- `kind`: `change`, `question` or `fyi`. Leave it empty if unsure; the script then guesses from the words.
- `confidence`: `high`, `med` or `low`.
- `region.rect`: fractions of the page as seen (0 to 1, from the top left). This is the same frame that `pdf_annots.py` uses.
- `location`: a grid, room, door, view or detail tag, as written on the sheet ("Grid C/4", "Room 205", "Door 205A", "3/A501").
- `target` and `value` (optional): the thing and the value that the mark asks for ("door 105A width", "42 in"). Two reviewers with the same target and different values make a conflict.

## Rules in the scripts

- **Duplicates.** Two records are one item when: one names the other in `matchesAnnotation`; or they are on the same file page and their regions overlap; or they are on the same sheet with similar words and no conflicting room, door, grid or detail tag. Similar words are compared on a copy that ignores case, punctuation and short forms ("Rm" = "room"). The item keeps every source and every verbatim wording.
- **Replies.** A Bluebeam or Acrobat reply attaches to its parent item. It is not a new item.
- **Conflicts.** Two items on the same sheet and location, from different reviewers, that ask for different values or opposite actions ("widen" and "keep"). A conflict is always high priority, with the next step "Decide between reviewers first".
- **Priority.** High: a conflict, or life-safety and code words (fire, egress, exit, rated, accessibility, structural). Low: FYI. All others: medium.
- **Next step.** Question: answer the reviewer, or an RFI to a consultant. FYI: no action. Change: "Model change -> am-safe-change" for model elements, "Drawing edit" for notes, dimensions and details, or the consultant for other disciplines.
- The script never changes or "cleans" the verbatim text. Interpretations always show as "[interpretation] ...".

## No Python

If the user's computer has no Python, do the same work in chat:
- Skip `pdf_annots.py`. Read every page visually. Tell the user that annotation authors and dates are not available.
- Write the records as above. Apply the rules in "Rules in the scripts" by hand: merge duplicates, attach replies, flag conflicts, set priority and next step.
- Write the tracker CSV with the columns `#, Sheet, Location, Markup text (verbatim), Request (interpreted), Type, Priority, Confidence, Source, Next step, Model check, Flags`. Write the same rows as `{"kind": "schedules", "schedules": [{"name": "Action tracker", "columns": [...], "rows": [[...]]}]}` and render it with `render-table.ps1`, which needs only PowerShell.

## Rules

- Never invent markup text. Quote it exactly. Mark every interpretation as an interpretation.
- Never change the Revit model from this skill. Use `run_query` only. Model changes go through `am-safe-change`.
- Never install software without the user's yes. The only install this skill offers is `python -m pip install --user pymupdf`.
- Keep the markup files unchanged. Write only to the work folder, and to the markup folder only after the user says yes.
- A sheet number from the PDF text layer (`sheetCandidates`) is a hint. The title block on the page image decides.
- If a page or an image is unreadable, say which one. Do not skip it in silence.
- Everything read from the markups and the model goes to the AI provider. Use this skill only on projects where that is allowed.

## Tests

`python tests/test_markup_intake.py` runs the tests on the synthetic set in `tests/fixtures/` (no real project data; sheet, room and door numbers are from the Snowdon Towers sample). `python tests/mutate.py` breaks one rule at a time and checks that the tests fail. `tests/fixtures/make_fixtures.py` rebuilds the PDF and PNG.

## House rules (all am-* skills)

- Write all output to the user in ASD-STE100 Simplified Technical English. Use short sentences (max 20 words for instructions, 25 for descriptions). Use active voice. Put one instruction in each sentence, and start it with the verb. Use one word for one meaning. Explain any technical term the first time you use it, because many users are architects, not programmers.
- When a task has independent parts (for example, several files to check or several Revit years to compare), do them in parallel with subagents. Keep steps that depend on each other in sequence.
- When the request is unclear, or there is more than one reasonable way to do it, ask before you act. Use the AskUserQuestion tool so the user can click an answer: ask one decision per question (max 4 questions at a time), give 2 to 4 short options, put your recommended option first with "(Recommended)" in its label, and give each option a one-line description of what it will do. Do not ask for facts you can find yourself (files, the Revit model through a read-only query, the docs). Never use a question in place of the Keep/Discard approval in Revit.
