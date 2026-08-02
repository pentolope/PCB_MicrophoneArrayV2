"""Build microphone_array_v2.kicad_pcb from the shared netlist and placement.

Stackup rationale: both inner layers are solid ground rather than the more
usual signal/GND/power/signal. The whole board draws about 200 mA, so the
supplies are comfortable on 0.6 mm tracks, and giving every F.Cu and B.Cu trace
an unbroken adjacent reference plane matters far more here than power-plane
impedance would. It also removes any chance of a PDM clock or data line
crossing a plane split.

Ground is a plane net that the autorouter never sees, so this script places an
explicit stitching via plus a short connecting track at every ground pad.
"""

import math
import os
import sys

import pcbnew

import design as d
import netlist as nl

FOOTPRINT_LIBS = {
    "Resistor_SMD": r"C:\Program Files\KiCad\10.0\share\kicad\footprints\Resistor_SMD.pretty",
    "Capacitor_SMD": r"C:\Program Files\KiCad\10.0\share\kicad\footprints\Capacitor_SMD.pretty",
    "Inductor_SMD": r"C:\Program Files\KiCad\10.0\share\kicad\footprints\Inductor_SMD.pretty",
    "Package_TO_SOT_SMD": r"C:\Program Files\KiCad\10.0\share\kicad\footprints\Package_TO_SOT_SMD.pretty",
    "Package_SO": r"C:\Program Files\KiCad\10.0\share\kicad\footprints\Package_SO.pretty",
    "Diode_SMD": r"C:\Program Files\KiCad\10.0\share\kicad\footprints\Diode_SMD.pretty",
    "Fuse": r"C:\Program Files\KiCad\10.0\share\kicad\footprints\Fuse.pretty",
    "Connector_PinHeader_2.54mm": r"C:\Program Files\KiCad\10.0\share\kicad\footprints\Connector_PinHeader_2.54mm.pretty",
    "Connector_IDC": r"C:\Program Files\KiCad\10.0\share\kicad\footprints\Connector_IDC.pretty",
    "MountingHole": r"C:\Program Files\KiCad\10.0\share\kicad\footprints\MountingHole.pretty",
    "TestPoint": r"C:\Program Files\KiCad\10.0\share\kicad\footprints\TestPoint.pretty",
}

VIA_DIAMETER = 0.45
VIA_DRILL = 0.30
STITCH_CLEARANCE = 0.55
EDGE_INSET = 0.30
PLANE_INSET = 0.50

GROUND_PLANE_LAYERS = (pcbnew.In1_Cu, pcbnew.In2_Cu)


def mm(value):
    return pcbnew.FromMM(float(value))


def vec(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def load_footprint(lib_id, project_root):
    nickname, name = lib_id.split(":", 1)
    path = FOOTPRINT_LIBS.get(nickname)
    if path is None:
        path = os.path.join(project_root, f"{nickname}.pretty")
    footprint = pcbnew.FootprintLoad(path, name)
    if footprint is None:
        raise SystemExit(f"footprint not found: {lib_id} (searched {path})")
    return footprint


# Footprints whose library silkscreen is dropped. Populated from the DRC
# result rather than by guesswork; everything else keeps the library legend so
# the board still matches its footprint library.
SILKSCREEN_STRIP = frozenset()


def strip_silkscreen(footprint):
    """Remove silkscreen graphics from a footprint, keeping copper and fab."""
    doomed = [item for item in footprint.GraphicalItems()
              if item.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS)]
    for item in doomed:
        footprint.Remove(item)


def open_pin_name(ref, pad):
    """Symbol pin name for a deliberately open pin, matching gen_symbols.py."""
    if ref == "U1":
        return "NC"
    if ref == "J1":
        return f"P{pad}_NC"
    labels = d.TANG_J5 if ref == "J2" else d.TANG_J6
    return f"P{pad}_FPGA{labels[int(pad) - 1]}"


def circle_points(radius, count=240, cx=d.PAGE_CX, cy=d.PAGE_CY):
    points = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        points.append((cx + radius * math.cos(angle),
                       cy + radius * math.sin(angle)))
    return points


