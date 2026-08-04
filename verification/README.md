# pcbqa - board-agnostic KiCad / JLCPCB verification

A fail-closed validator that takes a native KiCad project plus a declarative
manifest and produces a machine-readable pass/fail matrix. KiCad is the sole
design authority: nothing is believed because a report, a label or a Python
model says so.

Rev A of the microphone array is preserved here as a **negative regression
fixture**. The suite passes by proving the validator rejects it.

## Three commands

```bash
python verification/run.py selftest
```
```bash
python verification/run.py validate verification/boards/reva.json
```
```bash
python verification/run.py release verification/boards/reva.json
```

`selftest` runs 38 unit, portability, hygiene and mutation tests. `validate`
exits nonzero and writes `out/<board_id>/validation.{json,md}`. `release`
re-runs every gate first and, on any blocking result, writes only
`release_UNSAFE_diagnostic/` containing `DO_NOT_ORDER.txt` - it never creates a
sealed package.

Use KiCad's bundled Python (it provides `pcbnew` and `shapely`):
`"C:\Program Files\KiCad\10.0\bin\python.exe"`.

## Layout

| Path | Role |
|---|---|
| `pcbqa/core.py` | statuses, results, manifest, provenance, gate registry, reporting |
| `pcbqa/geom.py` | native pad/mask/via geometry via KiCad's own effective shapes |
| `pcbqa/gerber.py` | independent Gerber X2 + Excellon readers, incl. an aperture-macro interpreter |
| `pcbqa/gates/g_provenance.py` | fixture integrity, source authority, report freshness, ERC/DRC |
| `pcbqa/gates/g_geometry.py` | stackup, via/mask clearance, routing style |
| `pcbqa/gates/g_contracts.py` | net topology, connector, placement, BOM/CPL, archive, constraint parity |
| `pcbqa/rules/__init__.py` | reusable rule types: `NetTopologyRule`, `ConnectorContractRule`, `PlacementRule` |
| `boards/*.json` | per-board policy. **All** board identity lives here |
| `fixtures/reva/` | byte-for-byte frozen Rev A + `HASHES.json` |
| `fixtures/portability/` | a structurally different board for the portability test |
| `tests/` | synthetic fixtures, geometry tests, mutation tests, hygiene tests |

`tests/test_suite.py::GenericSourceHygiene` mechanically enforces the split: it
extracts identifiers from every board manifest and fails if any appears in
`pcbqa/`, and it fails if any known Rev A defect count is embedded as a literal
in framework source.

## Onboarding another board

Minimum manifest:

```json
{
  "schema_version": 2,
  "board_id": "my_board",
  "constraint_version": "v1",
  "project_root": "../fixtures/my_board",
  "tools": { "kicad_cli": "<path to kicad-cli>" },
  "sources": { "pcb": "my_board.kicad_pcb" },
  "board_origin_mm": [0.0, 0.0],
  "documentation_globs": [],
  "waivers": []
}
```

That alone runs the geometry-only gates. Every other gate stays
`NOT_APPLICABLE` with a reason until you add its policy block. **Absence is
never a silent pass.**

### Policy blocks and the gates they enable

| Manifest key | Gates enabled |
|---|---|
| `fixture.hash_file` | `PROV.FIXTURE_INTEGRITY` |
| `source_authority` | `PROV.SOURCE_AUTHORITY` |
| `reports` | `PROV.REPORT_FRESHNESS` |
| `checks.erc` / `checks.drc` | `ERC.AUTHORITATIVE`, `DRC.AUTHORITATIVE` |
| `checks.drc.forbidden_severities` | `DRC.NO_SUPPRESSED_RULES` |
| `stackup.expected` | `STACK.NATIVE_VS_MANIFEST` (+ `STACK.GERBER_PARITY` with `artifacts.gerber_dir`) |
| `via_mask.design_target_mm`, `via_mask.process.limit_mm`, `via_mask.pad_contact` | the four `VIA.*` gates |
| `routing.permitted_turn_degrees`, `routing.min_segment_mm`, `routing.hygiene` | the three `ROUTE.*` gates |
| `net_topology.rules` | `NET.TOPOLOGY` |
| `connector_contracts` + `connector_gender_tokens` | `CONTRACT.CONNECTOR` |
| `placement_rules` | `CONTRACT.PLACEMENT` |
| `artifacts.bom` + `artifacts.cpl` | `BOM.NATIVE_PARITY` |
| `archive.zip` + `archive.allow` | `ARCH.CONTENTS` |
| `archive.manifest` | `ARCH.PROVENANCE` |
| `constraint_parity.rival_scan` | `CFG.NO_RIVAL_THRESHOLDS` |

`CFG.THRESHOLD_PARITY` always runs last and proves every limit any gate applied
resolves to the manifest key it cited.

### Rule types

`NetTopologyRule` measures true electrical path length through the copper graph
(tracks + vias) from a driver pad pattern to load pad patterns:

```json
{ "id": "CLK", "net_regex": "^CLK_B\\d+$", "source_pad_regex": "^R\\d+\\.2$",
  "load_pad_regex": "^U\\d+\\.3$", "max_spread_mm": 5.0,
  "max_vias_per_net": 0, "permitted_layers": ["F.Cu"] }
```

`ConnectorContractRule` checks positions, rows, pitch, side, DNP/BOM state,
pin-to-net map, gender agreement across footprint id / 3D model / description /
value, and documentation consistency (`must_claim` / `must_not_claim`).

`PlacementRule` checks polar radius, azimuth grid and radial rotation for a
family of references, with an optional local offset so a feature (an acoustic
port, say) can be measured instead of the footprint origin.

## Measurement definitions

Via-to-mask distances are never collapsed into one number. Each via reports:

| Field | Meaning |
|---|---|
| `drill_to_opening_mm` | hole edge to mask aperture edge |
| `annulus_to_opening_mm` | via pad edge to mask aperture edge (the process metric) |
| `centre_to_opening_mm` | via centre to aperture edge, negative when inside |
| `annulus_to_pad_copper_mm` | via pad edge to pad copper edge |
| `annulus_contacts_opening` | zero distance, i.e. tangency counts |
| `annulus_overlaps_opening` | positive shared area only |

Curved shapes are polygonised **outward** at 1 µm chord error, so an
approximation can only under-state clearance, never over-state it. The
synthetic tests assert that directly.

## Fail-closed behaviour

- An unknown Gerber aperture, macro primitive or open region raises rather than
  being skipped. (Silently skipping macro apertures is precisely how an earlier
  manual review missed a via-in-pad population.)
- A gate that throws is reported `ERROR` and blocks the release.
- A missing manifest key raises; there are no defaults.
- Board default via tenting that cannot be resolved raises.
