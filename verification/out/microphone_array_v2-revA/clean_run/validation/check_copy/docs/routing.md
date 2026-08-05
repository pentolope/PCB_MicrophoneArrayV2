# Routing methodology

## Authority

KiCad owns the board. FreeRouting may add or change tracks and vias and
nothing else. Every candidate is imported into a *copy*, compared against a
semantic snapshot of the pre-route board, and only then promoted.

## What is pre-routed, and why

Three classes of copper are placed deterministically by `tools/gen_pcb.py`
rather than by the autorouter:

**Ground stitching.** Ground is a plane net that the autorouter is told to
ignore, and an inner plane cannot reach a surface-mount pad by itself. Every
ground pad therefore gets its own via plus a short connecting track. Via
direction is chosen along the pad's own axes, never diagonally: a diagonal
crosses the neighbouring pin on a fine-pitch package, and on the microphone it
lands in the corner channel the signal pads need.

**Microphone L/R straps.** Pad 2 sits inside the ground ring with a 0.40 mm gap
around it, so it cannot reach a via of its own, and it must not consume one of
the four diagonal corners. It is always on the same net as a neighbour it can
be joined to directly: ground (pad 6) on even channels, the supply pad on odd
channels.

**Microphone escapes.** This is the critical one. The `MSM261DHP006` land
pattern encloses its four signal pads in a ring of ground pads. The straight
gaps are 0.40 mm, which fits no track at all once clearance is counted. The
only way out is the diagonal corner between a side bar and an end bar, which
measures 0.566 mm - enough for a 0.15 mm track with 0.15 mm clearance and
nothing more.

FreeRouting cannot handle those corners in either direction:

- It will not create the escapes itself. It approximates pad outlines with
  bounding octagons (`ShapeSearchTree45Degree.complete_shape: non-IntOctagon
  contained shape, using bounding octagon approximation`), which closes the
  diagonal gap. Left to itself it reports "no connection was found between
  their nets" and finishes with all sixteen microphone clock and data nets
  unrouted.
- It will not accept them as existing wiring either. Given a DSN containing
  them it stalls indefinitely at `Wiring: normalization of net 'PDM_CLK_B3'
  failed` and never starts a routing pass.

The resolution is a handover point. The board given to the autorouter
(`gen_pcb.py --no-escapes`) contains, for each microphone:

- a **via** on each of the three signal nets, sitting where that escape will
  end, just outside the package. A bare via is geometry FreeRouting handles
  without complaint, so it happily routes the rest of each net up to it;
- a **keepout rule area** covering the corridor between the ring and those
  vias, so nothing else is routed through the space the escapes need.

After the candidate is merged, `tools/apply_escapes.py` deletes the keepouts
and draws the escapes into the corridor they reserved, terminating exactly on
the handover vias.

Applying the escapes without reserving the corridor first does not work: the
autorouter fills that space with other nets, and the result came back with 57
shorting-item violations and 103 crossing tracks.

The geometry is identical for all sixteen channels and is generated in
footprint-local coordinates:

| Pad | Path |
|---|---|
| 1 (VDD) | inward through the pad 5 / pad 6 corner |
| 4 (DATA) | inward through the pad 5 / pad 8 corner |
| 3 (CLK) | outward through the pad 7 / pad 8 corner, then up the outside of the left ground bar |

The clock pad needs the detour because it sits on the outward half of the
package while its resistor is inboard. Every corner waypoint is the exact
midpoint of the 0.566 mm gap, giving 0.208 mm to each ground pad, and every
segment is at 45 degrees or orthogonal.

The per-channel 100 nF capacitor is rotated 180 degrees so that its ground pad
- and therefore its stitching via - faces radially inward instead of sitting in
the clock escape corridor.

## FreeRouting invocation

FreeRouting 2.2.4 is pinned by SHA-256 (see [sources.md](sources.md)).

```
java -Xss256m -Xmx6g -jar freerouting-2.2.4.jar --gui.enabled=false \
     -de board.dsn -do board.ses -drc fr-drc.json \
     -mp 6 -mt 4 -inc PLANE
```

