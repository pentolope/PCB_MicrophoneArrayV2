# Manufacturing and bring-up

## Release package

`generated/release/`, built by the clean-room release in a single run from one
board revision:

```bash
"C:/Program Files/KiCad/10.0/bin/python.exe" verification/run.py release verification/boards/live.json
```

It copies the project into an empty directory, purges every pre-existing
output, regenerates everything from the native KiCad files with `kicad-cli`,
re-runs the full validation against what it produced, and publishes only if
every gate passes. The BOM and CPL come from the schematic and the board, not
from the Python model that generated them - a released part list has to be
derived from the thing being manufactured.

| File | Contents |
|---|---|
| `microphone_array_v2-revA-fabrication.zip` | 11 Gerbers and 2 Excellon drills, Protel-named |
| `bom.csv` | JLCPCB BOM, 15 lines |
| `cpl.csv` | JLCPCB pick-and-place, 103 placements, all top side |
| `schematic.pdf` | full schematic |
| `renders/` | top, bottom, underside, the stacking plan and the four copper layers |
| `MANIFEST.md` | SHA-256 of the archive, board and each data file |

### Why the layers are named the way they are

The archive says how many copper layers this board has in its **filenames**,
and nowhere else:

| File | Layer | KiCad |
|---|---|---|
| `microphone_array_v2.GTL` | L1, top copper | `F.Cu` |
| `microphone_array_v2.G2L` | L2, inner ground | `In1.Cu`, exported as `.g1` |
| `microphone_array_v2.G3L` | L3, inner ground | `In2.Cu`, exported as `.g2` |
| `microphone_array_v2.GBL` | L4, bottom copper | `B.Cu` |

Layer order used to travel in the Gerber X2 `FileFunction` attributes while the
files themselves were called `GND1.gbr` and `GND2.gbr`. JLCPCB does not
reliably read those attributes, and a board whose inner layers are named after
the net they carry has nothing left that says they are copper at all - it can
be quoted and built as two-layer. So the export now passes `--no-x2`, ships
Protel extensions, and carries no job file: there is exactly one statement of
the stackup and it is the one the fabricator actually reads.

The mapping lives in `fabrication_naming` in
[verification/boards/live.json](../verification/boards/live.json). The release
renames by it, the archive gate admits by it, and `FAB.LAYER_IDENTITY` proves
after every release that the four copper files are present, distinguishable by
name, carrying real geometry, free of X2 attributes - and that `.G2L` and
`.G3L` are geometrically identical to a fresh single-layer export of `In1.Cu`
and `In2.Cu`. Renaming is all that is done to these files; their contents are
KiCad's, byte for byte.

Aperture macros are left enabled. Disabling them made KiCad draw each rounded
pad corner as a single chord instead of an arc, which cost the front mask 1.4%
of its area and chamfered pad corners by up to 0.073 mm. Nothing needed it -
the layer identification is carried entirely by the filenames - so the artwork
keeps its true pad shapes and the export matches the board to within 0.01 mm.

Gerbers, drills and the CPL share one origin. Verified rather than assumed:
`MK1` appears in the CPL at 53.220 mm from the board centre on the +X axis at
270 degrees, which is exactly where the placement puts it, and the Edge.Cuts
outline spans the matching 120 mm.

### Placement angles

Two separate things happen to a rotation on its way from KiCad into `cpl.csv`,
and they are worth keeping apart because confusing them turns parts.

**Normalisation** puts every angle in `[0, 360)`. KiCad writes rotations in
`(-180, 180]`, so half the array arrived as negative numbers; -157.5 and 202.5
are the same orientation, but only one of them goes through without an
engineering query. This changes no part's orientation and applies to all 103
placements.

**Library-zero offsets** do change orientation, and only for parts whose zero
in JLCPCB's library differs from the footprint's zero in KiCad. Three parts on
this board are affected:

| LCSC | Part | Package | Offset | JLC library zero vs KiCad |
|---|---|---|---:|---|
| `C80670` | LP5907MFX-3.3 | SOT-23-5 | +180 | pins 1-3 on the right, pin 1 lowest |
| `C7668` | SN74LVC244APWR | TSSOP-20 | -90 | pins 1-10 along the bottom |
| `C111212` | USBLC6-4SC6 | SOT-23-6 | -90 | pins 1-3 along the bottom, pin 1 left |

The offsets are looked up by **LCSC number, not by footprint name**, because that
is what the difference is a property of. It matters here: a footprint-regex
table would lump SOT-23-5 in with SOT-23-6 and give the regulator -90 when it
needs 180. Looking them up by part number also makes it impossible for U3 and U4 - the
same device in two places - to be corrected differently.

Each offset was derived from JLCPCB's own library footprint, read through the
EasyEDA API, by comparing every pad against the KiCad footprint rather than
just pin 1: a pin-1 match alone cannot tell a rotation from a mirror. The
derivation is recorded per part in `release_generation.cpl_orientation` in
[verification/boards/live.json](../verification/boards/live.json), and
`CPL.ORIENTATION` re-checks after every release that each shipped angle is the
board angle plus its part's declared offset, normalised.

