"""Is there anywhere for these vias to go?

The guarded mover pushed each via straight away from the aperture it fouls and
KiCad rejected all 22 moves. That only proves one direction is blocked. This
searches the whole neighbourhood of each via geometrically - every direction,
several distances - and reports whether any position exists that satisfies the
mask target and the copper, hole and drill clearances at once.

The answer decides the engineering: if positions exist, the mover needs a
better search. If they do not, no amount of searching helps and the choice is
between re-routing the area and specifying a filled/capped via process.

    python tools/via_relief_feasibility.py
"""

from __future__ import annotations

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

BOARD = os.path.join(HERE, "microphone_array_v2.kicad_pcb")
MANIFEST = os.path.join(HERE, "verification", "boards", "live.json")

DIRECTIONS = 36
RADII_MM = [round(0.10 + 0.05 * i, 2) for i in range(15)]   # 0.10 .. 0.80
IU = 1e6


def board_rules(board):
    """The clearances KiCad will actually enforce, not the board minimum.

    `m_MinClearance` is the floor beneath which no net class may go - 0.127 mm
    here - and using it as *the* clearance is how an earlier version of this
    search proposed eleven positions that KiCad then rejected, every one with
    the same two clearance and two hole-clearance violations. The binding
    number is the widest net-class clearance on the board, because a candidate
    position has to satisfy whichever net it ends up next to.
    """
    import json as _json
    settings = board.GetDesignSettings()
    clearance = settings.m_MinClearance / IU
    project = os.path.join(HERE, "microphone_array_v2.kicad_pro")
    try:
        with open(project, encoding="utf-8") as fh:
            classes = _json.load(fh)["net_settings"]["classes"]
        declared = [c["clearance"] for c in classes if c.get("clearance")]
        if declared:
            clearance = max(declared)
    except (OSError, ValueError, KeyError):
        pass
    return {
        "clearance": clearance,
        "hole_to_hole": settings.m_HoleToHoleMin / IU,
        "hole_clearance": settings.m_HoleClearance / IU,
    }


def collect(board, survey):
    """Foreign copper by net, plus every hole on the board."""
    copper = []          # (net, shape)
    holes = []           # (x, y, radius, owner)
    for entry in survey.pads:
        for shape in entry["copper"].values():
            copper.append((entry["net"], shape))
        if entry.get("drill_mm"):
            pos = entry["pad_obj"].GetPosition()
            holes.append((pos.x / IU, pos.y / IU,
                          entry["drill_mm"] / 2.0, entry["label"]))
    for track in board.Tracks():
        net = track.GetNetname()
        if isinstance(track, pcbnew.PCB_VIA):
            # PCB_VIA.GetWidth() needs a layer: a via may be a different
            # diameter on different layers.
            pos = track.GetPosition()
            radius = track.GetWidth(pcbnew.F_Cu) / IU / 2.0
            copper.append((net, Point(pos.x / IU, pos.y / IU).buffer(
                radius, quad_segs=24)))
            holes.append((pos.x / IU, pos.y / IU,
                          track.GetDrill() / IU / 2.0, "via"))
            continue
        start_pt, end_pt = track.GetStart(), track.GetEnd()
        half = track.GetWidth() / IU / 2.0
        line = LineString([(start_pt.x / IU, start_pt.y / IU),
                           (end_pt.x / IU, end_pt.y / IU)])
        copper.append((net, line.buffer(half, cap_style=1, quad_segs=12)))
    return copper, holes


class Index:
    """Neighbour lookup. Without this the search is O(positions x board) and
    does not finish."""

    def __init__(self, copper, apertures, holes):
        self.copper_nets = [net for net, _shape in copper]
        self.copper_shapes = [shape for _net, shape in copper]
        self.copper_tree = STRtree(self.copper_shapes)
        self.aperture_shapes = list(apertures)
        self.aperture_tree = STRtree(self.aperture_shapes)
        self.holes = holes


def feasible(via, x, y, index, rules, target):
    annulus = Point(x, y).buffer(via.pad_radius, quad_segs=24)
    hole = Point(x, y).buffer(via.drill_radius, quad_segs=16)
    probe = annulus.buffer(max(target, rules["clearance"]) + 0.01)

    for i in index.aperture_tree.query(probe):
        if annulus.distance(index.aperture_shapes[int(i)]) < target:
            return False
    for i in index.copper_tree.query(probe):
        i = int(i)
        if index.copper_nets[i] == via.net:
            continue
        shape = index.copper_shapes[i]
        if annulus.distance(shape) < rules["clearance"]:
            return False
        if hole.distance(shape) < rules["hole_clearance"]:
            return False
    for hx, hy, radius, _owner in index.holes:
        gap = math.hypot(hx - x, hy - y)
        if gap < 1e-9:
            continue                                     # the via itself
        if gap - radius - via.drill_radius < rules["hole_to_hole"]:
            return False
    return True


def main():
    manifest = Manifest(MANIFEST)
    profile = manifest.geometry_profile()
    geom.configure(profile.tolerance("polygon_chord_error_mm").value)
    target = manifest.get("via_mask.design_target_mm")
    process = manifest.get("via_mask.process.limit_mm")

    board = pcbnew.LoadBoard(BOARD)
    survey = geom.BoardGeometry(
        board, contact_tolerance_mm=profile.tolerance("contact_mm").value)
    rules = board_rules(board)
    print("board minimums: clearance {clearance:.3f} mm, hole-to-hole "
          "{hole_to_hole:.3f} mm, hole clearance {hole_clearance:.3f} mm"
          .format(**rules))

    apertures = [shape for side in ("front", "back")
                 for _entry, shape in survey.mask_openings(side)]
    copper, holes = collect(board, survey)
    index = Index(copper, apertures, holes)
    print("indexed {} copper shapes, {} holes, {} mask apertures\n"
          .format(len(copper), len(holes), len(apertures)))

    stuck, movable = [], []
    for via in survey.vias:
        worst = None
        for side in ("front", "back"):
            report = survey.via_mask_report(via, side)
            if report and report.get("annulus_to_opening_mm") is not None:
                gap = report["annulus_to_opening_mm"]
                if worst is None or gap < worst[0]:
                    worst = (gap, report)
        if worst is None or worst[0] > 0.0:
            continue                                     # only the overlaps
        found = None
        for radius in RADII_MM:
            for step in range(DIRECTIONS):
                angle = 2 * math.pi * step / DIRECTIONS
                x = via.x + radius * math.cos(angle)
                y = via.y + radius * math.sin(angle)
                if feasible(via, x, y, index, rules, target):
                    found = (radius, math.degrees(angle), x, y)
                    break
            if found:
                break
        record = {"net": via.net, "pad": worst[1].get("pad"), "found": found}
        (movable if found else stuck).append(record)

    print("vias whose annulus overlaps an aperture: {}".format(
        len(stuck) + len(movable)))
    print("  a clear position exists : {}".format(len(movable)))
    print("  boxed in completely     : {}".format(len(stuck)))
    if movable:
        print("\nmovable:")
        for row in movable:
            radius, angle, _x, _y = row["found"]
            print("  net {:<14} pad {:<9} {:.2f} mm at {:.0f} deg".format(
                row["net"][:14], str(row["pad"]), radius, angle))
    if stuck:
        print("\nno position within {:.2f} mm satisfies target {:.2f} mm "
              "(process limit {:.2f} mm):".format(
                  RADII_MM[-1], target, process))
        for row in stuck:
            print("  net {:<14} pad {}".format(row["net"][:14], row["pad"]))


if __name__ == "__main__":
    main()
