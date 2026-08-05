"""Measure how far each via would have to move to clear the mask openings.

Reads the board with the verification package's own geometry code, so the
numbers here are the numbers the validator gates against - there is no second
opinion about what "0.35 mm to the nearest opening" means.

Usage:
    python tools/survey_via_relief.py [board.kicad_pcb]
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "verification"))

import pcbnew                                            # noqa: E402
from pcbqa import geom                                   # noqa: E402
from pcbqa.core import Manifest                          # noqa: E402

BOARD = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    HERE, "microphone_array_v2.kicad_pcb")
MANIFEST = os.path.join(HERE, "verification", "boards", "live.json")


def survey(board_path=BOARD):
    manifest = Manifest(MANIFEST)
    profile = manifest.geometry_profile()
    geom.configure(profile.tolerance("polygon_chord_error_mm").value)
    contact = profile.tolerance("contact_mm").value
    target = manifest.get("via_mask.design_target_mm")
    process = manifest.get("via_mask.process.limit_mm")

    board = pcbnew.LoadBoard(board_path)
    survey = geom.BoardGeometry(board, contact_tolerance_mm=contact)
    rows = []
    for via in survey.vias:
        worst = None
        for side in ("front", "back"):
            entry = survey.via_mask_report(via, side)
            if not entry:
                continue
            distance = entry.get("annulus_to_opening_mm")
            if distance is None:
                continue
            if worst is None or distance < worst[1]:
                worst = (side, distance, entry)
        if worst is None:
            continue
        side, distance, entry = worst
        rows.append({
            "net": via.net, "x": round(via.x, 4), "y": round(via.y, 4),
            "side": side, "gap_mm": round(distance, 4),
            "pad": entry.get("pad"),
            "pad_net": entry.get("pad_net"),
            "centre_inside": entry.get("centre_inside_opening"),
            "need_mm": round(max(0.0, target - distance), 4),
        })
    return rows, target, process


def main():
    rows, target, process = survey()
    failing = [r for r in rows if r["gap_mm"] < target]
    print("vias total          : {}".format(len(rows)))
    print("below target {:.2f} mm : {}".format(target, len(failing)))
    print("below process {:.2f} mm: {}".format(
        process, len([r for r in rows if r["gap_mm"] < process])))
    print("same-net pad         : {}".format(
        len([r for r in failing if r["net"] == r["pad_net"]])))
    print("different-net pad    : {}".format(
        len([r for r in failing if r["net"] != r["pad_net"]])))
    print()
    buckets = [(0.0, 0.05), (0.05, 0.15), (0.15, 0.30), (0.30, 0.50),
               (0.50, 99.0)]
    print("displacement needed to reach the {:.2f} mm target:".format(target))
    for low, high in buckets:
        n = len([r for r in failing if low <= r["need_mm"] < high])
        print("  {:.2f} - {:.2f} mm : {:3d}".format(low, high, n))
    print()
    print("worst 12:")
    for row in sorted(failing, key=lambda r: -r["need_mm"])[:12]:
        print("  need {:.3f} mm  gap {:.3f}  net {:<12} pad {:<9} "
              "centre_inside={}".format(
                  row["need_mm"], row["gap_mm"], row["net"][:12],
                  str(row["pad"]), row["centre_inside"]))


if __name__ == "__main__":
    main()