def build(project_root, with_escapes=True):
    """Build the board. `with_escapes=False` omits the pre-routed microphone
    escapes, which is the form handed to FreeRouting - its polyline normaliser
    hangs on them. They are re-applied afterwards by tools/apply_escapes.py."""
    components, nets = nl.build()
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    board.SetLayerName(pcbnew.In1_Cu, "GND1")
    board.SetLayerName(pcbnew.In2_Cu, "GND2")

    settings = board.GetDesignSettings()
    settings.SetCopperLayerCount(4)

    # ------------------------------------------------------------------
    # Nets
    # ------------------------------------------------------------------
    net_items = {}
    for name in sorted(nets):
        item = pcbnew.NETINFO_ITEM(board, name)
        board.Add(item)
        net_items[name] = item

    pin_net = {}
    for name, pins in nets.items():
        for ref, pad in pins:
            pin_net[(ref, pad)] = name

    # KiCad gives every deliberately open pin an auto-generated net name in the
    # schematic. Reproducing those names here keeps schematic parity clean
    # instead of leaving 39 net_conflict reports to be waived by hand.
    for ref, pad in nl.expected_unconnected():
        pin_name = open_pin_name(ref, pad)
        name = f"unconnected-({ref}-{pin_name}-Pad{pad})"
        item = pcbnew.NETINFO_ITEM(board, name)
        board.Add(item)
        net_items[name] = item
        pin_net[(ref, pad)] = name

    # ------------------------------------------------------------------
    # Footprints
    # ------------------------------------------------------------------
    placed = {}
    silk_reference = {"J1", "J2", "J3"}
    for component in components:
        ref = component["ref"]
        footprint = load_footprint(component["footprint"], project_root)
        board.Add(footprint)
        # Keep the library nickname so schematic parity can match the symbol's
        # footprint field.
        nickname, name = component["footprint"].split(":", 1)
        footprint.SetFPID(pcbnew.LIB_ID(nickname, name))
        footprint.SetReference(ref)
        footprint.SetValue(component["value"])
        footprint.SetLibDescription(component["description"])
        footprint.SetField("Description", component["description"])
        kx, ky = d.to_kicad(component["x"], component["y"])
        footprint.SetPosition(vec(kx, ky))
        if component["side"] == "bottom":
            footprint.Flip(vec(kx, ky), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        footprint.SetOrientationDegrees(component["rot"])
        if component["dnp"]:
            footprint.SetDNP(True)
        if not component["in_bom"]:
            footprint.SetExcludedFromBOM(True)

        for field, value in (("LCSC", component["lcsc"]),
                             ("MPN", component["mpn"]),
                             ("Manufacturer", component["manufacturer"])):
            if value:
                footprint.SetField(field, value)

        # Newly created fields default to being visible on the silkscreen, all
        # stacked on the footprint origin. Hide them and move them to the
        # fabrication layer - they are BOM data, not legend.
        for field in footprint.GetFields():
            if field.GetName() not in ("Reference", "Value"):
                field.SetVisible(False)
                field.SetLayer(pcbnew.B_Fab if footprint.IsFlipped()
                               else pcbnew.F_Fab)

        # The board is dense, so silkscreen designators are kept only for the
        # hand-soldered connectors and the test points. Everything else keeps
        # its designator on the fabrication layer, where JLCPCB's assembly data
        # and the CPL still carry it.
        # Two-terminal passives keep no silkscreen outline. At this density
        # their tiny side bars only collide with neighbouring pads, and they
        # carry no orientation information that assembly needs - JLCPCB places
        # from the CPL. Silkscreen is retained where it means something: the
        # microphone pin-1 mark, the diode polarity bar, the IC and oscillator
        # pin-1 marks, and the connectors.
        if ref in SILKSCREEN_STRIP:
            strip_silkscreen(footprint)

        back = footprint.IsFlipped()
        if ref not in silk_reference:
            footprint.Reference().SetLayer(pcbnew.B_Fab if back else pcbnew.F_Fab)
        if ref.startswith("TP"):
            # The full net name stays on the fabrication layer; a short legend
            # is drawn separately so neighbouring labels do not collide.
            footprint.Value().SetLayer(pcbnew.F_Fab)

        for pad in footprint.Pads():
            name = pin_net.get((ref, pad.GetNumber()))
            if name:
                pad.SetNet(net_items[name])
        placed[ref] = footprint

    # ------------------------------------------------------------------
    # Board outline and ground planes
    # ------------------------------------------------------------------
    outline = pcbnew.PCB_SHAPE(board)
    outline.SetShape(pcbnew.SHAPE_T_CIRCLE)
    outline.SetStart(vec(d.PAGE_CX, d.PAGE_CY))
    outline.SetEnd(vec(d.PAGE_CX + d.BOARD_RADIUS, d.PAGE_CY))
    outline.SetLayer(pcbnew.Edge_Cuts)
    outline.SetWidth(mm(0.1))
    board.Add(outline)

    for layer in GROUND_PLANE_LAYERS:
        zone = pcbnew.ZONE(board)
        zone.SetLayer(layer)
        zone.SetNet(net_items["GND"])
        zone.SetIsFilled(False)
        zone.SetLocalClearance(mm(0.25))
        zone.SetMinThickness(mm(0.2))
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        polygon = zone.Outline()
        polygon.NewOutline()
        for x, y in circle_points(d.BOARD_RADIUS - PLANE_INSET):
            polygon.Append(mm(x), mm(y))
        board.Add(zone)

    strap_count = link_microphone_straps(board, placed, pin_net, net_items)
    if with_escapes:
        strap_count += route_microphone_escapes(board, placed, pin_net, net_items)
        strap_count += route_channel_local(board, placed, pin_net, net_items)
        strap_count += route_supply_ring(board, placed, pin_net, net_items)
        strap_count += route_clock_branches(board, placed, pin_net, net_items)
        strap_count += route_data_spokes(board, placed, pin_net, net_items)
        strap_count += route_power_block(board, placed, pin_net, net_items)
        strap_count += route_supply_ring_feed(board, placed, pin_net, net_items)
        # route_host_block() is written but not yet called. The stack order is
        # now right - connector, ESD, resistors, socket, all flowing inward -
        # but routing *through* a specific ESD pin still needs a proper escape:
        # each array has two signal pins per side in one column, so a track
        # cannot simply pass both. See docs/status.md.
    else:
        strap_count += reserve_microphone_corridors(board, placed, pin_net,
                                                    net_items)
    stitch_count = place_ground_stitching(board, placed, pin_net, net_items)
    add_silkscreen(board)

    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())

    path = os.path.join(project_root, "microphone_array_v2.kicad_pcb")
    board.Save(path)
    apply_project_settings(project_root)
    return path, len(components), len(nets), stitch_count, strap_count


# The MSM261DHP006 land pattern encloses its four signal pads in a ground ring
# with only a 0.40 mm straight gap, so nothing escapes in a straight line. The
# open diagonal corner between the side bar and the end bar is 0.566 mm wide,
# which fits a 0.15 mm track with 0.15 mm clearance and nothing wider. The
# three classes that reach a microphone pad are sized for that escape; they
# carry a few milliamps at most, so the narrower track costs nothing.
NET_CLASSES = [
    # name, track width, clearance, via diameter, via drill
    ("Default", 0.20, 0.20, 0.45, 0.30),
    # 0.15 mm clearance because the microphone escape has to pass a GND pad on
    # both sides of a 0.566 mm diagonal channel; the ground zones keep their
    # own 0.25 mm local clearance for the fill.
    ("PLANE", 0.60, 0.15, 0.60, 0.35),
    ("POWER", 0.60, 0.25, 0.60, 0.35),
    ("MIC_SUPPLY", 0.15, 0.15, 0.45, 0.30),
    # MIC_DOUT is split out of PDM_DATA so the finished per-channel routing can
    # be handed to the autorouter as an ignored class while PDM_D stays live.
    ("MIC_DATA", 0.15, 0.15, 0.45, 0.30),
    ("MANUAL_CRITICAL", 0.15, 0.15, 0.45, 0.30),
    ("PDM_DATA", 0.15, 0.15, 0.45, 0.30),
    ("HOST", 0.20, 0.20, 0.45, 0.30),
]

NET_CLASS_PATTERNS = [
    ("PLANE", "GND"),
    ("POWER", "+5V"), ("POWER", "+3V3A"), ("POWER", "+3V3_CLK"),
    ("POWER", "PI_5V"), ("POWER", "5V_FUSED"), ("POWER", "TANG_3V3"),
    ("MIC_SUPPLY", "MIC_VDD_*"),
    ("MANUAL_CRITICAL", "AUDIO_MCLK"), ("MANUAL_CRITICAL", "MCLK_OSC"),
    ("MANUAL_CRITICAL", "PDM_CLK_*"),
    ("PDM_DATA", "PDM_D?"), ("MIC_DATA", "MIC_DOUT_*"),
    # Listed explicitly rather than as "PI_*", which would also capture PI_5V
    # and put that net in two classes at once.
    ("HOST", "SPI_*"), ("HOST", "HOST_*"),
    ("HOST", "PI_SCLK"), ("HOST", "PI_MOSI"), ("HOST", "PI_MISO"),
    ("HOST", "PI_CS_N"), ("HOST", "PI_IRQ"), ("HOST", "PI_SYNC"),
    ("HOST", "PI_RESET_N"), ("HOST", "PI_STATUS"),
]

