# Session feedback: detail section from a marked-up screenshot to a new sheet

Source: one live session (Revit 2026.4, pyRevit 7.0.0.26278, large workshared model).
Project and user names are left out on purpose.

## The task

The user pasted a plan screenshot with a green line (section cut plus arrow) and a red dash-dot line. They asked: "connect to Revit, create a section detail at those locations, place on a new sheet, assign the template like the other detail views." They also asked the agent to ask questions first.

Result: one detail-type section, view template applied, new sheet created, view placed. The user confirmed the position. About 8 tool calls to Revit, 2 of them writes (a dry run and the commit).

## What worked

- **Questions first, four at once.** Which lines are sections, which way they look, where the template comes from, how to set up the sheet. One round, then no more interruptions. The answers "find it yourself" and "match neighbours" moved the work to the agent, which is where it belongs.
- **Learning the house style from the model.** The agent counted the view templates used by existing Detail views, read the neighbouring sheet (title block, series, group, order) and picked the next free sheet number. Nothing was hard-coded.
- **Dry run before commit.** The dry run caught nothing wrong here, but it gave a change set (view, sheet, title block, viewport) the user could trust.
- **Capture to verify.** `capture_view` on the new view showed real content, so the section was not empty or on the wrong level.

## Gaps and friction

1. **No skill covers "detail view from a plan marker".** `create.create_section_view` makes a Section-family view. The house detail views are Detail-family (`ViewFamily.Detail`), so the agent fell back to raw `ViewSection.CreateDetail(doc, type_id, BoundingBoxXYZ)`. The box transform (BasisX along the cut, BasisY up, BasisZ opposite the look direction) is easy to get wrong. A tested helper would remove the risk.
2. **Screenshot markup is not in the model.** The green line existed only in the user's image. The agent estimated the position from the one model line it could see (the red dash-dot line, 13.75 ft long) to get a pixel-to-foot scale. It works, but the result is approximate and the user has to be told so. A better flow: ask the user to drop a detail line or a reference point, or snap to a named element, or confirm the estimate with a capture overlay before any write.
3. **`Name` on a ViewFamilyType fails in IronPython.** `t.Name` raised `AttributeError: Name`. `DB.Element.Name.GetValue(t)` works. Related to existing issue 6 (`ElementId.IntegerValue` is gone in 2026, use `.Value`). Both cost a retry.
4. **`capture_view` takes a view name, not a sheet number.** `view="A-477"` returned `view_not_found`. The sheet name or id is needed. Worth a line in the views and drawings guidance, or accept sheet numbers in the tool.
5. **Choosing a template is a judgment call.** Detail views in the model used about 30 different templates. The agent chose the one used by the most recent sheet in the same area. It should say so and show the runner-up templates so the user can swap in one step.
6. **Large "added" counts after a dry run.** The preview listed 24 added elements (work plane grid, sun path, schedule graphics) for one view and one sheet. This matches the existing issue about separating "edited" from "regenerated". Group the preview by what the user asked for.
7. **Sheet open and jump links.** The user wanted a one-click jump to the new sheet. `ui.request_view_change(sheet)` in `run_query` does it. This should be the standard last step after creating a sheet, plus a "reopen" button in the wrap-up.

## Proposals

- **New skill or recipe `am-detail-sheet`** (write through `am-safe-change`):
  1. Ask the four questions above in one round.
  2. Find the Detail view family type and the template by counting what existing Detail views use. Show the top 3.
  3. Resolve the cut location. Prefer a model element or a user-placed line. If from a screenshot, say it is an estimate and capture it for confirmation.
  4. Create the view with `CreateDetail`, set name and template.
  5. Create the sheet from the neighbour's title block, copy its series, group, order and revision parameters, pick the next free number.
  6. Place on the sheet, capture the view, open the sheet.
- **Add to `am-revit-api-docs`:** `Element.Name.GetValue` for types in IronPython, and the Detail vs Section view-family difference.
- **Add to `am-safe-change`:** a "new view plus new sheet" preview that lists the created view, the sheet and the viewport on three lines and hides the regenerated helper elements.
- **Pre-flight note:** the open document may have unsynced changes. Tell the user after a commit that nothing was synchronised with central.

## Done when

A user can say "make a section detail here and put it on a new sheet like the others" and get the same result without the agent rediscovering `CreateDetail`, the box transform, or the template choice.
