# Verification report - microphone_array_v2-revA-cleanroom

- Manifest: `manifest.json` sha256 `05cad8f603d0aa5d`
- Constraint version: `revA-frozen-2026-08-01`
- KiCad: `unrecorded`
- Generated: 2026-08-05T00:41:36.662886+00:00

## Verdict: **REJECTED**

| Status | Gates |
|---|---:|
| PASS | 10 |
| FAIL | 15 |

## Gate matrix

| Gate | Status | Detail |
|---|---|---|
| `ARCH.CONTENTS` | PASS | archive contains exactly the approved fabrication artifacts |
| `ARCH.PROVENANCE` | PASS | release manifest records full provenance and every hash matches |
| `BOM.NATIVE_PARITY` | FAIL | 21 disagreement(s) between the native schematic, the board and the packaged BOM |
| `CFG.NO_RIVAL_THRESHOLDS` | FAIL | 2 rival threshold definition(s) outside the canonical manifest |
| `CONTRACT.CONNECTOR` | FAIL | 15x documentation asserts a superseded interconnect; 2x artifact contradicts the required gender; 1x no document states a required property of the interconnect |
| `CONTRACT.PLACEMENT` | PASS | every placement contract holds |
| `CPL.NATIVE_PARITY` | PASS | all 103 populated parts agree between the native design and the packaged CPL |
| `DRC.AUTHORITATIVE` | FAIL | 1 blocking DRC condition(s); findings=0, exit=0, ignored_checks=5 |
| `DRC.NO_SUPPRESSED_RULES` | FAIL | 5 DRC and 0 ERC rule(s) disabled, 0 stored exclusion(s) |
| `ERC.AUTHORITATIVE` | FAIL | 1 blocking ERC condition(s); findings=0, exit=0, ignored_checks=4 |
| `NET.TOPOLOGY` | FAIL | 3 critical-net topology violation(s) |
| `PROV.FIXTURE_INTEGRITY` | PASS | the frozen copy holds exactly the 43 recorded files, each a regular file matching its canonical digest (text hashed over LF bytes, production output over raw... |
| `PROV.REPORT_FRESHNESS` | PASS | every committed report binds the canonical digest of all 4 source inputs, and every one still matches |
| `PROV.SOURCE_AUTHORITY` | FAIL | 1 contradictory authority claim group(s), 2 non-authoritative derivation(s) of released data |
| `ROUTE.ANGLE_STYLE` | FAIL | 138 corners are not on the permitted [0.0, 45.0] degree geometry |
| `ROUTE.GEOMETRY_HYGIENE` | PASS | no duplicate, dangling or crossing copper |
| `ROUTE.TINY_SEGMENTS` | FAIL | 57 track fragments below 0.25 mm are not pad or via entries |
| `STACK.GERBER_PARITY` | PASS | 4 shipped copper layers match a fresh export by geometric symmetric difference (limit 0.05 mm2) |
| `STACK.NATIVE_VS_MANIFEST` | FAIL | the frozen constraint manifest and the native board describe different plane assignments; the board is authoritative, so the manifest is the representation t... |
| `VIA.ANNULUS_MASK_OVERLAP` | FAIL | 24 via annulus/mask-opening contacts (23 strict overlaps + 1 exact tangencies): these vias cannot be tented or plugged |
| `VIA.IN_PAD_CONTACT` | FAIL | 13 vias contact a pad that receives solder paste (9 centre-inside, 4 partial); solder will wick into the barrel unless a filled/capped process is ordered |
| `VIA.MASK_CLEARANCE_PROCESS` | FAIL | 63 of 184 vias are closer than 0.35 mm (annulus_to_opening_mm) to a solder-mask opening |
| `VIA.MASK_CLEARANCE_TARGET` | FAIL | 70 of 184 vias are closer than 0.4 mm (annulus_to_opening_mm) to a solder-mask opening |
| `VIA.NATIVE_GERBER_AGREEMENT` | PASS | all 184 vias match the export object by object: coordinate, drill, annulus, clearance, contact, overlap, centre-inside, both limit classifications and neares... |
| `CFG.THRESHOLD_PARITY` | PASS | all 48 applied limits are typed constraints traced to the manifest |

### `BOM.NATIVE_PARITY` - Packaged BOM matches the native schematic

21 disagreement(s) between the native schematic, the board and the packaged BOM

Limits applied:
- `assembly.required_part_fields` = ['LCSC'] field name [policy] (from manifest.json#assembly.required_part_fields@05cad8f603d0)
- `assembly.compared_part_fields` = ['LCSC', 'MPN', 'Manufacturer'] field name [policy] (from manifest.json#assembly.compared_part_fields@05cad8f603d0)

- reference=H1, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MountingHole:MountingHole_3.2mm_M3, board_excluded_from_bom=True, board_dnp=False
- reference=H2, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MountingHole:MountingHole_3.2mm_M3, board_excluded_from_bom=True, board_dnp=False
- reference=H3, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MountingHole:MountingHole_3.2mm_M3, board_excluded_from_bom=True, board_dnp=False
- reference=H4, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MountingHole:MountingHole_3.2mm_M3, board_excluded_from_bom=True, board_dnp=False
- reference=J1, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=Connector_PinHeader_2.54mm:PinHeader_2x13_P2.54mm_Vertical, board_excluded_from_bom=True, board_dnp=True
- reference=J2, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=Connector_PinHeader_2.54mm:PinHeader_1x24_P2.54mm_Vertical, board_excluded_from_bom=True, board_dnp=True
- reference=J3, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=Connector_PinHeader_2.54mm:PinHeader_1x24_P2.54mm_Vertical, board_excluded_from_bom=True, board_dnp=True
- reference=TP1, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.0mm_NoSilk, board_excluded_from_bom=True, board_dnp=False
- reference=TP10, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.5mm_NoSilk, board_excluded_from_bom=True, board_dnp=False
- reference=TP11, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.5mm_NoSilk, board_excluded_from_bom=True, board_dnp=False
- reference=TP12, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.5mm_NoSilk, board_excluded_from_bom=True, board_dnp=False
- reference=TP13, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.5mm_NoSilk, board_excluded_from_bom=True, board_dnp=False
- reference=TP14, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.0mm_NoSilk, board_excluded_from_bom=True, board_dnp=False
- reference=TP2, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.5mm_NoSilk, board_excluded_from_bom=True, board_dnp=False
- reference=TP3, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.5mm_NoSilk, board_excluded_from_bom=True, board_dnp=False
- reference=TP4, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.5mm_NoSilk, board_excluded_from_bom=True, board_dnp=False
- reference=TP5, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.5mm_NoSilk, board_excluded_from_bom=True, board_dnp=False
- reference=TP6, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.5mm_NoSilk, board_excluded_from_bom=True, board_dnp=False
- reference=TP7, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.5mm_NoSilk, board_excluded_from_bom=True, board_dnp=False
- reference=TP8, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.5mm_NoSilk, board_excluded_from_bom=True, board_dnp=False
- reference=TP9, issue=on the board but in no schematic symbol; the schematic is the assembly authority, so this part is not part of the design, board_footprint=MicArrayV2:TestPoint_Pad_D1.5mm_NoSilk, board_excluded_from_bom=True, board_dnp=False

### `CFG.NO_RIVAL_THRESHOLDS` - No checker outside the manifest defines its own limits

2 rival threshold definition(s) outside the canonical manifest

Limits applied:
- `constraint_parity.watched_constants` = {'BRANCH_SKEW_LIMIT_MM': {'manifest_key': 'net_topology.rules.0.max_spread_mm'}, 'MIN_SEGMENT_MM': {'manifest_key': 'routing.min_segment_mm'}, 'MAX_TURN_DEGREES': {'manifest_key': 'routing.permitted_turn_degrees.1'}} constant name [policy] (from manifest.json#constraint_parity.rival_scan.watched_constants@05cad8f603d0)

- file=tools/check_routes.py, line=22, constant=MIN_SEGMENT_MM, declares=0.05, manifest_key=routing.min_segment_mm, manifest_value=0.25, issue=a second, divergent copy of a canonical limit
- file=tools/check_routes.py, line=51, constant=BRANCH_SKEW_LIMIT_MM, declares=25.0, manifest_key=net_topology.rules.0.max_spread_mm, manifest_value=5.0, issue=a second, divergent copy of a canonical limit

### `CONTRACT.CONNECTOR` - Connector mating contract is consistent everywhere

15x documentation asserts a superseded interconnect; 2x artifact contradicts the required gender; 1x no document states a required property of the interconnect

- issue=artifact contradicts the required gender, artifact=footprint_id, states=male, required=female, reference=J1, contract=HOST_DIRECT_STACK
- issue=artifact contradicts the required gender, artifact=model_3d, states=male, required=female, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=ribbon cable, file=README.md, line=6, text=ribbon, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=ribbon cable, file=docs/host-interface.md, line=7, text=ribbon, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=ribbon cable, file=docs/host-interface.md, line=56, text=ribbon, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=ribbon cable, file=docs/manufacturing.md, line=100, text=ribbon, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=IDC connector, file=constraints.json, line=84, text=IDC, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=IDC connector, file=docs/architecture.md, line=16, text=IDC, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=IDC connector, file=docs/architecture.md, line=164, text=IDC, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=IDC connector, file=docs/host-interface.md, line=5, text=IDC, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=IDC connector, file=docs/manufacturing.md, line=91, text=IDC, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=IDC connector, file=docs/manufacturing.md, line=94, text=IDC, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=shrouded/keyed connector, file=constraints.json, line=84, text=shrouded, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=shrouded/keyed connector, file=docs/host-interface.md, line=5, text=keyed, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=shrouded/keyed connector, file=docs/host-interface.md, line=5, text=shrouded, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=shrouded/keyed connector, file=docs/manufacturing.md, line=91, text=shrouded, reference=J1, contract=HOST_DIRECT_STACK
- issue=documentation asserts a superseded interconnect, label=shrouded/keyed connector, file=docs/manufacturing.md, line=91, text=keyed, reference=J1, contract=HOST_DIRECT_STACK
- issue=no document states a required property of the interconnect, label=direct board-to-board mating, reference=J1, contract=HOST_DIRECT_STACK

### `DRC.AUTHORITATIVE` - Fresh DRC on the exact final board

1 blocking DRC condition(s); findings=0, exit=0, ignored_checks=5

Limits applied:
- `checks.drc.required_flags` = ['--severity-all', '--exit-code-violations', '--all-track-errors', '--schematic-parity'] cli option [policy] (from manifest.json#checks.drc.required_flags@05cad8f603d0)
- `checks.drc.required_severities` = ['error', 'warning', 'exclusion'] severity [policy] (from manifest.json#checks.drc.required_severities@05cad8f603d0)
- `checks.drc.violations_exit_code` = 5 exit status [policy] (from manifest.json#checks.drc.violations_exit_code@05cad8f603d0)
- `geometry.waiver_location_mm` = 0.001 mm [tolerance] (from manifest.json#geometry_profile.tolerances.waiver_location_mm.value@05cad8f603d0)

- issue=run ignored one or more checks, ignored=['missing_courtyard', 'track_not_centered_on_via', 'tuning_profile_track_geometries', 'footprint_filters_mismatch', 'footprint_type_mismatch']

### `DRC.NO_SUPPRESSED_RULES` - No design rule is silently disabled

5 DRC and 0 ERC rule(s) disabled, 0 stored exclusion(s)

Limits applied:
- `checks.drc.forbidden_severities` = ['ignore'] severity [policy] (from manifest.json#checks.drc.forbidden_severities@05cad8f603d0)

- domain=drc, rule=footprint_filters_mismatch, severity=ignore, issue=rule disabled without an approved waiver
- domain=drc, rule=footprint_type_mismatch, severity=ignore, issue=rule disabled without an approved waiver
- domain=drc, rule=missing_courtyard, severity=ignore, issue=rule disabled without an approved waiver
- domain=drc, rule=track_not_centered_on_via, severity=ignore, issue=rule disabled without an approved waiver
- domain=drc, rule=tuning_profile_track_geometries, severity=ignore, issue=rule disabled without an approved waiver

### `ERC.AUTHORITATIVE` - Fresh ERC on the exact final schematic

1 blocking ERC condition(s); findings=0, exit=0, ignored_checks=4

Limits applied:
- `checks.erc.required_flags` = ['--severity-all', '--exit-code-violations'] cli option [policy] (from manifest.json#checks.erc.required_flags@05cad8f603d0)
- `checks.erc.required_severities` = ['error', 'warning', 'exclusion'] severity [policy] (from manifest.json#checks.erc.required_severities@05cad8f603d0)
- `checks.erc.violations_exit_code` = 5 exit status [policy] (from manifest.json#checks.erc.violations_exit_code@05cad8f603d0)
- `geometry.waiver_location_mm` = 0.001 mm [tolerance] (from manifest.json#geometry_profile.tolerances.waiver_location_mm.value@05cad8f603d0)

- issue=run ignored one or more checks, ignored=['single_global_label', 'four_way_junction', 'simulation_model_issue', 'footprint_filter']

### `NET.TOPOLOGY` - Critical-net topology and length matching

3 critical-net topology violation(s)

Limits applied:
- `geometry.polygon_chord_error_mm` = 0.001 mm [tolerance] (from manifest.json#geometry_profile.tolerances.polygon_chord_error_mm.value@05cad8f603d0)
- `net_topology.PDM_CLOCK_BRANCHES.max_spread_mm` = 5.0 mm [policy] (from manifest.json#net_topology.rules.0.max_spread_mm@05cad8f603d0)
- `net_topology.PDM_CLOCK_BRANCHES.max_vias_per_net` = 0 vias [policy] (from manifest.json#net_topology.rules.0.max_vias_per_net@05cad8f603d0)
- `net_topology.PDM_CLOCK_ROOT.max_vias_per_net` = 0 vias [policy] (from manifest.json#net_topology.rules.1.max_vias_per_net@05cad8f603d0)
- `net_topology.AUDIO_MCLK.max_vias_per_net` = 0 vias [policy] (from manifest.json#net_topology.rules.2.max_vias_per_net@05cad8f603d0)

- issue=branch length spread exceeds the requirement, measured_spread_mm=24.275, limit_mm=5.0, min_mm=55.037, max_mm=79.312, definition=longest driver-to-load path per net; vias contribute zero, rule=PDM_CLOCK_BRANCHES
- issue=via budget exceeded, net=PDM_CLK_IN, vias=3, limit=0, rule=PDM_CLOCK_ROOT
- issue=net uses a layer it is not allowed on, net=PDM_CLK_IN, layers=['B.Cu'], permitted=['F.Cu'], rule=PDM_CLOCK_ROOT

### `PROV.SOURCE_AUTHORITY` - KiCad is the sole design authority

1 contradictory authority claim group(s), 2 non-authoritative derivation(s) of released data

Limits applied:
- `source_authority` = native_kicad policy [policy] (from manifest.json#source_authority.authority@05cad8f603d0)

- issue=contradictory source-of-truth claims, claims=['native_kicad_is_authority', 'python_model_is_authority'], seen_at=['README.md:56', 'README.md:69', 'README.md:109', 'docs/status.md:137', 'README.md:55', 'docs/manufacturing.md:123', 'docs/manufacturing.md:124', 'docs/manufacturing.md:124']
- file=tools/make_release.py, line=19, issue=released BOM/CPL data is taken from a Python model instead of the native KiCad project, text=import netlist
- file=tools/make_release.py, line=92, issue=released BOM/CPL data is taken from a Python model instead of the native KiCad project, text=nl.build()

### `ROUTE.ANGLE_STYLE` - Routing obeys the permitted angle style

138 corners are not on the permitted [0.0, 45.0] degree geometry

Limits applied:
- `routing.permitted_turn_degrees` = [0.0, 45.0] deg [policy] (from manifest.json#routing.permitted_turn_degrees@05cad8f603d0)
- `routing.angle_tolerance_deg` = 1.0 deg [policy] (from manifest.json#routing.angle_tolerance_deg@05cad8f603d0)

- net=PI_SCLK, layer=F.Cu, x_mm=139.8, y_mm=-177.2, turn_deg=135.42
- net=+5V, layer=F.Cu, x_mm=151.863, y_mm=-166.05, turn_deg=90.05
- net=+3V3A, layer=F.Cu, x_mm=161.438, y_mm=-163.0, turn_deg=90.0
- net=+5V, layer=F.Cu, x_mm=150.3, y_mm=-166.05, turn_deg=90.0
- net=+5V, layer=F.Cu, x_mm=150.3, y_mm=-167.95, turn_deg=90.0
- net=+5V, layer=F.Cu, x_mm=146.03, y_mm=-163.3, turn_deg=90.0
- net=PDM_CLK_B0, layer=F.Cu, x_mm=180.32, y_mm=-140.77, turn_deg=90.0
- net=PDM_CLK_B6, layer=F.Cu, x_mm=169.0, y_mm=-183.472, turn_deg=90.0
- net=PDM_D0, layer=B.Cu, x_mm=179.05, y_mm=-133.17, turn_deg=90.0
- net=PDM_D0, layer=B.Cu, x_mm=179.05, y_mm=-143.97, turn_deg=90.0
- net=PDM_D0, layer=B.Cu, x_mm=180.32, y_mm=-140.77, turn_deg=90.0
- net=PDM_CLK_B5, layer=F.Cu, x_mm=125.5, y_mm=-163.2, turn_deg=90.0
- net=PDM_CLK_B1, layer=F.Cu, x_mm=165.08, y_mm=-140.77, turn_deg=90.0
- net=PDM_D4, layer=B.Cu, x_mm=137.14, y_mm=-159.23, turn_deg=90.0
- net=PDM_D4, layer=B.Cu, x_mm=135.87, y_mm=-166.83, turn_deg=90.0
- net=PDM_D4, layer=B.Cu, x_mm=135.87, y_mm=-156.03, turn_deg=90.0
- net=PDM_D6, layer=B.Cu, x_mm=161.43, y_mm=-183.93, turn_deg=90.0
- net=PI_5V, layer=F.Cu, x_mm=162.7, y_mm=-179.19, turn_deg=90.0
- net=PI_5V, layer=F.Cu, x_mm=162.7, y_mm=-171.0, turn_deg=90.0
- net=PDM_CLK_IN, layer=B.Cu, x_mm=146.0, y_mm=-150.8, turn_deg=90.0
- net=+5V, layer=F.Cu, x_mm=151.861, y_mm=-164.601, turn_deg=89.97
- net=PDM_D7, layer=B.Cu, x_mm=179.345, y_mm=-164.43, turn_deg=89.91
- net=+3V3_CLK, layer=F.Cu, x_mm=153.412, y_mm=-159.2, turn_deg=89.86
- net=+5V, layer=F.Cu, x_mm=136.35, y_mm=-164.6, turn_deg=67.5
- net=+5V, layer=F.Cu, x_mm=136.277, y_mm=-164.777, turn_deg=67.5
- ... 35 more

### `ROUTE.TINY_SEGMENTS` - No unjustified sub-minimum track fragments

57 track fragments below 0.25 mm are not pad or via entries

Limits applied:
- `routing.min_segment_mm` = 0.25 mm [policy] (from manifest.json#routing.min_segment_mm@05cad8f603d0)

- net=+3V3_CLK, layer=F.Cu, x_mm=155.1, y_mm=-157.5, length_mm=0.0708
- net=PDM_D0, layer=B.Cu, x_mm=179.05, y_mm=-140.669, length_mm=0.0758
- net=PDM_D4, layer=B.Cu, x_mm=135.87, y_mm=-159.331, length_mm=0.0758
- net=PI_MISO, layer=F.Cu, x_mm=153.7, y_mm=-178.7, length_mm=0.1
- net=PI_MISO, layer=F.Cu, x_mm=153.6, y_mm=-178.5, length_mm=0.1
- net=PDM_CLK_Y3, layer=F.Cu, x_mm=138.3, y_mm=-148.8, length_mm=0.1
- net=PDM_CLK_Y3, layer=F.Cu, x_mm=144.2, y_mm=-150.1, length_mm=0.1
- net=PDM_CLK_Y3, layer=F.Cu, x_mm=145.5, y_mm=-151.5, length_mm=0.1
- net=HOST_STATUS, layer=F.Cu, x_mm=153.5, y_mm=-164.4, length_mm=0.1
- net=PI_MOSI, layer=F.Cu, x_mm=145.6, y_mm=-182.8, length_mm=0.1
- net=PI_MOSI, layer=F.Cu, x_mm=145.4, y_mm=-182.9, length_mm=0.1
- net=PI_STATUS, layer=B.Cu, x_mm=151.6, y_mm=-176.5, length_mm=0.1
- net=+3V3_CLK, layer=F.Cu, x_mm=164.5, y_mm=-158.3, length_mm=0.1
- net=+3V3_CLK, layer=F.Cu, x_mm=164.0, y_mm=-157.9, length_mm=0.1
- net=+3V3_CLK, layer=F.Cu, x_mm=150.0, y_mm=-158.3, length_mm=0.1
- net=PDM_CLK_Y4, layer=F.Cu, x_mm=138.3, y_mm=-150.7, length_mm=0.1
- net=PDM_CLK_Y2, layer=F.Cu, x_mm=138.7, y_mm=-146.7, length_mm=0.1
- net=PDM_CLK_Y5, layer=F.Cu, x_mm=145.8, y_mm=-154.7, length_mm=0.1
- net=PDM_CLK_Y5, layer=F.Cu, x_mm=138.3, y_mm=-153.2, length_mm=0.1
- net=+3V3_CLK, layer=F.Cu, x_mm=155.421, y_mm=-157.5, length_mm=0.125
- net=+3V3_CLK, layer=F.Cu, x_mm=155.546, y_mm=-157.5, length_mm=0.125
- net=+3V3_CLK, layer=F.Cu, x_mm=155.171, y_mm=-157.5, length_mm=0.125
- net=+3V3_CLK, layer=F.Cu, x_mm=155.296, y_mm=-157.5, length_mm=0.125
- net=PI_MISO, layer=F.Cu, x_mm=153.7, y_mm=-178.6, length_mm=0.1414
- net=PI_MISO, layer=F.Cu, x_mm=153.8, y_mm=-178.8, length_mm=0.1414
- ... 32 more

### `STACK.NATIVE_VS_MANIFEST` - Board stackup matches the frozen constraints

the frozen constraint manifest and the native board describe different plane assignments; the board is authoritative, so the manifest is the representation that disagrees

Limits applied:
- `stackup.expected` = [{'role': 'signal'}, {'role': 'plane', 'plane_net': 'GND'}, {'role': 'plane', 'plane_net': '+3V3A'}, {'role': 'signal'}] layer roles [policy] (from manifest.json#stackup.expected@05cad8f603d0)

- layer_index=3, layer=GND2, expected_plane_net=+3V3A, actual_zone_nets=['GND'], issue=plane net disagreement

### `VIA.ANNULUS_MASK_OVERLAP` - No via annulus intersects a mask opening

24 via annulus/mask-opening contacts (23 strict overlaps + 1 exact tangencies): these vias cannot be tented or plugged

Limits applied:
- `geometry.contact_mm` = 1e-06 mm [tolerance] (from manifest.json#geometry_profile.tolerances.contact_mm.value@05cad8f603d0)
- `geometry.polygon_chord_error_mm` = 0.001 mm [tolerance] (from manifest.json#geometry_profile.tolerances.polygon_chord_error_mm.value@05cad8f603d0)

- net=GND, x_mm=154.0, y_mm=126.0, side=front, pad=TP4.1, pad_net=GND, contact=overlap, centre_inside=True, annulus_to_opening_mm=0.0
- net=GND, x_mm=150.9762, y_mm=167.1563, side=front, pad=U1.2, pad_net=GND, contact=overlap, centre_inside=False, annulus_to_opening_mm=0.0
- net=GND, x_mm=157.0, y_mm=128.0, side=front, pad=TP5.1, pad_net=GND, contact=overlap, centre_inside=True, annulus_to_opening_mm=0.0
- net=PI_MISO, x_mm=144.6, y_mm=172.7, side=front, pad=RH4.1, pad_net=PI_MISO, contact=overlap, centre_inside=True, annulus_to_opening_mm=0.0
- net=PDM_D1, x_mm=179.3449, y_mm=120.6551, side=front, pad=TP7.1, pad_net=PDM_D1, contact=overlap, centre_inside=False, annulus_to_opening_mm=0.0
- net=HOST_STATUS, x_mm=152.2, y_mm=171.7, side=front, pad=RH7.2, pad_net=HOST_STATUS, contact=overlap, centre_inside=True, annulus_to_opening_mm=0.0
- net=HOST_STATUS, x_mm=152.2, y_mm=170.3, side=front, pad=TP14.1, pad_net=HOST_STATUS, contact=overlap, centre_inside=False, annulus_to_opening_mm=0.0
- net=+3V3_CLK, x_mm=151.9, y_mm=150.0, side=front, pad=U2.20, pad_net=+3V3_CLK, contact=tangency, centre_inside=False, annulus_to_opening_mm=0.0
- net=+3V3_CLK, x_mm=142.5, y_mm=147.0, side=front, pad=C8.1, pad_net=+3V3_CLK, contact=overlap, centre_inside=True, annulus_to_opening_mm=0.0
- net=PDM_D0, x_mm=188.341, y_mm=134.1186, side=front, pad=TP6.1, pad_net=PDM_D0, contact=overlap, centre_inside=False, annulus_to_opening_mm=0.0
- net=PI_SCLK, x_mm=139.8, y_mm=177.2, side=front, pad=U3.3, pad_net=PI_SCLK, contact=overlap, centre_inside=False, annulus_to_opening_mm=0.0
- net=SPI_SCLK, x_mm=139.2, y_mm=171.7, side=front, pad=RH2.2, pad_net=SPI_SCLK, contact=overlap, centre_inside=True, annulus_to_opening_mm=0.0
- net=PDM_D2, x_mm=150.0, y_mm=108.5, side=front, pad=TP8.1, pad_net=PDM_D2, contact=overlap, centre_inside=False, annulus_to_opening_mm=0.0
- net=PI_SYNC, x_mm=154.4, y_mm=172.9, side=front, pad=RH8.1, pad_net=PI_SYNC, contact=overlap, centre_inside=True, annulus_to_opening_mm=0.0
- net=PDM_D4, x_mm=111.659, y_mm=165.8814, side=front, pad=TP10.1, pad_net=PDM_D4, contact=overlap, centre_inside=False, annulus_to_opening_mm=0.0
- net=PDM_D3, x_mm=120.6551, y_mm=120.6551, side=front, pad=TP9.1, pad_net=PDM_D3, contact=overlap, centre_inside=False, annulus_to_opening_mm=0.0
- net=PDM_D7, x_mm=179.3449, y_mm=179.3449, side=front, pad=TP13.1, pad_net=PDM_D7, contact=overlap, centre_inside=False, annulus_to_opening_mm=0.0
- net=TANG_3V3, x_mm=150.1, y_mm=175.8, side=front, pad=U4.5, pad_net=TANG_3V3, contact=overlap, centre_inside=True, annulus_to_opening_mm=0.0
- net=TANG_3V3, x_mm=141.6, y_mm=175.8, side=front, pad=U3.5, pad_net=TANG_3V3, contact=overlap, centre_inside=True, annulus_to_opening_mm=0.0
- net=PDM_D5, x_mm=120.6551, y_mm=179.3449, side=front, pad=TP11.1, pad_net=PDM_D5, contact=overlap, centre_inside=False, annulus_to_opening_mm=0.0
- net=PDM_D6, x_mm=165.8814, y_mm=188.341, side=front, pad=TP12.1, pad_net=PDM_D6, contact=overlap, centre_inside=False, annulus_to_opening_mm=0.0
- net=PI_IRQ, x_mm=148.1, y_mm=174.9, side=front, pad=U4.1, pad_net=PI_IRQ, contact=overlap, centre_inside=True, annulus_to_opening_mm=0.0
- net=HOST_IRQ, x_mm=147.4, y_mm=171.7, side=front, pad=RH5.2, pad_net=HOST_IRQ, contact=overlap, centre_inside=False, annulus_to_opening_mm=0.0
- net=PDM_CLK_FPGA, x_mm=142.2, y_mm=150.9, side=front, pad=R2.1, pad_net=PDM_CLK_FPGA, contact=overlap, centre_inside=True, annulus_to_opening_mm=0.0

### `VIA.IN_PAD_CONTACT` - No via contacts a pad that receives solder

13 vias contact a pad that receives solder paste (9 centre-inside, 4 partial); solder will wick into the barrel unless a filled/capped process is ordered

Limits applied:
- `via_mask.populated_pad_attributes` = ['SMD'] pad attribute [policy] (from manifest.json#via_mask.pad_contact.populated_pad_attributes@05cad8f603d0)
- `via_mask.mask_dam_rule` = contact policy [policy] (from manifest.json#via_mask.mask_dam_rule@05cad8f603d0)

- net=GND, x_mm=154.0, y_mm=126.0, side=front, pad=TP4.1, pad_net=GND, pad_receives_paste=False, class=unpopulated, contact=overlap, centre_to_opening_mm=-0.75
- net=GND, x_mm=157.0, y_mm=128.0, side=front, pad=TP5.1, pad_net=GND, pad_receives_paste=False, class=unpopulated, contact=overlap, centre_to_opening_mm=-0.75
- net=PI_MISO, x_mm=144.6, y_mm=172.7, side=front, pad=RH4.1, pad_net=PI_MISO, pad_receives_paste=True, class=populated, contact=overlap, centre_to_opening_mm=-0.02
- net=HOST_STATUS, x_mm=152.2, y_mm=171.7, side=front, pad=RH7.2, pad_net=HOST_STATUS, pad_receives_paste=True, class=populated, contact=overlap, centre_to_opening_mm=-0.18
- net=+3V3_CLK, x_mm=142.5, y_mm=147.0, side=front, pad=C8.1, pad_net=+3V3_CLK, pad_receives_paste=True, class=populated, contact=overlap, centre_to_opening_mm=-0.11
- net=SPI_SCLK, x_mm=139.2, y_mm=171.7, side=front, pad=RH2.2, pad_net=SPI_SCLK, pad_receives_paste=True, class=populated, contact=overlap, centre_to_opening_mm=-0.18
- net=PI_SYNC, x_mm=154.4, y_mm=172.9, side=front, pad=RH8.1, pad_net=PI_SYNC, pad_receives_paste=True, class=populated, contact=overlap, centre_to_opening_mm=-0.02
- net=TANG_3V3, x_mm=150.1, y_mm=175.8, side=front, pad=U4.5, pad_net=TANG_3V3, pad_receives_paste=True, class=populated, contact=overlap, centre_to_opening_mm=-0.3
- net=TANG_3V3, x_mm=141.6, y_mm=175.8, side=front, pad=U3.5, pad_net=TANG_3V3, pad_receives_paste=True, class=populated, contact=overlap, centre_to_opening_mm=-0.3
- net=PI_IRQ, x_mm=148.1, y_mm=174.9, side=front, pad=U4.1, pad_net=PI_IRQ, pad_receives_paste=True, class=populated, contact=overlap, centre_to_opening_mm=-0.25
- net=PDM_CLK_FPGA, x_mm=142.2, y_mm=150.9, side=front, pad=R2.1, pad_net=PDM_CLK_FPGA, pad_receives_paste=True, class=populated, contact=overlap, centre_to_opening_mm=-0.06
- net=GND, x_mm=150.9762, y_mm=167.1563, side=front, pad=U1.2, pad_net=GND, pad_receives_paste=True, class=populated, contact=overlap, centre_to_opening_mm=0.2238
- net=PDM_D1, x_mm=179.3449, y_mm=120.6551, side=front, pad=TP7.1, pad_net=PDM_D1, pad_receives_paste=False, class=unpopulated, contact=overlap, centre_to_opening_mm=0.1043
- net=HOST_STATUS, x_mm=152.2, y_mm=170.3, side=front, pad=TP14.1, pad_net=HOST_STATUS, pad_receives_paste=False, class=unpopulated, contact=overlap, centre_to_opening_mm=0.0657
- net=+3V3_CLK, x_mm=151.9, y_mm=150.0, side=front, pad=U2.20, pad_net=+3V3_CLK, pad_receives_paste=True, class=populated, contact=tangency, centre_to_opening_mm=0.225
- net=PDM_D0, x_mm=188.341, y_mm=134.1186, side=front, pad=TP6.1, pad_net=PDM_D0, pad_receives_paste=False, class=unpopulated, contact=overlap, centre_to_opening_mm=0.1043
- net=PI_SCLK, x_mm=139.8, y_mm=177.2, side=front, pad=U3.3, pad_net=PI_SCLK, pad_receives_paste=True, class=populated, contact=overlap, centre_to_opening_mm=0.15
- net=PDM_D2, x_mm=150.0, y_mm=108.5, side=front, pad=TP8.1, pad_net=PDM_D2, pad_receives_paste=False, class=unpopulated, contact=overlap, centre_to_opening_mm=0.1043
- net=PDM_D4, x_mm=111.659, y_mm=165.8814, side=front, pad=TP10.1, pad_net=PDM_D4, pad_receives_paste=False, class=unpopulated, contact=overlap, centre_to_opening_mm=0.1043
- net=PDM_D3, x_mm=120.6551, y_mm=120.6551, side=front, pad=TP9.1, pad_net=PDM_D3, pad_receives_paste=False, class=unpopulated, contact=overlap, centre_to_opening_mm=0.1043
- net=PDM_D7, x_mm=179.3449, y_mm=179.3449, side=front, pad=TP13.1, pad_net=PDM_D7, pad_receives_paste=False, class=unpopulated, contact=overlap, centre_to_opening_mm=0.1043
- net=PDM_D5, x_mm=120.6551, y_mm=179.3449, side=front, pad=TP11.1, pad_net=PDM_D5, pad_receives_paste=False, class=unpopulated, contact=overlap, centre_to_opening_mm=0.1043
- net=PDM_D6, x_mm=165.8814, y_mm=188.341, side=front, pad=TP12.1, pad_net=PDM_D6, pad_receives_paste=False, class=unpopulated, contact=overlap, centre_to_opening_mm=0.1043
- net=HOST_IRQ, x_mm=147.4, y_mm=171.7, side=front, pad=RH5.2, pad_net=HOST_IRQ, pad_receives_paste=True, class=populated, contact=overlap, centre_to_opening_mm=0.18

### `VIA.MASK_CLEARANCE_PROCESS` - Via to mask opening meets the fab process limit

63 of 184 vias are closer than 0.35 mm (annulus_to_opening_mm) to a solder-mask opening

Limits applied:
- `process_limit_mm` = 0.35 mm [policy] (from manifest.json#via_mask.process.limit_mm@05cad8f603d0)
- `geometry.polygon_chord_error_mm` = 0.001 mm [tolerance] (from manifest.json#geometry_profile.tolerances.polygon_chord_error_mm.value@05cad8f603d0)
- `via_mask.metric` = annulus_to_opening_mm field name [policy] (from manifest.json#via_mask.metric@05cad8f603d0)

- net=GND, x_mm=154.0, y_mm=126.0, side=front, nearest_pad=TP4.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.75
- net=GND, x_mm=150.9762, y_mm=167.1563, side=front, nearest_pad=U1.2, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0738, centre_to_opening_mm=0.2238
- net=GND, x_mm=157.0, y_mm=128.0, side=front, nearest_pad=TP5.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.75
- net=PI_MISO, x_mm=144.6, y_mm=172.7, side=front, nearest_pad=RH4.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.02
- net=PDM_D1, x_mm=179.3449, y_mm=120.6551, side=front, nearest_pad=TP7.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=HOST_STATUS, x_mm=152.2, y_mm=171.7, side=front, nearest_pad=RH7.2, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.18
- net=HOST_STATUS, x_mm=152.2, y_mm=170.3, side=front, nearest_pad=TP14.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.0657
- net=+3V3_CLK, x_mm=151.9, y_mm=150.0, side=front, nearest_pad=U2.20, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.075, centre_to_opening_mm=0.225
- net=+3V3_CLK, x_mm=142.5, y_mm=147.0, side=front, nearest_pad=C8.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.11
- net=PDM_D0, x_mm=188.341, y_mm=134.1186, side=front, nearest_pad=TP6.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=PI_SCLK, x_mm=139.8, y_mm=177.2, side=front, nearest_pad=U3.3, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.15
- net=SPI_SCLK, x_mm=139.2, y_mm=171.7, side=front, nearest_pad=RH2.2, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.18
- net=PDM_D2, x_mm=150.0, y_mm=108.5, side=front, nearest_pad=TP8.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=PI_SYNC, x_mm=154.4, y_mm=172.9, side=front, nearest_pad=RH8.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.02
- net=PDM_D4, x_mm=111.659, y_mm=165.8814, side=front, nearest_pad=TP10.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=PDM_D3, x_mm=120.6551, y_mm=120.6551, side=front, nearest_pad=TP9.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=PDM_D7, x_mm=179.3449, y_mm=179.3449, side=front, nearest_pad=TP13.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=TANG_3V3, x_mm=150.1, y_mm=175.8, side=front, nearest_pad=U4.5, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.3
- net=TANG_3V3, x_mm=141.6, y_mm=175.8, side=front, nearest_pad=U3.5, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.3
- net=PDM_D5, x_mm=120.6551, y_mm=179.3449, side=front, nearest_pad=TP11.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=PDM_D6, x_mm=165.8814, y_mm=188.341, side=front, nearest_pad=TP12.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=PI_IRQ, x_mm=148.1, y_mm=174.9, side=front, nearest_pad=U4.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.25
- net=HOST_IRQ, x_mm=147.4, y_mm=171.7, side=front, nearest_pad=RH5.2, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.03, centre_to_opening_mm=0.18
- net=PDM_CLK_FPGA, x_mm=142.2, y_mm=150.9, side=front, nearest_pad=R2.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.06
- net=PI_STATUS, x_mm=149.6, y_mm=177.3, side=front, nearest_pad=U4.4, annulus_to_opening_mm=0.0255, drill_to_opening_mm=0.1005, centre_to_opening_mm=0.2504
- ... 38 more

### `VIA.MASK_CLEARANCE_TARGET` - Via to mask opening meets the project target

70 of 184 vias are closer than 0.4 mm (annulus_to_opening_mm) to a solder-mask opening

Limits applied:
- `design_target_mm` = 0.4 mm [policy] (from manifest.json#via_mask.design_target_mm@05cad8f603d0)
- `geometry.polygon_chord_error_mm` = 0.001 mm [tolerance] (from manifest.json#geometry_profile.tolerances.polygon_chord_error_mm.value@05cad8f603d0)
- `via_mask.metric` = annulus_to_opening_mm field name [policy] (from manifest.json#via_mask.metric@05cad8f603d0)

- net=GND, x_mm=154.0, y_mm=126.0, side=front, nearest_pad=TP4.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.75
- net=GND, x_mm=150.9762, y_mm=167.1563, side=front, nearest_pad=U1.2, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0738, centre_to_opening_mm=0.2238
- net=GND, x_mm=157.0, y_mm=128.0, side=front, nearest_pad=TP5.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.75
- net=PI_MISO, x_mm=144.6, y_mm=172.7, side=front, nearest_pad=RH4.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.02
- net=PDM_D1, x_mm=179.3449, y_mm=120.6551, side=front, nearest_pad=TP7.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=HOST_STATUS, x_mm=152.2, y_mm=171.7, side=front, nearest_pad=RH7.2, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.18
- net=HOST_STATUS, x_mm=152.2, y_mm=170.3, side=front, nearest_pad=TP14.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.0657
- net=+3V3_CLK, x_mm=151.9, y_mm=150.0, side=front, nearest_pad=U2.20, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.075, centre_to_opening_mm=0.225
- net=+3V3_CLK, x_mm=142.5, y_mm=147.0, side=front, nearest_pad=C8.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.11
- net=PDM_D0, x_mm=188.341, y_mm=134.1186, side=front, nearest_pad=TP6.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=PI_SCLK, x_mm=139.8, y_mm=177.2, side=front, nearest_pad=U3.3, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.15
- net=SPI_SCLK, x_mm=139.2, y_mm=171.7, side=front, nearest_pad=RH2.2, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.18
- net=PDM_D2, x_mm=150.0, y_mm=108.5, side=front, nearest_pad=TP8.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=PI_SYNC, x_mm=154.4, y_mm=172.9, side=front, nearest_pad=RH8.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.02
- net=PDM_D4, x_mm=111.659, y_mm=165.8814, side=front, nearest_pad=TP10.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=PDM_D3, x_mm=120.6551, y_mm=120.6551, side=front, nearest_pad=TP9.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=PDM_D7, x_mm=179.3449, y_mm=179.3449, side=front, nearest_pad=TP13.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=TANG_3V3, x_mm=150.1, y_mm=175.8, side=front, nearest_pad=U4.5, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.3
- net=TANG_3V3, x_mm=141.6, y_mm=175.8, side=front, nearest_pad=U3.5, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.3
- net=PDM_D5, x_mm=120.6551, y_mm=179.3449, side=front, nearest_pad=TP11.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=PDM_D6, x_mm=165.8814, y_mm=188.341, side=front, nearest_pad=TP12.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=0.1043
- net=PI_IRQ, x_mm=148.1, y_mm=174.9, side=front, nearest_pad=U4.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.25
- net=HOST_IRQ, x_mm=147.4, y_mm=171.7, side=front, nearest_pad=RH5.2, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.03, centre_to_opening_mm=0.18
- net=PDM_CLK_FPGA, x_mm=142.2, y_mm=150.9, side=front, nearest_pad=R2.1, annulus_to_opening_mm=0.0, drill_to_opening_mm=0.0, centre_to_opening_mm=-0.06
- net=PI_STATUS, x_mm=149.6, y_mm=177.3, side=front, nearest_pad=U4.4, annulus_to_opening_mm=0.0255, drill_to_opening_mm=0.1005, centre_to_opening_mm=0.2504
- ... 45 more
