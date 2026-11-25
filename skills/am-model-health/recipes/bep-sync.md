# Recipe: keep a BIM execution plan in step with the model

A BIM execution plan (BEP) is a document that states facts about the model: the file name, the central path, worksharing, the Revit build and the naming rules. These facts change when the team renames the model or moves a folder. This recipe reads the facts from the live model and checks the document against them.

Every step is read-only. No step changes the model or the document.

## When to use

- The user asks "what is the exact model file name and central path?".
- The user wants the naming rules from a reference drafting view as text or a table for the BEP.
- The user asks "is the BEP still correct?" or "does the BEP name the old model?".

## Before you start

- The steps return raw model paths, file names and note text. Use them only where the project allows sending those details to the AI provider. Ask the user if you are not sure.
- Keep every output file in a private working folder on the user's computer. Never commit or post it.
- One Revit serves one agent session. If another session holds Revit, ask that session or the user to run steps 1 and 2.

## Steps

| Step | What it gives | Skill and section | Needs Revit |
|---|---|---|---|
| 1. Model facts | One JSON block: file name, current, central and cloud paths, worksharing, Revit year and build, workset counts, linked models with paths and status | `am-model-health`, "Model facts for a BIM execution plan" (`scripts/read_model_facts.py`) | Yes, read only |
| 2. View notes | All text notes of one drafting view, in reading order (top to bottom, left to right), grouped under heading notes | `am-shared-text-check`, "Export all drafting-view notes" (`scripts/read_shared_text.py` with `export_view: true`) | Yes, read only |
| 3. Document check | File and folder names in a local `.docx` that do not match the facts from step 1 | `am-markup-intake`, "Compare a local BIM execution plan with Revit model facts" (`scripts/bep_document_cli.py`) | No |

1. Run step 1. Save the complete JSON to the private folder, for example `model-facts.json`. Use the identity it returns (`path`, `project_uid`) in step 2.
2. Run step 2 only when the BEP quotes rules from a view. Ask the user which notes are headings, then pass their IDs as `heading_ids`. Check `inventory_complete` and `visual_order` before you use the order in a document.
3. Run step 3 with the `.docx` and the JSON from step 1. Exit code 1 means the document names a file or folder that is not in the live model. Show each mismatch with its document location and excerpt.
4. Give the user a short list: the correct values, and each place in the document to fix. Let the user edit the document. Do not edit it yourself unless the user asks.

## Notes

- Run the steps again after each rename, move or Revit upgrade. The facts from an old run are not proof of the current state.
- The facts query reports the build of the running Revit application, not the build that last saved the file.
- A text box, a tracked change or a merged table cell in the `.docx` can hide a name from step 3. The check reports this as incomplete coverage.
