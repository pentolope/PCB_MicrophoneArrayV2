"""Move ground stitching vias clear of the solder-mask keep-outs.

The autorouter obeys the keep-out rule areas, so every signal via it places is
already clear of the 0.40 mm mask target. The ground stitching vias are not its
work: tools/gen_pcb.py places them against its own STITCH_CLEARANCE, which is
smaller, so they are the entire remaining population.

A stitching via has far more freedom than a signal via - it joins one pad to a
plane that exists nearly everywhere - so this searches around each one for a
position that clears every mask aperture by the target and keeps the board's
copper, hole and drill clearances, then moves it and any track endpoint on it.
Candidates are screened geometrically against a spatial index and the whole
batch is checked once with KiCad's DRC, rather than paying a DRC per trial.

    python tools/relocate_stitching.py BOARD [--apply]
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
DIRECTIONS = 48
RADII_MM = [round(0.15 + 0.05 * i, 2) for i in range(28)]   # 0.15 .. 1.50


def rules(board, project):
    settings = board.GetDesignSettings()
    with open(project, encoding="utf-8") as fh:
        classes = json.load(fh)["net_settings"]["classes"]
    clearances = [c["clearance"] for c in classes if c.get("clearance")]
    return {
        "clearance": max(clearances) if clearances else 0.25,
        "hole_to_hole": settings.m_HoleToHoleMin / IU,
        "hole_clearance": settings.m_HoleClearance / IU,
    }


def collect(board, survey):
    copper, holes = [], []
    for entry in survey.pads:
        for shape in entry["copper"].values():
            copper.append((entry["net"], shape))
        if entry.get("drill_mm"):
            pos = entry["pad_obj"].GetPosition()
            holes.append((pos.x / IU, pos.y / IU, entry["drill_mm"] / 2.0))
    for track in board.Tracks():
        net = track.GetNetname()
        if isinstance(track, pcbnew.PCB_VIA):
            pos = track.GetPosition()
            radius = track.GetWidth(pcbnew.F_Cu) / IU / 2.0
            copper.append((net, Point(pos.x / IU, pos.y / IU).buffer(
                radius, quad_segs=16)))
            holes.append((pos.x / IU, pos.y / IU, track.GetDrill() / IU / 2.0))
            continue
        start, end = track.GetStart(), track.GetEnd()
        half = track.GetWidth() / IU / 2.0
        copper.append((net, LineString(
            [(start.x / IU, start.y / IU), (end.x / IU, end.y / IU)]
        ).buffer(half, cap_style=1, quad_segs=8)))
    return copper, holes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("board")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    manifest = Manifest(MANIFEST)
    profile = manifest.geometry_profile()
    geom.configure(profile.tolerance("polygon_chord_error_mm").value)
    target = manifest.get("via_mask.design_target_mm")

    board = pcbnew.LoadBoard(args.board)
    survey = geom.BoardGeometry(
        board, contact_tolerance_mm=profile.tolerance("contact_mm").value)
    limits = rules(board, os.path.join(HERE, "microphone_array_v2.kicad_pro"))
    apertures = [shape for side in ("front", "back")
                 for _entry, shape in survey.mask_openings(side)]
    aperture_tree = STRtree(apertures)
    copper, holes = collect(board, survey)
    copper_nets = [n for n, _s in copper]
    copper_shapes = [s for _n, s in copper]
    copper_tree = STRtree(copper_shapes)

    def clear(via, x, y):
        annulus = Point(x, y).buffer(via.pad_radius, quad_segs=20)
        hole = Point(x, y).buffer(via.drill_radius, quad_segs=12)
        probe = annulus.buffer(max(target, limits["clearance"]) + 0.01)
        for i in aperture_tree.query(probe):
            if annulus.distance(apertures[int(i)]) < target:
                return False
        for i in copper_tree.query(probe):
            i = int(i)
            if copper_nets[i] == via.net:
                continue
            if annulus.distance(copper_shapes[i]) < limits["clearance"]:
                return False
            if hole.distance(copper_shapes[i]) < limits["hole_clearance"]:
                return False
        for hx, hy, radius in holes:
            gap = math.hypot(hx - x, hy - y)
            if gap < 1e-9:
                continue
            if gap - radius - via.drill_radius < limits["hole_to_hole"]:
                return False
        return True

    moves, stuck = [], []
    for via in survey.vias:
        worst = None
        for side in ("front", "back"):
            report = survey.via_mask_report(via, side)
            if report and report.get("annulus_to_opening_mm") is not None:
                gap = report["annulus_to_opening_mm"]
                if worst is None or gap < worst:
                    worst = gap
        if worst is None or worst >= target:
            continue
        found = None
        for radius in RADII_MM:
            for step in range(DIRECTIONS):
                angle = 2 * math.pi * step / DIRECTIONS
                x = via.x + radius * math.cos(angle)
                y = via.y + radius * math.sin(angle)
                if clear(via, x, y):
                    found = (x, y, radius)
                    break
            if found:
                break
        (moves if found else stuck).append((via, worst, found))

    print("vias under the {:.2f} mm target: {}".format(
        target, len(moves) + len(stuck)))
    print("  relocatable : {}".format(len(moves)))
    print("  boxed in    : {}".format(len(stuck)))
    for via, gap, _f in stuck[:10]:
        print("    net {:<10} at ({:.2f}, {:.2f}) gap {:.3f}".format(
            via.net[:10], via.x, via.y, gap))
    if not args.apply or not moves:
        return 0

    lookup = {(round(v.x, 4), round(v.y, 4)): (x, y)
              for v, _g, (x, y, _r) in moves}
    live = pcbnew.LoadBoard(args.board)
    vias = [t for t in live.Tracks() if isinstance(t, pcbnew.PCB_VIA)]
    tracks = [t for t in live.Tracks() if not isinstance(t, pcbnew.PCB_VIA)]
    moved = 0
    for via in vias:
        pos = via.GetPosition()
        key = (round(pos.x / IU, 4), round(pos.y / IU, 4))
        if key not in lookup:
            continue
        x, y = lookup[key]
        new = pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
        old = pcbnew.VECTOR2I(pos.x, pos.y)
        via.SetPosition(new)
        for track in tracks:
            if track.GetStart() == old:
                track.SetStart(new)
            if track.GetEnd() == old:
                track.SetEnd(new)
        moved += 1
    live.Save(args.board)
    print("\nmoved {} via(s); saved {}".format(moved, args.board))
    return 0


if __name__ == "__main__":
    sys.exit(main())
