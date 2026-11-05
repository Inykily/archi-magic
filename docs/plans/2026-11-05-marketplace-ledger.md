# archi-magic: Marketplace Feature Ledger & Roadmap (2026-11-05)

Ledger tracking the 50 enhancement ideas surfaced from the scan of 1,672 public Revit add-in listings on Autodesk App Store (Issue #178), combined with the platform enhancement epics (#179 to #188).

Demand rating reflects cumulative user reviews from similar commercial and free add-ins.

---

## 1. Executive Summary & Delivery Status

| Wave / Tier | Total Ideas | Delivered / In Branch | RFC Scoped | Backlog |
|---|---|---|---|---|
| **Platform Epics (#179–#188)** | 10 | 4 (#179, #180, #183, #184) | 3 (#186, #187, #188) | 3 (#181, #182, #185) |
| **Tier P1 (#128–#137)** | 10 | 9 (#128, #129, #130, #131, #133, #134, #135, #136, #137) | - | 1 (#132) |
| **Tier P2 (#138–#157)** | 20 | 0 | - | 20 |
| **Tier P3 (#158–#177)** | 20 | 1 (#176) | 1 (#166 via RFC 001) | 18 |
| **Total** | **60** | **14** | **4** | **42** |

---

## 2. Platform Epics Ledger (#179 to #188)

| Issue | Title | Category | Target Skill | Status | Delivery Artifacts |
|---|---|---|---|---|---|
| #179 | Recipe library: save agent runs as versioned recipes | Platform | `am-safe-change` | **Delivered** | `scripts/recipe_library.py`, `tests/test_recipe_library.py`, fast-path docs |
| #180 | Check packs: team-authored rules with severity | Platform | `am-issue-board` | **Delivered** | `scripts/check_packs.py`, `tests/test_check_packs.py`, built-in packs |
| #181 | Spec sheet PDF to parametric family | Intelligence | `am-markup-intake` | Backlog | Planned subagent pipeline |
| #182 | Use project documents as task input (ACC, SharePoint, Excel) | Integration | `am-markup-intake` | Backlog | Planned document connector |
| #183 | Model version compare: what changed since date/sync | Safety | `am-safe-change` | **Delivered** | `scripts/model_compare.py`, `tests/test_model_compare.py`, diff docs |
| #184 | Local time-saved log and ROI report | Doctor / Value | `am-doctor` | **Delivered** | `scripts/time_log.py`, `tests/test_time_log.py`, CLI commands |
| #185 | Narrated screen recordings as task input | Intelligence | `am-markup-intake` | Backlog | Video framing and Whisper/multimodal parser |
| #186 | Epic: MEP support (routing, sizing and MEP QA) | Epic | `am-issue-board` / new | **Phase 1 delivered** | RFC 003 + `am-issue-board/scripts/mep_qa.py`. Phases 2-3 open |
| #187 | Epic: Web workspace (projects, previews, issue board) | Epic | `am-bim-viewer` / web | **Phase 1 started** | RFC 002 + `am-bim-viewer/scripts/project_page.py`. Phases 2-3 open |
| #188 | Epic: AutoCAD support (read and write DWG) | Epic | CAD connector | **Phase 1 delivered** | RFC 001 + `am-model-health/scripts/dwg_cad_audit.py`. Phases 2-3 open |

---

## 3. Tier P1: High Demand & Immediate Fit (#128 to #137)

| Issue | Title | Demand (Reviews) | Target Skill | Status | Implementation Details |
|---|---|---|---|---|---|
| #128 | Excel round trip for schedules with safe write-back | 233 | `am-schedule-view` | **Delivered** | `scripts/schedule_roundtrip.py`, CSV export/import, read-only field locks, test suite |
| #129 | Natural-language element selection | 101 | `am-revit-api-docs` | **Delivered** | Selection recipe with filtered collector and `show_elements` highlight |
| #130 | Join geometry by rules with a preview | 130 | `am-safe-change` | **Delivered** | Hierarchy rule join recipe with `JoinGeometryUtils` and preview |
| #131 | Renumber any category by pick order, path or location | 82 | `am-safe-change` | **Delivered** | Coordinate and path renumbering recipe with collision prevention |
| #132 | Room finishing: floors, walls and ceilings from rooms | 101 | `am-safe-change` | Backlog | Boundary geometry extraction to boundary layer creation |
| #133 | Auto tag untagged elements in views | 63 | `am-revit-api-docs` | **Delivered** | IndependentTag collector recipe with duplicate detection |
| #134 | Align and distribute tags, text and elements | 159 | `am-revit-api-docs` | **Delivered** | Coordinate alignment and bounding-box distribution recipe |
| #135 | Publish-set preflight before export | 286 | `am-model-health` | **Delivered** | `scripts/publish_preflight.py`, 4 preflight checks, markdown report, test suite |
| #136 | Bulk-bind shared parameters to categories | 111 | `am-param-qa` | **Delivered** | Category binding recipe with `CategorySet` and `SharedParameterElement` |
| #137 | Transfer standards between open models | 85 | `am-safe-change` | **Delivered** | Multi-document copy recipe using `ElementTransformUtils.CopyElements` |

---

## 4. Tier P2: Clear Demand & Good Fit (#138 to #157)

| Issue | Title | Demand (Reviews) | Target Skill | Status |
|---|---|---|---|---|
| #138 | Revision management: add revisions to many sheets and report clouds | 49 | `am-schedule-view` | Backlog |
| #139 | Warnings triage with fixes and issue-board hand-off | 35 | `am-issue-board` | Backlog |
| #140 | Model cleanup plan: purge unused views, templates, scope boxes and CAD | 46 | `am-model-health` | Backlog |
| #141 | Color-by-parameter view filters | 23 | `am-param-qa` | Backlog |
| #142 | Copy view filters and overrides between views and templates | 23 | `am-safe-change` | Backlog |
| #143 | Batch duplicate views with a template and a name rule | 41 | `am-safe-change` | Backlog |
| #144 | Place many views on sheets and replicate legends | 26 | `am-schedule-view` | Backlog |
| #145 | Create sheets from a list with title block values | 29 | `am-schedule-view` | Backlog |
| #146 | Auto-dimension grids, walls and openings | 26 | `am-revit-api-docs` | Backlog |
| #147 | Door and window type legends generated from the model | 40 | `am-schedule-view` | Backlog |
| #148 | BCF import and export for am-issue-board | 123 | `am-issue-board` | Backlog |
| #149 | Review Navisworks clash results inside Revit | 38 | `am-issue-board` | Backlog |
| #150 | Linked-model manager: report, path check and reload plan | 47 | `am-model-health` | Backlog |
| #151 | Split walls, floors and columns by level or grid | 52 | `am-safe-change` | Backlog |
| #152 | Openings and sleeves where MEP crosses walls and floors | 24 | `am-safe-change` | Backlog |
| #153 | Family library search and place | 87 | `am-revit-api-docs` | Backlog |
| #154 | Quantity and material takeoff report | 17 | `am-area-report` | Backlog |
| #155 | Embodied carbon quick estimate from materials | 13 | `am-material-audit` | Backlog |
| #156 | Code-check helpers: occupancy load and egress width | 4 | `am-area-report` | Backlog |
| #157 | Architecture vs structure mismatch check | 16 | `am-issue-board` | Backlog |

---

## 5. Tier P3: Narrower or Strategic Scope (#158 to #177)

| Issue | Title | Demand (Reviews) | Target Skill | Status | Notes |
|---|---|---|---|---|---|
| #158 | Zoom, section box and focused 3D view from selection | 62 | `am-bim-viewer` | Backlog | Quick view isolate |
| #159 | Find hidden elements and unhide them | 17 | `am-revit-api-docs` | Backlog | View query helper |
| #160 | Interior elevations and sections per room | 30 | `am-safe-change` | Backlog | Room marker generator |
| #161 | Copy a parameter value to another parameter | 15 | `am-param-qa` | Backlog | Parameter copy recipe |
| #162 | Spreadsheet-style bulk parameter editor | 28 | `am-param-qa` | Backlog | Aligns with #128 schedule roundtrip |
| #163 | Transfer parameters between families | 18 | `am-param-qa` | Backlog | Family definition copier |
| #164 | Family preview image generator | 20 | `am-bim-viewer` | Backlog | Thumbnail batch exporter |
| #165 | Batch load families and create types from a table | 13 | `am-safe-change` | Backlog | Family type generator |
| #166 | CAD-to-BIM: walls, doors and rooms from DWG layers | 46 | CAD connector | **RFC Approved** | Scoped in `docs/rfcs/001-autocad-support.md` (Phase 3) |
| #167 | Topography helpers: align to elements and convert to floors | 22 | `am-safe-change` | Backlog | Toposolid helpers |
| #168 | Match offset, rotation and reference level | 28 | `am-safe-change` | Backlog | Transform match recipe |
| #169 | Create levels and grids from a list | 5 | `am-safe-change` | Backlog | Datum creation tool |
| #170 | Keynote file editor and keynote check | 12 | `am-issue-board` | Backlog | Keynote table validator |
| #171 | Spell check and standard wording for text notes | 8 | `am-shared-text-check` | Backlog | Text note dictionary check |
| #172 | Wall and floor type legend and schedule | 8 | `am-schedule-view` | Backlog | Legend generator |
| #173 | Linked element inspector | 15 | `am-revit-api-docs` | Backlog | Link query tool |
| #174 | Batch process many models | 40 | `am-doctor` | Backlog | pyRevit batch script generator |
| #175 | Modelling effort log from journals | 50 | `am-doctor` | Backlog | Journal parser |
| #176 | Revit backup file cleanup | 17 | `am-doctor` | **Delivered** | `scripts/cleanup_backups.py`, scan, archive, delete, test suite |
| #177 | Positioning: list archi-magic as MCP app on Autodesk store | 54 | Docs / Distribution | Backlog | Listing package |