# Conservative JLCPCB standard four-layer profile.
BOARD_RULES = {
    "max_error": 0.005,
    "min_clearance": 0.127,
    "min_connection": 0.127,
    "min_copper_edge_clearance": 0.30,
    "min_hole_clearance": 0.25,
    "min_hole_to_hole": 0.25,
    "min_microvia_diameter": 0.20,
    "min_microvia_drill": 0.10,
    "min_resolved_spokes": 2,
    "min_silk_clearance": 0.15,
    "min_text_height": 1.0,
    "min_text_thickness": 0.15,
    "min_through_hole_diameter": 0.30,
    "min_track_width": 0.127,
    "min_via_annular_width": 0.075,
    "min_via_diameter": 0.45,
    "solder_mask_to_copper_clearance": 0.0,
    "use_height_for_length_calcs": True,
}


def apply_project_settings(project_root):
    """Re-apply design rules and net classes after pcbnew rewrites the project.

    Saving a board from the Python API resets the sibling .kicad_pro to
    defaults, so the curated rules are written back here rather than being
    maintained by hand.
    """
    import json

    path = os.path.join(project_root, "microphone_array_v2.kicad_pro")
    with open(path, "r", encoding="utf-8") as handle:
        project = json.load(handle)

    design = project.setdefault("board", {}).setdefault("design_settings", {})
    design.setdefault("rules", {}).update(BOARD_RULES)
    design["track_widths"] = [0.0, 0.127, 0.20, 0.25, 0.30, 0.60, 1.00]
    design["via_dimensions"] = [
        {"diameter": 0.0, "drill": 0.0},
        {"diameter": 0.45, "drill": 0.30},
        {"diameter": 0.60, "drill": 0.35},
    ]

    classes = []
    for name, track, clearance, via_d, via_drill in NET_CLASSES:
        classes.append({
            "bus_width": 12, "clearance": clearance,
            "diff_pair_gap": 0.25, "diff_pair_width": 0.2,
            "line_style": 0, "microvia_diameter": 0.3, "microvia_drill": 0.1,
            "name": name,
            "pcb_color": "rgba(0, 0, 0, 0.000)",
            "schematic_color": "rgba(0, 0, 0, 0.000)",
            "track_width": track, "via_diameter": via_d, "via_drill": via_drill,
            "wire_width": 6,
        })

    project["net_settings"] = {
        "classes": classes,
        "meta": {"version": 4},
        "net_colors": None,
        "netclass_assignments": None,
        "netclass_patterns": [{"netclass": cls, "pattern": pattern}
                              for cls, pattern in NET_CLASS_PATTERNS],
    }

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(project, handle, indent=2)
        handle.write("\n")


def choose_stitch_position(pad, footprint, position, obstacles, vias_placed):
    """Pick a clear spot just outside a ground pad for its stitching via.

    A simple "straight out from the footprint centre" rule fails on fine-pitch
    packages, where the diagonal runs straight across a neighbouring pad. So
    candidate directions are scored and the roomiest clear one wins.
    """
    size = pad.GetSize()
    centre = footprint.GetPosition()
    via_radius = mm(VIA_DIAMETER / 2.0)
    needed = mm(STITCH_CLEARANCE) + via_radius

    # Leave along one of the pad's own axes, never on a diagonal. A diagonal
    # runs across the neighbouring pin on a fine-pitch package, and on the
    # microphone it lands in the corner channel that the signal pads escape
    # through. Among the axes pointing away from the footprint centre, take
    # the one that clears the rest of this footprint by the widest margin.
    base_x = position.x - centre.x
    base_y = position.y - centre.y
    if base_x == 0 and base_y == 0:
        base_x, base_y = 0, 1
    norm = math.hypot(base_x, base_y)
    outward = (base_x / norm, base_y / norm)

    siblings = [p for p in footprint.Pads() if p.GetPosition() != position]
    pad_angle = math.radians(pad.GetOrientationDegrees())
    candidates = []
    for quarter in range(4):
        angle = pad_angle + quarter * math.pi / 2.0
        ux, uy = math.cos(angle), math.sin(angle)
        if ux * outward[0] + uy * outward[1] <= 0.1:
            continue
        reach = abs(ux) * size.x / 2.0 + abs(uy) * size.y / 2.0
        probe_x = position.x + ux * (reach + needed)
        probe_y = position.y + uy * (reach + needed)
        room = min((math.hypot(probe_x - p.GetPosition().x,
                               probe_y - p.GetPosition().y)
                    - math.hypot(p.GetSize().x, p.GetSize().y) / 2.0
                    for p in siblings), default=math.inf)
        candidates.append((-room, ux, uy))
    if not candidates:
        candidates = [(0.0, outward[0], outward[1])]
    candidates.sort()

    for _rank, ux, uy in candidates:
        reach = abs(ux) * size.x / 2.0 + abs(uy) * size.y / 2.0
        for extra in (0.0, mm(0.25), mm(0.5)):
            distance = reach + needed + extra
            candidate = pcbnew.VECTOR2I(int(position.x + ux * distance),
                                        int(position.y + uy * distance))
            clearance = math.inf
            for other_position, other_radius, other_net in obstacles:
                if other_position == position:
                    continue
                gap = (math.hypot(candidate.x - other_position.x,
                                  candidate.y - other_position.y)
                       - other_radius - via_radius)
                if other_net == "GND":
                    gap += mm(0.5)  # same-net crowding matters less
                clearance = min(clearance, gap)
            for other in vias_placed:
                gap = (math.hypot(candidate.x - other.x, candidate.y - other.y)
                       - 2 * via_radius - mm(0.25))
                clearance = min(clearance, gap)
            if clearance >= mm(0.2):
                return candidate
    return None


def local_to_board(footprint, lx, ly):
    """Map footprint-local millimetres to a board position."""
    angle = math.radians(footprint.GetOrientationDegrees())
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    dx = lx * cos_a + ly * sin_a
    dy = -lx * sin_a + ly * cos_a
    origin = footprint.GetPosition()
    return pcbnew.VECTOR2I(int(origin.x + mm(dx)), int(origin.y + mm(dy)))


def board_to_local(footprint, position):
    """Inverse of local_to_board, in millimetres."""
    angle = math.radians(footprint.GetOrientationDegrees())
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    origin = footprint.GetPosition()
    dx = (position.x - origin.x) / 1e6
    dy = (position.y - origin.y) / 1e6
    return (dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a)


# Escape paths in microphone-footprint-local millimetres. Local +Y points
# radially inward, so every path ends inward where the channel's own resistors
# and capacitor sit. The diagonal waypoints at (+/-0.85, +/-1.35) are the exact
# midpoints of the 0.566 mm corner gaps in the ground ring, which is the only
# way out of the ring; the clock path additionally runs up the outside of the
# left-hand ground bar because its pad is on the outward half of the package.
MIC_ESCAPES = {
    # supply and data pads are already on the inward half, so each leaves
    # straight through its own diagonal corner
    "1": [(0.45, 0.675), (0.45, 0.95), (0.85, 1.35), (1.20, 1.70), (1.20, 3.40)],
    "4": [(-0.45, 0.675), (-0.45, 0.95), (-0.85, 1.35), (-1.20, 1.70),
          (-1.20, 3.40)],
    # the clock pad is on the outward half, so it leaves through the outward
    # corner and then runs up the outside of the left ground bar
    # stops short of the others: the channel's decoupling capacitor sits at
    # local y ~ 4.0 on this side, so the handover via has to stay inboard of it
    "3": [(-0.45, -0.675), (-0.45, -0.95), (-0.85, -1.35), (-1.20, -1.70),
          (-2.15, -1.70), (-2.45, -1.40), (-2.45, 2.60)],
}

