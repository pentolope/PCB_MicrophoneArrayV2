# Status: routing is not finished

**This board is not ready to order.** 197 of 270 connections are routed. 73 are
not, and there are 52 DRC violations.

I did not finish. The two blocks that remain are blocked by placement faults,
not by routing difficulty, and both are described precisely below.

## What passes

| Gate | Result |
|---|---|
| Schematic ERC | 0 violations |
| Netlist parity, schematic vs `tools/netlist.py` | clean, 83 nets, 134 components |
| Placement and array geometry audit | clean, 134 footprints |
| Schematic parity of the board | 0 issues |
| Clock layer and via budget | clean - zero vias, F.Cu only |
| Clock branch length matching | clean - 7.1 mm spread |
| PDM data length | clean |

## What is routed

All generated deterministically by `tools/gen_pcb.py`.

- **Per-channel routing, 32 nets** - supply chain, data link and three escapes
  per channel, in separate tangential lanes.
- **+3V3A distribution ring, 20 connections** - polygon on B.Cu at R = 43.3 mm,
  crossing every radial spoke on the opposite layer, plus a feed from the
  regulator down the right-hand side.
- **PDM clock branches, 8 symmetric trees** - split on each pair's bisector, so
  the two microphones are length-matched by construction (81.9 - 89.0 mm).
  **Zero vias, entirely on F.Cu.**
- **PDM data spokes, 16 legs** - F.Cu outward, B.Cu inward, each net in its own
  lane parallel to the pin row so neighbours do not cross.
- **Power block** - 5 V input chain, PTC, Schottky, regulator and the clock
  rail's ferrite filter. Both rails run as a bus above the component row,
  because routing along the row collides with each part's own ground via.

Clocks own F.Cu inside the handover radius and data owns B.Cu, which is what
stopped those two families fighting over the same annulus.

## What is not routed - 73 connections

| Family | Count | Blocker |
|---|---:|---|
| Host block | 32 | U4 placement, see below |
| Central clock block | 21 | U2 pin escape, see below |
| Residual crossings and stubs | 20 | |

## Blocker 1: the host block escape

The host block has been **restacked** and now audits clean. `J1` is a plain
2x13 pin header rather than a shrouded IDC, and the block runs in signal order
outward to inward:

| | y (mm) |
|---|---:|
| module socket J3 | -11.43 |
| power row | -17.0 / -20.2 |
| series resistors RH1..RH8 | -22.3 |
| ESD arrays U3, U4 | -25.8 |
| Pi header J1 | -29.19 / -31.73 |

Every host signal now travels inward the whole way. Previously the header sat
in the middle of the stack, so each signal ran out to the resistors and back
past the connector, and those doubling-back paths crossed each other. The
resistor row, the ESD assignments and the J6 host pins are all ordered
left-to-right to match where each signal leaves the header.

`route_host_block()` is written but **not called**. What remains is the escape
at the arrays themselves: each `USBLC6-4SC6` has two signal pins per side in a
single column, 1.9 mm apart, so a track cannot simply pass through both. Each
signal needs to enter its pin from the side as a short stub off the main run,
rather than the run being routed through the pin. Called as it stands it closes
24 connections and costs 111 violations.

Note the header's second row sits 2.54 mm *inward* of its origin row, not
outward - worth remembering when moving `PI_HEADER_POS`.

## Blocker 2: the buffer's pin escape

`U2`'s eight inputs interleave with its eight outputs on 0.65 mm pitch. The gap
between adjacent pads is 0.25 mm, which fits no track at any allowed width. The
inputs therefore cannot be bussed on the top layer.

Each input pin needs its own via placed about 1.6 mm off the package edge, with
the bus running on B.Cu, while the outputs escape on F.Cu between those vias.
There is room - via to neighbouring output track works out at 0.35 mm - but it
has to be built deliberately.

The output-to-resistor mapping has already been fixed: outputs are assigned so
each branch leaves on the side its terminating resistor sits on, and in the
order that matches the resistor positions down the column. The obvious
`1Y1..2Y4` order crossed four tracks on one side and sent four more across the
package.

## Also outstanding

- 41 corners still turn more sharply than 45 degrees, and 5 track segments are
  shorter than 0.05 mm. Both come from `path_45()` producing degenerate knees
  when two waypoints are nearly collinear; they need filtering.
- The 52 violations concentrate on `PDM_CLK_B6`, `PDM_D5/6/7` and the ground
  stitching in the lower half.

## On the autorouter

FreeRouting 2.2.4 was tried and abandoned. It failed three ways, documented in
[routing.md](routing.md): it cannot reach the microphone pads at all, it
silently discards per-net layer and via constraints, and it stalls indefinitely
on any board that already has meaningful routing. That last point means there
is no hybrid available - it cannot be handed a partially routed board.

For comparison on this board:

| | FreeRouting | Generated |
|---|---|---|
| Clock branch spread | 15.0 mm | **7.1 mm** |
| Clock vias | 3 per branch | **0** |
| Master clock layer | B.Cu + via | **F.Cu, no via** |
| Copper | 3740 mm | 2210 mm |
