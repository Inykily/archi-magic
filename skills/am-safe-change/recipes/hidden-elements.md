# Diagnose and clear visibility hides in Revit

Use the active graphical view. Select the scope by element IDs or up to five top-level model or annotation category IDs. Document-level discovery includes elements that the active view collector can omit.

1. Call `get_context` and `get_skill("revit-scripting")`. Run `scripts/hidden_elements.py` with `run_query` and the scripts directory as `workspace`. Use `{"scope":{"element_ids":["101","102"]}}` or `{"scope":{"category_ids":["-2000011"]}}`.
2. Save the full result as `read.json`. Use `get_run` if truncated. Run `python hidden_elements_preview.py report read.json` from the scripts directory. Report direct hides, category settings, matching filters in order, and template sources. Explain ignored items and unknown evidence.
3. For direct unhide, create `intent.json` with `{"kind":"element","ids":["101"]}`. Choose only elements with a confirmed direct hide.
4. For a whole-view category or filter change, read the scope again. Add `"whole":{"kind":"category","id":"-2000011"}` or use `"kind":"filter"` with the exact filter ID. Review the potential impact list. The setting applies to current and future members. It can affect view content beyond the reviewed elements. Set `"allow_whole_view":true` in the intent only after that review. Template-controlled settings require separate template review.
5. Run `python hidden_elements_preview.py compute read.json intent.json preview.json`. Follow am-safe-change ownership and approval. The active view is the write target.
6. Run the same native script with `run_modify` and `dry_run:true`. Supply `{"mode":"apply","plan":<preview.json contents>}`. Save the full runtime result as `dryrun.json`. Run `python hidden_elements_preview.py side-effects preview.json dryrun.json`.
7. Read the original scope again and save `fresh.json`. Run `python hidden_elements_preview.py baseline preview.json fresh.json`. Stop on any mismatch or missing telemetry. Use the same approved plan for the real run. Follow Keep or Discard. Under auto policy, obtain the second approval after the dry run.
8. Read the same scope after Keep. Run `python hidden_elements_preview.py compare preview.json kept-read.json`. After Discard, run the baseline check on a fresh read. Verify visible elements separately in Revit.

The report covers configured host-view hides. Other conditions can still hide an element. It does not assess linked geometry, imports, temporary overrides, or rendered visibility.