`-Xss256m` is required, not an optimisation. With the default thread stack,
FreeRouting 2.2.4 dies about two seconds after loading this board with a
`StackOverflowError` in `PolylineTrace.combine`, recursing on the pre-routed
microphone escapes. The recursion is deep rather than infinite, so a larger
stack clears it; without the flag no candidate is produced at all.

Two constraints have to be applied to the DSN rather than the command line,
because **this version silently ignores the options that would express them**:

- `--router.layers.routable=true,false,false,true` is rejected with
  "Unknown settings property: router.layers.routable ... No field found with
  name or SerializedName: layers", and routing proceeds on all four layers -
  including both ground planes. `tools/patch_dsn.py` instead rewrites the two
  inner layers from `(type signal)` to `(type power)`, which FreeRouting does
  honour.
- KiCad does not carry a track's locked flag into the DSN; every wire exports
  as `(type route)`, which FreeRouting is free to rip up. The same script
  promotes them to `(type protect)`.

`-random_seed` is also rejected by this version, so candidates are varied by
pass count rather than by seed.

Always check the FreeRouting log for `Unknown command line argument` and
`Unknown settings property` warnings. They are warnings, not errors, and the
run continues with the constraint silently dropped. The first routing attempt
on this board ran to completion on all four layers, ground planes included,
because of exactly that.

## End-to-end sequence

```bash
python tools/gen_pcb.py --no-escapes
python tools/kicad_specctra.py export microphone_array_v2.kicad_pcb generated/route/board.dsn
python tools/patch_dsn.py generated/route/board.dsn GND1 GND2
java -Xss256m -Xmx6g -jar freerouting-2.2.4.jar --gui.enabled=false \
     -de generated/route/board.dsn -do generated/route/seed17.ses \
     -drc generated/route/fr-drc.json -mp 6 -mt 4 -inc PLANE
python tools/kicad_specctra.py import microphone_array_v2.kicad_pcb \
     generated/route/seed17.ses generated/route/routed17.kicad_pcb
python tools/merge_routing.py microphone_array_v2.kicad_pcb \
     generated/route/routed17.kicad_pcb generated/route/merged17.kicad_pcb
python tools/kicad_specctra.py compare microphone_array_v2.kicad_pcb \
     generated/route/merged17.kicad_pcb        # must report invariants_equal
python tools/apply_escapes.py generated/route/merged17.kicad_pcb
python tools/check_routes.py generated/route/merged17.kicad_pcb
```

## Why the candidate is merged rather than used directly

**KiCad's SES import must not be allowed to own placement.** Specctra stores
component rotation in whole degrees, and KiCad re-applies the session file's
placement on import. This board is built on 22.5 degree steps, so importing a
candidate silently rounds 33.75 degrees to 34.0 and moves 88 of the 134
footprints. The invariant comparison catches it - `changed_invariants:
["footprints"]`.

`tools/merge_routing.py` therefore keeps the pre-route board as the authority
for footprints, outline, zones and nets, and transplants only the tracks and
vias from the candidate. After merging, the semantic snapshot hash matches the
pre-route board exactly.

Re-running `gen_pcb.py` regenerates the board from the netlist and discards all
routing, so it must not be run after a candidate has been promoted.

## Post-route gates

`tools/check_routes.py` enforces the constraints KiCad's DRC cannot express:

- tracks only on `F.Cu` and `B.Cu`;
- `AUDIO_MCLK` and `MCLK_OSC` on `F.Cu` with zero vias;
- via budgets on the PDM clock nets;
- length spread across the eight clock branches within 6 mm;
- no segment shorter than 0.05 mm and no corner sharper than 45 degrees;
- the ground stitching still intact.

KiCad's own DRC is then the authority for clearance, shorts, holes, edge
clearance and schematic parity, run with `--all-track-errors`,
`--schematic-parity`, `--severity-all` and zero tolerated violations.