# Corridor reserved for the escapes above, in footprint-local millimetres.
# A keepout of this shape is placed for the autorouter and removed again once
# the escapes are drawn.
MIC_CORRIDOR = (-2.95, -2.75, 1.75, 3.15)  # left, top, right, bottom

# Ground stitching vias for the microphone are placed explicitly rather than by
# search, so that the short track from each ground bar to its via never crosses
# one of the escape corridors above.
MIC_GND_VIAS = {
    "5": (0.0, 2.85),
    "6": (1.95, 0.0),
    "7": (0.0, -2.85),
    "8": (-1.95, 0.0),
}


def path_45(start, end):
    """Two-segment path from start to end using only 45 degree geometry.

    Travels diagonally for the shorter axis, then straight along the longer
    one, so the single corner is always a 45 degree turn.
    """
    dx = end.x - start.x
    dy = end.y - start.y
    if dx == 0 or dy == 0 or abs(dx) == abs(dy):
        return [start, end]
    step = min(abs(dx), abs(dy))
    knee = pcbnew.VECTOR2I(
        int(start.x + step * (1 if dx > 0 else -1)),
        int(start.y + step * (1 if dy > 0 else -1)))
    return [start, knee, end]


def add_via(board, net, position, offset_mm=0.0):
    """Place a tented through via on `net`, optionally pushed radially inward."""
    target = position
    if offset_mm:
        centre_x, centre_y = mm(d.PAGE_CX), mm(d.PAGE_CY)
        dx, dy = centre_x - position.x, centre_y - position.y
        length = math.hypot(dx, dy) or 1.0
        step = mm(offset_mm) / length
        target = pcbnew.VECTOR2I(int(position.x + dx * step),
                                 int(position.y + dy * step))
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(target)
    via.SetWidth(mm(VIA_DIAMETER))
    via.SetDrill(mm(VIA_DRILL))
    via.SetNet(net)
    via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    via.SetFrontTentingMode(pcbnew.TENTING_MODE_TENTED)
    via.SetBackTentingMode(pcbnew.TENTING_MODE_TENTED)
    board.Add(via)
    return target


def add_track(board, net, layer, width_mm, points, locked=True):
    """Lay a polyline of tracks on one layer and net."""
    count = 0
    for a, b in zip(points, points[1:]):
        if a.x == b.x and a.y == b.y:
            continue
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(a)
        track.SetEnd(b)
        track.SetWidth(mm(width_mm))
        track.SetLayer(layer)
        track.SetNet(net)
        track.SetLocked(locked)
        board.Add(track)
        count += 1
    return count


def route_microphone_escapes(board, placed, pin_net, net_items):
    """Pre-route each microphone's three signal pads out of its ground ring.

    FreeRouting approximates pad outlines with bounding octagons, which closes
    the narrow diagonal corners and leaves these nets unrouted. The geometry is
    identical for all sixteen channels, so it is laid down deterministically
    here and locked, and the autorouter only has to pick the paths up outside
    the package.
    """
    count = 0
    for k in range(d.MIC_COUNT):
        ref = f"MK{k + 1}"
        footprint = placed[ref]
        pads = {pad.GetNumber(): pad for pad in footprint.Pads()}

        for number, path in MIC_ESCAPES.items():
            net_name = pin_net[(ref, number)]
            # Confirm the local frame really lands on the pad before drawing.
            start = local_to_board(footprint, *path[0])
            actual = pads[number].GetPosition()
            if abs(start.x - actual.x) > 2000 or abs(start.y - actual.y) > 2000:
                raise SystemExit(
                    f"{ref} pad {number}: local frame mismatch, "
                    f"computed {start.x},{start.y} actual {actual.x},{actual.y}")

            points = [actual] + [local_to_board(footprint, x, y)
                                 for x, y in path[1:]]
            count += add_track(board, net_items[net_name], pcbnew.F_Cu, 0.15,
                               points)
    return count


# Per-channel routing, in microphone-local millimetres. Local +Y is inward.
# Every path is 45 degree geometry and stays on the tangential side its escape
# leaves from, so the supply, data and clock nets of a channel never cross.
CHANNEL_ROUTES = [
    # MIC_VDD: supply escape -> decoupling capacitor -> isolation resistor
    ("1", [(1.20, 3.40), (1.79, 3.99), (2.21, 3.99)]),
    ("1", [(2.21, 3.99), (2.42, 4.20), (5.27, 4.20)]),
    # MIC_DOUT: data escape -> damping resistor, entering on its outward pad
    ("4", [(-1.20, 3.40), (0.00, 4.60), (0.00, 7.71)]),
]


def route_channel_local(board, placed, pin_net, net_items):
    """Route each channel's supply and data nets within its own cluster."""
    count = 0
    for k in range(d.MIC_COUNT):
        ref = f"MK{k + 1}"
        footprint = placed[ref]
        for number, path in CHANNEL_ROUTES:
            net = net_items[pin_net[(ref, number)]]
            points = [local_to_board(footprint, x, y) for x, y in path]
            count += add_track(board, net, pcbnew.F_Cu, 0.15, points)
    return count


# The ring sits in the one clear annulus: outside the module socket pins and
# the host block, inside the channels' own data resistors.
SUPPLY_RING_RADIUS = 43.3
SUPPLY_RING_WIDTH = 0.6
SUPPLY_STUB_WIDTH = 0.5
SUPPLY_RING_MAX_STEP_DEG = 11.25  # keeps chord sag off the host block


