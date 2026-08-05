"""Generate via keep-out rule areas around every solder-mask opening.

The board's manufacturability target is 0.40 mm from a via annulus to the
nearest mask aperture, so that an ordinary tented/plugged via is reliably
covered and solder cannot wick down a barrel next to a paste-receiving pad.
Expressing that as a rule the autorouter obeys is better than measuring it
afterwards and moving vias around: a via that was never placed there does not
have to be relieved later.

Each aperture is grown by (target + via radius) and the union is written as
KiCad rule areas with:

    (keepout (tracks allowed) (vias not_allowed) (pads allowed)
             (copperpour allowed) (footprints allowed))

Tracks stay allowed because the router still has to reach the pads; only via
placement is excluded. Copper pour stays allowed so the GND planes on the
inner layers are unaffected.

    python tools/make_via_keepouts.py            # report coverage
    python tools/make_via_keepouts.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "verification"))

import pcbnew                                            # noqa: E402
from shapely.geometry import MultiPolygon, Polygon       # noqa: E402
from shapely.ops import unary_union                      # noqa: E402

from pcbqa import geom                                   # noqa: E402
from pcbqa.core import Manifest                          # noqa: E402

BOARD = os.path.join(HERE, "microphone_array_v2.kicad_pcb")
MANIFEST = os.path.join(HERE, "verification", "boards", "live.json")
GROUP_NAME = "via_mask_keepout"

# Rule areas are simplified to this tolerance so the zone outlines stay a
# sensible size; well below the clearances involved.
SIMPLIFY_MM = 0.01


def smallest_clearance(project_path):
    """The tightest net-class clearance, which sets how much margin the
    router adds outside a rule area of its own accord.

    KiCad Routing Tools blocks a via whose centre is inside the area OR within
    (clearance + via_size/2) of its edge. So the polygon only has to supply the
    remainder: buffering by the full target as well would demand roughly double
    the real requirement and needlessly strangle a dense board.
    """
    with open(project_path, encoding="utf-8") as fh:
        classes = json.load(fh)["net_settings"]["classes"]
    values = [c.get("clearance") for c in classes if c.get("clearance")]
    return min(values) if values else 0.15


def build(board, survey, halo_mm):
    """One merged polygon set per side."""
    per_side = {}
    for side in ("front", "back"):
        shapes = [shape.buffer(halo_mm, quad_segs=8)
                  for _entry, shape in survey.mask_openings(side)]
        if not shapes:
            continue
        merged = unary_union(shapes).simplify(SIMPLIFY_MM)
        if isinstance(merged, Polygon):
            merged = MultiPolygon([merged])
        per_side[side] = merged
    return per_side


def clear_existing(board):
    """Remove rule areas this script previously created."""
    removed = 0
    for zone in list(board.Zones()):
        if zone.GetIsRuleArea() and zone.GetZoneName() == GROUP_NAME:
            board.Remove(zone)
            removed += 1
    return removed


def add_rule_areas(board, per_side):
    layer_for = {"front": pcbnew.F_Cu, "back": pcbnew.B_Cu}
    added = 0
    for side, polygons in per_side.items():
        layers = pcbnew.LSET()
        layers.addLayer(layer_for[side])
        for polygon in polygons.geoms:
            zone = pcbnew.ZONE(board)
            zone.SetIsRuleArea(True)
            zone.SetDoNotAllowTracks(False)       # the router still needs pads
            zone.SetDoNotAllowVias(True)          # the whole point
            zone.SetDoNotAllowPads(False)
            zone.SetDoNotAllowFootprints(False)
            zone.SetDoNotAllowZoneFills(False)    # planes are on inner layers
            zone.SetLayerSet(layers)
            zone.SetZoneName(GROUP_NAME)
            outline = zone.Outline()
            outline.NewOutline()
            for x, y in list(polygon.exterior.coords)[:-1]:
                outline.Append(pcbnew.FromMM(float(x)), pcbnew.FromMM(float(y)))
            for interior in polygon.interiors:
                outline.NewHole()
                for x, y in list(interior.coords)[:-1]:
                    outline.Append(pcbnew.FromMM(float(x)),
                                   pcbnew.FromMM(float(y)),
                                   outline.OutlineCount() - 1,
                                   outline.HoleCount(
                                       outline.OutlineCount() - 1) - 1)
            board.Add(zone)
            added += 1
    return added


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--board", default=BOARD)
    args = parser.parse_args()

    manifest = Manifest(MANIFEST)
    profile = manifest.geometry_profile()
    geom.configure(profile.tolerance("polygon_chord_error_mm").value)
    target = manifest.get("via_mask.design_target_mm")
    clearance = smallest_clearance(
        os.path.join(HERE, "microphone_array_v2.kicad_pro"))
    halo = max(0.0, target - clearance)

    board = pcbnew.LoadBoard(args.board)
    survey = geom.BoardGeometry(
        board, contact_tolerance_mm=profile.tolerance("contact_mm").value)
    per_side = build(board, survey, halo)

    board_area = 0.0
    outline = board.GetBoardEdgesBoundingBox()
    board_area = (outline.GetWidth() / 1e6) * (outline.GetHeight() / 1e6)
    print("mask target {:.2f} mm - tightest net-class clearance {:.2f} mm "
          "= {:.2f} mm polygon halo (the router adds clearance + via radius "
          "outside it)".format(target, clearance, halo))
    for side, polygons in per_side.items():
        print("  {:<5}: {} region(s), {:.1f} mm2 ({:.0f}% of the board bbox)"
              .format(side, len(polygons.geoms), polygons.area,
                      100.0 * polygons.area / board_area))

    if not args.apply:
        print("\nre-run with --apply to write the rule areas")
        return 0

    removed = clear_existing(board)
    added = add_rule_areas(board, per_side)
    board.Save(args.board)
    print("\nreplaced {} previous rule area(s) with {}".format(removed, added))
    print("saved " + args.board)
    return 0


if __name__ == "__main__":
    sys.exit(main())
