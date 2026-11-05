# RFC 003: MEP Support Architecture (Issue #186)

- **Author**: archi-magic architecture team
- **Status**: Phase 0 Scoping Approved
- **Target Milestones**: Phase 0 (Scoping & Go/No-Go) -> Phase 1 (Read-Only MEP QA) -> Phase 2 (Safe Parameter Adjustments) -> Phase 3 (Assisted Routing & Sizing)

## 1. Context and Problem Statement
archi-magic historically focused on architectural standards, rooms, doors, schedules, and geometry cleanup. Architectural teams routinely coordinate linked MEP models, detect service clearances, and audit consultant submissions. In integrated firms, in-house mechanical, electrical, and plumbing designers also require automated verification of distribution systems.

## 2. Scoping and Stakeholder Analysis (Phase 0)

| Dimension | Primary Focus (Architectural Coordination) | Secondary Focus (In-House MEP Design) |
|---|---|---|
| **Target Users** | BIM Managers, Project Architects, Coordinators | Mechanical / Electrical / Plumbing Engineers |
| **Primary Need** | Clearance checks, system classification consistency, unhosted terminals, penetrations | Open connector detection, flow continuity, duct/pipe sizing calculations |
| **First Workflow** | Non-invasive MEP QA audit with findings exported to `am-issue-board` | Parameter standardization across system categories |
| **Success Metric** | 0 unflagged clash clearances; 100% connector audit coverage on MEP links | Automated detection of 100% unconnected ends |
| **Go / No-Go Decision** | **GO**: Proceed with Phase 1 read audits and Phase 2 safe edits | **Deferred**: Complex hydraulic/aerodynamic CFD sizing remains with native Revit engines |

## 3. Phased Implementation Roadmap

### Phase 1: Read-Only MEP QA Audits (Target for Initial Release)
- **Connector Continuity Check**: Traverse MEP connectors (`ConnectorManager`) across ducts, pipes, conduits, and fittings to detect open/disconnected ends (`MEP-CON-01`).
- **System Classification & Naming**: Verify that all mechanical equipment, air terminals, and fixtures belong to assigned systems (`Supply Air`, `Return Air`, `Domestic Cold Water`) and match naming rules.
- **Service Clearance Envelope Validation**: Compute bounding clearance envelopes around equipment requiring maintenance access (e.g. 36" electrical clearance, filter pull zones, VAV box access) and test against architectural ceilings and partitions (`MEP-CLR-01`).
- **Penetration Candidate Detection**: Flag MEP runs penetrating fire-rated architectural assemblies lacking sleeve or opening families (`MEP-PEN-01`, coordinating with Issue #152).
- **Issue Board Integration**: Send all identified violations directly to `am-issue-board` with element IDs, system names, and 3D XYZ coordinates.

### Phase 2: Safe Parameter Standardization
- **Bulk System Assignment**: Assign unallocated duct/pipe runs to designated systems using verified recipes.
- **Elevation and Offset Standardization**: Standardize invert and centerline elevations across runs.
- **Pre-execution Preview**: Compute a parameter delta table via `am-safe-change` before any database modifications.

### Phase 3: Assisted Routing and Sizing
- **Assisted Routing**: Suggest connection routes between two open connectors with standard 45°/90° elbows, avoiding architectural bounding obstacles.
- **Rule-Based Sizing**: Suggest cross-sectional duct/pipe dimensions based on lookup velocity or friction tables.
- **Safety Guarantee**: Every geometry routing transaction is wrapped in an `am-safe-change` dry-run transaction. Users inspect changes visually in 3D and must confirm via the native Revit Keep/Discard dialog.