def route_supply_ring(board, placed, pin_net, net_items):
    """Distribute +3V3A to the ring as a polygon on B.Cu.

    A ring necessarily crosses every radial spoke, so it goes on the bottom
    layer where the spokes are not: the clock and data runs stay on F.Cu, and
    the two only meet at vias. Vertices sit exactly at the connection angles,
    so every turn is well under 45 degrees and each consumer is a short radial
    stub up to the top layer.
    """
    net = net_items["+3V3A"]
    centre_x, centre_y = mm(d.PAGE_CX), mm(d.PAGE_CY)

    consumers = []
    for k in range(d.MIC_COUNT):
        consumers.append((f"RV{k + 1}", "1"))
    for i in range(4):
        consumers.append((f"CB{i + 1}", "1"))

    nodes = []
    for ref, pad_number in consumers:
        footprint = placed[ref]
        pad = next(p for p in footprint.Pads() if p.GetNumber() == pad_number)
        position = pad.GetPosition()
        angle = math.atan2(position.y - centre_y, position.x - centre_x)
        nodes.append((angle % (2 * math.pi), position))
    nodes.sort()

    count = 0
    ring_points = []
    for angle, pad_position in nodes:
        vertex = pcbnew.VECTOR2I(
            int(centre_x + mm(SUPPLY_RING_RADIUS) * math.cos(angle)),
            int(centre_y + mm(SUPPLY_RING_RADIUS) * math.sin(angle)))
        ring_points.append(vertex)
        add_via(board, net, vertex)
        count += add_track(board, net, pcbnew.F_Cu, SUPPLY_STUB_WIDTH,
                           [vertex, pad_position])

    # Subdivide long spans so the chords do not sag inward onto the host block.
    angles = [angle for angle, _position in nodes]
    step = math.radians(SUPPLY_RING_MAX_STEP_DEG)
    path = []
    for i, angle in enumerate(angles):
        nxt = angles[(i + 1) % len(angles)]
        span = (nxt - angle) % (2 * math.pi)
        divisions = max(1, int(math.ceil(span / step)))
        for j in range(divisions):
            a = angle + span * j / divisions
            path.append(pcbnew.VECTOR2I(
                int(centre_x + mm(SUPPLY_RING_RADIUS) * math.cos(a)),
                int(centre_y + mm(SUPPLY_RING_RADIUS) * math.sin(a))))
    for a, b in zip(path, path[1:] + path[:1]):
        count += add_track(board, net, pcbnew.B_Cu, SUPPLY_RING_WIDTH, [a, b])
    return count


SPOKE_HANDOVER_RADIUS = 41.5
CLOCK_WIDTH = 0.25


def polar_point(radius, degrees):
    """Board position at a polar coordinate, in KiCad units."""
    x, y = d.polar(radius, degrees)
    kx, ky = d.to_kicad(x, y)
    return vec(kx, ky)


def board_angle(position):
    """Azimuth of a board position in design degrees, counter-clockwise."""
    dx = position.x / 1e6 - d.PAGE_CX
    dy = -(position.y / 1e6 - d.PAGE_CY)
    return math.degrees(math.atan2(dy, dx)) % 360.0


def board_radius(position):
    return math.hypot(position.x / 1e6 - d.PAGE_CX,
                      position.y / 1e6 - d.PAGE_CY)


SOCKET_ROW_CLEARANCE = 2.2


def pin_rows():
    """Every through-hole pin row that a track may have to cross.

    Both module sockets and both rows of the Pi header. Each entry is
    (row y, list of pin x positions) in design millimetres.
    """
    socket_x = [d.tang_socket_x(n) for n in range(1, d.TANG_PINS + 1)]
    header_x = [d.PI_HEADER_POS[0] + 15.24 - 2.54 * k for k in range(13)]
    return [
        (d.TANG_ROW_SPACING / 2.0, socket_x),
        (-d.TANG_ROW_SPACING / 2.0, socket_x),
        (d.PI_HEADER_POS[1] + 1.27, header_x),          # odd row
        (d.PI_HEADER_POS[1] + 1.27 + d.TANG_PITCH, header_x),  # even row
    ]


def thread_socket_rows(start, end):
    """Waypoints for a run that has to cross a row of through-hole pins.

    Those rows are solid walls of pads. A straight run into one lands on a pin,
    so each crossing is snapped to the midpoint between two adjacent pins,
    where 2.54 mm pitch on 1.0 mm drills leaves 1.54 mm of clear space - ample
    for a 0.25 mm track at 0.25 mm hole clearance.
    """
    ax, ay = start.x / 1e6 - d.PAGE_CX, -(start.y / 1e6 - d.PAGE_CY)
    bx, by = end.x / 1e6 - d.PAGE_CX, -(end.y / 1e6 - d.PAGE_CY)
    if by == ay:
        return []

    points = []
    for row, pins in pin_rows():
        if (ay - row) * (by - row) >= 0:
            continue
        t = (row - ay) / (by - ay)
        cross_x = ax + t * (bx - ax)
        if not (min(pins) - 1.0 <= cross_x <= max(pins) + 1.0):
            continue  # already passes beyond the end of the row
        gap = min((x - d.TANG_PITCH / 2.0 for x in pins),
                  key=lambda g: abs(g - cross_x))
        step = SOCKET_ROW_CLEARANCE if ay > row else -SOCKET_ROW_CLEARANCE
        points.append((t, (gap, row + step)))
        points.append((t, (gap, row - step)))

    points.sort(key=lambda item: item[0])
    return [vec(*d.to_kicad(x, y)) for _t, (x, y) in points]


# Lateral corridor used to get past the Pi header, which together with the ESD
# parts and the series resistors blocks the whole lower centre of the board.
HOST_DETOUR_X = 26.0
HOST_DETOUR_Y = -43.0
HOST_BLOCK_HALF_WIDTH = 22.0
HOST_BLOCK_TOP_Y = -25.0


def host_block_detour(start, end):
    """Waypoints taking a bottom-layer run around the Pi header block."""
    ex = end.x / 1e6 - d.PAGE_CX
    ey = -(end.y / 1e6 - d.PAGE_CY)
    if ey > HOST_BLOCK_TOP_Y or abs(ex) > HOST_BLOCK_HALF_WIDTH:
        return []
    side = HOST_DETOUR_X if ex >= 0 else -HOST_DETOUR_X
    return [vec(*d.to_kicad(side, -8.0)),
            vec(*d.to_kicad(side, HOST_DETOUR_Y)),
            vec(*d.to_kicad(ex, HOST_DETOUR_Y))]


def order_waypoints(start, end, points):
    """Keep inserted waypoints in travel order and drop duplicates."""
    ordered, seen = [], set()
    for point in points:
        key = (point.x, point.y)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(point)
    return ordered


def pad_axis_via(board, net, footprint, from_pad, to_pad, distance_mm=1.6):
    """Place a via just beyond `to_pad`, along the part's own pad axis.

    Offsetting towards the board centre instead drops the via onto the
    component's other pad on half the placements.
    """
    pads = {p.GetNumber(): p.GetPosition() for p in footprint.Pads()}
    a, b = pads[from_pad], pads[to_pad]
    dx, dy = b.x - a.x, b.y - a.y
    length = math.hypot(dx, dy) or 1.0
    target = pcbnew.VECTOR2I(int(b.x + dx / length * mm(distance_mm)),
                             int(b.y + dy / length * mm(distance_mm)))
    return add_via(board, net, target)


