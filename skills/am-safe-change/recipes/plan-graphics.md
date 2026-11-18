# Checklist: plan graphics after a drawing change

Use this checklist after any change that draws on a plan or a sheet: route lines, symbols, tags, notes, new view templates. It comes from issue #256. One plan was reported done after a check "from a capture of the sheet". The user's review then found five defects.

A capture shows only what is on screen at that size. Read the model as well. Check each item below, and say in the summary which items you checked and how.

1. **Lines through walls.** A route or path line must not cross a wall, a glass partition or a door leaf. Intersect each new line with the walls and the doors in the view (read their location lines). List each crossing.
2. **Hidden subcategories.** A new view template copies the source template, including hidden subcategories. A symbol on a hidden subcategory does not show. For each new symbol, read its subcategory and the template's visibility of that subcategory.
3. **Lines that must not show.** Room separation lines, area boundaries, reference planes and scope boxes often show in a new template. Check their visibility in the new view.
4. **Overlaps.** New tags and notes must not overlap other tags, notes, dimensions or each other. Compare their boxes in the view (`get_BoundingBox(view)`). List each overlap.
5. **Note placement.** Each note sits next to the thing it describes, inside the crop region, and not on top of model lines. Name the element each note refers to.
6. **Markers from other views.** Section, elevation and callout markers of other views can make a viewport larger than its crop. Hide them in the new view when the user does not need them.
7. **Capture last.** Capture the view after the checks above, at a scale that shows the detail. Use the capture as a last visual check, not as the only check.

Report each item as "checked: <how>" or "not checked: <why>".
