"""Bring ground vias inside the mask keep-outs back into legality.

The signal reroute is already compliant: every via KiCad Routing Tools placed
clears the 0.40 mm mask target. What remains are ground vias placed by
tools/gen_pcb.py, which used a smaller clearance of its own.

They are not interchangeable, so they are classified before anything is
touched:

  free      no track attached and no signal transition nearby - pure plane
            stitching. Deleting one and putting a fresh one somewhere legal
            costs nothing.
  bearing   a track is attached: the via carries a pad or a decoupling stub to
            the plane. A replacement has to exist and be connected before the
            original can go.
  return    no track, but a signal via is close by: the ground via is the
            return path for that layer transition. It has to stay close to the
            signal via it serves, or the return current has nowhere to go.

Nothing is dragged. A via with copper attached is replaced, and its short local
stub re-drawn to the new position; the whole ground net is never ripped up.

    python tools/legalize_gnd_vias.py BOARD              # classify only
    python tools/legalize_gnd_vias.py BOARD --apply
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "verification"))

import pcbnew                                            # noqa: E402
from shapely.geometry import LineString, Point           # noqa: E402
from shapely.strtree import STRtree                      # noqa: E402

from pcbqa import geom                                   # noqa: E402
from pcbqa.core import Manifest                          # noqa: E402

MANIFEST = os.path.join(HERE, "verification", "boards", "live.json")
IU = 1e6

# A ground via this close to a signal via is serving that transition.
RETURN_PATH_RADIUS_MM = 2.5
# How far a replacement may sit from the via it replaces.
# Out to 5 mm: a ground stitching via has no fixed home, and the ones in the
# host block between the module socket and the header need the room. The stub
# is re-drawn to wherever it lands, so distance costs only a little copper.
SEARCH_RADII_MM = [round(0.15 + 0.05 * i, 2) for i in range(98)]
DIRECTIONS = 48
# A return via must stay within this of the signal via it serves.
RETURN_KEEP_WITHIN_MM = 3.0
# The routing policy forbids track fragments below this length; an elbow
# whose short leg falls under it trades a via problem for a sliver.
MIN_SEGMENT_MM = 0.25


def to_mm(value):
    return value / IU


class Space:
    """Clearance model for candidate via positions."""

    def __init__(self, board, survey, manifest, exclude_positions=()):
        profile = manifest.geometry_profile()
        self.target = manifest.get("via_mask.design_target_mm")
        # KiCad enforces the LARGER of the two nets' class clearances, so a
        # single board-wide maximum is wrong in both directions: it blocks
        # legal positions next to a 0.15 mm class and would permit illegal
        # ones next to 0.25 mm. Resolve each net to its class instead.
        import fnmatch
        with open(os.path.join(HERE, "microphone_array_v2.kicad_pro"),
                  encoding="utf-8") as fh:
            settings_doc = json.load(fh)["net_settings"]
        by_class = {c["name"]: c.get("clearance")
                    for c in settings_doc["classes"] if c.get("clearance")}
        patterns = settings_doc.get("netclass_patterns") or []
        default = by_class.get("Default", 0.2)

        def clearance_of(net):
            for rule in patterns:
                if fnmatch.fnmatch(net, rule.get("pattern", "")):
                    return by_class.get(rule.get("netclass"), default)
            return default

        self.clearance_of = clearance_of
        self.own_clearance = clearance_of("GND")
        settings = board.GetDesignSettings()
        self.clearance = max(by_class.values()) if by_class else 0.25
        self.hole_to_hole = settings.m_HoleToHoleMin / IU
        self.hole_clearance = settings.m_HoleClearance / IU

        self.apertures = [shape for side in ("front", "back")
                          for _entry, shape in survey.mask_openings(side)]
        self.aperture_tree = STRtree(self.apertures)

        skip = {(round(x, 4), round(y, 4)) for x, y in exclude_positions}
        copper, holes = [], []
        for entry in survey.pads:
            for shape in entry["copper"].values():
                copper.append((entry["net"], shape))
            if entry.get("drill_mm"):
                pos = entry["pad_obj"].GetPosition()
                holes.append((to_mm(pos.x), to_mm(pos.y),
                              entry["drill_mm"] / 2.0))
        for track in board.Tracks():
            net = track.GetNetname()
            if isinstance(track, pcbnew.PCB_VIA):
                pos = track.GetPosition()
                key = (round(to_mm(pos.x), 4), round(to_mm(pos.y), 4))
                if key in skip:
                    continue                       # this one is going away
                radius = track.GetWidth(pcbnew.F_Cu) / IU / 2.0
                copper.append((net, Point(to_mm(pos.x), to_mm(pos.y)).buffer(
                    radius, quad_segs=16)))
                holes.append((to_mm(pos.x), to_mm(pos.y),
                              track.GetDrill() / IU / 2.0))
                continue
            start, end = track.GetStart(), track.GetEnd()
            half = track.GetWidth() / IU / 2.0
            copper.append((net, LineString(
                [(to_mm(start.x), to_mm(start.y)),
                 (to_mm(end.x), to_mm(end.y))]
            ).buffer(half, cap_style=1, quad_segs=8)))
        self.copper_nets = [n for n, _s in copper]
        self.copper_shapes = [s for _n, s in copper]
        self.copper_tree = STRtree(self.copper_shapes)
        self.holes = holes

    def via_ok(self, x, y, pad_radius, drill_radius, net):
        annulus = Point(x, y).buffer(pad_radius, quad_segs=20)
        hole = Point(x, y).buffer(drill_radius, quad_segs=12)
        probe = annulus.buffer(max(self.target, self.clearance) + 0.01)
        for i in self.aperture_tree.query(probe):
            if annulus.distance(self.apertures[int(i)]) < self.target:
                return False
        for i in self.copper_tree.query(probe):
            i = int(i)
            other = self.copper_nets[i]
            if other == net:
                continue
            required = max(self.own_clearance, self.clearance_of(other))
            if annulus.distance(self.copper_shapes[i]) < required:
                return False
            if hole.distance(self.copper_shapes[i]) < self.hole_clearance:
                return False
        for hx, hy, radius in self.holes:
            gap = math.hypot(hx - x, hy - y)
            if gap < 1e-9:
                continue
            if gap - radius - drill_radius < self.hole_to_hole:
                return False
        return True

    def track_ok(self, ax, ay, bx, by, width, net):
        """A stub from (ax,ay) to (bx,by) must not crowd another net."""
        shape = LineString([(ax, ay), (bx, by)]).buffer(
            width / 2.0, cap_style=1, quad_segs=8)
        probe = shape.buffer(self.clearance + 0.01)
        for i in self.copper_tree.query(probe):
            i = int(i)
            other = self.copper_nets[i]
            if other == net:
                continue
            required = max(self.own_clearance, self.clearance_of(other))
            if shape.distance(self.copper_shapes[i]) < required:
                return False
        return True


def classify(board, survey, manifest):
    """Split the offending ground vias into the three kinds."""
    target = manifest.get("via_mask.design_target_mm")
    vias = [t for t in board.Tracks() if isinstance(t, pcbnew.PCB_VIA)]
    tracks = [t for t in board.Tracks() if not isinstance(t, pcbnew.PCB_VIA)]
    by_geom = {(round(v.x, 4), round(v.y, 4)): v for v in survey.vias}

    rows = []
    for via in vias:
        pos = via.GetPosition()
        key = (round(to_mm(pos.x), 4), round(to_mm(pos.y), 4))
        entry = by_geom.get(key)
        if entry is None or via.GetNetname() != "GND":
            continue
        worst = None
        for side in ("front", "back"):
            report = survey.via_mask_report(entry, side)
            if report and report.get("annulus_to_opening_mm") is not None:
                gap = report["annulus_to_opening_mm"]
                if worst is None or gap < worst:
                    worst = gap
        if worst is None or worst >= target:
            continue

        attached = []
        for track in tracks:
            if track.GetNetname() != "GND":
                continue
            if track.GetStart() == pos or track.GetEnd() == pos:
                attached.append(track)

        nearest_signal = None
        for other in vias:
            if other.GetNetname() == "GND":
                continue
            other_pos = other.GetPosition()
            distance = math.hypot(to_mm(other_pos.x - pos.x),
                                  to_mm(other_pos.y - pos.y))
            if nearest_signal is None or distance < nearest_signal[0]:
                nearest_signal = (distance, other)

        # A via with no track can still be load-bearing: if it sits inside a
        # pad of its own net it connects through the pad's copper. TP4 and TP5
        # are exactly this, and calling them "free" and deleting them left both
        # test points unconnected.
        carrying_pad = None
        for entry_pad in survey.pads:
            if entry_pad["net"] != "GND":
                continue
            for shape in entry_pad["copper"].values():
                if shape.distance(Point(to_mm(pos.x), to_mm(pos.y))) <= 0.0:
                    carrying_pad = entry_pad
                    break
            if carrying_pad:
                break

        if attached or carrying_pad is not None:
            kind = "bearing"
        elif nearest_signal and nearest_signal[0] <= RETURN_PATH_RADIUS_MM:
            kind = "return"
        else:
            kind = "free"

        rows.append({
            "via": via, "geom": entry, "kind": kind, "gap": worst,
            "x": to_mm(pos.x), "y": to_mm(pos.y),
            "attached": attached,
            "carrying_pad": carrying_pad,
            "signal_distance": nearest_signal[0] if nearest_signal else None,
            "signal_via": nearest_signal[1] if nearest_signal else None,
        })
    return rows


def paths_45(start, end):
    """Candidate 0/45-degree polylines from `start` to `end`.

    The board's routing policy permits only 0 and 45 degree geometry, so a
    stub cannot simply be a straight line at whatever angle the new via
    happens to sit. Both elbow orders are offered; the caller takes the first
    that clears its neighbours.
    """
    (ax, ay), (bx, by) = start, end
    dx, dy = bx - ax, by - ay
    if abs(abs(dx) - abs(dy)) < 1e-9 or abs(dx) < 1e-9 or abs(dy) < 1e-9:
        return [[start, end]]                       # already 0 or 45
    run = min(abs(dx), abs(dy))
    sx = math.copysign(1.0, dx)
    sy = math.copysign(1.0, dy)
    diagonal_first = [start, (ax + run * sx, ay + run * sy), end]
    if abs(dx) > abs(dy):
        straight_first = [start, (bx - run * sx, ay), end]
    else:
        straight_first = [start, (ax, by - run * sy), end]
    return [diagonal_first, straight_first]


def stub_paths_ok(space, far, spot, width, escape=None):
    """The first permitted 45-degree path from `far` to `spot`.

    A pad in dense copper often has exactly one direction it can leave in - the
    one its original stub used. Two-elbow paths straight from the pad ignore
    that corridor and get rejected on the first segment, which is what left the
    C3 decoupling stub unplaceable. So the original escape direction is offered
    first: step along it, then turn.
    """
    candidates = list(paths_45(far, spot))
    if escape is not None:
        ex, ey = escape
        for step in (0.5, 1.0, 1.5, 2.0):
            waypoint = (far[0] + ex * step, far[1] + ey * step)
            for tail in paths_45(waypoint, spot):
                candidates.append([far] + tail)
    for path in candidates:
        segments = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
        lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segments]
        if any(0.0 < length < MIN_SEGMENT_MM for length in lengths):
            continue                      # would leave a sliver
        if all(space.track_ok(a[0], a[1], b[0], b[1], width, "GND")
               for a, b in segments):
            return [point for point in path]
    return None


def find_spot(space, row, anchor=None, limit=None):
    """A legal position whose stubs can also be re-drawn legally.

    Position and stub are searched together. Checking the via first and the
    stub afterwards rejects a via the moment its nearest legal position has an
    awkward stub, when a slightly further position would have suited both -
    which is what left eighteen of these unplaceable.
    """
    entry = row["geom"]
    for radius in SEARCH_RADII_MM:
        if limit is not None and radius > limit:
            break
        for step in range(DIRECTIONS):
            angle = 2 * math.pi * step / DIRECTIONS
            x = row["x"] + radius * math.cos(angle)
            y = row["y"] + radius * math.sin(angle)
            if anchor is not None:
                if math.hypot(x - anchor[0], y - anchor[1]) > RETURN_KEEP_WITHIN_MM:
                    continue
            if not space.via_ok(x, y, entry.pad_radius, entry.drill_radius,
                                "GND"):
                continue
            stubs = []
            ok = True
            if not row["attached"] and row.get("carrying_pad") is not None:
                # No track to re-draw: make one from the pad it used to sit in.
                pad_pos = row["carrying_pad"]["pad_obj"].GetPosition()
                anchor_xy = (to_mm(pad_pos.x), to_mm(pad_pos.y))
                path = stub_paths_ok(space, anchor_xy, (x, y), 0.3, None)
                if path is None:
                    continue
                stubs.append((None, path))
            for track in row["attached"]:
                start, end = track.GetStart(), track.GetEnd()
                at_start = start == row["via"].GetPosition()
                far = end if at_start else start
                # The direction the original stub left the pad in.
                near = start if at_start else end
                dx = to_mm(near.x - far.x)
                dy = to_mm(near.y - far.y)
                length = math.hypot(dx, dy)
                escape = (dx / length, dy / length) if length > 1e-9 else None
                path = stub_paths_ok(space, (to_mm(far.x), to_mm(far.y)),
                                     (x, y), track.GetWidth() / IU, escape)
                if path is None:
                    ok = False
                    break
                stubs.append((track, path))
            if ok:
                return (x, y, radius, stubs)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("board")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-partial", action="store_true",
                        help="apply what is placeable and report the "
                             "rest, so the pass can be repeated")
    args = parser.parse_args()

    manifest = Manifest(MANIFEST)
    profile = manifest.geometry_profile()
    geom.configure(profile.tolerance("polygon_chord_error_mm").value)
    board = pcbnew.LoadBoard(args.board)
    survey = geom.BoardGeometry(
        board, contact_tolerance_mm=profile.tolerance("contact_mm").value)
    rows = classify(board, survey, manifest)

    counts = {"free": 0, "bearing": 0, "return": 0}
    for row in rows:
        counts[row["kind"]] += 1
    print("offending GND vias: {}".format(len(rows)))
    for kind in ("free", "bearing", "return"):
        print("  {:<8}: {}".format(kind, counts[kind]))
    for row in rows:
        print("    {:<8} at ({:7.3f},{:7.3f}) gap {:.3f} stubs {} "
              "nearest signal via {}".format(
                  row["kind"], row["x"], row["y"], row["gap"],
                  len(row["attached"]),
                  "-" if row["signal_distance"] is None
                  else "{:.2f} mm".format(row["signal_distance"])))
    if not args.apply:
        return 0

    space = Space(board, survey, manifest,
                  exclude_positions=[(r["x"], r["y"]) for r in rows])
    plan, failed = [], []
    for row in rows:
        anchor = None
        limit = None
        if row["kind"] == "return":
            signal = row["signal_via"].GetPosition()
            anchor = (to_mm(signal.x), to_mm(signal.y))
        spot = find_spot(space, row, anchor, limit)
        if spot is None:
            failed.append(row)
            continue
        plan.append((row, spot, spot[3]))

    print("\nplanned {} replacement(s), {} without a legal spot".format(
        len(plan), len(failed)))
    for row in failed:
        print("  no spot: {} at ({:.3f},{:.3f})".format(
            row["kind"], row["x"], row["y"]))
    if failed and not args.allow_partial:
        print("")
        print("refusing to make a partial change")
        return 1

    for row, spot, stubs in plan:
        old = row["via"].GetPosition()
        new = pcbnew.VECTOR2I(pcbnew.FromMM(spot[0]), pcbnew.FromMM(spot[1]))
        replacement = pcbnew.PCB_VIA(board)
        replacement.SetPosition(new)
        replacement.SetWidth(row["via"].GetWidth(pcbnew.F_Cu))
        replacement.SetDrill(row["via"].GetDrill())
        replacement.SetNetCode(row["via"].GetNetCode())
        replacement.SetViaType(row["via"].GetViaType())
        replacement.SetLayerPair(row["via"].TopLayer(), row["via"].BottomLayer())
        board.Add(replacement)
        # Re-draw each stub along a permitted path rather than dragging the
        # old via and its copper into a new position.
        for track, path in stubs:
            if track is None:
                width = pcbnew.FromMM(0.3)
                layer = pcbnew.F_Cu
                netcode = row["via"].GetNetCode()
            else:
                width = track.GetWidth()
                layer = track.GetLayer()
                netcode = track.GetNetCode()
                board.Remove(track)
            for i in range(len(path) - 1):
                segment = pcbnew.PCB_TRACK(board)
                segment.SetStart(pcbnew.VECTOR2I(
                    pcbnew.FromMM(path[i][0]), pcbnew.FromMM(path[i][1])))
                segment.SetEnd(pcbnew.VECTOR2I(
                    pcbnew.FromMM(path[i + 1][0]), pcbnew.FromMM(path[i + 1][1])))
                segment.SetWidth(width)
                segment.SetLayer(layer)
                segment.SetNetCode(netcode)
                board.Add(segment)
        board.Remove(row["via"])

    board.Save(args.board)
    print("\nreplaced {} via(s); saved {}".format(len(plan), args.board))
    return 0


if __name__ == "__main__":
    sys.exit(main())
