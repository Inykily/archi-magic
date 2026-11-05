# RFC 001: AutoCAD and DWG Support Architecture (Issue #188)

- **Author**: archi-magic architecture team
- **Status**: Phase 0 Scoping Approved
- **Target Milestones**: Phase 0 (Scoping) -> Phase 1 (Read Audits) -> Phase 2 (Safe Edits) -> Phase 3 (CAD-to-BIM)

## 1. Context and Problem Statement
archi-magic currently interfaces with Revit and Rhino. Many architectural office workflows continue to exchange and reference 2D/3D DWG drawings from civil, structural, and MEP consultants, as well as legacy detail libraries. Users require reliable, safe DWG inspection, layer audits, xref validation, and write-back capabilities.

## 2. Connection Path Evaluation (Phase 0)

| Option | Method | Pros | Cons | Recommendation |
|---|---|---|---|---|
| **A. In-process .NET / ObjectARX** | C# / C++ plugin loaded in running AutoCAD | Full access to AutoCAD database, transactions, and UI | Requires AutoCAD license and active running instance | **Adopt for Phase 2** (Interactive edits with Keep/Discard) |
| **B. Headless Python library (`ezdxf`)** | Direct DXF/DWG file parsing in Python | Headless, zero license cost, runs in background tasks | Direct binary DWG write requires conversion (e.g. ODA File Converter or DXF intermediate) | **Adopt for Phase 1** (Fast headless read audits) |
| **C. Windows COM Automation** | `win32com` / pyautocad | Simple scripting, drives AutoCAD window | Fragile across versions, modal dialogs block COM calls | Rejected |

### Decision
- **Read-only audits (Phase 1)** use headless Python parsing (`ezdxf` with DXF/ODA conversion) for instant layer, xref, block, and unit audits without launching AutoCAD.
- **Interactive modifications (Phase 2)** use a lightweight `.NET` agent connector running inside AutoCAD, adhering strictly to the `am-safe-change` model: change preview, dry-run, and explicit Keep/Discard prompt in the AutoCAD viewport.

## 3. Phased Implementation Roadmap

### Phase 1: Read-Only DWG Audits
- **Layer Standards Audit**: verify layer naming against office or project conventions (e.g. AIA CAD Layer Guidelines: `A-WALL`, `A-DOOR`), color, and linetype standards.
- **Xref Inspector**: extract all external reference paths, detect broken/unresolved links, and report circular references.
- **Block & Attribute Inventory**: count title block instances, verify attribute fill completeness, and detect unpurged anonymous blocks.
- **Scale and Units Verification**: check `$INSUNITS` and `$MEASUREMENT` to detect unit mismatches before linking to Revit.

### Phase 2: Safe Edits with Explicit Approval
- **Layer Mapping and Renaming**: compute old/new layer mapping with preview table.
- **Xref Path Repathing**: repath absolute network drive letters to relative or cloud-synchronized paths.
- **Purge Candidates**: identify and purge unused layers, blocks, dimension styles, and empty text notes.
- **Safety Rule**: No DWG modification is written directly without dry-run comparison and explicit user approval in the CAD viewport.

### Phase 3: CAD-to-BIM Hand-off (Issue #166)
- Map approved DWG layers to native Revit elements (walls from `A-WALL`, doors from `A-DOOR`, rooms from boundary polylines).
- Export verified Revit schedules and sheet views back to clean, standardized DWG backgrounds.
