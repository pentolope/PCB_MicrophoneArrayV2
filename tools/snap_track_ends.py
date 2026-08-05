"""Snap track endpoints that stop just short of the via they connect to.

KiCad's `track_not_centered_on_via` check is off by default, which is why four
of these survived on this board: a track ends 0.1-0.22 mm from its via centre
instead of on it. The net is still connected - the track overlaps the annulus -
so nothing complains until the fab shifts the drill within its tolerance and
eats into an annulus that was already being entered off-centre.

The fix is to move the endpoint onto the via centre. Nothing else moves, and a
snap is only made when the endpoint is already close enough that it must have
been meant for that via.

    python tools/snap_track_ends.py            # report
    python tools/snap_track_ends.py --apply
"""

from __future__ import annotations

import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "verification"))

import pcbnew                                            # noqa: E402

BOARD = os.path.join(HERE, "microphone_array_v2.kicad_pcb")

# An endpoint further than this from a via centre was aiming at something else.
# Only used to pair a flagged violation with its via; the set of endpoints to
# move comes from KiCad, not from this radius. An earlier version swept up
# every endpoint within the radius - 53 of them, where KiCad objected to 4 -
# and moving the other 49 introduced a tracks_crossing violation. The board
# gets to say which endpoints are wrong.
SNAP_RADIUS_MM = 0.35
IU = 1e6


def to_mm(value):
    return value / IU


def flagged_positions(report_path):
    """The endpoints KiCad actually complained about, from a DRC report."""
    import json
    with open(report_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    wanted = set()
    for violation in doc.get("violations", []):
        if violation.get("type") != "track_not_centered_on_via":
            continue
        for item in violation.get("items", []):
            if item.get("description", "").startswith("Track"):
                pos = item.get("pos") or {}
                wanted.add((round(pos.get("x", 0.0), 4),
                            round(pos.get("y", 0.0), 4)))
    return wanted


def find(board, only=None):
    vias = [t for t in board.Tracks() if isinstance(t, pcbnew.PCB_VIA)]
    tracks = [t for t in board.Tracks() if not isinstance(t, pcbnew.PCB_VIA)]
    snaps = []
    for track in tracks:
        for which, getter in (("start", track.GetStart), ("end", track.GetEnd)):
            point = getter()
            for via in vias:
                if via.GetNetname() != track.GetNetname():
                    continue
                centre = via.GetPosition()
                if centre == point:
                    continue
                distance = math.hypot(to_mm(centre.x - point.x),
                                      to_mm(centre.y - point.y))
                if only is not None and (round(to_mm(point.x), 4),
                                         round(to_mm(point.y), 4)) not in only:
                    continue
                if distance <= SNAP_RADIUS_MM:
                    snaps.append({
                        "track": track, "which": which, "via": via,
                        "net": track.GetNetname(), "distance": distance,
                        "from": (to_mm(point.x), to_mm(point.y)),
                        "to": (to_mm(centre.x), to_mm(centre.y)),
                    })
                    break
    return snaps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--board", default=BOARD)
    parser.add_argument("--from-drc", default=None,
                        help="only snap endpoints this DRC report flagged")
    args = parser.parse_args()

    board = pcbnew.LoadBoard(args.board)
    only = flagged_positions(args.from_drc) if args.from_drc else None
    snaps = find(board, only)
    print("off-centre track endpoints within {:.2f} mm of a same-net via: {}"
          .format(SNAP_RADIUS_MM, len(snaps)))
    for snap in snaps:
        print("  {:.4f} mm  net {:<14} {} -> {}".format(
            snap["distance"], snap["net"][:14],
            "({:.3f}, {:.3f})".format(*snap["from"]),
            "({:.3f}, {:.3f})".format(*snap["to"])))
    if not args.apply or not snaps:
        if snaps:
            print("\nre-run with --apply to snap them")
        return 0

    for snap in snaps:
        centre = snap["via"].GetPosition()
        if snap["which"] == "start":
            snap["track"].SetStart(centre)
        else:
            snap["track"].SetEnd(centre)
    board.Save(args.board)
    print("\nsnapped {} endpoint(s); saved {}".format(len(snaps), args.board))
    return 0


if __name__ == "__main__":
    sys.exit(main())