def route_clock_branches(board, placed, pin_net, net_items):
    """Route each PDM clock branch as a symmetric tree to its two channels.

    The branch leaves its series resistor, drops to B.Cu for the run out
    through the module-socket area, and comes back up at a split point placed
    on the bisector of its two landing angles. The two arms from there are
    mirror images, so the pair is length-matched by construction rather than by
    tuning - which is the thing an autorouter could not give us.
    """
    count = 0
    for branch in range(8):
        net = net_items[f"PDM_CLK_B{branch}"]
        resistor = placed[f"RC{branch + 1}"]
        source = next(p.GetPosition() for p in resistor.Pads()
                      if p.GetNumber() == "2")

        landings = []
        for index in (2 * branch, 2 * branch + 1):
            microphone = placed[f"MK{index + 1}"]
            landings.append(local_to_board(microphone, *MIC_ESCAPES["3"][-1]))
        split_angle = sum(board_angle(p) for p in landings) / 2.0
        split = polar_point(SPOKE_HANDOVER_RADIUS, split_angle)

        # Resistor to split point, staying on F.Cu and threading between the
        # socket pins. The data spokes own B.Cu inside the handover radius, so
        # keeping the clocks on top separates the two families by layer instead
        # of letting them fight over the same annulus. It also leaves every
        # clock branch with no vias at all.
        waypoints = [source] + thread_socket_rows(source, split) + [split]
        for a, b in zip(waypoints, waypoints[1:]):
            count += add_track(board, net, pcbnew.F_Cu, CLOCK_WIDTH,
                               path_45(a, b))

        # split point -> each microphone on F.Cu, entering down the same clear
        # tangential lane the escape leaves by, so the arm never crosses the
        # channel's own resistors or capacitor
        for landing in landings:
            entry = polar_point(SPOKE_HANDOVER_RADIUS, board_angle(landing))
            count += add_track(board, net, pcbnew.F_Cu, CLOCK_WIDTH,
                               path_45(split, entry))
            count += add_track(board, net, pcbnew.F_Cu, CLOCK_WIDTH,
                               [entry, landing])
    return count


DATA_WIDTH = 0.2
# Lane offsets from the pin row, one per data net on that row, ordered so the
# net that reaches furthest along the row travels closest to it.
DATA_LANE_OFFSETS = (5.4, 4.6, 3.8, 3.0)


def socket_pin_for(net_name):
    """Which module socket pin a net is assigned to."""
    for (ref, position), name in d.TANG_NET_MAP.items():
        if name == net_name:
            return ref, position
    raise SystemExit(f"{net_name} is not assigned to a module pin")


def route_data_spokes(board, placed, pin_net, net_items):
    """Bring each pair's PDM data line in to its FPGA socket pin.

    The outer leg is a radial run on F.Cu, in the same lane the channel's own
    damping resistor sits on, then the line drops to B.Cu at the handover
    radius and crosses the module sockets between pins. The clock branches use
    F.Cu outside that radius and B.Cu inside, so the two families share the
    board without ever meeting on a layer.
    """
    count = 0
    for k in range(d.MIC_COUNT):
        pair = k // 2
        net = net_items[f"PDM_D{pair}"]
        microphone = placed[f"MK{k + 1}"]
        resistor = placed[f"RD{k + 1}"]
        source = next(p.GetPosition() for p in resistor.Pads()
                      if p.GetNumber() == "2")

        entry = polar_point(SPOKE_HANDOVER_RADIUS, board_angle(source))
        count += add_track(board, net, pcbnew.F_Cu, DATA_WIDTH, [source, entry])
        add_via(board, net, entry)

        socket_ref, position = socket_pin_for(f"PDM_D{pair}")
        socket = placed[socket_ref]
        target = next(p.GetPosition() for p in socket.Pads()
                      if p.GetNumber() == str(position))
        # Each net gets its own lane parallel to the pin row, and only runs
        # along it as far as its own pin. Cutting diagonally to the pin instead
        # makes neighbouring data lines cross each other.
        row_y = d.TANG_ROW_SPACING / 2.0 * (1 if socket_ref == "J2" else -1)
        sign = 1.0 if row_y > 0 else -1.0
        lane_y = row_y + sign * DATA_LANE_OFFSETS[pair % 4]
        pin_x = d.tang_socket_x(position)
        approach = vec(*d.to_kicad(pin_x, row_y + sign * 2.0))
        lane_turn = vec(*d.to_kicad(pin_x, lane_y))

        waypoints = ([entry] + thread_socket_rows(entry, lane_turn)
                     + [lane_turn, approach])
        for a, b in zip(waypoints, waypoints[1:]):
            count += add_track(board, net, pcbnew.B_Cu, DATA_WIDTH,
                               path_45(a, b))
        count += add_track(board, net, pcbnew.B_Cu, DATA_WIDTH,
                           [approach, target])
    return count


POWER_WIDTH = 0.6
SIGNAL_WIDTH = 0.2
# Parts in the power row, whose ground vias must clear the supply bus.
POWER_ROW_REFS = frozenset(["C1", "C2", "C3", "C4", "C5", "C9", "U1"])


def pad_at(placed, ref, number):
    footprint = placed[ref]
    return next(p.GetPosition() for p in footprint.Pads()
                if p.GetNumber() == str(number))


def chain(board, net_items, name, layer, width, nodes, placed):
    """Route a net through an ordered list of pads and explicit waypoints."""
    net = net_items[name]
    points = []
    for node in nodes:
        if isinstance(node, tuple) and len(node) == 2 and isinstance(node[0], str):
            points.append(pad_at(placed, node[0], node[1]))
        else:
            points.append(vec(*d.to_kicad(node[0], node[1])))
    count = 0
    for a, b in zip(points, points[1:]):
        for x, y in zip(path_45(a, b), path_45(a, b)[1:]):
            count += add_track(board, net, layer, width, [x, y])
    return count


