# Verification report - widget_b

- Manifest: `portability.json` sha256 `7f5059deb11adae0`
- Constraint version: `widget-b-v1`
- KiCad: `10.0.5`
- Generated: 2026-08-04T12:04:58.174254+00:00

## Verdict: **ACCEPTED**

| Status | Gates |
|---|---:|
| PASS | 10 |
| NOT_APPLICABLE | 14 |

## Gate matrix

| Gate | Status | Detail |
|---|---|---|
| `ARCH.CONTENTS` | NOT_APPLICABLE | manifest does not declare archive.allow, archive.zip; this board does not opt in to this gate |
| `ARCH.PROVENANCE` | NOT_APPLICABLE | manifest does not declare archive.manifest; this board does not opt in to this gate |
| `BOM.NATIVE_PARITY` | NOT_APPLICABLE | manifest does not declare artifacts.bom, artifacts.cpl; this board does not opt in to this gate |
| `CFG.NO_RIVAL_THRESHOLDS` | NOT_APPLICABLE | manifest does not declare constraint_parity.rival_scan; this board does not opt in to this gate |
| `CONTRACT.CONNECTOR` | NOT_APPLICABLE | manifest does not declare connector_contracts; this board does not opt in to this gate |
| `CONTRACT.PLACEMENT` | NOT_APPLICABLE | manifest does not declare placement_rules; this board does not opt in to this gate |
| `DRC.AUTHORITATIVE` | NOT_APPLICABLE | manifest does not declare checks.drc; this board does not opt in to this gate |
| `DRC.NO_SUPPRESSED_RULES` | NOT_APPLICABLE | manifest does not declare checks.drc.forbidden_severities; this board does not opt in to this gate |
| `ERC.AUTHORITATIVE` | NOT_APPLICABLE | manifest does not declare checks.erc; this board does not opt in to this gate |
| `NET.TOPOLOGY` | NOT_APPLICABLE | manifest does not declare net_topology.rules; this board does not opt in to this gate |
| `PROV.FIXTURE_INTEGRITY` | NOT_APPLICABLE | manifest does not declare fixture.hash_file; this board does not opt in to this gate |
| `PROV.REPORT_FRESHNESS` | NOT_APPLICABLE | manifest does not declare reports; this board does not opt in to this gate |
| `PROV.SOURCE_AUTHORITY` | PASS | a single, consistent design authority is asserted |
| `ROUTE.ANGLE_STYLE` | PASS | every corner is on the permitted geometry |
| `ROUTE.GEOMETRY_HYGIENE` | PASS | no duplicate, dangling or crossing copper |
| `ROUTE.TINY_SEGMENTS` | PASS | 0 short fragments are all pad/via entry geometry |
| `STACK.GERBER_PARITY` | NOT_APPLICABLE | manifest does not declare artifacts.gerber_dir; this board does not opt in to this gate |
| `STACK.NATIVE_VS_MANIFEST` | PASS | native stackup agrees with the frozen constraints |
| `VIA.ANNULUS_MASK_OVERLAP` | PASS | no via annulus reaches a mask opening |
| `VIA.IN_PAD_CONTACT` | PASS | no via contacts a solderable pad |
| `VIA.MASK_CLEARANCE_PROCESS` | PASS | all 1 vias clear 0.35 mm (annulus_to_opening_mm) |
| `VIA.MASK_CLEARANCE_TARGET` | PASS | all 1 vias clear 0.4 mm (annulus_to_opening_mm) |
| `VIA.NATIVE_GERBER_AGREEMENT` | NOT_APPLICABLE | manifest does not declare artifacts.gerber_dir; this board does not opt in to this gate |
| `CFG.THRESHOLD_PARITY` | PASS | all 10 applied limits trace to the manifest |
