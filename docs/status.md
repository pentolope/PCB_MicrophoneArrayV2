# Status: routed and DRC clean

All 270 connections are routed. KiCad reports **0 DRC violations, 0 unconnected
items and 0 schematic parity issues**, with zones refilled.

| Gate | Result |
|---|---|
| Schematic ERC | 0 violations |
| Board DRC (errors + warnings) | 0 violations |
| Unconnected items | 0 |
| Schematic parity | 0 issues |
| Netlist parity, schematic vs `tools/netlist.py` | clean, 83 nets, 110 components |
| Placement and array geometry audit | clean, 110 footprints |
| Clock branch layers and via budget | clean - zero vias, F.Cu only |
| Clock branch length matching | 21.5 mm spread against a 25 mm limit |
| PDM data length | clean |
| Different-net crossings | none |

Copper: 1749 mm on F.Cu, 817 mm on B.Cu, 183 vias. Both inner layers are still
solid ground - 10 757 mm² filled each, no tracks on either.

## How it got here

The generated routing in `tools/gen_pcb.py` closed the microphone array, the
clock tree, the data spokes, the supply ring and the power block, but left the
host block open - 73 connections. Those were finished with an external
autorouter, and the test points were removed at the same time.

The autorouter left the parts that matter alone. All eight PDM clock branches
are still F.Cu only with zero vias, and each PDM data net still uses exactly
two. Net classes, via geometry (0.45 mm pad / 0.30 mm drill throughout) and the
ground planes came through untouched.

## What was repaired afterwards

`tools/patch_board.py` fixes the board in place, because it is no longer
regenerated from the netlist. It found and fixed:

- **Two hard shorts.** A ground stitching via and its stub sat on U1 pin 3, tying
  the regulator's enable pin to ground - the whole 3.3 V rail would have been
  dead. Another shorted the 5 V input lane to ground. Both come from the
  `POWER_ROW_REFS` special case in `place_ground_stitching()`, which pushes the
  via 1.45 mm straight down with no obstacle test at all, even though the
  function builds an obstacle list a few lines earlier. Moving
  `POWER_ROW2_Y` from -20.2 to -19.8 mm, to open the 5 V lane, is what put the
  second one on top of that lane.
- **A third instance of the same defect**, 0.067 mm from RH4's SPI_MISO pad.
- **Three clearance failures caused by a single wrong constant.** The generator
  checks everything against `TRACK_CLEARANCE = 0.15`, but POWER wants 0.25 mm and
  Default 0.20 mm, so near misses against those nets passed the guard and
  failed DRC. The +3V3A feed threading the module socket needed 1.30 mm of the
  1.27 mm between two pins; it is now 0.25 mm wide and fits.
- **A dangling 1.6 mm tail** on the +5V bus, left over from turning D1 round so
  its anode faces the fuse.
- **Two 0.3 mm drills 0.204 mm apart** where the supply feed landed on its own
  via next to the ring's. Same net, so the feed now runs into the ring's via.

## Test points

Not populated. The 24 pads sat on the R = 26 and 32 mm rings, which is the
annulus the clock branches fan out through, and TP1 landed close enough to a
module socket pin to short it. `tools/design.py` keeps the table of nets worth
probing as `TEST_POINT_TABLE` but emits none, so schematic and board agree.

Reinstating them needs somewhere outside the fan-out annulus - the sector gaps
at 33.75 + 90n degrees beyond R = 50 mm are clear, or the underside.

## Still outstanding

None of these are DRC violations, and none affect function.

- **31 track segments shorter than 0.05 mm and 69 corners sharper than 45°**,
  including three exact 180° reversals where a track retraces itself. Autorouter
  cleanup artefacts plus degenerate knees from `path_45()` where two waypoints
  are nearly collinear. Acid-trap hygiene, worth a cleanup pass.
- **`PDM_CLK_IN` uses 3 vias against the budget of 2** in `check_routes.py`. The
  net fans out to eight buffer inputs and needs a layer change to do it; with
  both inner layers grounded the reference plane is continuous across each via,
  so this is a documented limit being exceeded rather than a signal integrity
  problem.
- **Clock branch spread is 21.5 mm**, up from 7.1 mm, because branches 5 and 6
  take lateral corridors around the host block. Still inside the 25 mm limit,
  and 21.5 mm of FR-4 is about 130 ps against a 325 ns PDM clock period, but
  the margin is thinner than it was.

## Reproducibility

**The board is no longer reproducible from `tools/gen_pcb.py`.** Re-running the
generator would discard the autorouted host block and the repairs above. The
schematic still is: `tools/gen_schematic.py` regenerates it from
`tools/netlist.py`, and netlist parity passes.

Treat `microphone_array_v2.kicad_pcb` as the source of truth for routing, and
`tools/patch_board.py` as the record of what was changed by hand.