def route_power_block(board, placed, pin_net, net_items):
    """Route the 5 V input chain, the LDO and the clock rail filter."""
    count = 0
    # The 5 V feed runs on B.Cu: the top layer between the header and the power
    # row is fully occupied by that row's own pads and ground stitching.
    net = net_items["PI_5V"]
    count += add_track(board, net, pcbnew.F_Cu, POWER_WIDTH,
                       [pad_at(placed, "J1", 2), pad_at(placed, "J1", 4)])
    fuse_via = add_via(board, net, vec(*d.to_kicad(-23.14, -21.60)))
    count += add_track(board, net, pcbnew.F_Cu, POWER_WIDTH,
                       [pad_at(placed, "F1", 1), fuse_via])
    run = [pad_at(placed, "J1", 4),
           vec(*d.to_kicad(12.70, -21.60)),
           fuse_via]
    for a, b in zip(run, run[1:]):
        count += add_track(board, net, pcbnew.B_Cu, POWER_WIDTH, path_45(a, b))
    count += chain(board, net_items, "5V_FUSED", pcbnew.F_Cu, POWER_WIDTH, [
        ("F1", 2), ("D1", 2)], placed)
    # Both rails run as a bus just above the component row. Routing along the
    # row itself collides with each part's own ground pad and stitching via.
    bus = -14.60
    count += chain(board, net_items, "+5V", pcbnew.F_Cu, POWER_WIDTH, [
        ("D1", 1), (-15.50, bus), (-7.45, bus), ("C4", 1)], placed)
    count += chain(board, net_items, "+5V", pcbnew.F_Cu, POWER_WIDTH, [
        (-7.45, bus), (-2.28, bus), ("C1", 1)], placed)
    count += chain(board, net_items, "+5V", pcbnew.F_Cu, POWER_WIDTH, [
        (-2.28, bus), (1.86, bus), ("U1", 1)], placed)
    count += chain(board, net_items, "+5V", pcbnew.F_Cu, SIGNAL_WIDTH, [
        ("C4", 1), (-7.45, -19.60), ("C5", 1)], placed)
    # EN is strapped to IN down the free side of the package.
    count += chain(board, net_items, "+5V", pcbnew.F_Cu, SIGNAL_WIDTH, [
        ("U1", 1), (0.30, -16.05), (0.30, -17.95), ("U1", 3)], placed)
    count += chain(board, net_items, "+5V", pcbnew.F_Cu, POWER_WIDTH, [
        (-2.28, bus), (-3.97, -13.30), ("J3", 18)], placed)
    # LDO output joins a matching bus on the far side.
    out_bus = -14.60
    count += chain(board, net_items, "+3V3A", pcbnew.F_Cu, POWER_WIDTH, [
        ("U1", 5), (4.14, out_bus), (6.72, out_bus), ("C2", 1)], placed)
    count += chain(board, net_items, "+3V3A", pcbnew.F_Cu, POWER_WIDTH, [
        (6.72, out_bus), (11.44, out_bus), ("FB1", 1)], placed)
    count += chain(board, net_items, "+3V3A", pcbnew.F_Cu, POWER_WIDTH, [
        ("C2", 1), (6.55, -18.60), ("C3", 1)], placed)
    count += chain(board, net_items, "+3V3_CLK", pcbnew.F_Cu, POWER_WIDTH, [
        ("FB1", 2), ("C9", 1)], placed)
    return count


def route_supply_ring_feed(board, placed, pin_net, net_items):
    """Carry +3V3A from the regulator out to the distribution ring.

    It goes down the right-hand side on B.Cu, clear of the Pi header pads, and
    meets the ring on a radial approach.
    """
    net = net_items["+3V3A"]
    start = pad_at(placed, "C3", 1)
    drop = add_via(board, net, vec(*d.to_kicad(6.55, -21.60)))
    count = add_track(board, net, pcbnew.F_Cu, POWER_WIDTH, [start, drop])

    landing_angle = 302.0
    landing = polar_point(SUPPLY_RING_RADIUS, landing_angle)
    waypoints = [drop,
                 vec(*d.to_kicad(19.00, -21.60)),
                 vec(*d.to_kicad(23.00, -25.60)),
                 vec(*d.to_kicad(23.00, -33.00)),
                 landing]
    for a, b in zip(waypoints, waypoints[1:]):
        count += add_track(board, net, pcbnew.B_Cu, POWER_WIDTH, path_45(a, b))
    return count


def route_host_block(board, placed, pin_net, net_items):
    """Route the Pi header through its ESD arrays and series resistors.

    Each signal runs connector -> ESD array -> series resistor on F.Cu, then
    back up to its socket pin on B.Cu. The return leg has to cross both rows of
    the header, so it is threaded between pins.
    """
    links = [
        # (Pi-side net, board-side net, ESD ref, ESD pin, resistor ref)
        ("PI_SCLK", "SPI_SCLK", "U3", "1", "RH1"),
        ("PI_MOSI", "SPI_MOSI", "U3", "3", "RH2"),
        ("PI_MISO", "SPI_MISO", "U3", "4", "RH3"),
        ("PI_CS_N", "SPI_CS_N", "U3", "6", "RH4"),
        ("PI_IRQ", "HOST_IRQ", "U4", "1", "RH5"),
        ("PI_SYNC", "HOST_SYNC", "U4", "3", "RH6"),
        ("PI_RESET_N", "HOST_RESET_N", "U4", "4", "RH7"),
        ("PI_STATUS", "HOST_STATUS", "U4", "6", "RH8"),
    ]
    header_pin = {}
    for pin, name in d.PI_HEADER.items():
        if name.startswith("PI_") and name != "PI_5V":
            header_pin[name] = pin

    count = 0
    for pi_net, board_net, esd, esd_pin, resistor in links:
        net = net_items[pi_net]

        # connector -> ESD array
        start = pad_at(placed, "J1", header_pin[pi_net])
        middle = pad_at(placed, esd, esd_pin)
        run = [start] + thread_socket_rows(start, middle) + [middle]
        for a, b in zip(run, run[1:]):
            count += add_track(board, net, pcbnew.F_Cu, SIGNAL_WIDTH,
                               path_45(a, b))

        # ESD array -> series resistor
        end = pad_at(placed, resistor, "1")
        count += add_track(board, net, pcbnew.F_Cu, SIGNAL_WIDTH,
                           path_45(middle, end))

        # series resistor -> socket pin, on the bottom layer
        net = net_items[board_net]
        source = pad_at(placed, resistor, "2")
        socket_ref, position = socket_pin_for(board_net)
        target = pad_at(placed, socket_ref, position)
        drop = add_via(board, net, pcbnew.VECTOR2I(
            source.x, source.y - mm(1.4)))
        count += add_track(board, net, pcbnew.F_Cu, SIGNAL_WIDTH,
                           [source, drop])
        run = [drop] + thread_socket_rows(drop, target) + [target]
        for a, b in zip(run, run[1:]):
            count += add_track(board, net, pcbnew.B_Cu, SIGNAL_WIDTH,
                               path_45(a, b))
    return count


def reserve_microphone_corridors(board, placed, pin_net, net_items):
    """Prepare the board the autorouter sees.

    Each escape ends on a via placed just outside the microphone, and the
    corridor leading to it is covered by a keepout. The autorouter can reach a
    bare via perfectly well, so it routes the rest of each net up to that
    handover point while staying out of the corridor. The keepouts are deleted
    again by tools/apply_escapes.py once the escapes are drawn.
    """
    vias = 0
    for k in range(d.MIC_COUNT):
        ref = f"MK{k + 1}"
        footprint = placed[ref]

        for number, path in MIC_ESCAPES.items():
            net = net_items[pin_net[(ref, number)]]
            add_via(board, net, local_to_board(footprint, *path[-1]))
            vias += 1

        left, top, right, bottom = MIC_CORRIDOR
        keepout = pcbnew.ZONE(board)
        keepout.SetIsRuleArea(True)
        keepout.SetDoNotAllowTracks(True)
        keepout.SetDoNotAllowVias(True)
        keepout.SetDoNotAllowZoneFills(False)
        keepout.SetLayer(pcbnew.F_Cu)
        keepout.SetZoneName(f"MIC_ESCAPE_{ref}")
        outline = keepout.Outline()
        outline.NewOutline()
        for lx, ly in ((left, top), (right, top), (right, bottom),
                       (left, bottom)):
            point = local_to_board(footprint, lx, ly)
            outline.Append(point.x, point.y)
        board.Add(keepout)
    return vias