Nothing else takes an offset, and that is measured rather than assumed. When
JLCPCB revised the first production upload they corrected 11 of the 16
microphones, 11 of 16 damping resistors and so on - and the five left alone in
each family were exactly those already sitting at a multiple of 45 degrees. A
library mismatch is a property of the part, so it would have turned all 16.
The clearest case is `C15850`: `C3` at 0 degrees was untouched while `CB1`-`CB4`
- the same part in the same footprint, at fractional angles - were revised.

**This is a release candidate, not an approved production file.** Upload the
package and step through JLCPCB's Gerber and pick-and-place previews before
paying for it.

## Order options

| Option | Value |
|---|---|
| Layers | 4 |
| Dimensions | 120 mm diameter circle |
| Thickness | 1.6 mm |
| Outer copper | 1 oz |
| Inner copper | 0.5 oz |
| Surface finish | ENIG |
| Solder mask | Green |
| Silkscreen | White |
| Via covering | Plugged (routing vias only) |
| Assembly | Top side only |
| Impedance control | Not required |

## Order remark

```
Four-layer board: L1 top signal / L2 GND / L3 GND / L4 bottom signal.
Both inner layers are solid ground planes; this is intentional.
Plug only the routing vias, which are 0.30 mm finished hole with 0.45 mm pads
and are tented on both sides. Keep every plated through-hole for the two 1x24
module sockets and the 2x13 pin header open, and keep the four 3.2 mm NPTH
mounting holes open. Follow the supplied layer order and the confirm-production
file.
```

## Assembly notes

- All surface-mount parts are on the **top** side. There are no bottom-side
  SMT parts.
- `J1`, `J2` and `J3` are marked DNP and are excluded from the BOM and CPL.
  They are hand-soldered by the customer from the bottom side.
- The four mounting holes and the twenty-four test pads carry no parts.

### Microphone handling

The `MSM261DHP006` datasheet imposes handling limits that must reach the
assembler:

- Moisture sensitivity level 1.
- Maximum three reflow cycles, peak 260 C.
- **Do not board-wash or clean after reflow.** No aqueous wash, no solvents,
  no ultrasonic cleaning.
- Do not apply compressed air or vacuum over the acoustic port, and do not
  place a pick-up nozzle over the port hole.

The first two lines of the top silkscreen carry `PORTS FACE UP - DO NOT WASH`
for this reason. If the assembler's standard process includes a wash step, the
order must be flagged as no-clean.

## Hand-soldered parts

| Ref | Part | Side | Notes |
|---|---|---|---|
| `J2`, `J3` | 1x24 2.54 mm female header | bottom | 0.900 in row spacing; 1.0 mm drills give about 0.18 mm radial slack per pin |
| `J1` | 2x13 2.54 mm pin header | bottom | pin 1 marked by a square pad and a silkscreen triangle |

Fit the module sockets first, then check the Tang Nano 9K seats freely before
soldering the host header.

## Bring-up sequence

1. Inspect the assembled board: all sixteen microphone ports clear, no residue
   over any port, `U1` and `D1` orientation against the silkscreen.
2. With **no** Tang Nano 9K fitted and the host cable disconnected, apply 5 V to
   test pad `5V` through a current-limited supply. Expect well under 5 mA.
   Confirm `3V3A` reads 3.3 V and `3V3C` reads 3.3 V.
3. Fit the Tang Nano 9K. Power from the Pi. Confirm `TANG` reads 3.3 V.
4. Load a bitstream over the module's USB-C. `D1` prevents the USB supply from
   back-feeding the Pi, so both may be connected.
5. Confirm 24.576 MHz on `MCLK` and 3.072 MHz on `PCLK`.
6. Confirm activity on `D0` to `D7`.

The Raspberry Pi must be fed from a supply of at least 1.5 A. This board adds
roughly 200 mA to the Pi's 5 V rail, which an original Model B's input polyfuse
can pass but a marginal phone charger cannot.

### USB-C access

The module hangs below the board on its sockets, with its USB-C connector
facing +X and about 15 mm of carrier overhanging it. With standard 8.5 mm
sockets there is enough gap for a slim USB-C plug, but a thick overmoulded
cable may not fit. Load the bitstream before final assembly, or use a slim or
right-angle cable.

## Regenerating the design

The schematic and the board are both generated from `tools/netlist.py`, which
is the single source of truth. Nothing in the KiCad files should be hand-edited.

```bash
python tools/gen_symbols.py
python tools/gen_schematic.py
python tools/check_netlist_parity.py
python tools/gen_pcb.py
python tools/check_placement.py
python tools/check_routes.py
```

`check_netlist_parity.py` proves the generated schematic carries exactly the
intended netlist. KiCad's own `--schematic-parity` DRC then proves the board
matches the schematic. Note that regenerating the board discards routing, so
run the generators before routing, not after.