def link_microphone_straps(board, placed, pin_net, net_items):
    """Pre-route each microphone's L/R strap inside the ground ring.

    Pad 2 sits inside the ring of ground pads with only a 0.40 mm gap around
    it, so it cannot reach a via of its own and it must not consume one of the
    four diagonal corners that pads 1, 3 and 4 need to escape through. It is
    always on the same net as a neighbour it can simply be joined to: ground
    (pad 6) on even channels, or the supply pad 1 on odd channels.
    """
    count = 0
    for k in range(d.MIC_COUNT):
        ref = f"MK{k + 1}"
        footprint = placed[ref]
        pads = {pad.GetNumber(): pad for pad in footprint.Pads()}
        strap = pads["2"]
        net_name = pin_net[(ref, "2")]
        target = pads["6"] if net_name == "GND" else pads["1"]

        track = pcbnew.PCB_TRACK(board)
        track.SetStart(strap.GetPosition())
        track.SetEnd(target.GetPosition())
        track.SetWidth(mm(0.15))
        track.SetLayer(pcbnew.F_Cu)
        track.SetNet(net_items[net_name])
        board.Add(track)
        count += 1
    return count


def place_ground_stitching(board, placed, pin_net, net_items):
    """Give every ground pad its own via into the inner planes.

    The via is pushed straight out from the footprint centre past the pad edge,
    and a short track ties the pad to it on the pad's own copper layer.
    """
    gnd = net_items["GND"]
    count = 0

    # Every pad on the board, so a stitching via never lands on a neighbour.
    obstacles = []
    for other_ref, other in placed.items():
        for pad in other.Pads():
            size = pad.GetSize()
            obstacles.append((pad.GetPosition(),
                              math.hypot(size.x, size.y) / 2.0,
                              pin_net.get((other_ref, pad.GetNumber()))))
    vias_placed = []

    for ref, footprint in sorted(placed.items()):
        on_bottom = footprint.IsFlipped()
        for pad in footprint.Pads():
            if pin_net.get((ref, pad.GetNumber())) != "GND":
                continue
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                continue  # plated holes already reach both planes
            if ref.startswith("MK") and pad.GetNumber() == "2":
                continue  # L/R strap: linked to the ground ring instead

            position = pad.GetPosition()
            override = (MIC_GND_VIAS.get(pad.GetNumber())
                        if ref.startswith("MK") else None)
            if override is not None:
                target = local_to_board(footprint, *override)
            elif ref in POWER_ROW_REFS:
                # Push the via straight down, away from the supply bus that
                # runs above the row.
                target = pcbnew.VECTOR2I(position.x, position.y + mm(1.45))
            elif ref.startswith("CM"):
                # Per-channel decoupling capacitor: push the via straight in
                # towards the board centre. The generic axis search can pick a
                # tangential direction here, which lays the via and its track
                # across the microphone's data escape running past it.
                centre_x, centre_y = mm(d.PAGE_CX), mm(d.PAGE_CY)
                dx = centre_x - position.x
                dy = centre_y - position.y
                length = math.hypot(dx, dy)
                step = mm(1.05) / length
                target = pcbnew.VECTOR2I(int(position.x + dx * step),
                                         int(position.y + dy * step))
            else:
                target = choose_stitch_position(pad, footprint, position,
                                                obstacles, vias_placed)
            if target is None:
                continue
            vias_placed.append(target)

            via = pcbnew.PCB_VIA(board)
            via.SetPosition(target)
            via.SetWidth(mm(VIA_DIAMETER))
            via.SetDrill(mm(VIA_DRILL))
            via.SetNet(gnd)
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            # Tented both sides: these are routing vias for the plugged-via
            # process, and leaving the mask open would also clip silkscreen.
            via.SetFrontTentingMode(pcbnew.TENTING_MODE_TENTED)
            via.SetBackTentingMode(pcbnew.TENTING_MODE_TENTED)
            board.Add(via)

            track = pcbnew.PCB_TRACK(board)
            track.SetStart(position)
            track.SetEnd(target)
            track.SetWidth(mm(0.3))
            track.SetLayer(pcbnew.B_Cu if on_bottom else pcbnew.F_Cu)
            track.SetNet(gnd)
            board.Add(track)
            count += 1
    return count


def add_silkscreen(board):
    """Channel numbers, cardinal marks and board identity."""
    def text(value, x, y, size=1.2, layer=pcbnew.F_SilkS, angle=0.0,
             thickness=0.16, mirrored=False):
        item = pcbnew.PCB_TEXT(board)
        item.SetText(value)
        item.SetPosition(vec(x, y))
        item.SetLayer(layer)
        item.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        item.SetTextThickness(mm(thickness))
        item.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        item.SetTextAngleDegrees(angle)
        item.SetMirrored(mirrored)
        board.Add(item)

    # Channel numbers sit just inside the rim. They are deliberately left
    # unrotated: KiCad bounds text with an axis-aligned box, so tangential
    # labels would claim far more room than their glyphs occupy and collide
    # with the microphone pads.
    for k in range(d.MIC_COUNT):
        lx, ly = d.polar(57.8, d.mic_angle(k))
        kx, ky = d.to_kicad(lx, ly)
        text(f"CH{k}", kx, ky, size=1.1, thickness=0.15)

    # Axis marks live in the clear band between the two socket rows.
    text("+X", *d.to_kicad(30.0, 0.0), size=1.4)
    text("-X", *d.to_kicad(-16.0, 0.0), size=1.4)

    # Short legend for each test point, pushed radially outward from its pad.
    for _ref, _net, radius, angle, label in d.TEST_POINTS:
        lx, ly = d.polar(radius + 2.5, angle)
        text(label, *d.to_kicad(lx, ly), size=1.0, thickness=0.15)

    text("16-CH PDM MIC ARRAY  rev A", *d.to_kicad(0.0, 18.0), size=1.4)
    text("PORTS FACE UP - DO NOT WASH", *d.to_kicad(0.0, 15.5), size=1.2)
    text("CH0..CH15 CCW FROM +X", *d.to_kicad(0.0, 20.5), size=1.2)

    # The module and host connector are on the reverse, so label them there.
    text("TANG NANO 9K - USB-C THIS END", d.PAGE_CX + 24.0, d.PAGE_CY,
         size=1.4, layer=pcbnew.B_SilkS, mirrored=True)
    text("RPi P1 26-WAY - PIN 1 MARKED", d.PAGE_CX, d.PAGE_CY + 17.5,
         size=1.4, layer=pcbnew.B_SilkS, mirrored=True)


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    path, comps, nets, stitches, straps = build(
        root, with_escapes="--no-escapes" not in sys.argv)
    print(f"wrote {path}")
    print(f"components {comps}  nets {nets}  ground stitching vias {stitches}  "
          f"microphone straps {straps}")
